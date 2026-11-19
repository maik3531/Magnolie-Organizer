# Controlled policy dependencies only. No actual certificates, tools or keys.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-phone-input-signatures-' + [guid]::NewGuid().ToString('N'))
try {
    $build = Join-Path $temp 'build'
    [IO.Directory]::CreateDirectory($build) | Out-Null
    foreach ($name in @('Verify-PhonePayloadInputs.ps1', 'Signing.Common.ps1', 'PhonePayloadSigning.Common.ps1')) {
        $source = Join-Path $PSScriptRoot "../build/$name"
        Copy-Item -LiteralPath $source -Destination $build
        if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath (Join-Path $build $name)).Hash) { throw 'Canonical source copy changed.' }
    }
    @'
function Invoke-NativeCommand {
    param($FilePath, $ArgumentList)
    if ($FilePath -ne 'mock' -or $ArgumentList.Count -ne 5 -or ($ArgumentList[0..3] -join ' ') -ne 'verify /pa /all /tw') { throw 'Non-verification native command rejected.' }
    $global:MagnoliePhoneSignatureCalls++
    if ($global:MagnoliePhoneSignatureCase -eq 'tool-failure') { throw 'Controlled verification failure' }
    if ($global:MagnoliePhoneSignatureCase -eq 'late-tamper') { [IO.File]::AppendAllText($ArgumentList[4], 'changed-during-verification') }
}
'@ | Set-Content -LiteralPath (Join-Path $build 'Release.Common.ps1') -Encoding UTF8
    @'
function Assert-PhonePayloadAuthenticodeEnvelope {
    param($Path)
    if (-not $global:MagnoliePhoneSignaturePaths.Contains([IO.Path]::GetFullPath($Path))) { throw 'Unexpected envelope read.' }
    $global:MagnoliePhoneEnvelopeCalls++
    if ($global:MagnoliePhoneSignatureCase -eq 'envelope-failure') { throw 'Controlled envelope rejection' }
}
'@ | Set-Content -LiteralPath (Join-Path $build 'PhonePayloadAuthenticode.Common.ps1') -Encoding UTF8
    . (Join-Path $build 'PhonePayloadSigning.Common.ps1')
    function Get-AuthenticodeSignature {
        param($LiteralPath)
        if (-not $global:MagnoliePhoneSignaturePaths.Contains([IO.Path]::GetFullPath($LiteralPath))) { throw 'Unexpected signature read; real certificate access forbidden.' }
        $case = $global:MagnoliePhoneSignatureCase
        $publisher = if ($case -eq 'wrong-publisher' -or ($case -eq 'helper-vendor' -and [IO.Path]::GetFileName($LiteralPath) -eq 'Magnolie.PhoneAudioSetup.x64.exe')) { 'CN=Vendor' } else { 'CN=Product' }
        $status = switch ($case) { 'unsigned' { 'NotSigned' }; 'untrusted' { 'NotTrusted' }; 'hash-mismatch' { 'HashMismatch' }; default { 'Valid' } }
        return [pscustomobject]@{ Status = $status; SignerCertificate = [pscustomobject]@{ Subject = $publisher };
            TimeStamperCertificate = ($case -ne 'missing-timestamp') }
    }
    $count = 0
    foreach ($case in @('all', 'helper', 'empty', 'wrong-publisher', 'helper-vendor', 'unsigned', 'untrusted',
        'hash-mismatch', 'missing-timestamp', 'tool-failure', 'late-tamper', 'stale-hash', 'unknown-schema', 'oversized-receipt', 'envelope-failure', 'different-input', 'unselected-input')) {
        $global:MagnoliePhoneSignatureCase = $case
        $global:MagnoliePhoneSignatureCalls = 0
        $global:MagnoliePhoneEnvelopeCalls = 0
        $global:MagnoliePhoneSignaturePaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $stage = Join-Path (Join-Path $temp $case) 'prepared'
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        $specs = @(Get-PhonePayloadSigningSpecifications)
        $selected = @(if ($case -eq 'empty') { } elseif ($case -in @('helper', 'unselected-input')) { $specs[0] } else { $specs })
        $inputs = @{}
        $payloads = @()
        foreach ($spec in $selected) {
            $directory = Join-Path (Join-Path $stage 'rechecked') $spec.Folder
            [IO.Directory]::CreateDirectory($directory) | Out-Null
            $binary = Join-Path $directory $spec.Binary
            $manifest = Join-Path $directory $spec.Manifest
            [IO.File]::WriteAllText($binary, 'MZsynthetic-' + $spec.Folder)
            [IO.File]::WriteAllText($manifest, 'synthetic-descriptor')
            $null = $global:MagnoliePhoneSignaturePaths.Add([IO.Path]::GetFullPath($binary))
            $inputs[$spec.Property] = $directory
            $payloads += [pscustomobject]@{ Property = $spec.Property; Binary = $spec.Binary; Manifest = $spec.Manifest;
                ManifestResource = $spec.Resource; Sha256 = (Get-FileHash -LiteralPath $binary).Hash.ToLowerInvariant();
                ManifestSha256 = (Get-FileHash -LiteralPath $manifest).Hash.ToLowerInvariant() }
        }
        if ($case -eq 'stale-hash') { $payloads[0].Sha256 = '0' * 64 }
        $schema = if ($case -eq 'unknown-schema') { 'unknown' } else { 'magnolie-prepared-phone-inputs-v1' }
        $receipt = Join-Path $stage 'receipt.json'
        [pscustomobject]@{ Schema = $schema; Stage = $stage; Inputs = $inputs; Payloads = $payloads } |
            ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding UTF8
        if ($case -eq 'oversized-receipt') { [IO.File]::WriteAllText($receipt, (' ' * 65537)) }
        $actualInputs = @{}
        foreach ($spec in $specs) { $actualInputs[$spec.Property] = if ($inputs.ContainsKey($spec.Property)) { $inputs[$spec.Property] } else { '' } }
        if ($case -eq 'different-input') { $actualInputs[$specs[0].Property] = $stage }
        if ($case -eq 'unselected-input') { $actualInputs[$specs[1].Property] = $stage }
        $passed = $true
        $failure = ''
        try { & (Join-Path $build 'Verify-PhonePayloadInputs.ps1') -Receipt $receipt -Publisher 'CN=Product' -SignTool 'mock' @actualInputs }
        catch { $passed = $false; $failure = $_.Exception.Message }
        $expected = $case -in @('all', 'helper', 'empty')
        if ($passed -ne $expected) { throw "Prepared signature verification mismatch: $case ($failure)" }
        if ($expected -and $global:MagnoliePhoneSignatureCalls -ne $selected.Count) { throw "Not every known input received independent verification: $case ($global:MagnoliePhoneSignatureCalls/$($selected.Count))." }
        if ($expected -and $global:MagnoliePhoneEnvelopeCalls -ne $selected.Count) { throw 'Not every known input received strict envelope verification.' }
        if ($case -in @('stale-hash', 'unknown-schema', 'oversized-receipt', 'different-input', 'unselected-input') -and $global:MagnoliePhoneSignatureCalls) { throw 'Invalid expected identity reached native verification.' }
        $count++
    }
    Write-Host "$count prepared-input signature policy cases passed with controlled signature/tool responses; native algorithms/chain/timestamps remain unaccepted."
} finally {
    foreach ($name in @('MagnoliePhoneSignatureCase', 'MagnoliePhoneSignatureCalls', 'MagnoliePhoneSignaturePaths', 'MagnoliePhoneEnvelopeCalls')) {
        Remove-Variable -Name $name -Scope Global -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
