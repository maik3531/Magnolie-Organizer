using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Relationship metadata is preserved even in builds without media features.
// This identity helper creates no file consent, transport handler or READ grant.
internal static class NativeFilePairingIdentity
{
    internal static bool Hash(string? value) => value is { Length: 64 } && value.All(char.IsAsciiHexDigitLower);

    internal static string Epoch(byte[] transcript)
    {
        if (transcript.Length != 32) throw new InvalidDataException("file_pairing_invalid_transcript");
        var value = JsonValue.Create(Convert.ToBase64String(transcript))!;
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes("magnolie-native-file-pairing-v1\0")
            .Concat(TelefonCrypto.Canonical(value)).ToArray())).ToLowerInvariant();
    }
}
