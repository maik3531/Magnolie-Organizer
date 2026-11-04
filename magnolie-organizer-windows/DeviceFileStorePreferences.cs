using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

// Saved intent only. A fresh receiver/data ACK and actual destination owner are
// still required; loading a positive choice never constructs a NativeLocalFileGrant.
internal sealed record NativeMediaPreferences(long Revision, string? Version,
    bool PhotosEnabled, bool VideosEnabled, bool AutomaticWifi,
    bool DeleteFromPhone = false, bool DeleteFromDesktop = false)
{
    internal bool GrantsReceiveAuthority => false;
    // Same single UI choice as Notes. A historical mixed native policy needs an
    // explicit choice; it must not be displayed as either unambiguous checkbox.
    internal bool? SkipDeletions => DeleteFromPhone == DeleteFromDesktop ? !DeleteFromPhone : null;
    internal PhotoSyncPlanPolicy ComparisonPolicy => new(phoneDeletionsToDesktop: DeleteFromDesktop,
        desktopDeletionsToPhone: DeleteFromPhone);
    internal const string Direction = "phone_inventory_only";
}

internal sealed partial class TelefonStore
{
    private SqliteConnection OpenNativeMediaDatabase() => new(new SqliteConnectionStringBuilder
    { DataSource = paths.TelefonDatabase, Mode = SqliteOpenMode.ReadWrite }.ToString());

    private sealed record NativeMediaPreferenceScope(string PeerId, string PeerKey, string PairingEpoch,
        string LocalId, string LocalKey);

    private NativeMediaPreferenceScope MediaPreferenceScope(string peerId)
    {
        if (RestoreFenced) throw DeviceFileControl.Error("file_preferences_restore_fenced");
        var identity = ReadFileIdentity();
        var current = LoadPeers().SingleOrDefault(value => value.Id == peerId);
        if (current is not { State: "paired" } || !DeviceFileControl.Hash(current.FilePairingEpoch))
            throw DeviceFileControl.Error("file_preferences_pairing_unavailable");
        return new(peerId, Convert.ToHexString(SHA256.HashData(current.PublicKey)).ToLowerInvariant(),
            current.FilePairingEpoch!, identity.DeviceId, identity.IdentitySha256);
    }

    // One "Löschungen auslassen" choice for both directions, like Notes. This
    // persists intent only; the unjoined native trash executor cannot be bypassed.
    internal NativeMediaPreferences SetNativeMediaSyncMode(string peerId, string? expectedVersion,
        bool automaticWifi, bool skipDeletions)
    {
        lock (gate)
        {
            var current = ReadNativeMediaPreferences(peerId);
            return SetNativeMediaPreferences(peerId, expectedVersion, current.PhotosEnabled, current.VideosEnabled,
                automaticWifi, deleteFromPhone: !skipDeletions, deleteFromDesktop: !skipDeletions);
        }
    }

