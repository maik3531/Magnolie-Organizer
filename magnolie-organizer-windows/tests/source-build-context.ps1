# Execute the byte-exact BuildSource orchestration with inert source inputs and
# controlled native callbacks. No SDK execution, package installation, signing or build.
param([string]$Source = (Join-Path $PSScriptRoot '../build/BuildSource.ps1'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$variables = @('MAGNOLIE_OFFICIAL_RELEASE', 'MagnoliePhoneCameraHelperDirectory',
    'MagnoliePhoneCameraRuntimeDirectory', 'MagnoliePhoneCameraParentDirectory', 'MagnoliePhoneCameraSourceDirectory',
    'MAGNOLIE_PHONE_VERIFY_RECEIPT', 'MAGNOLIE_PHONE_VERIFY_PUBLISHER', 'MAGNOLIE_PHONE_VERIFY_TOOL', 'MAGNOLIE_PHONE_VERIFY_HOST')
$saved = @{}
foreach ($name in $variables) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-source-context-' + [guid]::NewGuid().ToString('N'))
try {
    $root = Join-Path $temp 'source'
    $build = Join-Path $root 'build'
    [IO.Directory]::CreateDirectory($build) | Out-Null
    $copy = Join-Path $build 'BuildSource.ps1'
    Copy-Item -LiteralPath $Source -Destination $copy
    if ((Get-FileHash -LiteralPath $Source).Hash -ne (Get-FileHash -LiteralPath $copy).Hash) { throw 'Source orchestration copy changed.' }
    [IO.File]::WriteAllText((Join-Path $root 'Directory.Build.props'), '<Project><PropertyGroup><Version>9.8.7</Version></PropertyGroup></Project>')
    [IO.File]::WriteAllText((Join-Path $root 'LICENSE'), 'Synthetic source-context fixture, not a product.')
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'Source orchestration did not parse.' }
    # Materialize only the source's own literal mandatory fixture filenames.
    $loops = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.ForEachStatementAst] -and $node.Variable.VariablePath.UserPath -ceq 'required' }, $true)
    foreach ($loop in $loops) {
        foreach ($literal in $loop.Condition.FindAll({ param($node) $node -is [Management.Automation.Language.StringConstantExpressionAst] }, $true)) {
            $relative = $literal.Value
            if ($relative -notmatch '/') { $relative = 'tests/resources/' + $relative }
            $target = Join-Path $root $relative
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.File]::WriteAllText($target, 'Synthetic mandatory source input.')
        }
    }
    $common = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $Source) 'Release.Common.ps1')).Replace("'", "''")
    @"
. '$common'
"@ + "`n" + @'
function Get-ReleaseArchiveSources {
    param($Root)
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse) {
        [pscustomobject]@{ Source = $file.FullName; Relative = [IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/') }
    }
}
function Assert-SourceArchive { param($Archive, $Root, $Version) if (-not (Test-Path -LiteralPath $Archive)) { throw 'Synthetic ZIP missing.' } }
function Initialize-StandaloneWebCatalogs { param($Root, $Python) }
function Invoke-NativeCommand {
    param($FilePath, $ArgumentList)
    foreach ($name in $global:MagnolieSourceContextVariables) {
        if ([Environment]::GetEnvironmentVariable($name)) { throw ('Source-only validation inherited official payload context: ' + $name) }
    }
    $global:MagnolieSourceContextCalls++
    if ($global:MagnolieSourceContextFail -and ($ArgumentList -join ' ') -eq 'run test') { throw 'CONTROLLED-SOURCE-VALIDATION-FAILURE' }
}
'@ | Set-Content -LiteralPath (Join-Path $build 'Release.Common.ps1') -Encoding UTF8
    $global:MagnolieSourceContextVariables = $variables
    foreach ($failure in @($false, $true)) {
        $expected = @{}
        foreach ($name in $variables) {
            $expected[$name] = if ($name -eq 'MAGNOLIE_OFFICIAL_RELEASE') { '1' } else { 'SYNTHETIC-UNCHANGED-' + $name }
            [Environment]::SetEnvironmentVariable($name, $expected[$name])
        }
        $global:MagnolieSourceContextFail = $failure
        $global:MagnolieSourceContextCalls = 0
        $destination = Join-Path $temp ("source-$failure.zip")
        $caught = ''
        try { $null = & $copy -Destination $destination -SkipLock } catch { $caught = $_.Exception.Message; if ($caught -cne 'CONTROLLED-SOURCE-VALIDATION-FAILURE') { Write-Output $_.ScriptStackTrace } }
        if (($failure -and $caught -cne 'CONTROLLED-SOURCE-VALIDATION-FAILURE') -or (-not $failure -and $caught)) { throw "Unexpected source-context result: $caught" }
        if ($global:MagnolieSourceContextCalls -lt 3) { throw 'Controlled source validation did not run.' }
        foreach ($name in $variables) {
            if ([Environment]::GetEnvironmentVariable($name) -cne $expected[$name]) { throw ('Caller context not restored after source validation: ' + $name) }
        }
        if ((Test-Path -LiteralPath $destination) -eq $failure) { throw 'Failed source validation published its synthetic archive, or success lost it.' }
    }
    Write-Output 'Source-only official-payload context isolation/restoration passed for success and failure; no native tools or full tests executed.'
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    foreach ($name in 'MagnolieSourceContextVariables', 'MagnolieSourceContextCalls', 'MagnolieSourceContextFail') { Remove-Variable -Name $name -Scope Global -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
