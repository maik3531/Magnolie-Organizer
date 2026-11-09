using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    internal bool NativeMediaUiMetadataAvailable(bool videos = false)
    {
        lock (fileRouteGate) if (disposed || fileRouteFaulted) return false;
        return FileMetadataReady(videos);
    }
    internal bool NativeMediaLegacyActivationAvailable()
        => peer.FilePairingEpoch is null && FileMetadataReady(forLegacyActivation: true);

    internal void ActivateLegacyNativeMediaPairing()
    {
        void Current()
        {
            if (!NativeMediaLegacyActivationAvailable()) throw DeviceFileControl.Error("file_pairing_native_activation_changed");
            lock (fileRouteGate) if (fileControls is not null) throw DeviceFileControl.Error("file_media_native_owner_busy");
        }
        store.InitializeNativeMediaPairing(peer, Current);
        // A new native relationship requires a fresh authenticated channel and
        // fresh metadata receipts. Do not transplant the old channel's proofs.
        Dispose();
    }
    private sealed class NativeMediaUiAuthority(TelefonStore store, TelefonPeer peer, Func<NativeBookSaveState?> savedBook, Func<bool> sharedMatched)
    {
        private readonly object gate = new();
        private readonly object owner = new();
        private DeviceFileGrantState? grants;
        private NativeMediaPreferences? preferences;
        private NativeMediaSendConsent? sending;
        private NativeMediaReceiveConsent? receiving;
        private string? bookSource;
        private bool revoked;

        internal void Choose(bool forSending = false)
        {
            store.RequireNativeMediaStorageKey();
            var receive = store.ReadNativeMediaReceiveConsent(peer.Id);
            var send = store.ReadNativeMediaSendConsent(peer.Id);
            var saved = savedBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
            var choice = store.ReadNativeMediaPreferences(peer.Id);
            if (!choice.PhotosEnabled && !choice.VideosEnabled) throw DeviceFileControl.Error("file_media_native_choice_required");
            var intent = sharedMatched() ? store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey) : null;
            var canSend = intent is not null && send.Explicit &&
                (choice.PhotosEnabled && send.Photos && MediaSyncSettings.TransferRequestedFor(intent, "images", toPhone: true) ||
                 choice.VideosEnabled && send.Videos && MediaSyncSettings.TransferRequestedFor(intent, "video", toPhone: true));
            if (forSending ? !canSend : !receive.Granted)
                throw DeviceFileControl.Error(forSending ? "media_source_local_sending_consent_required" : "file_media_local_receive_consent_required");
            lock (gate)
            {
                if (grants is not null && !revoked && preferences == choice && sending == send && receiving == receive &&
                    grants.SendFiles == canSend && grants.ReceiveFiles == receive.Granted && bookSource == saved.BookSource) return;
                grants = new((grants?.Revision ?? 0) + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), sendFiles: canSend, receiveFiles: receive.Granted);
                preferences = choice; sending = send; receiving = receive; bookSource = saved.BookSource; revoked = false;
            }
        }

        internal NativeLocalFileGrant? Current()
        {
            // Called while the control session may own its lock. NEVER read
            // TelefonStore here (store -> session is the receive-job order).
            // Actual metadata/data IO separately rechecks key/preferences/root;
            // explicit UI preference changes revoke this memory owner below.
            NativeBookSaveState? saved = null;
            try { saved = savedBook(); } catch { }
            lock (gate)
            {
                if (grants is null) return null;
                if (saved?.BookSource != bookSource) revoked = true;
                if (revoked && (grants.SendFiles || grants.ReceiveFiles))
                    grants = new(grants.Revision + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant());
                return new(grants, owner, handlersReady: true);
            }
        }

        internal void Revoke() { lock (gate) revoked = true; }
    }
    private NativeMediaUiAuthority? nativeMediaUiAuthority;
    private readonly string nativeMediaUiStartEpoch = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
    internal string NativeMediaSharedUiVersion(JsonObject intent)
        => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(new JsonObject {
            ["channel"] = nativeMediaUiStartEpoch, ["settings"] = intent.DeepClone() }))).ToLowerInvariant();
    internal void RevokeNativeMediaUiConsent() => nativeMediaUiAuthority?.Revoke();

    internal Action CaptureNativeDestinationContext()
    {
        var controls = Volatile.Read(ref fileControls);
        var position = controls?.RemoteControlWitness();
        KeyValuePair<string, JsonObject>[] receipts;
        lock (fileMetadataGate) receipts = fileMetadataReceipts.ToArray();
        // Deny-only: no Scope(), Packet() or callbackful data agreement under
        // the destination store CAS. Actual metadata readiness is checked outside.
        return () => {
            cancellation.ThrowIfCancellationRequested();
            if (disposed || !ReferenceEquals(controls, Volatile.Read(ref fileControls)) ||
                controls is not null && !controls.NativeMetadataPositionUnchanged(position))
                throw DeviceFileControl.Error("file_destination_native_context_changed");
            lock (fileMetadataGate)
                if (fileMetadataRevoked || fileMetadataReceipts.Count != receipts.Length ||
                    receipts.Any(value => !fileMetadataReceipts.TryGetValue(value.Key, out var actual) || !ReferenceEquals(value.Value, actual)))
                    throw DeviceFileControl.Error("file_destination_native_context_changed");
        };
    }

    internal Action CaptureNativeCollectionFolderContext(string mediaType)
    {
        if (mediaType is not ("images" or "video")) throw DeviceFileControl.Error("media_collection_native_choice_invalid");
        var controls = Volatile.Read(ref fileControls);
        var position = controls?.RemoteControlWitness();
        void Current()
        {
            cancellation.ThrowIfCancellationRequested();
            if (!ReferenceEquals(controls, Volatile.Read(ref fileControls)) ||
                controls is not null && !controls.NativeMetadataPositionUnchanged(position) ||
                !NativeMediaUiMetadataAvailable(mediaType == "video") || !MediaSharedSettingsReady)
                throw DeviceFileControl.Error("media_collection_native_context_changed");
        }
        Current(); return Current;
    }

    internal async Task PrepareNativeMediaUiAsync(Func<NativeBookSaveState?> savedBook, string mediaType, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (!store.ReadNativeMediaReceiveConsent(peer.Id).Granted) throw DeviceFileControl.Error("file_media_local_receive_consent_required");
        var selected = store.ReadNativeMediaDestination(peer.Id, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
        using (var root = selected.OpenNative()) _ = root.CurrentIdentity();
        NativeMediaUiAuthority authority;
        lock (fileRouteGate)
        {
            if (fileControls is not null && nativeMediaUiAuthority is null) throw DeviceFileControl.Error("file_media_native_owner_busy");
            authority = nativeMediaUiAuthority ??= new(store, peer, savedBook, () => MediaSharedSettingsReady);
        }
        authority.Choose();
        bool open; lock (fileRouteGate) open = fileControls is null;
        if (open) _ = OpenNativeFileControls(authority.Current);
        await SendNativeFileControlsAsync();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token, cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(60));
        // Wait for the actual bilateral METADATA echo. A freshly installed
        // phone has its source policy closed: requiring data SendFiles here
        // would prevent the very status/configure commands that enable it.
        // Data reception still independently requires Binding() after configure.
        while (true)
        {
            deadline.Token.ThrowIfCancellationRequested();
            var current = authority.Current();
            if (current?.Grants.ReceiveFiles != true) throw DeviceFileControl.Error("file_media_native_choice_changed");
            var destination = store.ReadNativeMediaDestination(peer.Id, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
            bool ready;
            await fileControlIo.WaitAsync(deadline.Token);
            try
            {
                var controls = RequireNativeFileControls();
                try
                {
                    var ticket = controls.ReceiverCommandTicket();
                    controls.FinishReceiverCommand(ticket); ready = true;
                }
                catch (InvalidDataException error) when (error.Message == "file_control_receiver_command_not_ready") { ready = false; }
            }
            finally { fileControlIo.Release(); }
            if (ready) break;
            await Task.Delay(100, deadline.Token);
        }
    }

    internal async Task PrepareNativeMediaSendUiAsync(Func<NativeBookSaveState?> savedBook, string mediaType, CancellationToken token)
    {
        var saved = savedBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
        var consent = store.ReadNativeMediaSendConsent(peer.Id);
        if (!consent.Explicit || !(mediaType == "images" ? consent.Photos : mediaType == "video" && consent.Videos))
            throw DeviceFileControl.Error("media_source_local_sending_consent_required");
        var intent = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
        void Current()
        {
            token.ThrowIfCancellationRequested();
            if (savedBook() != saved || store.ReadNativeMediaSendConsent(peer.Id) != consent || !MediaSharedSettingsReady ||
                intent is null || !JsonNode.DeepEquals(store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey), intent) ||
                !MediaSyncSettings.TransferRequestedFor(intent, mediaType, toPhone: true) || !NativeMediaUiMetadataAvailable(videos: mediaType == "video"))
                throw DeviceFileControl.Error("media_source_current_sending_owner_required");
        }
        Current();
        NativeMediaUiAuthority? authority;
        lock (fileRouteGate)
        {
            // Explicit native non-UI compositions retain their existing owner.
            // They still need the exact positive actual bilateral SEND below.
            authority = fileControls is not null && nativeMediaUiAuthority is null ? null
                : nativeMediaUiAuthority ??= new(store, peer, savedBook, () => MediaSharedSettingsReady);
        }
        if (authority is not null)
        {
            authority.Choose(forSending: true);
            bool open; lock (fileRouteGate) open = fileControls is null;
            if (open) _ = OpenNativeFileControls(authority.Current);
            await SendNativeFileControlsAsync();
        }
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token, cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(60));
        while (true)
        {
            deadline.Token.ThrowIfCancellationRequested(); Current();
            await fileControlIo.WaitAsync(deadline.Token);
            bool ready;
            try { ready = RequireNativeFileControls().Binding(new string('0', 64), senderIsLocal: true) is not null; }
            finally { fileControlIo.Release(); }
            if (ready) { Current(); return; }
            await Task.Delay(100, deadline.Token);
        }
    }

    internal void RequireKnownNativeMediaAlbum(string version, string catalog, string album, string mediaType)
    {
        var owner = RequireNativeFileControls();
        if (KnownNativeAlbum(owner, mediaType, version, catalog, album) is null) throw DeviceFileControl.Error("file_media_native_catalog_choice_changed");
    }

    internal async Task AwaitNativeMediaDataAgreementAsync(string mediaType, CancellationToken token, Action? nativeGuard = null)
    {
        var owner = RequireNativeFileControls();
        var preferences = store.ReadNativeMediaPreferences(peer.Id);
        var destination = store.ReadNativeMediaDestination(peer.Id, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
        var authority = nativeMediaUiAuthority ?? throw DeviceFileControl.Error("file_media_native_owner_busy");
        var expected = authority.Current()?.Grants ?? throw DeviceFileControl.Error("file_media_native_choice_changed");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token, cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(60));
        while (true)
        {
            deadline.Token.ThrowIfCancellationRequested(); nativeGuard?.Invoke(); RequireNativeFileControls(owner); store.RequireNativeMediaStorageKey();
            var current = authority.Current();
            if (current is null || !current.Grants.ReceiveFiles || !current.Grants.SamePermission(expected) ||
                store.ReadNativeMediaPreferences(peer.Id) != preferences || store.ReadNativeMediaDestination(peer.Id, mediaType) != destination)
                throw DeviceFileControl.Error("file_media_native_choice_changed");
            if (owner.Binding(destination.DestinationToken) is not null) return;
            await Task.Delay(100, deadline.Token);
        }
    }
}

