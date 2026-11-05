using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaBackupVersion(string Id, string ObjectKey, long SavedMs, string Name, string RecordSha256)
{
    internal bool GrantsMutationAuthority => false;
}

internal sealed partial class TelefonStore
{
    // Payload AND authenticated catalog snapshots live in the destination's
    // Backup folder. The existing protected local DB holds only the exact latest
    // snapshot/folder witness: no foreign folder or old snapshot can bootstrap it.
    private sealed class MediaBackupCatalog : IDisposable
    {
        private const int MaxRecords = 4096, MaxSnapshotBytes = 2 * 1024 * 1024;
        private readonly TelefonStore store;
        private readonly Action native;
        private readonly DeviceFileNativeDirectory root, folder;
        private readonly string scope;
        private JsonObject anchor, state;
        private bool revoked;
        private static string Text(JsonObject value, string key) => TelefonMessagingContract.String(value, key);
        private static long Number(JsonObject value, string key) => TelefonProtocolContract.Integer(value[key]);
        private static JsonObject Identity(DeviceFileNativeDirectory.Identity value) => NativeMediaReceiveJob.NativeIdentity(value);
        private static DeviceFileNativeDirectory.Identity Identity(JsonNode value) => NativeMediaReceiveJob.NativeAlbumIdentity(value.AsObject());

        internal MediaBackupCatalog(TelefonStore store, NativeMediaDestination destination, Action native, bool create)
        {
            this.store = store; this.native = native;
            native(); store.RequireNativeMediaStorageKey();
            root = destination.OpenNative();
            scope = DeviceFileControl.Digest("magnolie-native-media-backup-root-v1\0", new JsonObject
            { ["volume_path"] = root.VolumePath, ["identity"] = Identity(root.OriginalIdentity) });
            try
            {
                var original = ReadAnchor();
                if (original is null)
                {
                    if (!create) throw DeviceFileControl.Error("media_backup_original_catalog_required");
                    // CREATE_ONLY refuses even an empty existing foreign Backup.
                    native(); folder = root.CreateChild("Backup");
                    state = new JsonObject { ["format"] = 1, ["scope"] = scope, ["revision"] = 0,
                        ["folder"] = Identity(folder.OriginalIdentity), ["objects"] = new JsonArray(), ["versions"] = new JsonArray() };
                    anchor = new JsonObject();
                    Commit(state.DeepClone().AsObject(), initial: true);
                }
                else
                {
                    anchor = original;
                    folder = root.OpenOriginalChild("Backup", Identity(anchor["folder"]!));
                    state = ReadSnapshot();
                }
                Current(); Validate(state);
            }
            catch { folder?.Dispose(); root.Dispose(); throw; }
        }

