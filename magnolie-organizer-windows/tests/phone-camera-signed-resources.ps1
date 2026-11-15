# BCL-generated inert managed PE fixtures; never Assembly.Load, native execution,
# signing, registry access or certificates. This checks byte identity only.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/PhonePayloadSigning.Common.ps1')
. (Join-Path $PSScriptRoot '../build/PhonePayloadResources.Common.ps1')
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-signed-resources-' + [guid]::NewGuid().ToString('N'))
$fixtureName = 'Magnolie.Inert.Signing.Resource.Fixture'
function Fixture-Hash([byte[]]$Bytes) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }
function Write-ManagedFixture([string]$Path, $Resources) {
    $metadata = [System.Reflection.Metadata.Ecma335.MetadataBuilder]::new()
    $null = $metadata.AddModule(0, $metadata.GetOrAddString('fixture.dll'), $metadata.GetOrAddGuid([guid]::NewGuid()),
        [System.Reflection.Metadata.GuidHandle]::new(), [System.Reflection.Metadata.GuidHandle]::new())
    $null = $metadata.AddAssembly($metadata.GetOrAddString($fixtureName), [Version]::new(1, 0, 0, 0),
        [System.Reflection.Metadata.StringHandle]::new(), [System.Reflection.Metadata.BlobHandle]::new(),
        [System.Reflection.AssemblyFlags]0, [System.Reflection.AssemblyHashAlgorithm]0)
    $null = $metadata.AddTypeDefinition([Reflection.TypeAttributes]0, [System.Reflection.Metadata.StringHandle]::new(),
        $metadata.GetOrAddString('<Module>'), [System.Reflection.Metadata.EntityHandle]::new(),
        [System.Reflection.Metadata.Ecma335.MetadataTokens]::FieldDefinitionHandle(1),
        [System.Reflection.Metadata.Ecma335.MetadataTokens]::MethodDefinitionHandle(1))
    $resourcesBlob = [System.Reflection.Metadata.BlobBuilder]::new()
    foreach ($resource in $Resources) {
        $offset = [uint32]$resourcesBlob.Count
        $resourcesBlob.WriteInt32($resource.Bytes.Length)
        $resourcesBlob.WriteBytes([byte[]]$resource.Bytes)
        $implementation = [System.Reflection.Metadata.EntityHandle]::new()
        if ($resource.Linked) {
            $file = $metadata.AddAssemblyFile($metadata.GetOrAddString('external-never-followed.dll'), [System.Reflection.Metadata.BlobHandle]::new(), $false)
            $implementation = [System.Reflection.Metadata.EntityHandle]$file
        }
        $null = $metadata.AddManifestResource([Reflection.ManifestResourceAttributes]::Public,
            $metadata.GetOrAddString($resource.Name), $implementation, $offset)
    }
    $builder = [System.Reflection.PortableExecutable.ManagedPEBuilder]::new(
        [System.Reflection.PortableExecutable.PEHeaderBuilder]::CreateLibraryHeader(),
        [System.Reflection.Metadata.Ecma335.MetadataRootBuilder]::new($metadata, 'v4.0.30319', $false),
        [System.Reflection.Metadata.BlobBuilder]::new(), $null, $resourcesBlob, $null, $null, 0,
        [System.Reflection.Metadata.MethodDefinitionHandle]::new(), [System.Reflection.PortableExecutable.CorFlags]::ILOnly, $null)
    $output = [System.Reflection.Metadata.BlobBuilder]::new()
    $null = $builder.Serialize($output)
    [IO.File]::WriteAllBytes($Path, $output.ToArray())
}
try {
    if (@([AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq $fixtureName }).Count) { throw 'Inert fixture was unexpectedly loaded before tests.' }
    $specs = @(Get-PhonePayloadSigningSpecifications)
    $count = 0
    foreach ($case in @('all', 'helper-only', 'empty', 'ordinary-resource', 'missing-binary', 'missing-manifest',
        'wrong-binary', 'wrong-manifest', 'missing-sidecar', 'wrong-sidecar', 'stale-input', 'stale-descriptor',
        'unknown-pe', 'duplicate-resource', 'linked-resource', 'bad-pe', 'outside-assembly', 'duplicate-prepared',
        'unknown-prepared', 'extra-input', 'escaped-input', 'case-changed-resource', 'oversized-descriptor')) {
        $root = Join-Path $temp $case
        $publish = Join-Path $root 'publish'
        $stage = Join-Path $root 'prepared'
        [IO.Directory]::CreateDirectory($publish) | Out-Null
        $inputs = @{}
        $payloads = @()
        $resources = [Collections.Generic.List[object]]::new()
        $selected = if ($case -eq 'empty') { @() } elseif ($case -in @('helper-only', 'ordinary-resource')) { @($specs[0]) } else { $specs }
        foreach ($spec in $selected) {
            $directory = Join-Path (Join-Path $stage 'rechecked') $spec.Folder
            [IO.Directory]::CreateDirectory($directory) | Out-Null
            $bytes = [Text.Encoding]::ASCII.GetBytes('MZsynthetic-signed-' + $spec.Folder)
            $descriptor = [Text.Encoding]::UTF8.GetBytes("synthetic-source-descriptor`nsha256=$(Fixture-Hash $bytes)`n")
            if ($case -eq 'oversized-descriptor') { $descriptor = [byte[]]::new(8193) }
            [IO.File]::WriteAllBytes((Join-Path $directory $spec.Binary), $bytes)
            [IO.File]::WriteAllBytes((Join-Path $directory $spec.Manifest), $descriptor)
            $inputs[$spec.Property] = $directory
            $payloads += [pscustomobject]@{ Property = $spec.Property; Binary = $spec.Binary; Manifest = $spec.Manifest;
                ManifestResource = $spec.Resource; Sha256 = (Fixture-Hash $bytes); ManifestSha256 = (Fixture-Hash $descriptor) }
            $resources.Add([pscustomobject]@{ Name = $spec.Binary; Bytes = $bytes; Linked = $false })
            $resources.Add([pscustomobject]@{ Name = $spec.Resource; Bytes = $descriptor; Linked = $false })
            if ($spec.Property -ne 'MagnoliePhoneCameraHelperDirectory') { [IO.File]::WriteAllBytes((Join-Path $publish $spec.Binary), $bytes) }
        }
        if ($case -eq 'ordinary-resource') { $resources.Add([pscustomobject]@{ Name = 'ordinary.json'; Bytes = [Text.Encoding]::ASCII.GetBytes('{}'); Linked = $false }) }
        if ($case -eq 'missing-binary') { $resources.RemoveAt(0) }
        if ($case -eq 'missing-manifest') { $resources.RemoveAt(1) }
        if ($case -eq 'wrong-binary') { $resources[0].Bytes = [Text.Encoding]::ASCII.GetBytes('MZwrong-embedded') }
        if ($case -eq 'wrong-manifest') { $resources[1].Bytes = [Text.Encoding]::ASCII.GetBytes('wrong descriptor') }
        if ($case -eq 'missing-sidecar') { Remove-Item -LiteralPath (Join-Path $publish $specs[1].Binary) }
        if ($case -eq 'wrong-sidecar') { [IO.File]::AppendAllText((Join-Path $publish $specs[1].Binary), 'changed') }
        if ($case -eq 'stale-input') { [IO.File]::AppendAllText((Join-Path $inputs[$specs[0].Property] $specs[0].Binary), 'changed') }
        if ($case -eq 'stale-descriptor') { [IO.File]::AppendAllText((Join-Path $inputs[$specs[0].Property] $specs[0].Manifest), 'changed') }
        if ($case -eq 'unknown-pe') { $resources.Add([pscustomobject]@{ Name = 'unknown-native'; Bytes = [Text.Encoding]::ASCII.GetBytes('MZunknown'); Linked = $false }) }
        if ($case -eq 'duplicate-resource') { $resources.Add($resources[0]) }
        if ($case -eq 'linked-resource') { $resources[0].Linked = $true }
        if ($case -eq 'duplicate-prepared') { $payloads[3] = $payloads[0] }
        if ($case -eq 'unknown-prepared') { $payloads[0].Binary = 'unknown-file.exe' }
        if ($case -eq 'extra-input') { $inputs['Unknown'] = $root }
        if ($case -eq 'escaped-input') { $inputs[$specs[0].Property] = $publish }
        if ($case -eq 'case-changed-resource') { $resources[0].Name = $resources[0].Name.ToLowerInvariant() }
        $assembly = Join-Path $publish 'fixture.dll'
        Write-ManagedFixture $assembly $resources
        if ($case -eq 'bad-pe') { [IO.File]::WriteAllText($assembly, 'not a PE') }
        if ($case -eq 'outside-assembly') { $assembly = Join-Path $root 'outside.dll'; [IO.File]::Copy((Join-Path $publish 'fixture.dll'), $assembly) }
        $prepared = [pscustomobject]@{ Stage = $stage; Inputs = $inputs; Payloads = $payloads }
        $passed = $true
        $failure = ''
        try { $report = Assert-PreparedPhonePayloadResources -AssemblyPath $assembly -PublishRoot $publish -Prepared $prepared }
        catch { $passed = $false; $failure = $_.Exception.Message }
        $expected = $case -in @('all', 'helper-only', 'empty', 'ordinary-resource')
        if ($passed -ne $expected) { throw "Managed resource identity mismatch: $case ($failure)" }
        if ($expected) {
            if (-not $report.IdentityOnly -or $report.Payloads -ne $payloads.Count -or $report.ManagedResources -ne 2 * $payloads.Count) { throw 'Resource report overstated its identity-only scope.' }
            $expectedSidecars = if ($case -eq 'all') { 3 } else { 0 }
            if ($report.Sidecars -ne $expectedSidecars) { throw 'Embedded-only helper or required sidecar handling changed.' }
        }
        if (@([AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq $fixtureName }).Count) { throw 'Product/fixture assembly was loaded instead of inspected as metadata.' }
        $count++
    }
    Write-Host "$count managed-resource identity cases passed with inert metadata fixtures; no assembly loading/signing/native acceptance."
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
