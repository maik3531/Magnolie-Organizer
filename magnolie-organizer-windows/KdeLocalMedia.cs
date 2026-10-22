using System.Text;
using System.Text.Json.Nodes;
#if WINDOWS
using Windows.Media.Control;
using Windows.Media;
#endif

namespace MagnolieOrganizer.Windows;

internal interface IKdeLocalMedia : IAsyncDisposable
{
    ValueTask IAsyncDisposable.DisposeAsync() => ValueTask.CompletedTask;
    Task<IReadOnlyList<JsonObject>> ReceiveAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken);
    JsonObject Settings() => new() { ["available"] = false };
    JsonObject Configure(string slot, string application) => throw new InvalidOperationException("local_media_unavailable");
    JsonObject OpenFile(string slot, string application, string path) => throw new InvalidOperationException("local_media_unavailable");
    Task<KdeMediaArtwork?> ArtworkAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken) => Task.FromResult<KdeMediaArtwork?>(null);
}

internal sealed record KdeMediaArtwork(JsonObject Body, byte[] Data);

internal static class KdeLocalMedia
{
    internal const string CurrentPlayer = "Magnolie · Aktuelle Wiedergabe";
    internal static IKdeLocalMedia? Create(string? directory = null, KdeRegisteredPlayers? registered = null)
    {
#if WINDOWS
        try
        {
            return new WindowsMedia(registered ?? new KdeRegisteredPlayers(directory));
        }
        catch (Exception) { return null; }
#else
        return null;
#endif
    }

#if WINDOWS
    private sealed class WindowsMedia : IKdeLocalMedia
    {
        private readonly KdeRegisteredPlayers registered;
        private GlobalSystemMediaTransportControlsSessionManager manager = null!;
        private readonly System.Collections.Concurrent.BlockingCollection<Action> work = new(32);
        private readonly CancellationTokenSource lifetime = new();
        private readonly Thread owner;
        private int disposed;
        private readonly SemaphoreSlim gate = new(1, 1);
        private readonly Dictionary<GlobalSystemMediaTransportControlsSession, string> names = new();
        private readonly Dictionary<string, (string Url, byte[] Data, GlobalSystemMediaTransportControlsSession Source)> artwork = new(StringComparer.Ordinal);

        internal WindowsMedia(KdeRegisteredPlayers registered)
        {
            this.registered = registered;
            owner = new Thread(() =>
            {
                foreach (var action in work.GetConsumingEnumerable()) action();
                names.Clear(); artwork.Clear();
            }) { IsBackground = true, Name = "Magnolie media sessions" };
            owner.SetApartmentState(ApartmentState.MTA); owner.Start();
            try
            {
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                Dispatch(() => { manager = GlobalSystemMediaTransportControlsSessionManager.RequestAsync().AsTask(deadline.Token).GetAwaiter().GetResult(); return true; }, deadline.Token).GetAwaiter().GetResult();
            }
            catch { DisposeAsync().GetAwaiter().GetResult(); throw; }
        }

        private Task<T> Dispatch<T>(Func<T> action, CancellationToken token)
        {
            var completion = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
            try
            {
                if (!work.TryAdd(() =>
                {
                    try { token.ThrowIfCancellationRequested(); lifetime.Token.ThrowIfCancellationRequested(); completion.TrySetResult(action()); }
                    catch (OperationCanceledException error) { completion.TrySetCanceled(error.CancellationToken); }
                    catch (Exception error) { completion.TrySetException(error); }
                })) completion.TrySetException(new InvalidOperationException("local_media_busy"));
            }
            catch (InvalidOperationException error) { completion.TrySetException(error); }
            return completion.Task;
        }

        public ValueTask DisposeAsync()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return ValueTask.CompletedTask;
            lifetime.Cancel(); work.CompleteAdding();
            if (owner.Join(TimeSpan.FromSeconds(5))) { work.Dispose(); lifetime.Dispose(); gate.Dispose(); }
            return ValueTask.CompletedTask;
        }
        public JsonObject Settings() => registered.Settings();
        public JsonObject Configure(string slot, string application) => registered.Configure(slot, application);
        public JsonObject OpenFile(string slot, string application, string path) => registered.OpenFile(slot, application, path);

        private static string DisplayName(string value)
        {
            var text = new StringBuilder(); var bytes = 0;
            foreach (var rune in value.EnumerateRunes())
            {
                if (Rune.IsControl(rune)) continue;
                if (bytes + rune.Utf8SequenceLength > 200) break;
                text.Append(rune.ToString()); bytes += rune.Utf8SequenceLength;
            }
            return text.Length == 0 ? "Media" : text.ToString();
        }

