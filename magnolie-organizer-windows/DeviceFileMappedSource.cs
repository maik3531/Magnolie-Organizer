using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed class NativeMappedMediaSource : IDisposable
    {
        private readonly object sourceGate = new();
        private readonly DeviceFileNativeDirectory root;
        private readonly DeviceFileNativeDirectory? album;
        private readonly DeviceFileNativeDirectory.ManagedSource file;
        private readonly JsonObject original;
        private readonly string senderId, receiverId, path;
        private DeviceFileManifest? prepared;
        internal readonly TelefonStore Store;
        internal readonly string PeerId;
        internal readonly object ConnectionOwner;
        private readonly JsonObject provenance;
        private NativePreparedMediaSource? frozen;
        private bool freezeAttempted;
        internal NativeMappedMediaSource(DeviceFileNativeDirectory root, DeviceFileNativeDirectory? album,
            DeviceFileNativeDirectory.ManagedSource file, JsonObject original, string senderId, string receiverId, string path,
            TelefonStore store, string peerId, JsonObject provenance, object connectionOwner)
        {
            this.root = root; this.album = album; this.file = file; this.original = original.DeepClone().AsObject();
            this.senderId = senderId; this.receiverId = receiverId; this.path = path;
            Store = store; PeerId = peerId; this.provenance = provenance.DeepClone().AsObject();
            ConnectionOwner = connectionOwner;
        }
        internal long Size => file.Size;
        internal JsonObject OriginalReference => original.DeepClone().AsObject(); // Correlation, never a phone grant.
        internal byte[] ReadExact(long offset, int count) => file.ReadExact(offset, count);
        internal void Require() => file.Require();
        internal JsonObject Provenance => provenance.DeepClone().AsObject();
        internal NativePreparedMediaSource Freeze()
        {
            NativePreparedMediaSource result;
            lock (sourceGate)
            {
                file.Require();
                if (frozen is null)
                {
                    if (freezeAttempted) throw DeviceFileControl.Error("media_source_original_preparation_required");
                    freezeAttempted = true;
                    frozen = Store.FreezeNativeMappedMediaSource(this);
                }
                result = frozen;
            }
            result.Require(); return result;
        }
        // Hash the SAME immutable held bytes that an eventual sender will read.
        // No wire output, cache adoption, Saved receipt or persistent send job
        // is created by preparation. The source handle must remain owned.
        internal DeviceFileManifest PrepareManifest()
        {
            lock (sourceGate)
            {
                file.Require();
                if (prepared is not null) return prepared;
                using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                for (long offset = 0; offset < file.Size;)
                {
                    var chunk = file.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, file.Size - offset));
                    try { digest.AppendData(chunk); offset += chunk.Length; }
                    finally { CryptographicOperations.ZeroMemory(chunk); }
                }
                file.Require();
                var hash = Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant();
                var manifest = new DeviceFileManifest(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), senderId, receiverId,
                    [new DeviceManifestFile(Guid.NewGuid().ToString("N"), path, file.Size, hash)], file.Size);
                file.Require(); prepared = manifest; return manifest;
            }
        }
        internal JsonObject PreparedOriginalReferences()
        {
            lock (sourceGate)
            {
                file.Require();
                if (prepared is null) throw DeviceFileControl.Error("media_source_prepared_manifest_required");
                return new JsonObject { [prepared.Files[0].Id] = original.DeepClone() };
            }
        }
        public void Dispose()
        {
            lock (sourceGate)
                try { file.Dispose(); } finally { try { album?.Dispose(); } finally { root.Dispose(); } }
        }
    }

    // Only the actual connection's original-book, exact matched-intent and
    // positive bilateral SEND/RECEIVE owner enters here. No browser path or
    // filename lookup can substitute for a protected completed mapping.
    internal NativeMappedMediaSource OpenNativeMappedMediaSource(string peerId, string mediaType, string jobId,
        string jobVersion, string fileId, DeviceTransferBinding sending, NativeMediaBookPermit book,
        JsonObject sharedIntent, Action requireConnection, object connectionOwner)
    {
        MediaDestinationKind(mediaType);
        if (!MediaSyncSettings.TransferRequestedFor(sharedIntent, mediaType, toPhone: true))
            throw DeviceFileControl.Error("media_source_current_sending_intent_required");
        var intent = sharedIntent.DeepClone().AsObject();
        var scope = MediaPreferenceScope(peerId);
        var destination = ReadNativeMediaDestination(peerId, mediaType) ?? throw DeviceFileControl.Error("media_source_original_destination_required");
        if (sending.SenderId != scope.LocalId || sending.SenderIdentitySha256 != scope.LocalKey ||
            sending.ReceiverId != scope.PeerId || sending.ReceiverIdentitySha256 != scope.PeerKey)
            throw DeviceFileControl.Error("media_source_current_sending_scope_required");

        ReceiveHead Mapping()
        {
            lock (gate)
            {
                using var db = OpenNativeMediaDatabase(); db.Open();
                var heads = ReceiveHeads(db, null, scope);
                var head = heads.SingleOrDefault(item => item.JobId == jobId);
                if (head is null || head.Version != jobVersion || !head.Body.ContainsKey("saved") || !head.Body.ContainsKey("source_end") ||
                    head.Body["media"] is not JsonObject media || TelefonMessagingContract.String(media, "media_type") != mediaType ||
                    TelefonMessagingContract.String(head.Body, "destination_version") != destination.Version ||
                    !JsonNode.DeepEquals(head.Body["destination"], new JsonObject { ["native_path"] = destination.NativePath,
                        ["volume_path"] = destination.VolumePath, ["identity"] = NativeMediaReceiveJob.NativeIdentity(destination.RootIdentity),
                        ["token"] = destination.DestinationToken }) ||
                    heads.Any(item => item.Body["files"]!.AsArray().OfType<JsonObject>().Any(file =>
                        ReplacementAncestors(heads, item.Body, TelefonMessagingContract.String(file, "id")).Contains((jobId, fileId)))))
                    throw DeviceFileControl.Error("media_source_original_saved_mapping_required");
                var selected = media["entries"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item =>
                    TelefonMessagingContract.String(item, "file_id") == fileId) ?? throw DeviceFileControl.Error("media_source_original_member_required");
                var photoId = TelefonMessagingContract.String(selected, "photo_id");
                var epoch = TelefonMessagingContract.String(media, "source_epoch");
                var superseded = new HashSet<(string Job, string File)>();
                foreach (var candidate in heads)
                    foreach (var file in candidate.Body["files"]!.AsArray().OfType<JsonObject>())
                        superseded.UnionWith(ReplacementAncestors(heads, candidate.Body, TelefonMessagingContract.String(file, "id")));
                if (heads.Count(candidate => candidate.Body["media"] is JsonObject other &&
                    TelefonMessagingContract.String(other, "media_type") == mediaType && TelefonMessagingContract.String(other, "source_epoch") == epoch &&
                    JsonNode.DeepEquals(candidate.Body["destination"], head.Body["destination"]) &&
                    other["entries"]!.AsArray().OfType<JsonObject>().Any(item => TelefonMessagingContract.String(item, "photo_id") == photoId &&
                        !superseded.Contains((candidate.JobId, TelefonMessagingContract.String(item, "file_id"))))) != 1)
                    throw DeviceFileControl.Error("media_source_ambiguous_original_mapping");
                return head;
            }
        }
        void Current()
        {
            book.Require(); requireConnection(); RequireNativeMediaStorageKey();
            if (MediaPreferenceScope(peerId) != scope || ReadNativeMediaDestination(peerId, mediaType) != destination ||
                !JsonNode.DeepEquals(intent, sharedIntent)) throw DeviceFileControl.Error("media_source_original_scope_changed");
            _ = Mapping(); book.Require(); requireConnection();
        }
        Current(); var head = Mapping();
        var metadata = head.Body["media"]!.AsObject();
        var entry = metadata["entries"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item => TelefonMessagingContract.String(item, "file_id") == fileId)
            ?? throw DeviceFileControl.Error("media_source_original_member_required");
        using var document = JsonDocument.Parse(head.Body["manifest"]!.ToJsonString());
        var manifest = DeviceFileManifest.Parse(document.RootElement);
        var mappedFile = manifest.Files.SingleOrDefault(item => item.Id == fileId) ?? throw DeviceFileControl.Error("media_source_original_member_required");
        var member = head.Body["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == fileId);
        var receipt = head.Body["saved"]!["receipts"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "file_id") == fileId);
        var reference = new JsonObject { ["source_epoch"] = metadata["source_epoch"]!.DeepClone(), ["photo_id"] = entry["photo_id"]!.DeepClone(),
            ["media_type"] = mediaType, ["manifest_sha256"] = manifest.Fingerprint, ["file_id"] = fileId,
            ["original_size"] = mappedFile.Size, ["original_sha256"] = mappedFile.Sha256, ["receipt_sha256"] = receipt["receipt_sha256"]!.DeepClone() };
        DeviceFileNativeDirectory? root = null, album = null; DeviceFileNativeDirectory.ManagedSource? source = null;
        try
        {
            Current(); root = destination.OpenNative();
            if (head.Body["album_root"] is JsonObject albumRoot)
                album = root.OpenOriginalChild(TelefonMessagingContract.String(albumRoot, "folder"),
                    NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject()));
            source = (album ?? root).OpenManagedSource(mappedFile.Path, NativeMediaReceiveJob.NativeAlbumIdentity(member["identity"]!.AsObject()), Current);
            if (mediaType == "images" && MediaSyncSettings.Effective(intent)["photos_only"]!.GetValue<bool>() && !source.MatchesPhotoMetadata())
                throw DeviceFileControl.Error("media_source_photo_metadata_required");
            var provenance = new JsonObject { ["mapping_job"] = jobId, ["mapping_version"] = jobVersion, ["mapping_file"] = fileId,
                ["book_version"] = book.Version, ["media_type"] = mediaType, ["settings"] = intent.DeepClone(), ["sending_binding"] = sending.Snapshot() };
            Current(); return new(root, album, source, reference, sending.SenderId, sending.ReceiverId, mappedFile.Path, this, peerId, provenance, connectionOwner);
        }
        catch { source?.Dispose(); album?.Dispose(); root?.Dispose(); throw; }
    }
}

internal sealed partial class TelefonConnection
{
    internal TelefonStore.NativeMappedMediaSource OpenNativeMappedMediaSource(string mediaType, string jobId, string jobVersion,
        string fileId, string phoneDestinationToken, NativeMediaBookPermit book)
    {
        if (!DeviceFileControl.Hash(phoneDestinationToken)) throw DeviceFileControl.Error("media_source_phone_destination_required");
        var controls = RequireNativeFileControls();
        var sending = controls.Binding(phoneDestinationToken, senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_positive_sending_grant_required");
        var intent = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey) ?? throw DeviceFileControl.Error("media_source_current_intent_required");
        void Current()
        {
            cancellation.ThrowIfCancellationRequested(); book.Require();
            if (!MediaSharedSettingsReady || !JsonNode.DeepEquals(intent, store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey)) ||
                RequireNativeFileControls(controls).Binding(phoneDestinationToken, senderIsLocal: true) != sending)
                throw DeviceFileControl.Error("media_source_current_sending_owner_required");
        }
        Current();
        return store.OpenNativeMappedMediaSource(peer.Id, mediaType, jobId, jobVersion, fileId, sending, book, intent, Current, this);
    }
}
