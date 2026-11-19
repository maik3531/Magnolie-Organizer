# Verification only: public publisher/tool configuration, never signing keys,
# passwords, signing commands, assembly loading or runtime permission changes.
param(
    [Parameter(Mandatory)][string] $Receipt,
    [Parameter(Mandatory)][string] $Publisher,
    [Parameter(Mandatory)][string] $SignTool,
    [Parameter(Mandatory)][AllowEmptyString()][string] $MagnoliePhoneCameraHelperDirectory,
    [Parameter(Mandatory)][AllowEmptyString()][string] $MagnoliePhoneCameraRuntimeDirectory,
    [Parameter(Mandatory)][AllowEmptyString()][string] $MagnoliePhoneCameraParentDirectory,
    [Parameter(Mandatory)][AllowEmptyString()][string] $MagnoliePhoneCameraSourceDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'Release.Common.ps1')
. (Join-Path $PSScriptRoot 'Signing.Common.ps1')
. (Join-Path $PSScriptRoot 'PhonePayloadSigning.Common.ps1')
. (Join-Path $PSScriptRoot 'PhonePayloadAuthenticode.Common.ps1')
$script:signingConfiguration = @{ MAGNOLIE_SIGN_PUBLISHER = $Publisher; MAGNOLIE_SIGNTOOL = $SignTool }
$item = Get-Item -LiteralPath $Receipt -ErrorAction Stop
if ($item.PSIsContainer -or $item.Length -gt 65536 -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'A bounded regular prepared-input receipt is required.'
}
$stream = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    if ($stream.Length -lt 1 -or $stream.Length -gt 65536) { throw 'Prepared-input receipt size changed.' }
    $bytes = [byte[]]::new([int]$stream.Length)
    $stream.ReadExactly($bytes, 0, $bytes.Length)
    if ($stream.ReadByte() -ne -1) { throw 'Prepared-input receipt grew during verification.' }
    $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes).TrimStart([char]0xfeff)
} finally { $stream.Dispose() }
$prepared = $text | ConvertFrom-Json -Depth 16
if ($prepared.Schema -cne 'magnolie-prepared-phone-inputs-v1') { throw 'Unknown prepared-input receipt schema.' }
$inputs = @{}
foreach ($entry in $prepared.Inputs.PSObject.Properties) { $inputs[$entry.Name] = $entry.Value }
$prepared.Inputs = $inputs
$embeddingInputs = @{
    MagnoliePhoneCameraHelperDirectory = $MagnoliePhoneCameraHelperDirectory
    MagnoliePhoneCameraRuntimeDirectory = $MagnoliePhoneCameraRuntimeDirectory
    MagnoliePhoneCameraParentDirectory = $MagnoliePhoneCameraParentDirectory
    MagnoliePhoneCameraSourceDirectory = $MagnoliePhoneCameraSourceDirectory
}
# The receipt supplies expected identity only; it does not confer trust. Check
# every binary against the independent native Authenticode policy as product
# ownership, including the embedded-only setup helper, never as a vendor.
$null = Get-PreparedPhonePublishArguments $prepared
foreach ($spec in @(Get-PhonePayloadSigningSpecifications)) {
    $expected = if ($inputs.ContainsKey($spec.Property)) { $inputs[$spec.Property] } else { '' }
    if ($embeddingInputs[$spec.Property] -cne $expected) { throw 'Actual embedding input differs from the verified receipt.' }
}
foreach ($payload in @($prepared.Payloads)) {
    $binary = Join-Path $prepared.Inputs[$payload.Property] $payload.Binary
    Assert-Signature $binary
    Assert-PhonePayloadAuthenticodeEnvelope -Path $binary
}
# A successful native verifier must not conceal a changed expected snapshot.
$null = Get-PreparedPhonePublishArguments $prepared
