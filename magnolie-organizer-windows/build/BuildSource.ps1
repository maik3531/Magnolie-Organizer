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
$archive = if ($Destination) { $Destination } else { Join-Path $root "$name-Source.zip" }
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
    foreach ($required in "app/magnolie-organizer.ico", "app/web/kaffee-qr.mga", "app/symbole/48x48/magnolie-organizer.png", "app/symbole/64x64/magnolie-organizer.png", "app/symbole/128x128/magnolie-organizer.png", "app/symbole/256x256/magnolie-organizer.png", "contracts/kontakt-sync-contract.json", "tests/resources/personal-sync-contract.json", "tests/resources/telefon-control-contract.json", "tests/resources/linux-parity-contract.json", "tests/linux-parity-fixture.js", "tests/generate-linux-parity-fixture.js", "shared/magnolie-handbuch-stamm/web/index.html", "shared/magnolie-handbuch-stamm/web/inhalt.js", "shared/magnolie-handbuch-stamm/web/kaffee-qr.mga", "shared/magnolie-handbuch-stamm/web/maik-walter.mga", "LICENSE") {
        if (-not (Test-Path (Join-Path $tree $required) -PathType Leaf)) { throw "Quellarchiv-Pflichtdatei fehlt: $required" }
    }
    New-DeterministicZip $tree $stagedArchive $name
    Assert-SourceArchive $stagedArchive $root $version

    $extract = Join-Path $work "standalone"
    [IO.Compression.ZipFile]::ExtractToDirectory($stagedArchive, $extract)
    $standalone = Join-Path $extract $name
    $handbookOverrides = @{}
    foreach ($variable in 'MAGNOLIE_HANDBOOK_WEB', 'MAGNOLIE_HANDBUCH_WEB', 'MAGNOLIE_LINUX_SOURCE', 'MAGNOLIE_TEST_SOURCE_ROOT') {
        $handbookOverrides[$variable] = [Environment]::GetEnvironmentVariable($variable)
        [Environment]::SetEnvironmentVariable($variable, $null)
    }
    Push-Location $standalone
    try {
        $python = if ($env:MAGNOLIE_PYTHON) { Get-Command $env:MAGNOLIE_PYTHON -ErrorAction Stop } else { Get-Command python3 -ErrorAction SilentlyContinue }
        if (-not $python) { $python = Get-Command python -ErrorAction Stop }
        Invoke-NativeCommand $python.Source @('-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_windows_pot_source_coverage.py')
        Invoke-NativeCommand (Get-Process -Id $PID).Path @('-NoProfile', '-File', 'tests/release-packaging.ps1')
        Invoke-NativeCommand "dotnet" @("restore", "tests/CoreTests.csproj", "--locked-mode")
        $previousSourceArchiveTest = $env:MAGNOLIE_SOURCE_ARCHIVE_TEST
        try {
            $env:MAGNOLIE_SOURCE_ARCHIVE_TEST = "1"
            Invoke-NativeCommand "dotnet" @("run", "--project", "tests/CoreTests.csproj", "-c", "Release", "--no-restore")
        } finally {
            $env:MAGNOLIE_SOURCE_ARCHIVE_TEST = $previousSourceArchiveTest
        }
        Invoke-NativeCommand "dotnet" @("restore", "MagnolieOrganizer.Windows.csproj", "--locked-mode")
        Invoke-NativeCommand "bun" @("install", "--frozen-lockfile")
        Invoke-NativeCommand "bun" @("run", "test")
        Invoke-NativeCommand "dotnet" @("build", "MagnolieOrganizer.Windows.csproj", "-c", "Release", "--no-restore")
    } finally {
        Pop-Location
        foreach ($variable in $handbookOverrides.Keys) {
            [Environment]::SetEnvironmentVariable($variable, $handbookOverrides[$variable])
        }
    }
    if ($Destination) { Move-Item -LiteralPath $stagedArchive -Destination $archive }
    else { Install-StagedPath $stagedArchive $archive }
    Get-FileHash -LiteralPath $archive -Algorithm SHA256
} finally {
    if ($lock) { $lock.Dispose() }
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
}
