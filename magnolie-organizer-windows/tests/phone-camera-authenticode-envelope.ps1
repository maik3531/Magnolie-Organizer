# Inert DER/invalid-PE cases only; no certificate or key generation/signing.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/PhonePayloadAuthenticode.Common.ps1')
function Der-Value([byte]$Tag, [byte[]]$Value) {
    if ($Value.Length -gt 127) { throw 'Synthetic DER fixture exceeds its short-form bound.' }
    return ,([byte[]]@($Tag, [byte]$Value.Length) + $Value)
}
$count = 0
foreach ($case in @('valid', 'absent-null', 'sha1', 'wrong-hash', 'wrong-parent', 'version', 'serial',
    'wrong-time-type', 'trailing', 'malformed', 'wrong-parameters', 'empty-parent')) {
    $parent = [Text.Encoding]::ASCII.GetBytes('synthetic-parent-signature-not-a-real-CMS')
    $hash = [Security.Cryptography.SHA256]::HashData($parent)
    if ($case -eq 'wrong-hash') { $hash[0] = $hash[0] -bxor 1 }
    $oid = if ($case -eq 'sha1') { [byte[]]@(0x2b, 0x0e, 3, 2, 0x1a) } else { [byte[]]@(0x60, 0x86, 0x48, 1, 0x65, 3, 4, 2, 1) }
    $parameters = if ($case -eq 'absent-null') { [byte[]]@() } elseif ($case -eq 'wrong-parameters') { [byte[]]@(2, 1, 0) } else { [byte[]]@(5, 0) }
    $algorithm = Der-Value 0x30 ((Der-Value 6 $oid) + $parameters)
    $imprint = Der-Value 0x30 ($algorithm + (Der-Value 4 $hash))
    $version = if ($case -eq 'version') { 2 } else { 1 }
    $serial = if ($case -eq 'serial') { 0 } else { 1 }
    $timeTag = if ($case -eq 'wrong-time-type') { 0x17 } else { 0x18 }
    $time = Der-Value $timeTag ([Text.Encoding]::ASCII.GetBytes('20261115100000Z'))
    $content = Der-Value 0x30 ([byte[]]@(2, 1, $version, 6, 2, 0x2a, 3) + $imprint + [byte[]]@(2, 1, $serial) + $time)
    if ($case -eq 'wrong-parent') { $parent[0] = $parent[0] -bxor 1 }
    if ($case -eq 'trailing') { $content = $content + [byte[]]@(5, 0) }
    if ($case -eq 'malformed') { $content = [byte[]]@(0x30, 0x7f, 0) }
    if ($case -eq 'empty-parent') { $parent = [byte[]]@() }
    $passed = $true
    $failure = ''
    try { Assert-PhoneTimestampImprint -Content $content -ParentSignature $parent }
    catch { $passed = $false; $failure = $_.Exception.Message }
    if ($passed -ne ($case -in @('valid', 'absent-null'))) { throw "Timestamp imprint policy mismatch: $case ($failure)" }
    $count++
}
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-envelope-' + [guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temp) | Out-Null
    foreach ($text in @('not a PE', 'MZsynthetic-unsigned-not-a-valid-PE')) {
        $path = Join-Path $temp 'fixture.exe'
        [IO.File]::WriteAllText($path, $text)
        $rejected = $false
        try { Assert-PhonePayloadAuthenticodeEnvelope -Path $path } catch { $rejected = $true }
        if (-not $rejected) { throw 'Invalid unsigned synthetic PE was accepted.' }
        $count++
    }
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
Write-Host "$count inert Authenticode/RFC3161 structural cases passed; no actual certificate chain or Magnolie signature acceptance."
