# Actual MSBuild checks with inert marker/receipt/process fixtures. Only the
# installed verifier-host public signature is checked; no product payload,
# signing key/tool, registry change or installer is used.
param([switch] $VerifierProcessOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-embedded-signing-' + [guid]::NewGuid().ToString('N'))
try {
    [IO.Directory]::CreateDirectory($temp) | Out-Null
    $source = Join-Path $PSScriptRoot '../PhoneCameraSigning.targets'
    $copied = Join-Path $temp 'PhoneCameraSigning.targets'
    Copy-Item -LiteralPath $source -Destination $copied
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $copied).Hash) { throw 'Target source copy changed.' }
    if ((Get-Content -LiteralPath (Join-Path $PSScriptRoot '../MagnolieOrganizer.Windows.csproj') -Raw) -notmatch '<Import Project="PhoneCameraSigning.targets"\s*/>') { throw 'Signing boundary is not imported by the product.' }
    $project = Join-Path $temp 'boundary.proj'
    @'
<Project DefaultTargets="AssignTargetPaths">
  <Import Project="PhoneCameraSigning.targets" />
  <Target Name="AssignTargetPaths" DependsOnTargets="PreparePhoneAudioHelperResource;PreparePhoneAudioRuntimeResource;PreparePhoneAudioParentResource;PreparePhoneCameraSourceResource" />
  <Target Name="PreparePhoneAudioHelperResource" Condition="'$(MagnoliePhoneCameraHelperDirectory)' != ''"><WriteLinesToFile File="$(Marker)" Lines="helper" Overwrite="false" /></Target>
  <Target Name="PreparePhoneAudioRuntimeResource" Condition="'$(MagnoliePhoneCameraRuntimeDirectory)' != ''"><WriteLinesToFile File="$(Marker)" Lines="runtime" Overwrite="false" /></Target>
  <Target Name="PreparePhoneAudioParentResource" Condition="'$(MagnoliePhoneCameraParentDirectory)' != ''"><WriteLinesToFile File="$(Marker)" Lines="parent" Overwrite="false" /></Target>
  <Target Name="PreparePhoneCameraSourceResource" Condition="'$(MagnoliePhoneCameraSourceDirectory)' != ''"><WriteLinesToFile File="$(Marker)" Lines="source" Overwrite="false" /></Target>
