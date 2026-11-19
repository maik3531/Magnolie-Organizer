# Preparation only. No work at import time, key creation, native artifact build,
# runtime registration or release permission. Both callbacks are native-build owned.
function Get-PhonePayloadSigningSpecifications {
    return @(
        @{ Property = 'MagnoliePhoneCameraHelperDirectory'; Target = 'PreparePhoneAudioHelperResource'; Folder = 'phone-audio-helper'; Binary = 'Magnolie.PhoneAudioSetup.x64.exe'; Manifest = 'phone-audio-helper.manifest'; Resource = 'Magnolie.PhoneAudioSetup.manifest' },
        @{ Property = 'MagnoliePhoneCameraRuntimeDirectory'; Target = 'PreparePhoneAudioRuntimeResource'; Folder = 'phone-audio-runtime'; Binary = 'Magnolie.PhoneAudioWorker.x64.exe'; Manifest = 'phone-audio-runtime.manifest'; Resource = 'Magnolie.PhoneAudioWorker.manifest' },
        @{ Property = 'MagnoliePhoneCameraParentDirectory'; Target = 'PreparePhoneAudioParentResource'; Folder = 'phone-audio-parent'; Binary = 'Magnolie.PhoneAudioParent.x64.dll'; Manifest = 'phone-audio-parent.manifest'; Resource = 'Magnolie.PhoneAudioParent.manifest' },
        @{ Property = 'MagnoliePhoneCameraSourceDirectory'; Target = 'PreparePhoneCameraSourceResource'; Folder = 'phone-camera-source'; Binary = 'Magnolie.PhoneCameraSource.x64.dll'; Manifest = 'phone-camera-source.manifest'; Resource = 'Magnolie.PhoneCameraSource.manifest' }
    )
}

