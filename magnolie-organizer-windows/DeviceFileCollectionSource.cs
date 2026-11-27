using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    internal sealed class NativeCollectionMediaSource : NativeMediaSourceOwner
    {
        private readonly object sourceGate = new();
        private readonly DeviceFileNativeDirectory root;
        private readonly DeviceFileNativeDirectory.CollectionSource file;
        private readonly string path, senderId, receiverId;
        private readonly JsonObject provenance, origin;
        private DeviceFileManifest? prepared;
        private string? preparedMime;
        private NativePreparedMediaSource? frozen;
        private bool freezeAttempted;
        internal override TelefonStore Store { get; }
        internal override string PeerId { get; }
        internal override object ConnectionOwner { get; }
        internal override JsonObject Provenance => provenance.DeepClone().AsObject();
        internal override JsonObject LocalOrigin => origin.DeepClone().AsObject();

        internal NativeCollectionMediaSource(TelefonStore store, string peerId, object connectionOwner,
            DeviceFileNativeDirectory root, DeviceFileNativeDirectory.CollectionSource file, string name,
            DeviceTransferBinding sending, JsonObject provenance, JsonObject origin)
        {
            Store = store; PeerId = peerId; ConnectionOwner = connectionOwner; this.root = root; this.file = file;
            path = name; senderId = sending.SenderId; receiverId = sending.ReceiverId;
            this.provenance = provenance.DeepClone().AsObject(); this.origin = origin.DeepClone().AsObject();
        }

        internal override void Require() => file.Require();
        internal override byte[] ReadExact(long offset, int count) => file.ReadExact(offset, count);
        internal DeviceFileNativeDirectory.CollectionSignature ObserveCollection() => file.Observe();
        internal NativePreparedMediaSource Freeze() => FreezeCore(false);
        internal NativePreparedMediaSource FreezeCompletedSuccessor() => FreezeCore(true);
        internal NativePreparedMediaSource FreezeNewTypedVideo() => FreezeCore(true, newTypedVideoOnly: true);
        private NativePreparedMediaSource FreezeCore(bool completedSuccessor, bool newTypedVideoOnly = false)
        {
            NativePreparedMediaSource result;
            lock (sourceGate)
            {
                Require();
                if (newTypedVideoOnly && (PrepareManifest().TotalBytes <= 0 || preparedMime != "video/mp4"))
                    throw DeviceFileControl.Error("media_collection_video_original_required");
                if (frozen is null)
                {
                    if (freezeAttempted) throw DeviceFileControl.Error("media_source_original_preparation_required");
                    freezeAttempted = true;
                    frozen = NativePreparedMediaSource.Create(Store, this, completedSuccessor, newTypedVideoOnly);
                }
                result = frozen;
                if (newTypedVideoOnly && !result.NewTypedVideoOnly)
                    throw DeviceFileControl.Error("media_collection_video_original_required");
            }
            result.Require(); return result;
        }

        internal override DeviceFileManifest PrepareManifest()
        {
            lock (sourceGate)
            {
                Require(); if (prepared is not null) return prepared;
                using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                var prefix = new byte[(int)Math.Min(file.Size, NativeMediaContentMime.PrefixBytes)];
                try
                {
                    for (long offset = 0; offset < file.Size;)
                    {
                        var chunk = ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, file.Size - offset));
                        try
                        {
                            digest.AppendData(chunk);
                            if (offset < prefix.Length) chunk.AsSpan(0, Math.Min(chunk.Length, prefix.Length - (int)offset)).CopyTo(prefix.AsSpan((int)offset));
                            offset += chunk.Length;
                        }
                        finally { CryptographicOperations.ZeroMemory(chunk); }
                    }
                    Require(); preparedMime = NativeMediaContentMime.IdentifyCollection(prefix, file.Size, provenance["media_type"]!.GetValue<string>());
                    var hash = Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant();
                    prepared = new(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), senderId, receiverId,
                        [new DeviceManifestFile(Guid.NewGuid().ToString("N"), path, file.Size, hash)], file.Size);
                    Require(); return prepared;
                }
                finally { CryptographicOperations.ZeroMemory(prefix); }
            }
        }

        internal override JsonObject PreparedOriginalReferences()
        {
            lock (sourceGate)
            {
                Require(); if (prepared is null) throw DeviceFileControl.Error("media_source_prepared_manifest_required");
                return new(); // Only an admitted entire_collection owner reaches this type.
            }
        }

        public override void Dispose()
        {
            lock (sourceGate) { try { file.Dispose(); } finally { root.Dispose(); } }
        }
    }

    // Deny-only membership check. A demonstrated phone mapping may be handled
    // only by its original mapping owner, never relabelled as a new PC origin.
    private void RequireIndependentCollectionMember(string peerId, DeviceFileNativeDirectory.Identity identity)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            RequireIndependentRecoveryMember(db, identity);
            var expected = NativeMediaReceiveJob.NativeIdentity(identity);
            if (ReceiveHeads(db, null, scope).Any(head => head.Body["files"]!.AsArray().OfType<JsonObject>()
                .Any(member => JsonNode.DeepEquals(member["identity"], expected))))
                throw DeviceFileControl.Error("media_collection_existing_mapping_required");
        }
    }

    internal NativeCollectionMediaSource OpenNativeCollectionMediaSource(string peerId, string mediaType, string rootId, string rootVersion,
        DeviceFileNativeDirectory.CollectionMember member, DeviceTransferBinding sending, NativeMediaBookPermit book,
        JsonObject sharedIntent, Action requireConnection, object connectionOwner)
    {
        MediaDestinationKind(mediaType);
        var intent = sharedIntent.DeepClone().AsObject();
        if (!MediaSyncSettings.TransferRequestedFor(intent, mediaType, toPhone: true) ||
            MediaSyncSettings.Effective(intent)["collection_mode"]!.GetValue<string>() != "entire_collection")
            throw DeviceFileControl.Error("media_collection_current_entire_sending_intent_required");
        var scope = MediaPreferenceScope(peerId); var consent = ReadNativeMediaSendConsent(peerId);
        if (!consent.Explicit || !(mediaType == "images" ? consent.Photos : consent.Videos))
            throw DeviceFileControl.Error("media_source_local_sending_consent_required");
        var selection = NativeMediaCollectionRoots(peerId).SingleOrDefault(item => item.Id == rootId && item.Version == rootVersion && item.MediaType == mediaType)
            ?? throw DeviceFileControl.Error("media_collection_original_root_required");
        if (selection.CreationFileTime is null) throw DeviceFileControl.Error("media_collection_root_generation_required");
        if (sending.SenderId != scope.LocalId || sending.SenderIdentitySha256 != scope.LocalKey || sending.ReceiverId != scope.PeerId || sending.ReceiverIdentitySha256 != scope.PeerKey)
            throw DeviceFileControl.Error("media_source_current_sending_scope_required");
        DeviceFileNativeDirectory? root = null; DeviceFileNativeDirectory.CollectionSource? file = null;
        var retired = false;
        void Current()
        {
            try
            {
                if (retired) throw DeviceFileControl.Error("media_collection_source_retired");
                book.Require(); requireConnection(); RequireNativeMediaStorageKey();
                if (ReadNativeMediaSendConsent(peerId) != consent || MediaPreferenceScope(peerId) != scope ||
                    NativeMediaCollectionRoots(peerId).SingleOrDefault(item => item.Id == rootId) != selection || !JsonNode.DeepEquals(sharedIntent, intent))
                    throw DeviceFileControl.Error("media_collection_original_sending_owner_changed");
                if (root is not null && (root.CurrentCollectionSourceIdentity() != selection.Identity || root.CurrentCollectionCreationFileTime() != selection.CreationFileTime))
                    throw DeviceFileControl.Error("media_collection_root_generation_changed");
                RequireIndependentCollectionMember(peerId, member.Identity);
                book.Require(); requireConnection();
            }
            catch { retired = true; throw; }
        }
        try
        {
            Current(); root = selection.OpenNative(); file = root.OpenCollectionMember(member, Current);
            if (mediaType == "images" && MediaSyncSettings.Effective(intent)["photos_only"]!.GetValue<bool>() && !file.MatchesPhotoMetadata())
                throw DeviceFileControl.Error("media_source_photo_metadata_required");
            var provenance = new JsonObject { ["collection_root"] = rootId, ["collection_version"] = rootVersion,
                ["book_version"] = book.Version, ["media_type"] = mediaType, ["settings"] = intent.DeepClone(), ["sending_binding"] = sending.Snapshot() };
            var origin = new JsonObject { ["format"] = 2, ["root_id"] = rootId, ["root_version"] = rootVersion,
                ["root_identity"] = NativeMediaReceiveJob.NativeIdentity(selection.Identity),
                ["root_creation_filetime"] = selection.CreationFileTime.Value.ToString("x16", System.Globalization.CultureInfo.InvariantCulture),
                ["file_identity"] = NativeMediaReceiveJob.NativeIdentity(member.Identity),
                ["file_creation_filetime"] = member.CreationFileTime.ToString("x16", System.Globalization.CultureInfo.InvariantCulture),
                ["relative_path"] = string.Join('/', member.Parents.Select(parent => parent.Name).Append(member.Name)) };
            ValidateLocalCollectionOrigin(origin, provenance); Current();
            return new(this, peerId, connectionOwner, root, file, member.Name, sending, provenance, origin);
        }
        catch { retired = true; file?.Dispose(); root?.Dispose(); throw; }
    }
}

