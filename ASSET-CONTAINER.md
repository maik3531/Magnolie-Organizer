# Magnolie protected asset container (MGA v1)

MGA is a small, versioned AES-256-GCM container for the two personal assets
shipped with Magnolie. It is an obfuscation boundary that keeps plaintext files
out of package listings, not confidentiality, access control, origin
authentication, or DRM: the native GPL readers necessarily contain enough
information to reconstruct the runtime key and to create other valid
containers. The key and cryptography are deliberately absent from browser
JavaScript.

All integer fields are unsigned. Multi-byte integers are big-endian.

| Offset | Size | Meaning |
| --- | ---: | --- |
| 0 | 4 | ASCII magic `MGA1` |
| 4 | 1 | format version, exactly `1` |
| 5 | 1 | asset ID: `1` coffee QR, `2` handbook portrait |
| 6 | 1 | MIME ID: `1` image/png, `2` image/jpeg |
| 7 | 1 | flags, exactly `0` |
| 8 | 12 | AES-GCM nonce |
| 20 | 4 | ciphertext length including the 16-byte GCM tag |
| 24 | n | ciphertext followed by tag |

The complete 24-byte header is authenticated as additional data. Readers
require an exact expected asset ID and MIME ID, cap the complete container at
2 MiB, require ciphertext to contain at least the tag, reject trailing bytes,
and return data only after successful GCM authentication. They additionally
check the decrypted PNG/JPEG signature and a 1 MiB plaintext bound.

`tools/pack_personal_assets.py` is the deterministic reference packer. Its
nonce is the first 12 bytes of HMAC-SHA256 over the domain, asset ID, MIME ID,
and plaintext SHA-256. Therefore unchanged inputs produce byte-identical
containers. A changed plaintext gets a different nonce; IDs are unique under
the shared key. Package builds copy the checked-in `.mga` files and never run
the packer.

Runtime logical requests are intentionally limited to:

* organizer: `kaffee-qr.png`
* handbook: `kaffee-qr.png`
* handbook: `maik-walter.jpg`

The old logical names remain in translated handbook markup. Native WebKit and
WebView2 routing resolves them without exposing container paths to the page.
