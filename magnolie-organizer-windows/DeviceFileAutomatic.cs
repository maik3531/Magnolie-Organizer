using System.Collections.Concurrent;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    // Scheduling positions only, never album identities or persisted catalogue
    // IDs. Each attempt discovers again; actual mapping still uses source_epoch.
    private sealed class NativeAutomaticMediaState(TelefonConnection connection)
    {
        internal readonly TelefonConnection Connection = connection;
        internal int Images, Videos;
        internal bool Paused;
        internal string Phase = "idle";
        internal CancellationTokenSource? Active;
    }
    private readonly ConcurrentDictionary<string, NativeAutomaticMediaState> nativeAutomaticMedia = new(StringComparer.Ordinal);
    private sealed record OriginalImageExport(NativeBookSaveState Book, NativeMediaSendConsent Consent,
        NativeMediaCollectionRoot[] Roots, byte[] PeerKey, Func<bool> Agreement);

    partial void StartNativeMediaAutomatic(CancellationToken token)
        => Track(McpServiceTask(() => NativeMediaAutomaticLoopAsync(token)));

    private async Task NativeMediaAutomaticLoopAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            KeyValuePair<string, TelefonConnection>[] current;
            lock (gate) current = online.ToArray();
            foreach (var old in nativeAutomaticMedia.ToArray())
                if (!current.Any(item => item.Key == old.Key && ReferenceEquals(item.Value, old.Value.Connection)))
                    nativeAutomaticMedia.TryRemove(old.Key, out _);
            foreach (var item in current)
            {
                try
                {
                    if (!item.Value.OriginalMediaReceiveSelected && item.Value.NativeMediaUiMetadataAvailable())
                        SweepNativeMediaTrashFromSavedBook(item.Key, token);
                    await RunNativeMediaAutomaticOnceAsync(item.Key, token);
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { return; }
                catch (Exception) { /* Retained jobs are repairable, never replay deletion or erase history. */ }
            }
            try { await Task.Delay(TimeSpan.FromSeconds(30), token); }
            catch (OperationCanceledException) { return; }
        }
    }

    internal bool StopNativeMediaAutomatic(string peerId)
    {
        if (!nativeAutomaticMedia.TryGetValue(peerId, out var state)) return false;
        CancellationTokenSource? active;
        lock (state)
        {
            state.Paused = true;
            if (state.Active is null) { state.Phase = "paused"; return false; }
            active = state.Active; state.Phase = "stopping";
        }
        try { active.Cancel(); } catch (ObjectDisposedException) { return false; }
        return true;
    }

    internal async Task RunNativeMediaAutomaticOnceAsync(string peerId, CancellationToken token)
    {
        var connection = NativeMediaOnlineConnection(peerId);
        if (!connection.OriginalMediaReceiveSelected)
        {
            await RunNativeMediaInventoryOnceAsync(peerId, null, token, connection);
            return;
        }
        if (!connection.OriginalMediaSettingsEditable || NativeSavedBook() is not { } book) return;
        var preferences = store.ReadNativeMediaPreferences(peerId);
        if (!preferences.AutomaticWifi || preferences.OriginalAutomaticKey is null) return;
        var peer = store.LoadPeers().Single(value => value.Id == peerId);
        var intent = store.ReadNativeMediaSharedSettings(peerId, peer.PublicKey);
        var receive = store.ReadNativeMediaReceiveConsent(peerId);
        if (intent is null || !receive.Granted || !OriginalReceiveAvailable(connection, intent, "wifi") ||
            preferences.OriginalAutomaticKey != OriginalAutomaticReceiveKey(peerId, intent, receive, book)) return;
        await RunNativeMediaInventoryOnceAsync(peerId, intent, token, connection, receive, book, originalBackground: true);
    }

    private string? OriginalAutomaticReceiveKey(string peerId, JsonObject intent, NativeMediaReceiveConsent receive, NativeBookSaveState book)
    {
        var targets = new JsonObject();
        foreach (var kind in new[] { "images", "video" })
        {
            if (!MediaSyncSettings.TransferRequestedFor(intent, kind, toPhone: false)) continue;
            if (store.ReadNativeMediaDestination(peerId, kind) is not { } target) return null;
            targets[kind] = target.Version;
        }
        return DeviceFileControl.Digest("magnolie-media-original-automatic-receive-v1\0",
            new JsonObject { ["settings"] = intent.DeepClone(), ["receive"] = receive.Version, ["book"] = book.BookSource, ["targets"] = targets });
    }

    // Explicit phone requests carry the exact agreed snapshot, not filesystem
    // paths, album IDs, local rights or an instruction to enable automatic mode.
    internal Task<string> RunNativeMediaManualOnceAsync(string peerId, JsonObject expectedIntent, CancellationToken token)
        => RunNativeMediaInventoryOnceAsync(peerId, expectedIntent.DeepClone().AsObject(), token);

    internal void StartNativeMediaManualRequest(string peerId, TelefonConnection connection, JsonObject settings, string requestId, long deadline, CancellationToken token)
    {
        Track(McpServiceTask(async () =>
        {
            var phase = "held";
            try
            {
                if (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() >= deadline) throw DeviceFileControl.Error("file_media_manual_request_expired");
                if (!ReferenceEquals(NativeMediaOnlineConnection(peerId), connection)) throw DeviceFileControl.Error("file_media_manual_connection_changed");
                phase = await RunNativeMediaInventoryOnceAsync(peerId, settings, token, connection);
            }
            catch (Exception) { /* Explicit result is HOLD; original jobs/history remain owned and recoverable. */ }
            try { await connection.SendMediaManualResultAsync(requestId, phase); }
            catch (Exception) { /* Disconnected requests are never replayed on another channel. */ }
            await emit("MagnolieMedia.changed", new { device_id = peerId });
        }));
    }

    private async Task<string> RunNativeMediaInventoryOnceAsync(string peerId, JsonObject? manualIntent, CancellationToken token,
        TelefonConnection? expectedConnection = null, NativeMediaReceiveConsent? originalReceive = null, NativeBookSaveState? originalBook = null,
        bool originalAutomaticSetup = false, bool originalBackground = false, OriginalImageExport? originalImages = null)
    {
        var manual = manualIntent is not null && !originalBackground;
        JsonObject? runIntent = manualIntent;
        token.ThrowIfCancellationRequested();
        var connection = NativeMediaOnlineConnection(peerId);
        var original = originalReceive is not null && manualIntent is not null ? connection.CapturePrivateMediaPhoneImport(manualIntent) : null;
        if (originalReceive is not null && (original is null || originalBook is null)) throw DeviceFileControl.Error("file_media_manual_intent_changed");
        if (expectedConnection is not null && !ReferenceEquals(expectedConnection, connection))
            throw DeviceFileControl.Error("file_media_manual_connection_changed");
        if ((!manual && connection.Transport != "wifi") || !connection.NativeMediaUiMetadataAvailable())
        {
            if (manual) throw DeviceFileControl.Error("file_media_manual_connection_not_ready");
            return "held";
        }
        void Intent()
        {
            if (runIntent is not null && (!ReferenceEquals(NativeMediaOnlineConnection(peerId), connection) ||
                !(originalImages?.Agreement() ?? original?.Invoke() ?? connection.MediaSharedSettingsReady) ||
                !JsonNode.DeepEquals(store.ReadNativeMediaSharedSettings(peerId, store.LoadPeers().Single(value => value.Id == peerId).PublicKey), runIntent)))
                throw DeviceFileControl.Error(manual ? "file_media_manual_intent_changed" : "file_media_original_shared_intent_changed");
        }
        Intent();
        if (original is null && originalImages is null && (connection.MediaSharedControlsReady || store.HasNativeMediaSharedSettings(peerId)))
        {
            // Pin the full original registers for automatic roots too. Equal
            // projected local preferences do not make a later shared ACK the
            // original operation's intent.
            runIntent ??= store.ReadNativeMediaSharedSettings(peerId, store.LoadPeers().Single(value => value.Id == peerId).PublicKey)?.DeepClone().AsObject();
            if (!connection.MediaSharedSettingsReady || !ApplyMatchedNativeMediaPreferences(peerId, connection))
            {
                if (manual) throw DeviceFileControl.Error("file_media_manual_intent_changed");
                return "held";
            }
            Intent();
        }
        var preferences = store.ReadNativeMediaPreferences(peerId);
        if (original is null && originalImages is null && ((!manual && !preferences.AutomaticWifi) || !preferences.PhotosEnabled && !preferences.VideosEnabled))
        {
            if (manual) throw DeviceFileControl.Error("file_media_manual_choice_required");
            return "held";
        }
        var state = nativeAutomaticMedia.GetOrAdd(peerId, _ => new(connection));
        if (!ReferenceEquals(state.Connection, connection))
        {
            var replacement = new NativeAutomaticMediaState(connection);
            if (!nativeAutomaticMedia.TryUpdate(peerId, replacement, state))
            {
                if (manual) throw DeviceFileControl.Error("file_media_manual_connection_changed");
                return "held";
            }
            state = replacement;
        }
        // Same lane as manual discovery/receive; skip, never enqueue stale work.
        if (Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0)
        {
            if (manual) throw DeviceFileControl.Error("file_media_native_worker_busy");
            return "held";
        }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(token);
        lifetime.CancelAfter(TimeSpan.FromHours(2));
        IDisposable? activity = null;
        try
        {
            lock (state)
            {
                if (manual) state.Paused = false; // Only a new explicit action resumes a stopped pass.
                else if (state.Paused) return "held";
                state.Active = lifetime; state.Phase = "running";
            }
            activity = TraySyncActivity.Enter();
            var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
            if (originalImages is not null)
            {
                void RequireIntent()
                {
                    lifetime.Token.ThrowIfCancellationRequested(); permit.Require();
                    if (!JsonNode.DeepEquals(store.ReadNativeMediaSharedSettings(peerId, originalImages.PeerKey), runIntent))
                        throw DeviceFileControl.Error("media_source_current_sending_owner_required");
                }
                try
                {
                    if (NativeSavedBook() != originalImages.Book)
                        throw DeviceFileControl.Error("file_media_current_saved_book_required");
                    RequireIntent();
                    await connection.PrepareNativeMediaSendUiAsync(NativeSavedBook, "images", lifetime.Token,
                        originalImages.Agreement, originalImages.Consent);
                    await connection.SynchronizeOriginalPcImageCollectionAsync(runIntent!, permit, RequireIntent, originalImages.Agreement,
                        originalImages.Consent, originalImages.Roots, lifetime.Token);
                    lock (state) state.Phase = "content_pass";
                    return "content_pass";
                }
                finally { connection.RevokeNativeMediaUiConsent(); }
            }
            NativeMediaReceiveConsent? accepted = originalReceive;
            var kinds = new[] { "images", "video" };
            var originalTargets = new Dictionary<string, NativeMediaDestination>();
            if (original is not null)
            {
                if (NativeSavedBook() != originalBook) throw DeviceFileControl.Error("file_media_current_saved_book_required");
                void Admission()
                {
                    lifetime.Token.ThrowIfCancellationRequested(); permit.Require();
                    if (!original() || !JsonNode.DeepEquals(store.ReadNativeMediaSharedSettings(peerId,
                            store.LoadPeers().Single(value => value.Id == peerId).PublicKey), runIntent))
                        throw DeviceFileControl.Error("file_media_manual_intent_changed");
                }
                Admission();
                void Project()
                {
                    Admission();
                    if (store.ReadNativeMediaReceiveConsent(peerId) != accepted)
                        throw DeviceFileControl.Error("file_media_local_receive_consent_required");
                }
                if (originalBackground)
                {
                    if (!preferences.AutomaticWifi || preferences.OriginalAutomaticKey is null ||
                        preferences.OriginalAutomaticKey != OriginalAutomaticReceiveKey(peerId, runIntent!, accepted!, originalBook!))
                        return "held";
                }
                else
                {
                    if (!accepted!.Granted) accepted = store.InitializeNativeMediaFirstReceive(peerId, accepted.Version, Admission);
                    preferences = store.SetNativeMediaPreferences(peerId, preferences.Version,
                        photosEnabled: MediaSyncSettings.TransferRequestedFor(runIntent!, "images", toPhone: false),
                        videosEnabled: MediaSyncSettings.TransferRequestedFor(runIntent!, "video", toPhone: false),
                        automaticWifi: false, deleteFromPhone: false, deleteFromDesktop: false, nativeGuard: Project);
                }
                Project();
                foreach (var kind in kinds.Where(kind => MediaSyncSettings.TransferRequestedFor(runIntent!, kind, toPhone: false)))
                {
                    if (!originalBackground) EnsureConfiguredNativeMediaDefault(peerId, kind);
                    var target = store.ReadNativeMediaDestination(peerId, kind)
                        ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
                    using var root = target.OpenNative(); _ = root.CurrentIdentity();
                    originalTargets.Add(kind, target);
                    Project();
                }
            }
            void Require()
            {
                lifetime.Token.ThrowIfCancellationRequested(); permit.Require(); Intent();
                if ((!manual && connection.Transport != "wifi") || !connection.NativeMediaUiMetadataAvailable() ||
                    store.ReadNativeMediaPreferences(peerId) != preferences ||
                    accepted is not null && store.ReadNativeMediaReceiveConsent(peerId) != accepted ||
                    originalTargets.Any(target => store.ReadNativeMediaDestination(peerId, target.Key) != target.Value))
                    throw DeviceFileControl.Error("file_media_automatic_choice_changed");
            }
            var review = false;
            async Task<(string CatalogId, string Coverage, List<DeviceFileAlbumMetadata> Albums)> Discover(string version, string kind)
            {
                var page = await connection.DiscoverNativeMediaAlbumsAsync(version, kind, token: lifetime.Token); Require();
                var albums = page.Albums.ToList();
                while (page.NextCursor is int after)
                {
                    page = await connection.DiscoverNativeMediaAlbumsAsync(version, kind, page.CatalogId, after, lifetime.Token); Require();
                    albums.AddRange(page.Albums);
                }
                return (page.CatalogId, page.Coverage, albums);
            }
            static string FullCoverage(string kind) => kind == "images" ? "full_images" : "full_videos";
            static bool ReadCovered(string kind, string coverage, List<DeviceFileAlbumMetadata> albums) =>
                coverage == FullCoverage(kind) || coverage == "selected_only" && albums.Count > 0;
            async Task Import(string kind, string version, string catalogId, string coverage, List<DeviceFileAlbumMetadata> albums)
            {
                review |= coverage != FullCoverage(kind) || albums.Any(album => album.NeedsChoice);
                var eligible = albums.Where(album => !album.NeedsChoice).ToArray();
                if (eligible.Length == 0) return;
                var position = kind == "images" ? state.Images : state.Videos;
                var selected = manual ? eligible : new[] { eligible[position % eligible.Length] };
                // Rotation is fairness only; no mapping/absence comes from it.
                if (kind == "images") state.Images = (position + 1) % eligible.Length;
                else state.Videos = (position + 1) % eligible.Length;
                foreach (var album in selected)
                {
                    Require();
                    var outcome = await connection.SynchronizeNativeMediaAlbumAsync(version, catalogId, album.AlbumId,
                        desktopChoice: false, kind, lifetime.Token, permit.ReplacementConsent, Require);
                    Require(); review |= outcome.NeedsReview;
                }
            }
            string Finish(bool needsReview)
            {
                var phase = needsReview ? "review" : "content_pass";
                lock (state) state.Phase = phase;
                return phase;
            }
            if (original is not null)
            {
                var selectedKinds = kinds.Where(originalTargets.ContainsKey).ToArray();
                var images = originalTargets.ContainsKey("images");
                var video = originalTargets.ContainsKey("video");
                var firstKind = selectedKinds[0];
                Require();
                await connection.PrepareNativeMediaUiAsync(NativeSavedBook, firstKind, lifetime.Token); Require();
                var status = await connection.ReadNativeFileSourceStatusAsync(lifetime.Token); Require();
                if (!originalBackground && status is { Revision: 0, RepairPending: false, Associated: false, Enabled: false } &&
                    status.Kinds.Count == 0)
                {
                    status = images ? await connection.ConfigureNativeMediaSourceAsync(status.Version, "images", true, lifetime.Token)
                        : await connection.BootstrapNativeVideoSourceAsync(status, lifetime.Token);
                    Require();
                }
                if (!status.Associated || status.RepairPending || images && !status.Enabled) return Finish(true);
                if (video)
                {
                    if (status.Videos is not { } videos || !videos.Enabled && (originalBackground || !images || videos.Revision != 0))
                        return Finish(true);
                    await connection.AwaitNativeMediaDataAgreementAsync("video", lifetime.Token, Require); Require();
                    var configured = await connection.ConfigureNativeMediaSourceAsync(status.Version, "video", true, lifetime.Token);
                    Require();
                    if (configured.Enabled != status.Enabled || !configured.Kinds.SequenceEqual(status.Kinds) ||
                        (videos.Enabled ? configured.Version != status.Version || configured.Revision != status.Revision || configured.Videos != videos
                            : configured.Version == status.Version || configured.Revision <= status.Revision || configured.Videos!.Revision <= videos.Revision))
                        throw DeviceFileControl.Error("file_sources_native_configuration_unconfirmed");
                    status = configured;
                }
                var catalogs = new Dictionary<string, (string CatalogId, string Coverage, List<DeviceFileAlbumMetadata> Albums)>();
                foreach (var kind in selectedKinds)
                {
                    await connection.AwaitNativeMediaDataAgreementAsync(kind, lifetime.Token, Require); Require();
                    var catalog = await Discover(status.Version, kind);
                    if (!ReadCovered(kind, catalog.Coverage, catalog.Albums))
                    {
                        if (!originalBackground)
                        {
                            await connection.RequestNativeMediaReadAsync(status.Version, kind, lifetime.Token); Require();
                        }
                        return Finish(true);
                    }
                    catalogs.Add(kind, catalog);
                }
                // Revalidate both roots after preflight and before the first content command.
                foreach (var target in originalTargets.Values)
                {
                    Require();
                    using var root = target.OpenNative(); _ = root.CurrentIdentity();
                }
                if (originalAutomaticSetup)
                {
                    var key = OriginalAutomaticReceiveKey(peerId, runIntent!, accepted!, originalBook!)
                        ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
                    lock (state)
                    {
                        if (state.Paused) throw new OperationCanceledException(lifetime.Token);
                        preferences = store.SetNativeMediaPreferences(peerId, preferences.Version, images, video, automaticWifi: true,
                            deleteFromPhone: false, deleteFromDesktop: false, nativeGuard: Require, originalAutomaticKey: key);
                        state.Phase = "waiting";
                    }
                    return "waiting";
                }
                foreach (var kind in selectedKinds)
                {
                    // The first transfer may outlive the other kind's short-lived Android catalog.
                    var catalog = kind == firstKind ? catalogs[kind] : await Discover(status.Version, kind);
                    if (!ReadCovered(kind, catalog.Coverage, catalog.Albums)) return Finish(true);
                    await Import(kind, status.Version, catalog.CatalogId, catalog.Coverage, catalog.Albums);
                }
                return Finish(review);
            }
            foreach (var kind in kinds)
            {
                if (!(kind == "images" ? preferences.PhotosEnabled : preferences.VideosEnabled)) continue;
                Require();
                if (kind == "video" && !connection.NativeMediaUiMetadataAvailable(videos: true)) { review = true; continue; }
                var sharedIntent = runIntent;
                if (sharedIntent is not null && MediaSyncSettings.TransferRequestedFor(sharedIntent, kind, toPhone: true))
                {
                    await connection.PrepareNativeMediaSendUiAsync(NativeSavedBook, kind, lifetime.Token); Require();
                    var outgoing = await connection.SynchronizeNativeMappedMediaChangesAsync(kind, permit, Require, lifetime.Token, automatic: !manual);
                    Require(); review |= outgoing.NeedsReview;
                }
                // Scope, mode and direction remain independent. PC-only direction
                // must not fall through to phone-source discovery/READ/import.
                if (sharedIntent is not null && !MediaSyncSettings.TransferRequestedFor(sharedIntent, kind, toPhone: false)) continue;
                EnsureConfiguredNativeMediaDefault(peerId, kind); Require();
                await connection.PrepareNativeMediaUiAsync(NativeSavedBook, kind, lifetime.Token); Require();
                var status = sharedIntent is not null
                    ? await connection.ReadNativeSharedMediaSourceStatusAsync(kind, lifetime.Token)
                    : await connection.ReadNativeFileSourceStatusAsync(lifetime.Token);
                Require();
                // A matched shared synchronization choice adopts current native
                // phone SEND state; it must not invoke the explicit legacy
                // setup/configure path or silently enable video access.
                if (sharedIntent is not null && (!status.Associated || status.RepairPending || !status.Enabled ||
                    kind == "video" && status.Videos?.Enabled != true))
                { review = true; continue; }
                var configured = sharedIntent is not null ? status
                    : await connection.PrepareNativeMediaSourceAsync(status, kind, lifetime.Token);
                Require();
                await connection.AwaitNativeMediaDataAgreementAsync(kind, lifetime.Token); Require();
                // No OS permission request or guessed explicit album choice in
                // background. Missing/selected-only coverage stays review.
                var catalog = await Discover(configured.Version, kind);
                await Import(kind, configured.Version, catalog.CatalogId, catalog.Coverage, catalog.Albums);
            }
            return Finish(review);
        }
        catch (OperationCanceledException)
        { lock (state) state.Phase = state.Paused ? "paused" : "partial"; throw; }
        catch { lock (state) state.Phase = "held"; throw; }
        finally
        {
            lock (state) if (ReferenceEquals(state.Active, lifetime)) state.Active = null;
            Interlocked.Exchange(ref nativeMediaWorker, 0);
            activity?.Dispose();
        }
    }
}
