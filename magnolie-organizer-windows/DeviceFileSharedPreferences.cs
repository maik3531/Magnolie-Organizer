using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal bool HasNativeMediaSharedSettings(string peerId)
    {
        lock (gate)
        {
            using var db = OpenNativeMediaDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_shared_settings'";
            if (read.ExecuteScalar() is null) return false;
            read.CommandText = "SELECT 1 FROM native_media_shared_settings WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", peerId); return read.ExecuteScalar() is not null;
        }
    }

    private (string Key, NativeMediaPreferenceScope Scope) MediaSharedBinding(string peerId, byte[] expectedPublic)
    {
        RequireNativeMediaStorageKey();
        var scope = MediaPreferenceScope(peerId);
        var peer = LoadPeers().SingleOrDefault(value => value.Id == peerId && value.State == "paired");
        if (peer is null || expectedPublic.Length != 32 || !CryptographicOperations.FixedTimeEquals(peer.PublicKey, expectedPublic))
            throw DeviceFileControl.Error("media_shared_peer_changed");
        var key = DeviceFileControl.Digest("magnolie-media-shared-scope-v1\0", new JsonObject {
            ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
            ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey });
        return ("media_shared_settings:" + key, scope);
    }

    private JsonObject? ReadMediaShared(SqliteConnection db, SqliteTransaction? transaction, string key, NativeMediaPreferenceScope scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_shared_settings'";
        if (exists.ExecuteScalar() is null) return null;
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT value FROM native_media_shared_settings WHERE peer_id=$peer";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        if (read.ExecuteScalar() is not byte[] encrypted) return null;
        if (encrypted.Length > 32768) throw DeviceFileControl.Error("media_shared_record_invalid");
        var plain = Open("native_media_shared_settings", scope.PeerId, encrypted);
        try
        {
            var record = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "body");
            if (TelefonProtocolContract.Integer(record["format"]) != 1 || record["scope"]?.GetValue<string>() != key || record["body"] is not JsonObject body)
                throw DeviceFileControl.Error("media_shared_record_invalid");
            return MediaSyncSettings.NormalizeStored(body, scope.LocalId, scope.PeerId);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private JsonObject LegacyMediaSharedProjection(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        // Read the untouched historical native record, not a fabricated grant.
        var previous = ReadNativeMediaPreferences(db, transaction, scope);
        var result = MediaSyncSettings.Create(scope.LocalId);
        if (previous.Version is null) return result;
        if (previous.SkipDeletions is not bool skip) throw DeviceFileControl.Error("media_shared_explicit_deletion_choice_required");
        var values = new JsonObject { ["enabled"] = previous.PhotosEnabled || previous.VideosEnabled,
            ["photos_enabled"] = previous.PhotosEnabled, ["videos_enabled"] = previous.VideosEnabled,
            ["auto_mode"] = previous.AutomaticWifi ? "wifi" : "manual", ["skip_deletions"] = skip };
        // A confirmed legacy choice outranks a fresh other-device bootstrap at
        // clock zero. No old record, mapping or deletion history is rewritten.
        foreach (var (field, value) in values)
            result = MediaSyncSettings.Change(result, scope.LocalId, scope.PeerId, field, value!);
        return result;
    }

    internal JsonObject? ReadNativeMediaSharedSettings(string peerId, byte[] expectedPublic)
    {
        lock (gate)
        {
            var (key, scope) = MediaSharedBinding(peerId, expectedPublic);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadMediaShared(db, null, key, scope);
            if (MediaSharedBinding(peerId, expectedPublic).Key != key) throw DeviceFileControl.Error("media_shared_peer_changed");
            return result;
        }
    }

    internal JsonObject ProjectNativeMediaSharedSettings(string peerId, byte[] expectedPublic)
    {
        lock (gate)
        {
            var (key, scope) = MediaSharedBinding(peerId, expectedPublic);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadMediaShared(db, null, key, scope) ?? LegacyMediaSharedProjection(db, null, scope);
            if (MediaSharedBinding(peerId, expectedPublic).Key != key) throw DeviceFileControl.Error("media_shared_peer_changed");
            return result;
        }
    }

    private static string MediaSharedFieldVersion(string key, JsonObject body, string field)
    {
        MediaSyncSettings.Validate(body);
        if (!body["settings"]!.AsObject().TryGetPropertyValue(field, out var register))
            throw DeviceFileControl.Error("media_shared_unknown_field");
        return DeviceFileControl.Digest("magnolie-media-shared-field-view-v1\0", new JsonArray(key, field, register!.DeepClone()));
    }

    internal string NativeMediaSharedFieldVersion(string peerId, byte[] expectedPublic, string field)
    {
        lock (gate)
        {
            var (key, _) = MediaSharedBinding(peerId, expectedPublic);
            var body = ProjectNativeMediaSharedSettings(peerId, expectedPublic);
            return MediaSharedFieldVersion(key, body, field);
        }
    }

    internal JsonObject NativeMediaSharedSettingsView(string peerId, byte[] expectedPublic)
    {
        lock (gate)
        {
            var (key, _) = MediaSharedBinding(peerId, expectedPublic);
            var body = ProjectNativeMediaSharedSettings(peerId, expectedPublic);
            var versions = new JsonObject();
            foreach (var (field, _) in body["settings"]!.AsObject())
                versions[field] = MediaSharedFieldVersion(key, body, field);
            if (MediaSharedBinding(peerId, expectedPublic).Key != key) throw DeviceFileControl.Error("media_shared_peer_changed");
            return new JsonObject { ["values"] = MediaSyncSettings.Configured(body), ["versions"] = versions };
        }
    }

    private JsonObject UpdateNativeMediaShared(string peerId, byte[] expectedPublic,
        Func<JsonObject, string, NativeMediaPreferenceScope, JsonObject> update)
    {
        lock (gate)
        {
            if (RestoreFenced) throw DeviceFileControl.Error("media_shared_restore_fenced");
            var (key, scope) = MediaSharedBinding(peerId, expectedPublic);
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var stored = ReadMediaShared(db, transaction, key, scope);
            var previous = stored ?? LegacyMediaSharedProjection(db, transaction, scope);
            var next = update(previous.DeepClone().AsObject(), key, scope);
            _ = MediaSyncSettings.Merge(next, next, scope.LocalId, scope.PeerId);
            if (MediaSharedBinding(peerId, expectedPublic).Key != key) throw DeviceFileControl.Error("media_shared_peer_changed");
            if (stored is not null && JsonNode.DeepEquals(stored, next)) return stored;
            using var write = db.CreateCommand(); write.Transaction = transaction;
            // The stable peer row retains evidence across key/epoch changes and
            // generic Notes cleanup. A changed binding HOLDs, never bootstraps
            // fresh defaults over an existing historical choice.
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_shared_settings(peer_id TEXT PRIMARY KEY, value BLOB NOT NULL); " +
                "INSERT INTO native_media_shared_settings(peer_id,value) VALUES($peer,$value) ON CONFLICT(peer_id) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", scope.PeerId);
            var plain = TelefonCrypto.Canonical(new JsonObject { ["format"] = 1, ["scope"] = key, ["body"] = next.DeepClone() });
            try { write.Parameters.AddWithValue("$value", Seal("native_media_shared_settings", scope.PeerId, plain)); }
            finally { CryptographicOperations.ZeroMemory(plain); }
            write.ExecuteNonQuery(); transaction.Commit();
            var actual = ReadMediaShared(db, null, key, scope);
            if (!JsonNode.DeepEquals(actual, next) || MediaSharedBinding(peerId, expectedPublic).Key != key)
                throw DeviceFileControl.Error("media_shared_commit_not_proven");
            return next;
        }
    }

    internal JsonObject ChangeNativeMediaSharedSetting(string peerId, byte[] expectedPublic, string field, JsonNode value, string expectedFieldVersion)
        => UpdateNativeMediaShared(peerId, expectedPublic, (body, key, scope) => {
            if (!DeviceFileControl.Hash(expectedFieldVersion) || MediaSharedFieldVersion(key, body, field) != expectedFieldVersion)
                throw DeviceFileControl.Error("media_shared_stale_field_choice");
            return MediaSyncSettings.Change(body, scope.LocalId, scope.PeerId, field, value);
        });

    internal JsonObject MergeNativeMediaSharedSettings(string peerId, byte[] expectedPublic, JsonObject incoming)
        => UpdateNativeMediaShared(peerId, expectedPublic, (body, _, scope) =>
            MediaSyncSettings.MergeCurrentChoices(body, incoming, scope.LocalId, scope.PeerId));
}
