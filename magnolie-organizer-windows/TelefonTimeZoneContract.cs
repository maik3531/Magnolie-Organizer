using System.Globalization;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class TelefonTimeZoneContract
{
    internal const int Version = 12;
    private static long Number(JsonObject value, string name)
    {
        var text = value[name]?.ToJsonString() ?? "";
        if (!Regex.IsMatch(text, @"^(?:0|[1-9][0-9]*)$") || !long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out var number))
            throw new InvalidDataException("invalid_time_zone_status");
        return number;
    }
    private static string Text(JsonObject value, string name) => value[name] is JsonValue field && field.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("invalid_time_zone_status");

    internal static void ValidateRequest(JsonObject value)
    {
        if (value.Count != 2 || !value.ContainsKey("request_id") || !value.ContainsKey("version") || Number(value, "version") != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(value, "request_id"))) throw new InvalidDataException("invalid_time_zone_request");
    }

    internal static void ValidateReport(JsonObject value)
    {
        if (value.Count != 5 || value.Any(pair => pair.Key is not ("request_id" or "version" or "state" or "time_zone" or "captured_ms")) ||
            Number(value, "version") != Version || !TelefonProtocolContract.IsUuidV4(Text(value, "request_id")) || Number(value, "captured_ms") > 253402300799999)
            throw new InvalidDataException("invalid_time_zone_status");
        var state = Text(value, "state"); var zone = Text(value, "time_zone");
        if (state == "unavailable" && zone.Length == 0) return;
        if (state != "available" || zone.Length > 128 || zone.Contains("..", StringComparison.Ordinal) ||
            zone is not ("UTC" or "GMT" or "Z") && !Regex.IsMatch(zone, @"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+$"))
            throw new InvalidDataException("invalid_time_zone_status");
        try { _ = TimeZoneInfo.FindSystemTimeZoneById(zone == "Z" ? "UTC" : zone); }
        catch (Exception error) when (error is TimeZoneNotFoundException or InvalidTimeZoneException)
        { throw new InvalidDataException("invalid_time_zone_status", error); }
    }
}