        private JsonObject? ReadAnchor(SqliteConnection? connection = null, SqliteTransaction? transaction = null)
        {
            using var owned = connection is null ? store.OpenNativeMediaDatabase() : null;
            var db = connection ?? owned!; if (connection is null) db.Open();
            using var exists = db.CreateCommand(); exists.Transaction = transaction;
            exists.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_backup_anchors'";
            if (exists.ExecuteScalar() is null) return null;
            using var read = db.CreateCommand(); read.Transaction = transaction;
            read.CommandText = "SELECT value FROM native_media_backup_anchors WHERE scope=$scope"; read.Parameters.AddWithValue("$scope", scope);
            if (read.ExecuteScalar() is not byte[] encrypted) return null;
            if (encrypted.Length > 8192) throw DeviceFileControl.Error("media_backup_anchor_invalid");
            var plain = store.Open("native_media_backup_anchor", scope, encrypted);
            try
            {
                var value = TelefonProtocolContract.ExactObject(JsonNode.Parse(plain)!, "format", "scope", "revision", "folder", "name", "identity", "size", "sha256");
                if (Number(value, "format") != 1 || Text(value, "scope") != scope || Number(value, "revision") is < 1 or > 8192 ||
                    Number(value, "size") is < 28 or > MaxSnapshotBytes || !DeviceFileControl.Hash(Text(value, "sha256")))
                    throw DeviceFileControl.Error("media_backup_anchor_invalid");
                _ = Identity(value["folder"]!); _ = Identity(value["identity"]!);
                _ = DeviceFileNativeDirectory.ReceiveLeaf(Text(value, "name"));
                if (!Text(value, "name").StartsWith("catalog-", StringComparison.Ordinal) || !Text(value, "name").EndsWith(".seal", StringComparison.Ordinal))
                    throw DeviceFileControl.Error("media_backup_anchor_invalid");
                return value;
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
        }

        private void Current()
        {
            try
            {
                if (revoked) throw DeviceFileControl.Error("media_backup_native_owner_revoked");
                native(); store.RequireNativeMediaStorageKey();
                _ = root.CurrentIdentity(); _ = folder.CurrentIdentity();
            }
            catch { revoked = true; throw; }
        }

        private JsonObject ReadSnapshot()
        {
            Current();
            using var held = folder.OpenOriginalStagedFile(Text(anchor, "name"), Identity(anchor["identity"]!), Number(anchor, "size"), Text(anchor, "sha256"));
            var size = checked((int)Number(anchor, "size")); var bytes = new byte[size];
            try
            {
                for (var at = 0; at < size;)
                {
                    Current(); var chunk = held.ReadExact(at, Math.Min(DeviceFileManifest.ChunkBytes, size - at));
                    try { chunk.CopyTo(bytes, at); at += chunk.Length; }
                    finally { CryptographicOperations.ZeroMemory(chunk); }
                }
                var plain = store.Open("native_media_backup_catalog", scope, bytes);
                try
                {
                    var result = JsonNode.Parse(plain)!.AsObject(); Validate(result);
                    if (Number(result, "revision") != Number(anchor, "revision") || !JsonNode.DeepEquals(result["folder"], anchor["folder"]))
                        throw DeviceFileControl.Error("media_backup_snapshot_changed");
                    Current(); return result;
                }
                finally { CryptographicOperations.ZeroMemory(plain); }
            }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }

        private void Validate(JsonObject value)
        {
            TelefonProtocolContract.ExactObject(value, "format", "scope", "revision", "folder", "objects", "versions");
            if (Number(value, "format") != 1 || Text(value, "scope") != scope || Number(value, "revision") is < 0 or > 8192 ||
                Identity(value["folder"]!) != folder.OriginalIdentity || value["objects"] is not JsonArray objects || objects.Count > MaxRecords ||
                value["versions"] is not JsonArray versions || versions.Count > MaxRecords) throw DeviceFileControl.Error("media_backup_catalog_invalid");
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in objects)
            {
                var obj = TelefonProtocolContract.ExactObject(item!, "id", "name", "identity", "size", "sha256", "complete");
                if (!ids.Add(Text(obj, "id")) || Text(obj, "id") != NativeMediaBackupPolicy.ContentKey(Number(obj, "size"), Text(obj, "sha256")) ||
                    Text(obj, "name") != "object-" + Text(obj, "id") + ".raw" || obj["complete"] is not JsonValue ready || !ready.TryGetValue<bool>(out _))
                    throw DeviceFileControl.Error("media_backup_object_invalid");
                if (Identity(obj["identity"]!).VolumeSerial != folder.OriginalIdentity.VolumeSerial) throw DeviceFileControl.Error("media_backup_object_invalid");
            }
            var refs = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in versions)
            {
                var version = TelefonProtocolContract.ExactObject(item!, "id", "object_key", "saved_ms", "name", "provenance");
                if (!DeviceFileControl.Hash(Text(version, "id")) || !refs.Add(Text(version, "id")) || Number(version, "saved_ms") is < 1 or > NativeMediaBackupPolicy.MaximumTimestampMs ||
                    Text(version, "name").Length is < 1 or > 4096 || version["provenance"] is not JsonObject provenance ||
                    Text(version, "id") != DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", provenance))
                    throw DeviceFileControl.Error("media_backup_version_invalid");
                var obj = objects.OfType<JsonObject>().SingleOrDefault(obj => Text(obj, "id") == Text(version, "object_key"));
                if (obj is null || obj["complete"]!.GetValue<bool>() != true) throw DeviceFileControl.Error("media_backup_version_object_required");
            }
        }

