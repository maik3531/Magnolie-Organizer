using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaSendConsent(bool Photos, bool Videos, string Version, bool Explicit = false);

internal sealed partial class TelefonStore
{
    private static string MediaSendConsentScope(NativeMediaPreferenceScope scope) => DeviceFileControl.Digest(
        "magnolie-media-local-send-scope-v1\0", new JsonObject { ["peer_id"] = scope.PeerId,
            ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey });

    private NativeMediaSendConsent ReadMediaSendConsent(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE name='native_media_send_consent' AND type='table'";
        byte[]? encrypted = null;
        if (exists.ExecuteScalar() is not null)
        {
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_send_consent WHERE peer_id=$peer";
            read.Parameters.AddWithValue("$peer", scope.PeerId);
            var stored = read.ExecuteScalar();
            if (stored is not null)
                encrypted = stored as byte[] ?? throw DeviceFileControl.Error("media_send_consent_invalid");
        }
        var digest = MediaSendConsentScope(scope);
        // No legacy RECEIVE selection, shared direction or peer message grants SEND.
        if (encrypted is null) return new(false, false, DeviceFileControl.Digest("magnolie-media-local-send-default-v1\0", JsonValue.Create(digest)!));
        if (encrypted.Length is < 29 or > 4096) throw DeviceFileControl.Error("media_send_consent_invalid");
        var plain = Open("native_media_send_consent", scope.PeerId, encrypted);
        try
        {
            var record = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "photos", "videos", "version");
            if (TelefonProtocolContract.Integer(record["format"]) != 1 || record["scope"]?.GetValue<string>() != digest ||
                record["photos"] is not JsonValue photos || !photos.TryGetValue<bool>(out var images) ||
                record["videos"] is not JsonValue videos || !videos.TryGetValue<bool>(out var clips) ||
                record["version"] is not JsonValue version || !version.TryGetValue<string>(out var stamp) || !DeviceFileControl.Hash(stamp))
                throw DeviceFileControl.Error("media_send_consent_invalid");
            return new(images, clips, stamp!, Explicit: true);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    internal NativeMediaSendConsent ReadNativeMediaSendConsent(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadMediaSendConsent(db, null, scope);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_send_consent_scope_changed");
            return result;
        }
    }

    // Explicit native local choice only, deliberately absent from wire codecs.
    // Persistence alone is not a source/book/control-session authority.
    internal NativeMediaSendConsent ChangeNativeMediaSendConsent(string peerId, string expectedVersion, bool photos, bool videos)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var before = ReadMediaSendConsent(db, transaction, scope);
            if (!DeviceFileControl.Hash(expectedVersion) || before.Version != expectedVersion)
                throw DeviceFileControl.Error("media_send_consent_stale_choice");
            if (before.Explicit && before.Photos == photos && before.Videos == videos) return before;
            var next = new NativeMediaSendConsent(photos, videos, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), Explicit: true);
            var plain = TelefonCrypto.Canonical(new JsonObject { ["format"] = 1, ["scope"] = MediaSendConsentScope(scope),
                ["photos"] = photos, ["videos"] = videos, ["version"] = next.Version });
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_send_consent(peer_id TEXT PRIMARY KEY, value BLOB NOT NULL); " +
                "INSERT INTO native_media_send_consent(peer_id,value) VALUES($peer,$value) ON CONFLICT(peer_id) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", peerId);
            try { write.Parameters.AddWithValue("$value", Seal("native_media_send_consent", peerId, plain)); }
            finally { CryptographicOperations.ZeroMemory(plain); }
            write.ExecuteNonQuery();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_send_consent_scope_changed");
            transaction.Commit();
            if (ReadMediaSendConsent(db, null, scope) != next || MediaPreferenceScope(peerId) != scope)
                throw DeviceFileControl.Error("media_send_consent_commit_not_proven");
            return next;
        }
    }
}
