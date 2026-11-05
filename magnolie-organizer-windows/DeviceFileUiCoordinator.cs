using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
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
        // Wait for the ACTUAL encrypted bilateral ACK. Stored intent/status is
        // never substituted for the receiver/data witness, especially for video.
        while (true)
        {
            deadline.Token.ThrowIfCancellationRequested();
            var current = authority.Current();
            if (current?.Grants.ReceiveFiles != true) throw DeviceFileControl.Error("file_media_native_choice_changed");
            var destination = store.ReadNativeMediaDestination(peer.Id, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
            bool ready;
            await fileControlIo.WaitAsync(deadline.Token);
            try { ready = RequireNativeFileControls().Binding(destination.DestinationToken) is not null; }
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
        var preference = store.ReadNativeMediaPreferences(peerId);
        TelefonConnection? connection; lock (gate) online.TryGetValue(peerId, out connection);
        JsonNode? Destination(string kind)
        {
            var value = store.ReadNativeMediaDestination(peerId, kind);
            return value is null ? null : new JsonObject { ["version"] = value.Version, ["display_path"] = value.NativePath };
        }
        return new JsonObject { ["supported"] = true, ["photos"] = preference.PhotosEnabled, ["videos"] = preference.VideosEnabled,
            ["automatic"] = preference.AutomaticWifi, ["skip_deletions"] = preference.SkipDeletions is bool skip ? JsonValue.Create(skip) : null,
            ["version"] = preference.Version, ["pictures"] = Destination("images"), ["video_destination"] = Destination("video"),
            ["metadata_ready"] = new JsonObject { ["images"] = connection?.FileMetadataReady() == true, ["video"] = connection?.FileMetadataReady(videos: true) == true },
            ["busy"] = Volatile.Read(ref nativeMediaWorker) != 0, ["deletions_ready"] = false, ["automatic_ready"] = false };
    }

    internal JsonObject SetNativeMediaUiChoices(string peerId, string? expectedVersion, bool photos, bool videos, bool skipDeletions)
    {
        store.RequireNativeMediaStorageKey();
        _ = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
        if (Volatile.Read(ref nativeMediaWorker) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        // Preserve single-checkbox intent for both directions, but no missing
        // deletion executor is represented as complete or silently enabled.
        var current = store.ReadNativeMediaPreferences(peerId);
        store.SetNativeMediaPreferences(peerId, expectedVersion, photos, videos, automaticWifi: current.AutomaticWifi,
            deleteFromPhone: !skipDeletions, deleteFromDesktop: !skipDeletions);
        TelefonConnection? connection; lock (gate) online.TryGetValue(peerId, out connection);
        connection?.RevokeNativeMediaUiConsent();
        return NativeMediaUiStatus(peerId);
    }

    internal void SetNativeMediaUiDestination(string peerId, string mediaType, string? version, DeviceFileNativeDirectory nativeOwner)
    {
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
        await connection.PrepareNativeMediaUiAsync(NativeSavedBook, mediaType, token); permit.Require();
        var status = await connection.ReadNativeFileSourceStatusAsync(token); permit.Require();
        var configured = await connection.ConfigureNativeMediaSourceAsync(status.Version, mediaType, true, token); permit.Require();
        return (configured.Version, await connection.DiscoverNativeMediaAlbumsAsync(configured.Version, mediaType, token: token));
    });

    internal async Task<(string Version, DeviceFileCatalogPage Page)> PageNativeMediaUiAsync(string peerId, string mediaType, string version, string catalog, int after, CancellationToken token)
        => await ExclusiveNativeMediaUiMetadataAsync(async () => (version, await NativeMediaOnlineConnection(peerId).DiscoverNativeMediaAlbumsAsync(version, mediaType, catalog, after, token)));

    internal Task<DeviceFilePermissionResult> RequestNativeMediaUiReadAsync(string peerId, string mediaType, string version, CancellationToken token)
        => ExclusiveNativeMediaUiMetadataAsync(() => NativeMediaOnlineConnection(peerId).RequestNativeMediaReadAsync(version, mediaType, token));

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