internal sealed partial class TelefonConnection
{
    // Original explicit membership only. This owner does not grant SEND and
    // never substitutes an inventory or Saved receipt for per-file source END.
    private sealed class NativeCollectionMediaPass : IDisposable
    {
        private sealed record Frame(NativeMediaCollectionRoot Selection, DeviceFileNativeDirectory Root,
            DeviceFileNativeDirectory.CollectionInventory Inventory,
            IReadOnlyDictionary<string, DeviceFileNativeDirectory.CollectionSignature> Signatures);
        private readonly TelefonStore store;
        private readonly string peerId;
        private readonly Action current;
        private readonly CancellationToken token;
        private readonly IReadOnlyList<NativeMediaCollectionRoot> catalog;
        private readonly List<Frame> frames = [];
        private readonly Dictionary<DeviceFileNativeDirectory.Identity, DeviceFileNativeDirectory.CollectionSignature> checkedMappings = [];
        private readonly HashSet<TelefonStore.NativeMappedMediaSource> admittedMappings = [];
        private readonly Action localCurrent;
        private readonly object connectionOwner;
        private bool closed;

        internal NativeCollectionMediaPass(TelefonStore store, string peerId, string mediaType, Action current, CancellationToken token, object connectionOwner,
            NativeMediaSendConsent? expectedSend = null, IReadOnlyList<NativeMediaCollectionRoot>? expectedRoots = null)
        {
            this.store = store; this.peerId = peerId; this.current = current; this.token = token;
            this.connectionOwner = connectionOwner;
            var preferences = expectedSend is null ? store.ReadNativeMediaPreferences(peerId) : null;
            var consent = expectedSend ?? store.ReadNativeMediaSendConsent(peerId);
            localCurrent = () =>
            {
                if (preferences is not null && store.ReadNativeMediaPreferences(peerId) != preferences ||
                    store.ReadNativeMediaSendConsent(peerId) != consent ||
                    !consent.Explicit || !(mediaType == "video" ? consent.Videos : consent.Photos))
                    throw DeviceFileControl.Error("media_source_local_consent_required");
            };
            catalog = store.NativeMediaCollectionRoots(peerId);
            try
            {
                Require(); var selected = catalog.Where(root => root.MediaType == mediaType).ToArray();
                if (selected.Length == 0) throw DeviceFileControl.Error("media_collection_explicit_source_roots_required");
                if (expectedRoots is not null && !selected.SequenceEqual(expectedRoots))
                    throw DeviceFileControl.Error("media_collection_original_catalog_changed");
                var identities = new HashSet<DeviceFileNativeDirectory.Identity>();
                foreach (var selection in selected)
                {
                    var root = selection.OpenNative();
                    try
                    {
                        var inventory = root.InventoryCollection(Require, token);
                        if (inventory.NeedsReview) throw DeviceFileControl.Error("media_collection_incomplete_native_inventory");
                        var signatures = new Dictionary<string, DeviceFileNativeDirectory.CollectionSignature>(StringComparer.OrdinalIgnoreCase);
                        foreach (var member in inventory.Members)
                        {
                            if (!identities.Add(member.Identity)) throw DeviceFileControl.Error("media_collection_ambiguous_identity");
                            if (identities.Count > 4096) throw DeviceFileControl.Error("media_collection_inventory_bound");
                            using var file = root.OpenCollectionMember(member, Require);
                            signatures.Add(Key(member), file.Observe());
                        }
                        frames.Add(new(selection, root, inventory, signatures));
                    }
                    catch { root.Dispose(); throw; }
                }
                Require();
            }
            catch { Dispose(); throw; }
        }

