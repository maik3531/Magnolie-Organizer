using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMappedMediaCandidate(string JobId, string JobVersion, string FileId, string SourceEpoch, string PhotoId);
internal sealed record NativeMappedMediaCandidatePlan(IReadOnlyList<NativeMappedMediaCandidate> Candidates, bool NeedsReview);

internal sealed partial class TelefonStore
{
    // Bounded protected mapping inventory only. No filename scan, source owner,
    // absence/deletion evidence or authority is created by this projection.
    internal NativeMappedMediaCandidatePlan NativeMappedMediaCandidates(string peerId, string mediaType)
    {
        MediaDestinationKind(mediaType);
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            var destination = ReadOriginalLegacyDestination(peerId, mediaType);
            if (destination is null) return new([], false);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var heads = ReceiveHeads(db, null, scope);
            var superseded = new HashSet<(string Job, string File)>();
            foreach (var head in heads)
                foreach (var file in head.Body["files"]!.AsArray().OfType<JsonObject>())
                    superseded.UnionWith(ReplacementAncestors(heads, head.Body, TelefonMessagingContract.String(file, "id")));
            var expectedDestination = new JsonObject { ["native_path"] = destination.NativePath, ["volume_path"] = destination.VolumePath,
                ["identity"] = NativeMediaReceiveJob.NativeIdentity(destination.RootIdentity), ["token"] = destination.DestinationToken };
            var candidates = new List<NativeMappedMediaCandidate>(); var review = false;
            foreach (var head in heads)
            {
                if (head.Body["media"] is not JsonObject media || TelefonMessagingContract.String(media, "media_type") != mediaType ||
                    TelefonMessagingContract.String(head.Body, "destination_version") != destination.Version || !JsonNode.DeepEquals(head.Body["destination"], expectedDestination)) continue;
                foreach (var member in media["entries"]!.AsArray().OfType<JsonObject>())
                {
                    var fileId = TelefonMessagingContract.String(member, "file_id");
                    if (superseded.Contains((head.JobId, fileId))) continue;
                    if (!head.Body.ContainsKey("saved") || !head.Body.ContainsKey("source_end")) { review = true; continue; }
                    candidates.Add(new(head.JobId, head.Version, fileId, TelefonMessagingContract.String(media, "source_epoch"), TelefonMessagingContract.String(member, "photo_id")));
                }
            }
            var unique = new List<NativeMappedMediaCandidate>();
            foreach (var group in candidates.GroupBy(item => (item.SourceEpoch, item.PhotoId)))
            { if (group.Count() == 1) unique.Add(group.Single()); else review = true; }
            return new(unique.OrderBy(item => item.JobId, StringComparer.Ordinal).ThenBy(item => item.FileId, StringComparer.Ordinal).ToArray(), review);
        }
    }

    internal bool HasNativeMediaSourceReference(string peerId, JsonObject original)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open(); using var transaction = db.BeginTransaction(deferred: true);
            var exists = SourceRecords(db, transaction, scope).Any(item => item.Body["local_origin"] is null &&
                JsonNode.DeepEquals(item.Body["originals"]!.AsObject().Single().Value, original));
            transaction.Commit(); return exists; // Scheduling fact only, never live source rights.
        }
    }

    internal sealed class NativeMappedMediaSource : NativeMediaSourceOwner
    {
        private readonly object sourceGate = new();
        private readonly DeviceFileNativeDirectory root;
        private readonly DeviceFileNativeDirectory? album;
        private readonly DeviceFileNativeDirectory.ManagedSource file;
        private readonly JsonObject original;
        private readonly string senderId, receiverId, path;
        private DeviceFileManifest? prepared;
        private DeviceFileNativeDirectory.CollectionSignature? comparedCollection;
        internal override TelefonStore Store { get; }
        internal override string PeerId { get; }
        internal override object ConnectionOwner { get; }
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
        // Historical observation from THIS source's actual complete raw read.
        // Remains metadata after END, never live READ/SEND or publication rights.
        internal DeviceFileNativeDirectory.CollectionSignature ComparedCollectionObservation
        {
            get { lock (sourceGate) return comparedCollection ?? throw DeviceFileControl.Error("media_collection_actual_mapping_comparison_required"); }
        }
        internal JsonObject OriginalReference => original.DeepClone().AsObject(); // Correlation, never a phone grant.
        internal override byte[] ReadExact(long offset, int count) => file.ReadExact(offset, count);
        internal override void Require() => file.Require();
        internal override JsonObject Provenance => provenance.DeepClone().AsObject();
        internal override JsonObject? LocalOrigin => null;
        internal NativePreparedMediaSource Freeze() => FreezeCore(completedSuccessor: false);
        internal NativePreparedMediaSource FreezeCompletedSuccessor() => FreezeCore(completedSuccessor: true);
        private NativePreparedMediaSource FreezeCore(bool completedSuccessor)
        {
            NativePreparedMediaSource result;
            lock (sourceGate)
            {
                file.Require();
                if (frozen is null)
                {
                    if (freezeAttempted) throw DeviceFileControl.Error("media_source_original_preparation_required");
                    freezeAttempted = true;
                    frozen = Store.FreezeNativeMappedMediaSource(this, completedSuccessor);
                }
                result = frozen;
            }
            result.Require(); return result;
        }
        // Hash the SAME immutable held bytes that an eventual sender will read.
        // No wire output, cache adoption, Saved receipt or persistent send job
        // is created by preparation. The source handle must remain owned.
        internal override DeviceFileManifest PrepareManifest()
        {
            lock (sourceGate)
            {
                file.Require();
                if (prepared is not null) return prepared;
                var collectionObservation = file.ObserveCollection();
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
                file.Require();
                if (file.ObserveCollection() != collectionObservation) throw DeviceFileControl.Error("media_collection_original_content_changed");
                comparedCollection = collectionObservation; prepared = manifest; return manifest;
            }
        }
        internal override JsonObject PreparedOriginalReferences()
        {
            lock (sourceGate)
            {
                file.Require();
                if (prepared is null) throw DeviceFileControl.Error("media_source_prepared_manifest_required");
                return new JsonObject { [prepared.Files[0].Id] = original.DeepClone() };
            }
        }
        public override void Dispose()
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
        var consent = ReadNativeMediaSendConsent(peerId);
        if (!consent.Explicit || !(mediaType == "images" ? consent.Photos : consent.Videos))
            throw DeviceFileControl.Error("media_source_local_sending_consent_required");
        // The existing source owner independently reauthenticates its exact
        // Mapping on every IO. Resolve its immutable original root, not a future
        // current receive choice and never an inert staged destination.
        var destination = ReadOriginalLegacyDestination(peerId, mediaType) ?? throw DeviceFileControl.Error("media_source_original_destination_required");
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
            if (ReadNativeMediaSendConsent(peerId) != consent)
                throw DeviceFileControl.Error("media_source_local_sending_consent_changed");
            if (MediaPreferenceScope(peerId) != scope || ReadOriginalLegacyDestination(peerId, mediaType) != destination ||
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
    internal async Task<(int Sent, bool NeedsReview)> SynchronizeNativeMappedMediaChangesAsync(string mediaType, NativeMediaBookPermit book,
        Action requireCurrent, CancellationToken token, bool automatic = true)
    {
        var intent = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey) ?? throw DeviceFileControl.Error("media_source_current_intent_required");
        NativeFileControlSession? collectionControls = null;
        DeviceTransferBinding? collectionBinding = null;
        void Current()
        {
            token.ThrowIfCancellationRequested(); book.Require(); requireCurrent();
            if (collectionControls is not null && RequireNativeFileControls(collectionControls).Binding(new string('0', 64), true) != collectionBinding)
                throw DeviceFileControl.Error("media_collection_original_send_binding_required");
            if (!MediaSharedSettingsReady || !JsonNode.DeepEquals(intent, store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey)) ||
                !MediaSyncSettings.TransferRequestedFor(intent, mediaType, toPhone: true))
                throw DeviceFileControl.Error("media_source_current_sending_owner_required");
        }
        Current();
        var entire = MediaSyncSettings.Effective(intent)["collection_mode"]!.GetValue<string>() == "entire_collection";
        if (entire && automatic) throw DeviceFileControl.Error("media_source_entire_collection_automatic_acceptance_required");
        if (entire)
        {
            collectionControls = RequireNativeFileControls();
            collectionBinding = collectionControls.Binding(new string('0', 64), true)
                ?? throw DeviceFileControl.Error("media_source_positive_sending_grant_required");
        }
        using var collection = entire ? new NativeCollectionMediaPass(store, peer.Id, mediaType, Current, token, this) : null;
        var plan = store.NativeMappedMediaCandidates(peer.Id, mediaType); var sent = 0;
        var review = plan.NeedsReview;
        foreach (var candidate in plan.Candidates)
        {
            Current();
            var destination = DeviceFileControl.Digest("magnolie-media-source-candidate-v1\0", new JsonObject {
                ["job_id"] = candidate.JobId, ["job_version"] = candidate.JobVersion, ["file_id"] = candidate.FileId });
            TelefonStore.NativeMappedMediaSource source;
            try { source = OpenNativeMappedMediaSource(mediaType, candidate.JobId, candidate.JobVersion, candidate.FileId, destination, book,
                collection is null ? null : collection.Require); }
            catch (InvalidDataException error) when (error.Message == "media_source_photo_metadata_required")
            { Current(); continue; } // Explicit photos-only filter, not a missing-file/deletion assumption.
            using var heldSource = source;
            collection?.AdmitMapping(source);
            var manifest = source.PrepareManifest(); var file = manifest.Files.Single(); var original = source.OriginalReference;
            if (file.Sha256 == original["original_sha256"]!.GetValue<string>() && file.Size == TelefonProtocolContract.Integer(original["original_size"]) &&
                !store.HasNativeMediaSourceReference(peer.Id, original))
            { Current(); collection?.NoteCheckedMapping(source); continue; }
            // Reject unsupported actual bytes before reserving a cache. The real
            // sender independently checks its authenticated frozen bytes again.
            var prefix = new byte[(int)Math.Min(file.Size, NativeMediaContentMime.PrefixBytes)];
            try
            {
                for (var offset = 0; offset < prefix.Length;)
                {
                    Current(); var chunk = source.ReadExact(offset, Math.Min(DeviceFileManifest.ChunkBytes, prefix.Length - offset));
                    try { chunk.CopyTo(prefix, offset); offset += chunk.Length; }
                    finally { CryptographicOperations.ZeroMemory(chunk); }
                }
                _ = NativeMediaContentMime.Identify(prefix, file.Size, mediaType);
            }
            finally { CryptographicOperations.ZeroMemory(prefix); }
            TelefonStore.NativePreparedMediaSource cache;
            try { cache = source.FreezeCompletedSuccessor(); }
            catch (InvalidDataException error) when (error.Message == "media_source_cache_latest_payload_already_sent")
            { Current(); collection?.NoteCheckedMapping(source); continue; }
            using (cache) { await SendNativeMappedMediaSourceToSourceEndAsync(cache, token); }
            collection?.NoteCheckedMapping(source);
            Current(); sent++;
        }
        if (collection is not null)
        {
            foreach (var (selection, member) in collection.Members())
            {
                Current();
                var destination = DeviceFileControl.Digest("magnolie-media-collection-member-v1\0", new JsonObject {
                    ["root_id"] = selection.Id, ["root_version"] = selection.Version });
                TelefonStore.NativeCollectionMediaSource source;
                try { source = OpenNativeCollectionMediaSource(mediaType, selection.Id, selection.Version, member, destination, book, collection.Require); }
                catch (InvalidDataException error) when (error.Message == "media_source_photo_metadata_required")
                { Current(); continue; }
                using var heldSource = source;
                collection.CheckOpened(selection, member, source.ObserveCollection());
                TelefonStore.NativePreparedMediaSource cache;
                try { cache = source.FreezeCompletedSuccessor(); }
                catch (InvalidDataException error) when (error.Message == "media_collection_known_other_type")
                { Current(); continue; } // Explicit exclusion, never a known publication or new grant.
                catch (InvalidDataException error) when (error.Message == "media_source_cache_latest_payload_already_sent")
                { Current(); continue; }
                using (cache) { await SendNativeMappedMediaSourceToSourceEndAsync(cache, token); }
                Current(); sent++;
            }
            collection.Finish();
        }
        Current(); return (sent, review);
    }

    internal TelefonStore.NativeMappedMediaSource OpenNativeMappedMediaSource(string mediaType, string jobId, string jobVersion,
        string fileId, string phoneDestinationToken, NativeMediaBookPermit book, Action? requireCurrent = null)
    {
        if (!DeviceFileControl.Hash(phoneDestinationToken)) throw DeviceFileControl.Error("media_source_phone_destination_required");
        var controls = RequireNativeFileControls();
        var sending = controls.Binding(phoneDestinationToken, senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_positive_sending_grant_required");
        var intent = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey) ?? throw DeviceFileControl.Error("media_source_current_intent_required");
        void Current()
        {
            cancellation.ThrowIfCancellationRequested(); book.Require(); requireCurrent?.Invoke();
            if (!MediaSharedSettingsReady || !JsonNode.DeepEquals(intent, store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey)) ||
                RequireNativeFileControls(controls).Binding(phoneDestinationToken, senderIsLocal: true) != sending)
                throw DeviceFileControl.Error("media_source_current_sending_owner_required");
        }
        Current();
        return store.OpenNativeMappedMediaSource(peer.Id, mediaType, jobId, jobVersion, fileId, sending, book, intent, Current, this);
    }
}