</Project>
'@ | Set-Content -LiteralPath $project -Encoding UTF8
    $properties = @('MagnoliePhoneCameraHelperDirectory', 'MagnoliePhoneCameraRuntimeDirectory', 'MagnoliePhoneCameraParentDirectory', 'MagnoliePhoneCameraSourceDirectory')
    $dotnet = (Get-Command dotnet -ErrorAction Stop).Source
    $count = 0
    foreach ($official in @(if (-not $VerifierProcessOnly) { '0'; '1' })) {
        foreach ($selection in @('none', 'helper', 'runtime', 'parent', 'source', 'all')) {
            $marker = Join-Path $temp ("marker-$official-$selection.txt")
            $selected = @(switch ($selection) {
                'none' { @() }
                'helper' { @($properties[0]) }
                'runtime' { @($properties[1]) }
                'parent' { @($properties[2]) }
                'source' { @($properties[3]) }
                'all' { $properties }
            })
            $info = [Diagnostics.ProcessStartInfo]::new($dotnet)
            foreach ($argument in @('msbuild', $project, '-nologo', '-verbosity:minimal', '-m:1', '-nodeReuse:false', "-p:MAGNOLIE_OFFICIAL_RELEASE=$official", "-p:Marker=$marker")) { $info.ArgumentList.Add($argument) }
            foreach ($property in $selected) { $info.ArgumentList.Add("-p:$property=synthetic-input") }
            $info.Environment['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
            $info.Environment['DOTNET_GENERATE_ASPNET_CERTIFICATE'] = 'false'
            $info.Environment['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
            $info.Environment['DOTNET_CLI_HOME'] = Join-Path $temp 'cli-home'
            foreach ($name in @('RECEIPT', 'PUBLISHER', 'TOOL', 'HOST')) { $null = $info.Environment.Remove('MAGNOLIE_PHONE_VERIFY_' + $name) }
            $info.UseShellExecute = $false
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $process = [Diagnostics.Process]::new()
            $process.StartInfo = $info
            try {
                [void]$process.Start()
                $stdout = $process.StandardOutput.ReadToEndAsync()
                $stderr = $process.StandardError.ReadToEndAsync()
                if (-not $process.WaitForExit(15000)) { $process.Kill($true); $process.WaitForExit(); throw 'Owned MSBuild boundary test timeout.' }
                $held = $official -eq '1' -and $selected.Count -gt 0
                if ($held) {
                    if ($process.ExitCode -eq 0 -or ($stdout.Result + $stderr.Result) -notmatch 'MAGNOLIE560') { throw ("Official embedding was not held: $selection; " + $stdout.Result + $stderr.Result) }
                    if (Test-Path -LiteralPath $marker) { throw 'A native embedding target ran before the signing hold.' }
                } else {
                    if ($process.ExitCode -ne 0) { throw ("Ordinary source path changed: $selection; " + $stdout.Result + $stderr.Result) }
                    $lines = if (Test-Path -LiteralPath $marker) { @(Get-Content -LiteralPath $marker) } else { @() }
                    if (@($lines).Count -ne $selected.Count) { throw 'Ordinary embedding target selection changed.' }
                }
            } finally { $process.Dispose() }
            $count++
        }
    }
    # Exercise the real source-bound verifier in a child process with invalid
    # synthetic receipts. Rejection occurs before any signature or tool read.
    $build = Join-Path $temp 'build'
    [IO.Directory]::CreateDirectory($build) | Out-Null
    foreach ($name in @('Release.Common.ps1', 'Signing.Common.ps1', 'PhonePayloadSigning.Common.ps1',
        'PhonePayloadAuthenticode.Common.ps1', 'Verify-PhonePayloadInputs.ps1')) {
        $inputFile = Join-Path $PSScriptRoot "../build/$name"
        Copy-Item -LiteralPath $inputFile -Destination $build
        if ((Get-FileHash -LiteralPath $inputFile).Hash -ne (Get-FileHash -LiteralPath (Join-Path $build $name)).Hash) { throw 'Native verifier source copy changed.' }
    }
    $receipt = Join-Path $temp 'public identity receipt.json'
    foreach ($case in @(if (-not $VerifierProcessOnly) { 'schema'; 'different-input'; 'missing-script'; 'untrusted-host' })) {
        $marker = Join-Path $temp ("verified-marker-$case.txt")
        [pscustomobject]@{ Schema = $(if ($case -eq 'schema') { 'invalid' } else { 'magnolie-prepared-phone-inputs-v1' });
            Stage = $null; Inputs = @{}; Payloads = @() } | ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath $receipt -Encoding UTF8
        $verifier = Join-Path $build 'Verify-PhonePayloadInputs.ps1'
        if ($case -eq 'missing-script') { Move-Item -LiteralPath $verifier -Destination ($verifier + '.held') }
        $info = [Diagnostics.ProcessStartInfo]::new($dotnet)
        foreach ($argument in @('msbuild', $project, '-nologo', '-verbosity:minimal', '-m:1', '-nodeReuse:false',
            '-p:MAGNOLIE_OFFICIAL_RELEASE=1', "-p:Marker=$marker", '-p:MagnoliePhoneCameraHelperDirectory=synthetic-input')) { $info.ArgumentList.Add($argument) }
        $info.Environment['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
        $info.Environment['DOTNET_GENERATE_ASPNET_CERTIFICATE'] = 'false'
        $info.Environment['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
        $info.Environment['DOTNET_CLI_HOME'] = Join-Path $temp 'cli-home'
        $info.Environment['MAGNOLIE_PHONE_VERIFY_RECEIPT'] = $receipt
        $info.Environment['MAGNOLIE_PHONE_VERIFY_PUBLISHER'] = 'CN=Synthetic, O=Not a real identity'
        # Existing host path is only passed as a public tool argument. The
        # invalid receipt must reject before this tool can ever be invoked.
        $info.Environment['MAGNOLIE_PHONE_VERIFY_TOOL'] = (Get-Process -Id $PID).Path
        $info.Environment['MAGNOLIE_PHONE_VERIFY_HOST'] = (Get-Process -Id $PID).Path
        if ($case -eq 'untrusted-host') {
            $untrusted = Join-Path $temp 'untrusted-host/pwsh.exe'
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($untrusted)) | Out-Null
            [IO.File]::WriteAllText($untrusted, 'MZsynthetic-untrusted-not-an-executable')
            $info.Environment['MAGNOLIE_PHONE_VERIFY_HOST'] = $untrusted
        }
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
        try {
            [void]$process.Start()
            $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(20000)) { $process.Kill($true); $process.WaitForExit(); throw 'Owned verifier boundary test timeout.' }
            $expected = switch ($case) {
                'schema' { 'Unknown prepared-input receipt schema' }
                'different-input' { 'Actual embedding input differs from the verified receipt' }
                'missing-script' { 'source-bound script is missing' }
                'untrusted-host' { 'Configured verifier host is not a valid Microsoft-signed PowerShell executable' }
            }
            $message = $stdout.Result + $stderr.Result
            if ($process.ExitCode -eq 0 -or $message -notmatch 'MAGNOLIE560' -or $message -notmatch [regex]::Escape($expected)) {
                throw "Independent verifier boundary did not reject $case as expected: $message"
            }
            if (Test-Path -LiteralPath $marker) { throw 'Embedding ran after independent verification rejected.' }
        } finally {
            $process.Dispose()
            if ($case -eq 'missing-script') { Move-Item -LiteralPath ($verifier + '.held') -Destination $verifier }
        }
        $count++
    }
    # Controlled host-process tests, NOT substitutes for the signature policy.
    # A successful controlled dependency must precede the inert snapshot marker.
    $verifier = Join-Path $build 'Verify-PhonePayloadInputs.ps1'
    Move-Item -LiteralPath $verifier -Destination ($verifier + '.canonical')
    @'
param($Receipt, $Publisher, $SignTool, $MagnoliePhoneCameraHelperDirectory,
    $MagnoliePhoneCameraRuntimeDirectory, $MagnoliePhoneCameraParentDirectory, $MagnoliePhoneCameraSourceDirectory)
$ErrorActionPreference = 'Stop'
if ($env:MAGNOLIE_SIGN_CERTIFICATE -or $env:MAGNOLIE_SIGN_PASSWORD) { throw 'Signing credentials leaked into the verifier.' }
if ($Publisher -cne 'CN=Synthetic, O=Not a real identity' -or $MagnoliePhoneCameraHelperDirectory -cne 'synthetic-input' -or
    $MagnoliePhoneCameraRuntimeDirectory -cne '' -or $MagnoliePhoneCameraParentDirectory -cne '' -or $MagnoliePhoneCameraSourceDirectory -cne '') { throw 'Native argv was changed.' }
[pscustomobject]@{ Pid = $PID; StartTicks = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks } |
    ConvertTo-Json -Compress | Set-Content -LiteralPath ($Receipt + '.process') -Encoding UTF8
if ((Get-Content -LiteralPath $Receipt -Raw) -eq 'timeout') { Start-Sleep -Seconds 60 }
'@ | Set-Content -LiteralPath $verifier -Encoding UTF8
    foreach ($case in @('success-before-snapshot', 'timeout')) {
        $receipt = Join-Path $temp ("$case public receipt.json")
        [IO.File]::WriteAllText($receipt, $case)
        $marker = Join-Path $temp ("$case-embedding.txt")
        $info = [Diagnostics.ProcessStartInfo]::new($dotnet)
        foreach ($argument in @('msbuild', $project, '-nologo', '-verbosity:minimal', '-m:1', '-nodeReuse:false',
            '-p:MAGNOLIE_OFFICIAL_RELEASE=1', "-p:Marker=$marker", '-p:MagnoliePhoneCameraHelperDirectory=synthetic-input')) { $info.ArgumentList.Add($argument) }
        $info.Environment['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
        $info.Environment['DOTNET_GENERATE_ASPNET_CERTIFICATE'] = 'false'
        $info.Environment['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
        $info.Environment['DOTNET_CLI_HOME'] = Join-Path $temp 'cli-home'
        $info.Environment['MAGNOLIE_PHONE_VERIFY_RECEIPT'] = $receipt
        $info.Environment['MAGNOLIE_PHONE_VERIFY_PUBLISHER'] = 'CN=Synthetic, O=Not a real identity'
        $info.Environment['MAGNOLIE_PHONE_VERIFY_TOOL'] = (Get-Process -Id $PID).Path
        $info.Environment['MAGNOLIE_PHONE_VERIFY_HOST'] = (Get-Process -Id $PID).Path
        $info.Environment['MAGNOLIE_SIGN_CERTIFICATE'] = 'SYNTHETIC-CANARY-NOT-A-CERTIFICATE'
        $info.Environment['MAGNOLIE_SIGN_PASSWORD'] = 'SYNTHETIC-CANARY-NOT-A-PASSWORD'
        $info.UseShellExecute = $false; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new(); $process.StartInfo = $info
        try {
            [void]$process.Start()
            $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(45000)) { $process.Kill($true); $process.WaitForExit(); throw 'Owned process-boundary test timeout.' }
            $message = $stdout.Result + $stderr.Result
            if ($case -eq 'timeout') {
                if ($process.ExitCode -eq 0 -or $message -notmatch 'Native verifier exceeded its deadline' -or (Test-Path -LiteralPath $marker)) { throw "Verifier timeout boundary failed: $message" }
            } elseif ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $marker)) { throw "Verified dependency did not precede the inert snapshot: $message" }
            $record = Get-Content -LiteralPath ($receipt + '.process') -Raw | ConvertFrom-Json
            $owned = Get-Process -Id $record.Pid -ErrorAction SilentlyContinue
            if ($owned -and $owned.StartTime.ToUniversalTime().Ticks -eq $record.StartTicks) { throw 'The owned verifier process is still running after rejection/timeout.' }
        } finally {
            $process.Dispose()
            if (Test-Path -LiteralPath ($receipt + '.process')) {
                $record = Get-Content -LiteralPath ($receipt + '.process') -Raw | ConvertFrom-Json
                $owned = Get-Process -Id $record.Pid -ErrorAction SilentlyContinue
                if ($owned -and $owned.StartTime.ToUniversalTime().Ticks -eq $record.StartTicks) { $owned.Kill($true); $null = $owned.WaitForExit(5000) }
            }
        }
        $count++
    }
    Write-Host "$count actual MSBuild signing-boundary cases passed; inert fixtures and verifier-host signatures only, no signing or signature-tool/payload execution."
} finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force } }
