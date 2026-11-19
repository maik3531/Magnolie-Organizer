# Actual portable recipe against a cold, bounded source-only ZIP. No product
# build, native provider replacement, user profile, signing or installation.
param(
    [string] $Common = (Join-Path $PSScriptRoot '../build/Release.Common.ps1'),
    [string] $Python = $env:MAGNOLIE_PYTHON,
    [string] $LinuxRoot = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. $Common
if (-not $Python) {
    $command = Get-Command python3 -CommandType Application -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command python -CommandType Application -ErrorAction Stop }
    $Python = $command.Source
}
if ($Python -match '(?i)[\\/]WindowsApps[\\/]python(?:3)?\.exe$') { throw 'An existing executable Python is required, not a Store launcher alias.' }
if (-not $LinuxRoot) {
    $LinuxRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'magnolie-organizer'
    if (-not (Test-Path -LiteralPath $LinuxRoot -PathType Container)) {
        $LinuxRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'shared/magnolie-organizer'
    }
}
$inputs = @(Get-SharedLinuxTimezoneInputs $LinuxRoot)
if ($inputs.Count -ne 7) { throw 'Exactly the recipe and six bound source inputs are required.' }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-timezone-recipe-' + [guid]::NewGuid().ToString('N'))
$expected = '82a07365a6a4076609dfa3ed7b4eba4125b38b3daf16a5cf8e95278c0cb45c8b'
try {
    $before = @{}
    $tree = Join-Path $temp 'source'
    foreach ($entry in $inputs) {
        $before[$entry.Source] = (Get-FileHash -LiteralPath $entry.Source).Hash
        $target = Join-Path $tree $entry.Relative
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        [IO.File]::Copy($entry.Source, $target)
    }
    $archive = Join-Path $temp 'Synthetic-Timezone-Source.zip'
    New-DeterministicZip $tree $archive 'Synthetic-Timezone-Source'
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        if ($zip.Entries.Count -ne 7 -or @($zip.Entries | Where-Object { $_.FullName -notlike 'Synthetic-Timezone-Source/shared/magnolie-organizer/werkzeuge/*' }).Count) {
            throw 'Cold fixture ZIP contains unrelated or generated data.'
        }
    } finally { $zip.Dispose() }
    $extracted = Join-Path $temp 'extracted'
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $extracted)
    $root = Join-Path $extracted 'Synthetic-Timezone-Source'
    $linux = Join-Path $root 'shared/magnolie-organizer'
    $generator = Join-Path $linux 'werkzeuge/zeitzonen_erzeugen.py'
    $source = Join-Path $linux 'werkzeuge/timezones'
    Invoke-NativeCommand $Python @('-I', '-B', $generator, '--source', $source, '--check')
    foreach ($web in @((Join-Path $root 'app/web'), (Join-Path $linux 'web'))) {
        Invoke-NativeCommand $Python @('-I', '-B', $generator, '--source', $source, '--output', $web)
        if ((Get-FileHash -LiteralPath (Join-Path $web 'normative-timezones.js')).Hash.ToLowerInvariant() -cne $expected) {
            throw 'Cold bootstrap differs from the independently checked port vector.'
        }
        foreach ($name in 'tzdb-2026egtz.json', 'provenance.json', 'LICENSE-tzdb.txt') {
            if ((Get-FileHash -LiteralPath (Join-Path $source $name)).Hash -cne
                (Get-FileHash -LiteralPath (Join-Path $web "timezones/$name")).Hash) {
                throw 'Cold payload/provenance/license bytes differ.'
            }
        }
    }
    $payload = Join-Path $source 'tzdb-2026egtz.json'
    [IO.File]::AppendAllText($payload, ' ')
    $web = Join-Path $root 'app/web'
    $rejected = $false
    try { Invoke-NativeCommand $Python @('-I', '-B', $generator, '--source', $source, '--output', $web) }
    catch { $rejected = $true }
    if (-not $rejected -or (Get-FileHash -LiteralPath (Join-Path $web 'normative-timezones.js')).Hash.ToLowerInvariant() -cne $expected) {
        throw 'Changed cold input was accepted or replaced the previous checked bootstrap.'
    }
    foreach ($entry in $inputs) {
        if ((Get-FileHash -LiteralPath $entry.Source).Hash -cne $before[$entry.Source]) { throw 'Caller source was modified.' }
    }
    Write-Output 'Cold timezone recipe passed: seven source inputs, both GUI bootstraps byte-exact, payload/license binding, tamper rejection and unchanged caller.'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