        private static string Key(DeviceFileNativeDirectory.CollectionMember member) => string.Join('\\', member.Parents.Select(parent => parent.Name).Append(member.Name));
        internal void Require()
        {
            token.ThrowIfCancellationRequested();
            if (closed) throw DeviceFileControl.Error("media_collection_original_pass_required");
            current(); localCurrent();
        }
        private void CatalogCurrent()
        {
            Require();
            if (!store.NativeMediaCollectionRoots(peerId).SequenceEqual(catalog))
                throw DeviceFileControl.Error("media_collection_original_catalog_changed");
        }
        private void Check(Frame frame, DeviceFileNativeDirectory.CollectionMember member)
        {
            CatalogCurrent();
            using var file = frame.Root.OpenCollectionMember(member, Require);
            if (!frame.Signatures.TryGetValue(Key(member), out var signature) || file.Observe() != signature)
                throw DeviceFileControl.Error("media_collection_original_inventory_changed");
        }
        internal IEnumerable<(NativeMediaCollectionRoot Selection, DeviceFileNativeDirectory.CollectionMember Member)> Members()
        {
            foreach (var frame in frames)
                foreach (var member in frame.Inventory.Members)
                {
                    Check(frame, member);
                    if (checkedMappings.TryGetValue(member.Identity, out var observation))
                    {
                        if (frame.Signatures[Key(member)] != observation)
                            throw DeviceFileControl.Error("media_collection_original_inventory_changed");
                        continue; // Already actually read, never relabelled or counted twice.
                    }
                    yield return (frame.Selection, member);
                }
        }
        internal IEnumerable<(NativeMediaCollectionRoot Selection, IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> Members)> ImageBatches(bool photosOnly)
        {
            foreach (var frame in frames)
            {
                var selected = new List<DeviceFileNativeDirectory.CollectionMember>();
                foreach (var member in frame.Inventory.Members)
                {
                    CatalogCurrent();
                    using var file = frame.Root.OpenCollectionMember(member, Require);
                    if (file.Observe() != frame.Signatures[Key(member)])
                        throw DeviceFileControl.Error("media_collection_original_inventory_changed");
                    var prefix = new byte[(int)Math.Min(member.Size, NativeMediaContentMime.PrefixBytes)];
                    try
                    {
                        for (var offset = 0; offset < prefix.Length;)
                        {
                            var chunk = file.ReadExact(offset, Math.Min(DeviceFileManifest.ChunkBytes, prefix.Length - offset));
                            try { chunk.CopyTo(prefix, offset); offset += chunk.Length; }
                            finally { CryptographicOperations.ZeroMemory(chunk); }
                        }
                        try { _ = NativeMediaContentMime.IdentifyCollection(prefix, member.Size, "images"); }
                        catch (InvalidDataException error) when (error.Message == "media_collection_known_other_type") { continue; }
                        if (!photosOnly || file.MatchesPhotoMetadata()) selected.Add(member);
                    }
                    finally { CryptographicOperations.ZeroMemory(prefix); }
                }
                if (selected.Count > DeviceFileManifest.MaxFiles || selected.Sum(member => member.Size) > DeviceFileManifest.MaxTotalBytes)
                    throw DeviceFileControl.Error("media_source_batch_original_members_required");
                if (selected.Count != 0) yield return (frame.Selection, selected.AsReadOnly());
            }
        }
        internal void AdmitMapping(TelefonStore.NativeMappedMediaSource source)
        {
            Require();
            if (!ReferenceEquals(source.Store, store) || !ReferenceEquals(source.ConnectionOwner, connectionOwner) || source.PeerId != peerId)
                throw DeviceFileControl.Error("media_collection_original_mapping_observation_required");
            source.Require();
            if (!admittedMappings.Add(source)) throw DeviceFileControl.Error("media_collection_original_mapping_observation_required");
        }
        internal void NoteCheckedMapping(TelefonStore.NativeMappedMediaSource source)
        {
            Require();
            if (!admittedMappings.Remove(source)) throw DeviceFileControl.Error("media_collection_original_mapping_observation_required");
            var observation = source.ComparedCollectionObservation;
            if (!checkedMappings.TryAdd(observation.Identity, observation))
                throw DeviceFileControl.Error("media_collection_ambiguous_mapped_identity");
        }
        internal void CheckOpened(NativeMediaCollectionRoot selection, DeviceFileNativeDirectory.CollectionMember member,
            DeviceFileNativeDirectory.CollectionSignature signature)
        {
            CatalogCurrent();
            var frame = frames.Single(value => ReferenceEquals(value.Selection, selection));
            if (!frame.Inventory.Members.Any(value => ReferenceEquals(value, member)) || frame.Signatures[Key(member)] != signature)
                throw DeviceFileControl.Error("media_collection_original_inventory_changed");
        }
        internal void Finish()
        {
            CatalogCurrent();
            foreach (var frame in frames)
            {
                var inventory = frame.Root.InventoryCollection(Require, token);
                if (inventory.NeedsReview || inventory.Members.Count != frame.Inventory.Members.Count)
                    throw DeviceFileControl.Error("media_collection_original_inventory_changed");
                foreach (var member in inventory.Members)
                {
                    var original = frame.Inventory.Members.SingleOrDefault(value => Key(value).Equals(Key(member), StringComparison.OrdinalIgnoreCase));
                    if (original is null || original.Identity != member.Identity || original.Size != member.Size ||
                        original.CreationFileTime != member.CreationFileTime || !original.Parents.SequenceEqual(member.Parents))
                        throw DeviceFileControl.Error("media_collection_original_inventory_changed");
                    Check(frame, member);
                }
            }
            CatalogCurrent();
        }
        public void Dispose()
        {
            closed = true;
            Exception? failure = null;
            foreach (var frame in frames)
                try { frame.Root.Dispose(); } catch (Exception error) { failure ??= error; }
            if (failure is not null) throw failure;
        }
    }

