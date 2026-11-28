using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record HolidayEntry(string von, string bis, string name, string art,
    string region, string regionName, string country, bool nationwide, string[] regions);

internal sealed record HolidayFetchScope(string country, string region, string art, string von, string bis);

internal static class OpenHolidayData
{
    // Refs #854/#857: these school groups are provider identities, not ISO
    // administrative subdivisions. Keep the two request scopes separate.
    private static readonly HashSet<string> BelgianSchoolGroups = ["BE-DE", "BE-FR", "BE-NL"];
    private static readonly HashSet<string> DutchSchoolGroups = ["NL-NO", "NL-MI", "NL-ZU"];
    private static readonly HashSet<string> NoSchoolGroups = [];

    internal static IReadOnlySet<string> SchoolHolidayGroups(string country) => country switch
    {
        "BE" => BelgianSchoolGroups,
        "NL" => DutchSchoolGroups,
        _ => NoSchoolGroups
    };

    // Refs #856: OpenHolidays /Subdivisions distinguishes provider "code"
    // from "isoCode". Keep the existing ISO codes in settings and caches.
    private static readonly (string Iso, string Provider)[] AustrianSubdivisions = [
        ("AT-1", "AT-BL"), ("AT-2", "AT-KÄ"), ("AT-3", "AT-NÖ"),
        ("AT-4", "AT-OÖ"), ("AT-5", "AT-SB"), ("AT-6", "AT-SM"),
        ("AT-7", "AT-TI"), ("AT-8", "AT-VA"), ("AT-9", "AT-WI")
    ];

    internal static string ProviderSubdivisionCode(string country, string isoCode)
    {
        if (country == "AT")
            foreach (var subdivision in AustrianSubdivisions)
                if (subdivision.Iso == isoCode) return subdivision.Provider;
        return isoCode;
    }

    private static string CanonicalSubdivisionCode(string country, string code)
    {
        code = code.Trim().ToUpperInvariant();
        if (country == "AT")
            foreach (var subdivision in AustrianSubdivisions)
                if (subdivision.Provider == code) return subdivision.Iso;
        return code;
    }

    private static bool KnownAustrianSubdivision(string code) =>
        AustrianSubdivisions.Any(subdivision => subdivision.Iso == code);

