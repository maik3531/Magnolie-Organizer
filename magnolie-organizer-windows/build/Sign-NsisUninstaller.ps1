param([Parameter(Mandatory)][string] $Path)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
try {
    . (Join-Path $PSScriptRoot 'Release.Common.ps1')
    . (Join-Path $PSScriptRoot 'Signing.Common.ps1')
    $secret = Import-Clixml -LiteralPath $env:MAGNOLIE_NSIS_SIGN_CONFIG
    $receipt = $env:MAGNOLIE_NSIS_SIGN_RECEIPT
    $env:MAGNOLIE_NSIS_SIGN_CONFIG = $null
    $env:MAGNOLIE_NSIS_SIGN_RECEIPT = $null
    $json = [Net.NetworkCredential]::new('', $secret).Password
    $script:signingConfiguration = @{}
    ($json | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $script:signingConfiguration[$_.Name] = $_.Value }
    $json = $null
    $official = $true
    Sign-Official $Path
    [pscustomobject]@{ sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash } |
        ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
    exit 0
} catch {
    # Do not serialize exceptions that could contain signing configuration.
    [Console]::Error.WriteLine('NSIS uninstaller signing/verification failed.')
    exit 1
}
