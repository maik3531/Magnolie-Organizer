param([Parameter(Mandatory)][string] $Common)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. $Common

function Invoke-PublicationCase([string] $Failure) {
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("magnolie-pwsh-publish-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory $temp | Out-Null
    try {
        $live = Join-Path $temp "installer.exe"
        $record = Join-Path $temp "installer.exe.build.json"
        $stale = Join-Path $temp "old-UNSIGNED.exe"
        $stage = Join-Path $temp "new.exe"
        $recordStage = Join-Path $temp "new.build.json"
        Set-Content -LiteralPath $live -Value "old installer"
        Set-Content -LiteralPath $record -Value "old record"
        Set-Content -LiteralPath $stale -Value "old stale"
        Set-Content -LiteralPath $stage -Value "new installer"
        Set-Content -LiteralPath $recordStage -Value "new record"
        $script:cleanupFailure = $Failure -ceq "Cleanup"
        $script:recoveryFailure = $Failure -ceq "CleanupRecovery"
        $script:recoveryDeletes = 0
        function Remove-Item {
            param($LiteralPath, [switch] $Recurse, [switch] $Force)
            if ($script:cleanupFailure -and $LiteralPath -like "*.rollback") {
                $script:cleanupFailure = $false
                throw "simulierter Quarantäne-Cleanupfehler"
            }
            if ($script:recoveryFailure -and $LiteralPath -like "*.rollback-recovery-*") {
                $script:recoveryDeletes++
                if ($script:recoveryDeletes -eq 2) {
                    $script:recoveryFailure = $false
                    throw "simulierter spaeter Recovery-Cleanupfehler"
                }
            }
            Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse:$Recurse -Force:$Force
        }
        $caught = $null
        try {
            $changes = @()
            $changes += ,@($stage, $live)
            $changes += ,@($recordStage, $record)
            $changes += ,@($null, $stale)
            Install-StagedPaths $changes {
                if ((Get-Content -LiteralPath $live -Raw).Trim() -cne "new installer" -or
                    (Get-Content -LiteralPath $record -Raw).Trim() -cne "new record" -or
                    (Test-Path -LiteralPath $stale)) { throw "Validator sah keinen gemeinsam publizierten Zustand" }
                if ($Failure -ceq "Audit") { throw "simulierter Auditfehler" }
            }
        } catch {
            $caught = $_
            if (-not $Failure) { throw }
            if ($Failure -cin @("Cleanup", "CleanupRecovery")) {
                if ($_.Exception.Message -notlike "Publication committed; cleanup failed.*" -or $script:cleanupFailure -or $script:recoveryFailure) {
                    throw "Cleanupfehler wurde nicht nach dem Commit gemeldet"
                }
                if ((Get-Content -LiteralPath $live -Raw).Trim() -cne "new installer" -or
                    (Get-Content -LiteralPath $record -Raw).Trim() -cne "new record" -or (Test-Path -LiteralPath $stale)) {
                    throw "Cleanupfehler hat bereits publizierte neue Ausgaben zurueckgerollt"
                }
                foreach ($prior in @(@($live, "old installer"), @($record, "old record"), @($stale, "old stale"))) {
                    $copies = @(Get-ChildItem -LiteralPath $temp -File | Where-Object {
                        $_.Name -like ((Split-Path -Leaf $prior[0]) + ".rollback-recovery-*")
                    })
                    $expectedCopies = if ($Failure -ceq "CleanupRecovery" -and $prior[0] -ceq $live) { 0 } else { 1 }
                    if ($copies.Count -ne $expectedCopies -or ($expectedCopies -eq 1 -and
                        (Get-Content -LiteralPath $copies[0].FullName -Raw).Trim() -cne $prior[1])) {
                        throw "Alte Ausgabe ist nach dem Cleanupfehler nicht wiederherstellbar: $($prior[0])"
                    }
                }
            } elseif ((Get-Content -LiteralPath $live -Raw).Trim() -cne "old installer" -or
                (Get-Content -LiteralPath $record -Raw).Trim() -cne "old record" -or
                (Get-Content -LiteralPath $stale -Raw).Trim() -cne "old stale") {
                throw "PowerShell-Transaktion stellte nach $Failure nicht den alten Zustand wieder her"
            }
        }
        if ($Failure -and -not $caught) { throw "simulierter Fehler wurde nicht ausgeloest: $Failure" }
        if (-not $Failure -and (@(Get-ChildItem -LiteralPath $temp -Filter "*.rollback*").Count -ne 0)) {
            throw "Erfolgreiche Publikation hinterliess Rollback-Dateien"
        }
    } finally {
        Microsoft.PowerShell.Management\Remove-Item -LiteralPath $temp -Recurse -Force
    }
}

Invoke-PublicationCase ""
Invoke-PublicationCase "Audit"
Invoke-PublicationCase "Cleanup"
Invoke-PublicationCase "CleanupRecovery"
Write-Host "PowerShell-Installerpublikation ist transaktional."
