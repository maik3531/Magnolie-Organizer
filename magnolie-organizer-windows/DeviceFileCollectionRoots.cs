using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

// A selected source, not a destination or native/current SEND grant. IDs never
// originate in a phone mapping, filename, browser path or synthetic phone UID.
internal sealed record NativeMediaCollectionRoot(string Id, string Version, string MediaType, string NativePath,
    string VolumePath, DeviceFileNativeDirectory.Identity Identity, ulong? CreationFileTime)
{
    internal DeviceFileNativeDirectory OpenNative()
    {
        if (CreationFileTime is null) throw DeviceFileControl.Error("media_collection_root_generation_required");
        var root = DeviceFileNativeDirectory.OpenExisting(NativePath);
        try
        {
            if (root.CurrentCollectionSourceIdentity() != Identity || !string.Equals(root.VolumePath, VolumePath, StringComparison.OrdinalIgnoreCase))
                throw DeviceFileControl.Error("media_collection_original_root_required");
            if (root.CurrentCollectionCreationFileTime() != CreationFileTime) throw DeviceFileControl.Error("media_collection_root_generation_changed");
            NativeMediaBackupExclusions.RequireMediaDirectory(root); return root;
        }
        catch { root.Dispose(); throw; }
    }
}

internal sealed partial class TelefonStore
{
    private const int CollectionRootLimit = 64, CollectionRootRecordLimit = 131072;

