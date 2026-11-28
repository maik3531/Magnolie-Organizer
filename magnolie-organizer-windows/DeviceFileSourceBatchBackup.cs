using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Refs #330. Historical per-member correlation of ONE protected root. The
    // full-root member digest avoids duplicating up to 6400 chunk witnesses in
    // every local backup version. These codecs never grant READ or retirement.
    private static void ValidatePreparedBatchPcBackup(JsonObject version, JsonObject raw)
    {
        var value = TelefonProtocolContract.ExactObject(raw, "kind", "format", "job_id", "job_version", "nonce", "scope",
            "manifest_sha256", "members_sha256", "file", "source_provenance", "local_origin", "previous");
        var scope = TelefonProtocolContract.ExactObject(value["scope"]!, "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key");
        var source = TelefonProtocolContract.ExactObject(value["source_provenance"]!, "collection_root", "collection_version",
            "book_version", "media_type", "settings", "sending_binding");
        var binding = TelefonProtocolContract.ExactObject(source["sending_binding"]!, "sender_id", "receiver_id",
            "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token");
        var file = TelefonProtocolContract.ExactObject(value["file"]!, "id", "path", "size", "sha256");
        static string Text(JsonObject obj, string key) => TelefonMessagingContract.String(obj, key);
        var kind = Text(source, "media_type");
        ValidateLocalCollectionOrigin(value["local_origin"]!, source);
        MediaSyncSettings.ValidateStart(new JsonObject { ["format"] = 1, ["settings"] = source["settings"]!.DeepClone() });
        if (Text(value, "kind") != "prepared_pc_batch_source" || TelefonProtocolContract.Integer(value["format"]) != 1 ||
            !SourceId(Text(value, "job_id")) || !SourceId(Text(file, "id")) || !DeviceFileManifest.PortablePath(Text(file, "path")) ||
            !DeviceFileControl.Hash(Text(file, "sha256")) ||
            TelefonProtocolContract.Integer(file["size"]) is < 1 or > DeviceFileManifest.MaxFileBytes ||
            new[] { "job_version", "nonce", "manifest_sha256", "members_sha256" }.Any(key => !DeviceFileControl.Hash(Text(value, key))) ||
            !DeviceFileControl.Hash(Text(source, "book_version")) ||
            new[] { "peer_key", "pairing_epoch", "local_key" }.Any(key => !DeviceFileControl.Hash(Text(scope, key))) ||
            !DeviceFileControl.Identity(Text(scope, "local_id")) || !DeviceFileControl.Identity(Text(scope, "peer_id")) ||
            Text(binding, "sender_id") != Text(scope, "local_id") || Text(binding, "receiver_id") != Text(scope, "peer_id") ||
            Text(binding, "sender_identity_sha256") != Text(scope, "local_key") || Text(binding, "receiver_identity_sha256") != Text(scope, "peer_key") ||
            !DeviceFileControl.Hash(Text(binding, "permission_epoch")) || !DeviceFileControl.Hash(Text(binding, "destination_token")) ||
            !MediaSyncSettings.TransferRequestedFor(source["settings"]!.AsObject(), kind, toPhone: true) ||
            MediaSyncSettings.Effective(source["settings"]!.AsObject())["collection_mode"]!.GetValue<string>() != "entire_collection" ||
            value["local_origin"]!["relative_path"]?.GetValue<string>() != Text(file, "path") ||
            Text(version, "name") != Text(file, "path") ||
            Text(version, "object_key") != NativeMediaBackupPolicy.ContentKey(TelefonProtocolContract.Integer(file["size"]), Text(file, "sha256")))
            throw DeviceFileControl.Error("media_backup_pc_batch_source_provenance_invalid");
        ValidateBatchPredecessor(value["previous"], Text(value, "job_id"));
    }

    private static JsonObject BatchBackupProvenance(JsonObject record, string version, DeviceFileManifest manifest, DeviceManifestFile file) =>
        new() { ["kind"] = "prepared_pc_batch_source", ["format"] = 1, ["job_id"] = manifest.SourceId,
            ["job_version"] = version, ["nonce"] = record["nonce"]!.DeepClone(), ["scope"] = record["scope"]!.DeepClone(),
            ["manifest_sha256"] = manifest.Fingerprint,
            ["members_sha256"] = DeviceFileControl.Digest("magnolie-pc-media-backup-batch-members-v1\0", new JsonObject {
                ["origins"] = record["origins"]!.DeepClone(), ["mime_types"] = record["mime_types"]!.DeepClone(), ["predecessors"] = record["predecessors"]!.DeepClone() }),
            ["file"] = new JsonObject { ["id"] = file.Id, ["path"] = file.Path, ["size"] = file.Size, ["sha256"] = file.Sha256 },
            ["source_provenance"] = record["provenance"]!.DeepClone(), ["local_origin"] = record["origins"]![file.Id]!.DeepClone(),
            ["previous"] = record["predecessors"]![file.Id]?.DeepClone() };

    internal IReadOnlyDictionary<string, NativeMediaBackupVersion> SaveNativePreparedPcBatchBackups(NativePreparedMediaBatch source,
        DeviceFileNativeDirectory output, Func<bool> nativePermit, bool createBackup = false, Action<string>? boundary = null)
    {
        ArgumentNullException.ThrowIfNull(source); ArgumentNullException.ThrowIfNull(output); ArgumentNullException.ThrowIfNull(nativePermit);
        if (!ReferenceEquals(source.OwnerStore, this)) throw DeviceFileControl.Error("media_backup_original_batch_owner_required");
        return source.SavePcBackups(output, nativePermit, createBackup, boundary);
    }

    internal sealed partial class NativePreparedMediaBatch
    {
        private JsonObject BackupProvenance(DeviceManifestFile file)
        {
            return BatchBackupProvenance(record, version, Manifest, file);
        }

        internal IReadOnlyDictionary<string, NativeMediaBackupVersion> SavePcBackups(DeviceFileNativeDirectory output,
            Func<bool> nativePermit, bool create, Action<string>? boundary)
        {
            lock (cacheGate)
            lock (store.gate)
            {
                Require(); var parent = NativeMediaBackupParent.Capture(output); var expectedVersion = version; var nonce = record["nonce"]!.GetValue<string>();
                void Current()
                {
                    if (store.RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed");
                    RequireBackupIdentity(expectedVersion, nonce);
                    if (NativeMediaBackupParent.Capture(output) != parent) throw DeviceFileControl.Error("media_backup_original_batch_owner_required");
                }
                Current(); VerifyCipherSet();
                boundary?.Invoke("source_batch_backup_ciphers_verified");
                var expected = Manifest.Files.ToDictionary(file => file.Id, BackupProvenance, StringComparer.Ordinal);
                var selected = new Dictionary<string, NativeMediaBackupVersion>(StringComparer.Ordinal);
                using var catalog = new MediaBackupCatalog(store, parent, Current, create && Recovery is null);
                boundary?.Invoke("source_batch_backup_catalog_opened");
                var existing = Recovery is null ? null : catalog.Versions().ToDictionary(item => item.Id, StringComparer.Ordinal);
                foreach (var file in Manifest.Files)
                {
                    Current();
                    var saved = existing is null
                        ? catalog.Save(NativeMediaBackupBytes.Input.FromPreparedBatch(this, file.Id), file.Size, file.Sha256, file.Path, expected[file.Id])
                        : existing.GetValueOrDefault(DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", expected[file.Id]))
                            ?? throw DeviceFileControl.Error("media_backup_complete_original_batch_map_required");
                    selected.Add(file.Id, saved); boundary?.Invoke("source_batch_backup_member_saved"); Current();
                }
                // The caller never sees a first-file or stale subset map.
                catalog.VerifyPreparedBatchMap(selected, expected); Current();
                boundary?.Invoke("source_batch_backup_all_members_verified");
                return new System.Collections.ObjectModel.ReadOnlyDictionary<string, NativeMediaBackupVersion>(selected);
            }
        }
    }

    private sealed partial class MediaBackupCatalog
    {
        private DeviceFileNativeDirectory.ManagedSource? batchSnapshot;

        internal void RequireOriginalBatchAnchor(Microsoft.Data.Sqlite.SqliteConnection db, Microsoft.Data.Sqlite.SqliteTransaction transaction)
        {
            Current();
            if (batchSnapshot is null || !JsonNode.DeepEquals(ReadAnchor(db, transaction), anchor))
                throw DeviceFileControl.Error("media_backup_original_catalog_required");
            batchSnapshot.Require();
        }

        internal void VerifyPreparedBatchMap(IReadOnlyDictionary<string, NativeMediaBackupVersion> selected,
            IReadOnlyDictionary<string, JsonObject> expected, NativeBatchSourceRetirement? retirement = null,
            Action<Action>? finish = null)
        {
            Current();
            if (selected.Count is < 1 or > DeviceFileManifest.MaxFiles || !selected.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(expected.Keys) ||
                selected.Values.Select(value => value.Id).Distinct(StringComparer.Ordinal).Count() != selected.Count)
                throw DeviceFileControl.Error("media_backup_complete_original_batch_map_required");
            var held = new Dictionary<string, (JsonObject Object, DeviceFileNativeDirectory.ManagedSource File)>(StringComparer.Ordinal);
            var identities = new HashSet<DeviceFileNativeDirectory.Identity>();
            try
            {
                // Pin the actual encrypted catalog, not just its in-memory
                // version map, through a native terminal callback/CAS too.
                if (batchSnapshot is not null) throw DeviceFileControl.Error("media_backup_original_catalog_required");
                batchSnapshot = folder.OpenManagedSource(Text(anchor, "name"), Identity(anchor["identity"]!), Current);
                using (var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
                {
                    for (long offset = 0; offset < batchSnapshot.Size;)
                    {
                        Current(); var bytes = batchSnapshot.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, batchSnapshot.Size - offset));
                        try { digest.AppendData(bytes); offset += bytes.Length; }
                        finally { CryptographicOperations.ZeroMemory(bytes); }
                    }
                    if (batchSnapshot.Size != Number(anchor, "size") || Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != Text(anchor, "sha256"))
                        throw DeviceFileControl.Error("media_backup_snapshot_changed");
                }
                foreach (var (fileId, selection) in selected)
                {
                    Current(); var obj = SelectedObject(selection);
                    var version = state["versions"]!.AsArray().OfType<JsonObject>().SingleOrDefault(value => Text(value, "id") == selection.Id);
                    if (version is null || !JsonNode.DeepEquals(version["provenance"], expected[fileId]) || !obj["complete"]!.GetValue<bool>())
                        throw DeviceFileControl.Error("media_backup_complete_original_batch_map_required");
                    if (held.ContainsKey(selection.ObjectKey)) continue; // Actual content dedup, not original-ID aliasing.
                    var file = folder.OpenManagedSource(Text(obj, "name"), Identity(obj["identity"]!), Current);
                    try
                    {
                        if (file.Size != Number(obj, "size") || !identities.Add(Identity(obj["identity"]!)))
                            throw DeviceFileControl.Error("media_backup_original_object_changed");
                        held.Add(selection.ObjectKey, (obj, file));
                    }
                    catch { file.Dispose(); throw; }
                }
                // All actual canonical RO descriptors stay held through every
                // payload hash AND final revalidation of earlier members.
                foreach (var (obj, file) in held.Values)
                {
                    Current(); using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                    for (long offset = 0; offset < file.Size;)
                    {
                        Current(); var bytes = file.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, file.Size - offset));
                        try { digest.AppendData(bytes); offset += bytes.Length; }
                        finally { CryptographicOperations.ZeroMemory(bytes); }
                    }
                    if (Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != Text(obj, "sha256"))
                        throw DeviceFileControl.Error("media_backup_original_content_changed");
                }
                foreach (var (obj, file) in held.Values)
                {
                    Current(); file.Require();
                    if (folder.FileIdentityAt(Text(obj, "name")) != Identity(obj["identity"]!))
                        throw DeviceFileControl.Error("media_backup_original_object_changed");
                }
                Current();
                batchSnapshot.Require();
                retirement?.FinishVerifiedBackupMap(this);
                finish?.Invoke(() =>
                {
                    Current();
                    batchSnapshot.Require();
                    foreach (var (_, file) in held.Values) file.Require();
                });
            }
            finally
            {
                foreach (var pair in held.Values.Reverse()) pair.File.Dispose();
                batchSnapshot?.Dispose(); batchSnapshot = null;
            }
        }
    }
}
