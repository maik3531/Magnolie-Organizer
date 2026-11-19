# Synthetic hook contract only: no real DPAPI, signing, NSIS compiler or installer.
param([string]$Case, [string]$InputPath, [string]$Receipt, [string]$Marker, [string]$HookRoot)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if ($Case) {
    $global:MagnolieHookCase = $Case
    $global:MagnolieHookInput = $InputPath
    $global:MagnolieHookMarker = $Marker
    $env:MAGNOLIE_NSIS_SIGN_CONFIG = 'synthetic-config-not-a-real-path'
    $env:MAGNOLIE_NSIS_SIGN_RECEIPT = $Receipt
    & (Join-Path $HookRoot 'Sign-NsisUninstaller.ps1') -Path $InputPath
    exit $LASTEXITCODE
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-nsis-hook-' + [guid]::NewGuid().ToString('N'))
try {
    $hookRoot = Join-Path $temp 'hook'
    [IO.Directory]::CreateDirectory($hookRoot) | Out-Null
    $source = Join-Path $PSScriptRoot '../build/Sign-NsisUninstaller.ps1'
    $hook = Join-Path $hookRoot 'Sign-NsisUninstaller.ps1'
    Copy-Item -LiteralPath $source -Destination $hook
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $hook).Hash) { throw 'Hook source copy changed.' }
    @'
function Import-Clixml {
    param($LiteralPath)
    if ($global:MagnolieHookCase -eq 'missing-config') { throw 'SYNTHETIC-SECRET missing config' }
    if ($LiteralPath -ne 'synthetic-config-not-a-real-path') { throw 'Real configuration reads forbidden.' }
    $text = if ($global:MagnolieHookCase -eq 'invalid-config') { '{SYNTHETIC-SECRET-invalid' }
        else { '{"MAGNOLIE_SIGN_PUBLISHER":"CN=Synthetic","MAGNOLIE_SIGN_PASSWORD":"SYNTHETIC-SECRET"}' }
    $value = [Security.SecureString]::new()
    foreach ($ch in $text.ToCharArray()) { $value.AppendChar($ch) }
    return $value
}
'@ | Set-Content -LiteralPath (Join-Path $hookRoot 'Release.Common.ps1') -Encoding UTF8
    @'
function Sign-Official {
    param($Path)
    if (-not $official -or $script:signingConfiguration['MAGNOLIE_SIGN_PUBLISHER'] -ne 'CN=Synthetic') { throw 'Wrong synthetic config.' }
    if ($env:MAGNOLIE_NSIS_SIGN_CONFIG -or $env:MAGNOLIE_NSIS_SIGN_RECEIPT) { throw 'Environment not cleared before callback.' }
    if ($Path -ne $global:MagnolieHookInput) { throw 'Wrong original input path.' }
    [IO.File]::WriteAllText($global:MagnolieHookMarker, 'controlled-sign-callback-only')
    if ($global:MagnolieHookCase -eq 'sign-failure') { throw 'SYNTHETIC-SECRET sign failure' }
}
'@ | Set-Content -LiteralPath (Join-Path $hookRoot 'Signing.Common.ps1') -Encoding UTF8
    $count = 0
    foreach ($caseName in @('success', 'missing-config', 'invalid-config', 'sign-failure', 'missing-input', 'receipt-failure')) {
        $work = Join-Path $temp $caseName
        [IO.Directory]::CreateDirectory($work) | Out-Null
        $inputPath = Join-Path $work 'synthetic-uninstaller.bin'
        if ($caseName -ne 'missing-input') { [IO.File]::WriteAllText($inputPath, 'MZsynthetic-not-executable-' + $caseName) }
        $receiptPath = Join-Path $work 'receipt.json'
        if ($caseName -eq 'receipt-failure') { $receiptPath = Join-Path $work 'missing-directory/receipt.json' }
        $markerPath = Join-Path $work 'callback.txt'
        $info = [Diagnostics.ProcessStartInfo]::new((Get-Process -Id $PID).Path)
        foreach ($arg in @('-NoProfile', '-NonInteractive', '-File', $PSCommandPath, '-Case', $caseName,
            '-InputPath', $inputPath, '-Receipt', $receiptPath, '-Marker', $markerPath, '-HookRoot', $hookRoot)) { $info.ArgumentList.Add($arg) }
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $p = [Diagnostics.Process]::new()
        $p.StartInfo = $info
        try {
            [void]$p.Start()
            $stdout = $p.StandardOutput.ReadToEndAsync()
            $stderr = $p.StandardError.ReadToEndAsync()
            if (-not $p.WaitForExit(10000)) { $p.Kill($true); $p.WaitForExit(); throw 'Owned synthetic hook timeout.' }
            $expected = if ($caseName -eq 'success') { 0 } else { 1 }
            if ($p.ExitCode -ne $expected) { throw "Unexpected hook exit: $caseName ($($p.ExitCode))" }
            if (($stdout.Result + $stderr.Result) -match 'SYNTHETIC-SECRET') { throw 'Hook exposed synthetic configuration.' }
            if ($caseName -eq 'success') {
                $result = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
                if ($result.sha256 -ne (Get-FileHash -LiteralPath $inputPath).Hash) { throw 'Receipt hash changed.' }
            } else {
                if (Test-Path -LiteralPath $receiptPath) { throw 'Failed hook left positive receipt.' }
                if ($stderr.Result -notmatch 'NSIS uninstaller signing/verification failed\.') { throw 'Generic hook error missing.' }
            }
            if ((Test-Path -LiteralPath $markerPath) -ne ($caseName -notin @('missing-config', 'invalid-config'))) { throw 'Hook callback order changed.' }
        } finally { $p.Dispose() }
        $count++
    }
    Write-Host "$count synthetic hook cases passed. Native NSIS/signing remains untested."
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
