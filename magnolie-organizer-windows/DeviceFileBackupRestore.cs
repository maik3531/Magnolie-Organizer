using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaBackupRestoration(string Operation, string State, string Name)
{
    internal bool IsRemoteSavedReceipt => false;
}

internal sealed record NativeMediaBackupRestoreChoice(string PeerId, NativeMediaDestination Destination, NativeMediaBackupVersion Selected, NativeMediaBookPermit Permit);

internal sealed partial class TelefonStore
{
    private sealed record BackupRestoreHead(string Operation, int Sequence, string Version, JsonObject Body);
    private List<BackupRestoreHead> BackupRestoreHeads(SqliteConnection db, SqliteTransaction? transaction, string scope)
    {
        using var exists = db.CreateCommand(); exists.Transaction = transaction;
        exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_backup_restore_events'";
        if (exists.ExecuteScalar() is null) return [];
        using var read = db.CreateCommand(); read.Transaction = transaction;
        read.CommandText = "SELECT operation,sequence,value FROM native_media_backup_restore_events WHERE scope=$scope ORDER BY operation,sequence";
        read.Parameters.AddWithValue("$scope", scope); using var rows = read.ExecuteReader(); var heads = new Dictionary<string, BackupRestoreHead>(); var count = 0;
        while (rows.Read())
        {
            if (++count > 8192) throw DeviceFileControl.Error("media_backup_restore_history_capacity");
            var operation = rows.GetString(0); var sequence = rows.GetInt32(1); var encrypted = (byte[])rows[2];
            if (operation.Length != 32 || operation.Any(c => !char.IsAsciiHexDigitLower(c)) || sequence is < 1 or > 2 || encrypted.Length > 16384)
                throw DeviceFileControl.Error("media_backup_restore_history_invalid");
            var plain = Open("native_media_backup_restore", scope + "/" + operation + "/" + sequence, encrypted);
            try
            {
                var record = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "operation", "sequence", "version", "record");
                var version = TelefonMessagingContract.String(record, "version");
                if (TelefonProtocolContract.Integer(record["format"]) != 1 || TelefonMessagingContract.String(record, "scope") != scope ||
                    TelefonMessagingContract.String(record, "operation") != operation || TelefonProtocolContract.Integer(record["sequence"]) != sequence || !DeviceFileControl.Hash(version))
                    throw DeviceFileControl.Error("media_backup_restore_history_invalid");
                var body = TelefonProtocolContract.ExactObject(record["record"]!, "reference", "reference_sha256", "name", "stage", "identity", "size", "sha256", "state", "previous_version");
                string Text(string key) => TelefonMessagingContract.String(body, key);
                if (!DeviceFileControl.Hash(Text("reference")) || !DeviceFileControl.Hash(Text("reference_sha256")) || !DeviceFileControl.Hash(Text("sha256")) ||
                    TelefonProtocolContract.Integer(body["size"]) is < 0 or > DeviceFileManifest.MaxFileBytes || Text("stage") != ".magnolie-restore-" + operation + ".part" ||
                    Text("state") != (sequence == 1 ? "prepared" : "restored")) throw DeviceFileControl.Error("media_backup_restore_history_invalid");
                _ = DeviceFileNativeDirectory.ReceiveLeaf(Text("name")); _ = NativeMediaReceiveJob.NativeAlbumIdentity(body["identity"]!.AsObject());
                heads.TryGetValue(operation, out var previous);
                if (sequence == 1 ? previous is not null || body["previous_version"] is not null : previous is null || previous.Sequence != 1 ||
                    Text("previous_version") != previous.Version || new[] { "reference", "reference_sha256", "name", "stage", "identity", "size", "sha256" }
                        .Any(key => !JsonNode.DeepEquals(body[key], previous.Body[key]))) throw DeviceFileControl.Error("media_backup_restore_history_changed");
                heads[operation] = new(operation, sequence, version, body);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }
        return heads.Values.ToList();
    }