    internal async Task SynchronizeOriginalPcImageCollectionAsync(JsonObject intent, NativeMediaBookPermit book,
        Action requireIntent, Func<bool> agreement, NativeMediaSendConsent expectedSend,
        IReadOnlyList<NativeMediaCollectionRoot> expectedRoots, CancellationToken token)
    {
        var controls = RequireNativeFileControls();
        var epoch = controls.Binding(new string('0', 64), senderIsLocal: true)
            ?? throw DeviceFileControl.Error("media_source_positive_sending_grant_required");
        var position = controls.RemoteControlWitness();
        if (position is null || controls.Binding(epoch.DestinationToken, senderIsLocal: true) != epoch)
            throw DeviceFileControl.Error("media_collection_original_send_binding_required");
        void Current()
        {
            requireIntent();
            // This callback also runs under the protected source store. A
            // control-session callback would reacquire that store in reverse order.
            // The wire sender independently checks the positive binding.
            if (!agreement() || !ReferenceEquals(Volatile.Read(ref fileControls), controls) ||
                !controls.NativeMetadataPositionUnchanged(position))
                throw DeviceFileControl.Error("media_collection_original_send_binding_required");
        }
        using var collection = new NativeCollectionMediaPass(store, peer.Id, "images", Current, token, this, expectedSend, expectedRoots);
        var photosOnly = MediaSyncSettings.Effective(intent)["photos_only"]!.GetValue<bool>();
        foreach (var (selection, members) in collection.ImageBatches(photosOnly))
        {
            var tokenForRoot = DeviceFileControl.Digest("magnolie-media-collection-member-v1\0",
                new JsonObject { ["root_id"] = selection.Id, ["root_version"] = selection.Version });
            var binding = epoch with { DestinationToken = tokenForRoot };
            using var original = store.OpenNativeCollectionMediaBatch(peer.Id, "images", selection.Id, selection.Version,
                members, binding, book, intent, Current, this, expectedSend: expectedSend);
            TelefonStore.NativePreparedMediaBatch cache;
            try { cache = original.FreezeCache(); }
            catch (InvalidDataException error) when (error.Message == "media_source_batch_latest_payload_already_sent")
            { Current(); continue; }
            using (cache)
            using (var output = DeviceFileNativeDirectory.OpenExistingForReceive(selection.NativePath))
            {
                bool TargetCurrent() => output.CurrentReceiveIdentity() == selection.Identity &&
                    output.CurrentReceiveCreationFileTime() == selection.CreationFileTime &&
                    string.Equals(output.VolumePath, selection.VolumePath, StringComparison.OrdinalIgnoreCase);
                bool PermitAfterDrain() { Current(); return TargetCurrent(); }
                var backups = store.SaveNativePreparedPcBatchBackups(cache, output, TargetCurrent, createBackup: true);
                await SendConnectedMediaBatchToSourceEndAsync(cache, output, backups, PermitAfterDrain, agreement, token);
            }
        }
        collection.Finish();
    }

