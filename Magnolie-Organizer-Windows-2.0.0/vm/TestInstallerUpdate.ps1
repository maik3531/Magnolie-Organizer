$ErrorActionPreference = "Stop"

$installer = Join-Path $PSScriptRoot "Magnolie-Organizer-Windows-2.0.16-Setup-x64.exe"
$install = Join-Path $env:LOCALAPPDATA "Programs\Magnolie Organizer"
$resultPath = Join-Path $env:TEMP "Magnolie-Installer-Test.json"
$results = try {
    Get-PSDrive -PSProvider FileSystem | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.Root "MAGNOLIE_RESULTS") -PathType Leaf
    } | Select-Object -First 1
} catch { $null }
if (-not $results) {
    [Console]::Error.WriteLine("Der zwingende MAGNOLIE_RESULTS-Ergebnisdatentraeger fehlt; VM bleibt zur Diagnose aktiv.")
    exit 2
}
$resultFile = Join-Path $results.Root "RESULT.txt"
$resultLogFile = Join-Path $results.Root "windows-vm-test.log"
$logFile = $resultLogFile
foreach ($path in @($resultFile, $resultLogFile)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}
$checks = [ordered]@{}
$transcriptStarted = $false
$resultWritten = $false
$resultPersisted = $false
$logPersisted = $false

try {
    Start-Transcript -Path $logFile -Force | Out-Null
    $transcriptStarted = $true
} catch {
    $logFile = Join-Path $env:TEMP ("windows-vm-test-{0}.log" -f [guid]::NewGuid())
    try {
        Start-Transcript -Path $logFile -Force | Out-Null
        $transcriptStarted = $true
    } catch { }
}

