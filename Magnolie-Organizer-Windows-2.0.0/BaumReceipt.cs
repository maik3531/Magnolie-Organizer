using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class BaumReceipt
{
    internal static string EnvelopeHash(JsonObject envelope) => Convert.ToHexString(
        SHA256.HashData(MagnolienbaumCrypto.Canonical(envelope))).ToLowerInvariant();

    internal static JsonObject Create(byte[] partnerKey, string sender, string recipient, JsonObject envelope)
    {
        var core = new JsonObject { ["format"] = "baum-1-receipt", ["version"] = 1,
            ["sender"] = sender, ["recipient"] = recipient, ["counter"] = envelope["zaehler"]!.DeepClone(),
            ["envelopeSha256"] = EnvelopeHash(envelope), ["status"] = "accepted" };
        var key = MagnolienbaumCrypto.HkdfSha256(partnerKey, null, "magnolienbaum\0baum-1\0receipt-v1"u8.ToArray(), 32);
        try { core["mac"] = Convert.ToBase64String(MagnolienbaumCrypto.Hmac(key, "magnolienbaum\0baum-1\0receipt-v1\0"u8.ToArray(), core)); }
        finally { CryptographicOperations.ZeroMemory(key); }
        return core;
    }

    internal static bool Verify(byte[] partnerKey, string sender, string recipient, JsonObject envelope, JsonObject receipt)
    {
        try
        {
            var expected = Create(partnerKey, sender, recipient, envelope);
            var actualMac = Convert.FromBase64String(receipt["mac"]!.GetValue<string>());
            var expectedMac = Convert.FromBase64String(expected["mac"]!.GetValue<string>());
            var core = receipt.DeepClone().AsObject(); core.Remove("mac"); expected.Remove("mac");
            return Convert.ToBase64String(actualMac) == receipt["mac"]!.GetValue<string>() &&
                JsonNode.DeepEquals(core, expected) && CryptographicOperations.FixedTimeEquals(actualMac, expectedMac);
        }
        catch (Exception error) when (error is FormatException or InvalidOperationException or NullReferenceException) { return false; }
    }
}
