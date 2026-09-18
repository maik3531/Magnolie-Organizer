$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ReleaseVersion([string] $Root) {
    [xml]$props = Get-Content -LiteralPath (Join-Path $Root "Directory.Build.props") -Raw
    $value = [string]$props.Project.PropertyGroup.Version
    if ($value -notmatch '^\d+\.\d+\.\d+$') { throw "Directory.Build.props enthält keine gültige Version." }
    return $value
}

function Get-SharedHandbookWeb([string] $Root) {
    $canonical = Join-Path (Split-Path -Parent $Root) 'magnolie-handbuch/web'
    if (-not (Test-Path -LiteralPath $canonical -PathType Container)) {
        $canonical = Join-Path $Root 'shared/magnolie-handbuch/web'
    }
    $configured = [Environment]::GetEnvironmentVariable('MAGNOLIE_HANDBOOK_WEB')
    $comparison = if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
    if ($configured -and -not [string]::Equals([IO.Path]::GetFullPath($configured), [IO.Path]::GetFullPath($canonical), $comparison)) {
        throw 'Handbook build override must refer to the canonical source, not another projection.'
    }
    $candidates = @($canonical)
    foreach ($candidate in $candidates) {
        $full = [IO.Path]::GetFullPath($candidate)
        if ((Test-Path -LiteralPath (Join-Path $full "index.html") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $full "inhalt.js") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $full "i18n/de.js") -PathType Leaf)) { return $full }
    }
    throw "Gemeinsame Handbuchquelle magnolie-handbuch/web fehlt."
}

