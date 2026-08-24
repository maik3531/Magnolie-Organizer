using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class RegionalSettings
{
    private static readonly HashSet<string> Languages = new(StringComparer.OrdinalIgnoreCase)
    { "system", "de", "en", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb", "hi", "zh_CN", "ja", "ar", "uk", "be", "tr" };

    internal static string LanguagePreference()
    {
        var path = new WindowsPaths().RegionalSettings;
        return Read(path)["language"]?.GetValue<string>() ?? "system";
    }

    internal static JsonObject Read(string path)
    {
        try
        {
            var text = new AtomicStore().Read(path, 64 * 1024);
            return Clean(text is null ? null : JsonNode.Parse(text) as JsonObject);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            return Clean(null);
        }
    }

    internal static JsonObject Write(string path, JsonElement value)
    {
        var clean = Clean(JsonNode.Parse(value.GetRawText()) as JsonObject);
        new AtomicStore().Write(path, clean.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), 64 * 1024);
        return clean;
    }

    private static JsonObject Clean(JsonObject? source)
    {
        var language = Text(source, "language", "system");
        if (!Languages.Contains(language)) language = "system";
        var format = Text(source, "formatLocale", "system").Replace('_', '-');
        if (format != "system" && !Regex.IsMatch(format, @"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")) format = "system";
        var hours = OneOf(Text(source, "hourCycle", "system"), "system", "h12", "h23");
        var first = OneOf(Text(source, "firstDayOfWeek", "locale"), "locale", "monday", "sunday", "saturday");
        var temperature = OneOf(Text(source, "temperatureUnit", "system"), "system", "celsius", "fahrenheit");
        var zone = Text(source, "timeZone", "system");
        if (zone != "system" && zone != "UTC" && (zone.Contains("..") || !Regex.IsMatch(zone, @"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+$"))) zone = "system";
        return new JsonObject { ["language"] = language, ["formatLocale"] = format,
            ["hourCycle"] = hours, ["firstDayOfWeek"] = first, ["weekRule"] = "iso",
            ["temperatureUnit"] = temperature, ["timeZone"] = zone };
    }

    private static string Text(JsonObject? source, string name, string fallback)
    {
        if (source?[name] is JsonValue node && node.TryGetValue<string>(out var text) &&
            text.Trim() is { Length: > 0 } value) return value;
        return fallback;
    }

    private static string OneOf(string value, params string[] allowed) =>
        allowed.Contains(value, StringComparer.Ordinal) ? value : allowed[0];
}
