using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class RegionalSettings
{
    private static readonly HashSet<string> Languages = new(StringComparer.OrdinalIgnoreCase)
    { "system", "de", "en", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb", "hi", "zh_CN", "ja", "ar", "uk", "be", "tr" };
    private static readonly object Gate = new();
    private static readonly string[] TimeZoneManagementFields = ["timeZoneManagement", "timeZoneDetection", "timeZoneManual", "timeZoneDetectedSource", "timeZoneDetectedAt"];

    internal static JsonObject ReadVerified(string path)
    {
        lock (Gate)
        {
            var text = new AtomicStore().Read(path, 64 * 1024);
            if (text is null) return Clean(null);
            return Clean(JsonNode.Parse(text) as JsonObject ?? throw new InvalidDataException("invalid_regional_settings"));
        }
    }

    internal static JsonObject WriteChecked(string path, JsonElement value, JsonElement expected)
    {
        lock (Gate)
        {
            var current = ReadVerified(path);
            if (expected.ValueKind != JsonValueKind.Object || !JsonNode.DeepEquals(current, JsonNode.Parse(expected.GetRawText())))
                throw new InvalidOperationException("regional_conflict");
            var source = JsonNode.Parse(value.GetRawText()) as JsonObject ?? throw new InvalidDataException("invalid_regional_settings");
            if (!source.ContainsKey("homeCountry")) source["homeCountry"] = current["homeCountry"]?.DeepClone();
            if (!source.ContainsKey("timeZone")) source["timeZone"] = current["timeZone"]?.DeepClone();
            foreach (var field in TimeZoneManagementFields) if (!source.ContainsKey(field)) source[field] = current[field]?.DeepClone();
            var clean = Clean(source);
            foreach (var pair in source)
            {
                if (pair.Value is not JsonValue node || !node.TryGetValue<string>(out var text) || !clean.ContainsKey(pair.Key))
                    throw new InvalidDataException("invalid_regional_settings");
                text = text.Trim();
                if (pair.Key == "formatLocale") text = text.Replace('_', '-');
                if (pair.Key == "homeCountry") text = text.ToUpperInvariant();
                if (!string.Equals(clean[pair.Key]?.GetValue<string>(), text, StringComparison.Ordinal)) throw new InvalidDataException("invalid_regional_settings");
            }
            foreach (var zone in new[] { clean["timeZone"]!.GetValue<string>(), clean["timeZoneManual"]!.GetValue<string>() }.Where(zone => zone != "system"))
            {
                try { _ = TimeZoneInfo.FindSystemTimeZoneById(zone); }
                catch (Exception error) when (error is TimeZoneNotFoundException or InvalidTimeZoneException)
                { throw new InvalidDataException("invalid_regional_settings", error); }
            }
            var written = Write(path, value);
            var actual = ReadVerified(path);
            if (!JsonNode.DeepEquals(actual, written)) throw new IOException("regional_readback_failed");
            return actual;
        }
    }

    internal static string LanguagePreference()
    {
        var path = new WindowsPaths().RegionalSettings;
        return Read(path)["language"]?.GetValue<string>() ?? "system";
    }

    internal static string HomeCountry() =>
        Read(new WindowsPaths().RegionalSettings)["homeCountry"]?.GetValue<string>() ?? "DE";

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
        lock (Gate)
        {
            var source = JsonNode.Parse(value.GetRawText()) as JsonObject;
            if (source is not null && !source.ContainsKey("homeCountry"))
                source["homeCountry"] = Read(path)["homeCountry"]?.DeepClone();
            if (source is not null)
            {
                var current = Read(path);
                var zoneSupplied = source.ContainsKey("timeZone");
                if (!zoneSupplied) source["timeZone"] = current["timeZone"]?.DeepClone();
                foreach (var field in TimeZoneManagementFields) if (!source.ContainsKey(field))
                    source[field] = field == "timeZoneManual" && current["timeZoneManagement"]?.GetValue<string>() != "automatic" && zoneSupplied
                        ? source["timeZone"]?.DeepClone() : current[field]?.DeepClone();
            }
            var clean = Clean(source);
            new AtomicStore().Write(path, clean.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), 64 * 1024);
            return clean;
        }
    }

    internal static JsonObject WriteLanguage(string path, string language)
    {
        lock (Gate)
        {
            var settings = Read(path);
            settings["language"] = language;
            var clean = Clean(settings);
            new AtomicStore().Write(path, clean.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), 64 * 1024);
            return clean;
        }
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
        var homeCountry = PhoneRegionInfo.HomeCountry(Text(source, "homeCountry", "DE"));
        var manualZone = Text(source, "timeZoneManual", zone);
        if (manualZone != "system" && manualZone != "UTC" && (manualZone.Contains("..") || !Regex.IsMatch(manualZone, @"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+$"))) manualZone = "system";
        var capturedText = Text(source, "timeZoneDetectedAt", "0");
        var captured = long.TryParse(capturedText, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out var milliseconds) && milliseconds is >= 0 and <= 253402300799999
            ? milliseconds.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0";
        return new JsonObject { ["language"] = language, ["formatLocale"] = format,
            ["hourCycle"] = hours, ["firstDayOfWeek"] = first, ["weekRule"] = "iso",
            ["temperatureUnit"] = temperature, ["timeZone"] = zone,
            ["timeZoneManagement"] = OneOf(Text(source, "timeZoneManagement", "off"), "off", "manual", "automatic"),
            ["timeZoneDetection"] = OneOf(Text(source, "timeZoneDetection", "auto"), "auto", "system", "phone", "gps", "ip"),
            ["timeZoneManual"] = manualZone,
            ["timeZoneDetectedSource"] = OneOf(Text(source, "timeZoneDetectedSource", "manual"), "manual", "system", "phone", "gps", "ip"),
            ["timeZoneDetectedAt"] = captured,
            ["homeCountry"] = homeCountry };
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
