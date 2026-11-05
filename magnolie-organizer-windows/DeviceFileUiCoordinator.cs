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
    private sealed class NativeMediaUiAuthority(TelefonStore store, string peerId, Func<NativeBookSaveState?> savedBook)
    {
        private readonly object gate = new();
        private readonly object owner = new();
        private DeviceFileGrantState? grants;
        private NativeMediaPreferences? preferences;
        private string? bookSource;
        private bool revoked;

        internal void Choose()
        {
            store.RequireNativeMediaStorageKey();
            if (!store.ReadNativeMediaReceiveConsent(peerId).Granted) throw DeviceFileControl.Error("file_media_local_receive_consent_required");
            var saved = savedBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required");
            var choice = store.ReadNativeMediaPreferences(peerId);
            if (!choice.PhotosEnabled && !choice.VideosEnabled) throw DeviceFileControl.Error("file_media_native_choice_required");
            lock (gate)
            {
                if (grants is not null && !revoked && preferences == choice && bookSource == saved.BookSource) return;
                grants = new((grants?.Revision ?? 0) + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), receiveFiles: true);
                preferences = choice; bookSource = saved.BookSource; revoked = false;
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
                if (revoked && grants.ReceiveFiles)
                    grants = new(grants.Revision + 1, Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant());
                return new(grants, owner, handlersReady: true);
            }
        }

        internal void Revoke() { lock (gate) revoked = true; }
    }
    private NativeMediaUiAuthority? nativeMediaUiAuthority;
    internal void RevokeNativeMediaUiConsent() => nativeMediaUiAuthority?.Revoke();

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
            authority = nativeMediaUiAuthority ??= new(store, peer.Id, savedBook);
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

    internal void RequireKnownNativeMediaAlbum(string version, string catalog, string album, string mediaType)
    {
        var owner = RequireNativeFileControls();
        if (KnownNativeAlbum(owner, mediaType, version, catalog, album) is null) throw DeviceFileControl.Error("file_media_native_catalog_choice_changed");
    }

    internal async Task AwaitNativeMediaDataAgreementAsync(string mediaType, CancellationToken token)
    {
        var owner = RequireNativeFileControls();
        var preferences = store.ReadNativeMediaPreferences(peer.Id);
        var destination = store.ReadNativeMediaDestination(peer.Id, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
        var authority = nativeMediaUiAuthority ?? throw DeviceFileControl.Error("file_media_native_owner_busy");
        var expected = authority.Current()?.Grants ?? throw DeviceFileControl.Error("file_media_native_choice_changed");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token, cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(60));
        while (true)
        {
            deadline.Token.ThrowIfCancellationRequested(); RequireNativeFileControls(owner); store.RequireNativeMediaStorageKey();
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
        var videosReady = connection!.NativeMediaUiMetadataAvailable(videos: true);
        var preference = store.ReadNativeMediaPreferences(peerId);
        JsonNode? Destination(string kind)
        {
            var value = store.ReadNativeMediaDestination(peerId, kind);
            if (value is not null) return new JsonObject { ["version"] = value.Version, ["display_path"] = value.NativePath };
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
        if (connection.MediaSharedControlsReady)
        {
            var currentPeer = store.LoadPeers().Single(value => value.Id == peerId);
            result["shared_settings"] = store.NativeMediaSharedSettingsView(peerId, currentPeer.PublicKey);
            result["shared_matched"] = connection.MediaSharedSettingsReady;
            var receive = store.ReadNativeMediaReceiveConsent(peerId);
            result["receive_consent"] = new JsonObject { ["granted"] = receive.Granted, ["version"] = receive.Version };
        }
        return result;
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
            store.SetNativeMediaDestination(peerId, mediaType, null, child);
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

    internal void SetNativeMediaUiDestination(string peerId, string mediaType, string? version, DeviceFileNativeDirectory nativeOwner)
    {
        RequireNativeMediaUiDestinationConsent(peerId);
        store.RequireNativeMediaStorageKey();
        _ = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        if (Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        store.SetNativeMediaDestination(peerId, mediaType, version, nativeOwner);
    }

    internal async Task<(string Version, DeviceFileCatalogPage Page)> DiscoverNativeMediaUiAsync(string peerId, string mediaType, CancellationToken token)
        => await ExclusiveNativeMediaUiMetadataAsync(async () =>
    {
        var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        var connection = NativeMediaOnlineConnection(peerId);
        EnsureConfiguredNativeMediaDefault(peerId, mediaType); permit.Require();
        await connection.PrepareNativeMediaUiAsync(NativeSavedBook, mediaType, token); permit.Require();
        var status = await connection.ReadNativeFileSourceStatusAsync(token); permit.Require();
        var configured = await connection.ConfigureNativeMediaSourceAsync(status.Version, mediaType, true, token); permit.Require();
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
                var configured = await connection.ConfigureNativeMediaSourceAsync(status.Version, mediaType, true, token); permit.Require();
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
