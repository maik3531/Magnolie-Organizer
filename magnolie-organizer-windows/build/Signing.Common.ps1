function Assert-Signature([string] $Path, [switch] $ThirdParty) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) { throw "Authenticode-Prüfung fehlgeschlagen: $Path ($($signature.Status))" }
    if (-not $ThirdParty -and -not [string]::Equals($signature.SignerCertificate.Subject, $script:signingConfiguration["MAGNOLIE_SIGN_PUBLISHER"], [StringComparison]::Ordinal)) {
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