        private void Commit(JsonObject next, bool initial = false)
        {
            Current(); Validate(next);
            if (Number(next, "revision") >= 8192) throw DeviceFileControl.Error("media_backup_catalog_capacity");
            next["revision"] = Number(next, "revision") + 1;
            var plain = TelefonCrypto.Canonical(next); byte[] encrypted;
            try
            {
                if (plain.Length > MaxSnapshotBytes - 28) throw DeviceFileControl.Error("media_backup_catalog_capacity");
                encrypted = store.Seal("native_media_backup_catalog", scope, plain);
            }
            finally { CryptographicOperations.ZeroMemory(plain); }
            var name = "catalog-" + Guid.NewGuid().ToString("N") + ".seal";
            using var held = folder.CreateStagedFile(name);
            try
            {
                for (var at = 0; at < encrypted.Length;)
                {
                    Current(); var count = Math.Min(DeviceFileManifest.ChunkBytes, encrypted.Length - at);
                    held.WriteChunk(at, encrypted.AsSpan(at, count)); at += count;
                }
                var checkpoint = held.DurableCheckpoint();
                var verified = NativeMediaBackupBytes.Verify(held, checkpoint.Size, checkpoint.Sha256, Current);
                var after = new JsonObject { ["format"] = 1, ["scope"] = scope, ["revision"] = next["revision"]!.DeepClone(),
                    ["folder"] = Identity(folder.OriginalIdentity), ["name"] = name, ["identity"] = Identity(verified.Identity),
                    ["size"] = verified.Size, ["sha256"] = verified.Sha256 };
                using var db = store.OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction();
                var before = ReadAnchor(db, transaction);
                if (initial ? before is not null : !JsonNode.DeepEquals(before, anchor)) throw DeviceFileControl.Error("media_backup_catalog_cas_conflict");
                var encoded = TelefonCrypto.Canonical(after); byte[] cipher;
                try { cipher = store.Seal("native_media_backup_anchor", scope, encoded); }
                finally { CryptographicOperations.ZeroMemory(encoded); }
                using var write = db.CreateCommand(); write.Transaction = transaction;
                write.CommandText = "CREATE TABLE IF NOT EXISTS native_media_backup_anchors(scope TEXT PRIMARY KEY NOT NULL,value BLOB NOT NULL); " +
                    "INSERT OR REPLACE INTO native_media_backup_anchors(scope,value) VALUES($scope,$value)";
                write.Parameters.AddWithValue("$scope", scope); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
                Current(); transaction.Commit();
                if (!JsonNode.DeepEquals(ReadAnchor(), after)) throw DeviceFileControl.Error("media_backup_commit_not_proven");
                anchor = after; state = next; // Old snapshots remain immutable; no data retirement here.
                held.Dispose(); // Release exclusive WRITE sharing before exact-FID reopen.
                if (!JsonNode.DeepEquals(ReadSnapshot(), state)) throw DeviceFileControl.Error("media_backup_commit_not_proven");
            }
            catch { revoked = true; throw; }
            finally { CryptographicOperations.ZeroMemory(encrypted); }
        }

        private static NativeMediaBackupVersion Version(JsonObject value) => new(Text(value, "id"), Text(value, "object_key"), Number(value, "saved_ms"),
            Text(value, "name"), DeviceFileControl.Digest("magnolie-native-media-backup-reference-v1\0", value));
        internal IReadOnlyList<NativeMediaBackupVersion> Versions()
        {
            Current(); return state["versions"]!.AsArray().OfType<JsonObject>().Select(Version).ToArray();
        }

