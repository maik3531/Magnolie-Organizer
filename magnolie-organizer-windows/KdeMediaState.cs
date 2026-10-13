using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Issue #28: one remote-player cache per authenticated TLS connection.
internal sealed class KdeMediaState
{
    internal const string Packet = "kdeconnect.mpris";
    internal const string Request = "kdeconnect.mpris.request";
    internal object Gate { get; } = new();
    private string token = Guid.NewGuid().ToString("N");
    private Dictionary<string, JsonObject> players = new(StringComparer.Ordinal);
    private bool ready;
    internal bool Started { get; set; }

    private static string Name(JsonNode? node)
    {
        if (node is not JsonValue value || !value.TryGetValue<string>(out var name) ||
            Encoding.UTF8.GetByteCount(name) is < 1 or > 256 || name.Any(c => c < 32))
            throw new InvalidDataException("invalid_media_player");
        return name;
    }

    internal static long Integer(JsonNode? node)
    {
        if (node is JsonValue value)
        {
            if (value.TryGetValue<long>(out var number)) return number;
            if (value.TryGetValue<int>(out var small)) return small;
        }
        throw new InvalidDataException("invalid_media_value");
    }

    internal static JsonObject CommandBody(string player, string action, long? value)
    {
        var body = new JsonObject { ["player"] = Name(JsonValue.Create(player)) };
        if (action is "Play" or "Pause" or "PlayPause" or "Stop" or "Next" or "Previous")
        {
            if (value is not null) throw new InvalidDataException("invalid_media_value");
            body["action"] = action;
        }
        else if (action is "volume" or "position" or "seek")
        {
            long low = action == "seek" ? -9007199254740991 : 0;
            long high = action == "volume" ? 100 : 9007199254740991;
            if (value is null || value < low || value > high) throw new InvalidDataException("invalid_media_value");
            body[action == "volume" ? "setVolume" : action == "position" ? "SetPosition" : "Seek"] = value;
        }
        else throw new InvalidDataException("invalid_media_action");
        return body;
    }

    internal IReadOnlyList<JsonObject> Accept(JsonObject body)
    {
        if (body["transferringAlbumArt"] is JsonValue art && art.TryGetValue<bool>(out var transfer) && transfer) return [];
        string[]? names = null;
        if (body.ContainsKey("playerList"))
        {
            if (body["playerList"] is not JsonArray list || list.Count > 32) throw new InvalidDataException("invalid_media_players");
            names = list.Select(Name).ToArray();
            if (names.Distinct(StringComparer.Ordinal).Count() != names.Length) throw new InvalidDataException("invalid_media_players");
        }
        var player = body.ContainsKey("player") ? Name(body["player"]) : null;
        var update = new JsonObject();
        foreach (var key in new[] { "title", "artist", "album", "nowPlaying" })
            if (body.ContainsKey(key))
            {
                if (body[key] is not JsonValue text || !text.TryGetValue<string>(out var value))
                    throw new InvalidDataException("invalid_media_metadata");
                var clean = new StringBuilder(); var bytes = 0;
                foreach (var rune in value.EnumerateRunes())
                {
                    if (Rune.IsControl(rune)) continue;
                    if (bytes + rune.Utf8SequenceLength > 128) break;
                    clean.Append(rune.ToString()); bytes += rune.Utf8SequenceLength;
                }
                update[key] = clean.ToString();
            }
        foreach (var key in new[] { "isPlaying", "canPause", "canPlay", "canGoNext", "canGoPrevious", "canSeek" })
            if (body.ContainsKey(key))
            {
                if (body[key] is not JsonValue flag || !flag.TryGetValue<bool>(out var value)) throw new InvalidDataException("invalid_media_capability");
                update[key] = value;
            }
        foreach (var key in new[] { "pos", "length", "volume" })
            if (body.ContainsKey(key))
            {
                if (body[key] is not JsonValue number || !number.TryGetValue<double>(out var value) || !double.IsFinite(value) ||
                    value < 0 || value > (key == "volume" ? 100 : 9007199254740991)) throw new InvalidDataException("invalid_media_value");
                update[key] = (long)value;
            }
        lock (Gate)
        {
            var added = Array.Empty<string>();
            if (names is not null)
            {
                added = names.Where(name => !players.ContainsKey(name)).ToArray();
                if (!names.ToHashSet(StringComparer.Ordinal).SetEquals(players.Keys)) token = Guid.NewGuid().ToString("N");
                players = names.ToDictionary(name => name, name => players.GetValueOrDefault(name) ?? new JsonObject(), StringComparer.Ordinal);
                ready = true;
            }
            if (player is not null && players.TryGetValue(player, out var state))
                foreach (var (key, value) in update) state[key] = value?.DeepClone();
            return added.Select(name => new JsonObject { ["player"] = name, ["requestNowPlaying"] = true, ["requestVolume"] = true }).ToArray();
        }
    }

    internal JsonObject Snapshot(string deviceId)
    {
        lock (Gate)
        {
            var list = new JsonArray();
            foreach (var (name, value) in players)
            {
                var state = value.DeepClone().AsObject(); state["player"] = name; list.Add(state);
            }
            return new JsonObject { ["available"] = true, ["device_id"] = deviceId, ["token"] = token, ["ready"] = ready, ["players"] = list };
        }
    }

    internal JsonObject Command(string expectedToken, string player, string action, long? value)
    {
        var body = CommandBody(player, action, value);
        lock (Gate)
        {
            if (expectedToken != token || !ready || !players.TryGetValue(player, out var flags)) throw new InvalidDataException("media_source_changed");
            var required = action switch { "Play" => "canPlay", "Pause" => "canPause", "Next" => "canGoNext",
                "Previous" => "canGoPrevious", "seek" or "position" => "canSeek", _ => "" };
            if (required.Length != 0 && flags[required] is JsonValue flag && flag.TryGetValue<bool>(out var enabled) && !enabled)
                throw new InvalidDataException("media_action_unavailable");
            return body;
        }
    }
}
