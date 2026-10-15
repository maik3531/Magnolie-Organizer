using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeRegisteredPlayer(string Id, string Name, string Executable, string[] SessionIds);

// Network requests name a previously advertised slot, never a command or path.
internal sealed class KdeRegisteredPlayers
{
    private readonly object gate = new();
    private readonly string? settingsPath;
    private readonly Func<IReadOnlyList<KdeRegisteredPlayer>> applications;
    private readonly Action<KdeRegisteredPlayer> launch;
    private readonly Dictionary<string, string> selected = new() { ["music"] = "", ["video"] = "" };
    private readonly Dictionary<string, long> launchUntil = new();

    internal KdeRegisteredPlayers(string? directory, Func<IReadOnlyList<KdeRegisteredPlayer>>? applications = null,
        Action<KdeRegisteredPlayer>? launch = null)
    {
        settingsPath = directory is null ? null : Path.Combine(directory, "media-player.json");
        this.applications = applications ?? Installed;
        this.launch = launch ?? (app =>
        {
            if (!File.Exists(app.Executable)) throw new InvalidOperationException("media_application_unavailable");
            using var process = Process.Start(new ProcessStartInfo(app.Executable) { UseShellExecute = false });
            if (process is null) throw new InvalidOperationException("media_application_start_failed");
        });
        if (settingsPath is not null && File.Exists(settingsPath))
            try
            {
                var saved = JsonNode.Parse(new AtomicStore().Read(settingsPath, 4096)!)?.AsObject();
                foreach (var slot in selected.Keys.ToArray())
                    if (saved?[slot] is JsonValue value && value.TryGetValue<string>(out var id) && id.Length <= 512)
                        selected[slot] = id;
            }
            catch (Exception error) when (error is IOException or JsonException or InvalidOperationException) { }
        else if (directory is not null)
        {
            var first = this.applications().FirstOrDefault();
            if (first is not null) { selected["music"] = first.Id; selected["video"] = first.Id; }
        }
    }

    internal Dictionary<string, (string Slot, KdeRegisteredPlayer App)> Choices()
    {
        lock (gate)
        {
            var apps = applications().Take(64).ToDictionary(app => app.Id, StringComparer.Ordinal);
            var result = new Dictionary<string, (string, KdeRegisteredPlayer)>();
            foreach (var (slot, id) in selected)
                if (apps.TryGetValue(id, out var app))
                    result[$"Magnolie · {(slot == "music" ? "Music" : "Video")} · {app.Name[..Math.Min(app.Name.Length, 100)]}"] = (slot, app);
            return result;
        }
    }

    internal JsonObject Settings()
    {
        lock (gate)
        {
            var apps = applications().Take(64).ToArray();
            return new JsonObject { ["available"] = apps.Length > 0, ["music"] = selected["music"], ["video"] = selected["video"],
                ["applications"] = new JsonArray(apps.Select(app => (JsonNode)new JsonObject { ["id"] = app.Id, ["name"] = app.Name }).ToArray()) };
        }
    }

    internal JsonObject Configure(string slot, string application)
    {
        lock (gate)
        {
            if (!selected.ContainsKey(slot)) throw new InvalidDataException("invalid_media_slot");
            if (application != "" && !applications().Take(64).Any(app => app.Id == application))
                throw new InvalidOperationException("media_application_unavailable");
            var next = new Dictionary<string, string>(selected) { [slot] = application };
            if (settingsPath is not null)
                new AtomicStore().Write(settingsPath, JsonSerializer.Serialize(next), 4096);
            selected[slot] = application; launchUntil.Remove(slot);
            return Settings();
        }
    }

