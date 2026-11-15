# Real existing NSIS compiler, canonical hook/macro, controlled signing/config
# dependencies ONLY. Never execute an installer/uninstaller or read real keys.
param(
    [Parameter(Mandatory)][string] $Compiler,
    [string] $EvidenceDirectory
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
if (-not $IsWindows -or -not [IO.Path]::IsPathFullyQualified($Compiler) -or -not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'An existing native Windows NSIS compiler is required.' }
if ($EvidenceDirectory) {
    if (-not [IO.Path]::IsPathFullyQualified($EvidenceDirectory) -or (Test-Path -LiteralPath $EvidenceDirectory)) { throw 'Preserve existing evidence; choose a fresh absolute directory.' }
    for ($parent = Get-Item -LiteralPath ([IO.Path]::GetDirectoryName($EvidenceDirectory)); $null -ne $parent; $parent = $parent.Parent) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Evidence cannot use linked directories.' }
    }
    [IO.Directory]::CreateDirectory($EvidenceDirectory) | Out-Null
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-nsis-compiler-' + [guid]::NewGuid().ToString('N'))
try {
    $hookRoot = Join-Path $temp 'hook Prüfung with spaces'
    [IO.Directory]::CreateDirectory($hookRoot) | Out-Null
    $hook = Join-Path $hookRoot 'Sign-NsisUninstaller.ps1'
    $hookSource = Join-Path $PSScriptRoot '../build/Sign-NsisUninstaller.ps1'
    Copy-Item -LiteralPath $hookSource -Destination $hook
    if ((Get-FileHash -LiteralPath $hookSource).Hash -ne (Get-FileHash -LiteralPath $hook).Hash) { throw 'Canonical hook copy changed.' }
    @'
function Import-Clixml {
    param($LiteralPath)
    if ($LiteralPath -ne 'SYNTHETIC-NOT-A-CONFIG-PATH') { throw 'Real configuration reads forbidden.' }
    $value = [Security.SecureString]::new()
    foreach ($ch in '{"MAGNOLIE_SIGN_PUBLISHER":"CN=Synthetic","MAGNOLIE_SIGN_PASSWORD":"SYNTHETIC-SIGNING-SECRET"}'.ToCharArray()) { $value.AppendChar($ch) }
    return $value
}
'@ | Set-Content -LiteralPath (Join-Path $hookRoot 'Release.Common.ps1') -Encoding UTF8
    @'
function Sign-Official {
    param($Path)
    $full = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($env:MAGNOLIE_NSIS_TEST_TEMP).TrimEnd('\') + '\'
    $record = [ordered]@{
        Path = $full; WithinOwnedTemp = $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
        ConfigCleared = (-not $env:MAGNOLIE_NSIS_SIGN_CONFIG -and -not $env:MAGNOLIE_NSIS_SIGN_RECEIPT)
        ConfigKnown = ($official -and $script:signingConfiguration['MAGNOLIE_SIGN_PUBLISHER'] -ceq 'CN=Synthetic')
        InputExists = (Test-Path -LiteralPath $full -PathType Leaf)
    }
    [pscustomobject]$record | ConvertTo-Json | Set-Content -LiteralPath $env:MAGNOLIE_NSIS_TEST_MARKER -Encoding UTF8
    if (-not $record.WithinOwnedTemp -or -not $record.ConfigCleared -or -not $record.ConfigKnown -or -not $record.InputExists) { throw 'Controlled hook boundary rejected.' }
    if ((Get-Item -LiteralPath $full).Length -gt 8 * 1024 * 1024) { throw 'Inert uninstaller exceeds its fixture limit.' }
    if ($env:MAGNOLIE_NSIS_TEST_CASE -eq 'failure') { throw 'SYNTHETIC-SIGNING-SECRET controlled failure' }
    # Opaque overlay mutation only, NOT a certificate or actual signature.
    [IO.File]::AppendAllText($full, "`nMAGNOLIE-INERT-HOOK-TAIL-NOT-A-SIGNATURE`n", [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath $full -Destination $env:MAGNOLIE_NSIS_TEST_COPY
}
'@ | Set-Content -LiteralPath (Join-Path $hookRoot 'Signing.Common.ps1') -Encoding UTF8
    $nsi = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../installer/MagnolieOrganizer.nsi') -Raw
    $match = [regex]::Match($nsi, '(?ms)\A(.*?)^!define ROOT ')
    if (-not $match.Success -or [regex]::Matches($match.Groups[1].Value, '!uninstfinalize').Count -ne 1) { throw 'Canonical NSIS hook prefix is unavailable.' }
    $fixture = $match.Groups[1].Value + @'
Name "Magnolie INERT signature-hook fixture - DO NOT RUN"
OutFile "${FIXTURE_OUTPUT}"
RequestExecutionLevel user
InstallDir "$TEMP\Magnolie-INERT-NEVER-RUN"
Section
  WriteUninstaller "$INSTDIR\fixture-uninstall.exe"
SectionEnd
Section "Uninstall"
  DetailPrint "INERT FIXTURE - NOT A PRODUCT"
SectionEnd
'@
    $project = Join-Path $temp 'inert Prüfung with spaces.nsi'
    $fixture | Set-Content -LiteralPath $project -Encoding utf8BOM
    $count = 0
    foreach ($case in @('success', 'failure')) {
        $work = Join-Path $temp $case
        $compilerTemp = Join-Path $work 'compiler Prüfbereich with spaces'
        [IO.Directory]::CreateDirectory($compilerTemp) | Out-Null
        $output = Join-Path $work 'INERT Prüfung DO NOT RUN.exe'
        $receipt = Join-Path $work 'identity receipt.json'
        $marker = Join-Path $work 'callback.json'
        $copy = Join-Path $work 'exact finalizer input.exe'
        $info = [Diagnostics.ProcessStartInfo]::new($Compiler)
        foreach ($argument in @('-V3', '-WX', '-DOFFICIAL_RELEASE', ('-DSIGNING_HOST=' + (Get-Process -Id $PID).Path),
            "-DSIGNING_SCRIPT=$hook", "-DFIXTURE_OUTPUT=$output", $project)) { $info.ArgumentList.Add($argument) }
        $info.Environment['TEMP'] = $compilerTemp; $info.Environment['TMP'] = $compilerTemp
        $info.Environment['MAGNOLIE_NSIS_SIGN_CONFIG'] = 'SYNTHETIC-NOT-A-CONFIG-PATH'
        $info.Environment['MAGNOLIE_NSIS_SIGN_RECEIPT'] = $receipt
        $info.Environment['MAGNOLIE_NSIS_TEST_CASE'] = $case
        $info.Environment['MAGNOLIE_NSIS_TEST_TEMP'] = $compilerTemp
        $info.Environment['MAGNOLIE_NSIS_TEST_MARKER'] = $marker
        $info.Environment['MAGNOLIE_NSIS_TEST_COPY'] = $copy
        $info.UseShellExecute = $false; $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
        try {
            [void]$process.Start()
            $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(30000)) { $process.Kill($true); $process.WaitForExit(); throw 'Owned NSIS fixture compile timeout.' }
            $message = $stdout.Result + $stderr.Result
            if ($message.Contains('SYNTHETIC-SIGNING-SECRET')) { throw 'Compiler/hook exposed synthetic signing configuration.' }
            if (-not (Test-Path -LiteralPath $marker)) { throw "Canonical NSIS hook was not reached: $case; $message" }
            $record = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
            if (-not $record.WithinOwnedTemp -or -not $record.ConfigCleared -or -not $record.ConfigKnown -or -not $record.InputExists) { throw "Canonical hook crossed its controlled fixture boundary: $($record | ConvertTo-Json -Compress)" }
            if ($case -eq 'success') {
                if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) { throw ('NSIS successful fixture failed: ' + $message) }
                $result = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
                if ($result.sha256 -ne (Get-FileHash -LiteralPath $copy).Hash) { throw 'NSIS callback receipt differs from exact post-callback input.' }
                if ($EvidenceDirectory) {
                    Copy-Item -LiteralPath $output -Destination (Join-Path $EvidenceDirectory 'INERT-setup-DO-NOT-RUN.exe')
                    Copy-Item -LiteralPath $copy -Destination (Join-Path $EvidenceDirectory 'exact-finalizer-input.exe')
                    Copy-Item -LiteralPath $receipt -Destination (Join-Path $EvidenceDirectory 'identity-receipt.json')
                }
            } elseif ($process.ExitCode -eq 0 -or (Test-Path -LiteralPath $receipt) -or $message -notmatch 'NSIS uninstaller signing/verification failed') {
                throw ('NSIS did not propagate the controlled finalizer failure: ' + $message)
            }
        } finally { $process.Dispose() }
        $count++
    }
    Write-Host "$count actual NSIS compiler/hook quoting and failure cases passed with controlled dependencies; no real signing, DPAPI, keys or installer execution."
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