function Test-PrivateReleasePath([string] $Relative) {
    $parts = $Relative.Replace('\', '/') -split '/'
    return [bool]($parts | Where-Object {
        $_ -match '^(?i)(?:\.private(?:-.*)?|\.claude|\.idea|\.vscode|\.ssh|\.aws|\.azure|\.config|\.local|\.cache|\.pytest_cache|an-claude\.md|\.env(?:\..*)?|settings\.local\.json|local\.properties|schluessel\.properties)$' -or
        $_ -match '(?i)\.(?:pem|key|pfx|p12|jks|keystore|secret|token)$'
    })
}

function Assert-SourceFileSafe([IO.FileInfo] $File) {
    if (($File.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Source symlinks are not permitted.' }
    for ($directory = $File.Directory; $null -ne $directory; $directory = $directory.Parent) {
        if (($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Source directory links are not permitted.' }
    }
    $text = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($File.FullName))
    if ($text -match '-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?\n') { throw 'Private key material in source input.' }
    $branding = [Environment]::GetEnvironmentVariable('MAGNOLIE_CONTRIBUTOR_HASH')
    if ($branding -match '^[0-9a-fA-F]{64}$' -and $branding -ne ('0' * 64) -and
        $text.IndexOf($branding, [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Private branding in source input.' }
}

function Get-ReleaseSourceFiles([string] $Root) {
    $excludedDirectories = @(".git", ".private-testing", ".claude", ".idea", ".vscode", "__pycache__", "Ausgabe", "bin", "handbook-windows-i18n", "handbuch", "node_modules", "obj", "shared", "contracts")
    $internalNotePattern = '(?i)(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$'
    $generatedReleasePattern = '(?i)^(?:Magnolie-Organizer-Windows-.*-Setup-.*\.exe(?:\.build\.json)?|.*-x64\.zip|.*-Source\.zip|.*-PRUEFSUMMEN\.sha256)$'
    Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object {
        $relative = [IO.Path]::GetRelativePath($Root, $_.FullName)
        $parts = $relative -split '[\\/]'
        -not ($parts | Where-Object { $excludedDirectories -contains $_ }) -and
            -not ($parts | Where-Object { $_ -match '\.rollback(?:-recovery-.*)?$' }) -and
            -not ($parts | Where-Object { $_ -like '.release-staging-*' }) -and
            $_.Name -notmatch $internalNotePattern -and
            $_.Name -notlike "*~" -and
            -not (Test-PrivateReleasePath $relative) -and
            $_.Extension -ine ".pyc" -and
            $_.Extension -notin @(".iso", ".qcow2", ".vdi", ".vhd", ".vhdx", ".img", ".raw", ".ppm", ".pdb") -and
            $_.Extension -notin @(".pfx", ".p12", ".pem", ".key") -and
            $_.Name -notmatch '(?i)^(?:\.env(?:\..*)?|settings\.local\.json)$' -and
            -not ($parts[0] -ieq "vm" -and $_.Extension -ieq ".png") -and
            $_.Name -notmatch $generatedReleasePattern -and
            $_.Name -ine ".magnolie-windows-release.lock" -and
            $_.Name -notlike '*-provenance.json'
    } | Sort-Object { [IO.Path]::GetRelativePath($Root, $_.FullName).Replace('\', '/') }
}

function Get-ReleaseArchiveSources([string] $Root) {
    $oracleRelative = 'tests/fixtures/recurrence-rfc-oracle.json'
    foreach ($file in Get-ReleaseSourceFiles $Root) {
        if ([IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/') -ceq $oracleRelative) { continue }
        Assert-SourceFileSafe $file
        [pscustomobject]@{
            Source = $file.FullName
            Relative = [IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/')
        }
    }
    $handbookWeb = Get-SharedHandbookWeb $Root
    foreach ($file in Get-ChildItem -LiteralPath $handbookWeb -Recurse -File -Force |
        Sort-Object { [IO.Path]::GetRelativePath($handbookWeb, $_.FullName).Replace('\', '/') }) {
        $relative = [IO.Path]::GetRelativePath($handbookWeb, $file.FullName).Replace('\', '/')
        if (Test-PrivateReleasePath $relative) { continue }
        if (($relative -split '/') | Where-Object { $_ -in @('.git', 'node_modules', '__pycache__') }) { continue }
        Assert-SourceFileSafe $file
        [pscustomobject]@{
            Source = $file.FullName
            Relative = "shared/magnolie-handbuch/web/$([IO.Path]::GetRelativePath($handbookWeb, $file.FullName).Replace('\', '/'))"
        }
    }
    $contracts = Join-Path (Split-Path -Parent $Root) 'contracts'
    if (-not (Test-Path -LiteralPath $contracts -PathType Container)) { $contracts = Join-Path $Root 'contracts' }
    foreach ($required in 'kontakt-sync-contract.json', 'kontakt-import-contract.json', 'phone-region-vectors.json', 'thunderbird-addressbook-fixture.json', 'recurrence-integration.json', 'recurrence-timezones.json', 'baum-1-receipt-v1-vectors.json', 'baum-1-receipt-v1.md', 'phone-bluetooth-first-pair.md', 'phone-setup-daemon-lifecycle.md', 'phone-wlan-invitation.md') {
        if (-not (Test-Path -LiteralPath (Join-Path $contracts $required) -PathType Leaf)) { throw "Shared contract missing: $required" }
    }
    foreach ($file in Get-ChildItem -LiteralPath $contracts -Recurse -File -Force | Sort-Object FullName) {
        $relative = [IO.Path]::GetRelativePath($contracts, $file.FullName).Replace('\', '/')
        if (Test-PrivateReleasePath $relative) { continue }
        if ($file.Extension -cnotin @('.json', '.md')) { throw 'Only reviewed JSON/Markdown contracts may enter source archives.' }
        Assert-SourceFileSafe $file
        $content = [IO.File]::ReadAllText($file.FullName)
        if ($file.Extension -ceq '.json') { [void]($content | ConvertFrom-Json) }
        elseif (-not $content.Trim()) { throw 'Empty contract documentation.' }
        [pscustomobject]@{ Source = $file.FullName; Relative = "contracts/$relative" }
    }
    $oracle = Join-Path (Split-Path -Parent $Root) 'magnolie-organizer/pruefungen/fixtures/recurrence-rfc-oracle.json'
    if (-not (Test-Path -LiteralPath $oracle -PathType Leaf)) { $oracle = Join-Path $Root $oracleRelative }
    $oracleFile = Get-Item -LiteralPath $oracle
    Assert-SourceFileSafe $oracleFile
    [void]([IO.File]::ReadAllText($oracleFile.FullName) | ConvertFrom-Json)
    [pscustomobject]@{ Source = $oracleFile.FullName; Relative = $oracleRelative }
}

function Invoke-NativeCommand([string] $FilePath, [object[]] $ArgumentList = @()) {
    & $FilePath @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $error = [InvalidOperationException]::new("Nativer Befehl fehlgeschlagen: $FilePath (Exitcode $exitCode)")
        $error.Data["Command"] = $FilePath
        $error.Data["ExitCode"] = $exitCode
        throw $error
    }
}

function New-DeterministicZip([string] $Source, [string] $Destination, [string] $Prefix = "") {
    Add-Type -AssemblyName System.IO.Compression
    $timestamp = [DateTimeOffset]::Parse("2020-01-01T00:00:00Z")
    $stream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        $files = Get-ChildItem -LiteralPath $Source -Recurse -File -Force | Sort-Object { [IO.Path]::GetRelativePath($Source, $_.FullName).Replace('\', '/') }
        foreach ($file in $files) {
            $relative = [IO.Path]::GetRelativePath($Source, $file.FullName).Replace('\', '/')
            if ($file.Extension -ieq ".pdb") { continue }
            $name = if ($Prefix) { "$Prefix/$relative" } else { $relative }
            $entry = $zip.CreateEntry($name, [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = $timestamp
            $entry.ExternalAttributes = 0x81A40000
            $input = [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    } finally { $zip.Dispose(); $stream.Dispose() }
}

function Assert-BinaryArchiveBuildConfig([string] $Archive, [string] $ExpectedHash) {
    Add-Type -AssemblyName System.IO.Compression
    $stream = [IO.File]::OpenRead($Archive)
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read)
    try {
        $entries = @($zip.Entries | Where-Object { $_.FullName -ceq "build-config.json" })
        if ($entries.Count -ne 1) { throw "Binärarchiv enthält build-config.json nicht genau einmal." }
        $reader = [IO.StreamReader]::new($entries[0].Open(), [Text.Encoding]::ASCII, $false)
        try { $config = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($config.contributorHash -cne $ExpectedHash) { throw "Binärarchiv enthält nicht das erwartete Contributor-Branding." }
    } finally { $zip.Dispose(); $stream.Dispose() }
}

function Assert-CurrentWebPayload([string] $Root, [string] $Publish) {
    $source = Join-Path $Root "app/web/anwendung.js"
    $published = Join-Path $Publish "web/anwendung.js"
    if (-not (Test-Path -LiteralPath $published -PathType Leaf)) {
        throw "Publizierte Weboberfläche fehlt: web/anwendung.js"
    }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $published -Algorithm SHA256).Hash) {
        throw "Publizierte Weboberfläche entspricht nicht der aktuellen Quell-Webdatei."
    }
    $text = [IO.File]::ReadAllText($published)
    foreach ($marker in "oeffneSuche", "syncMetadaten", "nextcloud") {
        if ($text.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
            throw "Publizierte Weboberfläche enthält den Pflichtmarker nicht: $marker"
        }
    }
}

function Enter-ReleaseLock([string] $Root) {
    $path = Join-Path $Root ".magnolie-windows-release.lock"
    return [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}

function Remove-StaleUnsignedInstallers([string] $Root) {
    Get-ChildItem -LiteralPath $Root -File -Force | Where-Object {
        $_.Name -match '(?i)^Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64-UNSIGNED\.exe$'
    } | Remove-Item -Force
}

function Install-StagedPath([string] $Staged, [string] $Live) {
    Install-StagedPaths @(,@($Staged, $Live))
}

function Install-StagedPaths([object[]] $Changes, [scriptblock] $Validate = $null) {
    foreach ($change in $Changes) {
        if (Test-Path -LiteralPath "$($change[1]).rollback") { throw "Rollback-Pfad ist belegt: $($change[1]).rollback" }
        if ($change[0] -and -not (Test-Path -LiteralPath $change[0])) { throw "Staging-Pfad fehlt: $($change[0])" }
    }
    $backedUp = [Collections.Generic.List[object]]::new()
    $installed = [Collections.Generic.List[object]]::new()
    $cleanupCopies = [Collections.Generic.List[object]]::new()
    $committed = $false
    try {
        foreach ($change in $Changes) {
            if (Test-Path -LiteralPath $change[1]) {
                Move-Item -LiteralPath $change[1] -Destination "$($change[1]).rollback"
                $backedUp.Add($change)
            }
        }
        foreach ($change in $Changes) {
            if (-not $change[0]) { continue }
            Move-Item -LiteralPath $change[0] -Destination $change[1]
            $installed.Add($change)
        }
        if ($Validate) { & $Validate }
        foreach ($change in $backedUp) {
            $copy = "$($change[1]).rollback-recovery-$([Guid]::NewGuid().ToString('N'))"
            Copy-Item -LiteralPath "$($change[1]).rollback" -Destination $copy -Recurse
            $cleanupCopies.Add(@($copy, $change))
        }
        # Cleanup may fail, but must never roll back after deleting a recovery copy.
        $committed = $true
        foreach ($change in $backedUp) {
            Remove-Item -LiteralPath "$($change[1]).rollback" -Recurse -Force
        }
        foreach ($copy in $cleanupCopies) { Remove-Item -LiteralPath $copy[0] -Recurse -Force }
    } catch {
        if ($committed) {
            throw "Publication committed; cleanup failed. Keep remaining rollback/recovery files: $($_.Exception.Message)"
        }
        for ($index = $installed.Count - 1; $index -ge 0; $index--) {
            $change = $installed[$index]
            if (Test-Path -LiteralPath $change[1]) { Remove-Item -LiteralPath $change[1] -Recurse -Force }
        }
        for ($index = $backedUp.Count - 1; $index -ge 0; $index--) {
            $change = $backedUp[$index]
            $saved = "$($change[1]).rollback"
            if (-not (Test-Path -LiteralPath $saved)) {
                $saved = @($cleanupCopies | Where-Object { $_[1][1] -ceq $change[1] } | Select-Object -Last 1)[0][0]
            }
            if ($saved -and (Test-Path -LiteralPath $saved)) { Move-Item -LiteralPath $saved -Destination $change[1] }
        }
        foreach ($copy in $cleanupCopies) { if (Test-Path -LiteralPath $copy[0]) { Remove-Item -LiteralPath $copy[0] -Recurse -Force } }
        throw
    }
}

function Assert-SourceArchive([string] $Archive, [string] $Root, [string] $Version) {
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { throw "Quellarchiv fehlt: $Archive" }
    Add-Type -AssemblyName System.IO.Compression
    $expectedTop = "Magnolie-Organizer-Windows-$Version"
    $required = @(
        "Directory.Build.props",
        "LICENSE",
        "app/magnolie-organizer.ico",
        "app/web/kaffee-qr.mga",
        "app/symbole/48x48/magnolie-organizer.png",
        "app/symbole/64x64/magnolie-organizer.png",
        "app/symbole/128x128/magnolie-organizer.png",
        "app/symbole/256x256/magnolie-organizer.png",
        "contracts/kontakt-sync-contract.json",
        "contracts/recurrence-integration.json",
        "contracts/recurrence-timezones.json",
        "tests/fixtures/recurrence-rfc-oracle.json",
        "tests/resources/personal-sync-contract.json",
        "tests/resources/telefon-control-contract.json",
        "tests/resources/linux-parity-contract.json",
        "tests/linux-parity-fixture.js",
        "tests/generate-linux-parity-fixture.js",
        "shared/magnolie-handbuch/web/index.html",
        "shared/magnolie-handbuch/web/inhalt.js",
        "shared/magnolie-handbuch/web/i18n/en.js",
        "shared/magnolie-handbuch/web/kaffee-qr.mga",
        "shared/magnolie-handbuch/web/maik-walter.mga"
    )
    $stream = [IO.File]::OpenRead($Archive)
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read)
    try {
        $files = @($zip.Entries | Where-Object { $_.Name })
        if (-not $files) { throw "Quellarchiv ist leer: $Archive" }
        $names = @($files | ForEach-Object { $_.FullName.Replace('\', '/') })
        if (@($names | Where-Object { -not $_.StartsWith("$expectedTop/", [StringComparison]::Ordinal) }).Count) {
            throw "Quellarchiv hat nicht ausschließlich den erwarteten Hauptordner $expectedTop."
        }
        if ($names | Group-Object | Where-Object { $_.Count -gt 1 }) { throw "Quellarchiv enthält doppelte Dateipfade." }
        if (@($names | Where-Object { Test-PrivateReleasePath $_ }).Count) { throw 'Private path in source archive.' }
        if ($files.Count -gt 10000 -or @($files | Where-Object Length -GT 134217728).Count -or
            ($files | Measure-Object Length -Sum).Sum -gt 1073741824) { throw 'Source archive exceeds validation limits.' }
        if (@($names | Where-Object { [IO.Path]::GetFileName($_) -ceq "build-config.json" }).Count) {
            throw "Quellarchiv enthält build-config.json."
        }
        $contributorHash = [Environment]::GetEnvironmentVariable("MAGNOLIE_CONTRIBUTOR_HASH")
        if ($contributorHash -match '^[0-9a-fA-F]{64}$') {
            foreach ($file in $files) {
                $entryStream = $file.Open()
                $memory = [IO.MemoryStream]::new()
                try { $entryStream.CopyTo($memory) } finally { $entryStream.Dispose() }
                $content = [Text.Encoding]::ASCII.GetString($memory.ToArray())
                $memory.Dispose()
                if ($content.IndexOf($contributorHash, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    throw "Quellarchiv enthält den Contributor-Hash: $($file.FullName)"
                }
            }
        }
        $forbiddenDirectories = @(".git", "__pycache__", "Ausgabe", "bin", "handbook-windows-i18n", "handbuch", "node_modules", "obj")
        $forbiddenExtensions = @(".exe", ".dll", ".com", ".scr", ".sys", ".msi", ".msix", ".appx", ".appxbundle", ".msixbundle", ".pdb", ".pyc", ".zip", ".7z", ".rar", ".tar", ".gz", ".nupkg", ".sha256", ".iso", ".qcow2", ".vdi", ".vhd", ".vhdx", ".img", ".raw", ".ppm")
        $internalNotePattern = '(?i)(REVIEW|ENTWURF|OFFENE[-_ ]?PUNKTE|ANALYSE|PLAN|AUDIT).*\.md$'
        $generatedReleasePattern = '(?i)^(?:Magnolie-Organizer-Windows-.*-Setup-.*\.exe(?:\.build\.json)?|.*-x64\.zip|.*-Source\.zip|.*-PRUEFSUMMEN\.sha256)$'
        foreach ($file in $files) {
            $relative = $file.FullName.Replace('\', '/').Substring($expectedTop.Length + 1)
            $parts = $relative -split '/'
            $extension = [IO.Path]::GetExtension($file.Name)
            if ((Test-PrivateReleasePath $relative) -or ($parts -contains '..') -or
                ($parts -contains '.') -or $relative.StartsWith('/') -or $relative.Contains(':') -or
                (($file.ExternalAttributes -shr 16) -band 0xf000) -eq 0xa000 -or
                ($parts | Where-Object { $forbiddenDirectories -contains $_ }) -or
                ($parts | Where-Object { $_ -like '.release-staging-*' }) -or
                $file.Name -like "*~" -or
                ($file.Name -match $internalNotePattern -and
                    $relative -cne 'contracts/sms-plan-review-v1.md') -or
                $file.Name -imatch $generatedReleasePattern -or
                $file.Name -ieq ".magnolie-windows-release.lock" -or
                $forbiddenExtensions -contains $extension -or
                ($parts[0] -ieq "vm" -and $extension -ieq ".png")) {
                throw "Quellarchiv enthält erzeugte oder nicht quellgeeignete Datei: $relative"
            }
            $entryStream = $file.Open()
            try {
                $first = $entryStream.ReadByte()
                $second = $entryStream.ReadByte()
            } finally { $entryStream.Dispose() }
            if ($first -eq 0x4d -and $second -eq 0x5a) { throw "Quellarchiv enthält PE-Datei: $relative" }
            $reader = [IO.StreamReader]::new($file.Open(), [Text.Encoding]::ASCII)
            try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
            if ($content -match '-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?\n') { throw 'Private key material in source archive.' }
        }
        foreach ($relative in $required) {
            if (-not $zip.GetEntry("$expectedTop/$relative")) { throw "Quellarchiv-Pflichtdatei fehlt: $relative" }
        }
        foreach ($forbidden in "app/web/kaffee-qr.png", "shared/magnolie-handbuch/web/kaffee-qr.png", "shared/magnolie-handbuch/web/maik-walter.jpg") {
            if ($zip.GetEntry("$expectedTop/$forbidden")) { throw "Quellarchiv enthält Klartext-Personenasset: $forbidden" }
        }
        $currentFiles = @(Get-ReleaseArchiveSources $Root)
        $currentNames = @($currentFiles | ForEach-Object { "$expectedTop/$($_.Relative)" })
        if ($currentNames.Count -ne $names.Count -or (Compare-Object $currentNames $names -CaseSensitive)) {
            throw "Quellarchiv-Dateibestand entspricht nicht dem aktuellen Quellbaum."
        }
        foreach ($sourceFile in $currentFiles) {
            $relative = $sourceFile.Relative
            $entry = $zip.GetEntry("$expectedTop/$relative")
            $entryStream = $entry.Open()
            try { $entryHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($entryStream)) } finally { $entryStream.Dispose() }
            $sourceHash = (Get-FileHash -LiteralPath $sourceFile.Source -Algorithm SHA256).Hash
            if ($entryHash -cne $sourceHash) { throw "Quellarchiv ist nicht aktuell: $relative" }
        }
        $propsEntry = $zip.GetEntry("$expectedTop/Directory.Build.props")
        $reader = [IO.StreamReader]::new($propsEntry.Open(), [Text.Encoding]::UTF8, $true)
        try { [xml]$props = $reader.ReadToEnd() } finally { $reader.Dispose() }
        if ([string]$props.Project.PropertyGroup.Version -cne $Version) { throw "Quellarchiv-Version entspricht nicht $Version." }
    } finally { $zip.Dispose(); $stream.Dispose() }
}

function Write-ReleaseChecksums([string] $Root, [string] $Version, [string] $Destination, [object[]] $Artifacts) {
    $entries = foreach ($artifact in $Artifacts) {
        $source = [string]$artifact.Source
        $displayPath = [string]$artifact.DisplayPath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Pflichtartefakt für Prüfsumme fehlt: $source" }
        if (-not $displayPath -or [IO.Path]::IsPathRooted($displayPath) -or $displayPath -match '[\\/:\r\n]' -or $displayPath -in @('.', '..')) {
            throw "Ungültiger relativer Prüfsummenpfad: $displayPath"
        }
        [pscustomobject]@{ Source = [IO.Path]::GetFullPath($source); DisplayPath = $displayPath.Replace('\', '/') }
    }
    if (@($entries | Group-Object DisplayPath | Where-Object Count -gt 1).Count) { throw "Doppelter Prüfsummenpfad." }
    $lines = foreach ($entry in $entries | Sort-Object DisplayPath) {
        "{0}  {1}" -f (Get-FileHash -LiteralPath $entry.Source -Algorithm SHA256).Hash.ToLowerInvariant(), $entry.DisplayPath
    }
    if (-not $lines) { throw "Keine Artefakte für die Prüfsummendatei." }
    [IO.File]::WriteAllText($Destination, (($lines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
    foreach ($line in $lines) {
        $hash, $name = $line -split '  ', 2
        $path = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $Destination) $name))
        $entry = $entries | Where-Object DisplayPath -CEQ $name | Select-Object -First 1
        $comparison = if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
        if (-not [string]::Equals($path, $entry.Source, $comparison)) { throw "Prüfsummenpfad zeigt nicht auf das Quellartefakt: $name" }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) { throw "Prüfsummen-Selbsttest fehlgeschlagen: $name" }
    }
}

function Assert-BinaryPayloadFiles([string] $Publish) {
    foreach ($file in Get-ChildItem -LiteralPath $Publish -Recurse -File -Force) {
        $relative = [IO.Path]::GetRelativePath($Publish, $file.FullName).Replace('\', '/')
        if ((Test-PrivateReleasePath $relative) -or
            (($relative -split '/') | Where-Object { $_ -in @('tests', 'pruefungen', 'fixtures', 'contracts', '.git', 'node_modules') }) -or
            ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Non-product/private file in binary payload: $relative"
        }
    }
}

function Write-WindowsCandidateRecord([string] $Root, [string] $Directory, [string] $Version) {
    Assert-SourceArchive (Join-Path $Directory "Magnolie-Organizer-Windows-$Version-Source.zip") $Root $Version
    $artifacts = [ordered]@{}
    foreach ($suffix in 'Source.zip', 'x64.zip', 'Setup-x64.exe', 'Setup-x64.exe.build.json') {
        $name = "Magnolie-Organizer-Windows-$Version-$suffix"
        $path = Join-Path $Directory $name
        $artifacts[$name] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $record = [ordered]@{ schema = 'magnolie-windows-candidate-v1'; version = $Version; artifacts = $artifacts }
    $path = Join-Path $Directory "Magnolie-Organizer-Windows-$Version-provenance.json"
    [IO.File]::WriteAllText($path, ($record | ConvertTo-Json -Depth 5 -Compress) + "`n", [Text.UTF8Encoding]::new($false))
}

function Assert-WindowsCandidate([string] $Root, [string] $Directory, [string] $Version) {
    $record = Get-Content -LiteralPath (Join-Path $Directory "Magnolie-Organizer-Windows-$Version-provenance.json") -Raw | ConvertFrom-Json
    if ($record.schema -cne 'magnolie-windows-candidate-v1' -or $record.version -cne $Version -or
        @($record.artifacts.PSObject.Properties).Count -ne 4) { throw 'Invalid Windows candidate provenance.' }
    foreach ($suffix in 'Source.zip', 'x64.zip', 'Setup-x64.exe', 'Setup-x64.exe.build.json') {
        $name = "Magnolie-Organizer-Windows-$Version-$suffix"
        $expected = $record.artifacts.$name
        $path = Join-Path $Directory $name
        if ($expected -cnotmatch '^[0-9a-f]{64}$' -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected) {
            throw "Windows candidate artifact changed: $name"
        }
    }
    Assert-SourceArchive (Join-Path $Directory "Magnolie-Organizer-Windows-$Version-Source.zip") $Root $Version
}
