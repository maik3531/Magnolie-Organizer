using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaTrashEntry(string Operation, string Version, string JobId, string FileId, string State, long ChangedMs)
{
    internal bool GrantsWriteAuthority => false;
    internal bool IsRemoteDeletionReceipt => false;
}

internal sealed partial class TelefonStore
{
    // Local native recovery, not a wire deletion handler or absence witness.
    // Originals stay on the SAME volume in their original held parent.
    // Restore and permanent removal are exclusive append-only lifecycle branches.
    private sealed record MediaTrashHead(NativeMediaTrashEntry Entry, JsonObject Body);

    private static int MediaTrashSequence(string state) => state switch {
        "prepared" => 1, "trashed" => 2, "restore_prepared" or "purge_prepared" => 3,
        "restored" or "purged" => 4, _ => throw DeviceFileControl.Error("media_trash_state_invalid") };
    private static string? MediaTrashPrevious(string state) => state switch {
        "prepared" => null, "trashed" => "prepared", "restore_prepared" or "purge_prepared" => "trashed",
        "restored" => "restore_prepared", "purged" => "purge_prepared", _ => throw DeviceFileControl.Error("media_trash_state_invalid") };

    private List<MediaTrashHead> ReadMediaTrash(SqliteConnection db, SqliteTransaction? transaction, NativeMediaPreferenceScope scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_trash_events'";
        if (exists.ExecuteScalar() is null) return [];
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT operation,sequence,value FROM native_media_trash_events WHERE peer_id=$peer ORDER BY operation,sequence";
        read.Parameters.AddWithValue("$peer", scope.PeerId);
        using var rows = read.ExecuteReader(); var heads = new Dictionary<string, MediaTrashHead>(StringComparer.Ordinal); var count = 0;
        while (rows.Read())
        {
            if (++count > 8192) throw DeviceFileControl.Error("media_trash_history_bound");
            var operation = rows.GetString(0); var sequence = rows.GetInt64(1); var cipher = (byte[])rows[2];
            if (operation.Length != 32 || operation.Any(c => !char.IsAsciiHexDigitLower(c)) || sequence is < 1 or > 4 || cipher.Length > 8192)
                throw DeviceFileControl.Error("media_trash_history_invalid");
            var plain = Open("native_media_trash_event", scope.PeerId + "/" + operation + "/" + sequence, cipher);
            try
            {
                var value = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key", "operation", "sequence", "version", "record");
                string Text(string key) => TelefonMessagingContract.String(value, key);
                if (TelefonProtocolContract.Integer(value["format"]) != 1 || Text("peer_id") != scope.PeerId || Text("peer_key") != scope.PeerKey ||
                    Text("pairing_epoch") != scope.PairingEpoch || Text("local_id") != scope.LocalId || Text("local_key") != scope.LocalKey ||
                    Text("operation") != operation || TelefonProtocolContract.Integer(value["sequence"]) != sequence || !DeviceFileControl.Hash(Text("version")))
                    throw DeviceFileControl.Error("media_trash_scope_changed");
                var body = TelefonProtocolContract.ExactObject(value["record"]!, "job_id", "job_version", "file_id", "state", "changed_ms", "previous_version");
                var jobId = TelefonMessagingContract.String(body, "job_id"); var fileId = TelefonMessagingContract.String(body, "file_id");
                var state = TelefonMessagingContract.String(body, "state"); var changed = TelefonProtocolContract.Integer(body["changed_ms"]);
                if (jobId.Length != 32 || jobId.Any(c => !char.IsAsciiHexDigitLower(c)) || fileId.Length != 32 || fileId.Any(c => !char.IsAsciiHexDigitLower(c)) ||
                    !DeviceFileControl.Hash(TelefonMessagingContract.String(body, "job_version")) || changed <= 0 || changed > DeviceFileControl.MaximumRevision ||
                    MediaTrashSequence(state) != sequence)
                    throw DeviceFileControl.Error("media_trash_history_invalid");
                heads.TryGetValue(operation, out var before);
                if (before?.Entry.State != MediaTrashPrevious(state) || (sequence == 1 ? before is not null || body["previous_version"] is not null : before is null ||
                    TelefonMessagingContract.String(body, "previous_version") != before.Entry.Version || changed < before.Entry.ChangedMs ||
                    jobId != before.Entry.JobId || fileId != before.Entry.FileId || !JsonNode.DeepEquals(body["job_version"], before.Body["job_version"])))
                    throw DeviceFileControl.Error("media_trash_original_history_required");
                if (state is "purge_prepared" or "purged" && changed != before!.Entry.ChangedMs)
                    throw DeviceFileControl.Error("media_trash_retention_origin_changed");
                heads[operation] = new(new(operation, Text("version"), jobId, fileId, state, changed), body);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        return heads.Values.ToList();
    }

    private MediaTrashHead AppendMediaTrash(NativeMediaPreferenceScope scope, string operation, string? expectedVersion, JsonObject body, Action current)
    {
        current(); using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var heads = ReadMediaTrash(db, transaction, scope); var before = heads.SingleOrDefault(head => head.Entry.Operation == operation);
        if (before?.Entry.Version != expectedVersion || MediaPreferenceScope(scope.PeerId) != scope)
            throw DeviceFileControl.Error("media_trash_history_cas_conflict");
        var state = TelefonMessagingContract.String(body, "state");
        var sequence = MediaTrashSequence(state);
        var expectedState = MediaTrashPrevious(state);
        // Reserve all four lifecycle events up front: a full catalog must never
        // consume the capacity needed to complete an existing restore.
        if (sequence == 1 && heads.Count >= 2048)
            throw DeviceFileControl.Error("media_trash_history_bound");
        if (before?.Entry.State != expectedState || (before is not null &&
            (before.Entry.JobId != TelefonMessagingContract.String(body, "job_id") || before.Entry.FileId != TelefonMessagingContract.String(body, "file_id") ||
             !JsonNode.DeepEquals(before.Body["job_version"], body["job_version"]))))
            throw DeviceFileControl.Error("media_trash_original_history_required");
        if (sequence == 1 && heads.Any(head => head.Entry.JobId == TelefonMessagingContract.String(body, "job_id") &&
            head.Entry.FileId == TelefonMessagingContract.String(body, "file_id") && head.Entry.State != "restored"))
            throw DeviceFileControl.Error("media_trash_original_operation_pending");
        var version = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        var value = new JsonObject { ["format"] = 1, ["peer_id"] = scope.PeerId, ["peer_key"] = scope.PeerKey, ["pairing_epoch"] = scope.PairingEpoch,
            ["local_id"] = scope.LocalId, ["local_key"] = scope.LocalKey, ["operation"] = operation, ["sequence"] = sequence, ["version"] = version, ["record"] = body.DeepClone() };
        var plain = TelefonCrypto.Canonical(value); byte[] cipher;
        try { cipher = Seal("native_media_trash_event", scope.PeerId + "/" + operation + "/" + sequence, plain); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        using var write = db.CreateCommand(); write.Transaction = transaction;
        write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_trash_events(peer_id TEXT NOT NULL,operation TEXT NOT NULL,sequence INTEGER NOT NULL,value BLOB NOT NULL,PRIMARY KEY(peer_id,operation,sequence)); " +
            "INSERT INTO native_media_trash_events(peer_id,operation,sequence,value) VALUES($peer,$operation,$sequence,$value)";
        write.Parameters.AddWithValue("$peer", scope.PeerId); write.Parameters.AddWithValue("$operation", operation);
        write.Parameters.AddWithValue("$sequence", sequence); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
        current(); transaction.Commit();
        var actual = ReadMediaTrash(db, null, scope).Single(head => head.Entry.Operation == operation);
        if (actual.Entry.Version != version || !JsonNode.DeepEquals(actual.Body, body)) throw DeviceFileControl.Error("media_trash_history_readback_failed");
        current(); return actual;
    }

    internal IReadOnlyList<NativeMediaTrashEntry> NativeMediaTrashHistory(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var result = ReadMediaTrash(db, null, scope).Select(head => head.Entry).ToArray();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_trash_scope_changed"); return result;
        }
    }

    // The callback is supplied by the native owner AFTER a successful book save
    // and actual explicit choice. It is never deserialized from a UI/wire bool.
    internal NativeMediaTrashEntry TrashNativeMediaSavedFile(string peerId, string jobId, string jobVersion, string fileId, Func<bool> nativePermit)
        => MoveNativeMediaTrash(peerId, jobId, jobVersion, fileId, null, nativePermit);

    internal NativeMediaTrashEntry RestoreNativeMediaTrash(string peerId, NativeMediaTrashEntry selected, Func<bool> nativePermit)
    {
        if (selected.State is not ("trashed" or "restore_prepared")) throw DeviceFileControl.Error("media_trash_original_operation_required");
        return MoveNativeMediaTrash(peerId, selected.JobId, null, selected.FileId, selected, nativePermit);
    }

    internal NativeMediaTrashEntry RecoverNativeMediaTrashOperation(string peerId, NativeMediaTrashEntry selected, Func<bool> nativePermit)
    {
        if (selected.State is not ("prepared" or "restore_prepared")) throw DeviceFileControl.Error("media_trash_original_operation_required");
        return MoveNativeMediaTrash(peerId, selected.JobId, null, selected.FileId, selected, nativePermit);
    }

    private NativeMediaTrashEntry MoveNativeMediaTrash(string peerId, string jobId, string? jobVersion, string fileId,
        NativeMediaTrashEntry? selected, Func<bool> nativePermit, string? replacementOperation = null)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId); var revoked = false;
            void Current()
            {
                try
                {
                    if (revoked || nativePermit() != true || MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_trash_native_permit_changed");
                    RequireNativeMediaStorageKey();
                }
                catch { revoked = true; throw; }
            }
            Current(); using var db = OpenNativeMediaDatabase(); db.Open(); var histories = ReadMediaTrash(db, null, scope);
            var original = selected is null ? null : histories.SingleOrDefault(head => head.Entry == selected);
            if (selected is not null && original is null) throw DeviceFileControl.Error("media_trash_stale_selection");
            if (replacementOperation is not null)
            {
                original = histories.SingleOrDefault(head => head.Entry.Operation == replacementOperation);
                if (original is not null && (original.Entry.JobId != jobId || original.Entry.FileId != fileId ||
                    TelefonMessagingContract.String(original.Body, "job_version") != jobVersion || original.Entry.State is not ("prepared" or "trashed")))
                    throw DeviceFileControl.Error("media_trash_replacement_operation_changed");
            }
            if (original is not null) jobVersion = TelefonMessagingContract.String(original.Body, "job_version");
            var job = ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == jobId && head.Version == jobVersion)
                ?? throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            if (!job.Body.ContainsKey("saved") || !job.Body.ContainsKey("source_end")) throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            var manifest = job.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().SingleOrDefault(file => TelefonMessagingContract.String(file, "id") == fileId)
                ?? throw DeviceFileControl.Error("media_trash_original_file_required");
            var member = job.Body["files"]!.AsArray().OfType<JsonObject>().Single(file => TelefonMessagingContract.String(file, "id") == fileId);
            var mediaType = TelefonMessagingContract.String(job.Body, "media_type");
            var destination = ReadNativeMediaDestination(peerId, mediaType) ?? throw DeviceFileControl.Error("media_trash_original_destination_required");
            if (destination.Version != TelefonMessagingContract.String(job.Body, "destination_version") ||
                destination.DestinationToken != TelefonMessagingContract.String(job.Body["binding"]!.AsObject(), "destination_token"))
                throw DeviceFileControl.Error("media_trash_original_destination_required");
            using var root = destination.OpenNative();
            using var album = job.Body["album_root"] is JsonObject albumRoot
                ? root.OpenOriginalChild(TelefonMessagingContract.String(albumRoot, "folder"), NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject())) : null;
            var parent = album ?? root;
            void Bound()
            {
                Current(); _ = root.CurrentIdentity(); _ = parent.CurrentIdentity();
                if (ReadNativeMediaDestination(peerId, mediaType) != destination) throw DeviceFileControl.Error("media_trash_original_destination_changed");
            }
            var operation = replacementOperation ?? selected?.Operation ?? Guid.NewGuid().ToString("N"); var trashName = ".magnolie-trash-" + operation;
            var leaf = DeviceFileNativeDirectory.ReceiveLeaf(TelefonMessagingContract.String(manifest, "path"));
            var size = TelefonProtocolContract.Integer(manifest["size"]); var hash = TelefonMessagingContract.String(manifest, "sha256");
            var identity = NativeMediaReceiveJob.NativeAlbumIdentity(member["identity"]!.AsObject());
            var restoring = selected is not null && selected.State != "prepared";
            Bound();
            if (replacementOperation is not null && original?.Entry.State == "trashed")
            {
                using var preserved = parent.OpenOriginalStagedFile(trashName, identity, size, hash); Bound();
                return original.Entry; // Revalidate the exact original, never replay an old deletion.
            }
            // OPEN_ONLY, actual original FID+size+full held-file hash. This
            // existing no-replace publication primitive also forbids WRITE and
            // DELETE sharing, so no path reopen race can substitute the source.
            var sourceName = restoring ? trashName : leaf; var targetName = restoring ? leaf : trashName;
            var alreadyMoved = (original?.Entry.State is "prepared" or "restore_prepared") && parent.ExistingFileIdentity(sourceName) is null;
            using var held = parent.OpenOriginalStagedFile(alreadyMoved ? targetName : sourceName, identity, size, hash);
            Bound();
            var nextState = restoring ? "restore_prepared" : "prepared";
            var body = new JsonObject { ["job_id"] = jobId, ["job_version"] = jobVersion, ["file_id"] = fileId,
                ["state"] = nextState, ["changed_ms"] = Math.Max(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), original?.Entry.ChangedMs ?? 0), ["previous_version"] = original?.Entry.Version };
            // An interrupted restore may retry only its original prepared move;
            // uncertain trash never gets reinterpreted as a new deletion.
            var prepared = original?.Entry.State is "prepared" or "restore_prepared" ? original : AppendMediaTrash(scope, operation, original?.Entry.Version, body, Bound);
            if (!alreadyMoved) held.Publish(parent, targetName, size, hash, Bound);
            var completed = prepared.Body.DeepClone().AsObject(); completed["state"] = restoring ? "restored" : "trashed";
            completed["previous_version"] = prepared.Entry.Version;
            completed["changed_ms"] = Math.Max(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), prepared.Entry.ChangedMs);
            return AppendMediaTrash(scope, operation, prepared.Entry.Version, completed, Bound).Entry;
        }
    }
}
