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
    // Inert, append-only native choices. This is NOT an active destination head
    // and must not be used to resolve a receive/source/restore permission.
    internal sealed record NativeMediaDestinationChoice(string OriginalVersion, ulong CreationFileTime, NativeMediaDestination Destination)
    {
        internal bool GrantsReceiveAuthority => false;
        internal bool GrantsSendAuthority => false;
    }
    private const int MediaDestinationChoiceLimit = 32;
    private static void MediaDestinationKind(string mediaType)
    {
        if (mediaType is not ("images" or "video")) throw DeviceFileControl.Error("file_destination_media_type_invalid");
    }

    internal NativeMediaDestination? ReadNativeMediaDestination(string peerId, string mediaType)
        => ReadOriginalLegacyDestination(peerId, mediaType); // No active-generation switch implemented yet.

    private NativeMediaDestination? ReadOriginalLegacyDestination(string peerId, string mediaType)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var connection = OpenNativeMediaDatabase(); connection.Open();
            var result = ReadLegacyNativeMediaDestination(connection, null, scope, mediaType);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_destination_scope_changed");
            return result;
        }
    }

    // Immutable original record, deliberately NOT the future current-selection
    // resolver and never an inert staged choice.
    private NativeMediaDestination? ReadLegacyNativeMediaDestination(SqliteConnection connection, SqliteTransaction? transaction,
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
            return ParseNativeMediaDestination(value, scope, mediaType);
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    private static NativeMediaDestination ParseNativeMediaDestination(JsonObject value, NativeMediaPreferenceScope scope, string mediaType)
    {
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

    private static JsonObject NativeMediaDestinationValue(NativeMediaPreferenceScope scope, NativeMediaDestination result) => new()
    {
        ["format"] = 1, ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
        ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey, ["media_type"] = result.MediaType,
        ["revision"] = result.Revision, ["version"] = result.Version, ["native_path"] = result.NativePath,
        ["volume_path"] = result.VolumePath, ["volume_serial"] = result.RootIdentity.VolumeSerial.ToString("x16", CultureInfo.InvariantCulture),
        ["file_id_low"] = result.RootIdentity.FileIdLow.ToString("x16", CultureInfo.InvariantCulture),
        ["file_id_high"] = result.RootIdentity.FileIdHigh.ToString("x16", CultureInfo.InvariantCulture), ["destination_token"] = result.DestinationToken
    };

    internal IReadOnlyList<NativeMediaDestinationChoice> ReadNativeMediaDestinationChoices(string peerId, string mediaType)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            RequireNativeMediaStorageKey();
            var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var original = ReadLegacyNativeMediaDestination(db, null, scope, mediaType); // Never create or replace it.
            var result = ReadNativeMediaDestinationChoices(db, null, scope, mediaType);
            if (original is null && result.Count != 0) throw DeviceFileControl.Error("file_destination_choice_original_required");
            RequireNativeMediaStorageKey();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_destination_scope_changed");
            return result;
        }
    }

    private IReadOnlyList<NativeMediaDestinationChoice> ReadNativeMediaDestinationChoices(SqliteConnection db, SqliteTransaction? transaction,
        NativeMediaPreferenceScope scope, string mediaType)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_destination_choices'";
        if (exists.ExecuteScalar() is null) return [];
        using var query = db.CreateCommand(); query.Transaction = transaction;
        query.CommandText = "SELECT version,value FROM native_media_destination_choices WHERE peer_id=$peer AND media_type=$kind ORDER BY version LIMIT 33";
        query.Parameters.AddWithValue("$peer", scope.PeerId); query.Parameters.AddWithValue("$kind", mediaType);
        using var rows = query.ExecuteReader(); var result = new List<NativeMediaDestinationChoice>();
        while (rows.Read())
        {
            if (result.Count >= MediaDestinationChoiceLimit) throw DeviceFileControl.Error("file_destination_choice_capacity");
            var version = rows.GetString(0); var encrypted = (byte[])rows[1];
            if (!DeviceFileControl.Hash(version) || encrypted.Length > MediaDestinationRecordLimit + 28)
                throw DeviceFileControl.Error("file_destination_choice_invalid");
            var plain = Open("native_media_destination_choices", scope.PeerId + "/" + mediaType + "/" + version, encrypted);
            try
            {
                var value = JsonNode.Parse(plain) as JsonObject ?? throw DeviceFileControl.Error("file_destination_choice_invalid");
                TelefonProtocolContract.ExactObject(value, "format", "original_version", "creation_file_time", "destination");
                var original = TelefonMessagingContract.String(value, "original_version"); var creation = TelefonMessagingContract.String(value, "creation_file_time");
                if (TelefonProtocolContract.Integer(value["format"]) != 1 || !DeviceFileControl.Hash(original) || creation.Length != 16 ||
                    creation.Any(c => !char.IsAsciiHexDigitLower(c)) || !ulong.TryParse(creation, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var generation) || generation == 0 ||
                    value["destination"] is not JsonObject destination)
                    throw DeviceFileControl.Error("file_destination_choice_invalid");
                var record = ParseNativeMediaDestination(destination, scope, mediaType);
                if (record.Version != version || record.Revision != 1 || record.Version == original)
                    throw DeviceFileControl.Error("file_destination_choice_invalid");
                if (result.Any(previous => previous.Destination.RootIdentity == record.RootIdentity ||
                    previous.Destination.NativePath.Equals(record.NativePath, StringComparison.OrdinalIgnoreCase)))
                    throw DeviceFileControl.Error("file_destination_choice_ambiguous");
                result.Add(new(original, generation, record));
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        return result.AsReadOnly();
    }

    // Staging persists metadata ONLY. No current destination selection, old
    // ciphertext, token, mapping, file or consent is changed. An active switch
    // stays blocked until the separate historical owners are implemented.
    internal NativeMediaDestinationChoice StageNativeMediaDestinationChoice(string peerId, string mediaType, string originalVersion,
        IReadOnlyList<NativeMediaDestinationChoice> expected, DeviceFileNativeDirectory owner, Action requireCurrent)
    {
        ArgumentNullException.ThrowIfNull(expected); ArgumentNullException.ThrowIfNull(requireCurrent); MediaDestinationKind(mediaType);
        lock (gate)
        {
            requireCurrent(); RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId); var identity = owner.CurrentReceiveIdentity();
            var generation = owner.CurrentReceiveCreationFileTime();
            NativeMediaBackupExclusions.RequireMediaDirectory(owner.NativePath, owner.VolumePath);
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
            var original = ReadLegacyNativeMediaDestination(db, transaction, scope, mediaType);
            if (original is null || original.Version != originalVersion) throw DeviceFileControl.Error("file_destination_stale_choice");
            var before = ReadNativeMediaDestinationChoices(db, transaction, scope, mediaType);
            if (!before.SequenceEqual(expected)) throw DeviceFileControl.Error("file_destination_choice_catalog_changed");
            void Current()
            {
                requireCurrent(); RequireNativeMediaStorageKey();
                if (MediaPreferenceScope(peerId) != scope || owner.CurrentReceiveIdentity() != identity || owner.CurrentReceiveCreationFileTime() != generation ||
                    ReadLegacyNativeMediaDestination(db, transaction, scope, mediaType) != original)
                    throw DeviceFileControl.Error("file_destination_choice_context_changed");
            }
            Current();
            var same = before.SingleOrDefault(choice => choice.Destination.RootIdentity == identity &&
                choice.Destination.NativePath.Equals(owner.NativePath, StringComparison.OrdinalIgnoreCase) &&
                choice.Destination.VolumePath.Equals(owner.VolumePath, StringComparison.OrdinalIgnoreCase));
            if (same is not null)
            {
                if (same.OriginalVersion != originalVersion || same.CreationFileTime != generation)
                    throw DeviceFileControl.Error("file_destination_choice_generation_changed");
                Current(); transaction.Commit(); return same;
            }
            if (before.Count >= MediaDestinationChoiceLimit) throw DeviceFileControl.Error("file_destination_choice_capacity");
            static bool Within(string child, string parent) => child.Equals(parent, StringComparison.OrdinalIgnoreCase) ||
                child.StartsWith(parent.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
            var other = ReadLegacyNativeMediaDestination(db, transaction, scope, mediaType == "images" ? "video" : "images");
            var preserved = before.Select(choice => choice.Destination).Append(original).Concat(other is null ? [] : new[] { other });
            if (preserved.Any(value => value.RootIdentity == identity || Within(value.VolumePath, owner.VolumePath) || Within(owner.VolumePath, value.VolumePath)))
                throw DeviceFileControl.Error("file_destination_choice_roots_overlap");
            var otherChoices = ReadNativeMediaDestinationChoices(db, transaction, scope, mediaType == "images" ? "video" : "images");
            if (otherChoices.Any(choice => choice.Destination.RootIdentity == identity || Within(choice.Destination.VolumePath, owner.VolumePath) || Within(owner.VolumePath, choice.Destination.VolumePath)))
                throw DeviceFileControl.Error("file_destination_choice_roots_overlap");
            var result = new NativeMediaDestinationChoice(originalVersion, generation, new(1,
                Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), mediaType, owner.NativePath, owner.VolumePath, identity,
                Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant()));
            var value = new JsonObject { ["format"] = 1, ["original_version"] = originalVersion,
                ["creation_file_time"] = generation.ToString("x16", CultureInfo.InvariantCulture), ["destination"] = NativeMediaDestinationValue(scope, result.Destination) };
            var plain = TelefonCrypto.Canonical(value); byte[] encrypted;
            try
            {
                if (plain.Length > MediaDestinationRecordLimit) throw DeviceFileControl.Error("file_destination_choice_capacity");
                encrypted = Seal("native_media_destination_choices", scope.PeerId + "/" + mediaType + "/" + result.Destination.Version, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            Current();
            using var write = db.CreateCommand(); write.Transaction = transaction;
            write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_destination_choices(peer_id TEXT NOT NULL,media_type TEXT NOT NULL,version TEXT NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,media_type,version)); " +
                "INSERT INTO native_media_destination_choices(peer_id,media_type,version,value) VALUES($peer,$kind,$version,$value)";
            write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$kind", mediaType);
            write.Parameters.AddWithValue("$version", result.Destination.Version); write.Parameters.AddWithValue("$value", encrypted); write.ExecuteNonQuery();
            var after = ReadNativeMediaDestinationChoices(db, transaction, scope, mediaType);
            if (after.Count != before.Count + 1 || !before.All(after.Contains) || !after.Contains(result))
                throw DeviceFileControl.Error("file_destination_choice_readback_failed");
            Current(); transaction.Commit(); return result;
        }
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
            var before = ReadLegacyNativeMediaDestination(connection, transaction, scope, mediaType);
            if (before?.Version != expectedVersion) throw DeviceFileControl.Error("file_destination_stale_choice");
            if (before is not null)
            {
                if (before.RootIdentity != root || before.NativePath != owner.NativePath || before.VolumePath != owner.VolumePath)
                    throw DeviceFileControl.Error("file_destination_existing_history_required");
                if (MediaPreferenceScope(peerId) != scope || owner.CurrentIdentity() != root)
                    throw DeviceFileControl.Error("file_destination_scope_changed");
                return before; // No token/version/ciphertext rotation for the same destination.
            }
            // Absence is not proof of a first choice. Authenticate existing
            // evidence only to DENY reconstruction; never infer an old root,
            // token, generation or data permission from history/staging.
            var histories = ReceiveHeads(connection, transaction, scope);
            if (histories.Any(head => TelefonMessagingContract.String(head.Body, "media_type") == mediaType) ||
                ReadNativeMediaDestinationChoices(connection, transaction, scope, mediaType).Count != 0)
                throw DeviceFileControl.Error("file_destination_original_record_required");
            var other = ReadLegacyNativeMediaDestination(connection, transaction, scope, mediaType == "images" ? "video" : "images");
            static bool Within(string child, string parent) => child.Equals(parent, StringComparison.OrdinalIgnoreCase) ||
                child.StartsWith(parent.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
            if (other is not null && (other.RootIdentity == root || Within(owner.VolumePath, other.VolumePath) || Within(other.VolumePath, owner.VolumePath)))
                throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            foreach (var head in histories)
            {
                var destination = head.Body["destination"]!.AsObject();
                var volumePath = TelefonMessagingContract.String(destination, "volume_path");
                if (NativeMediaReceiveJob.NativeAlbumIdentity(destination["identity"]!.AsObject()) == root ||
                    Within(owner.VolumePath, volumePath) || Within(volumePath, owner.VolumePath))
                    throw DeviceFileControl.Error("file_destination_media_roots_overlap");
            }
            var result = new NativeMediaDestination(1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), mediaType,
                owner.NativePath, owner.VolumePath, root, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant());
            var value = NativeMediaDestinationValue(scope, result);
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
            if (ReadLegacyNativeMediaDestination(connection, transaction, scope, mediaType) != result || owner.CurrentIdentity() != root || MediaPreferenceScope(peerId) != scope)
                throw DeviceFileControl.Error("file_destination_readback_failed");
            transaction.Commit(); return result;
        }
    }

    // This typed owner authenticates ONLY the exact completed job's original
    // destination metadata. Callers must separately retain their book, native
    // file handles, full byte checks and operation-specific data authority.
    // It cannot resolve a staged choice or infer a future admitted generation.
    private sealed class NativeCompletedDestinationOwner
    {
        private readonly TelefonStore store;
        private readonly NativeMediaPreferenceScope scope;
        private readonly string jobId, jobVersion, mediaType, jobFingerprint;
        private readonly long jobRevision;
        private bool revoked;
        internal NativeMediaDestination Destination { get; }
        internal bool GrantsMutationAuthority => false;
        internal bool GrantsReadAuthority => false;

        internal NativeCompletedDestinationOwner(TelefonStore store, NativeMediaPreferenceScope scope, ReceiveHead job)
        {
            this.store = store; this.scope = scope; jobId = job.JobId; jobVersion = job.Version;
            jobRevision = job.Revision; jobFingerprint = DeviceFileControl.Digest("magnolie-completed-destination-job-v1\0", job.Body);
            mediaType = TelefonMessagingContract.String(job.Body, "media_type"); MediaDestinationKind(mediaType);
            store.RequireNativeMediaStorageKey();
            using var db = store.OpenNativeMediaDatabase(); db.Open();
            Destination = store.ReadLegacyNativeMediaDestination(db, null, scope, mediaType)
                ?? throw DeviceFileControl.Error("media_completed_destination_original_required");
            Require();
        }

        internal void Require()
        {
            lock (store.gate)
            {
                try
                {
                    if (revoked || store.MediaPreferenceScope(scope.PeerId) != scope)
                        throw DeviceFileControl.Error("media_completed_destination_owner_changed");
                    store.RequireNativeMediaStorageKey();
                    using var db = store.OpenNativeMediaDatabase(); db.Open();
                    var job = store.ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == jobId && head.Version == jobVersion);
                    if (job is null || job.Revision != jobRevision || DeviceFileControl.Digest("magnolie-completed-destination-job-v1\0", job.Body) != jobFingerprint ||
                        !job.Body.ContainsKey("saved") || !job.Body.ContainsKey("source_end") ||
                        TelefonMessagingContract.String(job.Body, "media_type") != mediaType ||
                        TelefonMessagingContract.String(job.Body, "destination_version") != Destination.Version ||
                        job.Body["binding"] is not JsonObject binding || TelefonMessagingContract.String(binding, "destination_token") != Destination.DestinationToken ||
                        !JsonNode.DeepEquals(job.Body["destination"], new JsonObject {
                            ["native_path"] = Destination.NativePath, ["volume_path"] = Destination.VolumePath,
                            ["identity"] = NativeMediaReceiveJob.NativeIdentity(Destination.RootIdentity), ["token"] = Destination.DestinationToken }) ||
                        store.ReadLegacyNativeMediaDestination(db, null, scope, mediaType) != Destination)
                        throw DeviceFileControl.Error("media_completed_destination_original_required");
                    store.RequireNativeMediaStorageKey();
                    if (store.MediaPreferenceScope(scope.PeerId) != scope)
                        throw DeviceFileControl.Error("media_completed_destination_owner_changed");
                }
                catch { revoked = true; throw; }
            }
        }
    }
}
