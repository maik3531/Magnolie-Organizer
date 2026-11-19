# Identity/readback only, never signature, runtime permission or release authority.
# PEReader reads metadata directly; the product assembly is NEVER loaded/executed.
function Assert-PreparedPhonePayloadResources {
    param(
        [Parameter(Mandatory)][string] $AssemblyPath,
        [Parameter(Mandatory)][string] $PublishRoot,
        [Parameter(Mandatory)] $Prepared
    )
    function Read-RegularBytes([string] $Path, [int] $Maximum) {
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'A regular payload file is required.' }
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            if ($stream.Length -lt 1 -or $stream.Length -gt $Maximum) { throw 'Payload size is outside the source-bound limit.' }
            $memory = [IO.MemoryStream]::new()
            try {
                $buffer = [byte[]]::new(8192)
                while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    if ($memory.Length + $read -gt $Maximum) { throw 'Payload grew beyond its source-bound limit.' }
                    $memory.Write($buffer, 0, $read)
                }
                return ,$memory.ToArray()
            } finally { $memory.Dispose() }
        } finally { $stream.Dispose() }
    }
    function Bytes-Hash([byte[]] $Bytes) { return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant() }
    if (-not [IO.Path]::IsPathFullyQualified($AssemblyPath) -or -not [IO.Path]::IsPathFullyQualified($PublishRoot)) { throw 'Absolute native build paths are required.' }
    $publish = [IO.Path]::GetFullPath($PublishRoot)
    $assembly = [IO.Path]::GetFullPath($AssemblyPath)
    $prefix = $publish.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $assembly.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Managed assembly is outside the publication stage.' }
    $payloads = @($Prepared.Payloads)
    if ($Prepared.Inputs.Count -ne $payloads.Count) { throw 'Incomplete prepared input inventory.' }
    $known = @(Get-PhonePayloadSigningSpecifications)
    $expected = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $properties = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $sidecars = 0
    foreach ($payload in $payloads) {
        $spec = @($known | Where-Object { $_.Binary -ceq $payload.Binary })
        if ($spec.Count -ne 1 -or $payload.Property -cne $spec[0].Property -or
            $payload.Manifest -cne $spec[0].Manifest -or $payload.ManifestResource -cne $spec[0].Resource -or
            -not $properties.Add($payload.Property) -or -not $Prepared.Inputs.ContainsKey($payload.Property)) { throw 'Unknown, duplicate or renamed prepared payload.' }
        if (-not [IO.Path]::IsPathFullyQualified($Prepared.Stage)) { throw 'Owned preparation stage is required.' }
        $directory = [IO.Path]::GetFullPath($Prepared.Inputs[$payload.Property])
        $bound = [IO.Path]::GetFullPath((Join-Path (Join-Path $Prepared.Stage 'rechecked') $spec[0].Folder))
        if (-not $directory.Equals($bound, [StringComparison]::OrdinalIgnoreCase)) { throw 'Prepared input escaped its rechecked snapshot.' }
        $binary = Read-RegularBytes (Join-Path $directory $payload.Binary) (8 * 1024 * 1024)
        $descriptor = Read-RegularBytes (Join-Path $directory $payload.Manifest) 8192
        if ((Bytes-Hash $binary) -cne $payload.Sha256 -or (Bytes-Hash $descriptor) -cne $payload.ManifestSha256) { throw 'Prepared snapshot changed after validation.' }
        $expected.Add($payload.Binary, [pscustomobject]@{ Bytes = $binary; Maximum = 8 * 1024 * 1024 })
        $expected.Add($payload.ManifestResource, [pscustomobject]@{ Bytes = $descriptor; Maximum = 8192 })
        # The setup helper is deliberately embedded-only; the other three
        # existing targets publish a byte-identical sibling as well.
        if ($payload.Property -ne 'MagnoliePhoneCameraHelperDirectory') {
            $sidecar = Read-RegularBytes (Join-Path $publish $payload.Binary) (8 * 1024 * 1024)
            if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$binary, [byte[]]$sidecar)) { throw 'Published sidecar differs from the prepared signed snapshot.' }
            $sidecars++
        }
    }
    $item = Get-Item -LiteralPath $assembly -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'A regular managed artifact is required.' }
    $stream = [IO.File]::Open($assembly, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $pe = $null
    try {
        $pe = [System.Reflection.PortableExecutable.PEReader]::new($stream)
        if (-not $pe.HasMetadata) { throw 'Managed build metadata is required.' }
        $metadata = [System.Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($pe)
        $directory = $pe.PEHeaders.CorHeader.ResourcesDirectory
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $block = if ($directory.Size -gt 0) { $pe.GetSectionData($directory.RelativeVirtualAddress) } else { $null }
        foreach ($handle in $metadata.ManifestResources) {
            $resource = $metadata.GetManifestResource($handle)
            $name = $metadata.GetString($resource.Name)
            if (-not $seen.Add($name)) { throw 'Duplicate managed manifest resource.' }
            if (-not $resource.Implementation.IsNil) { throw 'External manifest resources are not followed or accepted.' }
            if ($null -eq $block -or $resource.Offset -gt [int]::MaxValue -or [long]$resource.Offset + 4 -gt $directory.Size) { throw 'Managed resource offset is invalid.' }
            $reader = $block.GetReader([int]$resource.Offset, $directory.Size - [int]$resource.Offset)
            $length = $reader.ReadUInt32()
            if ($length -gt $reader.RemainingBytes) { throw 'Managed resource size exceeds its directory.' }
            $mz = $false
            if ($length -ge 2) { $first = $reader.ReadByte(); $second = $reader.ReadByte(); $mz = $first -eq 0x4d -and $second -eq 0x5a }
            if (-not $expected.ContainsKey($name)) {
                if ($mz) { throw 'Unknown embedded PE candidate is not covered by the prepared inventory.' }
                continue
            }
            if ($length -lt 1 -or $length -gt $expected[$name].Maximum) { throw 'Expected embedded payload size is invalid.' }
            $body = $block.GetReader([int]$resource.Offset + 4, [int]$length)
            $bytes = $body.ReadBytes([int]$length)
            if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$bytes, [byte[]]$expected[$name].Bytes)) { throw 'Embedded resource differs from the prepared signed snapshot.' }
        }
        foreach ($name in $expected.Keys) { if (-not $seen.Contains($name)) { throw 'A required embedded payload or descriptor is missing.' } }
        return [pscustomobject]@{ Payloads = $payloads.Count; ManagedResources = $expected.Count; Sidecars = $sidecars; IdentityOnly = $true }
    } finally {
        if ($null -ne $pe) { $pe.Dispose() }
        $stream.Dispose()
    }
}
