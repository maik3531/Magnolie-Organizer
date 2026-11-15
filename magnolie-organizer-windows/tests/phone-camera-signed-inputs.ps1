# Preparation unit tests only. Snapshot validation and signing callbacks are
# controlled dependencies, not real MSBuild/source/signature acceptance.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/PhonePayloadSigning.Common.ps1')
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-signed-inputs-' + [guid]::NewGuid().ToString('N'))
$specs = @(
    @('MagnoliePhoneCameraHelperDirectory', 'phone-audio-helper', 'Magnolie.PhoneAudioSetup.x64.exe', 'phone-audio-helper.manifest'),
    @('MagnoliePhoneCameraRuntimeDirectory', 'phone-audio-runtime', 'Magnolie.PhoneAudioWorker.x64.exe', 'phone-audio-runtime.manifest'),
    @('MagnoliePhoneCameraParentDirectory', 'phone-audio-parent', 'Magnolie.PhoneAudioParent.x64.dll', 'phone-audio-parent.manifest'),
    @('MagnoliePhoneCameraSourceDirectory', 'phone-camera-source', 'Magnolie.PhoneCameraSource.x64.dll', 'phone-camera-source.manifest')
)
try {
    $buildRoot = Join-Path $temp 'source'
    [IO.Directory]::CreateDirectory($buildRoot) | Out-Null
    [IO.File]::WriteAllText((Join-Path $buildRoot 'MagnolieOrganizer.Windows.csproj'), '<Project />')
    $originals = @{}
    foreach ($spec in $specs) {
        $directory = Join-Path (Join-Path $temp 'originals') $spec[1]
        [IO.Directory]::CreateDirectory($directory) | Out-Null
        $image = Join-Path $directory $spec[2]
        $manifest = Join-Path $directory $spec[3]
        [IO.File]::WriteAllText($image, 'MZsynthetic-input-' + $spec[1])
        $hash = (Get-FileHash -LiteralPath $image).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText($manifest, "synthetic-source-checked-fixture`narchitecture=x64`nsha256=$hash`nsource=fixture.cc|$('a' * 64)`n", [Text.UTF8Encoding]::new($false))
        $originals[$spec[0]] = $directory
    }
    $originalHashes = @{}
    Get-ChildItem -LiteralPath (Join-Path $temp 'originals') -File -Recurse | ForEach-Object { $originalHashes[$_.FullName] = (Get-FileHash -LiteralPath $_.FullName).Hash }
    $count = 0
    foreach ($scenario in @('all', 'helper', 'runtime', 'parent', 'source', 'empty', 'verify-failure', 'bad-descriptor',
        'sign-failure', 'descriptor-tamper', 'recheck-failure', 'recheck-tamper', 'unknown-property', 'unsafe-path', 'unsafe-comma', 'inside-original', 'reused-stage', 'missing-input')) {
        $script:preparationScenario = $scenario
        $script:snapshotCalls = 0
        $script:signCalls = 0
        $script:trace = [Collections.Generic.List[string]]::new()
        $inputs = @{}
        if ($scenario -ne 'empty') {
            $chosen = switch ($scenario) { 'helper' { @(0) }; 'runtime' { @(1) }; 'parent' { @(2) }; 'source' { @(3) }; default { @(0, 1, 2, 3) } }
            foreach ($index in $chosen) { $inputs[$specs[$index][0]] = $originals[$specs[$index][0]] }
        }
        $stage = Join-Path (Join-Path $temp 'stages') $scenario
        if ($scenario -eq 'unknown-property') { $inputs = @{ UnknownProperty = $originals[$specs[0][0]] } }
        if ($scenario -eq 'unsafe-path') { $inputs[$specs[0][0]] = Join-Path $temp 'input;Unexpected=1' }
        if ($scenario -eq 'unsafe-comma') {
            $inputs[$specs[0][0]] = Join-Path $temp 'input,Unexpected=1'
            [IO.Directory]::CreateDirectory($inputs[$specs[0][0]]) | Out-Null
        }
        if ($scenario -eq 'missing-input') { $inputs[$specs[0][0]] = Join-Path $temp 'missing' }
        if ($scenario -eq 'inside-original') { $stage = Join-Path $originals[$specs[0][0]] 'do-not-write-here' }
        if ($scenario -eq 'reused-stage') { [IO.Directory]::CreateDirectory($stage) | Out-Null; [IO.File]::WriteAllText((Join-Path $stage 'preserve.txt'), 'foreign-control') }
        $snapshot = {
            param([string[]]$Arguments)
            $script:snapshotCalls++
            $script:trace.Add('verify-' + $script:snapshotCalls)
            if ($Arguments[0] -ne 'msbuild' -or $Arguments -notcontains '-p:MAGNOLIE_OFFICIAL_RELEASE=0' -or
                $Arguments -notcontains '-m:1' -or $Arguments -notcontains '-nodeReuse:false' -or $Arguments -contains 'publish') { throw 'Wrong source-only validation command.' }
            if ($script:preparationScenario -eq 'verify-failure' -or
                ($script:preparationScenario -eq 'recheck-failure' -and $script:snapshotCalls -eq 2)) { throw 'Controlled source validation failure' }
            $output = ($Arguments | Where-Object { $_.StartsWith('-p:IntermediateOutputPath=') }).Substring('-p:IntermediateOutputPath='.Length)
            foreach ($spec in $specs) {
                $property = '-p:' + $spec[0] + '='
                $values = @($Arguments | Where-Object { $_.StartsWith($property) })
                if ($values.Count -ne 1) { throw 'An inherited native property was not explicitly bounded.' }
                $from = $values[0].Substring($property.Length)
                if (-not $from) { continue }
                $to = Join-Path $output $spec[1]
                [IO.Directory]::CreateDirectory($to) | Out-Null
                $image = Join-Path $from $spec[2]
                $descriptor = Join-Path $from $spec[3]
                $text = [IO.File]::ReadAllText($descriptor)
                $hash = (Get-FileHash -LiteralPath $image).Hash.ToLowerInvariant()
                if ($text -notmatch ('(?m)^sha256=' + $hash + '$') -or $text -notmatch ('source=fixture.cc\|' + ('a' * 64))) { throw 'Descriptor source/hash changed before validation.' }
                Copy-Item -LiteralPath $image -Destination $to
                Copy-Item -LiteralPath $descriptor -Destination $to
                if ($script:preparationScenario -eq 'bad-descriptor' -and $script:snapshotCalls -eq 1) {
                    [IO.File]::WriteAllText((Join-Path $to $spec[3]), $text.Replace($hash, ('0' * 64)))
                }
                if ($script:preparationScenario -eq 'recheck-tamper' -and $script:snapshotCalls -eq 2) {
                    [IO.File]::AppendAllText((Join-Path $to $spec[2]), 'tampered')
                }
            }
        }
        $sign = {
            param($Path)
            if ($script:snapshotCalls -ne 1) { throw 'Signing preceded complete source validation.' }
            if ($Path -notmatch '[\\/]signed[\\/]') { throw 'Signing callback received an original or verified input.' }
            $script:signCalls++
            $script:trace.Add('sign')
            if ($script:preparationScenario -eq 'sign-failure') { throw 'Controlled signing failure' }
            [IO.File]::AppendAllText($Path, '-synthetic-signature')
            if ($script:preparationScenario -eq 'descriptor-tamper') {
                $descriptor = Get-ChildItem -LiteralPath ([IO.Path]::GetDirectoryName($Path)) -Filter '*.manifest'
                [IO.File]::AppendAllText($descriptor.FullName, 'wrong-source')
            }
        }
        $passed = $true
        $result = $null
        $failure = ''
        try { $result = New-VerifiedSignedPhoneInputs -BuildRoot $buildRoot -Stage $stage -Inputs $inputs -SnapshotRunner $snapshot -SignSnapshot $sign }
        catch { $passed = $false; $failure = $_.Exception.Message }
        $expected = $scenario -in @('all', 'helper', 'runtime', 'parent', 'source', 'empty')
        if ($passed -ne $expected) { throw "Preparation result mismatch: $scenario ($failure)" }
        foreach ($file in $originalHashes.Keys) { if ((Get-FileHash -LiteralPath $file).Hash -ne $originalHashes[$file]) { throw 'Original input was modified.' } }
        if ($expected) {
            $publishArguments = @(Get-PreparedPhonePublishArguments $result)
            if ($publishArguments.Count -ne 4) { throw 'Publish did not bound all four inherited native properties.' }
            foreach ($spec in $specs) {
                $directory = if ($result.Inputs.ContainsKey($spec[0])) { $result.Inputs[$spec[0]] } else { '' }
                if ($publishArguments -cnotcontains ('-p:' + $spec[0] + '=' + $directory)) { throw 'Publish used an original, missing or unselected input.' }
            }
            if ($scenario -eq 'empty') {
                if ($script:snapshotCalls -or $script:signCalls -or (Test-Path -LiteralPath $stage)) { throw 'Empty preparation performed work.' }
            } else {
                if ($script:snapshotCalls -ne 2 -or $script:signCalls -ne $inputs.Count -or $result.Payloads.Count -ne $inputs.Count) { throw 'Missing validation/signing/revalidation phase.' }
                if ($script:trace[0] -ne 'verify-1' -or $script:trace[$script:trace.Count - 1] -ne 'verify-2') { throw 'Wrong phase ordering.' }
                foreach ($payload in $result.Payloads) {
                    $spec = @($specs | Where-Object { $_[2] -eq $payload.Binary })[0]
                    $directory = $result.Inputs[$spec[0]]
                    if ((Get-FileHash -LiteralPath (Join-Path $directory $payload.Binary)).Hash.ToLowerInvariant() -ne $payload.Sha256 -or
                        -not [IO.File]::ReadAllText((Join-Path $directory $payload.Binary)).EndsWith('-synthetic-signature')) { throw 'Rechecked bytes are not the signed snapshot.' }
                }
                $first = $result.Payloads[0]
                $pinned = $result.Inputs[$first.Property]
                $result.Inputs[$first.Property] = $originals[$first.Property]
                $rejected = $false
                try { $null = Get-PreparedPhonePublishArguments $result } catch { $rejected = $true }
                if (-not $rejected) { throw 'Publish arguments accepted an original input instead of the signed snapshot.' }
                $result.Inputs[$first.Property] = $pinned
                $originalStage = $result.Stage
                $result.Stage = $result.Stage + ',Unexpected=1'
                $stageFailure = ''
                try { $null = Get-PreparedPhonePublishArguments $result } catch { $stageFailure = $_.Exception.Message }
                if ($stageFailure -ne 'Unsafe prepared publish stage.') { throw 'Publish did not reject a comma-separated MSBuild property injection at the path boundary.' }
                $result.Stage = $originalStage
                [IO.File]::AppendAllText((Join-Path $pinned $first.Binary), 'post-verification-tamper')
                $rejected = $false
                try { $null = Get-PreparedPhonePublishArguments $result } catch { $rejected = $true }
                if (-not $rejected) { throw 'Publish arguments accepted a changed rechecked binary.' }
            }
        } elseif ($scenario -eq 'reused-stage') {
            if ([IO.File]::ReadAllText((Join-Path $stage 'preserve.txt')) -ne 'foreign-control') { throw 'Existing stage was overwritten.' }
        } elseif (Test-Path -LiteralPath $stage) { throw 'Failed preparation left an owned output stage.' }
        if ($scenario -in @('verify-failure', 'bad-descriptor', 'unknown-property', 'unsafe-path', 'unsafe-comma', 'inside-original', 'reused-stage', 'missing-input') -and $script:signCalls) { throw 'Rejected input reached signing.' }
        if ($scenario -eq 'unsafe-comma' -and ($script:snapshotCalls -ne 0 -or $failure -notmatch 'MSBuild metacharacters')) { throw 'Comma path reached MSBuild instead of explicit preflight rejection.' }
        $count++
    }
    Write-Host "$count signed-input preparation cases passed with controlled snapshot/signing callbacks; no real signatures or publication."
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
