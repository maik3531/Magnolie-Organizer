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
        function Remove-Item {
            param($LiteralPath, [switch] $Recurse, [switch] $Force)
            if ($script:cleanupFailure -and $LiteralPath -like "*.rollback") {
                $script:cleanupFailure = $false
                throw "simulierter Quarantäne-Cleanupfehler"
            }
            Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse:$Recurse -Force:$Force
        }
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
            if ($Failure) { throw "simulierter Fehler wurde nicht ausgelöst: $Failure" }
        } catch {
            if (-not $Failure) { throw }
            if ((Get-Content -LiteralPath $live -Raw).Trim() -cne "old installer" -or
                (Get-Content -LiteralPath $record -Raw).Trim() -cne "old record" -or
                (Get-Content -LiteralPath $stale -Raw).Trim() -cne "old stale") {
                throw "PowerShell-Transaktion stellte nach $Failure nicht den alten Zustand wieder her"
            }
        }
    } finally {
        Microsoft.PowerShell.Management\Remove-Item -LiteralPath $temp -Recurse -Force
    }
}

Invoke-PublicationCase ""
Invoke-PublicationCase "Audit"
Invoke-PublicationCase "Cleanup"
Write-Host "PowerShell-Installerpublikation ist transaktional."
