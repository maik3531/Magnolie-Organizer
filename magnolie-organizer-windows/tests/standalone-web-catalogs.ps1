# Source projection/generation orchestration only, with a controlled Python
# callback. No actual user data, translations rewritten in the caller, or build.
param([string] $Common = (Join-Path $PSScriptRoot '../build/Release.Common.ps1'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. $Common
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-standalone-catalogs-' + [guid]::NewGuid().ToString('N'))
function Write-Fixture([string]$Path, [string]$Text) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}
function Assert-Rejected([scriptblock]$Action, [string]$Expected = '') {
    $failure = ''
    try { & $Action } catch { $failure = $_.Exception.Message }
    if (-not $failure -or ($Expected -and $failure -notmatch [regex]::Escape($Expected))) { throw "Expected source preflight rejection was missing: $failure" }
}
try {
    $root = Join-Path $temp 'extracted-source'
    $linux = Join-Path $root 'shared/magnolie-organizer'
    foreach ($po in @((Join-Path $root 'app/po'), (Join-Path $linux 'po'))) {
        Write-Fixture (Join-Path $po 'LINGUAS') "de`ntr`n"
        foreach ($language in 'de', 'tr') { Write-Fixture (Join-Path $po ($language + '.po')) 'Synthetic PO input, never parsed by this controlled callback.' }
    }
    foreach ($file in @('werkzeuge/pot_erzeugen.py', 'werkzeuge/po_zu_js.py', 'werkzeuge/po_zu_native.py',
        'shared/magnolie-organizer/werkzeuge/po_zu_js.py')) { Write-Fixture (Join-Path $root $file) '# Synthetic generator dependency.' }
    $pot = Join-Path $root 'app/po/magnolie-organizer.pot'
    Write-Fixture $pot 'stale-derived-template'
    $script:catalogCalls = [Collections.Generic.List[string]]::new()
    function Invoke-NativeCommand {
        param($FilePath, $ArgumentList)
        if ($FilePath -cne 'SYNTHETIC-PYTHON-NOT-EXECUTED' -or $ArgumentList[0] -cne '-B') { throw 'Unexpected process invocation.' }
        $script:catalogCalls.Add([string]$ArgumentList[1])
        switch ([IO.Path]::GetFileName($ArgumentList[1])) {
            'pot_erzeugen.py' {
                if ($ArgumentList[2] -cne '--output') { throw 'Template output was not explicit.' }
                Write-Fixture $ArgumentList[3] 'fresh-derived-template'
            }
            'po_zu_js.py' { Write-Fixture $ArgumentList[4] ('generated-' + $ArgumentList[2]) }
            'po_zu_native.py' { Write-Fixture $ArgumentList[2] 'generated-native-catalogue' }
            default { throw 'Unknown synthetic generator.' }
        }
    }
    Assert-Rejected { Initialize-StandaloneWebCatalogs (Split-Path -Parent $PSScriptRoot) 'SYNTHETIC-PYTHON-NOT-EXECUTED' } 'must not modify the caller source tree'
    if ($script:catalogCalls.Count) { throw 'Caller source preflight reached a generator.' }
    $linguas = Join-Path $linux 'po/LINGUAS'
    foreach ($invalid in @("de`nde`ntr`n", "de`n../escape`ntr`n")) {
        Write-Fixture $linguas $invalid
        Assert-Rejected { Initialize-StandaloneWebCatalogs $root 'SYNTHETIC-PYTHON-NOT-EXECUTED' } 'Invalid or repeated'
        if ($script:catalogCalls.Count -or [IO.File]::ReadAllText($pot) -cne 'stale-derived-template') { throw 'Invalid recipe modified derived data.' }
    }
    Write-Fixture $linguas "de`ntr`n"
    $tr = Join-Path $linux 'po/tr.po'
    Move-Item -LiteralPath $tr -Destination ($tr + '.held')
    Assert-Rejected { Initialize-StandaloneWebCatalogs $root 'SYNTHETIC-PYTHON-NOT-EXECUTED' }
    Move-Item -LiteralPath ($tr + '.held') -Destination $tr
    if ($script:catalogCalls.Count -or [IO.File]::ReadAllText($pot) -cne 'stale-derived-template') { throw 'Missing recipe input modified derived data.' }
    $generator = Join-Path $root 'werkzeuge/po_zu_native.py'
    Move-Item -LiteralPath $generator -Destination ($generator + '.held')
    Assert-Rejected { Initialize-StandaloneWebCatalogs $root 'SYNTHETIC-PYTHON-NOT-EXECUTED' }
    Move-Item -LiteralPath ($generator + '.held') -Destination $generator
    if ($script:catalogCalls.Count -or [IO.File]::ReadAllText($pot) -cne 'stale-derived-template') { throw 'Missing Windows generator modified derived data.' }
    Initialize-StandaloneWebCatalogs $root 'SYNTHETIC-PYTHON-NOT-EXECUTED'
    if ($script:catalogCalls.Count -ne 6 -or [IO.File]::ReadAllText($pot) -cne 'fresh-derived-template') { throw 'Standalone template/locale preparation did not complete.' }
    foreach ($directory in @('app/web/i18n', 'shared/magnolie-organizer/web/i18n')) {
        foreach ($language in 'de', 'tr') {
            if ([IO.File]::ReadAllText((Join-Path $root "$directory/$language.js")) -cne ('generated-' + $language)) { throw 'Independent GUI catalogue was not materialized.' }
        }
    }
    if ([IO.File]::ReadAllText((Join-Path $root 'app/native-i18n.json')) -cne 'generated-native-catalogue') { throw 'Native catalogue was not materialized.' }
    Write-Output 'Standalone catalogue fixtures passed: caller-source protection, missing/unsafe recipe rejection and both generated GUI matrices.'
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
