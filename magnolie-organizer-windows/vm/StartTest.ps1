$ErrorActionPreference = "Stop"

$target = "C:\Magnolie-Test"
$log = Join-Path $target "vm-self-test.log"
$result = Join-Path $target "vm-result.json"
$expectedVersion = (Get-Content (Join-Path $PSScriptRoot "Magnolie.Version") -Raw).Trim() + ".0"
$branding = (Get-Content (Join-Path $PSScriptRoot "Magnolie.Branding") -Raw).Trim()
if ($branding -cnotin @("official", "unbranded")) { throw "Ungültige Magnolie.Branding-Metadaten: $branding" }

New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "App\*") -Destination $target -Recurse -Force

$executable = Join-Path $target "Magnolie Organizer.exe"
$fileVersion = (Get-Item $executable).VersionInfo.FileVersion
if ($fileVersion -ne $expectedVersion) {
    throw "Unerwartete Dateiversion: $fileVersion (erwartet $expectedVersion)"
}
$selfTest = Start-Process -FilePath $executable -ArgumentList "--self-test" -Wait -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError (Join-Path $target "vm-self-test-error.log")
$packagingSelfTest = $null
if ($branding -ceq "official") {
    $packagingSelfTest = Start-Process -FilePath $executable -ArgumentList "--packaging-self-test" -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $target "vm-packaging-self-test.log") `
        -RedirectStandardError (Join-Path $target "vm-packaging-self-test-error.log")
}
$uiSelfTest = Start-Process -FilePath $executable -ArgumentList "--ui-self-test" -Wait -PassThru `
    -RedirectStandardOutput (Join-Path $target "vm-ui-self-test.log") `
    -RedirectStandardError (Join-Path $target "vm-ui-self-test-error.log")
$selfTestText = Get-Content -Path $log -Raw -ErrorAction SilentlyContinue
if (-not $selfTestText) { $selfTestText = "" }
$uiSelfTestText = Get-Content -Path (Join-Path $target "vm-ui-self-test.log") -Raw -ErrorAction SilentlyContinue
if (-not $uiSelfTestText) { $uiSelfTestText = "" }
$selfTestError = Get-Content -Path (Join-Path $target "vm-self-test-error.log") -Raw -ErrorAction SilentlyContinue
$packagingSelfTestError = if ($packagingSelfTest) { Get-Content -Path (Join-Path $target "vm-packaging-self-test-error.log") -Raw -ErrorAction SilentlyContinue } else { "" }
$uiSelfTestError = Get-Content -Path (Join-Path $target "vm-ui-self-test-error.log") -Raw -ErrorAction SilentlyContinue
$selfTestText += "`n" + $uiSelfTestText
$reminderCodes = [regex]::Matches($selfTestText, 'REMINDER-[A-Z-]+-OK') | ForEach-Object { $_.Value } | Select-Object -Unique
$recoveryCodes = [regex]::Matches($selfTestText, 'RECOVERY-[A-Z-]+-OK') | ForEach-Object { $_.Value } | Select-Object -Unique

$application = Start-Process -FilePath $executable -PassThru
Start-Sleep -Seconds 20

$webViewVersion = Get-ChildItem "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue } |
    Where-Object { $_.name -like "*WebView2*" } |
    Select-Object -First 1 -ExpandProperty pv -ErrorAction SilentlyContinue
$crossCompileRuntimeMarkerPresent = Test-Path -LiteralPath (Join-Path $target "WINDOWS-RUNTIME-UNVERIFIED.txt") -PathType Leaf

$report = [ordered]@{
    Timestamp = (Get-Date).ToString("o")
    Windows = [Environment]::OSVersion.VersionString
    Is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem
    SelfTestExitCode = $selfTest.ExitCode
    SelfTestError = if ($selfTestError) { $selfTestError.Trim() } else { "" }
    Branding = $branding
    PackagingSelfTestStatus = if (-not $packagingSelfTest) { "NotRun" } elseif ($packagingSelfTest.ExitCode -eq 0) { "Passed" } else { "Failed" }
    PackagingSelfTestExitCode = if ($packagingSelfTest) { $packagingSelfTest.ExitCode } else { $null }
    PackagingSelfTestPassed = if ($packagingSelfTest) { $packagingSelfTest.ExitCode -eq 0 } else { $null }
    PackagingSelfTestError = if ($packagingSelfTestError) { $packagingSelfTestError.Trim() } else { "" }
    UiSelfTestExitCode = $uiSelfTest.ExitCode
    UiSelfTestError = if ($uiSelfTestError) { $uiSelfTestError.Trim() } else { "" }
    ReminderTestCodes = @($reminderCodes)
    RecoveryTestCodes = @($recoveryCodes)
    ReminderTestsPassed = @($reminderCodes).Count -ge 2
    RecoveryTestsPassed = @($recoveryCodes).Count -ge 2
    ApplicationRunning = -not $application.HasExited
    WebView2Runtime = $webViewVersion
    CrossCompileRuntimeMarkerPresent = $crossCompileRuntimeMarkerPresent
    ExecutableSha256 = (Get-FileHash $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    FileVersion = $fileVersion
} | ConvertTo-Json
$report | Set-Content -Path $result -Encoding UTF8

try {
    Invoke-WebRequest -Uri "http://192.168.122.1:18080/" -Method Post `
        -ContentType "application/json" -Body $report -TimeoutSec 5 | Out-Null
}
catch {
    Add-Content -Path $log -Value "Host-Bericht konnte nicht gesendet werden: $($_.Exception.Message)"
}

powercfg.exe /change monitor-timeout-ac 0 | Out-Null
powercfg.exe /change standby-timeout-ac 0 | Out-Null

if ($branding -ceq "official" -and $packagingSelfTest.ExitCode -ne 0) {
    throw "Offizieller Packaging-Selbsttest fehlgeschlagen (Exitcode $($packagingSelfTest.ExitCode))."
}