function Test-Condition([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}

function Install-Magnolie {
    $process = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
    Test-Condition ($process.ExitCode -eq 0) "Installer beendete sich mit $($process.ExitCode)."
    Test-Condition (Test-Path -LiteralPath (Join-Path $install "Magnolie Organizer.exe") -PathType Leaf) `
        "Installierte Anwendung fehlt."
}

function Sync-ResultFile([string] $Path) {
    $lastError = $null
    foreach ($attempt in 1..10) {
        try {
            $share = [System.IO.FileShare]([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete)
            $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::ReadWrite, $share)
            try { $stream.Flush($true) } finally { $stream.Dispose() }
            return
        } catch {
            $lastError = $_
            if ($attempt -lt 10) { Start-Sleep -Milliseconds 250 }
        }
    }
    throw $lastError
}

function Write-InfrastructureFailure([string] $Message) {
    $line = "{0} INFRASTRUCTURE FAILURE: {1}" -f (Get-Date).ToString("o"), $Message
    try {
        @("FAIL", $Message) | Set-Content -LiteralPath $resultFile -Encoding UTF8
        Sync-ResultFile $resultFile
    } catch {
        [Console]::Error.WriteLine("RESULT.txt konnte nicht aktualisiert werden: {0}", $_.Exception.Message)
    }
    try {
        Add-Content -LiteralPath $resultLogFile -Encoding UTF8 -Value $line
        Sync-ResultFile $resultLogFile
    } catch {
        [Console]::Error.WriteLine("Ergebnisprotokoll konnte nicht aktualisiert werden: {0}", $_.Exception.Message)
    }
    [Console]::Error.WriteLine($line)
}

try {
    Get-Process -Name "Magnolie Organizer" -ErrorAction SilentlyContinue | Stop-Process -Force
    if (Test-Path -LiteralPath $install) { Remove-Item -LiteralPath $install -Recurse -Force }

    Install-Magnolie
    $checks.FreshInstall = $true
    Set-Content -LiteralPath (Join-Path $install "notes-from-user.txt") -Value "preserve" -Encoding ASCII

    Install-Magnolie
    Test-Condition ((Get-Content -LiteralPath (Join-Path $install "notes-from-user.txt") -Raw).Trim() -eq "preserve") `
        "Normales Update löschte die unbekannte Benutzerdatei."
    $checks.UpdateOverInstalledVersion = $true

    $uninstaller = Join-Path $install "Magnolie Organizer deinstallieren.exe"
    $process = Start-Process -FilePath $uninstaller -ArgumentList "/S" -Wait -PassThru
    Test-Condition ($process.ExitCode -eq 0) "Deinstaller beendete sich mit $($process.ExitCode)."
    $uninstallDeadline = (Get-Date).AddSeconds(15)
    while ((Test-Path -LiteralPath (Join-Path $install "Magnolie Organizer.exe")) -and
           (Get-Date) -lt $uninstallDeadline) {
        Start-Sleep -Milliseconds 200
    }
    if (Test-Path -LiteralPath (Join-Path $install "Magnolie Organizer.exe")) {
        $manifest = Join-Path $install ".magnolie-core.manifest"
        $remaining = if (Test-Path -LiteralPath $manifest) {
            Get-Content -LiteralPath $manifest | Where-Object { $_.StartsWith("F|") } |
                ForEach-Object { $_.Substring(2) } |
                Where-Object { Test-Path -LiteralPath (Join-Path $install $_) } |
                Select-Object -First 20
        } else { @("<Core-Besitzliste fehlt>") }
        throw "Deinstaller ließ verwaltete Dateien zurück: $($remaining -join ', ')"
    }
    Test-Condition (Test-Path -LiteralPath (Join-Path $install "notes-from-user.txt") -PathType Leaf) `
        "Deinstaller löschte eine unbekannte Benutzerdatei."
    Test-Condition (Test-Path -LiteralPath (Join-Path $install ".magnolie-installer") -PathType Leaf) `
        "Deinstaller kennzeichnete den geschützten Restordner nicht."
    Test-Condition (-not (Test-Path -LiteralPath (Join-Path $install ".magnolie-core.manifest"))) `
        "Deinstaller ließ die Core-Besitzliste zurück."
    $checks.ManagedRemainder = $true

    Install-Magnolie
    Test-Condition ((Get-Content -LiteralPath (Join-Path $install "notes-from-user.txt") -Raw).Trim() -eq "preserve") `
        "Wiederinstallation löschte die unbekannte Benutzerdatei."
    $checks.ReinstallOverManagedRemainder = $true

    $uiLog = Join-Path $env:TEMP "Magnolie-UI-Selbsttest.log"
    $uiError = Join-Path $env:TEMP "Magnolie-UI-Selbsttest-error.log"
    $ui = Start-Process -FilePath (Join-Path $install "Magnolie Organizer.exe") -ArgumentList "--ui-self-test" `
        -RedirectStandardOutput $uiLog -RedirectStandardError $uiError -Wait -PassThru
    $uiErrorText = if (Test-Path -LiteralPath $uiError) { Get-Content $uiError -Raw } else { "" }
    Test-Condition ($ui.ExitCode -eq 0) "UI-Selbsttest schlug fehl: $uiErrorText"
    $uiText = Get-Content $uiLog -Raw
    Test-Condition ($uiText -match "WINDOWS-BUNDLED-FONT-OK") "WebView2 bestätigte die eingebettete Schrift nicht."
    $checks.BundledFontLoaded = $true
    Test-Condition ($uiText -match "WINDOWS-HEALTH-LAYOUT-OK") `
        "WebView2 bestätigte die vollständige Datums- und Zeitdarstellung nicht."
    $checks.HealthLayoutChecked = $true
    $checks.WindowSizeChecked = $true

    $report = [ordered]@{ Passed = $true; Checks = $checks; Error = "" }
}
catch {
    $report = [ordered]@{ Passed = $false; Checks = $checks; Error = $_.Exception.ToString() }
}

$json = $report | ConvertTo-Json -Depth 4
try { $json | Set-Content -LiteralPath $resultPath -Encoding UTF8 } catch { }
$statusLines = if ($report.Passed) {
    @("SUCCESS", "All installer and UI checks passed.")
} else {
    @("FAIL", $report.Error)
}
try {
    $statusLines | Set-Content -LiteralPath $resultFile -Encoding UTF8
    $resultWritten = $true
} catch {
    $report = [ordered]@{
        Passed = $false
        Checks = $checks
        Error = "Ergebnisdatentraeger konnte nicht geschrieben werden: $($_.Exception.Message)"
    }
    $json = $report | ConvertTo-Json -Depth 4
    try { $json | Set-Content -LiteralPath $resultPath -Encoding UTF8 } catch { }
    try { @("FAIL", $report.Error) | Set-Content -LiteralPath (Join-Path $env:TEMP "RESULT.txt") -Encoding UTF8 } catch { }
}
try {
    Invoke-WebRequest -Uri "http://192.168.122.1:18080/" -Method Post `
        -ContentType "application/json" -Body $json -TimeoutSec 5 | Out-Null
}
catch { }

if ($transcriptStarted) {
    try { Stop-Transcript | Out-Null } catch {
        Write-InfrastructureFailure "PowerShell-Aufzeichnung konnte nicht beendet werden: $($_.Exception.Message)"
        exit 2
    }
}
if ($logFile -ne $resultLogFile) {
    try {
        Copy-Item -LiteralPath $logFile -Destination $resultLogFile -Force
        $logFile = $resultLogFile
    } catch {
        Write-InfrastructureFailure "Ergebnisprotokoll konnte nicht auf den Ergebnisdatentraeger kopiert werden: $($_.Exception.Message)"
        exit 2
    }
}
try {
    if (-not $resultWritten) { throw "Das primaere Testergebnis wurde nicht geschrieben." }
    Sync-ResultFile $resultFile
    $resultPersisted = $true
    Sync-ResultFile $resultLogFile
    $logPersisted = $true
} catch {
    Write-InfrastructureFailure "Ergebnisdateien konnten nicht dauerhaft geschrieben werden: $($_.Exception.Message)"
    exit 2
}
if ($results) {
    try {
        $mountOutput = @(& "$env:SystemRoot\System32\mountvol.exe" $results.Root /p 2>&1)
        $mountExitCode = $LASTEXITCODE
    } catch {
        Write-InfrastructureFailure "mountvol.exe konnte nicht gestartet werden: $($_.Exception.Message)"
        exit 2
    }
    if ($mountExitCode -ne 0) {
        Write-InfrastructureFailure "Ergebnisdatentraeger konnte nicht ausgehaengt werden (Exitcode $mountExitCode): $($mountOutput -join ' ')"
        exit 2
    }
}
try {
    $shutdownOutput = @(& "$env:SystemRoot\System32\shutdown.exe" /s /t 5 /f 2>&1)
    $shutdownExitCode = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("shutdown.exe konnte nicht gestartet werden: {0}", $_.Exception.Message)
    exit 2
}
if ($shutdownExitCode -ne 0) {
    [Console]::Error.WriteLine("VM konnte nicht heruntergefahren werden (Exitcode {0}): {1}",
        $shutdownExitCode, ($shutdownOutput -join " "))
    exit 2
}

if (-not $report.Passed) { exit 1 }
exit 0
