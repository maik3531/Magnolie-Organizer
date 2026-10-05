using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record HolidayEntry(string von, string bis, string name, string art,
    string region, string regionName, string country, bool nationwide, string[] regions);

internal static class OpenHolidayData
{
    internal static IReadOnlyList<HolidayEntry> Parse(JsonElement data, string kind, string country,
        string region, string regionName, string language)
    {
        if (data.ValueKind == JsonValueKind.Object && data.TryGetProperty("data", out var nested)) data = nested;
        var result = new List<HolidayEntry>();
        if (data.ValueKind != JsonValueKind.Array) return result;
        foreach (var item in data.EnumerateArray())
        {
            var fromText = Text(item, "startDate");
            var from = fromText[..Math.Min(10, fromText.Length)];
            var toText = Text(item, "endDate"); var to = toText.Length >= 10 ? toText[..10] : from;
            var name = Name(item, language);
            if (!DateOnly.TryParseExact(from, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var start) || name.Length == 0) continue;
            if (!DateOnly.TryParseExact(to, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var end) || end < start) to = from;
            var nationwide = item.TryGetProperty("nationwide", out var whole) && whole.ValueKind == JsonValueKind.True;
            var regions = item.TryGetProperty("subdivisions", out var subdivisions) && subdivisions.ValueKind == JsonValueKind.Array
                ? subdivisions.EnumerateArray().Select(value => Text(value, "code").Trim().ToUpperInvariant())
                    .Where(value => Regex.IsMatch(value, "^[A-Z0-9-]{1,64}$")).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray()
                : Array.Empty<string>();
            if (!nationwide && regions.Length == 0 && region.Length > 0) regions = [region];
            result.Add(new HolidayEntry(from, to, name, kind, region, regionName, country, nationwide, regions));
        }
        return result;
    }

    private static string Text(JsonElement value, string key) => value.ValueKind == JsonValueKind.Object &&
        value.TryGetProperty(key, out var text) && text.ValueKind == JsonValueKind.String ? text.GetString() ?? "" : "";

    private static string Name(JsonElement item, string language)
    {
        if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty("name", out var names)) return "";
        if (names.ValueKind == JsonValueKind.String) return names.GetString()?.Trim() ?? "";
        if (names.ValueKind != JsonValueKind.Array) return "";
        var fallback = "";
        foreach (var name in names.EnumerateArray())
        {
            var text = Text(name, "text").Trim();
            if (text.Length == 0) continue;
            if (fallback.Length == 0) fallback = text;
            if (Text(name, "language").Equals(language, StringComparison.OrdinalIgnoreCase)) return text;
        }
        return fallback;
    }
}