function New-VerifiedSignedPhoneInputs {
    param(
        [Parameter(Mandatory)][string] $BuildRoot,
        [Parameter(Mandatory)][string] $Stage,
        [Parameter(Mandatory)][AllowEmptyCollection()][Collections.IDictionary] $Inputs,
        [Parameter(Mandatory)][scriptblock] $SnapshotRunner,
        [Parameter(Mandatory)][scriptblock] $SignSnapshot
    )
    $specifications = @(Get-PhonePayloadSigningSpecifications)
    function Checked-Path([string] $Value) {
        if (-not [IO.Path]::IsPathFullyQualified($Value) -or $Value -match '[;,%$@"\r\n]') {
            throw 'A fully qualified path without MSBuild metacharacters is required.'
        }
        return [IO.Path]::GetFullPath($Value)
    }
    $root = Checked-Path $BuildRoot
    $stagePath = Checked-Path $Stage
    $project = Join-Path $root 'MagnolieOrganizer.Windows.csproj'
    if (-not (Test-Path -LiteralPath $project -PathType Leaf)) { throw 'Canonical build project is required.' }
    $selectedInputs = @{}
    foreach ($key in $Inputs.Keys) {
        $known = @($specifications | Where-Object { $_.Property -eq $key })
        if ($known.Count -ne 1 -or $selectedInputs.ContainsKey($known[0].Property) -or $Inputs[$key] -isnot [string]) { throw 'Unknown or repeated native input property.' }
        $inputPath = Checked-Path $Inputs[$key]
        if (-not (Test-Path -LiteralPath $inputPath -PathType Container)) { throw 'Native artifact input directory is missing.' }
        $prefix = $inputPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if ($stagePath.Equals($inputPath, [StringComparison]::OrdinalIgnoreCase) -or $stagePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Signed preparation cannot write inside the original input directory.'
        }
        $selectedInputs[$known[0].Property] = $inputPath
    }
    $selected = @($specifications | Where-Object { $selectedInputs.ContainsKey($_.Property) })
    if ($selected.Count -eq 0) { return [pscustomobject]@{ Stage = $null; Inputs = @{}; Payloads = @() } }
    if (Test-Path -LiteralPath $stagePath) { throw 'Signed preparation stage already exists; preserve it.' }
    $created = $false
    try {
        New-Item -ItemType Directory -Path $stagePath -ErrorAction Stop | Out-Null
        $created = $true
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $hashPattern = '(?m)^sha256=([0-9a-f]{64})(?=\r?$)'
        function Snapshot-Arguments($Directories, [string] $Output) {
            $arguments = @('msbuild', $project, ('-target:' + (($selected | ForEach-Object { $_.Target }) -join ';')),
                '-nologo', '-m:1', '-nodeReuse:false', '-p:Configuration=Release', '-p:UseSharedCompilation=false',
                '-p:MAGNOLIE_OFFICIAL_RELEASE=0', '-p:MagnoliePhoneCamera=true',
                ('-p:IntermediateOutputPath=' + $Output + [IO.Path]::DirectorySeparatorChar))
            # Clear every unselected inherited property. This process only runs
            # the existing source-verification/snapshot targets, never publish.
            foreach ($spec in $specifications) {
                $value = if ($Directories.ContainsKey($spec.Property)) { $Directories[$spec.Property] } else { '' }
                $arguments += '-p:' + $spec.Property + '=' + $value
            }
            return ,$arguments
        }
        $verified = Join-Path $stagePath 'verified'
        $null = & $SnapshotRunner (Snapshot-Arguments $selectedInputs $verified)
        $records = @()
        foreach ($spec in $selected) {
            $directory = Join-Path $verified $spec.Folder
            $binary = Join-Path $directory $spec.Binary
            $descriptor = Join-Path $directory $spec.Manifest
            foreach ($file in @($binary, $descriptor)) {
                $item = Get-Item -LiteralPath $file -ErrorAction Stop
                if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Verified snapshot must contain regular files.' }
            }
            $hash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
            $bytes = [IO.File]::ReadAllBytes($descriptor)
            $text = $utf8.GetString($bytes)
            $matches = [regex]::Matches($text, $hashPattern)
            if ($matches.Count -ne 1 -or $matches[0].Groups[1].Value -ne $hash) { throw 'Source-verified snapshot descriptor changed.' }
            $records += [pscustomobject]@{ Spec = $spec; Binary = $binary; Descriptor = $descriptor; OriginalHash = $hash; DescriptorBytes = $bytes; DescriptorText = $text }
        }
        # ALL source-bound snapshots must be verified before the first signing
        # callback. Original inputs and verified snapshots are never modified.
        $signedInputs = @{}
        foreach ($record in $records) {
            $directory = Join-Path (Join-Path $stagePath 'signed') $record.Spec.Folder
            [IO.Directory]::CreateDirectory($directory) | Out-Null
            $binary = Join-Path $directory $record.Spec.Binary
            $descriptor = Join-Path $directory $record.Spec.Manifest
            Copy-Item -LiteralPath $record.Binary -Destination $binary
            [IO.File]::WriteAllBytes($descriptor, $record.DescriptorBytes)
            if ((Get-FileHash -LiteralPath $binary).Hash.ToLowerInvariant() -ne $record.OriginalHash) { throw 'Snapshot copy changed before signing.' }
            $null = & $SignSnapshot $binary
            if (-not [Linq.Enumerable]::SequenceEqual([byte[]][IO.File]::ReadAllBytes($descriptor), [byte[]]$record.DescriptorBytes)) { throw 'Signing callback changed source descriptor fields.' }
            $signedHash = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
            $updated = [regex]::Replace($record.DescriptorText, $hashPattern, ('sha256=' + $signedHash))
            [IO.File]::WriteAllBytes($descriptor, $utf8.GetBytes($updated))
            $record | Add-Member -NotePropertyName SignedHash -NotePropertyValue $signedHash
            $record | Add-Member -NotePropertyName SignedDescriptor -NotePropertyValue $utf8.GetBytes($updated)
            $signedInputs[$record.Spec.Property] = $directory
        }
        foreach ($record in $records) {
            if ((Get-FileHash -LiteralPath $record.Binary).Hash.ToLowerInvariant() -ne $record.OriginalHash -or
                -not [Linq.Enumerable]::SequenceEqual([byte[]][IO.File]::ReadAllBytes($record.Descriptor), [byte[]]$record.DescriptorBytes)) { throw 'A verified source snapshot was modified.' }
        }
        # Reuse the SAME canonical validators on signed copies. Only their own
        # binary checksum changed; all required source/header fields must match.
        $checked = Join-Path $stagePath 'rechecked'
        $null = & $SnapshotRunner (Snapshot-Arguments $signedInputs $checked)
        $resultInputs = @{}
        $payloads = @()
        foreach ($record in $records) {
            $directory = Join-Path $checked $record.Spec.Folder
            $binary = Join-Path $directory $record.Spec.Binary
            $descriptor = Join-Path $directory $record.Spec.Manifest
            if ((Get-FileHash -LiteralPath $binary).Hash.ToLowerInvariant() -ne $record.SignedHash -or
                -not [Linq.Enumerable]::SequenceEqual([byte[]][IO.File]::ReadAllBytes($descriptor), [byte[]]$record.SignedDescriptor)) { throw 'Signed snapshot changed during source revalidation.' }
            $resultInputs[$record.Spec.Property] = $directory
            $payloads += [pscustomobject]@{ Property = $record.Spec.Property; Binary = $record.Spec.Binary; Manifest = $record.Spec.Manifest;
                ManifestResource = $record.Spec.Resource; Sha256 = $record.SignedHash;
                ManifestSha256 = (Get-FileHash -LiteralPath $descriptor -Algorithm SHA256).Hash.ToLowerInvariant() }
        }
        return [pscustomobject]@{ Stage = $stagePath; Inputs = $resultInputs; Payloads = $payloads }
    } catch {
        if ($created -and (Test-Path -LiteralPath $stagePath)) { Remove-Item -LiteralPath $stagePath -Recurse -Force }
        throw
    }
}

