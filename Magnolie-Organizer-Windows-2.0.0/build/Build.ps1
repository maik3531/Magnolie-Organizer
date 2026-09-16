param(
    [switch] $BuildInstaller,
    [switch] $CrossCompile,
    [string] $Destination
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "Release.Common.ps1")

$root = Split-Path -Parent $PSScriptRoot
$outputRoot = $root
if ($Destination) {
    $outputRoot = [IO.Path]::GetFullPath($Destination)
    $canonical = [IO.Path]::GetFullPath((Split-Path -Parent $root)).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if ($outputRoot.Equals($canonical, [StringComparison]::OrdinalIgnoreCase) -or
        $outputRoot.StartsWith($canonical + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Private candidate destination must be outside canonical source.'
    }
    if (Test-Path -LiteralPath $outputRoot) {
        if (-not (Test-Path -LiteralPath $outputRoot -PathType Container) -or @(Get-ChildItem -LiteralPath $outputRoot -Force).Count) {
            throw 'Private candidate destination must be an empty directory.'
        }
    } else { [void][IO.Directory]::CreateDirectory($outputRoot) }
    for ($directory = Get-Item -LiteralPath $outputRoot; $null -ne $directory; $directory = $directory.Parent) {
        if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Private destination cannot use directory links.' }
    }
    if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl.SetOwner($sid)
        $acl.SetAccessRuleProtection($true, $false)
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
        Set-Acl -LiteralPath $outputRoot -AclObject $acl
    } else { [IO.File]::SetUnixFileMode($outputRoot, [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite -bor [IO.UnixFileMode]::UserExecute) }
}
$version = Get-ReleaseVersion $root
$official = $env:MAGNOLIE_OFFICIAL_RELEASE -eq "1"
$hash = $env:MAGNOLIE_CONTRIBUTOR_HASH
$runningOnWindows = [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)
$runningOnLinux = [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Linux)
$signingRequested = @(
    @("MAGNOLIE_SIGNTOOL", "MAGNOLIE_SIGN_CERTIFICATE", "MAGNOLIE_SIGN_PASSWORD", "MAGNOLIE_SIGN_PUBLISHER", "MAGNOLIE_TIMESTAMP_URL") |
        Where-Object { [Environment]::GetEnvironmentVariable($_) }
)
if ($CrossCompile) {
    if (-not $runningOnLinux) { throw "-CrossCompile ist ausschließlich für einen Linux-Bau bestimmt." }
    if ($official) { throw "-CrossCompile kann keine offizielle Ausgabe erzeugen." }
    if ($signingRequested.Count) { throw "-CrossCompile verweigert konfigurierte Signierung: $($signingRequested -join ', ')." }
    if (-not $env:NSISDIR -or -not (Test-Path -LiteralPath $env:NSISDIR -PathType Container)) {
        throw "-CrossCompile benötigt ein extern gesetztes NSISDIR, das auf ein vorhandenes NSIS-Datenverzeichnis zeigt."
    }
    Write-Warning "CROSS-COMPILE: WINDOWS-LAUFZEIT UNGEPRÜFT. Ausschließlich UNSIGNIERT; Validierung in einer Windows-VM ist zwingend."
} elseif (-not $runningOnWindows) {
    throw "Der Windows-Bau benötigt Windows; unter Linux muss -CrossCompile ausdrücklich gesetzt werden."
}
$script:signingConfiguration = @{}
foreach ($name in "MAGNOLIE_SIGNTOOL", "MAGNOLIE_SIGN_CERTIFICATE", "MAGNOLIE_SIGN_PASSWORD", "MAGNOLIE_SIGN_PUBLISHER", "MAGNOLIE_TIMESTAMP_URL") {
    $script:signingConfiguration[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $null, [EnvironmentVariableTarget]::Process)
}
$stage = Join-Path $root (".release-staging-" + [Guid]::NewGuid().ToString("N"))
$publicationStage = Join-Path $stage "project"
$publish = Join-Path $publicationStage "Ausgabe"
$zipStage = Join-Path $publicationStage "Magnolie-Organizer-Windows-$version-x64.zip"
$canonicalInstallerName = "Magnolie-Organizer-Windows-$version-Setup-x64.exe"
$setupStage = Join-Path $publicationStage $canonicalInstallerName
$installerRecordName = "$canonicalInstallerName.build.json"
$installerRecordStage = Join-Path $publicationStage $installerRecordName
$unsignedSetupStage = if ($official) { Join-Path $publicationStage (".unsigned-" + $canonicalInstallerName) } else { $setupStage }
$sourceName = "Magnolie-Organizer-Windows-$version-Source.zip"
$sourceLive = Join-Path $root $sourceName
$sourceStage = Join-Path $publicationStage $sourceName
$sourceForRelease = $sourceLive
$installSource = $false
$installerName = $canonicalInstallerName
$checksumName = "Magnolie-Organizer-Windows-$version-PRUEFSUMMEN.sha256"
$checksumStage = Join-Path $publicationStage $checksumName
$lock = $null

function Assert-Signature([string] $Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) { throw "Authenticode-Prüfung fehlgeschlagen: $Path ($($signature.Status))" }
    if (-not [string]::Equals($signature.SignerCertificate.Subject, $script:signingConfiguration["MAGNOLIE_SIGN_PUBLISHER"], [StringComparison]::Ordinal)) {
        throw "Unerwarteter Authenticode-Herausgeber: $($signature.SignerCertificate.Subject)"
    }
    if (-not $signature.TimeStamperCertificate) { throw "Gültiger RFC3161-Zeitstempel fehlt: $Path" }
    Invoke-NativeCommand $script:signingConfiguration["MAGNOLIE_SIGNTOOL"] @("verify", "/pa", "/all", "/tw", $Path)
}