        private DeviceFileNativeDirectory.DeviceFileNativeStagedFile OpenObject(JsonObject obj, bool prepared = false)
        {
            Current(); var name = Text(obj, "name"); var expected = Identity(obj["identity"]!);
            if (!prepared) return folder.OpenOriginalStagedFile(name, expected, Number(obj, "size"), Text(obj, "sha256"));
            // Observe only this registered inode; content is compared to the
            // original source prefix before any resume write (never truncate).
            var observed = folder.ObserveManagedFile(name, Current) ?? throw DeviceFileControl.Error("media_backup_original_candidate_required");
            if (observed.Identity != expected || observed.Size > Number(obj, "size")) throw DeviceFileControl.Error("media_backup_original_candidate_changed");
            return folder.OpenOriginalStagedFile(name, expected, observed.Size, observed.Sha256);
        }

        internal NativeMediaBackupVersion Save(DeviceFileNativeDirectory.DeviceFileNativeStagedFile source,
            long size, string hash, string name, JsonObject provenance)
        {
            Current(); _ = NativeMediaBackupBytes.Verify(source, size, hash, Current);
            var id = DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", provenance);
            var key = NativeMediaBackupPolicy.ContentKey(size, hash);
            var original = state["versions"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item => Text(item, "id") == id);
            var obj = state["objects"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item => Text(item, "id") == key);
            if (original is not null)
            {
                if (Text(original, "object_key") != key || Text(original, "name") != name || !JsonNode.DeepEquals(original["provenance"], provenance) || obj is null)
                    throw DeviceFileControl.Error("media_backup_original_version_changed");
                using var existing = OpenObject(obj); _ = NativeMediaBackupBytes.Verify(existing, size, hash, Current);
                return Version(original); // No second copy and no retention-origin renewal.
            }
            if (state["versions"]!.AsArray().Count >= MaxRecords) throw DeviceFileControl.Error("media_backup_catalog_capacity");
            if (obj is null)
            {
                if (state["objects"]!.AsArray().Count >= MaxRecords) throw DeviceFileControl.Error("media_backup_catalog_capacity");
                var objectName = "object-" + key + ".raw";
                using var created = folder.CreateStagedFile(objectName);
                obj = new JsonObject { ["id"] = key, ["name"] = objectName, ["identity"] = Identity(created.Observe().Identity),
                    ["size"] = size, ["sha256"] = hash, ["complete"] = false };
                var pending = state.DeepClone().AsObject(); pending["objects"]!.AsArray().Add(obj.DeepClone());
                Commit(pending); // Register FID durably BEFORE first payload write.
            }
            using (var held = OpenObject(obj, prepared: !obj["complete"]!.GetValue<bool>()))
            {
                if (obj["complete"]!.GetValue<bool>()) _ = NativeMediaBackupBytes.Verify(held, size, hash, Current);
                else _ = NativeMediaBackupBytes.ResumeOwnedCandidate(source, held, size, hash, Current);
            }
            var next = state.DeepClone().AsObject();
            next["objects"]!.AsArray().OfType<JsonObject>().Single(item => Text(item, "id") == key)["complete"] = true;
            var version = new JsonObject { ["id"] = id, ["object_key"] = key, ["name"] = name,
                ["saved_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), ["provenance"] = provenance.DeepClone() };
            next["versions"]!.AsArray().Add(version); Commit(next); return Version(version);
        }

        internal NativeMediaBackupBytes.VerifiedRaw Restore(NativeMediaBackupVersion selected, DeviceFileNativeDirectory.DeviceFileNativeStagedFile target)
        {
            Current(); var version = state["versions"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item => Text(item, "id") == selected.Id);
            if (version is null || Version(version) != selected) throw DeviceFileControl.Error("media_backup_stale_selection");
            var obj = state["objects"]!.AsArray().OfType<JsonObject>().Single(item => Text(item, "id") == selected.ObjectKey);
            using var held = OpenObject(obj);
            return NativeMediaBackupBytes.RestoreRawToNew(held, target, new(Identity(obj["identity"]!), Number(obj, "size"), Text(obj, "sha256")), Current);
        }
        public void Dispose() { revoked = true; folder.Dispose(); root.Dispose(); }
    }

    // Explicit native owner entry points, not wire handlers. Construction/import
    // starts no worker. Local restore is independent of any current peer session.
    internal IReadOnlyList<NativeMediaBackupVersion> NativeMediaBackupVersions(NativeMediaDestination destination, Func<bool> nativePermit)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, destination, Current, false); return catalog.Versions();
        }
    }
    internal NativeMediaBackupBytes.VerifiedRaw RestoreNativeMediaBackup(NativeMediaDestination destination, NativeMediaBackupVersion selected,
        DeviceFileNativeDirectory.DeviceFileNativeStagedFile target, Func<bool> nativePermit)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, destination, Current, false); return catalog.Restore(selected, target);
        }
    }
    internal NativeMediaBackupVersion SaveNativeMediaBackup(string peerId, string jobId, string jobVersion, string fileId,
        Func<bool> nativePermit, bool createBackup = false)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            void Current()
            {
                if (RestoreFenced || !nativePermit() || MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_backup_native_permit_changed");
                RequireNativeMediaStorageKey();
            }
            Current(); using var db = OpenNativeMediaDatabase(); db.Open();
            var job = ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == jobId && head.Version == jobVersion)
                ?? throw DeviceFileControl.Error("media_backup_original_saved_job_required");
            if (!job.Body.ContainsKey("saved") || !job.Body.ContainsKey("source_end")) throw DeviceFileControl.Error("media_backup_original_saved_job_required");
            var file = job.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item => TelefonMessagingContract.String(item, "id") == fileId)
                ?? throw DeviceFileControl.Error("media_backup_original_file_required");
            var member = job.Body["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == fileId);
            var receipt = job.Body["saved"]!["receipts"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "file_id") == fileId);
            var kind = TelefonMessagingContract.String(job.Body, "media_type");
            var destination = ReadNativeMediaDestination(peerId, kind) ?? throw DeviceFileControl.Error("media_backup_original_destination_required");
            if (destination.Version != TelefonMessagingContract.String(job.Body, "destination_version") ||
                destination.DestinationToken != TelefonMessagingContract.String(job.Body["binding"]!.AsObject(), "destination_token"))
                throw DeviceFileControl.Error("media_backup_original_destination_required");
            using var root = destination.OpenNative();
            using var album = job.Body["album_root"] is JsonObject albumRoot ? root.OpenOriginalChild(TelefonMessagingContract.String(albumRoot, "folder"),
                NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject())) : null;
            var parent = album ?? root;
            void Bound()
            {
                Current(); _ = root.CurrentIdentity(); _ = parent.CurrentIdentity();
                if (ReadNativeMediaDestination(peerId, kind) != destination) throw DeviceFileControl.Error("media_backup_original_destination_changed");
            }
            var name = DeviceFileNativeDirectory.ReceiveLeaf(TelefonMessagingContract.String(file, "path"));
            var size = TelefonProtocolContract.Integer(file["size"]); var hash = TelefonMessagingContract.String(file, "sha256");
            using var source = parent.OpenOriginalStagedFile(name, NativeMediaReceiveJob.NativeAlbumIdentity(member["identity"]!.AsObject()), size, hash);
            using var catalog = new MediaBackupCatalog(this, destination, Bound, createBackup);
            var provenance = new JsonObject { ["peer_id"] = peerId, ["pairing_epoch"] = scope.PairingEpoch, ["job_id"] = jobId,
                ["job_version"] = jobVersion, ["file_id"] = fileId, ["receipt"] = receipt.DeepClone() };
            return catalog.Save(source, size, hash, album is null ? name : TelefonMessagingContract.String(job.Body["album_root"]!.AsObject(), "folder") + "/" + name, provenance);
        }
    }
}
