using System.Collections.Concurrent;

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
                try { await RunNativeMediaAutomaticOnceAsync(item.Key, token); }
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
        token.ThrowIfCancellationRequested();
        var connection = NativeMediaOnlineConnection(peerId);
        if (connection.Transport != "wifi" || !connection.NativeMediaUiMetadataAvailable()) return;
        var preferences = store.ReadNativeMediaPreferences(peerId);
        if (!preferences.AutomaticWifi || !preferences.PhotosEnabled && !preferences.VideosEnabled) return;
        var state = nativeAutomaticMedia.GetOrAdd(peerId, _ => new(connection));
        if (!ReferenceEquals(state.Connection, connection))
        {
            var replacement = new NativeAutomaticMediaState(connection);
            if (!nativeAutomaticMedia.TryUpdate(peerId, replacement, state)) return;
            state = replacement;
        }
        // Same lane as manual discovery/receive; skip, never enqueue stale work.
        if (Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0) return;
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(token);
        lifetime.CancelAfter(TimeSpan.FromHours(2));
        try
        {
            lock (state)
            {
                if (state.Paused) return;
                state.Active = lifetime; state.Phase = "running";
            }
            var permit = NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);
            void Require()
            {
                lifetime.Token.ThrowIfCancellationRequested(); permit.Require();
                if (connection.Transport != "wifi" || !connection.NativeMediaUiMetadataAvailable() ||
                    store.ReadNativeMediaPreferences(peerId) != preferences)
                    throw DeviceFileControl.Error("file_media_automatic_choice_changed");
            }
            var review = false;
            foreach (var kind in new[] { "images", "video" })
            {
                if (!(kind == "images" ? preferences.PhotosEnabled : preferences.VideosEnabled)) continue;
                Require();
                if (kind == "video" && !connection.NativeMediaUiMetadataAvailable(videos: true)) { review = true; continue; }
                if (store.ReadNativeMediaDestination(peerId, kind) is null) { review = true; continue; }
                await connection.PrepareNativeMediaUiAsync(NativeSavedBook, kind, lifetime.Token); Require();
                var status = await connection.ReadNativeFileSourceStatusAsync(lifetime.Token); Require();
                var configured = await connection.ConfigureNativeMediaSourceAsync(status.Version, kind, true, lifetime.Token); Require();
                var page = await connection.DiscoverNativeMediaAlbumsAsync(configured.Version, kind, token: lifetime.Token); Require();
                var albums = page.Albums.ToList();
                while (page.NextCursor is int after)
                {
                    page = await connection.DiscoverNativeMediaAlbumsAsync(configured.Version, kind, page.CatalogId, after, lifetime.Token); Require();
                    albums.AddRange(page.Albums);
                }
                // No OS permission request or guessed explicit album choice in
                // background. Missing/selected-only coverage stays review.
                review |= page.Coverage != (kind == "images" ? "full_images" : "full_videos") || albums.Any(album => album.NeedsChoice);
                var eligible = albums.Where(album => !album.NeedsChoice).ToArray();
                if (eligible.Length == 0) continue;
                var position = kind == "images" ? state.Images : state.Videos;
                var album = eligible[position % eligible.Length];
                // One complete album per media domain per pass avoids retaining
                // other short-lived IDs across an arbitrarily long transfer.
                // Rotation is fairness only; no mapping/absence comes from it.
                if (kind == "images") state.Images = (position + 1) % eligible.Length;
                else state.Videos = (position + 1) % eligible.Length;
                var outcome = await connection.SynchronizeNativeMediaAlbumAsync(configured.Version, page.CatalogId, album.AlbumId,
                    desktopChoice: false, kind, lifetime.Token, permit.ReplacementConsent, Require);
                Require(); review |= outcome.NeedsReview;
            }
            lock (state) state.Phase = review ? "review" : "content_pass";
        }
        catch (OperationCanceledException)
        { lock (state) state.Phase = state.Paused ? "paused" : "partial"; throw; }
        catch { lock (state) state.Phase = "held"; throw; }
        finally
        {
            lock (state) if (ReferenceEquals(state.Active, lifetime)) state.Active = null;
            Interlocked.Exchange(ref nativeMediaWorker, 0);
        }
    }
}