    private static bool ValidSubdivisionShape(string country, string code)
    {
        code = CanonicalSubdivisionCode(country, code);
        return Regex.IsMatch(code, "^[A-Z0-9-]{1,64}$") &&
            (country != "AT" || KnownAustrianSubdivision(code));
    }

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
        var schoolGroups = SchoolHolidayGroups(country);
        var groupRequest = schoolGroups.Contains(region);
        var groupScope = kind == "school-holiday" && schoolGroups.Count > 0 && (groupRequest || region.Length == 0);
        foreach (var item in data.EnumerateArray())
        {
            complete &= CompleteShape(item, country);
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
                ? subdivisions.EnumerateArray().Select(value => CanonicalSubdivisionCode(country, Text(value, "code")))
                    .Where(value => Regex.IsMatch(value, "^[A-Z0-9-]{1,64}$")).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray()
                : Array.Empty<string>();
            if (groupScope)
            {
                // Unknown future/malformed scope metadata may contribute
                // explicit rows, but cannot certify replacement coverage.
                if (item.TryGetProperty("regionalScope", out var regionalScope) &&
                    (regionalScope.ValueKind != JsonValueKind.String ||
                     regionalScope.GetString() is not ("National" or "Regional" or "Local"))) complete = false;
                var groupCodes = Array.Empty<string>();
                if (item.TryGetProperty("groups", out var groups))
                {
                    if (groups.ValueKind != JsonValueKind.Array || groups.EnumerateArray().Any(value =>
                        value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("code", out var code) ||
                        code.ValueKind != JsonValueKind.String || !schoolGroups.Contains(code.GetString() ?? "")))
                    { complete = false; continue; }
                    groupCodes = groups.EnumerateArray().Select(value => Text(value, "code"))
                        .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
                }
                var subdivisionShape = subdivisions.ValueKind == JsonValueKind.Undefined ||
                    subdivisions.ValueKind == JsonValueKind.Array && subdivisions.EnumerateArray().All(value =>
                        value.ValueKind == JsonValueKind.Object && value.TryGetProperty("code", out var code) &&
                        code.ValueKind == JsonValueKind.String && ValidSubdivisionShape(country, code.GetString() ?? ""));
                if (!subdivisionShape || regions.Any(code => !code.StartsWith(country + "-", StringComparison.Ordinal)))
                { complete = false; continue; }
                var hasSubdivisions = subdivisions.ValueKind == JsonValueKind.Array && subdivisions.GetArrayLength() > 0;
                var explicitlyLocal = Text(item, "regionalScope") == "Local";
                if (explicitlyLocal || groupCodes.Length == 0 && hasSubdivisions)
                {
                    // A genuinely local/subdivision-only row cannot prove a
                    // school group's coverage. Keep local country data without
                    // replacement authority; never infer a requested group.
                    complete = false;
                    if (groupRequest || !hasSubdivisions || nationwide) continue;
                }
                else
                {
                    if (nationwide)
                    {
                        if (groupCodes.Length > 0 && !schoolGroups.SetEquals(groupCodes))
                        { complete = false; continue; }
                    }
                    else if (groupCodes.Length == 0 || groupRequest && !groupCodes.Contains(region, StringComparer.Ordinal))
                    { complete = false; continue; }
                    // The provider expands groups into subdivisions. Both
                    // arrays are normal (not evidence of a municipal-only
                    // restriction); explicit groups carry school identity.
                    regions = groupCodes;
                }
            }
            // Only legacy subdivision paths may infer the requested scope.
            if (!groupScope && !nationwide && regions.Length == 0 && region.Length > 0) regions = [region];
            result.Add(new HolidayEntry(from, to, name, kind, region, regionName, country, nationwide, regions));
        }
        return result;
    }

    internal static bool HasSchoolGroupCoverage(IReadOnlyList<HolidayEntry> entries, string kind, string country, string region)
    {
        var groups = SchoolHolidayGroups(country);
        if (kind != "school-holiday" || groups.Count == 0 || region.Length > 0 && !groups.Contains(region)) return true;
        var evidenced = entries.SelectMany(item => item.regions).ToHashSet(StringComparer.Ordinal);
        // Empty and nationwide-only responses do not prove that a school's
        // group calendar exists. Country coverage requires all known groups.
        return region.Length > 0 ? evidenced.Contains(region) : groups.IsSubsetOf(evidenced);
    }

    internal static bool ReturnedRowsMatchQuery(IReadOnlyList<HolidayEntry> entries, string country, string region, int year)
    {
        var from = $"{year}-01-01"; var to = $"{year}-12-31";
        string Canonical(string code) => code.Contains('-') || code == country ? code : country + "-" + code;
        return entries.All(item => StringComparer.Ordinal.Compare(item.von, to) <= 0 &&
            StringComparer.Ordinal.Compare(item.bis, from) >= 0 &&
            (country != "AT" || item.regions.All(KnownAustrianSubdivision)) &&
            !item.regions.Any(code => code.Contains('-') && !code.StartsWith(country + "-", StringComparison.Ordinal)) &&
            (region.Length > 0 || item.nationwide || item.regions.Length > 0) &&
            (region.Length == 0 || item.nationwide || item.regions.Length == 0 || item.regions.Select(Canonical).Any(code =>
                code == region || code.StartsWith(region + "-", StringComparison.Ordinal) || region.StartsWith(code + "-", StringComparison.Ordinal))));
    }

    // A tolerated partial/malformed response can contribute valid rows, but
    // cannot authorize removal of previously cached records (Refs #855).
    private static bool CompleteShape(JsonElement item, string country)
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
                code.ValueKind != JsonValueKind.String || !ValidSubdivisionShape(country, code.GetString() ?? "")))) return false;
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
