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

    private static byte[] ReadShared(string path, int maximum)
    {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        if (input.Length > maximum) throw new InvalidDataException("Readonly witness size bound exceeded.");
        using var output = new MemoryStream(); var buffer = new byte[8192];
        int count;
        while ((count = input.Read(buffer)) != 0)
        {
            if (output.Length + count > maximum) throw new InvalidDataException("Readonly witness size bound exceeded.");
            output.Write(buffer, 0, count);
        }
        return output.ToArray();
    }

    internal static string ContentHash(byte[] encoded, byte[] key, Action<JsonObject>? inspect = null)
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
            inspect?.Invoke(envelope);
            canonical = TelefonCrypto.Canonical(envelope);
            return Hash(canonical);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(blob); CryptographicOperations.ZeroMemory(plain);
            if (canonical is not null) CryptographicOperations.ZeroMemory(canonical);
        }
    }

    private static JsonObject Snapshot(Action<JsonObject>? inspect = null)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var paths = new WindowsPaths();
        if (File.Exists(paths.TelefonStorageKey) && new FileInfo(paths.TelefonStorageKey).Length > 4096 ||
            File.Exists(paths.TelefonPeers) && new FileInfo(paths.TelefonPeers).Length > 4 * 1024 * 1024)
            throw new InvalidDataException("Readonly witness size bound exceeded.");
        var keyFile = File.Exists(paths.TelefonStorageKey) ? ReadShared(paths.TelefonStorageKey, 4096) : null;
        var encoded = File.Exists(paths.TelefonPeers) ? ReadShared(paths.TelefonPeers, 4 * 1024 * 1024) : null;
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
                content = ContentHash(encoded, key, inspect);
            }
            return new JsonObject { ["version"] = 1, ["ciphertextSha256"] = encoded is null ? null : Hash(encoded),
                ["storageKeySha256"] = keyFile is null ? null : Hash(keyFile), ["contentSha256"] = content };
        }
        finally
        {
            if (key is not null) CryptographicOperations.ZeroMemory(key);
            if (keyFile is not null) CryptographicOperations.ZeroMemory(keyFile);
            if (encoded is not null) CryptographicOperations.ZeroMemory(encoded);
        }
    }

    internal static int Run()
    {
        Console.WriteLine(Snapshot().ToJsonString());
        return 0;
    }

    internal static int MediaReadiness()
    {
        var rows = new JsonArray();
        _ = Snapshot(envelope => {
            foreach (var item in envelope["blob"]!.AsArray())
            {
                var peer = item!.AsObject();
                var status = peer["capabilities"]?["device_status"] as JsonObject;
                var versions = status?["versions"] as JsonArray;
                bool Has(int version) => versions?.Any(value => TelefonProtocolContract.TryInteger(value, out var number) && number == version) == true;
                rows.Add(new JsonObject { ["paired"] = peer["state"]?.GetValue<string>() == "paired",
                    ["nativePairingPresent"] = DeviceFileControl.Hash(peer["file_pairing_epoch"]?.GetValue<string>() ?? ""),
                    ["statusAvailable"] = status?["available"]?.GetValue<bool>() == true,
                    ["photoSourceAdvertised"] = Has(21), ["videoSourceAdvertised"] = Has(22) });
            }
        });
        Console.WriteLine(new JsonObject { ["productWrites"] = false, ["peers"] = rows }.ToJsonString());
        return 0;
    }

    private static Dictionary<string, string> FieldHashes(JsonObject envelope)
    {
        string Of(JsonNode? value)
        {
            var bytes = TelefonCrypto.Canonical(new JsonArray(value?.DeepClone()));
            try { return Hash(bytes); } finally { CryptographicOperations.ZeroMemory(bytes); }
        }
        string[] names = ["device_id", "display_name", "static_public", "state", "last_seen_ms", "capability_revision",
            "capabilities", "grant_revision", "grants", "pending_transcript", "pending_phone_proof", "pending_desktop_proof",
            "pending_expires_ms", "bluetooth_address"];
        var result = new Dictionary<string, string>();
        var wrapper = envelope.DeepClone().AsObject(); wrapper.Remove("blob"); result["wrapper"] = Of(wrapper);
        var peers = envelope["blob"]!.AsArray(); result["peer_count"] = Of(JsonValue.Create(peers.Count));
        for (var index = 0; index < peers.Count; index++)
        {
            var peer = peers[index]!.AsObject(); result[$"peer{index}:all_fields"] = Of(peer);
            foreach (var name in names) result[$"peer{index}:{name}"] = Of(peer[name]);
        }
        return result;
    }

    internal static int ObserveChanges()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var paths = new WindowsPaths();
        if (!Directory.Exists(paths.Telefon)) throw new DirectoryNotFoundException("Existing phone directory required.");
        using var watcher = new FileSystemWatcher(paths.Telefon, "peers.json") {
            NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.FileName, EnableRaisingEvents = true };
        var a = new Dictionary<string, string>(); var b = new Dictionary<string, string>();
        var before = Snapshot(envelope => a = FieldHashes(envelope));
        var observed = watcher.WaitForChanged(WatcherChangeTypes.All, 90_000);
        var after = Snapshot(envelope => b = FieldHashes(envelope));
        var changes = a.Keys.Concat(b.Keys).Distinct().Where(name => a.GetValueOrDefault(name) != b.GetValueOrDefault(name)).Order(StringComparer.Ordinal);
        Console.WriteLine(new JsonObject { ["version"] = 1, ["productWrites"] = false,
            ["eventObserved"] = !observed.TimedOut,
            ["ciphertextChanged"] = !JsonNode.DeepEquals(before["ciphertextSha256"], after["ciphertextSha256"]),
            ["contentChanged"] = !JsonNode.DeepEquals(before["contentSha256"], after["contentSha256"]),
            ["changedFields"] = new JsonArray(changes.Select(name => JsonValue.Create(name)).ToArray()) }.ToJsonString());
        return 0;
    }

    internal static void Verify()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-peer-witness-" + Guid.NewGuid().ToString("N"));
        var key = RandomNumberGenerator.GetBytes(32);
        try
        {
            var store = new TelefonStore(new WindowsPaths(root), key);
            using var ownPool = new OwnedTelefonPool(store);
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
            var beforeFields = new Dictionary<string, string>();
            ContentHash(a, key, envelope => beforeFields = FieldHashes(envelope));
            payload[0]!["last_seen_ms"] = 101;
            var afterFields = new Dictionary<string, string>();
            ContentHash(Encode(payload), key, envelope => afterFields = FieldHashes(envelope));
            var changedFields = beforeFields.Keys.Where(name => beforeFields[name] != afterFields[name]).ToArray();
            TestAssert.That(changedFields.Order().SequenceEqual(new[] { "peer0:all_fields", "peer0:last_seen_ms" }),
                "Readonly field diagnosis did not isolate the exact changed schema field.");
            TestAssert.That(!string.Join(',', beforeFields.Keys).Contains("synthetic", StringComparison.Ordinal),
                "Field diagnosis exposed a peer value instead of a schema field name.");
        }
        finally { CryptographicOperations.ZeroMemory(key); if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
}
