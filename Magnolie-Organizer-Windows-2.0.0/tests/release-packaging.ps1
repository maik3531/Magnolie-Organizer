param([string] $Common = (Join-Path $PSScriptRoot '../build/Release.Common.ps1'))
$ErrorActionPreference = 'Stop'
. $Common
$oldHandbookOverride = [Environment]::GetEnvironmentVariable('MAGNOLIE_HANDBOOK_WEB')
[Environment]::SetEnvironmentVariable('MAGNOLIE_HANDBOOK_WEB', $null)
$temp = Join-Path ([IO.Path]::GetTempPath()) ('magnolie-packaging-fixtures-' + [Guid]::NewGuid().ToString('N'))
$root = Join-Path $temp 'standalone'
$output = Join-Path $temp 'artifacts'
$version = '9.8.7'
$top = "Magnolie-Organizer-Windows-$version"
$prefix = "$top-"
function Write-Fixture([string] $Path, [string] $Text = 'SYNTHETIC TEST DATA, NOT A PRODUCT OR CREDENTIAL') {
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}
function Assert-Rejected([scriptblock] $Action) {
    $rejected = $false
    try { & $Action } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unsafe synthetic fixture was accepted.' }
}
try {
    foreach ($relative in @(
        'LICENSE', 'app/magnolie-organizer.ico', 'app/web/kaffee-qr.mga',
        'app/symbole/48x48/magnolie-organizer.png', 'app/symbole/64x64/magnolie-organizer.png',
        'app/symbole/128x128/magnolie-organizer.png', 'app/symbole/256x256/magnolie-organizer.png',
        'tests/resources/personal-sync-contract.json', 'tests/resources/telefon-control-contract.json',
        'tests/resources/linux-parity-contract.json', 'tests/linux-parity-fixture.js',
        'tests/generate-linux-parity-fixture.js', 'tests/fixtures/new-schema.sql',
        'shared/magnolie-handbuch-stamm/web/index.html', 'shared/magnolie-handbuch-stamm/web/inhalt.js',
        'shared/magnolie-handbuch-stamm/web/i18n/de.js', 'shared/magnolie-handbuch-stamm/web/i18n/en.js', 'shared/magnolie-handbuch-stamm/web/kaffee-qr.mga',
        'shared/magnolie-handbuch-stamm/web/maik-walter.mga')) {
        Write-Fixture (Join-Path $root $relative)
    }
    Write-Fixture (Join-Path $root 'Directory.Build.props') "<Project><PropertyGroup><Version>$version</Version></PropertyGroup></Project>"
    foreach ($name in 'ProfileLease.cs', 'SmsSubmissionJournal.cs', 'BaumReceipt.cs', 'CloudBackupWorker.cs',
        'FirstRunSetupPhoneServices.cs', 'FirstRunPhoneStartup.cs', 'TelefonInvitation.cs',
        'WindowsCallNotifications.cs', 'TelefonCallActions.cs') {
        Write-Fixture (Join-Path $root $name) '// Synthetic current feature source'
    }
    Write-Fixture (Join-Path $root 'tests/fixtures/recurrence-rfc-oracle.json') '{"synthetic":true}'
    foreach ($name in 'kontakt-sync-contract.json', 'kontakt-import-contract.json', 'phone-region-vectors.json', 'thunderbird-addressbook-fixture.json', 'recurrence-integration.json', 'recurrence-timezones.json', 'baum-1-receipt-v1-vectors.json', 'new-reviewed-contract.json') {
        Write-Fixture (Join-Path $root "contracts/$name") '{"synthetic":true}'
    }
    foreach ($name in 'baum-1-receipt-v1.md', 'phone-bluetooth-first-pair.md', 'phone-setup-daemon-lifecycle.md', 'phone-wlan-invitation.md',
        'device-status-v4.md', 'native-call-audio.md', 'call-alert-actions-v2.md', 'sms-plan-review-v1.md') {
        Write-Fixture (Join-Path $root "contracts/$name") '# Synthetic public contract documentation'
    }
    foreach ($relative in 'local.token', 'local.secret', 'local.pem', '.private-testing/personal.json',
        'an-claude.md', 'shared/magnolie-handbuch-stamm/web/.private-testing/personal.json',
        'shared/magnolie-handbuch-stamm/web/local.token') {
        Write-Fixture (Join-Path $root $relative)
    }
    $files = @(Get-ReleaseArchiveSources $root)
    $names = @($files | ForEach-Object Relative)
    foreach ($name in 'ProfileLease.cs', 'SmsSubmissionJournal.cs', 'BaumReceipt.cs', 'CloudBackupWorker.cs',
        'FirstRunSetupPhoneServices.cs', 'FirstRunPhoneStartup.cs', 'TelefonInvitation.cs',
        'WindowsCallNotifications.cs', 'TelefonCallActions.cs',
        'contracts/device-status-v4.md', 'contracts/native-call-audio.md', 'contracts/call-alert-actions-v2.md',
        'contracts/sms-plan-review-v1.md',
        'contracts/baum-1-receipt-v1-vectors.json', 'contracts/phone-setup-daemon-lifecycle.md',
        'shared/magnolie-handbuch-stamm/web/i18n/en.js') {
        if ($names -notcontains $name) { throw "Current feature source missing from standalone archive: $name" }
    }
    if ($names -notcontains 'contracts/thunderbird-addressbook-fixture.json' -or
        $names -notcontains 'contracts/recurrence-integration.json' -or
        $names -notcontains 'contracts/recurrence-timezones.json' -or
        $names -notcontains 'tests/fixtures/recurrence-rfc-oracle.json' -or
        $names -notcontains 'contracts/new-reviewed-contract.json' -or
        $names -notcontains 'tests/fixtures/new-schema.sql') { throw 'Standalone source dependencies were dropped.' }
    if (@($names | Where-Object { Test-PrivateReleasePath $_ }).Count) { throw 'Private file entered source enumeration.' }
    $tree = Join-Path $temp 'archive-tree'
    foreach ($file in $files) {
        $target = Join-Path $tree $file.Relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        Copy-Item -LiteralPath $file.Source -Destination $target
    }
    [void][IO.Directory]::CreateDirectory($output)
    $archive = Join-Path $output ($prefix + 'Source.zip')
    New-DeterministicZip $tree $archive $top
    Assert-SourceArchive $archive $root $version
    # The public SMS review protocol is allowed; unrelated internal review notes are not.
    $internalReview = Join-Path $root 'contracts/internal-review.md'
    Write-Fixture $internalReview '# Synthetic internal review, not a public protocol'
    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Update)
    try {
        $entry = $zip.CreateEntry("$top/contracts/internal-review.md")
        $writer = [IO.StreamWriter]::new($entry.Open())
        try { $writer.Write([IO.File]::ReadAllText($internalReview)) } finally { $writer.Dispose() }
    } finally { $zip.Dispose() }
    Assert-Rejected { Assert-SourceArchive $archive $root $version }
    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Update)
    try { $zip.GetEntry("$top/contracts/internal-review.md").Delete() } finally { $zip.Dispose() }
    Remove-Item -LiteralPath $internalReview
    Assert-SourceArchive $archive $root $version
    foreach ($suffix in 'x64.zip', 'Setup-x64.exe', 'Setup-x64.exe.build.json') {
        Write-Fixture (Join-Path $output ($prefix + $suffix))
    }
    Write-WindowsCandidateRecord $root $output $version
    Assert-WindowsCandidate $root $output $version
    $licensePath = Join-Path $root 'LICENSE'
    $originalLicense = [IO.File]::ReadAllText($licensePath)
    Write-Fixture $licensePath 'changed canonical source while all candidate hashes remain valid'
    Assert-Rejected { Assert-WindowsCandidate $root $output $version }
    Write-Fixture $licensePath $originalLicense
    Assert-WindowsCandidate $root $output $version
    $artifacts = @(Get-ChildItem -LiteralPath $output -File | ForEach-Object {
        [pscustomobject]@{ Source = $_.FullName; DisplayPath = $_.Name }
    })
    $checksums = Join-Path $output 'synthetic.sha256'
    Write-ReleaseChecksums $root $version $checksums $artifacts
    Assert-Rejected { Write-ReleaseChecksums $root $version $checksums @([pscustomobject]@{ Source = $archive; DisplayPath = '../Source.zip' }) }
    Write-Fixture (Join-Path $output ($prefix + 'Setup-x64.exe')) 'changed installer'
    Assert-Rejected { Assert-WindowsCandidate $root $output $version }

    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Update)
    try {
        $entry = $zip.CreateEntry("$top/leak.token")
        $writer = [IO.StreamWriter]::new($entry.Open())
        try { $writer.Write('SYNTHETIC NON-CREDENTIAL') } finally { $writer.Dispose() }
    } finally { $zip.Dispose() }
    Assert-Rejected { Assert-SourceArchive $archive $root $version }
    $publish = Join-Path $temp 'publish'
    Write-Fixture (Join-Path $publish 'web/anwendung.js')
    Assert-BinaryPayloadFiles $publish
    Write-Fixture (Join-Path $publish 'tests/fixtures/new-schema.sql')
    Assert-Rejected { Assert-BinaryPayloadFiles $publish }
    $vm = Join-Path (Split-Path -Parent (Split-Path -Parent $Common)) 'vm/TestInstallerUpdate.ps1'
    $installerName = $prefix + 'Setup-x64.exe'
    $candidatePath = Join-Path $output 'candidate.json'
    $candidateData = @{
        schema = 'magnolie-desktop-candidate-v2'; version = $version; sourceSha256 = ('0' * 64)
        artifacts = @{ $installerName = @{ sha256 = (Get-FileHash (Join-Path $output $installerName)).Hash.ToLowerInvariant() } }
    }
    Write-Fixture $candidatePath ($candidateData | ConvertTo-Json -Depth 5)
    $pwsh = (Get-Process -Id $PID).Path
    Invoke-NativeCommand $pwsh @('-NoProfile', '-File', $vm, '-CandidateRecord', $candidatePath, '-ValidateOnly')
    Write-Fixture (Join-Path $output $installerName) 'tampered native media fixture'
    $vmRejected = $false
    try { Invoke-NativeCommand $pwsh @('-NoProfile', '-File', $vm, '-CandidateRecord', $candidatePath, '-ValidateOnly') 2>$null }
    catch { $vmRejected = $true }
    if (-not $vmRejected) { throw 'VM validation accepted a changed installer.' }
    # The actual publication helper, with ordinary text files and no build/signing.
    foreach ($failurePhase in 'validation', 'cleanup') {
        $transaction = Join-Path $temp $failurePhase
        $changes = @()
        foreach ($name in 'first', 'second') {
            $live = Join-Path $transaction "$name.live"
            $staged = Join-Path $transaction "$name.stage"
            Write-Fixture $live "OLD $name"
            Write-Fixture $staged "NEW $name"
            $changes += ,@($staged, $live)
        }
        if ($failurePhase -eq 'validation') {
            Assert-Rejected { Install-StagedPaths $changes { throw 'Synthetic validation fault' } }
            foreach ($name in 'first', 'second') {
                if ([IO.File]::ReadAllText((Join-Path $transaction "$name.live")) -cne "OLD $name") { throw 'Validation rollback failed.' }
            }
        } else {
            $script:recoveryDeletes = 0
            function Remove-Item {
                param([Parameter(Position=0)][Alias('LiteralPath')][string] $Path, [switch] $Recurse, [switch] $Force)
                if ($Path -like '*.rollback-recovery-*') {
                    $script:recoveryDeletes++
                    if ($script:recoveryDeletes -eq 2) { throw 'Synthetic recovery cleanup fault' }
                }
                Microsoft.PowerShell.Management\Remove-Item -LiteralPath $Path -Recurse:$Recurse -Force:$Force
            }
            try {
                $message = ''
                try { Install-StagedPaths $changes } catch { $message = $_.Exception.Message }
                if ($message -notlike 'Publication committed; cleanup failed.*') { throw 'Cleanup failure status was lost.' }
                foreach ($name in 'first', 'second') {
                    if ([IO.File]::ReadAllText((Join-Path $transaction "$name.live")) -cne "NEW $name") { throw 'Cleanup destroyed committed output.' }
                }
                if (@(Get-ChildItem $transaction -Filter '*.rollback-recovery-*').Count -ne 1) { throw 'Remaining recovery copy was not preserved.' }
            } finally {
                Microsoft.PowerShell.Management\Remove-Item Function:Remove-Item
            }
        }
    }
    Write-Output 'Windows source, private-path, new-fixture, provenance and flat-checksum fixtures passed.'
} finally {
    [Environment]::SetEnvironmentVariable('MAGNOLIE_HANDBOOK_WEB', $oldHandbookOverride)
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
