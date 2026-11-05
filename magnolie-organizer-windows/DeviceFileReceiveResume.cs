using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed record NativeMediaResumeSelection(TelefonStore Owner, string PeerId, string JobId, string Version,
        string MediaType, string DestinationVersion, DeviceFileManifest Manifest)
    {
        internal bool GrantsResumeAuthority => false;
    }

    // Read exact existing history only: no directory open, key bootstrap, new
    // job, reservation, chunk grant or claim that staged bytes were recovered.
    internal NativeMediaResumeSelection SelectNativeMediaResume(string peerId, string jobId, string expectedVersion)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var head = ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == jobId);
            if (head is null || head.Version != expectedVersion) throw DeviceFileControl.Error("file_receive_original_history_required");
            using var document = JsonDocument.Parse(head.Body["manifest"]!.ToJsonString());
            var manifest = DeviceFileManifest.Parse(document.RootElement);
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_history_binding_changed");
            return new(this, peerId, jobId, head.Version, TelefonMessagingContract.String(head.Body, "media_type"),
                TelefonMessagingContract.String(head.Body, "destination_version"), manifest);
        }
    }

    internal void RequireNativeMediaResumeSelection(NativeMediaResumeSelection selected)
    {
        if (!ReferenceEquals(selected.Owner, this)) throw DeviceFileControl.Error("file_receive_foreign_resume_selection");
        var current = SelectNativeMediaResume(selected.PeerId, selected.JobId, selected.Version);
        if (current.MediaType != selected.MediaType || current.DestinationVersion != selected.DestinationVersion ||
            current.Manifest.Fingerprint != selected.Manifest.Fingerprint)
            throw DeviceFileControl.Error("file_receive_original_history_changed");
    }

    internal NativeMediaResumeSelection RecordNativeSourceResumeHistory(NativeMediaResumeSelection selected,
        DeviceFileResumeHistory remote, Action current)
    {
        lock (gate)
        {
            RequireNativeMediaResumeSelection(selected); current();
            if (remote.MediaType != selected.MediaType || remote.SourceId != selected.Manifest.SourceId ||
                remote.TransferId != selected.Manifest.TransferId || remote.ManifestSha256 != selected.Manifest.Fingerprint)
                throw DeviceFileControl.Error("file_receive_original_source_history_changed");
            var scope = MediaPreferenceScope(selected.PeerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var head = ReceiveHeads(db, null, scope).Single(value => value.JobId == selected.JobId);
            var body = head.Body.DeepClone().AsObject();
            body["source_job"] = new JsonObject { ["job_id"] = remote.JobId, ["job_version"] = remote.JobVersion };
            var saved = SaveReceiveHead(selected.PeerId, selected.JobId, selected.Version, body, current);
            return selected with { Version = saved.Version };
        }
    }

    internal NativeMediaReceiveJob RecoverNativeMediaReceiveJob(NativeMediaResumeSelection selected, Func<DeviceTransferBinding?> currentBinding)
        => NativeMediaReceiveJob.Recover(this, selected, currentBinding);

    internal sealed partial class NativeMediaReceiveJob
    {
        private bool recoveredOriginal;

        internal void RequireRecoveredSourceResume(NativeMediaResumeSelection selected, DeviceFileResumeHistory remote)
        {
            lock (jobGate)
            {
                Current(); store.RequireNativeMediaResumeSelection(selected);
                if (!recoveredOriginal || !ReferenceEquals(selected.Owner, store) || selected.PeerId != peerId || selected.JobId != JobId ||
                    selected.Version != Version || selected.Manifest.Fingerprint != Manifest.Fingerprint || remote.ManifestSha256 != Manifest.Fingerprint ||
                    remote.SourceId != Manifest.SourceId || remote.TransferId != Manifest.TransferId || TelefonMessagingContract.String(head!.Body, "phase") != "receiving" ||
                    remote.MediaType != mediaType || head!.Body["source_job"] is not JsonObject source ||
                    TelefonMessagingContract.String(source, "job_id") != remote.JobId || TelefonMessagingContract.String(source, "job_version") != remote.JobVersion)
                    throw DeviceFileControl.Error("file_receive_original_recovered_owner_required");
            }
        }

        internal static NativeMediaReceiveJob Recover(TelefonStore store, NativeMediaResumeSelection selected, Func<DeviceTransferBinding?> currentBinding)
        {
            ArgumentNullException.ThrowIfNull(currentBinding);
            lock (store.gate)
            {
                store.RequireNativeMediaResumeSelection(selected);
                var scope = store.MediaPreferenceScope(selected.PeerId); using var db = store.OpenNativeMediaDatabase(); db.Open();
                var saved = store.ReceiveHeads(db, null, scope).Single(head => head.JobId == selected.JobId);
                if (TelefonMessagingContract.String(saved.Body, "phase") != "receiving" || !saved.Body.ContainsKey("source_job"))
                    throw DeviceFileControl.Error("file_receive_original_source_history_required");
                var destination = store.ReadNativeMediaDestination(selected.PeerId, selected.MediaType);
                if (destination is null || destination.Version != selected.DestinationVersion)
                    throw DeviceFileControl.Error("file_receive_original_destination_required");
                var owner = new NativeMediaReceiveJob(store, selected.PeerId, selected.MediaType, selected.Manifest, destination, currentBinding, selected.JobId);
                try
                {
                    if (!JsonNode.DeepEquals(saved.Body["binding"], owner.binding.Snapshot()))
                        throw DeviceFileControl.Error("file_receive_original_binding_required");
                    owner.head = saved; owner.root = destination.OpenNative(); owner.Current();
                    if (saved.Body["album_root"] is JsonObject originalAlbum)
                    {
                        owner.albumRoot = originalAlbum.DeepClone().AsObject();
                        owner.albumDirectory = owner.root.OpenOriginalChild(TelefonMessagingContract.String(originalAlbum, "folder"), AlbumIdentity(originalAlbum["identity"]!.AsObject()));
                    }
                    static DeviceFileNativeDirectory.Identity Identity(JsonNode node)
                    {
                        var value = node.AsObject();
                        return new(Convert.ToUInt64(TelefonMessagingContract.String(value, "volume"), 16),
                            Convert.ToUInt64(TelefonMessagingContract.String(value, "low"), 16), Convert.ToUInt64(TelefonMessagingContract.String(value, "high"), 16));
                    }
                    owner.stage = owner.root.OpenOriginalChild(TelefonMessagingContract.String(saved.Body, "stage_name"), Identity(saved.Body["stage_identity"]!));
                    var members = saved.Body["files"]!.AsArray().OfType<JsonObject>().ToArray();
                    var expected = selected.Manifest.Files.Select(file => file.Id + ".part").ToHashSet(StringComparer.Ordinal);
                    var count = 0;
                    foreach (var path in Directory.EnumerateFileSystemEntries(owner.stage.NativePath, "*", SearchOption.TopDirectoryOnly))
                    {
                        owner.Current();
                        if (++count > 16 || !expected.Remove(Path.GetFileName(path))) throw DeviceFileControl.Error("file_receive_original_stage_inventory_changed");
                    }
                    if (expected.Count != 0) throw DeviceFileControl.Error("file_receive_original_stage_inventory_changed");
                    for (var index = 0; index < members.Length; index++)
                    {
                        owner.Current(); var member = members[index]; var file = selected.Manifest.Files[index];
                        if (TelefonMessagingContract.String(member, "phase") != "receiving" || member["checkpoint"] is not JsonObject checkpoint)
                            throw DeviceFileControl.Error("file_receive_original_checkpoint_required");
                        var size = TelefonProtocolContract.Integer(checkpoint["size"]);
                        var payload = owner.stage.OpenOriginalStagedFile(file.Id + ".part", Identity(member["identity"]!), size, TelefonMessagingContract.String(checkpoint, "sha256"));
                        owner.files.Add(file.Id, payload);
                        for (long offset = 0; offset < size; offset += DeviceFileManifest.ChunkBytes)
                        {
                            owner.Current(); var chunk = payload.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, size - offset));
                            try
                            {
                                // Rebuild the ledger only from the actual held bytes
                                // authenticated by the persisted prefix checkpoint.
                                owner.ledger.Record(file.Id, checked((int)(offset / DeviceFileManifest.ChunkBytes)), chunk,
                                    (_, _, _) => owner.Current(), (_, at, length) => payload.ReadExact(at, length));
                            }
                            finally { System.Security.Cryptography.CryptographicOperations.ZeroMemory(chunk); }
                        }
                    }
                    store.RequireNativeMediaResumeSelection(selected); owner.Current(); owner.recoveredOriginal = true; return owner;
                }
                catch { owner.Dispose(); throw; } // Never truncate, recreate or delete uncertain original bytes.
            }
        }
    }
}
