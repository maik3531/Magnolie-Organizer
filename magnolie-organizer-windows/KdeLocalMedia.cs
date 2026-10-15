using System.Text;
using System.Text.Json.Nodes;
#if WINDOWS
using Windows.Media.Control;
#endif

namespace MagnolieOrganizer.Windows;

internal interface IKdeLocalMedia
{
    Task<IReadOnlyList<JsonObject>> ReceiveAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken);
    JsonObject Settings() => new() { ["available"] = false };
    JsonObject Configure(string slot, string application) => throw new InvalidOperationException("local_media_unavailable");
}

internal static class KdeLocalMedia
{
    internal static IKdeLocalMedia? Create(string? directory = null)
    {
#if WINDOWS
        try
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            var manager = GlobalSystemMediaTransportControlsSessionManager.RequestAsync().AsTask(deadline.Token)
                .ConfigureAwait(false).GetAwaiter().GetResult();
            return new WindowsMedia(manager, new KdeRegisteredPlayers(directory));
        }
        catch (Exception) { return null; }
#else
        return null;
#endif
    }

#if WINDOWS
    private sealed class WindowsMedia(GlobalSystemMediaTransportControlsSessionManager manager, KdeRegisteredPlayers registered) : IKdeLocalMedia
    {
        private readonly SemaphoreSlim gate = new(1, 1);
        private readonly Dictionary<GlobalSystemMediaTransportControlsSession, string> names = new();
        public JsonObject Settings() => registered.Settings();
        public JsonObject Configure(string slot, string application) => registered.Configure(slot, application);

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
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            deadline.CancelAfter(TimeSpan.FromSeconds(3));
            var token = deadline.Token;
            await gate.WaitAsync(token).ConfigureAwait(false);
            try
            {
                if (!permitted()) throw new InvalidOperationException("local_media_source_changed");
                var sessions = manager.GetSessions().Take(32).ToArray();
                foreach (var old in names.Keys.Except(sessions).ToArray()) names.Remove(old);
                foreach (var session in sessions)
                    if (!names.ContainsKey(session)) names.Add(session, DisplayName(session.SourceAppUserModelId) + " · " + Guid.NewGuid().ToString("N")[..8]);
                var choices = registered.Choices();
                var list = new JsonObject { ["playerList"] = new JsonArray((choices.Count > 0 ? choices.Keys.AsEnumerable() : names.Values)
                    .Select(name => (JsonNode?)JsonValue.Create(name)).ToArray()), ["supportAlbumArtPayload"] = false };
                if (body["requestPlayerList"]?.GetValue<bool>() == true) return [list];
                var player = body["player"]?.GetValue<string>() ?? "";
                var selected = choices.TryGetValue(player, out var assigned)
                    ? sessions.FirstOrDefault(session => assigned.App.SessionIds.Contains(session.SourceAppUserModelId, StringComparer.OrdinalIgnoreCase))
                    : choices.Count > 0 ? null : names.FirstOrDefault(value => value.Value == player).Key;
                if (selected is null && choices.ContainsKey(player)) return [registered.Closed(player, body, permitted)];
                if (selected is null) return [list];
                var keys = new[] { "action", "setVolume", "SetPosition", "Seek" }.Where(body.ContainsKey).ToArray();
                if (keys.Length > 1) throw new InvalidDataException("invalid_local_media_request");
                if (keys.Length == 1)
                {
                    var key = keys[0];
                    var action = key == "action" ? body[key]!.GetValue<string>() : key == "setVolume" ? "volume" : key == "Seek" ? "seek" : "position";
                    long? value = key == "action" ? null : KdeMediaState.Integer(body[key]);
                    _ = KdeMediaState.CommandBody(player, action, value);
                    var controls = selected.GetPlaybackInfo().Controls;
                    if (!permitted() || !manager.GetSessions().Contains(selected)) throw new InvalidOperationException("local_media_source_changed");
                    bool accepted;
                    switch (action)
                    {
                        case "Play" when controls.IsPlayEnabled: accepted = await selected.TryPlayAsync().AsTask(token).ConfigureAwait(false); break;
                        case "Pause" when controls.IsPauseEnabled: accepted = await selected.TryPauseAsync().AsTask(token).ConfigureAwait(false); break;
                        case "PlayPause" when controls.IsPlayPauseToggleEnabled: accepted = await selected.TryTogglePlayPauseAsync().AsTask(token).ConfigureAwait(false); break;
                        case "Stop" when controls.IsStopEnabled: accepted = await selected.TryStopAsync().AsTask(token).ConfigureAwait(false); break;
                        case "Next" when controls.IsNextEnabled: accepted = await selected.TrySkipNextAsync().AsTask(token).ConfigureAwait(false); break;
                        case "Previous" when controls.IsPreviousEnabled: accepted = await selected.TrySkipPreviousAsync().AsTask(token).ConfigureAwait(false); break;
                        case "position" or "seek" when controls.IsPlaybackPositionEnabled:
                            var timeline = selected.GetTimelineProperties();
                            var ticks = action == "position" ? checked(value!.Value * TimeSpan.TicksPerMillisecond) : checked(timeline.Position.Ticks + value!.Value * 10);
                            ticks = Math.Max(ticks, timeline.StartTime.Ticks);
                            // Some native players support seeking before publishing
                            // a duration. A zero/unknown EndTime is not a zero-length
                            // track and must not turn every requested position into 0.
                            if (timeline.EndTime > timeline.StartTime) ticks = Math.Min(ticks, timeline.EndTime.Ticks);
                            accepted = await selected.TryChangePlaybackPositionAsync(ticks).AsTask(token).ConfigureAwait(false); break;
                        default: throw new InvalidOperationException("local_media_action_unavailable");
                    }
                    if (!accepted) throw new InvalidOperationException("local_media_action_unavailable");
                }
                var properties = await selected.TryGetMediaPropertiesAsync().AsTask(token).ConfigureAwait(false);
                var info = selected.GetPlaybackInfo(); var position = selected.GetTimelineProperties();
                if (!permitted() || !manager.GetSessions().Contains(selected)) throw new InvalidOperationException("local_media_source_changed");
                return [new JsonObject { ["player"] = player, ["title"] = properties.Title, ["artist"] = properties.Artist,
                    ["album"] = properties.AlbumTitle, ["isPlaying"] = info.PlaybackStatus == GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing,
                    ["canPlay"] = info.Controls.IsPlayEnabled, ["canPause"] = info.Controls.IsPauseEnabled,
                    ["canGoNext"] = info.Controls.IsNextEnabled, ["canGoPrevious"] = info.Controls.IsPreviousEnabled,
                    ["canSeek"] = info.Controls.IsPlaybackPositionEnabled,
                    ["pos"] = Math.Max(0, position.Position.Ticks / TimeSpan.TicksPerMillisecond),
                    ["length"] = Math.Max(0, position.EndTime.Ticks / TimeSpan.TicksPerMillisecond) }];
            }
            finally { gate.Release(); }
        }
    }
#endif
}
