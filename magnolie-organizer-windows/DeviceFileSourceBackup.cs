using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed record RecoveredVideoBackup(NativeMediaBackupParent Parent, NativeMediaBackupVersion Version, JsonObject Provenance)
    {
        internal JsonObject Evidence() => new()
        {
            ["id"] = Version.Id, ["object_key"] = Version.ObjectKey, ["saved_ms"] = Version.SavedMs,
            ["name"] = Version.Name, ["record_sha256"] = Version.RecordSha256
        };
    }

    private static JsonObject PcBackupProvenance(JsonObject job, string version, string id) => new()
    {
        ["kind"] = "prepared_pc_source", ["format"] = 1, ["job_id"] = id, ["job_version"] = version,
        ["nonce"] = job["nonce"]!.DeepClone(), ["scope"] = job["scope"]!.DeepClone(), ["manifest"] = job["manifest"]!.DeepClone(),
        ["source_provenance"] = job["provenance"]!.DeepClone(), ["local_origin"] = job["local_origin"]!.DeepClone(),
        ["previous"] = job["previous"]?.DeepClone()
    };

    private static void ValidateRecoveredVideoBackup(JsonObject job, string version, DeviceFileManifest manifest, JsonObject proof)
    {
        TelefonProtocolContract.ExactObject(proof, "id", "object_key", "saved_ms", "name", "record_sha256");
        var provenance = PcBackupProvenance(job, version, manifest.SourceId);
        var record = proof.DeepClone().AsObject();
        record.Remove("record_sha256");
        record["provenance"] = provenance;
        ValidatePreparedPcBackup(record, provenance);
        if (record["id"]?.GetValue<string>() != DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", provenance) ||
            TelefonProtocolContract.Integer(record["saved_ms"]) is < 1 or > NativeMediaBackupPolicy.MaximumTimestampMs ||
            proof["record_sha256"]?.GetValue<string>() != DeviceFileControl.Digest("magnolie-native-media-backup-reference-v1\0", record))
            throw DeviceFileControl.Error("media_backup_original_version_changed");
    }

    internal void WithVerifiedRecoveredVideoBackup(RecoveredVideoBackup backup, string fileId, Func<bool> permit, Action<Action> finish)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !permit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, backup.Parent, Current, false);
            catalog.VerifyPreparedBatchMap(new Dictionary<string, NativeMediaBackupVersion> { [fileId] = backup.Version },
                new Dictionary<string, JsonObject> { [fileId] = backup.Provenance }, finish: finish);
        }
    }

    // Source backup is not an incoming Saved receipt, source-END or a grant to
    // publish/delete. The output directory has its own explicit native WRITE
    // owner; the selected collection remains read-only.
    private static void ValidatePreparedPcBackup(JsonObject version, JsonObject raw)
    {
        if (raw["kind"]?.GetValue<string>() == "prepared_pc_batch_source")
        {
            ValidatePreparedBatchPcBackup(version, raw);
            return;
        }
        var value = TelefonProtocolContract.ExactObject(raw, "kind", "format", "job_id", "job_version", "nonce", "scope",
            "manifest", "source_provenance", "local_origin", "previous");
        var scope = TelefonProtocolContract.ExactObject(value["scope"]!, "peer_id", "peer_key", "pairing_epoch", "local_id", "local_key");
        var source = TelefonProtocolContract.ExactObject(value["source_provenance"]!, "collection_root", "collection_version",
            "book_version", "media_type", "settings", "sending_binding");
        var binding = TelefonProtocolContract.ExactObject(source["sending_binding"]!, "sender_id", "receiver_id",
            "sender_identity_sha256", "receiver_identity_sha256", "permission_epoch", "destination_token");
        using var document = System.Text.Json.JsonDocument.Parse(value["manifest"]!.ToJsonString());
        var manifest = DeviceFileManifest.Parse(document.RootElement);
        string Text(JsonObject obj, string key) => TelefonMessagingContract.String(obj, key);
        var kind = Text(source, "media_type");
        ValidateLocalCollectionOrigin(value["local_origin"]!, source);
        MediaSyncSettings.ValidateStart(new JsonObject { ["format"] = 1, ["settings"] = source["settings"]!.DeepClone() });
        if (Text(value, "kind") != "prepared_pc_source" || TelefonProtocolContract.Integer(value["format"]) != 1 ||
            !SourceId(Text(value, "job_id")) || manifest.SourceId != Text(value, "job_id") || manifest.Files.Count != 1 ||
            !DeviceFileControl.Hash(Text(value, "job_version")) || !DeviceFileControl.Hash(Text(value, "nonce")) ||
            !DeviceFileControl.Hash(Text(source, "book_version")) ||
            new[] { "peer_key", "pairing_epoch", "local_key" }.Any(key => !DeviceFileControl.Hash(Text(scope, key))) ||
            manifest.SenderId != Text(scope, "local_id") || manifest.ReceiverId != Text(scope, "peer_id") ||
            Text(binding, "sender_id") != manifest.SenderId || Text(binding, "receiver_id") != manifest.ReceiverId ||
            Text(binding, "sender_identity_sha256") != Text(scope, "local_key") || Text(binding, "receiver_identity_sha256") != Text(scope, "peer_key") ||
            !DeviceFileControl.Hash(Text(binding, "permission_epoch")) || !DeviceFileControl.Hash(Text(binding, "destination_token")) ||
            !MediaSyncSettings.TransferRequestedFor(source["settings"]!.AsObject(), kind, toPhone: true) ||
            MediaSyncSettings.Effective(source["settings"]!.AsObject())["collection_mode"]!.GetValue<string>() != "entire_collection" ||
            Text(version, "object_key") != NativeMediaBackupPolicy.ContentKey(manifest.Files[0].Size, manifest.Files[0].Sha256) ||
            Text(version, "name") != manifest.Files[0].Path ||
            value["local_origin"]!["relative_path"] is JsonValue path && path.GetValue<string>().Split('/').Last() != manifest.Files[0].Path)
            throw DeviceFileControl.Error("media_backup_pc_source_provenance_invalid");
        if (value["previous"] is not null)
        {
            var previous = TelefonProtocolContract.ExactObject(value["previous"]!, "job_id", "job_version", "exchange_version");
            if (!SourceId(Text(previous, "job_id")) || Text(previous, "job_id") == manifest.SourceId ||
                !DeviceFileControl.Hash(Text(previous, "job_version")) || !DeviceFileControl.Hash(Text(previous, "exchange_version")))
                throw DeviceFileControl.Error("media_backup_pc_source_provenance_invalid");
        }
    }

    internal NativeMediaBackupVersion SaveNativePreparedPcBackup(NativePreparedMediaSource source,
        DeviceFileNativeDirectory output, Func<bool> nativePermit, bool createBackup = false)
    {
        ArgumentNullException.ThrowIfNull(source); ArgumentNullException.ThrowIfNull(output); ArgumentNullException.ThrowIfNull(nativePermit);
        if (!ReferenceEquals(source.OwnerStore, this)) throw DeviceFileControl.Error("media_backup_original_source_owner_required");
        return source.SavePcBackup(output, nativePermit, createBackup);
    }

    internal sealed partial class NativePreparedMediaSource
    {
        internal NativeMediaBackupVersion SavePcBackup(DeviceFileNativeDirectory output, Func<bool> nativePermit, bool create)
        {
            // Preserve the existing cache -> store lock order. Disposal marks
            // retirement immediately but cannot release the original source
            // handles while this actual local-copy IO is still draining.
            lock (cacheGate)
            lock (store.gate)
            {
                Require();
                if (record["local_origin"] is not JsonObject) throw DeviceFileControl.Error("media_backup_pc_source_required");
                var parent = NativeMediaBackupParent.Capture(output);
                var originalVersion = version; var originalNonce = record["nonce"]!.GetValue<string>();
                void Current()
                {
                    if (store.RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed");
                    Require();
                    if (version != originalVersion || record["nonce"]!.GetValue<string>() != originalNonce ||
                        NativeMediaBackupParent.Capture(output) != parent)
                        throw DeviceFileControl.Error("media_backup_original_source_owner_required");
                }
                Current(); var file = Manifest.Files.Single();
                var provenance = PcBackupProvenance(record, version, JobId);
                using var catalog = new MediaBackupCatalog(store, parent, Current, create);
                return catalog.Save(NativeMediaBackupBytes.Input.FromPrepared(this), file.Size, file.Sha256, file.Path, provenance);
            }
        }

        internal RecoveredVideoBackup FindRecoveredVideoBackup(DeviceFileNativeDirectory output, Func<bool> permit)
        {
            lock (cacheGate)
            lock (store.gate)
            {
                Require();
                if (Recovery is null) throw DeviceFileControl.Error("media_source_video_original_saved_required");
                var parent = NativeMediaBackupParent.Capture(output);
                var provenance = PcBackupProvenance(record, version, JobId);
                var id = DeviceFileControl.Digest("magnolie-native-media-backup-version-v1\0", provenance);
                void Current()
                {
                    Require();
                    if (!permit() || NativeMediaBackupParent.Capture(output) != parent)
                        throw DeviceFileControl.Error("media_backup_native_permit_changed");
                }
                using var catalog = new MediaBackupCatalog(store, parent, Current, false);
                var selected = catalog.Versions().SingleOrDefault(item => item.Id == id)
                    ?? throw DeviceFileControl.Error("media_backup_original_version_changed");
                return new(parent, selected, provenance);
            }
        }
    }

    // These explicit raw recovery APIs do not consult a peer, collection,
    // receive destination, mapping store or prepared transfer cache. Publication
    // into a synchronized collection still needs a separate native owner.
    internal IReadOnlyList<NativeMediaBackupVersion> NativeIndependentBackupVersions(NativeMediaBackupParent parent, Func<bool> nativePermit)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, parent, Current, false); return catalog.RecoveryVersions();
        }
    }

    internal NativeMediaBackupBytes.VerifiedRaw RestoreNativeIndependentBackup(NativeMediaBackupParent parent,
        NativeMediaBackupVersion selected, DeviceFileNativeDirectory.DeviceFileNativeStagedFile target, Func<bool> nativePermit)
    {
        lock (gate)
        {
            void Current() { if (RestoreFenced || !nativePermit()) throw DeviceFileControl.Error("media_backup_native_permit_changed"); }
            using var catalog = new MediaBackupCatalog(this, parent, Current, false); return catalog.Restore(selected, target);
        }
    }
}