    internal JsonObject Closed(string alias, JsonObject body, Func<bool> permitted)
    {
        lock (gate)
        {
            if (!Choices().TryGetValue(alias, out var choice)) throw new InvalidOperationException("media_application_unavailable");
            var keys = new[] { "action", "setVolume", "SetPosition", "Seek" }.Where(body.ContainsKey).ToArray();
            if (keys.Length > 1 || keys.Length == 1 && (keys[0] != "action" || body["action"]?.GetValue<string>() is not ("Play" or "PlayPause")))
                throw new InvalidOperationException("local_media_action_unavailable");
            if (!permitted()) throw new InvalidOperationException("local_media_source_changed");
            if (keys.Length == 1 && (!launchUntil.TryGetValue(choice.Slot, out var until) || Environment.TickCount64 >= until))
            {
                launch(choice.App); launchUntil[choice.Slot] = Environment.TickCount64 + 10000;
            }
            return new JsonObject { ["player"] = alias, ["title"] = "", ["isPlaying"] = false, ["canPlay"] = true,
                ["canPause"] = false, ["canGoNext"] = false, ["canGoPrevious"] = false, ["canSeek"] = false };
        }
    }

    internal static IReadOnlyList<KdeRegisteredPlayer> Installed()
    {
        if (!OperatingSystem.IsWindows()) return [];
        var result = new Dictionary<string, KdeRegisteredPlayer>(StringComparer.OrdinalIgnoreCase);
        foreach (var (hiveName, hive) in new[] { ("user", Registry.CurrentUser), ("machine", Registry.LocalMachine) })
        {
            using var registered = hive.OpenSubKey(@"SOFTWARE\RegisteredApplications");
            foreach (var name in registered?.GetValueNames().Take(512) ?? [])
            {
                if (name.Length > 200 || registered?.GetValue(name) is not string capabilitiesPath) continue;
                using var capabilities = hive.OpenSubKey(capabilitiesPath);
                using var associations = capabilities?.OpenSubKey("FileAssociations");
                foreach (var extension in new[] { ".mp3", ".mp4" })
                {
                    if (associations?.GetValue(extension) is not string progId || progId.Length > 256 || progId.Contains('\\')) continue;
                    using var commandKey = hive.OpenSubKey(@"SOFTWARE\Classes\" + progId + @"\shell\open\command");
                    if (commandKey?.GetValue(null) is not string command) continue;
                    var match = Regex.Match(command, "^\\s*\"(?<path>[^\"]+\\.exe)\"(?:\\s|$)|^\\s*(?<path>[^\"]+?\\.exe)(?:\\s|$)", RegexOptions.IgnoreCase);
                    var executable = match.Groups["path"].Value;
                    if (!match.Success || !Path.IsPathFullyQualified(executable) || !File.Exists(executable)) continue;
                    var stem = Path.GetFileNameWithoutExtension(executable);
                    var display = capabilities?.GetValue("ApplicationName") as string;
                    if (string.IsNullOrWhiteSpace(display) || display.StartsWith('@')) display = stem;
                    result.TryAdd(Path.GetFileName(executable), new("registered:" + hiveName + ":" + name,
                        display, executable, [stem, Path.GetFileName(executable)]));
                }
            }
            using var paths = hive.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths");
            if (paths is null) continue;
            foreach (var name in paths.GetSubKeyNames().Take(2048))
            {
                if (!new[] { "wmplayer.exe", "vlc.exe", "mpv.exe", "foobar2000.exe", "winamp.exe", "MusicBee.exe", "mpc-hc.exe", "mpc-hc64.exe", "PotPlayerMini.exe", "PotPlayerMini64.exe" }.Contains(name, StringComparer.OrdinalIgnoreCase)) continue;
                using var entry = paths.OpenSubKey(name);
                var executable = (entry?.GetValue(null) as string)?.Trim('"');
                if (executable is null || !Path.IsPathFullyQualified(executable) || !File.Exists(executable) ||
                    !string.Equals(Path.GetFileName(executable), name, StringComparison.OrdinalIgnoreCase)) continue;
                var stem = Path.GetFileNameWithoutExtension(name);
                var ids = name.Equals("wmplayer.exe", StringComparison.OrdinalIgnoreCase)
                    ? new[] { "Microsoft.Windows.MediaPlayer32", stem, name } : new[] { stem, name };
                result.TryAdd(name, new(hiveName + ":" + name, stem, executable, ids));
            }
        }
        return result.Values.OrderBy(app => app.Name, StringComparer.OrdinalIgnoreCase).Take(64).ToArray();
    }
}