# Argument construction is identity-only, not a bypass for the independent
# official MSBuild signing hold. Clear every inherited unselected property.
function Get-PreparedPhonePublishArguments {
    param([Parameter(Mandatory)] $Prepared)
    $specifications = @(Get-PhonePayloadSigningSpecifications)
    $payloads = @($Prepared.Payloads)
    if ($Prepared.Inputs.Count -ne $payloads.Count) { throw 'Prepared publish inventory is incomplete.' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($payload in $payloads) {
        $known = @($specifications | Where-Object { $_.Property -ceq $payload.Property })
        if ($known.Count -ne 1 -or -not $seen.Add($payload.Property) -or
            -not $Prepared.Inputs.ContainsKey($payload.Property) -or
            $payload.Binary -cne $known[0].Binary -or $payload.Manifest -cne $known[0].Manifest -or
            $payload.ManifestResource -cne $known[0].Resource) { throw 'Unknown or duplicate prepared publish payload.' }
        if (-not [IO.Path]::IsPathFullyQualified($Prepared.Stage) -or $Prepared.Stage -match '[;,%$@"\r\n]') { throw 'Unsafe prepared publish stage.' }
        $bound = [IO.Path]::GetFullPath((Join-Path (Join-Path $Prepared.Stage 'rechecked') $known[0].Folder))
        if ($Prepared.Inputs[$payload.Property] -cne $bound) { throw 'Publish input escaped its rechecked snapshot.' }
        foreach ($entry in @(@($payload.Binary, $payload.Sha256), @($payload.Manifest, $payload.ManifestSha256))) {
            $item = Get-Item -LiteralPath (Join-Path $bound $entry[0]) -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[1]) {
                throw 'Prepared publish snapshot changed after validation.'
            }
        }
    }
    foreach ($spec in $specifications) {
        $directory = if ($Prepared.Inputs.ContainsKey($spec.Property)) { $Prepared.Inputs[$spec.Property] } else { '' }
        '-p:' + $spec.Property + '=' + $directory
    }
}
