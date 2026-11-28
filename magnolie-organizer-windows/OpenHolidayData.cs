using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record HolidayEntry(string von, string bis, string name, string art,
    string region, string regionName, string country, bool nationwide, string[] regions);

internal sealed record HolidayFetchScope(string country, string region, string art, string von, string bis);

internal static class OpenHolidayData
{
    internal static IReadOnlyList<HolidayEntry> Parse(JsonElement data, string kind, string country,
        string region, string regionName, string language) => Parse(data, kind, country,
            region, regionName, language, out _);

    internal static IReadOnlyList<HolidayEntry> Parse(JsonElement data, string kind, string country,
        string region, string regionName, string language, out bool complete)
    {
        if (data.ValueKind == JsonValueKind.Object && data.TryGetProperty("data", out var nested)) data = nested;
        var result = new List<HolidayEntry>();
        complete = data.ValueKind == JsonValueKind.Array;
        if (data.ValueKind != JsonValueKind.Array) return result;
        foreach (var item in data.EnumerateArray())
        {
            complete &= CompleteShape(item);
            var fromText = Text(item, "startDate");
            var from = fromText[..Math.Min(10, fromText.Length)];
            var toText = Text(item, "endDate"); var to = toText.Length >= 10 ? toText[..10] : from;
            var name = Name(item, language);
            if (!DateOnly.TryParseExact(from, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var start) || name.Length == 0)
            { complete = false; continue; }
            if (!DateOnly.TryParseExact(to, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var end) || end < start)
            { complete = false; to = from; }
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

    internal static bool ReturnedRowsMatchQuery(IReadOnlyList<HolidayEntry> entries, string country, string region, int year)
    {
        var from = $"{year}-01-01"; var to = $"{year}-12-31";
        string Canonical(string code) => code.Contains('-') || code == country ? code : country + "-" + code;
        return entries.All(item => StringComparer.Ordinal.Compare(item.von, to) <= 0 &&
            StringComparer.Ordinal.Compare(item.bis, from) >= 0 &&
            !item.regions.Any(code => code.Contains('-') && !code.StartsWith(country + "-", StringComparison.Ordinal)) &&
            (region.Length > 0 || item.nationwide || item.regions.Length > 0) &&
            (region.Length == 0 || item.nationwide || item.regions.Length == 0 || item.regions.Select(Canonical).Any(code =>
                code == region || code.StartsWith(region + "-", StringComparison.Ordinal) || region.StartsWith(code + "-", StringComparison.Ordinal))));
    }

    // A tolerated partial/malformed response can contribute valid rows, but
    // cannot authorize removal of previously cached records (Refs #855).
    private static bool CompleteShape(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty("startDate", out var start) ||
            start.ValueKind != JsonValueKind.String || !item.TryGetProperty("name", out var names)) return false;
        if (names.ValueKind != JsonValueKind.String && (names.ValueKind != JsonValueKind.Array ||
            names.EnumerateArray().Any(value => value.ValueKind != JsonValueKind.Object ||
                !value.TryGetProperty("text", out var text) || text.ValueKind != JsonValueKind.String ||
                value.TryGetProperty("language", out var language) && language.ValueKind != JsonValueKind.String))) return false;
        if (!item.TryGetProperty("endDate", out var end) ||
            end.ValueKind != JsonValueKind.String || (end.GetString()?.Length ?? 0) < 10) return false;
        if (!item.TryGetProperty("nationwide", out var whole) ||
            whole.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return false;
        if (item.TryGetProperty("subdivisions", out var regions) &&
            (regions.ValueKind != JsonValueKind.Array || regions.EnumerateArray().Any(value =>
                value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("code", out var code) ||
                code.ValueKind != JsonValueKind.String || !Regex.IsMatch(
                    (code.GetString() ?? "").Trim().ToUpperInvariant(), "^[A-Z0-9-]{1,64}$")))) return false;
        return true;
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