        public async Task<IReadOnlyList<JsonObject>> ReceiveAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken)
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, lifetime.Token);
            deadline.CancelAfter(TimeSpan.FromSeconds(3)); var token = deadline.Token;
            return await Dispatch(() => ReceiveOnThread(body, permitted, token), token).WaitAsync(token).ConfigureAwait(false);
        }

        private IReadOnlyList<JsonObject> ReceiveOnThread(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken)
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, lifetime.Token);
            deadline.CancelAfter(TimeSpan.FromSeconds(3));
            var token = deadline.Token;
            gate.Wait(token);
            try
            {
                if (!permitted()) throw new InvalidOperationException("local_media_source_changed");
                var sessions = manager.GetSessions().Take(32).ToArray();
                foreach (var old in names.Keys.Except(sessions).ToArray()) names.Remove(old);
                foreach (var session in sessions)
                    if (!names.ContainsKey(session)) names.Add(session, DisplayName(session.SourceAppUserModelId) + " · " + Guid.NewGuid().ToString("N")[..8]);
                var choices = registered.Choices();
                var active = names.Where(value => !choices.Values.Any(choice =>
                    choice.App.SessionIds.Contains(value.Key.SourceAppUserModelId, StringComparer.OrdinalIgnoreCase))).ToArray();
                var list = new JsonObject { ["playerList"] = new JsonArray(new[] { CurrentPlayer }.Concat(choices.Keys).Concat(active.Select(value => value.Value)).Distinct(StringComparer.Ordinal).Take(32)
                    .Select(name => (JsonNode?)JsonValue.Create(name)).ToArray()), ["supportAlbumArtPayload"] = true };
                foreach (var old in artwork.Keys.Except(choices.Keys.Concat(names.Values).Append(CurrentPlayer)).ToArray()) artwork.Remove(old);
                if (body["requestPlayerList"]?.GetValue<bool>() == true) return [list];
                var player = body["player"]?.GetValue<string>() ?? "";
                var selected = player == CurrentPlayer ? manager.GetCurrentSession() : choices.TryGetValue(player, out var assigned)
                    ? sessions.FirstOrDefault(session => assigned.App.SessionIds.Contains(session.SourceAppUserModelId, StringComparer.OrdinalIgnoreCase))
                    : active.FirstOrDefault(value => value.Value == player).Key;
                if (selected is null && choices.ContainsKey(player)) { artwork.Remove(player); return [registered.Closed(player, body, permitted)]; }
                if (selected is null && player == CurrentPlayer)
                {
                    artwork.Remove(player);
                    if (new[] { "action", "setVolume", "SetPosition", "Seek", "setShuffle", "setLoopStatus" }.Any(body.ContainsKey)) throw new InvalidOperationException("local_media_action_unavailable");
                    return [new JsonObject { ["player"] = player, ["title"] = "", ["albumArtUrl"] = "", ["isPlaying"] = false,
                        ["canPlay"] = false, ["canPause"] = false, ["canGoNext"] = false, ["canGoPrevious"] = false, ["canSeek"] = false }];
                }
                if (selected is null) return [list];
                var keys = new[] { "action", "setVolume", "SetPosition", "Seek", "setShuffle", "setLoopStatus" }.Where(body.ContainsKey).ToArray();
                if (keys.Length > 1) throw new InvalidDataException("invalid_local_media_request");
                if (keys.Length == 1)
                {
                    var key = keys[0];
                    var action = key == "action" ? body[key]!.GetValue<string>() : key == "setShuffle" ? "shuffle" : key == "setLoopStatus" ? "loop" : key == "setVolume" ? "volume" : key == "Seek" ? "seek" : "position";
                    long? value = key is "action" or "setShuffle" or "setLoopStatus" ? null : KdeMediaState.Integer(body[key]);
                    if (action == "shuffle") _ = body[key]!.GetValue<bool>();
                    else if (action == "loop")
                    {
                        if (body[key]!.GetValue<string>() is not ("None" or "Track" or "Playlist")) throw new InvalidDataException("invalid_local_media_request");
                    }
                    else _ = KdeMediaState.CommandBody(player, action, value);
                    var controls = selected.GetPlaybackInfo().Controls;
                    if (!permitted() || !manager.GetSessions().Contains(selected)) throw new InvalidOperationException("local_media_source_changed");
                    bool accepted;
                    switch (action)
                    {
                        case "Play" when controls.IsPlayEnabled: accepted = selected.TryPlayAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "Pause" when controls.IsPauseEnabled: accepted = selected.TryPauseAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "PlayPause" when controls.IsPlayPauseToggleEnabled: accepted = selected.TryTogglePlayPauseAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "Stop" when controls.IsStopEnabled: accepted = selected.TryStopAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "Next" when controls.IsNextEnabled: accepted = selected.TrySkipNextAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "Previous" when controls.IsPreviousEnabled: accepted = selected.TrySkipPreviousAsync().AsTask(token).GetAwaiter().GetResult(); break;
                        case "shuffle" when controls.IsShuffleEnabled: accepted = selected.TryChangeShuffleActiveAsync(body[key]!.GetValue<bool>()).AsTask(token).GetAwaiter().GetResult(); break;
                        case "loop" when controls.IsRepeatEnabled:
                            var repeat = body[key]!.GetValue<string>() switch { "Track" => MediaPlaybackAutoRepeatMode.Track, "Playlist" => MediaPlaybackAutoRepeatMode.List, _ => MediaPlaybackAutoRepeatMode.None };
                            accepted = selected.TryChangeAutoRepeatModeAsync(repeat).AsTask(token).GetAwaiter().GetResult(); break;
                        case "position" or "seek" when controls.IsPlaybackPositionEnabled:
                            var timeline = selected.GetTimelineProperties();
                            var ticks = action == "position" ? checked(value!.Value * TimeSpan.TicksPerMillisecond) : checked(timeline.Position.Ticks + value!.Value * 10);
                            ticks = Math.Max(ticks, timeline.StartTime.Ticks);
                            // Some native players support seeking before publishing
                            // a duration. A zero/unknown EndTime is not a zero-length
                            // track and must not turn every requested position into 0.
                            if (timeline.EndTime > timeline.StartTime) ticks = Math.Min(ticks, timeline.EndTime.Ticks);
                            accepted = selected.TryChangePlaybackPositionAsync(ticks).AsTask(token).GetAwaiter().GetResult(); break;
                        default: throw new InvalidOperationException("local_media_action_unavailable");
                    }
                    if (!accepted) throw new InvalidOperationException("local_media_action_unavailable");
                }
                var properties = selected.TryGetMediaPropertiesAsync().AsTask(token).GetAwaiter().GetResult();
                var info = selected.GetPlaybackInfo(); var position = selected.GetTimelineProperties();
                if (!permitted() || !manager.GetSessions().Contains(selected)) throw new InvalidOperationException("local_media_source_changed");
                var result = new JsonObject { ["player"] = player, ["title"] = properties.Title, ["artist"] = properties.Artist, ["albumArtUrl"] = "",
                    ["album"] = properties.AlbumTitle, ["isPlaying"] = info.PlaybackStatus == GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing,
                    ["canPlay"] = info.Controls.IsPlayEnabled, ["canPause"] = info.Controls.IsPauseEnabled,
                    ["canGoNext"] = info.Controls.IsNextEnabled, ["canGoPrevious"] = info.Controls.IsPreviousEnabled,
                    ["canSeek"] = info.Controls.IsPlaybackPositionEnabled,
                    ["pos"] = Math.Max(0, position.Position.Ticks / TimeSpan.TicksPerMillisecond),
                    ["length"] = Math.Max(0, position.EndTime.Ticks / TimeSpan.TicksPerMillisecond) };
                artwork.Remove(player);
                if (info.Controls.IsShuffleEnabled && info.IsShuffleActive is { } shuffle) result["shuffle"] = shuffle;
                if (info.Controls.IsRepeatEnabled && info.AutoRepeatMode is { } repeatMode)
                    result["loopStatus"] = repeatMode switch { MediaPlaybackAutoRepeatMode.Track => "Track", MediaPlaybackAutoRepeatMode.List => "Playlist", _ => "None" };
                if (properties.Thumbnail is not null)
                {
                    try
                    {
                        using var thumbnail = properties.Thumbnail.OpenReadAsync().AsTask(token).GetAwaiter().GetResult();
                        if (thumbnail.Size is > 0 and <= 2 * 1024 * 1024)
                        {
                            var bytes = new byte[(int)thumbnail.Size];
                            using var input = thumbnail.AsStreamForRead();
                            input.ReadExactlyAsync(bytes, token).GetAwaiter().GetResult();
                            var url = "kdeconnect://magnolie/cover/" + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
                            artwork[player] = (url, bytes, selected); result["albumArtUrl"] = url;
                        }
                    }
                    catch (Exception error) when (error is not OperationCanceledException)
                    { /* An unavailable cover must not disable the actual player controls. */ }
                }
                if (!permitted() || !manager.GetSessions().Contains(selected)) throw new InvalidOperationException("local_media_source_changed");
                return [result];
            }
            finally { gate.Release(); }
        }

        public async Task<KdeMediaArtwork?> ArtworkAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken)
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, lifetime.Token);
            deadline.CancelAfter(TimeSpan.FromSeconds(3)); var token = deadline.Token;
            return await Dispatch(() => ArtworkOnThread(body, permitted, token), token).WaitAsync(token).ConfigureAwait(false);
        }

        private KdeMediaArtwork? ArtworkOnThread(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken)
        {
            var player = body["player"]?.GetValue<string>() ?? "";
            var requested = body["albumArtUrl"]?.GetValue<string>() ?? "";
            gate.Wait(cancellationToken);
            try
            {
                if (!permitted() || !artwork.TryGetValue(player, out var cover) || cover.Url != requested) return null;
                if (!manager.GetSessions().Contains(cover.Source)) return null;
                var choices = registered.Choices();
                if (choices.TryGetValue(player, out var choice))
                {
                    if (!choice.App.SessionIds.Contains(cover.Source.SourceAppUserModelId, StringComparer.OrdinalIgnoreCase)) return null;
                }
                else if (player == CurrentPlayer) { if (manager.GetCurrentSession() != cover.Source) return null; }
                else if (!names.TryGetValue(cover.Source, out var activeName) || activeName != player) return null;
                return new KdeMediaArtwork(new JsonObject { ["player"] = player, ["albumArtUrl"] = requested, ["transferringAlbumArt"] = true }, cover.Data);
            }
            finally { gate.Release(); }
        }
    }
#endif
}
