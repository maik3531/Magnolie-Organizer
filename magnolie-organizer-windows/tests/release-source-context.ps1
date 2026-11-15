# Execute only the canonical release caller's source-test prefix/finally.
# Native commands and catalogue generation are controlled dependencies; the
# signing/publish portion is never extracted or executed by this fixture.
param([string]$Source = (Join-Path $PSScriptRoot '../build/Build.ps1'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$text = [IO.File]::ReadAllText([IO.Path]::GetFullPath($Source))
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Release caller source does not parse.' }
$scopes = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.TryStatementAst] -and
    $node.Finally -and $node.Finally.Extent.Text.Contains('$testEnvironment.Keys')
}, $true))
if ($scopes.Count -ne 1) { throw 'Exact release test-context scope is missing or ambiguous.' }
$scope = $scopes[0]
$start = $text.IndexOf('    $testEnvironment = @{}', [StringComparison]::Ordinal)
$lastTests = @($scope.Body.FindAll({ param($node)
    $node -is [Management.Automation.Language.CommandAst] -and
    $node.Extent.Text -ceq 'Invoke-NativeCommand "bun" @("run", "test")'
}, $true))
if ($lastTests.Count -ne 1) { throw 'The exact final source Web-test command is missing or ambiguous.' }
$stop = $lastTests[0].Extent.EndOffset
if ($start -lt 0 -or $stop -le $scope.Body.Extent.StartOffset -or $stop -ge $scope.Body.Extent.EndOffset) { throw 'Source-only release prefix boundaries changed.' }
$prefix = $text.Substring($start, $scope.Body.Extent.StartOffset + 1 - $start)
$body = $text.Substring($scope.Body.Extent.StartOffset + 1, $stop - $scope.Body.Extent.StartOffset - 1)
if ($body -match 'Sign-Official|New-VerifiedSignedPhoneInputs|Invoke-NativeCommand\s+[^\r\n]+publish') { throw 'Signing/publish commands must never enter the fixture.' }
$controlled = [scriptblock]::Create($prefix + $body + "`n} finally " + $scope.Finally.Extent.Text)
$variables = @('MAGNOLIE_HANDBOOK_WEB', 'MAGNOLIE_HANDBUCH_WEB', 'MAGNOLIE_LINUX_SOURCE',
    'MAGNOLIE_TEST_SOURCE_ROOT', 'DOTNET_HOST_PATH', 'MAGNOLIE_TEST_PWSH')
$saved = @{}
foreach ($name in $variables) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-release-context-' + [guid]::NewGuid().ToString('N'))
try {
    $buildRoot = Join-Path $temp 'extracted-source'
    $handbookWeb = Join-Path $buildRoot 'shared/magnolie-handbuch/web'
    $linux = Join-Path $buildRoot 'shared/magnolie-organizer/web'
    [IO.Directory]::CreateDirectory($handbookWeb) | Out-Null
    [IO.Directory]::CreateDirectory($linux) | Out-Null
    [IO.File]::WriteAllText((Join-Path $linux 'index.html'), 'Synthetic independent GUI input.')
    $python = [pscustomobject]@{ Source = 'SYNTHETIC-PYTHON-NOT-EXECUTED' }
    $expectedDotnet = (Get-Command dotnet -CommandType Application -ErrorAction Stop).Source
    $expectedHost = (Get-Process -Id $PID).Path
    function Initialize-StandaloneWebCatalogs {
        param($Root, $Python)
        if ($Root -cne $buildRoot -or $Python -cne 'SYNTHETIC-PYTHON-NOT-EXECUTED') { throw 'Release caller did not prepare its own extracted source.' }
        $script:catalogueCalls++
        if ($script:controlledCase -eq 'catalogue-failure') { throw 'CONTROLLED-CATALOGUE-FAILURE' }
    }
    function Invoke-NativeCommand {
        param($FilePath, $ArgumentList)
        if ($script:catalogueCalls -ne 1) { throw 'Release source tests started before cold catalogue generation.' }
        if ($env:DOTNET_HOST_PATH -cne $expectedDotnet -or $env:MAGNOLIE_TEST_PWSH -cne $expectedHost -or
            $env:MAGNOLIE_TEST_SOURCE_ROOT -cne $buildRoot -or $env:MAGNOLIE_HANDBOOK_WEB -cne $handbookWeb -or
            $env:MAGNOLIE_HANDBUCH_WEB -cne $handbookWeb -or $env:MAGNOLIE_LINUX_SOURCE -cne (Split-Path -Parent $linux)) { throw 'Release caller did not forward its exact source/tool context.' }
        $script:nativeCalls++
        if ($script:controlledCase -eq 'test-failure' -and ($ArgumentList -join ' ') -eq 'run test') { throw 'CONTROLLED-WEB-FAILURE' }
    }
    foreach ($case in @('success', 'catalogue-failure', 'test-failure')) {
        foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, 'SYNTHETIC-PREVIOUS-' + $name) }
        $script:catalogueCalls = 0; $script:nativeCalls = 0; $script:controlledCase = $case
        $cwd = (Get-Location).Path
        $failure = ''
        try { & $controlled } catch { $failure = $_.Exception.Message }
        $expected = switch ($case) { 'success' { '' }; 'catalogue-failure' { 'CONTROLLED-CATALOGUE-FAILURE' }; 'test-failure' { 'CONTROLLED-WEB-FAILURE' } }
        if ($failure -cne $expected) { throw "Unexpected release source-context result: $case; $failure" }
        if ($script:catalogueCalls -ne 1 -or ($case -eq 'catalogue-failure' -and $script:nativeCalls) -or
            ($case -ne 'catalogue-failure' -and $script:nativeCalls -lt 3)) { throw 'Controlled release test ordering did not execute.' }
        if ((Get-Location).Path -cne $cwd) { throw 'Release source context did not restore its working directory.' }
        foreach ($name in $variables) {
            if ([Environment]::GetEnvironmentVariable($name) -cne ('SYNTHETIC-PREVIOUS-' + $name)) { throw ('Release source context was not restored: ' + $name) }
        }
    }
    Write-Output 'Release source-context success/catalogue-failure/web-failure cases passed; canonical source-test prefix only, no native commands or signing.'
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
