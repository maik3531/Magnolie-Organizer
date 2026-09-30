using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeDigitizerFrame(string DeviceId, string Token, JsonObject Sample, bool Stopped = false);

// KDE sends partial updates. State is per authenticated connection/session;
// consumers receive complete normalized samples and never operating-system input.
internal sealed class KdeDigitizerState
{
    internal const string SessionPacket = "kdeconnect.digitizer.session";
    internal const string EventPacket = "kdeconnect.digitizer";
    private int width, height;
    private int? x, y;
    private bool active, touching;
    private string tool = "Pen";
    private double pressure;

    internal void Reset()
    {
        width = height = 0; x = y = null; active = touching = false; tool = "Pen"; pressure = 0;
    }

    internal JsonObject Accept(string type, JsonObject body)
    {
        try
        {
            if (type == SessionPacket)
            {
                var action = body["action"]?.GetValue<string>();
                if (action == "end") { Reset(); return Sample(); }
                if (action != "start" || body.Any(pair => pair.Key is not ("action" or "width" or "height" or "resolutionX" or "resolutionY")))
                    throw new InvalidDataException("invalid_digitizer_session");
                var newWidth = Integer(body, "width", 1, 32768);
                var newHeight = Integer(body, "height", 1, 32768);
                _ = Integer(body, "resolutionX", 0, 100000);
                _ = Integer(body, "resolutionY", 0, 100000);
                Reset(); width = newWidth; height = newHeight; return Sample();
            }
            if (type != EventPacket || width == 0 || body.Count == 0 ||
                body.Any(pair => pair.Key is not ("active" or "touching" or "tool" or "x" or "y" or "pressure")))
                throw new InvalidDataException("invalid_digitizer_event");
            var nextActive = body.ContainsKey("active") ? body["active"]!.GetValue<bool>() : active;
            var nextTouching = body.ContainsKey("touching") ? body["touching"]!.GetValue<bool>() : touching;
            var nextTool = body.ContainsKey("tool") ? body["tool"]!.GetValue<string>() : tool;
            if (nextTool is not ("Pen" or "Rubber")) throw new InvalidDataException("invalid_digitizer_tool");
            var nextX = body.ContainsKey("x") ? Integer(body, "x", -1000000, 1000000) : x;
            var nextY = body.ContainsKey("y") ? Integer(body, "y", -1000000, 1000000) : y;
            var nextPressure = body.ContainsKey("pressure") ? body["pressure"]!.GetValue<double>() : pressure;
            if (!double.IsFinite(nextPressure) || nextPressure is < 0 or > 8) throw new InvalidDataException("invalid_digitizer_pressure");
            active = nextActive; touching = active && nextTouching; tool = nextTool;
            x = nextX; y = nextY; pressure = Math.Clamp(nextPressure, 0, 1);
            return Sample();
        }
        catch (Exception error) when (error is InvalidOperationException or FormatException or OverflowException or NullReferenceException or InvalidDataException)
        {
            Reset(); throw new InvalidDataException("invalid_digitizer_packet", error);
        }
    }

    private JsonObject Sample() => new()
    {
        ["active"] = active && width > 0,
        ["touching"] = active && touching && x.HasValue && y.HasValue,
        ["tool"] = tool, ["x"] = x.HasValue && width > 0 ? x.Value / (double)width : 0,
        ["y"] = y.HasValue && height > 0 ? y.Value / (double)height : 0, ["pressure"] = pressure
    };

    private static int Integer(JsonObject body, string name, int minimum, int maximum)
    {
        var value = body[name]?.GetValue<int>() ?? throw new InvalidDataException("missing_digitizer_field");
        if (value < minimum || value > maximum) throw new InvalidDataException("invalid_digitizer_field");
        return value;
    }
}
