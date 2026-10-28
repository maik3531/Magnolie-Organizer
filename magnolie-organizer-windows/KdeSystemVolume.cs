using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeAudioOutput(string Name, string Description, int Volume, bool Muted, bool Enabled)
{
    internal JsonObject ToJson() => new() { ["name"] = Name, ["description"] = Description,
        ["volume"] = Volume, ["maxVolume"] = 100, ["muted"] = Muted, ["enabled"] = Enabled };
}

internal interface IKdeAudioOutputs
{
    IReadOnlyList<KdeAudioOutput> Read();
    void SetVolume(string name, int volume, Func<bool> permitted);
    void SetMute(string name, bool muted, Func<bool> permitted);
    void SetDefault(string name, Func<bool> permitted);
}

internal sealed class KdeSystemVolume : IAsyncDisposable
{
    internal const string Packet = "kdeconnect.systemvolume";
    internal const string Request = "kdeconnect.systemvolume.request";
    private readonly IKdeAudioOutputs outputs;
    private readonly SemaphoreSlim gate = new(1, 1);

    internal KdeSystemVolume(IKdeAudioOutputs outputs) => this.outputs = outputs;

    internal static KdeSystemVolume? Create()
    {
#if WINDOWS
        return new KdeSystemVolume(new WindowsAudioOutputs());
#else
        return null;
#endif
    }

    internal sealed record Command(string? Name, int? Volume, bool? Muted, bool? Enabled);

    internal static Command Parse(JsonObject body)
    {
        static bool Boolean(JsonNode? node, out bool result)
        { result = false; return node is JsonValue value && value.TryGetValue(out result); }
        if (body.Count == 1 && Boolean(body["requestSinks"], out var request) && request)
            return new(null, null, null, null);
        if (body.Count < 2 || body.Any(pair => pair.Key is not ("name" or "volume" or "muted" or "enabled")) ||
            body["name"] is not JsonValue nameValue || !nameValue.TryGetValue<string>(out var name) ||
            string.IsNullOrEmpty(name) || name.Length > 512 || name.Any(character => character < 32))
            throw new InvalidDataException("invalid_system_volume_request");
        int? volume = null; bool? muted = null; bool? enabled = null;
        if (body.ContainsKey("volume"))
        {
            if (body["volume"] is not JsonValue value || !value.TryGetValue<int>(out var number) || number is < 0 or > 100)
                throw new InvalidDataException("invalid_system_volume_request");
            volume = number;
        }
        if (body.ContainsKey("muted"))
        {
            if (!Boolean(body["muted"], out var flag)) throw new InvalidDataException("invalid_system_volume_request");
            muted = flag;
        }
        if (body.ContainsKey("enabled"))
        {
            if (!Boolean(body["enabled"], out var flag)) throw new InvalidDataException("invalid_system_volume_request");
            enabled = flag;
        }
        return new(name, volume, muted, enabled);
    }

    internal async Task<JsonObject> ReceiveAsync(JsonObject body, Func<bool> permitted, CancellationToken cancellationToken)
    {
        var command = Parse(body);
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await Task.Run(() =>
            {
                void RequireCurrent()
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    if (!permitted()) throw new InvalidOperationException("system_volume_source_changed");
                }
                RequireCurrent();
                var current = outputs.Read();
                if (command.Name is { } name)
                {
                    if (current.Count(output => output.Name == name) != 1)
                        throw new InvalidOperationException("system_volume_output_unavailable");
                    bool Current() { RequireCurrent(); return true; }
                    if (command.Volume is { } volume)
                    {
                        RequireCurrent(); outputs.SetVolume(name, volume, Current);
                        RequireCurrent(); outputs.SetMute(name, command.Muted ?? false, Current);
                    }
                    else if (command.Muted is { } muted) { RequireCurrent(); outputs.SetMute(name, muted, Current); }
                    if (command.Enabled is true) { RequireCurrent(); outputs.SetDefault(name, Current); }
                    current = outputs.Read();
                }
                RequireCurrent();
                return new JsonObject { ["sinkList"] = new JsonArray(current.Take(128).Select(output => (JsonNode)output.ToJson()).ToArray()) };
            }, cancellationToken).ConfigureAwait(false);
        }
        finally { gate.Release(); }
    }

    public ValueTask DisposeAsync() { gate.Dispose(); return ValueTask.CompletedTask; }
}