    internal IReadOnlyList<NativeMediaCollectionRoot> NativeMediaCollectionRoots(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadCollectionRoots(db, null, scope);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_collection_scope_changed");
            return result.AsReadOnly();
        }
    }

    private List<NativeMediaCollectionRoot> ReadCollectionRoots(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='native_media_collection_roots'";
        if (Convert.ToInt32(read.ExecuteScalar()) == 0) return [];
        read.CommandText = "SELECT root_id,length(value),value FROM native_media_collection_roots WHERE peer_id=$peer ORDER BY root_id";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        using var rows = read.ExecuteReader(); var result = new List<NativeMediaCollectionRoot>();
        while (rows.Read())
        {
            var id = rows.GetString(0);
            if (result.Count >= CollectionRootLimit || !SourceId(id) || rows.GetInt64(1) is < 29 or > CollectionRootRecordLimit + 28)
                throw DeviceFileControl.Error("media_collection_root_record_invalid");
            var clear = Open("native_media_collection_root", scope.PeerId + "/" + id, (byte[])rows[2]);
            try
            {
                var raw = JsonNode.Parse(clear)!;
                var format = TelefonProtocolContract.Integer(raw["format"]);
                var fields = new[] { "format", "id", "version", "scope", "media_type", "native_path", "volume_path", "identity" };
                var value = TelefonProtocolContract.ExactObject(raw, format == 2 ? fields.Append("creation_filetime").ToArray() : fields);
                var identity = TelefonProtocolContract.ExactObject(value["identity"]!, "volume", "low", "high");
                var expectedScope = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
                    ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey };
                string Text(string key) => TelefonMessagingContract.String(value, key);
                static ulong ParseHex(string text)
                {
                    if (text.Length != 16 || text.Any(c => !char.IsAsciiHexDigitLower(c))) throw DeviceFileControl.Error("media_collection_root_record_invalid");
                    return ulong.Parse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                }
                ulong Hex(string key) => ParseHex(TelefonMessagingContract.String(identity, key));
                ulong? creation = format == 2 ? ParseHex(Text("creation_filetime")) : null;
                if (format is not (1 or 2) || creation == 0 || Text("id") != id || !DeviceFileControl.Hash(Text("version")) ||
                    !JsonNode.DeepEquals(value["scope"], expectedScope) || Text("media_type") is not ("images" or "video"))
                    throw DeviceFileControl.Error("media_collection_original_scope_required");
                var path = Text("native_path"); _ = DeviceFileNativeDirectory.NtDirectoryName(path);
                var volume = Text("volume_path");
                if (!volume.StartsWith(@"\\?\Volume{", StringComparison.Ordinal) || volume.Length > 16048 || volume.Any(c => c < 32 || c == 127))
                    throw DeviceFileControl.Error("media_collection_root_record_invalid");
                DeviceFileNativeDirectory.RequireCollectionDirectory(path, volume);
                var native = new DeviceFileNativeDirectory.Identity(Hex("volume"), Hex("low"), Hex("high"));
                if (native.FileIdLow == 0 && native.FileIdHigh == 0) throw DeviceFileControl.Error("media_collection_root_record_invalid");
                result.Add(new(id, Text("version"), Text("media_type"), path, volume, native, creation));
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }
        return result;
    }

    // Native picker owner only. Append, never replace a selected root/history.
    // A separate future explicit deactivation operation must preserve records.
    internal NativeMediaCollectionRoot AddNativeMediaCollectionRoot(string peerId, string mediaType,
        DeviceFileNativeDirectory selected, Action current)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            current(); RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            var identity = selected.CurrentCollectionSourceIdentity(); NativeMediaBackupExclusions.RequireMediaDirectory(selected);
            var creation = selected.CurrentCollectionCreationFileTime();
            void RequireCurrent()
            {
                current();
                if (selected.CurrentCollectionSourceIdentity() != identity || selected.CurrentCollectionCreationFileTime() != creation || MediaPreferenceScope(peerId) != scope)
                    throw DeviceFileControl.Error("media_collection_scope_or_generation_changed");
            }
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var previous = ReadCollectionRoots(db, transaction, scope);
            static bool Within(string child, string parent) => child.Equals(parent, StringComparison.OrdinalIgnoreCase) ||
                child.StartsWith(parent.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
            var same = previous.Where(item => item.MediaType == mediaType && item.Identity == identity && item.NativePath == selected.NativePath && item.VolumePath == selected.VolumePath).ToArray();
            if (same.Length > 1) throw DeviceFileControl.Error("media_collection_ambiguous_root");
            if (same.Length == 1)
            {
                RequireCurrent();
                if (same[0].CreationFileTime is null || same[0].CreationFileTime != creation)
                    throw DeviceFileControl.Error("media_collection_root_generation_required");
                return same[0];
            }
            if (previous.Count >= CollectionRootLimit || previous.Any(item => item.MediaType == mediaType &&
                (item.Identity == identity || Within(item.VolumePath, selected.VolumePath) || Within(selected.VolumePath, item.VolumePath))))
                throw DeviceFileControl.Error("media_collection_overlapping_or_replaced_root");
            var result = new NativeMediaCollectionRoot(Guid.NewGuid().ToString("N"), SourceDigest(RandomNumberGenerator.GetBytes(32)), mediaType,
                selected.NativePath, selected.VolumePath, identity, creation);
            var value = new JsonObject { ["format"] = 2, ["id"] = result.Id, ["version"] = result.Version, ["creation_filetime"] = creation.ToString("x16", CultureInfo.InvariantCulture),
                ["scope"] = new JsonObject { ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
                    ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey },
                ["media_type"] = mediaType, ["native_path"] = result.NativePath, ["volume_path"] = result.VolumePath,
                ["identity"] = NativeMediaReceiveJob.NativeIdentity(identity) };
            var clear = TelefonCrypto.Canonical(value); byte[] cipher;
            try
            {
                if (clear.Length > CollectionRootRecordLimit) throw DeviceFileControl.Error("media_collection_root_record_invalid");
                cipher = Seal("native_media_collection_root", scope.PeerId + "/" + result.Id, clear);
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_collection_roots(peer_id TEXT NOT NULL,root_id TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,root_id)); " +
                "INSERT INTO native_media_collection_roots(peer_id,root_id,value) VALUES($peer,$root,$value)";
            write.Parameters.AddWithValue("$peer", peerId); write.Parameters.AddWithValue("$root", result.Id); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
            if (ReadCollectionRoots(db, transaction, scope).SingleOrDefault(item => item.Id == result.Id) != result ||
                selected.CurrentCollectionSourceIdentity() != identity || selected.CurrentCollectionCreationFileTime() != creation || MediaPreferenceScope(peerId) != scope)
                throw DeviceFileControl.Error("media_collection_root_readback_failed");
            RequireCurrent(); transaction.Commit(); return result;
        }
    }
}