    private BackupRestoreHead AppendBackupRestore(string scope, string operation, string? expectedVersion, JsonObject body, Action current)
    {
        current(); using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
        var heads = BackupRestoreHeads(db, transaction, scope); var before = heads.SingleOrDefault(item => item.Operation == operation);
        if (before?.Version != expectedVersion || before?.Sequence == 2 || before is null && heads.Count >= 4096)
            throw DeviceFileControl.Error("media_backup_restore_history_conflict");
        var sequence = before is null ? 1 : 2; var version = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        var record = new JsonObject { ["format"] = 1, ["scope"] = scope, ["operation"] = operation, ["sequence"] = sequence,
            ["version"] = version, ["record"] = body.DeepClone() };
        var plain = TelefonCrypto.Canonical(record); byte[] cipher;
        try { cipher = Seal("native_media_backup_restore", scope + "/" + operation + "/" + sequence, plain); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        using var write = db.CreateCommand(); write.Transaction = transaction;
        write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_backup_restore_events(scope TEXT NOT NULL,operation TEXT NOT NULL,sequence INTEGER NOT NULL,value BLOB NOT NULL,PRIMARY KEY(scope,operation,sequence)); " +
            "INSERT INTO native_media_backup_restore_events VALUES($scope,$operation,$sequence,$value)";
        write.Parameters.AddWithValue("$scope", scope); write.Parameters.AddWithValue("$operation", operation); write.Parameters.AddWithValue("$sequence", sequence); write.Parameters.AddWithValue("$value", cipher);
        write.ExecuteNonQuery(); current(); transaction.Commit();
        var actual = BackupRestoreHeads(db, null, scope).Single(item => item.Operation == operation);
        if (actual.Version != version || !JsonNode.DeepEquals(actual.Body, body)) throw DeviceFileControl.Error("media_backup_restore_commit_not_proven");
        current(); return actual;
    }

    internal NativeMediaBackupRestoration RestoreNativeMediaBackupToDestination(NativeMediaDestination destination, NativeMediaBackupVersion selected, Func<bool> nativePermit)
    {
        lock (gate)
        {
            var revoked = false;
            void Current()
            {
                try
                {
                    if (revoked || RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed");
                    RequireNativeMediaStorageKey();
                }
                catch { revoked = true; throw; }
            }
            Current(); using var root = destination.OpenNative();
            NativeMediaBackupExclusions.RequireMediaDirectory(root);
            using var catalog = new MediaBackupCatalog(this, destination, Current, false);
            var source = catalog.VerifySelected(selected);
            var scope = DeviceFileControl.Digest("magnolie-native-media-backup-restore-root-v1\0", new JsonObject
                { ["identity"] = NativeMediaReceiveJob.NativeIdentity(root.OriginalIdentity), ["volume_path"] = root.VolumePath });
            using var db = OpenNativeMediaDatabase(); db.Open();
            var pending = BackupRestoreHeads(db, null, scope).Where(item => item.Sequence == 1 && TelefonMessagingContract.String(item.Body, "reference") == selected.Id).ToArray();
            if (pending.Length > 1) throw DeviceFileControl.Error("media_backup_restore_history_conflict");
            var original = pending.SingleOrDefault();
            if (original is null)
            {
                var operation = Guid.NewGuid().ToString("N"); var stage = ".magnolie-restore-" + operation + ".part";
                var leaf = selected.Name.Split('/').Last(); _ = DeviceFileNativeDirectory.ReceiveLeaf(leaf);
                var stem = Path.GetFileNameWithoutExtension(leaf); var extension = Path.GetExtension(leaf);
                // Keep the original extension without splitting a surrogate or
                // combining sequence when bounding the human-readable prefix.
                var starts = System.Globalization.StringInfo.ParseCombiningCharacters(stem);
                if (starts.Length > 48) stem = stem[..starts[48]];
                var name = DeviceFileNativeDirectory.ReceiveLeaf(stem + " - restored " + operation + extension);
                using var created = root.CreateStagedFile(stage);
                var body = new JsonObject { ["reference"] = selected.Id, ["reference_sha256"] = selected.RecordSha256,
                    ["name"] = name, ["stage"] = stage, ["identity"] = NativeMediaReceiveJob.NativeIdentity(created.Observe().Identity),
                    ["size"] = source.Size, ["sha256"] = source.Sha256, ["state"] = "prepared", ["previous_version"] = null };
                original = AppendBackupRestore(scope, operation, null, body, Current); // Before first payload write.
            }
            string Text(string key) => TelefonMessagingContract.String(original.Body, key);
            if (Text("reference_sha256") != selected.RecordSha256 || TelefonProtocolContract.Integer(original.Body["size"]) != source.Size || Text("sha256") != source.Sha256)
                throw DeviceFileControl.Error("media_backup_restore_original_selection_required");
            var identity = NativeMediaReceiveJob.NativeAlbumIdentity(original.Body["identity"]!.AsObject());
            var stageIdentity = root.ExistingFileIdentity(Text("stage"));
            var published = stageIdentity is null;
            var path = published ? Text("name") : Text("stage");
            if (stageIdentity is not null && stageIdentity != identity || published && root.ExistingFileIdentity(path) != identity)
                throw DeviceFileControl.Error("media_backup_restore_original_candidate_required");
            var observed = root.ObserveManagedFile(path, Current) ?? throw DeviceFileControl.Error("media_backup_restore_original_candidate_required");
            if (observed.Identity != identity || observed.Size > source.Size || published && (observed.Size != source.Size || observed.Sha256 != source.Sha256))
                throw DeviceFileControl.Error("media_backup_restore_original_candidate_changed");
            using var held = root.OpenOriginalStagedFile(path, identity, observed.Size, observed.Sha256);
            var restored = catalog.RestoreOwnedCandidate(selected, held); Current();
            if (!published) held.Publish(root, Text("name"), restored.Size, restored.Sha256, Current);
            var completed = original.Body.DeepClone().AsObject(); completed["state"] = "restored"; completed["previous_version"] = original.Version;
            var result = AppendBackupRestore(scope, original.Operation, original.Version, completed, Current);
            return new(result.Operation, "restored", Text("name")); // Not a phone write/Saved or deletion receipt.
        }
    }
}

internal sealed partial class TelefonCoordinator
{
    internal IReadOnlyList<NativeMediaBackupVersion> ReadNativeMediaBackupUi(string peerId, string kind)
    {
        var permit = NativeMediaLocalBookPermit();
        var destination = store.ReadNativeMediaDestination(peerId, kind);
        if (destination is null) return [];
        bool Current() { permit.Require(); return store.ReadNativeMediaDestination(peerId, kind) == destination; }
        try { return store.NativeMediaBackupVersions(destination, Current); }
        catch (InvalidDataException error) when (error.Message == "media_backup_original_catalog_required") { return []; }
    }
    internal NativeMediaBackupRestoreChoice PrepareNativeMediaBackupRestore(string peerId, string kind, string id, string revision)
    {
        var permit = NativeMediaLocalBookPermit();
        var destination = store.ReadNativeMediaDestination(peerId, kind) ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
        bool Current() { permit.Require(); return store.ReadNativeMediaDestination(peerId, kind) == destination; }
        var selected = store.NativeMediaBackupVersions(destination, Current).SingleOrDefault(item => item.Id == id && item.RecordSha256 == revision)
            ?? throw DeviceFileControl.Error("media_backup_stale_selection");
        permit.Require(); return new(peerId, destination, selected, permit);
    }
    internal NativeMediaBackupRestoration RestoreConfirmedNativeMediaBackup(NativeMediaBackupRestoreChoice choice)
        => NativeMediaLocalOperation(() => store.RestoreNativeMediaBackupToDestination(choice.Destination, choice.Selected,
            () => { choice.Permit.Require(); return store.ReadNativeMediaDestination(choice.PeerId, choice.Destination.MediaType) == choice.Destination; }));
}
