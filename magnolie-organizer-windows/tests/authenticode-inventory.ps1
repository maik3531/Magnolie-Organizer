# Synthetic inventory only: no real certificates, native tools or trust-store access.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-signature-inventory-' + [guid]::NewGuid().ToString('N'))
try {
    $build = Join-Path $temp 'build'
    [IO.Directory]::CreateDirectory($build) | Out-Null
    foreach ($name in @('Verify-AuthenticodePayload.ps1', 'Signing.Common.ps1')) {
        $source = Join-Path $PSScriptRoot "../build/$name"
        Copy-Item -LiteralPath $source -Destination $build
        if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath (Join-Path $build $name)).Hash) { throw 'Test source copy changed.' }
    }
    @'
function Invoke-NativeCommand {
    param($FilePath, $ArgumentList)
    if ($FilePath -ne 'mock' -or $ArgumentList.Count -ne 5 -or ($ArgumentList[0..3] -join ' ') -ne 'verify /pa /all /tw') { throw 'Unexpected native command.' }
    if ($global:MagnolieInventoryToolFailure) { throw 'Synthetic verification failure' }
}
'@ | Set-Content -LiteralPath (Join-Path $build 'Release.Common.ps1') -Encoding UTF8
    $global:MagnolieInventorySignatures = @{}
    $global:MagnolieInventoryToolFailure = $false
    function Get-AuthenticodeSignature {
        param($LiteralPath)
        $key = [IO.Path]::GetFullPath($LiteralPath)
        if (-not $global:MagnolieInventorySignatures.ContainsKey($key)) { throw 'Unexpected signature request; real certificate reads forbidden.' }
        return $global:MagnolieInventorySignatures[$key]
    }
    function Add-Fixture($Root, $Name, $Text, $Publisher = 'CN=Product', $Status = 'Valid', $Timestamp = $true) {
        $path = Join-Path $Root $Name
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
        [IO.File]::WriteAllText($path, $Text)
        $global:MagnolieInventorySignatures[[IO.Path]::GetFullPath($path)] = [pscustomobject]@{
            Status = $Status; SignerCertificate = [pscustomobject]@{ Subject = $Publisher; Thumbprint = 'SYNTHETIC' }; TimeStamperCertificate = $Timestamp
        }
        return $path
    }
    $count = 0
    foreach ($case in @('owned-app', 'vendor', 'extensionless', 'text', 'missing-app', 'wrong-publisher', 'setup-helper-publisher', 'missing-timestamp',
        'unsigned-vendor', 'receipt-match', 'receipt-missing', 'invalid-receipt', 'tool-failure', 'malformed-executable')) {
        $work = Join-Path $temp $case
        $root = Join-Path $work 'payload'
        [IO.Directory]::CreateDirectory($root) | Out-Null
        $report = Join-Path $work 'report.json'
        $global:MagnolieInventorySignatures.Clear()
        $global:MagnolieInventoryToolFailure = $case -eq 'tool-failure'
        $expected = $case -in @('owned-app', 'vendor', 'extensionless', 'text', 'receipt-match')
        if ($case -ne 'missing-app') {
            $publisher = if ($case -eq 'wrong-publisher') { 'CN=Other' } else { 'CN=Product' }
            $null = Add-Fixture $root 'Magnolie Organizer.exe' ('MZsynthetic-app-' + $case) $publisher 'Valid' ($case -ne 'missing-timestamp')
        }
        if ($case -eq 'vendor') { $null = Add-Fixture $root 'vendor/Vendor.dll' 'MZsynthetic-vendor' 'CN=Vendor' }
        if ($case -eq 'setup-helper-publisher') { $null = Add-Fixture $root 'Magnolie.PhoneAudioSetup.x64.exe' 'MZsynthetic-setup-helper' 'CN=Vendor' }
        if ($case -eq 'extensionless') { $null = Add-Fixture $root 'vendor/extensionless' 'MZsynthetic-extensionless' 'CN=Vendor' }
        if ($case -eq 'text') { [IO.File]::WriteAllText((Join-Path $root 'data.txt'), 'Plain text; no signature query allowed.') }
        if ($case -eq 'unsigned-vendor') { $null = Add-Fixture $root 'Unsigned.dll' 'MZsynthetic-unsigned' 'CN=Vendor' 'NotSigned' }
        if ($case -eq 'malformed-executable') { $null = Add-Fixture $root 'broken.dll' 'not-a-PE' 'CN=Vendor' 'NotSigned' }
        $parameters = @{ Root = $root; Publisher = 'CN=Product'; SignTool = 'mock'; Report = $report }
        if ($case -in @('receipt-match', 'receipt-missing', 'invalid-receipt')) {
            $receipt = Join-Path $work 'receipt.json'
            $hash = '0' * 64
            if ($case -eq 'receipt-match') { $hash = (Get-FileHash -LiteralPath (Add-Fixture $root 'nested/uninstaller.bin' 'MZsynthetic-uninstaller')).Hash }
            if ($case -eq 'invalid-receipt') { $hash = 'invalid-hash' }
            @{ sha256 = $hash } | ConvertTo-Json | Set-Content -LiteralPath $receipt
            $parameters.UninstallerReceipt = $receipt
        }
        $passed = $true
        try { & (Join-Path $build 'Verify-AuthenticodePayload.ps1') @parameters } catch { $passed = $false }
        if ($passed -ne $expected) { throw "Inventory result mismatch: $case" }
        if ($case -ne 'invalid-receipt') {
            $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
            if ($result.schema -ne 'magnolie-authenticode-v1' -or $result.passed -ne $expected) { throw "Report mismatch: $case" }
            if ($case -eq 'vendor' -and @($result.files | Where-Object { $_.role -eq 'third-party' -and $_.publisher -eq 'CN=Vendor' }).Count -ne 1) { throw 'Vendor identity lost.' }
            if ($case -eq 'extensionless' -and @($result.files | Where-Object { $_.path -eq 'vendor/extensionless' }).Count -ne 1) { throw 'Extensionless MZ omitted.' }
            if ($case -eq 'text' -and @($result.files).Count -ne 1) { throw 'Plain text inventoried as executable.' }
            if ($case -eq 'receipt-match' -and @($result.files | Where-Object { $_.path -eq 'nested/uninstaller.bin' -and $_.role -eq 'product' }).Count -ne 1) { throw 'Uninstaller receipt not bound.' }
        }
        $count++
    }
    Write-Host "$count synthetic inventory cases passed. Native Authenticode remains untested."
} finally {
    Remove-Variable -Name MagnolieInventorySignatures, MagnolieInventoryToolFailure -Scope Global -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