internal sealed partial class TelefonCoordinator
{
    private int nativeMediaCollectionDialog;

    private string NativeDestinationChoiceVersion(string peerId, string mediaType, TelefonConnection connection)
    {
        var peer = store.LoadPeers().Single(value => value.Id == peerId && value.State == "paired");
        // Local descriptors contain unsigned native IDs, outside the signed
        // protocol integer range. Bind their complete deterministic JSON as
        // opaque text; only the final digest crosses the renderer boundary.
        string Snapshot<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value);
        return connection.NativeMediaSharedUiVersion(new JsonObject {
            ["media_type"] = mediaType, ["book"] = NativeSavedBook()?.BookSource,
            ["peer_key"] = Convert.ToBase64String(peer.PublicKey), ["pairing_epoch"] = peer.FilePairingEpoch,
            ["intent"] = store.ReadNativeMediaSharedSettings(peerId, peer.PublicKey)?.DeepClone(),
            ["preferences"] = Snapshot(store.ReadNativeMediaPreferences(peerId)),
            ["send"] = Snapshot(store.ReadNativeMediaSendConsent(peerId)),
            ["receive"] = Snapshot(store.ReadNativeMediaReceiveConsent(peerId)),
            ["sources"] = Snapshot(store.NativeMediaCollectionRoots(peerId)),
            ["images"] = Snapshot(store.ReadNativeMediaDestination(peerId, "images")),
            ["video"] = Snapshot(store.ReadNativeMediaDestination(peerId, "video")),
            ["image_choices"] = Snapshot(store.ReadNativeMediaDestinationChoices(peerId, "images")),
            ["video_choices"] = Snapshot(store.ReadNativeMediaDestinationChoices(peerId, "video")) });
    }

    internal JsonObject ChooseNativeMediaDestination(string peerId, string mediaType, string version,
        Func<Action, DeviceFileNativeDirectory?> pickNative)
    {
        ArgumentNullException.ThrowIfNull(pickNative);
        if (mediaType is not ("images" or "video")) throw DeviceFileControl.Error("file_media_type_invalid");
        if (Interlocked.CompareExchange(ref nativeMediaCollectionDialog, 1, 0) != 0)
            throw DeviceFileControl.Error("media_collection_native_choice_pending");
        var timer = System.Diagnostics.Stopwatch.StartNew(); var canceled = false;
        try
        {
            var connection = NativeMediaOnlineConnection(peerId);
            var control = connection.CaptureNativeDestinationContext();
            var permit = NativeMediaLocalBookPermit();
            var destination = store.ReadNativeMediaDestination(peerId, mediaType);
            var revoked = false;
            void Current()
            {
                try
                {
                    permit.Require(); control(); store.RequireNativeMediaStorageKey();
                    if (revoked || timer.Elapsed >= TimeSpan.FromSeconds(60) ||
                        !ReferenceEquals(connection, NativeMediaOnlineConnection(peerId)) ||
                        NativeDestinationChoiceVersion(peerId, mediaType, connection) != version)
                        throw DeviceFileControl.Error("file_destination_native_context_changed");
                    if (Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
                }
                catch { revoked = true; throw; }
            }
            void Ready()
            {
                Current();
                if (!connection.NativeMediaUiMetadataAvailable(mediaType == "video"))
                    throw DeviceFileControl.Error("file_media_native_peer_unavailable");
                RequireNativeMediaUiDestinationConsent(peerId);
                Current();
            }
            Ready();
            using var selected = pickNative(Current);
            Ready();
            if (selected is null) canceled = true;
            else store.SetNativeMediaDestination(peerId, mediaType, destination?.Version, selected, Current);
            permit.Require();
        }
        finally { Volatile.Write(ref nativeMediaCollectionDialog, 0); }
        var result = NativeMediaUiStatus(peerId);
        if (canceled) result["canceled"] = true;
        return result;
    }

    internal JsonObject ChooseNativeMediaCollectionFolder(string peerId, string mediaType, string version,
        Func<Action, DeviceFileNativeDirectory?> pickNative)
    {
        ArgumentNullException.ThrowIfNull(pickNative);
        if (Interlocked.CompareExchange(ref nativeMediaCollectionDialog, 1, 0) != 0)
            throw DeviceFileControl.Error("media_collection_native_choice_pending");
        var timer = System.Diagnostics.Stopwatch.StartNew();
        var canceled = false;
        try
        {
            var connection = NativeMediaOnlineConnection(peerId);
            var currentControl = connection.CaptureNativeCollectionFolderContext(mediaType);
            var permit = NativeMediaLocalBookPermit(); permit.Require();
            var peer = store.LoadPeers().Single(value => value.Id == peerId);
            var intent = store.ReadNativeMediaSharedSettings(peerId, peer.PublicKey)
                ?? throw DeviceFileControl.Error("media_collection_current_intent_required");
            var preferences = store.ReadNativeMediaPreferences(peerId);
            var send = store.ReadNativeMediaSendConsent(peerId);
            var receive = store.ReadNativeMediaReceiveConsent(peerId);
            var expectedRoots = store.NativeMediaCollectionRoots(peerId);
            void Current()
            {
                permit.Require(); currentControl();
                if (!ReferenceEquals(connection, NativeMediaOnlineConnection(peerId)) || timer.Elapsed >= TimeSpan.FromSeconds(60) ||
                    connection.NativeMediaSharedUiVersion(intent) != version ||
                    !JsonNode.DeepEquals(intent, store.ReadNativeMediaSharedSettings(peerId, peer.PublicKey)) ||
                    MediaSyncSettings.Effective(intent)["collection_mode"]?.GetValue<string>() != "entire_collection" ||
                    !MediaSyncSettings.TransferRequestedFor(intent, mediaType, toPhone: true) ||
                    store.ReadNativeMediaPreferences(peerId) != preferences || store.ReadNativeMediaSendConsent(peerId) != send ||
                    store.ReadNativeMediaReceiveConsent(peerId) != receive || !send.Explicit || !(mediaType == "video" ? send.Videos : send.Photos))
                    throw DeviceFileControl.Error("media_collection_native_choice_changed");
                if (Volatile.Read(ref nativeMediaWorker) != 0)
                    throw DeviceFileControl.Error("file_media_native_worker_busy");
            }
            Current();
            // Only the native WinForms bridge supplies this callback/owner.
            // Neither renderer paths nor a receive destination are accepted.
            using var selected = pickNative(Current);
            Current();
            if (selected is null) canceled = true;
            else store.AddNativeMediaCollectionRoot(peerId, mediaType, selected, Current, expectedRoots);
            permit.Require();
        }
        finally { Volatile.Write(ref nativeMediaCollectionDialog, 0); }
        var result = NativeMediaUiStatus(peerId);
        if (canceled) result["canceled"] = true;
        return result;
    }

    private Task NativeMediaSharedPreferencesChangedAsync(string peerId, TelefonConnection connection)
    {
        try { ApplyMatchedNativeMediaPreferences(peerId, connection); }
        catch (Exception error) when (error is InvalidDataException or IOException or InvalidOperationException or CryptographicException)
        { /* Shared choices stay durable; a missing local authority HOLDs IO, not metadata. */ }
        emit("MagnolieMedia.changed", new { device_id = peerId });
        return Task.CompletedTask;
    }

    internal bool ApplyMatchedNativeMediaPreferences(string peerId, TelefonConnection connection)
    {
        if (!ReferenceEquals(NativeMediaOnlineConnection(peerId), connection) || !connection.MediaSharedSettingsReady) return false;
        var permit = NativeMediaLocalBookPermit(); permit.Require();
        var currentPeer = store.LoadPeers().Single(value => value.Id == peerId);
        var body = store.ReadNativeMediaSharedSettings(peerId, currentPeer.PublicKey) ?? throw DeviceFileControl.Error("media_shared_snapshot_unavailable");
        void Current()
        {
            permit.Require();
            if (!connection.MediaSharedSettingsReady) throw DeviceFileControl.Error("media_shared_snapshot_changed");
        }
        var previous = store.ReadNativeMediaPreferences(peerId);
        var next = store.ProjectNativeMediaSharedPreferences(peerId, currentPeer.PublicKey, body, Current);
        if (next != previous)
        {
            connection.RevokeNativeMediaUiConsent();
            if (!next.AutomaticWifi) StopNativeMediaAutomatic(peerId);
            else if (!previous.AutomaticWifi && nativeAutomaticMedia.TryGetValue(peerId, out var state))
                lock (state) { state.Paused = false; state.Phase = "idle"; }
        }
        return true;
    }
    private TelefonConnection NativeMediaOnlineConnection(string peerId)
    {
        lock (gate)
            return !disposed && online.TryGetValue(peerId, out var connection) ? connection : throw DeviceFileControl.Error("file_media_native_peer_offline");
    }

    internal JsonObject NativeMediaUiStatus(string peerId)
    {
        TelefonConnection? connection; lock (gate) online.TryGetValue(peerId, out connection);
        var imagesReady = connection?.NativeMediaUiMetadataAvailable() == true;
        // Unsupported, disabled and not-yet-acknowledged peers have no advanced
        // media section. A claimed version or compiled implementation alone is
        // deliberately not a positive native availability projection.
        if (!imagesReady) return connection?.NativeMediaLegacyActivationAvailable() == true
            ? new JsonObject { ["supported"] = true, ["activation_required"] = true }
            : new JsonObject { ["supported"] = false };
        if (store.HasNativeMediaSharedSettings(peerId) && !connection!.MediaSharedControlsReady)
            return new JsonObject { ["supported"] = false };
        var videosReady = connection!.NativeMediaUiMetadataAvailable(videos: true);
        var preference = store.ReadNativeMediaPreferences(peerId);
        JsonNode? Destination(string kind)
        {
            var value = store.ReadNativeMediaDestination(peerId, kind);
            if (value is not null)
            {
                var isDefault = false;
                try
                {
                    var name = store.LoadPeers().Single(peer => peer.Id == peerId).Name;
                    var expected = kind == "images"
                        ? Path.Combine(PhotoDestinationPaths.NativePicturesDirectory(), PhotoDestinationPaths.NativeFolderComponent(name))
                        : Path.Combine(VideoDestinationPaths.NativeVideosDirectory(), VideoDestinationPaths.NativeFolderComponent(name));
                    isDefault = string.Equals(Path.GetFullPath(value.NativePath).TrimEnd('\\'), Path.GetFullPath(expected).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
                }
                catch (InvalidDataException) { }
                return new JsonObject { ["version"] = value.Version, ["display_path"] = value.NativePath, ["default"] = isDefault };
            }
            // Read-only default projection. Merely opening settings must never
            // create folders, persist a destination, or enable a transfer.
            try
            {
                var name = store.LoadPeers().Single(peer => peer.Id == peerId).Name;
                var path = kind == "images"
                    ? Path.Combine(PhotoDestinationPaths.NativePicturesDirectory(), PhotoDestinationPaths.NativeFolderComponent(name))
                    : Path.Combine(VideoDestinationPaths.NativeVideosDirectory(), VideoDestinationPaths.NativeFolderComponent(name));
                return new JsonObject { ["version"] = null, ["display_path"] = path, ["default"] = true };
            }
            catch (InvalidDataException) { return null; }
        }
        var automaticPhase = "idle"; var automaticBusy = false;
        if (nativeAutomaticMedia.TryGetValue(peerId, out var automatic) && ReferenceEquals(automatic.Connection, connection))
            lock (automatic) { automaticPhase = automatic.Phase; automaticBusy = automatic.Active is not null; }
        var result = new JsonObject { ["supported"] = true, ["photos"] = preference.PhotosEnabled, ["videos"] = preference.VideosEnabled,
            ["automatic"] = preference.AutomaticWifi, ["skip_deletions"] = preference.SkipDeletions is bool skip ? JsonValue.Create(skip) : null,
            ["version"] = preference.Version, ["pictures"] = Destination("images"), ["video_destination"] = Destination("video"),
            ["metadata_ready"] = new JsonObject { ["images"] = imagesReady, ["video"] = videosReady },
            ["automatic_phase"] = automaticPhase, ["automatic_busy"] = automaticBusy,
            ["busy"] = Volatile.Read(ref nativeMediaWorker) != 0, ["deletions_ready"] = false, ["automatic_ready"] = true };
        try
        {
            result["destination_choices"] = new JsonObject {
                ["images"] = NativeDestinationChoiceVersion(peerId, "images", connection),
                ["video"] = videosReady ? NativeDestinationChoiceVersion(peerId, "video", connection) : null };
        }
        catch (InvalidDataException error) when (error.Message == "file_receive_existing_storage_key_required")
        {
            // A read-only legacy status must not bootstrap the native key.
            // No choice hint is exposed until its original context is provable.
            result["destination_choices"] = null;
        }
        if (connection.MediaSharedControlsReady)
        {
            var currentPeer = store.LoadPeers().Single(value => value.Id == peerId);
            result["shared_settings"] = store.NativeMediaSharedSettingsView(peerId, currentPeer.PublicKey);
            result["shared_matched"] = connection.MediaSharedSettingsReady;
            // Availability/version hints only, never native file authority.
            result["shared_runtime_ready"] = connection.MediaSharedControlsReady;
            var intent = store.ReadNativeMediaSharedSettings(peerId, currentPeer.PublicKey);
            if (intent is not null && connection.MediaSharedSettingsReady && NativeMediaSharedUiChoiceAvailable(peerId, intent))
                result["shared_start_version"] = connection.NativeMediaSharedUiVersion(intent);
            var receive = store.ReadNativeMediaReceiveConsent(peerId);
            result["receive_consent"] = new JsonObject { ["granted"] = receive.Granted, ["version"] = receive.Version };
            var send = store.ReadNativeMediaSendConsent(peerId);
            result["send_consent"] = new JsonObject { ["photos"] = send.Photos, ["videos"] = send.Videos, ["version"] = send.Version };
            result["collection_sources_supported"] = true;
            if (intent is not null && connection.MediaSharedSettingsReady && MediaSyncSettings.Effective(intent)["collection_mode"]?.GetValue<string>() == "entire_collection")
                result["collection_sources_version"] = connection.NativeMediaSharedUiVersion(intent);
            var roots = new JsonArray();
            foreach (var root in store.NativeMediaCollectionRoots(peerId)) roots.Add(new JsonObject {
                ["id"] = root.Id, ["version"] = root.Version, ["media_type"] = root.MediaType, ["display_path"] = root.NativePath });
            result["collection_sources"] = roots;
        }
        return result;
    }

    private bool NativeMediaSharedUiChoiceAvailable(string peerId, JsonObject intent)
    {
        var receive = store.ReadNativeMediaReceiveConsent(peerId);
        var send = store.ReadNativeMediaSendConsent(peerId);
        return new[] { "images", "video" }.Any(kind =>
            receive.Granted && MediaSyncSettings.TransferRequestedFor(intent, kind, toPhone: false) ||
            send.Explicit && (kind == "images" ? send.Photos : send.Videos) && MediaSyncSettings.TransferRequestedFor(intent, kind, toPhone: true));
    }

    internal async Task<string> DispatchNativeMediaUiSharedAsync(NativeMediaUiRequest request, Func<object, Task> reply, CancellationToken token)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(token);
        var pass = RunNativeMediaUiSharedAsync(request, lifetime.Token);
        try { await reply(new { requestId = request.RequestId, device_id = request.PeerId, ok = true, state = "running" }); }
        catch
        {
            lifetime.Cancel();
            try { await pass; } catch { /* Retain the original reply failure, after actual worker exit. */ }
            throw;
        }
        var phase = await pass;
        await reply(new { requestId = request.RequestId, device_id = request.PeerId, ok = true, state = phase });
        return phase;
    }

    internal Task<string> RunNativeMediaUiSharedAsync(NativeMediaUiRequest request, CancellationToken token)
    {
        if (request.Action != "sync_shared" || !DeviceFileControl.Hash(request.Version ?? ""))
            throw DeviceFileControl.Error("file_media_ui_request_invalid");
        token.ThrowIfCancellationRequested();
        var connection = NativeMediaOnlineConnection(request.PeerId);
        var peer = store.LoadPeers().Single(value => value.Id == request.PeerId);
        var intent = store.ReadNativeMediaSharedSettings(request.PeerId, peer.PublicKey);
        if (intent is null || !connection.MediaSharedSettingsReady || connection.NativeMediaSharedUiVersion(intent) != request.Version)
            throw DeviceFileControl.Error("file_media_manual_intent_changed");
        if (!NativeMediaSharedUiChoiceAvailable(request.PeerId, intent))
            throw DeviceFileControl.Error("file_media_manual_choice_required");
        // Capture only native state; browser input carries neither intent nor grants.
        NativeMediaLocalBookPermit().Require();
        return RunNativeMediaInventoryOnceAsync(request.PeerId, intent.DeepClone().AsObject(), token, connection);
    }

    internal async Task<JsonObject> ChangeNativeMediaUiSharedSettingAsync(string peerId, string field, JsonNode value, string version)
    {
        var connection = NativeMediaOnlineConnection(peerId);
        if (!connection.MediaSharedControlsReady) throw DeviceFileControl.Error("media_shared_controls_unavailable");
        var permit = NativeMediaLocalBookPermit(); permit.Require();
        var currentPeer = store.LoadPeers().Single(peer => peer.Id == peerId);
        store.ChangeNativeMediaSharedSetting(peerId, currentPeer.PublicKey, field, value, version);
        // An edit is shared intent, never local receive rights or an IO start.
        connection.RevokeNativeMediaUiConsent();
        await connection.SendMediaSharedSettingsAsync();
        permit.Require(); return NativeMediaUiStatus(peerId);
    }

    internal JsonObject ChangeNativeMediaUiReceiveConsent(string peerId, string version, bool granted)
    {
        var connection = NativeMediaOnlineConnection(peerId);
        if (!connection.MediaSharedControlsReady) throw DeviceFileControl.Error("media_shared_controls_unavailable");
        var permit = NativeMediaLocalBookPermit(); permit.Require();
        if (granted && Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        store.ChangeNativeMediaReceiveConsent(peerId, version, granted);
        connection.RevokeNativeMediaUiConsent();
        if (!granted) StopNativeMediaAutomatic(peerId);
        ApplyMatchedNativeMediaPreferences(peerId, connection);
        permit.Require(); return NativeMediaUiStatus(peerId);
    }

    internal JsonObject ConfirmNativeMediaUiSendConsent(string peerId, string version, bool photos, bool videos, Func<bool> confirmNative)
    {
        ArgumentNullException.ThrowIfNull(confirmNative);
        if (Volatile.Read(ref nativeMediaCollectionDialog) != 0) throw DeviceFileControl.Error("media_collection_native_choice_pending");
        var connection = NativeMediaOnlineConnection(peerId);
        var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        var before = store.ReadNativeMediaSendConsent(peerId);
        if (before.Version != version) throw DeviceFileControl.Error("media_send_consent_stale_choice");
        var timer = System.Diagnostics.Stopwatch.StartNew();
        void Current()
        {
            permit.Require();
            if (!ReferenceEquals(connection, NativeMediaOnlineConnection(peerId)) || !connection.MediaSharedControlsReady ||
                !connection.NativeMediaUiMetadataAvailable() || timer.Elapsed > TimeSpan.FromSeconds(60))
                throw DeviceFileControl.Error("media_send_consent_native_context_changed");
            if (store.ReadNativeMediaSendConsent(peerId) != before) throw DeviceFileControl.Error("media_send_consent_stale_choice");
        }
        Current();
        var increasing = photos && !before.Photos || videos && !before.Videos;
        if (increasing && Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        // Only the native bridge supplies this modal-dialog callback. There is
        // no browser-confirmed bit, and dismissal never persists a choice.
        if (increasing && !confirmNative())
        {
            var canceled = NativeMediaUiStatus(peerId); canceled["canceled"] = true; return canceled;
        }
        Current();
        if (increasing && Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        store.ChangeNativeMediaSendConsent(peerId, version, photos, videos);
        connection.RevokeNativeMediaUiConsent();
        if (before.Photos && !photos || before.Videos && !videos) StopNativeMediaAutomatic(peerId);
        permit.Require(); return NativeMediaUiStatus(peerId);
    }

    internal void RequireNativeMediaUiDestinationConsent(string peerId)
    {
        TelefonConnection? connection; lock (gate) online.TryGetValue(peerId, out connection);
        if (connection?.MediaSharedControlsReady == true && !store.ReadNativeMediaReceiveConsent(peerId).Granted)
            throw DeviceFileControl.Error("file_media_local_receive_consent_required");
    }

    internal void ActivateLegacyNativeMediaUi(string peerId)
        => NativeMediaLocalOperation(() => {
            var permit = NativeMediaLocalBookPermit();
            permit.Require(); NativeMediaOnlineConnection(peerId).ActivateLegacyNativeMediaPairing();
            return true;
        });

    internal JsonObject SetNativeMediaUiAutomaticMode(string peerId, string? version, bool automaticWifi)
    {
        store.RequireNativeMediaStorageKey();
        _ = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        if (automaticWifi && Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        var current = store.ReadNativeMediaPreferences(peerId);
        store.SetNativeMediaPreferences(peerId, version, current.PhotosEnabled, current.VideosEnabled, automaticWifi);
        if (!automaticWifi) StopNativeMediaAutomatic(peerId);
        else if (nativeAutomaticMedia.TryGetValue(peerId, out var state)) lock (state) { state.Paused = false; state.Phase = "idle"; }
        return NativeMediaUiStatus(peerId);
    }

    internal JsonObject SetNativeMediaUiChoices(string peerId, string? expectedVersion, bool photos, bool videos, bool skipDeletions)
    {
        NativeMediaLocalOperation(() => {
        store.RequireNativeMediaStorageKey();
        var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        // Preserve single-checkbox intent for both directions, but no missing
        // deletion executor is represented as complete or silently enabled.
        var current = store.ReadNativeMediaPreferences(peerId);
        if (current.Version != expectedVersion) throw DeviceFileControl.Error("file_preferences_stale_selection");
        if (photos && store.ReadNativeMediaDestination(peerId, "images") is null)
            EnsureNativeMediaDefaultDestination(peerId, "images", PhotoDestinationPaths.NativePicturesDirectory());
        if (videos && store.ReadNativeMediaDestination(peerId, "video") is null)
            EnsureNativeMediaDefaultDestination(peerId, "video", VideoDestinationPaths.NativeVideosDirectory());
        permit.Require();
        store.SetNativeMediaPreferences(peerId, expectedVersion, photos, videos, automaticWifi: current.AutomaticWifi,
            deleteFromPhone: !skipDeletions, deleteFromDesktop: !skipDeletions);
        TelefonConnection? connection; lock (gate) online.TryGetValue(peerId, out connection);
        connection?.RevokeNativeMediaUiConsent();
        permit.Require(); return true;
        });
        return NativeMediaUiStatus(peerId);
    }

    internal void EnsureNativeMediaDefaultDestination(string peerId, string mediaType, string nativeKnownFolder)
    {
        RequireNativeMediaUiDestinationConsent(peerId);
        if (store.ReadNativeMediaDestination(peerId, mediaType) is not null) return;
        SetNativeMediaDefaultDestination(peerId, mediaType, nativeKnownFolder, null);
    }

    internal JsonObject ResetNativeMediaUiDestination(string peerId, string mediaType, string version)
        => ChooseNativeMediaDestination(peerId, mediaType, version, current => {
            current();
            var parentPath = mediaType == "images" ? PhotoDestinationPaths.NativePicturesDirectory() : VideoDestinationPaths.NativeVideosDirectory();
            var name = store.LoadPeers().Single(value => value.Id == peerId && value.State == "paired").Name;
            var leaf = mediaType == "images" ? PhotoDestinationPaths.NativeFolderComponent(name) : VideoDestinationPaths.NativeFolderComponent(name);
            using var parent = DeviceFileNativeDirectory.OpenExistingForReceive(parentPath);
            current();
            try { return DeviceFileNativeDirectory.OpenExistingForReceive(Path.Combine(parent.NativePath, leaf)); }
            catch (IOException error) when (error.InnerException is System.ComponentModel.Win32Exception native && native.NativeErrorCode is 2 or 3)
            { current(); return parent.CreateChild(leaf); }
        });

    private void SetNativeMediaDefaultDestination(string peerId, string mediaType, string nativeKnownFolder, string? version)
    {
        RequireNativeMediaUiDestinationConsent(peerId);
        if (store.ReadNativeMediaDestination(peerId, mediaType)?.Version != version) throw DeviceFileControl.Error("file_destination_stale_choice");
        var permit = NativeMediaLocalBookPermit(); permit.Require();
        var peer = store.LoadPeers().Single(value => value.Id == peerId && value.State == "paired");
        var name = mediaType == "images" ? PhotoDestinationPaths.NativeFolderComponent(peer.Name)
            : mediaType == "video" ? VideoDestinationPaths.NativeFolderComponent(peer.Name)
            : throw DeviceFileControl.Error("file_media_type_invalid");
        using var parent = DeviceFileNativeDirectory.OpenExistingForReceive(nativeKnownFolder);
        DeviceFileNativeDirectory child;
        try { child = DeviceFileNativeDirectory.OpenExistingForReceive(Path.Combine(parent.NativePath, name)); }
        catch (IOException error) when (error.InnerException is System.ComponentModel.Win32Exception native && native.NativeErrorCode is 2 or 3)
        { child = parent.CreateChild(name); }
        using (child)
        {
            permit.Require(); _ = parent.CurrentReceiveIdentity();
            store.SetNativeMediaDestination(peerId, mediaType, version, child);
            permit.Require();
        }
    }

    private void EnsureConfiguredNativeMediaDefault(string peerId, string mediaType)
    {
        var preferences = store.ReadNativeMediaPreferences(peerId);
        if (!(mediaType == "images" ? preferences.PhotosEnabled : mediaType == "video" && preferences.VideosEnabled))
            throw DeviceFileControl.Error("file_media_native_choice_required");
        if (store.ReadNativeMediaDestination(peerId, mediaType) is null)
            EnsureNativeMediaDefaultDestination(peerId, mediaType, mediaType == "images"
                ? PhotoDestinationPaths.NativePicturesDirectory() : VideoDestinationPaths.NativeVideosDirectory());
    }

    internal async Task<(string Version, DeviceFileCatalogPage Page)> DiscoverNativeMediaUiAsync(string peerId, string mediaType, CancellationToken token)
        => await ExclusiveNativeMediaUiMetadataAsync(async () =>
    {
        var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        var connection = NativeMediaOnlineConnection(peerId);
        EnsureConfiguredNativeMediaDefault(peerId, mediaType); permit.Require();
        await connection.PrepareNativeMediaUiAsync(NativeSavedBook, mediaType, token); permit.Require();
        var status = await connection.ReadNativeFileSourceStatusAsync(token); permit.Require();
        var configured = await connection.PrepareNativeMediaSourceAsync(status, mediaType, token); permit.Require();
        await connection.AwaitNativeMediaDataAgreementAsync(mediaType, token); permit.Require();
        return (configured.Version, await connection.DiscoverNativeMediaAlbumsAsync(configured.Version, mediaType, token: token));
    });

    internal async Task<(string Version, DeviceFileCatalogPage Page)> PageNativeMediaUiAsync(string peerId, string mediaType, string version, string catalog, int after, CancellationToken token)
        => await ExclusiveNativeMediaUiMetadataAsync(async () => (version, await NativeMediaOnlineConnection(peerId).DiscoverNativeMediaAlbumsAsync(version, mediaType, catalog, after, token)));

    internal Task<DeviceFilePermissionResult> RequestNativeMediaUiReadAsync(string peerId, string mediaType, string? version, CancellationToken token)
        => ExclusiveNativeMediaUiMetadataAsync(async () => {
            var permit = NativeMediaLocalBookPermit();
            EnsureConfiguredNativeMediaDefault(peerId, mediaType); permit.Require();
            var connection = NativeMediaOnlineConnection(peerId);
            if (version is null)
            {
                await connection.PrepareNativeMediaUiAsync(NativeSavedBook, mediaType, token); permit.Require();
                var status = await connection.ReadNativeFileSourceStatusAsync(token); permit.Require();
                var configured = await connection.PrepareNativeMediaSourceAsync(status, mediaType, token); permit.Require();
                version = configured.Version;
                await connection.AwaitNativeMediaDataAgreementAsync(mediaType, token); permit.Require();
            }
            var result = await connection.RequestNativeMediaReadAsync(version, mediaType, token); permit.Require();
            return result;
        });

    private async Task<T> ExclusiveNativeMediaUiMetadataAsync<T>(Func<Task<T>> action)
    {
        if (Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        try { return await action(); }
        finally { Interlocked.Exchange(ref nativeMediaWorker, 0); }
    }

    internal async Task<TelefonConnection.NativeMediaAlbumOutcome> SynchronizeNativeMediaUiAsync(string peerId, string mediaType,
        string version, string catalog, string album, CancellationToken token)
    {
        NativeMediaOnlineConnection(peerId).RequireKnownNativeMediaAlbum(version, catalog, album, mediaType);
        return await SynchronizeNativeMediaAlbumFromSavedBookAsync(peerId, version, catalog, album, true, mediaType, token);
    }
}