    internal NativeMediaPreferences ReadNativeMediaPreferences(string peerId)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var connection = OpenNativeMediaDatabase(); connection.Open();
            var result = ReadNativeMediaPreferences(connection, null, scope);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_preferences_scope_changed");
            return result;
        }
    }

    private NativeMediaPreferences ReadNativeMediaPreferences(SqliteConnection connection, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope)
    {
        using var exists = connection.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_preferences'";
        if (exists.ExecuteScalar() is null) return new(0, null, false, false, false);
        using var read = connection.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT value FROM native_media_preferences WHERE peer_id=$peer";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        if (read.ExecuteScalar() is not byte[] encrypted) return new(0, null, false, false, false);
        if (encrypted.Length > 8192) throw DeviceFileControl.Error("file_preferences_invalid");
        var plain = Open("native_media_preferences", scope.PeerId, encrypted);
        try
        {
            var value = JsonNode.Parse(plain) as JsonObject ?? throw DeviceFileControl.Error("file_preferences_invalid");
            TelefonProtocolContract.ExactObject(value, "format", "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key",
                "revision", "version", "photos_enabled", "videos_enabled", "automatic_wifi", "direction", "delete_phone", "delete_desktop");
            string Text(string key) => value[key] is JsonValue item && item.TryGetValue<string>(out var text) && text is not null
                ? text : throw DeviceFileControl.Error("file_preferences_invalid");
            bool Flag(string key) => value[key] is JsonValue item && item.TryGetValue<bool>(out var flag)
                ? flag : throw DeviceFileControl.Error("file_preferences_invalid");
            var revision = TelefonProtocolContract.Integer(value["revision"]);
            var version = Text("version");
            if (TelefonProtocolContract.Integer(value["format"]) != 1 || revision is < 1 or > DeviceFileControl.MaximumRevision ||
                !DeviceFileControl.Hash(version) || Text("direction") != NativeMediaPreferences.Direction)
                throw DeviceFileControl.Error("file_preferences_invalid");
            if (Text("peer_id") != scope.PeerId || Text("peer_key") != scope.PeerKey || Text("pairing_epoch") != scope.PairingEpoch ||
                Text("local_id") != scope.LocalId || Text("local_key") != scope.LocalKey)
                throw DeviceFileControl.Error("file_preferences_reassociation_required");
            return new(revision, version, Flag("photos_enabled"), Flag("videos_enabled"), Flag("automatic_wifi"),
                Flag("delete_phone"), Flag("delete_desktop"));
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    // Native explicit choice only: no bridge registration, wire handler or startup
    // call. Compare-and-set prevents another window/process from losing a choice.
    internal NativeMediaPreferences SetNativeMediaPreferences(string peerId, string? expectedVersion,
        bool photosEnabled, bool videosEnabled, bool automaticWifi,
        bool? deleteFromPhone = null, bool? deleteFromDesktop = null)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var connection = OpenNativeMediaDatabase(); connection.Open();
            using var transaction = connection.BeginTransaction();
            var previous = ReadNativeMediaPreferences(connection, transaction, scope);
            if (previous.Version != expectedVersion) throw DeviceFileControl.Error("file_preferences_stale_choice");
            var phoneDeletion = deleteFromPhone ?? previous.DeleteFromPhone;
            var desktopDeletion = deleteFromDesktop ?? previous.DeleteFromDesktop;
            if (previous.PhotosEnabled == photosEnabled && previous.VideosEnabled == videosEnabled && previous.AutomaticWifi == automaticWifi &&
                previous.DeleteFromPhone == phoneDeletion && previous.DeleteFromDesktop == desktopDeletion)
            {
                if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_preferences_scope_changed");
                return previous;
            }
            if (previous.Revision >= DeviceFileControl.MaximumRevision) throw DeviceFileControl.Error("file_preferences_revision_exhausted");
            var next = new NativeMediaPreferences(previous.Revision + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(),
                photosEnabled, videosEnabled, automaticWifi, phoneDeletion, desktopDeletion);
            var value = new JsonObject { ["format"] = 1, ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey,
                ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey,
                ["revision"] = next.Revision, ["version"] = next.Version, ["photos_enabled"] = next.PhotosEnabled,
                ["videos_enabled"] = next.VideosEnabled, ["automatic_wifi"] = next.AutomaticWifi,
                ["direction"] = NativeMediaPreferences.Direction, ["delete_phone"] = next.DeleteFromPhone, ["delete_desktop"] = next.DeleteFromDesktop };
            using var write = connection.CreateCommand(); write.Transaction = transaction;
            // A dedicated table survives generic Notes/meta cleanup and profile
            // restore. Binding mismatches HOLD instead of resetting old intent.
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_preferences(peer_id TEXT PRIMARY KEY, value BLOB NOT NULL); " +
                "INSERT INTO native_media_preferences(peer_id,value) VALUES($peer,$value) ON CONFLICT(peer_id) DO UPDATE SET value=excluded.value";
            write.Parameters.AddWithValue("$peer", scope.PeerId);
            write.Parameters.AddWithValue("$value", Seal("native_media_preferences", scope.PeerId, TelefonCrypto.Canonical(value)));
            write.ExecuteNonQuery();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_preferences_scope_changed");
            transaction.Commit();
            return next;
        }
    }
}
