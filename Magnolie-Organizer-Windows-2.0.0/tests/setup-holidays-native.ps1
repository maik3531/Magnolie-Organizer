param([Parameter(Mandatory=$true)][string] $TemporaryRoot,
      [Parameter(Mandatory=$true)][string] $WindowsDesktopReferences)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
[void][IO.Directory]::CreateDirectory($TemporaryRoot)
$files = @('FirstRunSetupState.cs', 'WindowsPaths.cs', 'AtomicStore.cs', 'NativeLocalization.cs',
           'tests/FirstRunSetupTests.cs', 'tests/TestRunner.cs', 'tests/setup-holidays-native.cs.txt') |
    ForEach-Object { Join-Path $root $_ }
# PowerShell's bundled Roslyn/.NET compiles the canonical C# without SDK downloads.
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll')
Add-Type -Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll')
function Compile($sources, $references, $output, $extraSource = '') {
    $parse = [Microsoft.CodeAnalysis.CSharp.CSharpParseOptions]::Default.WithLanguageVersion(
        [Microsoft.CodeAnalysis.CSharp.LanguageVersion]::Preview)
    $trees = [Microsoft.CodeAnalysis.SyntaxTree[]] @($sources | ForEach-Object {
        [Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText($_), $parse, $_)
    })
    if ($extraSource) { $trees += [Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText($extraSource, $parse) }
    $metadata = [Microsoft.CodeAnalysis.MetadataReference[]] @($references | ForEach-Object {
        [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($_)
    })
    $options = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new(
        [Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary).WithNullableContextOptions(
        [Microsoft.CodeAnalysis.NullableContextOptions]::Enable)
    $compilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create(
        ('SetupHolidayProbe' + [Guid]::NewGuid().ToString('N')), [Microsoft.CodeAnalysis.SyntaxTree[]]$trees, $metadata, $options)
    $stream = [IO.MemoryStream]::new()
    $result = $compilation.Emit($stream)
    if (-not $result.Success) { throw ($result.Diagnostics -join "`n") }
    $bytes = $stream.ToArray()
    if ($output) { [IO.File]::WriteAllBytes($output, $bytes) }
    else { return [Reflection.Assembly]::Load($bytes) }
}
$refs = @(Get-ChildItem (Join-Path $PSHOME 'ref') -Filter '*.dll' | ForEach-Object FullName)
$coreRefs = $refs
$assembly = Compile $files $refs $null
[void]$assembly.GetType('MagnolieOrganizer.Windows.SetupHolidayProbe').GetMethod('Run').Invoke(
    $null, [object[]]@([string]$TemporaryRoot, [string][IO.Path]::Combine($root, 'app')))
$refs = @($refs | Where-Object { [IO.Path]::GetFileName($_) -notin @('System.Drawing.dll', 'System.Drawing.Primitives.dll') })
$refs += @(Get-ChildItem $WindowsDesktopReferences -Filter '*.dll' | Where-Object {
    $_.Name -in @('System.Windows.Forms.dll', 'System.Windows.Forms.Primitives.dll', 'System.Drawing.Common.dll', 'Accessibility.dll')
} | ForEach-Object FullName)
$refs += Join-Path $PSHOME 'ref/System.Drawing.Primitives.dll'
$formFiles = $files + @('FirstRunSetupForm.cs', 'FirstRunSetupUiSelfTest.cs', 'LibreOfficeUserData.cs',
    'tests/setup-holidays-form-stubs.cs.txt' | ForEach-Object { Join-Path $root $_ })
Compile $formFiles $refs (Join-Path $TemporaryRoot 'setup-form-compile-only.dll')
Write-Output 'Canonical WinForms setup and native GUI assertions compiled against Windows reference assemblies. GUI execution pending Windows.'
$tree = [Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText([IO.File]::ReadAllText((Join-Path $root 'BridgeDispatcher.cs')))
$members = @($tree.GetRoot().DescendantNodes() | Where-Object {
    ($_.GetType().Name -eq 'MethodDeclarationSyntax' -and $_.Identifier.ValueText -in @(
        'FetchHolidaysAsync', 'AddHolidayEntriesAsync', 'LocalizedName', 'PropertyText', 'Text', 'Boolean')) -or
    ($_.GetType().Name -eq 'RecordDeclarationSyntax' -and $_.Identifier.ValueText -in @('HolidayRegion', 'HolidayEntry')) -or
    ($_.GetType().Name -eq 'FieldDeclarationSyntax' -and $_.Declaration.Variables[0].Identifier.ValueText -eq 'HolidayDownloadMaxBytes')
})
if ($members.Count -ne 9) { throw 'Actual provider members changed; update the scoped compiler.' }
$source = 'namespace MagnolieOrganizer.Windows; public sealed partial class SetupHolidayProviderProbe {' +
    (($members | ForEach-Object ToFullString) -join "`n") + '}'
$provider = Compile ($files + (Join-Path $root 'tests/setup-holidays-provider.cs.txt')) $coreRefs $null $source
$task = $provider.GetType('MagnolieOrganizer.Windows.SetupHolidayProviderProbe').GetMethod('Run').Invoke($null, $null)
[void]$task.GetAwaiter().GetResult()
