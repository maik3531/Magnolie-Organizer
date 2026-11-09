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
        internal NativePreparedMediaSource Freeze() => FreezeCore(false);
        internal NativePreparedMediaSource FreezeCompletedSuccessor() => FreezeCore(true);
        private NativePreparedMediaSource FreezeCore(bool completedSuccessor)
        {
            NativePreparedMediaSource result;
            lock (sourceGate)
            {
                Require();
                if (frozen is null)
                {
                    if (freezeAttempted) throw DeviceFileControl.Error("media_source_original_preparation_required");
                    freezeAttempted = true;
                    frozen = NativePreparedMediaSource.Create(Store, this, completedSuccessor);
                }
                result = frozen;
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
                    Require(); _ = NativeMediaContentMime.Identify(prefix, file.Size, provenance["media_type"]!.GetValue<string>());
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
    internal TelefonStore.NativeCollectionMediaSource OpenNativeCollectionMediaSource(string mediaType, string rootId, string rootVersion,
        DeviceFileNativeDirectory.CollectionMember member, string phoneDestinationToken, NativeMediaBookPermit book)
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
        Current(); return store.OpenNativeCollectionMediaSource(peer.Id, mediaType, rootId, rootVersion, member, sending, book, intent, Current, this);
    }
}
