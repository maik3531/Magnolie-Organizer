using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class KdeInputProtocol
{
    internal const string Request = "kdeconnect.mousepad.request";
    internal const string KeyboardState = "kdeconnect.mousepad.keyboardstate";
    internal const string Presenter = "kdeconnect.presenter";
    internal static readonly string[] Clicks = ["singleclick", "doubleclick", "middleclick", "rightclick", "singlehold", "singlerelease"];
    internal static readonly string[] Modifiers = ["ctrl", "alt", "shift", "super"];

    internal static JsonObject Input(JsonObject body)
    {
        var permitted = Clicks.Concat(Modifiers).Concat(["dx", "dy", "x", "y", "scroll", "key", "specialKey", "sendAck"]).ToHashSet(StringComparer.Ordinal);
        if (body.Any(pair => !permitted.Contains(pair.Key))) throw new InvalidDataException("invalid_remote_input");
        var data = JsonSerializer.SerializeToElement(body);
        foreach (var name in Clicks.Concat(Modifiers).Concat(["scroll", "sendAck"]))
            if (data.TryGetProperty(name, out var flag) && flag.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                throw new InvalidDataException("invalid_remote_input_flag");
        foreach (var name in new[] { "dx", "dy", "x", "y" })
            if (data.TryGetProperty(name, out var axis))
            {
                var bound = name is "x" or "y" ? 32768 : 4096;
                if (axis.ValueKind != JsonValueKind.Number || !axis.TryGetDouble(out var value) || !double.IsFinite(value) || value < -bound || value > bound)
                    throw new InvalidDataException("invalid_remote_input_coordinate");
            }
        if (body.ContainsKey("x") != body.ContainsKey("y") || body.ContainsKey("x") && (body.ContainsKey("dx") || body.ContainsKey("dy")))
            throw new InvalidDataException("invalid_remote_input_coordinate");
        if (data.TryGetProperty("key", out var text))
        {
            if (text.ValueKind != JsonValueKind.String) throw new InvalidDataException("invalid_remote_input_text");
            var value = text.GetString()!;
            if (Encoding.UTF8.GetByteCount(value) is < 1 or > 1024 || value.Any(c => c < 32)) throw new InvalidDataException("invalid_remote_input_text");
        }
        if (data.TryGetProperty("specialKey", out var special) && (special.ValueKind != JsonValueKind.Number || !special.TryGetInt32(out var key) || key is < 1 or > 32))
            throw new InvalidDataException("invalid_remote_input_key");
        if (body.ContainsKey("key") && body.ContainsKey("specialKey")) throw new InvalidDataException("invalid_remote_input_key");
        bool Flag(string name) => data.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        var clicks = Clicks.Count(Flag);
        var keyboard = body.ContainsKey("key") || body.ContainsKey("specialKey");
        var move = new[] { "x", "y", "dx", "dy" }.Any(body.ContainsKey);
        var scroll = Flag("scroll");
        if (clicks > 1 || keyboard && (clicks != 0 || move || scroll) || clicks != 0 && (move || scroll) ||
            scroll && body.ContainsKey("x") || Modifiers.Any(Flag) && !keyboard)
            throw new InvalidDataException("ambiguous_remote_input");
        if (!keyboard && clicks == 0 && !move) throw new InvalidDataException("empty_remote_input");
        return body.DeepClone().AsObject();
    }

    internal static JsonObject Pointer(JsonObject body)
    {
        if (body.Any(pair => pair.Key is not ("dx" or "dy" or "stop"))) throw new InvalidDataException("invalid_presenter_input");
        var data = JsonSerializer.SerializeToElement(body);
        if (data.TryGetProperty("stop", out var stop))
        {
            if (stop.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new InvalidDataException("invalid_presenter_input");
            if (stop.GetBoolean())
            {
                if (body.Count != 1) throw new InvalidDataException("invalid_presenter_input");
                return new JsonObject { ["stop"] = true };
            }
        }
        foreach (var name in new[] { "dx", "dy" })
            if (!data.TryGetProperty(name, out var axis) || axis.ValueKind != JsonValueKind.Number ||
                !axis.TryGetDouble(out var value) || !double.IsFinite(value) || value is < -1 or > 1)
                throw new InvalidDataException("invalid_presenter_input");
        return body.DeepClone().AsObject();
    }
}

internal interface IKdeInputSink : IDisposable
{
    bool Keyboard { get; }
    void Apply(JsonObject body);
    void Release();
}

internal sealed class KdeInputTarget(IKdeInputSink sink)
{
    internal object Gate { get; } = new();
    private object? owner;
    private string token = "";
    private Func<bool> permitted = () => false;

    internal void Arm(object source, string targetToken, Func<bool> permission)
    {
        if (!Guid.TryParse(targetToken, out _) || !permission()) throw new InvalidOperationException("input_target_not_ready");
        lock (Gate) { Disarm(); owner = source; token = targetToken; permitted = permission; }
    }

    internal bool Disarm(object? source = null, string? targetToken = null)
    {
        lock (Gate)
        {
            if (source is not null && !ReferenceEquals(owner, source) || targetToken is not null && targetToken != token) return false;
            if (owner is not null)
            {
                try { sink.Release(); }
                finally { owner = null; token = ""; permitted = () => false; }
            }
            return true;
        }
    }

    private bool Allowed() { try { return permitted(); } catch (Exception) { return false; } }

    internal bool Expire()
    {
        lock (Gate)
        {
            if (owner is null || Allowed()) return false;
            Disarm(); return true;
        }
    }

    internal bool Accept(object source, JsonObject body)
    {
        lock (Gate)
        {
            if (!ReferenceEquals(owner, source)) return false;
            if (!Allowed()) { Disarm(source); return false; }
            try { sink.Apply(KdeInputProtocol.Input(body)); return true; }
            catch { Disarm(source); throw; }
        }
    }
}
