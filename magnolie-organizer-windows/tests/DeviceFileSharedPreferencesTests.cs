using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSharedPreferencesTests
{
    private static void Identity(DeviceFileConnectionMetadataTests.Fixture f)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
    }

    private static byte[]? Blob(TelefonStore store)
    {
        using var db = store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT 1 FROM sqlite_master WHERE name='native_media_shared_settings'";
        if (query.ExecuteScalar() is null) return null;
        query.CommandText = "SELECT value FROM native_media_shared_settings";
        return query.ExecuteScalar() as byte[];
    }

    internal static Task SevenFieldProjectionAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var version = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "skip_deletions");
        _ = f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "skip_deletions", JsonValue.Create(true)!, version);
        var enabledVersion = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled");
        var clear = f.Store.Open("native_media_shared_settings", f.Peer.Id, Blob(f.Store)!);
        JsonObject record;
        try { record = JsonNode.Parse(clear)!.AsObject(); }
        finally { CryptographicOperations.ZeroMemory(clear); }
        record["body"]!["settings"]!.AsObject().Remove("photos_only"); var old = record["body"]!.DeepClone();
        var payload = TelefonCrypto.Canonical(record);
        byte[] historical;
        try { historical = f.Store.Seal("native_media_shared_settings", f.Peer.Id, payload); }
        finally { CryptographicOperations.ZeroMemory(payload); }
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var write = db.CreateCommand(); write.CommandText = "UPDATE native_media_shared_settings SET value=$value";
            write.Parameters.AddWithValue("$value", historical); write.ExecuteNonQuery();
        }
        var projection = f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)!;
        TestAssert.That(historical.SequenceEqual(Blob(f.Store)!) && !MediaSyncSettings.Effective(projection)["photos_only"]!.GetValue<bool>() &&
            enabledVersion == f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled"),
            "Passive seven-field projection rewrote ciphertext, enabled the filter or invalidated an unrelated field.");
        var filterVersion = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "photos_only");
        var changed = f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "photos_only", JsonValue.Create(true)!, filterVersion);
        var others = changed.DeepClone().AsObject(); others["settings"]!.AsObject().Remove("photos_only");
        TestAssert.That(!historical.SequenceEqual(Blob(f.Store)!) && JsonNode.DeepEquals(old, others) &&
            JsonNode.DeepEquals(changed, f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)),
            "The explicit filter edit did not persist or rewrote a historical register.");
        return Task.CompletedTask;
    }

    internal static Task PersistenceAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var grants = f.Store.LocalGrants().DeepClone(); var personal = f.Store.PersonalSettings(f.Peer.Id);
        var initial = f.Store.ProjectNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey);
        TestAssert.That(Blob(f.Store) is null && f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey) is null &&
            !MediaSyncSettings.RequestedFor(initial, "images"), "Read-only projection persisted or enabled media.");
        var enabledVersion = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled");
        var videoVersion = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "videos_enabled");
        var first = f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "enabled", JsonValue.Create(true)!, enabledVersion);
        var next = f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "videos_enabled", JsonValue.Create(true)!, videoVersion);
        TestAssert.That(MediaSyncSettings.RequestedFor(next, "images") && MediaSyncSettings.RequestedFor(next, "video"),
            "An unrelated field edit invalidated the independent choice.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey,
            "enabled", JsonValue.Create(false)!, enabledVersion), "Stale field choice overwrote a newer edit.");
        var cipher = Blob(f.Store)!;
        TestAssert.That(!Encoding.UTF8.GetString(cipher).Contains("photos_enabled"), "Shared intent was stored as plaintext.");
        var reopened = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(JsonNode.DeepEquals(next, reopened.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)), "Reopen lost shared intent.");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var delete = db.CreateCommand(); delete.CommandText = "DELETE FROM meta"; delete.ExecuteNonQuery();
        }
        TestAssert.That(JsonNode.DeepEquals(next, f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)) &&
            JsonNode.DeepEquals(grants, f.Store.LocalGrants()) && personal == f.Store.PersonalSettings(f.Peer.Id) &&
            f.Store.ReadNativeMediaPreferences(f.Peer.Id).Version is null, "Shared settings changed rights/native preferences or were cleared by Notes cleanup.");
        var actor = next["settings"]!["enabled"]!.AsObject().Single().Key;
        var remote = MediaSyncSettings.Merge(MediaSyncSettings.Create(f.Peer.Id), next, f.Peer.Id, actor);
        remote = MediaSyncSettings.Change(remote, f.Peer.Id, actor, "auto_mode", JsonValue.Create("wifi")!);
        var merged = f.Store.MergeNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey, remote);
        var saved = Blob(f.Store)!;
        TestAssert.That(MediaSyncSettings.Effective(merged)["auto_mode"]!.GetValue<string>() == "wifi" &&
            JsonNode.DeepEquals(merged, f.Store.MergeNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey, remote)) &&
            saved.SequenceEqual(Blob(f.Store)!), "Merge/echo did not persist idempotently.");
        remote["settings"]!["enabled"]![actor]!["counter"] = 99;
        TestAssert.Throws<InvalidDataException>(() => f.Store.MergeNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey, remote), "Forged local clock was accepted.");
        TestAssert.That(saved.SequenceEqual(Blob(f.Store)!), "Rejected echo changed ciphertext.");
        return Task.CompletedTask;
    }

    internal static Task IndependentDirectionViewAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var grants = f.Store.LocalGrants().DeepClone(); var native = f.Store.ReadNativeMediaPreferences(f.Peer.Id);
        JsonObject Change(string field, JsonNode value) => f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey,
            field, value, f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, field));
        _ = Change("enabled", JsonValue.Create(true)!);
        _ = Change("direction", JsonValue.Create("pc_to_phone")!);
        _ = Change("auto_mode", JsonValue.Create("wifi")!);
        var stored = Change("collection_mode", JsonValue.Create("import_only")!); var ciphertext = Blob(f.Store)!;
        var version = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "direction");
        var view = f.Store.NativeMediaSharedSettingsView(f.Peer.Id, f.Peer.PublicKey);
        TestAssert.That(view["values"]!["direction"]!.GetValue<string>() == "pc_to_phone" &&
            view["values"]!["auto_mode"]!.GetValue<string>() == "wifi" &&
            view["versions"]!["direction"]!.GetValue<string>() == version,
            "Import-only UI replaced the independently stored direction or mode with its effective transfer policy.");
        TestAssert.That(!MediaSyncSettings.TransferRequestedFor(stored, "images", true) &&
            MediaSyncSettings.TransferRequestedFor(stored, "images", false) && ciphertext.SequenceEqual(Blob(f.Store)!) &&
            JsonNode.DeepEquals(grants, f.Store.LocalGrants()) && native == f.Store.ReadNativeMediaPreferences(f.Peer.Id),
            "A configured display granted export, changed native rights or rewrote stored settings.");
        var changed = Change("direction", JsonValue.Create("two_way")!);
        TestAssert.That(!MediaSyncSettings.TransferRequestedFor(changed, "images", true) &&
            f.Store.NativeMediaSharedSettingsView(f.Peer.Id, f.Peer.PublicKey)["values"]!["direction"]!.GetValue<string>() == "two_way",
            "An independent direction edit bypassed import-only or did not remain visible.");
        var restored = Change("collection_mode", JsonValue.Create("phone_inventory")!);
        TestAssert.That(MediaSyncSettings.TransferRequestedFor(restored, "images", true) &&
            JsonNode.DeepEquals(changed["settings"]!["direction"], restored["settings"]!["direction"]),
            "Returning to inventory reset the independently edited direction history.");
        return Task.CompletedTask;
    }

    internal static Task LegacyAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var old = f.Store.SetNativeMediaPreferences(f.Peer.Id, null, false, true, true);
        var projected = f.Store.ProjectNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey);
        var values = MediaSyncSettings.Effective(projected);
        TestAssert.That(values["enabled"]!.GetValue<bool>() && !values["photos_enabled"]!.GetValue<bool>() &&
            values["videos_enabled"]!.GetValue<bool>() && values["skip_deletions"]!.GetValue<bool>() &&
            values["auto_mode"]!.GetValue<string>() == "wifi" && Blob(f.Store) is null &&
            f.Store.ReadNativeMediaPreferences(f.Peer.Id) == old, "Legacy projection reset explicit choices or wrote migration state.");
        f.Store.SetNativeMediaPreferences(f.Peer.Id, old.Version, false, true, true, deleteFromPhone: true);
        TestAssert.Throws<InvalidDataException>(() => f.Store.ProjectNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey), "Mixed deletion choices were silently normalized.");
        TestAssert.That(Blob(f.Store) is null, "Ambiguous projection persisted a replacement.");
        return Task.CompletedTask;
    }

    internal static Task BindingAsync()
    {
        foreach (var change in new[] { "key", "pairing", "local", "unpaired", "corrupt", "restore" })
        {
            using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
            var version = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled");
            f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "enabled", JsonValue.Create(true)!, version);
            var expectedKey = f.Peer.PublicKey;
            string? token = null;
            if (change == "key") { expectedKey = Enumerable.Repeat((byte)91, 32).ToArray(); f.Store.SavePeers([f.Peer with { PublicKey = expectedKey }]); }
            if (change == "pairing") f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
            if (change == "unpaired") f.Store.SavePeers([]);
            if (change == "local") { File.Delete(f.Paths.TelefonIdentity); File.Delete(f.Paths.TelefonIdentityKey); Identity(f); }
            if (change == "restore") { token = Guid.NewGuid().ToString("D"); f.Store.BeginRestore(token); }
            if (change == "corrupt")
            {
                var damaged = Blob(f.Store)!; damaged[^1] ^= 1;
                using var db = f.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
                write.CommandText = "UPDATE native_media_shared_settings SET value=$value"; write.Parameters.AddWithValue("$value", damaged); write.ExecuteNonQuery();
            }
            var before = Blob(f.Store)!;
            void Reject(Action action)
            {
                if (change == "corrupt") TestAssert.Throws<CryptographicException>(action, "Corrupt intent was reset.");
                else TestAssert.Throws<InvalidDataException>(action, "Changed binding was reused: " + change);
            }
            Reject(() => f.Store.ProjectNativeMediaSharedSettings(f.Peer.Id, expectedKey));
            Reject(() => f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, expectedKey, "enabled", JsonValue.Create(false)!, version));
            TestAssert.That(before.SequenceEqual(Blob(f.Store)!), "HOLD changed protected history: " + change);
            if (token is not null) f.Store.AbortRestore(token);
        }
        return Task.CompletedTask;
    }
}
