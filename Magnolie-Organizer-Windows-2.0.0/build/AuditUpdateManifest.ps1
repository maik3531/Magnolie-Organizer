param(
    [Parameter(Mandatory)][string[]] $Manifest,
    [string] $PublishedInstaller,
    [string] $Report
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$results = foreach ($path in $Manifest) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Manifest fehlt: $path" }
    [xml]$xml = Get-Content -LiteralPath $path -Raw
    $windows = @($xml.SelectNodes("/update/windows"))
    if ($windows.Count -ne 1) { throw "Windows-Manifestvertrag ist nicht eindeutig: $path" }
    $hashNodes = @($windows[0].SelectNodes("sha256"))
    if ($hashNodes.Count -ne 1) { throw "Windows-Manifestvertrag ist nicht eindeutig: $path" }
    $claimed = [string]$hashNodes[0].InnerText
    $proven = $false
    if ($PublishedInstaller) {
        if (-not (Test-Path -LiteralPath $PublishedInstaller -PathType Leaf)) { throw "Veröffentlichter Installer fehlt: $PublishedInstaller" }
        $proven = $claimed -cmatch '^[0-9a-f]{64}$' -and
            $claimed -ceq (Get-FileHash -LiteralPath $PublishedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    [pscustomobject][ordered]@{
        manifest = [IO.Path]::GetFullPath($path)
        claimedWindowsSha256 = $claimed
        windowsReleaseStatus = if ($proven) { "VEROEFFENTLICHT-BELEGT" } else { "UNVEROEFFENTLICHT" }
        embeddedSignature = @($xml.SelectNodes("//*[translate(local-name(), 'SIGNATURE', 'signature')='signature']")).Count -gt 0
        reason = if ($proven) { "Hash stimmt bytegenau mit dem explizit geprüften Installer überein." } else { "Kein bytegleicher veröffentlichter Installer wurde belegt; der Manifestwert gilt nicht als Freigabenachweis." }
    }
}
if ($Report) {
    $json = $results | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($Report, "$json`n", [Text.UTF8Encoding]::new($false))
}
$results | Format-Table -AutoSize | Out-String | Write-Host
if (@($results | Where-Object windowsReleaseStatus -CEQ "UNVEROEFFENTLICHT").Count) { exit 3 }
