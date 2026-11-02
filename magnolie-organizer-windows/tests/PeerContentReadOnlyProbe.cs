using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// No TelefonStore constructor: it would initialize/clean the real database.
// Compare ALL authenticated plaintext fields, including last-seen/grants/keys;
// only the random encryption representation may differ.
internal static class PeerContentReadOnlyProbe
{
    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    internal static string ContentHash(byte[] encoded, byte[] key)
    {
        var envelope = JsonNode.Parse(encoded)!.AsObject();
        var blob = Convert.FromBase64String(envelope["blob"]!.GetValue<string>());
        if (blob.Length < 28) throw new CryptographicException("Invalid encrypted peer envelope.");
        var plain = new byte[blob.Length - 28]; byte[]? canonical = null;
        try
        {
            using (var aes = new AesGcm(key, 16)) aes.Decrypt(blob.AsSpan(0, 12), blob.AsSpan(12, plain.Length),
                blob.AsSpan(blob.Length - 16), plain, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1\0peersall"));
            // Preserve wrapper metadata too. Never drop volatile-looking fields.
            envelope["blob"] = JsonNode.Parse(plain) as JsonArray ?? throw new InvalidDataException("Invalid peer payload.");
            canonical = TelefonCrypto.Canonical(envelope);
            return Hash(canonical);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(blob); CryptographicOperations.ZeroMemory(plain);
            if (canonical is not null) CryptographicOperations.ZeroMemory(canonical);
        }
    }

    internal static int Run()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var paths = new WindowsPaths();
        if (File.Exists(paths.TelefonStorageKey) && new FileInfo(paths.TelefonStorageKey).Length > 4096 ||
            File.Exists(paths.TelefonPeers) && new FileInfo(paths.TelefonPeers).Length > 4 * 1024 * 1024)
            throw new InvalidDataException("Readonly witness size bound exceeded.");
        var keyFile = File.Exists(paths.TelefonStorageKey) ? File.ReadAllBytes(paths.TelefonStorageKey) : null;
        var encoded = File.Exists(paths.TelefonPeers) ? File.ReadAllBytes(paths.TelefonPeers) : null;
        byte[]? key = null;
        try
        {
            if (keyFile?.Length > 4096 || encoded?.Length > 4 * 1024 * 1024) throw new InvalidDataException("Readonly witness size bound exceeded.");
            string? content = null;
            if (encoded is not null)
            {
                if (keyFile is null) throw new InvalidDataException("Existing peer key is missing; no recovery or key creation allowed.");
                key = ProtectedData.Unprotect(Convert.FromBase64String(Encoding.UTF8.GetString(keyFile)),
                    Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser);
                content = ContentHash(encoded, key);
            }
            Console.WriteLine(new JsonObject { ["version"] = 1, ["ciphertextSha256"] = encoded is null ? null : Hash(encoded),
                ["storageKeySha256"] = keyFile is null ? null : Hash(keyFile), ["contentSha256"] = content }.ToJsonString());
            return 0;
        }
        finally
        {
            if (key is not null) CryptographicOperations.ZeroMemory(key);
            if (keyFile is not null) CryptographicOperations.ZeroMemory(keyFile);
            if (encoded is not null) CryptographicOperations.ZeroMemory(encoded);
        }
    }

    internal static void Verify()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-peer-witness-" + Guid.NewGuid().ToString("N"));
        var key = RandomNumberGenerator.GetBytes(32);
        try
        {
            var store = new TelefonStore(new WindowsPaths(root), key);
            var payload = JsonNode.Parse("[{\"device_id\":\"synthetic\",\"last_seen_ms\":100,\"grants\":{\"read\":true}}]")!.AsArray();
            byte[] Encode(JsonArray value) => Encoding.UTF8.GetBytes(new JsonObject {
                ["blob"] = Convert.ToBase64String(store.Seal("peers", "all", Encoding.UTF8.GetBytes(value.ToJsonString()))) }.ToJsonString());
            var a = Encode(payload); var b = Encode(payload); var digest = ContentHash(a, key);
            TestAssert.That(!a.SequenceEqual(b) && digest == ContentHash(b, key), "Random nonce changed the logical peer witness.");
            foreach (var field in new[] { "last_seen_ms", "grants", "device_id" })
            {
                var changed = payload.DeepClone().AsArray();
                changed[0]![field] = field == "last_seen_ms" ? JsonValue.Create(101) : field == "device_id" ?
                    JsonValue.Create("different-peer") : new JsonObject { ["read"] = false };
                TestAssert.That(ContentHash(Encode(changed), key) != digest, "Peer witness ignored a changed protected field: " + field);
            }
            var tampered = JsonNode.Parse(a)!.AsObject(); tampered["extra"] = true;
            TestAssert.That(ContentHash(Encoding.UTF8.GetBytes(tampered.ToJsonString()), key) != digest, "Envelope metadata was ignored.");
        }
        finally { CryptographicOperations.ZeroMemory(key); if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
}
