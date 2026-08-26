param(
    [Parameter(Mandatory)][string] $Installer,
    [string] $RootManifest,
    [string] $LinuxSourceManifest,
    [string] $ExpectedPublisher = $env:MAGNOLIE_SIGN_PUBLISHER,
    [string] $SignTool = $env:MAGNOLIE_SIGNTOOL,
    [switch] $UpdateManualWindows
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "Release.Common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$version = Get-ReleaseVersion $root
if ($env:OS -ne "Windows_NT") { throw "Manifestaktualisierung ist nur auf Windows erlaubt." }
if (-not $RootManifest) { $RootManifest = Join-Path (Split-Path -Parent $root) "update.xml" }
if (-not $LinuxSourceManifest) { $LinuxSourceManifest = Join-Path (Split-Path -Parent $root) "magnolie-organizer-2.0.0/update.xml" }
if ([IO.Path]::GetFullPath($RootManifest).Equals([IO.Path]::GetFullPath($LinuxSourceManifest), [StringComparison]::OrdinalIgnoreCase)) {
    throw "Wurzel- und Linux-Quellmanifest müssen verschiedene Pfade sein."
}
if (-not (Test-Path $Installer -PathType Leaf)) { throw "Installer fehlt: $Installer" }
$expectedName = "Magnolie-Organizer-Windows-$version-Setup-x64.exe"
if ((Split-Path $Installer -Leaf) -cne $expectedName) { throw "Installername entspricht nicht Version $version." }
if (-not $ExpectedPublisher) { throw "Signaturprüfung benötigt ExpectedPublisher oder MAGNOLIE_SIGN_PUBLISHER." }
$signature = Get-AuthenticodeSignature -LiteralPath $Installer
if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) {
    throw "Authenticode-Prüfung fehlgeschlagen: $Installer ($($signature.Status))"
}
if (-not [string]::Equals($signature.SignerCertificate.Subject, $ExpectedPublisher, [StringComparison]::Ordinal)) {
    throw "Unerwarteter Authenticode-Herausgeber: $($signature.SignerCertificate.Subject)"
}
if (-not $signature.TimeStamperCertificate) { throw "Gültiger RFC3161-Zeitstempel fehlt: $Installer" }
if ($SignTool) {
    if (-not (Test-Path -LiteralPath $SignTool -PathType Leaf)) { throw "Konfiguriertes signtool fehlt: $SignTool" }
} else {
    $signToolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signToolCommand) { $signToolCommand = Get-Command signtool -ErrorAction SilentlyContinue }
    if ($signToolCommand) { $SignTool = $signToolCommand.Source }
}
if ($SignTool) { Invoke-NativeCommand $SignTool @("verify", "/pa", "/all", "/tw", $Installer) }
$hash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
$changes = @()
$packageRoot = "/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/"
function Assert-PackageUrl([string] $value, [string] $fileName) {
    $uri = [uri]$value
    if ($uri.Scheme -cne "https" -or $uri.Host -ine "gitlab.com" -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        $uri.AbsolutePath -cne "$packageRoot$fileName") { throw "Manifest-URL verletzt die Download-Policy: $value" }
}
foreach ($path in @($RootManifest, $LinuxSourceManifest)) {
    if (-not (Test-Path $path -PathType Leaf)) { throw "Manifest fehlt: $path" }
    $raw = Get-Content $path -Raw
    [xml]$xml = $raw
    if ($xml.SelectNodes("//*[translate(local-name(), 'SIGNATURE', 'signature')='signature']").Count -gt 0 -or
        (Test-Path "$path.sig") -or (Test-Path "$path.asc")) { throw "Signiertes Manifest wird nicht verändert: $path" }
    $windowsNodes = $xml.SelectNodes("/update/windows")
    if ($windowsNodes.Count -ne 1) { throw "Manifest benötigt genau ein /update/windows-Element: $path" }
    $windows = $windowsNodes[0]
    $urlNodes = $windows.SelectNodes("url")
    $versionNodes = $windows.SelectNodes("version")
    $hashNodes = $windows.SelectNodes("sha256")
    if ($urlNodes.Count -ne 1 -or $versionNodes.Count -ne 1 -or $hashNodes.Count -ne 1) {
        throw "Windows-Manifestvertrag ist nicht eindeutig oder verweist nicht auf den gebauten Installer: $path"
    }
    Assert-PackageUrl $urlNodes[0].InnerText $expectedName
    $versionNodes[0].InnerText = $version
    $hashNodes[0].InnerText = $hash
    if ($UpdateManualWindows) {
        $manualNodes = $xml.SelectNodes("/update/manual/windows")
        if ($manualNodes.Count -ne 1) { throw "Manifest benötigt genau ein /update/manual/windows-Element: $path" }
        $manualUrls = $manualNodes[0].SelectNodes("url")
        $manualHashes = $manualNodes[0].SelectNodes("sha256")
        if ($manualUrls.Count -ne 1 -or $manualHashes.Count -ne 1) {
            throw "Handbuch-Policy erlaubt kein Update: manual/windows ist nicht exakt derselbe Installer."
        }
        Assert-PackageUrl $manualUrls[0].InnerText $expectedName
        $manualHashes[0].InnerText = $hash
    }
    $staged = "$path.staging-$([Guid]::NewGuid().ToString('N'))"
    $settings = [Xml.XmlWriterSettings]@{ Encoding = [Text.UTF8Encoding]::new($false); Indent = $true }
    $writer = [Xml.XmlWriter]::Create($staged, $settings)
    try { $xml.Save($writer) } finally { $writer.Dispose() }
    [xml](Get-Content $staged -Raw) | Out-Null
    $changes += ,@($staged, $path)
}
try {
    Install-StagedPaths $changes
} finally {
    foreach ($change in $changes) { if (Test-Path $change[0]) { Remove-Item $change[0] -Force } }
}
Write-Host "Windows-Hash $hash wurde in beide Manifeste eingetragen."