    internal async Task SynchronizeOriginalPcVideoCollectionAsync(JsonObject intent, NativeMediaBookPermit book,
        Action requireIntent, Func<bool> agreement, NativeMediaSendConsent expectedSend,
        IReadOnlyList<NativeMediaCollectionRoot> expectedRoots, CancellationToken token)
    {
        var controls = RequireNativeFileControls();
        var binding = controls.Binding(new string('0', 64), senderIsLocal: true)
            ?? throw DeviceFileControl.Error("media_source_positive_sending_grant_required");
        var position = controls.RemoteControlWitness();
        if (position is null || controls.Binding(binding.DestinationToken, senderIsLocal: true) != binding)
            throw DeviceFileControl.Error("media_collection_original_send_binding_required");
        void Current()
        {
            requireIntent();
            if (!agreement() || !ReferenceEquals(Volatile.Read(ref fileControls), controls) ||
                !controls.NativeMetadataPositionUnchanged(position))
                throw DeviceFileControl.Error("media_collection_original_send_binding_required");
        }
        Current();
        var plan = store.NativeMappedMediaCandidates(peer.Id, "video");
        if (plan.NeedsReview || plan.Candidates.Count != 0)
            throw DeviceFileControl.Error("media_source_private_mapped_return_unavailable");
        using var collection = new NativeCollectionMediaPass(store, peer.Id, "video", Current, token, this, expectedSend, expectedRoots);
        foreach (var (selection, member) in collection.Members())
        {
            var tokenForRoot = DeviceFileControl.Digest("magnolie-media-collection-member-v1\0",
                new JsonObject { ["root_id"] = selection.Id, ["root_version"] = selection.Version });
            using var source = store.OpenNativeCollectionMediaSource(peer.Id, "video", selection.Id, selection.Version,
                member, binding with { DestinationToken = tokenForRoot }, book, intent, collection.Require, this);
            collection.CheckOpened(selection, member, source.ObserveCollection());
            TelefonStore.NativePreparedMediaSource cache;
            try { cache = source.FreezeNewTypedVideo(); }
            catch (InvalidDataException error) when (error.Message is "media_collection_known_other_type" or
                "media_source_cache_latest_payload_already_sent") { Current(); continue; }
            using (cache) await SendNativeMappedMediaSourceToSourceEndAsync(cache, token);
            Current();
        }
        collection.Finish();
    }

    internal TelefonStore.NativeCollectionMediaSource OpenNativeCollectionMediaSource(string mediaType, string rootId, string rootVersion,
        DeviceFileNativeDirectory.CollectionMember member, string phoneDestinationToken, NativeMediaBookPermit book, Action? requireCurrent = null)
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
        Current(); return store.OpenNativeCollectionMediaSource(peer.Id, mediaType, rootId, rootVersion, member, sending, book, intent, Current, this);
    }
}
