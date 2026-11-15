# Synthetic policy regression only; no keys, signing, trust-store changes or installation.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot '../build/Signing.Common.ps1')
$script:signingConfiguration = @{ MAGNOLIE_SIGN_PUBLISHER = 'CN=Product'; MAGNOLIE_SIGNTOOL = 'mock' }
function Get-AuthenticodeSignature { param($LiteralPath) return $script:fixture }
function Invoke-NativeCommand { param($FilePath, $ArgumentList)
    if (($ArgumentList -join ' ') -ne 'verify /pa /all /tw fixture.exe') { throw 'Wrong verification flags' }
    if ($script:toolFailure) { throw 'Synthetic verification failure' }
}
$count = 0
foreach ($case in @(
    @('Valid', 'CN=Product', $true, $false, $false, $true),
    @('Valid', 'CN=Vendor', $true, $true, $false, $true),
    @('Valid', 'CN=Vendor', $true, $false, $false, $false),
    @('Valid', 'CN=Product extra', $true, $false, $false, $false),
    @('NotSigned', 'CN=Product', $true, $false, $false, $false),
    @('HashMismatch', 'CN=Vendor', $true, $true, $false, $false),
    @('NotTrusted', 'CN=Vendor', $true, $true, $false, $false),
    @('Valid', 'CN=Product', $false, $false, $false, $false),
    @('Valid', 'CN=Vendor', $false, $true, $false, $false),
    @('Valid', 'CN=Product', $true, $false, $true, $false)
)) {
    $script:fixture = [pscustomobject]@{ Status = $case[0]; SignerCertificate = [pscustomobject]@{ Subject = $case[1] }; TimeStamperCertificate = $case[2] }
    $script:toolFailure = $case[4]
    $passed = $true
    try { Assert-Signature 'fixture.exe' -ThirdParty:$case[3] } catch { $passed = $false }
    if ($passed -ne $case[5]) { throw "Policy regression failed: $($case -join ',')" }
    $count++
}
Write-Host "$count synthetic signature policy cases passed. Native Authenticode remains untested."
