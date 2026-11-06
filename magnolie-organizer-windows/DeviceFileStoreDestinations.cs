using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaDestination(long Revision, string Version, string MediaType, string NativePath,
    string VolumePath, DeviceFileNativeDirectory.Identity RootIdentity, string DestinationToken)
{
    internal bool GrantsReceiveAuthority => false;

    internal DeviceFileNativeDirectory OpenNative()
    {
        var owner = DeviceFileNativeDirectory.OpenExistingForReceive(NativePath);
        try
        {
            if (owner.CurrentIdentity() != RootIdentity || !string.Equals(owner.VolumePath, VolumePath, StringComparison.OrdinalIgnoreCase))
                throw DeviceFileControl.Error("file_destination_original_root_required");
            return owner;
        }
        catch { owner.Dispose(); throw; }
    }
}

internal sealed partial class TelefonStore
{
    private const int MediaDestinationRecordLimit = 128 * 1024;
    private static void MediaDestinationKind(string mediaType)
    {
        if (mediaType is not ("images" or "video")) throw DeviceFileControl.Error("file_destination_media_type_invalid");
    }

    internal NativeMediaDestination? ReadNativeMediaDestination(string peerId, string mediaType)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var connection = OpenNativeMediaDatabase(); connection.Open();
            var result = ReadNativeMediaDestination(connection, null, scope, mediaType);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_destination_scope_changed");
            return result;
        }
    }

    private NativeMediaDestination? ReadNativeMediaDestination(SqliteConnection connection, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope, string mediaType)
    {
        using var exists = connection.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_destinations'";
        if (exists.ExecuteScalar() is null) return null;
        using var read = connection.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT value FROM native_media_destinations WHERE peer_id=$peer AND media_type=$kind";
        read.Parameters.AddWithValue("$peer", scope.PeerId); read.Parameters.AddWithValue("$kind", mediaType);
        if (read.ExecuteScalar() is not byte[] encrypted) return null;
        if (encrypted.Length > MediaDestinationRecordLimit + 28) throw DeviceFileControl.Error("file_destination_record_invalid");
        var plain = Open("native_media_destinations", scope.PeerId + "/" + mediaType, encrypted);
        try
        {
            var value = JsonNode.Parse(plain) as JsonObject ?? throw DeviceFileControl.Error("file_destination_record_invalid");
            TelefonProtocolContract.ExactObject(value, "format", "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key",
                "media_type", "revision", "version", "native_path", "volume_path", "volume_serial", "file_id_low", "file_id_high", "destination_token");
            string Text(string key) => value[key] is JsonValue item && item.TryGetValue<string>(out var text) && text is not null
                ? text : throw DeviceFileControl.Error("file_destination_record_invalid");
            ulong Hex(string key)
            {
                var text = Text(key);
                if (text.Length != 16 || text.Any(c => !char.IsAsciiHexDigitLower(c))) throw DeviceFileControl.Error("file_destination_record_invalid");
                return ulong.Parse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            }
            var revision = TelefonProtocolContract.Integer(value["revision"]); var version = Text("version"); var token = Text("destination_token");
            if (TelefonProtocolContract.Integer(value["format"]) != 1 || revision is < 1 or > DeviceFileControl.MaximumRevision ||
                !DeviceFileControl.Hash(version) || !DeviceFileControl.Hash(token) || Text("media_type") != mediaType)
                throw DeviceFileControl.Error("file_destination_record_invalid");
            if (Text("peer_id") != scope.PeerId || Text("peer_key") != scope.PeerKey || Text("pairing_epoch") != scope.PairingEpoch ||
                Text("local_id") != scope.LocalId || Text("local_key") != scope.LocalKey)
                throw DeviceFileControl.Error("file_destination_reassociation_required");
            var path = Text("native_path"); _ = DeviceFileNativeDirectory.NtDirectoryName(path);
            var volumePath = Text("volume_path");
            if (!volumePath.StartsWith(@"\\?\Volume{", StringComparison.Ordinal) || volumePath.Length > 16048 ||
                volumePath.Any(c => c < 32 || c == 127)) throw DeviceFileControl.Error("file_destination_record_invalid");
            NativeMediaBackupExclusions.RequireMediaDirectory(path, volumePath);
            var identity = new DeviceFileNativeDirectory.Identity(Hex("volume_serial"), Hex("file_id_low"), Hex("file_id_high"));
            if (identity.FileIdLow == 0 && identity.FileIdHigh == 0) throw DeviceFileControl.Error("file_destination_record_invalid");
            return new(revision, version, mediaType, path, volumePath, identity, token);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    // The caller supplies the actual picked/default native directory owner, not
    // a bridge-selected path/identity. This persists intent only, never receive.
    internal NativeMediaDestination SetNativeMediaDestination(string peerId, string mediaType, string? expectedVersion,
        DeviceFileNativeDirectory owner)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); var root = owner.CurrentReceiveIdentity();
            NativeMediaBackupExclusions.RequireMediaDirectory(owner.NativePath, owner.VolumePath);
            using var connection = OpenNativeMediaDatabase(); connection.Open(); using var transaction = connection.BeginTransaction();
            var before = ReadNativeMediaDestination(connection, transaction, scope, mediaType);
            if (before?.Version != expectedVersion) throw DeviceFileControl.Error("file_destination_stale_choice");
            if (before is not null)
            {
                if (before.RootIdentity != root || before.NativePath != owner.NativePath || before.VolumePath != owner.VolumePath)
                    throw DeviceFileControl.Error("file_destination_existing_history_required");
                if (MediaPreferenceScope(peerId) != scope || owner.CurrentIdentity() != root)
                    throw DeviceFileControl.Error("file_destination_scope_changed");
                return before; // No token/version/ciphertext rotation for the same destination.
            }
            var other = ReadNativeMediaDestination(connection, transaction, scope, mediaType == "images" ? "video" : "images");
            static bool Within(string child, string parent) => child.Equals(parent, StringComparison.OrdinalIgnoreCase) ||
                child.StartsWith(parent.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
            if (other is not null && (other.RootIdentity == root || Within(owner.VolumePath, other.VolumePath) || Within(other.VolumePath, owner.VolumePath)))
                throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            var result = new NativeMediaDestination(1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), mediaType,
                owner.NativePath, owner.VolumePath, root, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant());
            var value = new JsonObject { ["format"] = 1, ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey,
                ["pairing_epoch"] = scope.PairingEpoch, ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey,
                ["media_type"] = mediaType, ["revision"] = result.Revision, ["version"] = result.Version, ["native_path"] = result.NativePath,
                ["volume_path"] = result.VolumePath, ["volume_serial"] = root.VolumeSerial.ToString("x16", CultureInfo.InvariantCulture),
                ["file_id_low"] = root.FileIdLow.ToString("x16", CultureInfo.InvariantCulture), ["file_id_high"] = root.FileIdHigh.ToString("x16", CultureInfo.InvariantCulture),
                ["destination_token"] = result.DestinationToken };
            var plain = TelefonCrypto.Canonical(value);
            byte[] encrypted;
            try
            {
                if (plain.Length > MediaDestinationRecordLimit) throw DeviceFileControl.Error("file_destination_record_invalid");
                encrypted = Seal("native_media_destinations", scope.PeerId + "/" + mediaType, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            using var write = connection.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_destinations(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type)); " +
                "INSERT INTO native_media_destinations(peer_id,media_type,value) VALUES($peer,$kind,$value)";
            write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$kind", mediaType); write.Parameters.AddWithValue("$value", encrypted);
            write.ExecuteNonQuery();
            if (ReadNativeMediaDestination(connection, transaction, scope, mediaType) != result || owner.CurrentIdentity() != root || MediaPreferenceScope(peerId) != scope)
                throw DeviceFileControl.Error("file_destination_readback_failed");
            transaction.Commit(); return result;
        }
    }
}
