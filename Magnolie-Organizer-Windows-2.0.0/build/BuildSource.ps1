param(
    [string] $Destination,
    [switch] $SkipLock
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "Release.Common.ps1")

$root = Split-Path -Parent $PSScriptRoot
$version = Get-ReleaseVersion $root
$name = "Magnolie-Organizer-Windows-$version"
$archive = if ($Destination) { $Destination } else { Join-Path (Split-Path -Parent $root) "$name-Source.zip" }
$work = Join-Path ([IO.Path]::GetTempPath()) ("magnolie-source-" + [Guid]::NewGuid().ToString("N"))
$tree = Join-Path $work $name
$stagedArchive = Join-Path $work "$name-Source.zip"
$lock = if ($SkipLock) { $null } else { Enter-ReleaseLock $root }

try {
    if (-not (Test-Path (Join-Path $root "LICENSE") -PathType Leaf)) { throw "GPLv3-LICENSE fehlt; Quellarchiv wird nicht erzeugt." }
    New-Item -ItemType Directory -Path $tree | Out-Null
    $files = Get-ReleaseArchiveSources $root
    foreach ($file in $files) {
        $relative = $file.Relative
        $target = Join-Path $tree $relative
        $parent = Split-Path -Parent $target
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
        Copy-Item -LiteralPath $file.Source -Destination $target
    }
    foreach ($required in "app/magnolie-organizer.ico", "app/web/kaffee-qr.png", "app/symbole/48x48/magnolie-organizer.png", "app/symbole/64x64/magnolie-organizer.png", "app/symbole/128x128/magnolie-organizer.png", "app/symbole/256x256/magnolie-organizer.png", "contracts/kontakt-sync-contract.json", "tests/resources/personal-sync-contract.json", "tests/resources/telefon-control-contract.json", "tests/resources/linux-parity-contract.json", "tests/linux-parity-fixture.js", "tests/generate-linux-parity-fixture.js", "shared/magnolie-handbuch-stamm/web/index.html", "shared/magnolie-handbuch-stamm/web/inhalt.js", "LICENSE") {
        if (-not (Test-Path (Join-Path $tree $required) -PathType Leaf)) { throw "Quellarchiv-Pflichtdatei fehlt: $required" }
    }
    New-DeterministicZip $tree $stagedArchive $name
    Assert-SourceArchive $stagedArchive $root $version

    $extract = Join-Path $work "standalone"
    [IO.Compression.ZipFile]::ExtractToDirectory($stagedArchive, $extract)
    $standalone = Join-Path $extract $name
    Push-Location $standalone
    try {
        Invoke-NativeCommand "dotnet" @("restore", "tests/CoreTests.csproj", "--locked-mode")
        Invoke-NativeCommand "dotnet" @("run", "--project", "tests/CoreTests.csproj", "-c", "Release", "--no-restore")
        Invoke-NativeCommand "dotnet" @("restore", "MagnolieOrganizer.Windows.csproj", "--locked-mode")
        Invoke-NativeCommand "bun" @("install", "--frozen-lockfile")
        Invoke-NativeCommand "bun" @("run", "test")
        Invoke-NativeCommand "dotnet" @("build", "MagnolieOrganizer.Windows.csproj", "-c", "Release", "--no-restore")
    } finally { Pop-Location }
    if ($Destination) { Move-Item -LiteralPath $stagedArchive -Destination $archive }
    else { Install-StagedPath $stagedArchive $archive }
    Get-FileHash -LiteralPath $archive -Algorithm SHA256
} finally {
    if ($lock) { $lock.Dispose() }
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
}
