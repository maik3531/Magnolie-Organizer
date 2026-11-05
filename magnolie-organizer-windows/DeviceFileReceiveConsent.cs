using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaReceiveConsent(bool Granted, string Version, bool Explicit = false);

internal sealed partial class TelefonStore
{
    private string MediaReceiveConsentScope(NativeMediaPreferenceScope scope) => DeviceFileControl.Digest(
        "magnolie-media-local-receive-scope-v1\0", new JsonObject { ["peer_id"] = scope.PeerId,
            ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey });

    private NativeMediaReceiveConsent ReadMediaReceiveConsent(SqliteConnection db, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE name='native_media_receive_consent' AND type='table'";
        byte[]? encrypted = null;
        if (exists.ExecuteScalar() is not null)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_receive_consent WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", scope.PeerId); encrypted = read.ExecuteScalar() as byte[];
        }
        var scopeDigest = MediaReceiveConsentScope(scope);
        if (encrypted is null)
        {
            // Old explicit local native choices already authorized receiving.
            // New shared/remote intent never participates in this projection.
            var legacy = ReadNativeMediaPreferences(db, transaction, scope);
            var granted = legacy.PhotosEnabled || legacy.VideosEnabled;
            return new(granted, DeviceFileControl.Digest("magnolie-media-local-receive-default-v1\0",
                new JsonArray(scopeDigest, legacy.Version, JsonValue.Create(granted))));
        }
        if (encrypted.Length > 4096) throw DeviceFileControl.Error("media_receive_consent_invalid");
        var plain = Open("native_media_receive_consent", scope.PeerId, encrypted);
        try
        {
            var record = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "granted", "version");
            if (TelefonProtocolContract.Integer(record["format"]) != 1 || record["scope"]?.GetValue<string>() != scopeDigest ||
                record["granted"] is not JsonValue granted || !granted.TryGetValue<bool>(out var value) ||
                record["version"] is not JsonValue version || !version.TryGetValue<string>(out var stamp) || !DeviceFileControl.Hash(stamp))
                throw DeviceFileControl.Error("media_receive_consent_invalid");
            return new(value, stamp!, Explicit: true);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    internal NativeMediaReceiveConsent ReadNativeMediaReceiveConsent(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadMediaReceiveConsent(db, null, scope);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_receive_consent_scope_changed");
            return result;
        }
    }

    // Native local action only. Deliberately absent from paired-message codecs.
    internal NativeMediaReceiveConsent ChangeNativeMediaReceiveConsent(string peerId, string expectedVersion, bool granted)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var before = ReadMediaReceiveConsent(db, transaction, scope);
            if (!DeviceFileControl.Hash(expectedVersion) || before.Version != expectedVersion)
                throw DeviceFileControl.Error("media_receive_consent_stale_choice");
            if (before.Explicit && before.Granted == granted) return before;
            var next = new NativeMediaReceiveConsent(granted, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), Explicit: true);
            var plain = TelefonCrypto.Canonical(new JsonObject { ["format"] = 1, ["scope"] = MediaReceiveConsentScope(scope),
                ["granted"] = granted, ["version"] = next.Version });
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_receive_consent(peer_id TEXT PRIMARY KEY, value BLOB NOT NULL); " +
                "INSERT INTO native_media_receive_consent(peer_id,value) VALUES($peer,$value) ON CONFLICT(peer_id) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", peerId);
            try { write.Parameters.AddWithValue("$value", Seal("native_media_receive_consent", peerId, plain)); }
            finally { CryptographicOperations.ZeroMemory(plain); }
            write.ExecuteNonQuery();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_receive_consent_scope_changed");
            transaction.Commit();
            if (ReadMediaReceiveConsent(db, null, scope) != next || MediaPreferenceScope(peerId) != scope)
                throw DeviceFileControl.Error("media_receive_consent_commit_not_proven");
            return next;
        }
    }
}
