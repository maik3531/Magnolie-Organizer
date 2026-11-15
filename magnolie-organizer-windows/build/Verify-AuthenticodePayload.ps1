param(
    [Parameter(Mandatory)][string] $Root,
    [Parameter(Mandatory)][string] $Publisher,
    [Parameter(Mandatory)][string] $SignTool,
    [Parameter(Mandatory)][string] $Report,
    [string] $Installer,
    [string] $UninstallerReceipt
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'Release.Common.ps1')
. (Join-Path $PSScriptRoot 'Signing.Common.ps1')
$script:signingConfiguration = @{ MAGNOLIE_SIGN_PUBLISHER = $Publisher; MAGNOLIE_SIGNTOOL = $SignTool }
$owned = @('Magnolie Organizer.exe', 'Magnolie Organizer.dll',
    'Magnolie.PhoneAudioSetup.x64.exe',
    'Magnolie.PhoneAudioWorker.x64.exe', 'Magnolie.PhoneAudioParent.x64.dll',
    'Magnolie.PhoneCameraSource.x64.dll')
$expectedUninstallerHash = if ($UninstallerReceipt) {
    (Get-Content -LiteralPath $UninstallerReceipt -Raw | ConvertFrom-Json).sha256
} else { $null }
if ($UninstallerReceipt -and $expectedUninstallerHash -notmatch '^[0-9A-Fa-f]{64}$') { throw 'Invalid uninstaller receipt.' }
$foundUninstaller = $false
$foundApp = $false
$results = [Collections.Generic.List[object]]::new()
$failure = $false
$files = @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force)
if ($Installer) { $files += Get-Item -LiteralPath $Installer }
foreach ($file in $files) {
    # Detect PE content, including extensionless files; malformed executable candidates fail closed.
    $stream = [IO.File]::OpenRead($file.FullName)
    try { $mz = $stream.ReadByte() -eq 0x4d; $mz = ($stream.ReadByte() -eq 0x5a) -and $mz }
    finally { $stream.Dispose() }
    if (-not $mz -and $file.Extension -notin @('.exe', '.dll', '.sys', '.ocx', '.scr', '.cpl', '.pyd', '.msi')) { continue }
    $relative = [IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/')
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    $isUninstaller = $expectedUninstallerHash -and $hash -eq $expectedUninstallerHash
    $isOwn = $relative -in $owned -or $isUninstaller -or ($Installer -and $file.FullName -eq [IO.Path]::GetFullPath($Installer))
    if ($relative -eq 'Magnolie Organizer.exe') { $foundApp = $true }
    if ($isUninstaller) { $foundUninstaller = $true }
    $status = 'Valid'
    try { Assert-Signature $file.FullName -ThirdParty:(-not $isOwn) }
    catch { $status = 'Rejected'; $failure = $true }
    $sig = Get-AuthenticodeSignature -LiteralPath $file.FullName
    $results.Add([pscustomobject]@{
        path = $relative; sha256 = $hash; role = $(if ($isOwn) { 'product' } else { 'third-party' })
        status = $status; authenticodeStatus = [string]$sig.Status
        publisher = $(if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null })
        signerThumbprint = $(if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { $null })
        timestampPresent = [bool]$sig.TimeStamperCertificate
    })
}
if (-not $foundApp -or ($UninstallerReceipt -and -not $foundUninstaller)) { $failure = $true }
[pscustomobject]@{ schema = 'magnolie-authenticode-v1'; passed = (-not $failure); files = $results.ToArray() } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Report -Encoding UTF8
if ($failure) { throw 'Authenticode payload rejected (including required app/uninstaller presence); see report.' }