function Sign-Official([string] $Path) {
    if (-not $official) { return }
    foreach ($name in "MAGNOLIE_SIGNTOOL", "MAGNOLIE_SIGN_CERTIFICATE", "MAGNOLIE_SIGN_PASSWORD", "MAGNOLIE_SIGN_PUBLISHER", "MAGNOLIE_TIMESTAMP_URL") {
        if (-not $script:signingConfiguration[$name]) { throw "Offizielle Ausgabe benötigt $name." }
    }
    if (-not (Test-Path -LiteralPath $script:signingConfiguration["MAGNOLIE_SIGNTOOL"] -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:signingConfiguration["MAGNOLIE_SIGN_CERTIFICATE"] -PathType Leaf)) {
        throw "Signaturwerkzeug oder Zertifikat fehlt."
    }
    Invoke-NativeCommand $script:signingConfiguration["MAGNOLIE_SIGNTOOL"] @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr",
        $script:signingConfiguration["MAGNOLIE_TIMESTAMP_URL"], "/f", $script:signingConfiguration["MAGNOLIE_SIGN_CERTIFICATE"],
        "/p", $script:signingConfiguration["MAGNOLIE_SIGN_PASSWORD"], $Path)
    Assert-Signature $Path
}

function Update-WebCatalogs([string] $Root, [string] $Python) {
    Invoke-NativeCommand $Python @((Join-Path $Root "werkzeuge/pot_erzeugen.py"))
    $tool = Join-Path $Root "werkzeuge/po_zu_js.py"
    $po = Join-Path $Root "app/po"
    $target = Join-Path $Root "app/web/i18n"
    $languages = ([IO.File]::ReadAllText((Join-Path $po "LINGUAS")) -split '\s+') |
        Where-Object { $_ }
    foreach ($language in $languages) {
        Invoke-NativeCommand $Python @($tool, $language,
            (Join-Path $po "$language.po"), (Join-Path $target "$language.js"))
    }
    $nativeArguments = @((Join-Path $Root "werkzeuge/po_zu_native.py"), (Join-Path $Root "app/native-i18n.json"))
    foreach ($language in $languages) {
        $nativeArguments += @($language, (Join-Path $po "$language.po"))
    }
    Invoke-NativeCommand $Python $nativeArguments
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw "Der Windows-Bau benötigt ein 64-Bit-Windows." }
    if ($hash -notmatch '^[0-9a-fA-F]{64}$') { throw "Binärausgabe benötigt MAGNOLIE_CONTRIBUTOR_HASH als SHA-256-Hexfolge." }
    $hash = $hash.ToLowerInvariant()
    $env:MAGNOLIE_CONTRIBUTOR_HASH = $hash
    $python = if ($env:MAGNOLIE_PYTHON) { Get-Command $env:MAGNOLIE_PYTHON -ErrorAction Stop } else { Get-Command "python3" -ErrorAction SilentlyContinue }
    if (-not $python) { $python = Get-Command "python" -ErrorAction SilentlyContinue }
    if (-not $python) { throw "Der Bau benötigt Python 3 für Lokalisierungstests und Kataloggeneratoren." }
    $msgfmt = Get-Command "msgfmt" -ErrorAction SilentlyContinue
    if (-not $msgfmt) { throw "Der Bau benötigt msgfmt aus GNU gettext für die PO-Prüfung." }
    $env:MAGNOLIE_PYTHON = $python.Source
    $env:MAGNOLIE_MSGFMT = $msgfmt.Source
    $handbookWeb = Get-SharedHandbookWeb $root
    $lock = Enter-ReleaseLock $root
    Update-WebCatalogs $root $python.Source
    New-Item -ItemType Directory -Path $publish | Out-Null
    try {
        Assert-SourceArchive $sourceLive $root $version
        Copy-Item -LiteralPath $sourceLive -Destination $sourceStage
        $sourceForRelease = $sourceStage
    } catch {
        Write-Host "Aktuelles Quellarchiv fehlt oder ist veraltet; es wird in derselben Release-Transaktion gebaut."
        & (Join-Path $PSScriptRoot "BuildSource.ps1") -Destination $sourceStage -SkipLock
        Assert-SourceArchive $sourceStage $root $version
        $sourceForRelease = $sourceStage
        $installSource = $true
    }
    $sourceProjection = Join-Path $stage 'source'
    [IO.Compression.ZipFile]::ExtractToDirectory($sourceForRelease, $sourceProjection)
    $buildRoot = Join-Path $sourceProjection "Magnolie-Organizer-Windows-$version"
    $handbookWeb = Join-Path $buildRoot 'shared/magnolie-handbuch-stamm/web'
    $testEnvironment = @{}
    foreach ($variable in 'MAGNOLIE_HANDBOOK_WEB', 'MAGNOLIE_HANDBUCH_WEB', 'MAGNOLIE_LINUX_SOURCE', 'MAGNOLIE_TEST_SOURCE_ROOT') {
        $testEnvironment[$variable] = [Environment]::GetEnvironmentVariable($variable)
    }
    $env:MAGNOLIE_HANDBOOK_WEB = $handbookWeb
    $env:MAGNOLIE_HANDBUCH_WEB = $handbookWeb
    $env:MAGNOLIE_TEST_SOURCE_ROOT = $buildRoot
    $linuxSource = Join-Path (Split-Path -Parent $root) 'magnolie-organizer-2.0.0'
    $env:MAGNOLIE_LINUX_SOURCE = if (Test-Path -LiteralPath $linuxSource -PathType Container) { $linuxSource } else { $null }
    Push-Location $buildRoot
    try {
        Invoke-NativeCommand (Get-Process -Id $PID).Path @('-NoProfile', '-File', 'tests/release-packaging.ps1')
        Invoke-NativeCommand $python.Source @('-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_windows_pot_source_coverage.py')
        Invoke-NativeCommand "dotnet" @("restore", "MagnolieOrganizer.Windows.csproj", "--locked-mode")
        Invoke-NativeCommand "dotnet" @("restore", "tests/CoreTests.csproj", "--locked-mode")
        $previousReleaseBuildTest = $env:MAGNOLIE_RELEASE_BUILD_TEST
        try {
            $env:MAGNOLIE_RELEASE_BUILD_TEST = "1"
            Invoke-NativeCommand "dotnet" @("run", "--project", "tests/CoreTests.csproj", "-c", "Release", "--no-restore")
        } finally {
            $env:MAGNOLIE_RELEASE_BUILD_TEST = $previousReleaseBuildTest
        }
        Invoke-NativeCommand "bun" @("install", "--frozen-lockfile")
        Invoke-NativeCommand "bun" @("run", "test")
        Invoke-NativeCommand "dotnet" @("publish", "MagnolieOrganizer.Windows.csproj", "-c", "Release", "-r", "win-x64", "--self-contained", "true", "--no-restore", "-p:Version=$version", "-o", $publish)
        Invoke-NativeCommand "bun" @((Join-Path $buildRoot "build/PortHandbook.js"), $handbookWeb, $version, $installerName, (Join-Path $publish "handbuch"))
        Invoke-NativeCommand "bun" @((Join-Path $buildRoot "build/AuditWebPayload.js"), "--publish", $buildRoot, $publish)
    } finally {
        Pop-Location
        foreach ($variable in $testEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($variable, $testEnvironment[$variable])
        }
    }

    $config = [ordered]@{ contributorHash = $hash }
    if ($env:MAGNOLIE_GRAPH_CLIENT_ID) {
        $id = [Guid]::Empty
        if (-not [Guid]::TryParse($env:MAGNOLIE_GRAPH_CLIENT_ID, [ref]$id)) { throw "MAGNOLIE_GRAPH_CLIENT_ID ist keine GUID." }
        $config.graphClientId = $id.ToString()
    }
    [IO.File]::WriteAllText((Join-Path $publish "build-config.json"), ($config | ConvertTo-Json -Compress), [Text.Encoding]::ASCII)
    Invoke-NativeCommand "bun" @((Join-Path $buildRoot "installer/VerifyBuildConfig.js"), (Join-Path $publish "build-config.json"))

    $app = Join-Path $publish "Magnolie Organizer.exe"
    Sign-Official $app
    if ($CrossCompile) {
        $marker = @(
            "windowsRuntimeVerified=false"
            "windowsVmValidationRequired=true"
            "artifactTrust=UNSIGNED"
        ) -join "`n"
        [IO.File]::WriteAllText((Join-Path $publish "WINDOWS-RUNTIME-UNVERIFIED.txt"), "$marker`n", [Text.Encoding]::ASCII)
    } else {
        if ($official) {
            Invoke-NativeCommand $app @("--packaging-self-test")
        }
        Invoke-NativeCommand $app @("--self-test")
        Invoke-NativeCommand $app @("--ui-self-test")
    }
    Assert-BinaryPayloadFiles $publish
    New-DeterministicZip $publish $zipStage
    Assert-BinaryArchiveBuildConfig $zipStage $hash
    $zipAudit = Join-Path $stage "zip-audit"
    [IO.Compression.ZipFile]::ExtractToDirectory($zipStage, $zipAudit)
    Invoke-NativeCommand "bun" @((Join-Path $buildRoot "build/AuditWebPayload.js"), "--artifact", $publish, $zipAudit)

    if ($BuildInstaller -or $official -or $CrossCompile) {
        $makensisCommand = if ($CrossCompile) { Get-Command makensis -ErrorAction SilentlyContinue } else { Get-Command makensis.exe -ErrorAction SilentlyContinue }
        $makensis = if ($makensisCommand) { $makensisCommand.Source } else { $null }
        if (-not $makensisCommand -and $CrossCompile -and (Test-Path -LiteralPath "/tmp/opencode/nsis-root/usr/bin/makensis" -PathType Leaf)) {
            $makensis = "/tmp/opencode/nsis-root/usr/bin/makensis"
        }
        $alternateMakensis = if ($CrossCompile) { "makensis.exe" } else { "makensis" }
        if (-not $makensis) {
            $makensisCommand = Get-Command $alternateMakensis -ErrorAction SilentlyContinue
            if ($makensisCommand) { $makensis = $makensisCommand.Source }
        }
        if (-not $makensis) { throw "Installer angefordert, aber makensis beziehungsweise makensis.exe fehlt." }
        $installerManifestDir = Join-Path $stage "installer-manifests"
        Invoke-NativeCommand "bun" @((Join-Path $buildRoot "installer/GenerateInstallManifests.js"), $publish, $installerManifestDir)
        Invoke-NativeCommand $makensis @("-WX", "-DPRODUCT_VERSION=$version", "-DPUBLISH_DIR=$publish", "-DCORE_MANIFEST=$(Join-Path $installerManifestDir 'core.manifest')", "-DHANDBOOK_MANIFEST=$(Join-Path $installerManifestDir 'handbook.manifest')", "-DOUTPUT_FILE=$unsignedSetupStage", "-DINSTALLER_FILENAME=$canonicalInstallerName", (Join-Path $buildRoot "installer/MagnolieOrganizer.nsi"))
        if (-not (Test-Path $unsignedSetupStage -PathType Leaf)) { throw "NSIS-Bau erzeugte keinen Installer." }
        Sign-Official $unsignedSetupStage
        if ($official) { Move-Item -LiteralPath $unsignedSetupStage -Destination $setupStage }
        Invoke-NativeCommand "bun" @((Join-Path $buildRoot "installer/CreateInstallerBuildRecord.js"), $setupStage, $installerRecordStage, $canonicalInstallerName)
        Invoke-NativeCommand "bun" @((Join-Path $buildRoot "installer/AuditInstaller.js"), $setupStage, $publish, $canonicalInstallerName, $installerRecordStage)
        Write-WindowsCandidateRecord $root $publicationStage $version
    }

    $checksumArtifacts = @(
        [pscustomobject]@{ Source = $sourceForRelease; DisplayPath = $sourceName }
        [pscustomobject]@{ Source = $zipStage; DisplayPath = (Split-Path $zipStage -Leaf) }
    )
    if ($BuildInstaller -or $official -or $CrossCompile) {
        $checksumArtifacts += [pscustomobject]@{ Source = $setupStage; DisplayPath = (Split-Path $setupStage -Leaf) }
        $checksumArtifacts += [pscustomobject]@{ Source = $installerRecordStage; DisplayPath = $installerRecordName }
        $provenanceName = "Magnolie-Organizer-Windows-$version-provenance.json"
        $checksumArtifacts += [pscustomobject]@{ Source = (Join-Path $publicationStage $provenanceName); DisplayPath = $provenanceName }
    }
    Write-ReleaseChecksums $root $version $checksumStage $checksumArtifacts
    $changes = @(
        ,@($publish, (Join-Path $outputRoot "Ausgabe"))
        ,@($zipStage, (Join-Path $outputRoot "Magnolie-Organizer-Windows-$version-x64.zip"))
    )
    if ($installSource -or $Destination) { $changes += ,@($sourceStage, (Join-Path $outputRoot $sourceName)) }
    if (Test-Path $setupStage) { $changes += ,@($setupStage, (Join-Path $outputRoot $canonicalInstallerName)) }
    if (Test-Path $installerRecordStage) { $changes += ,@($installerRecordStage, (Join-Path $outputRoot $installerRecordName)) }
    if ($BuildInstaller -or $official -or $CrossCompile) {
        $changes += ,@((Join-Path $publicationStage $provenanceName), (Join-Path $outputRoot $provenanceName))
    }
    $changes += ,@($checksumStage, (Join-Path $outputRoot $checksumName))
    foreach ($stale in Get-ChildItem -LiteralPath $outputRoot -File -Force | Where-Object {
        $_.Name -match '(?i)^Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64-UNSIGNED\.exe$'
    }) {
        $changes += ,@($null, $stale.FullName)
    }
    Install-StagedPaths $changes {
        if ($CrossCompile) {
            Invoke-NativeCommand "bun" @((Join-Path $buildRoot "installer/AuditInstaller.js"), (Join-Path $outputRoot $canonicalInstallerName), (Join-Path $outputRoot "Ausgabe"), $canonicalInstallerName, (Join-Path $outputRoot $installerRecordName))
        }
    }
    if ($official) { Write-Host "Signed Windows transport candidate $version created; native/user acceptance and promotion are still required." }
    else { Write-Host "Unsigned Windows transport candidate $version created; native/user acceptance and promotion are still required." }
} finally {
    if ($lock) { $lock.Dispose() }
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
}
