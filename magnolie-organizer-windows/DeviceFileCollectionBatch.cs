using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonStore
{
    // Actual original descriptors only (Refs #330). Deliberately NOT a
    // NativeMediaSourceOwner: the old one-file cache/sender cannot adopt this.
    internal sealed class NativeCollectionMediaBatch : IDisposable
    {
        internal sealed record MemberObservation(string FileId, string Path, long Size, JsonObject Origin)
        {
            internal bool GrantsReadAuthority => false;
            internal bool IsSavedReceipt => false;
            internal bool PermitsRetirement => false;
        }
        private sealed record Held(string FileId, string Path, DeviceFileNativeDirectory.CollectionSource File, JsonObject Origin);
        private readonly object gate = new();
        private readonly Dictionary<string, Held> files = new(StringComparer.Ordinal);
        private readonly Action current, retire, authority;
        private readonly DeviceFileNativeDirectory root;
        private readonly JsonObject provenance;
        private readonly string senderId, receiverId, transferId = Guid.NewGuid().ToString("N");
        private readonly Dictionary<string, string> mimeTypes = new(StringComparer.Ordinal);
        private int closed;
        private bool admitted;
        private DeviceFileManifest? manifest;
        private bool freezeAttempted;
        private NativePreparedMediaBatch? frozen;
        private NativeBatchSourceRetirement? retirement;
        internal string Id { get; } = Guid.NewGuid().ToString("N");
        internal TelefonStore Store { get; }
        internal string PeerId { get; }
        internal object ConnectionOwner { get; }

        internal NativeCollectionMediaBatch(TelefonStore store, string peerId, object connectionOwner,
            DeviceFileNativeDirectory root, IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> members,
            DeviceTransferBinding sending, JsonObject provenance, NativeMediaCollectionRoot selection,
            Action current, Action retire, Action authority, Action<NativeCollectionMediaBatch, string>? boundary)
        {
            Store = store; PeerId = peerId; ConnectionOwner = connectionOwner; this.root = root;
            this.current = current; this.retire = retire; this.authority = authority; this.provenance = provenance.DeepClone().AsObject();
            senderId = sending.SenderId; receiverId = sending.ReceiverId;
            try
            {
                lock (gate)
                {
                    current();
                    foreach (var member in members)
                    {
                        var path = string.Join('/', member.Parents.Select(parent => parent.Name).Append(member.Name));
                        var file = root.OpenCollectionMember(member, current);
                        try
                        {
                            var origin = new JsonObject { ["format"] = 2, ["root_id"] = selection.Id, ["root_version"] = selection.Version,
                                ["root_identity"] = NativeMediaReceiveJob.NativeIdentity(selection.Identity),
                                ["root_creation_filetime"] = selection.CreationFileTime!.Value.ToString("x16", System.Globalization.CultureInfo.InvariantCulture),
                                ["file_identity"] = NativeMediaReceiveJob.NativeIdentity(member.Identity),
                                ["file_creation_filetime"] = member.CreationFileTime.ToString("x16", System.Globalization.CultureInfo.InvariantCulture),
                                ["relative_path"] = path };
                            ValidateLocalCollectionOrigin(origin, provenance);
                            var id = Guid.NewGuid().ToString("N");
                            files.Add(id, new(id, path, file, origin));
                        }
                        catch { file.Dispose(); throw; }
                        boundary?.Invoke(this, "source_batch_original_open"); RequireAll();
                    }
                    // All original handles remain owned through every native
                    // media check and final revalidation of earlier members.
                    var kind = provenance["media_type"]!.GetValue<string>();
                    foreach (var member in files.Values)
                    {
                        var prefix = new byte[(int)Math.Min(member.File.Size, NativeMediaContentMime.PrefixBytes)];
                        try
                        {
                            for (var offset = 0; offset < prefix.Length;)
                            {
                                var chunk = member.File.ReadExact(offset, Math.Min(DeviceFileManifest.ChunkBytes, prefix.Length - offset));
                                try { chunk.CopyTo(prefix, offset); offset += chunk.Length; }
                                finally { CryptographicOperations.ZeroMemory(chunk); }
                            }
                            mimeTypes.Add(member.FileId, NativeMediaContentMime.IdentifyCollection(prefix, member.File.Size, kind));
                        }
                        finally { CryptographicOperations.ZeroMemory(prefix); }
                        if (kind == "images" && MediaSyncSettings.Effective(provenance["settings"]!.AsObject())["photos_only"]!.GetValue<bool>() &&
                            !member.File.MatchesPhotoMetadata()) throw DeviceFileControl.Error("media_source_photo_metadata_required");
                    }
                    RequireAll(); admitted = true;
                }
            }
            catch { Dispose(); throw; }
        }

        private void RequireAdmitted()
        {
            if (!admitted) throw DeviceFileControl.Error("media_source_batch_all_members_not_admitted");
        }

        private void RequireAll()
        {
            if (Volatile.Read(ref closed) != 0) throw DeviceFileControl.Error("media_collection_source_retired");
            current();
            foreach (var file in files.Values) file.File.Require();
            current();
        }

        internal void Require()
        {
            lock (gate)
            {
                RequireAdmitted();
                try { RequireAll(); }
                catch { RetireAndClose(); throw; }
            }
        }


        internal IReadOnlyList<MemberObservation> Observe()
        {
            lock (gate)
            {
                Require();
                return Array.AsReadOnly(files.Values.Select(file =>
                    new MemberObservation(file.FileId, file.Path, file.File.Size, file.Origin.DeepClone().AsObject())).ToArray());
            }
        }

        internal JsonObject Provenance { get { lock (gate) { Require(); return provenance.DeepClone().AsObject(); } } }
        internal JsonObject OriginalOrigins
        {
            get { lock (gate) { Require(); var result = new JsonObject(); foreach (var file in files.Values) result[file.FileId] = file.Origin.DeepClone(); return result; } }
        }
        internal IReadOnlyDictionary<string, string> MimeTypes
        {
            get { lock (gate) { Require(); return new System.Collections.ObjectModel.ReadOnlyDictionary<string, string>(new Dictionary<string, string>(mimeTypes, StringComparer.Ordinal)); } }
        }

        internal byte[] ReadChunk(string fileId, int index)
        {
            lock (gate)
            {
                RequireAdmitted();
                byte[]? bytes = null;
                try
                {
                    RequireAll();
                    if (string.IsNullOrEmpty(fileId) || index < 0 || !files.TryGetValue(fileId, out var file) || (long)index * DeviceFileManifest.ChunkBytes >= file.File.Size)
                        throw DeviceFileControl.Error("media_source_batch_invalid_chunk");
                    var offset = (long)index * DeviceFileManifest.ChunkBytes;
                    bytes = file.File.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, file.File.Size - offset));
                    RequireAll(); return bytes;
                }
                catch
                {
                    if (bytes is not null) CryptographicOperations.ZeroMemory(bytes);
                    RetireAndClose(); throw;
                }
            }
        }

        internal DeviceFileManifest PrepareManifest()
        {
            lock (gate)
            {
                Require();
                if (manifest is not null) return manifest;
                try
                {
                    var prepared = new List<DeviceManifestFile>();
                    foreach (var file in files.Values)
                    {
                        using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                        for (var index = 0; (long)index * DeviceFileManifest.ChunkBytes < file.File.Size; index++)
                        {
                            var chunk = ReadChunk(file.FileId, index);
                            try { digest.AppendData(chunk); }
                            finally { CryptographicOperations.ZeroMemory(chunk); }
                        }
                        prepared.Add(new(file.FileId, file.Path, file.File.Size, Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant()));
                    }
                    RequireAll();
                    manifest = new(transferId, Id, senderId, receiverId, prepared, prepared.Sum(file => file.Size));
                    return manifest; // Metadata only: no cache/job/offer/receipt or retirement permission.
                }
                catch { RetireAndClose(); throw; }
            }
        }

        internal NativePreparedMediaBatch FreezeCache()
        {
            NativePreparedMediaBatch result;
            lock (gate)
            {
                Require();
                if (frozen is not null) result = frozen;
                else
                {
                    if (freezeAttempted) throw DeviceFileControl.Error("media_source_cache_original_preparation_required");
                    freezeAttempted = true;
                    try { result = frozen = NativePreparedMediaBatch.Create(this); }
                    catch { RetireAndClose(); throw; }
                }
            }
            result.Require(); return result; // Never invert published cacheGate -> original gate.
        }

        internal NativePreparedMediaBatch? RecoverSavedCache()
        {
            lock (gate)
            {
                Require();
                if (freezeAttempted) throw DeviceFileControl.Error("media_source_cache_original_preparation_required");
                try
                {
                    var attached = NativePreparedMediaBatch.AttachSaved(this);
                    if (attached is not null)
                    {
                        freezeAttempted = true;
                        frozen = attached;
                    }
                    return attached;
                }
                catch { RetireAndClose(); throw; }
            }
        }

        internal void BindRetirementDrain(NativeBatchSourceRetirement owner)
        {
            lock (gate)
            {
                Require();
                if (retirement is not null || !owner.PermitsOriginalDrain(this))
                    throw DeviceFileControl.Error("media_source_batch_original_drain_owner_required");
                retirement = owner;
            }
        }

        internal void RunRetirementScope(NativeBatchSourceRetirement owner)
        {
            lock (gate)
            {
                Require();
                if (!owner.PermitsLocalScopeEntry(this)) throw DeviceFileControl.Error("media_source_batch_original_drain_owner_required");
                owner.RunProtectedLocalScope();
            }
        }

        internal void RequireRetirementAuthority(NativeBatchSourceRetirement owner)
        {
            lock (gate)
            {
                if (!ReferenceEquals(retirement, owner) || !owner.PermitsEndedAuthority(this) || Volatile.Read(ref closed) == 0)
                    throw DeviceFileControl.Error("media_source_batch_original_drain_owner_required");
                // Native book/consent/intent/control/catalog identity ONLY.
                // Original file handles stay closed; this can never READ.
                authority();
            }
        }

        private void RetireAndClose()
        {
            Interlocked.Exchange(ref closed, 1); retire();
            Exception? failure = null;
            foreach (var file in files.Values.Reverse())
                try { file.File.Dispose(); } catch (Exception error) { failure ??= error; }
            try { root.Dispose(); } catch (Exception error) { failure ??= error; }
            if (failure is not null) throw failure;
        }

        public void Dispose()
        {
            Interlocked.Exchange(ref closed, 1); retire();
            NativePreparedMediaBatch? cache;
            lock (gate)
            {
                cache = frozen;
                if (cache is null) RetireAndClose();
            }
            // Never take endGate/cacheGate underneath the original gate. A
            // public source close also drains its actual published cache.
            cache?.Dispose();
        }

        internal void CloseOriginalsForCache(NativePreparedMediaBatch owner)
        {
            lock (gate)
            {
                if (!owner.HasOriginalSource(this) || frozen is not null && !ReferenceEquals(frozen, owner))
                    throw DeviceFileControl.Error("media_source_batch_original_drain_owner_required");
                RetireAndClose();
            }
        }

        internal static DeviceFileNativeDirectory.CollectionMember[] CopyValidatedMembers(IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> input)
        {
            // Deny-only metadata checks. Copies never confer native READ, and
            // the actual constructor still opens/verifies every original FD.
            if (input is null || input.Count is < 1 or > DeviceFileManifest.MaxFiles ||
                input.Any(member => member is null || member.Parents is null || member.Parents.Count > 16 ||
                    member.Parents.Any(parent => parent is null || parent.Identity is null || parent.CreationFileTime == 0) || member.Identity is null || member.CreationFileTime == 0 ||
                    member.Size is < 1 or > DeviceFileManifest.MaxFileBytes))
                throw DeviceFileControl.Error("media_source_batch_original_members_required");
            var members = input.Select(member => member with { Parents = Array.AsReadOnly(member.Parents.ToArray()) }).ToArray();
            if (members.Length is < 1 or > DeviceFileManifest.MaxFiles || members.Sum(member => member.Size) > DeviceFileManifest.MaxTotalBytes ||
                members.Select(member => member.Identity).Distinct().Count() != members.Length)
                throw DeviceFileControl.Error("media_source_batch_original_members_required");
            var paths = members.Select(member => string.Join('/', member.Parents.Select(parent => parent.Name).Append(member.Name))).ToArray();
            if (paths.Any(path => !DeviceFileManifest.PortablePath(path))) throw DeviceFileControl.Error("media_source_batch_original_paths_required");
            for (var first = 0; first < paths.Length; first++)
                for (var second = first + 1; second < paths.Length; second++)
                    if (DeviceFileManifest.CollidingPaths(paths[first], paths[second])) throw DeviceFileControl.Error("media_source_batch_original_paths_required");
            return members;
        }
    }

    private void RequireIndependentCollectionMembers(string peerId, IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> members)
    {
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open();
            var known = ReceiveHeads(db, null, scope).SelectMany(head => head.Body["files"]!.AsArray().OfType<JsonObject>())
                .Select(member => member["identity"]).ToArray();
            foreach (var member in members)
            {
                RequireIndependentRecoveryMember(db, member.Identity);
                if (known.Any(identity => JsonNode.DeepEquals(identity, NativeMediaReceiveJob.NativeIdentity(member.Identity))))
                    throw DeviceFileControl.Error("media_collection_existing_mapping_required");
            }
        }
    }

    internal NativeCollectionMediaBatch OpenNativeCollectionMediaBatch(string peerId, string mediaType, string rootId, string rootVersion,
        IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> input, DeviceTransferBinding sending, NativeMediaBookPermit book,
        JsonObject sharedIntent, Action requireConnection, object connectionOwner, Action<NativeCollectionMediaBatch, string>? boundary = null,
        NativeMediaSendConsent? expectedSend = null)
    {
        MediaDestinationKind(mediaType);
        var members = NativeCollectionMediaBatch.CopyValidatedMembers(input);
        var intent = sharedIntent.DeepClone().AsObject();
        if (!MediaSyncSettings.TransferRequestedFor(intent, mediaType, toPhone: true) ||
            MediaSyncSettings.Effective(intent)["collection_mode"]!.GetValue<string>() != "entire_collection")
            throw DeviceFileControl.Error("media_collection_current_entire_sending_intent_required");
        var scope = MediaPreferenceScope(peerId); var consent = ReadNativeMediaSendConsent(peerId);
        if (!consent.Explicit || !(mediaType == "images" ? consent.Photos : consent.Videos) || expectedSend is not null && consent != expectedSend)
            throw DeviceFileControl.Error("media_source_local_sending_consent_required");
        var selection = NativeMediaCollectionRoots(peerId).SingleOrDefault(item => item.Id == rootId && item.Version == rootVersion && item.MediaType == mediaType)
            ?? throw DeviceFileControl.Error("media_collection_original_root_required");
        if (selection.CreationFileTime is null) throw DeviceFileControl.Error("media_collection_root_generation_required");
        if (sending.SenderId != scope.LocalId || sending.SenderIdentitySha256 != scope.LocalKey || sending.ReceiverId != scope.PeerId || sending.ReceiverIdentitySha256 != scope.PeerKey)
            throw DeviceFileControl.Error("media_source_current_sending_scope_required");
        DeviceFileNativeDirectory? root = null; var retired = 0;
        void Retire() => Interlocked.Exchange(ref retired, 1);
        void Guard(bool checkOriginalRoot)
        {
            book.Require(); requireConnection(); RequireNativeMediaStorageKey();
            if (ReadNativeMediaSendConsent(peerId) != consent || MediaPreferenceScope(peerId) != scope ||
                NativeMediaCollectionRoots(peerId).SingleOrDefault(item => item.Id == rootId) != selection || !JsonNode.DeepEquals(sharedIntent, intent))
                throw DeviceFileControl.Error("media_collection_original_sending_owner_changed");
            if (checkOriginalRoot && root is not null && (root.CurrentCollectionSourceIdentity() != selection.Identity || root.CurrentCollectionCreationFileTime() != selection.CreationFileTime))
                throw DeviceFileControl.Error("media_collection_root_generation_changed");
            RequireIndependentCollectionMembers(peerId, members); book.Require(); requireConnection();
        }
        void Authority() => Guard(checkOriginalRoot: false);
        void Current()
        {
            try
            {
                if (Volatile.Read(ref retired) != 0) throw DeviceFileControl.Error("media_collection_source_retired");
                Guard(checkOriginalRoot: true);
            }
            catch { Retire(); throw; }
        }
        try
        {
            Current(); root = selection.OpenNative();
            var provenance = new JsonObject { ["collection_root"] = rootId, ["collection_version"] = rootVersion,
                ["book_version"] = book.Version, ["media_type"] = mediaType, ["settings"] = intent.DeepClone(), ["sending_binding"] = sending.Snapshot() };
            return new(this, peerId, connectionOwner, root, members, sending, provenance, selection, Current, Retire, Authority, boundary);
        }
        catch { Retire(); root?.Dispose(); throw; }
    }
}

internal sealed partial class TelefonConnection
{
    internal TelefonStore.NativeCollectionMediaBatch OpenNativeCollectionMediaBatch(string mediaType, string rootId, string rootVersion,
        IReadOnlyList<DeviceFileNativeDirectory.CollectionMember> members, string phoneDestinationToken, NativeMediaBookPermit book,
        Action? requireCurrent = null, Action<TelefonStore.NativeCollectionMediaBatch, string>? boundary = null)
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
        Current(); return store.OpenNativeCollectionMediaBatch(peer.Id, mediaType, rootId, rootVersion, members, sending, book, intent, Current, this, boundary);
    }
}
