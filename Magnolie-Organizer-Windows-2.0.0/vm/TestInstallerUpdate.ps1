$ErrorActionPreference = "Stop"

$installer = Join-Path $PSScriptRoot "Magnolie-Organizer-Windows-2.0.11-Setup-x64.exe"
$install = Join-Path $env:LOCALAPPDATA "Programs\Magnolie Organizer"
$resultPath = Join-Path $env:TEMP "Magnolie-Installer-Test.json"
$checks = [ordered]@{}

function Test-Condition([bool] $Condition, [string] $Message) {
    if (-not $Condition) { throw $Message }
}

function Install-Magnolie {
    $process = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
    Test-Condition ($process.ExitCode -eq 0) "Installer beendete sich mit $($process.ExitCode)."
    Test-Condition (Test-Path -LiteralPath (Join-Path $install "Magnolie Organizer.exe") -PathType Leaf) `
        "Installierte Anwendung fehlt."
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
$json | Set-Content -LiteralPath $resultPath -Encoding UTF8
try {
    Invoke-WebRequest -Uri "http://192.168.122.1:18080/" -Method Post `
        -ContentType "application/json" -Body $json -TimeoutSec 5 | Out-Null
}
catch { }

if (-not $report.Passed) { exit 1 }
