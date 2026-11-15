# Strict envelope/algorithm evidence only. Native Authenticode trust, publisher
# and timestamp-chain verification are independently required as well.
function Assert-PhoneTimestampImprint {
    param([byte[]] $Content, [byte[]] $ParentSignature)
    if ($Content.Length -lt 1 -or $Content.Length -gt 32768 -or $ParentSignature.Length -lt 1 -or $ParentSignature.Length -gt 8192) {
        throw 'RFC3161 content/signature size is outside the bounded policy.'
    }
    $sha256 = '2.16.840.1.101.3.4.2.1'
    $reader = [System.Formats.Asn1.AsnReader]::new([ReadOnlyMemory[byte]]::new($Content), [System.Formats.Asn1.AsnEncodingRules]::DER)
    $sequence = $reader.ReadSequence()
    $reader.ThrowIfNotEmpty()
    if ($sequence.ReadInteger() -ne 1) { throw 'Unsupported RFC3161 TSTInfo version.' }
    $null = $sequence.ReadObjectIdentifier() # TSA policy, not publisher authority.
    $imprint = $sequence.ReadSequence()
    $algorithm = $imprint.ReadSequence()
    if ($algorithm.ReadObjectIdentifier() -cne $sha256) { throw 'RFC3161 message imprint must use SHA256.' }
    if ($algorithm.HasData) { $algorithm.ReadNull() }
    $algorithm.ThrowIfNotEmpty()
    $hash = $imprint.ReadOctetString()
    $imprint.ThrowIfNotEmpty()
    $expected = [Security.Cryptography.SHA256]::HashData($ParentSignature)
    if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$hash, [byte[]]$expected)) { throw 'RFC3161 token is not bound to this Authenticode signature.' }
    if ($sequence.ReadInteger() -le 0) { throw 'RFC3161 timestamp serial is invalid.' }
    $null = $sequence.ReadGeneralizedTime()
    # Optional accuracy/order/nonce/TSA/extensions remain DER-bounded; native
    # Authenticode verification owns their trust/time/chain interpretation.
    while ($sequence.HasData) { $null = $sequence.ReadEncodedValue() }
}

function Assert-PhonePayloadAuthenticodeEnvelope {
    param([Parameter(Mandatory)][string] $Path)
    $sha256 = '2.16.840.1.101.3.4.2.1'
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'A regular native payload is required.' }
    $stream = [IO.File]::Open($item.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $pe = $null
    try {
        if ($stream.Length -lt 1 -or $stream.Length -gt 8 * 1024 * 1024) { throw 'Native payload size is outside its source-bound limit.' }
        $pe = [Reflection.PortableExecutable.PEReader]::new($stream, [Reflection.PortableExecutable.PEStreamOptions]::LeaveOpen)
        $directory = $pe.PEHeaders.PEHeader.CertificateTableDirectory
        $offset = [long]$directory.RelativeVirtualAddress # SECURITY uses a file offset, not an RVA.
        if ($offset -lt 1 -or $offset % 8 -ne 0 -or $directory.Size -lt 8 -or
            $directory.Size -gt 1024 * 1024 -or $offset + $directory.Size -gt $stream.Length) { throw 'Invalid Authenticode certificate table.' }
        $stream.Position = $offset
        $header = [byte[]]::new(8); $stream.ReadExactly($header, 0, 8)
        $length = [BitConverter]::ToUInt32($header, 0)
        if ($length -le 8 -or $length -gt $directory.Size -or
            (([long]$length + 7) -band -8L) -ne $directory.Size -or
            [BitConverter]::ToUInt16($header, 4) -ne 0x0200 -or [BitConverter]::ToUInt16($header, 6) -ne 2) {
            throw 'Exactly one bounded PKCS7 WIN_CERTIFICATE is required.'
        }
        $bytes = [byte[]]::new([int]$length - 8); $stream.ReadExactly($bytes, 0, $bytes.Length)
        $cms = [Security.Cryptography.Pkcs.SignedCms]::new(); $cms.Decode($bytes)
        if ($cms.ContentInfo.ContentType.Value -cne '1.3.6.1.4.1.311.2.1.4' -or $cms.SignerInfos.Count -ne 1) { throw 'A single Authenticode signer is required.' }
        $signer = $cms.SignerInfos[0]
        if ($signer.DigestAlgorithm.Value -cne $sha256 -or $signer.CounterSignerInfos.Count -ne 0) { throw 'Authenticode requires SHA256 and no legacy countersignature.' }
        $cms.CheckSignature($true) # Signature mathematics only, NOT chain trust.
        $indirect = [System.Formats.Asn1.AsnReader]::new([ReadOnlyMemory[byte]]::new($cms.ContentInfo.Content), [System.Formats.Asn1.AsnEncodingRules]::DER)
        $content = $indirect.ReadSequence(); $indirect.ThrowIfNotEmpty()
        $null = $content.ReadEncodedValue() # SpcAttributeTypeAndOptionalValue.
        $digest = $content.ReadSequence(); $content.ThrowIfNotEmpty()
        $algorithm = $digest.ReadSequence()
        if ($algorithm.ReadObjectIdentifier() -cne $sha256) { throw 'Authenticode PE digest must use SHA256.' }
        if ($algorithm.HasData) { $algorithm.ReadNull() }
        $algorithm.ThrowIfNotEmpty()
        if ($digest.ReadOctetString().Length -ne 32) { throw 'Invalid Authenticode PE digest length.' }
        $digest.ThrowIfNotEmpty() # Native trust verification checks the PE digest itself.
        $timestamps = @($signer.UnsignedAttributes | Where-Object { $_.Oid.Value -ceq '1.3.6.1.4.1.311.3.3.1' })
        if ($timestamps.Count -ne 1 -or $timestamps[0].Values.Count -ne 1 -or $signer.UnsignedAttributes.Count -ne 1) { throw 'Exactly one RFC3161 timestamp attribute is required.' }
        $timestamp = [Security.Cryptography.Pkcs.SignedCms]::new(); $timestamp.Decode($timestamps[0].Values[0].RawData)
        if ($timestamp.ContentInfo.ContentType.Value -cne '1.2.840.113549.1.9.16.1.4' -or $timestamp.SignerInfos.Count -ne 1 -or
            $timestamp.SignerInfos[0].DigestAlgorithm.Value -cne $sha256) { throw 'RFC3161 requires a single SHA256 token signer.' }
        $timestamp.CheckSignature($true) # Native verification separately owns TSA trust.
        Assert-PhoneTimestampImprint -Content $timestamp.ContentInfo.Content -ParentSignature $signer.GetSignature()
    } finally {
        if ($null -ne $pe) { $pe.Dispose() }
        $stream.Dispose()
    }
}
