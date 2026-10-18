using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class ContactGroupExclusions
{
    private static readonly string[] Presets = ["Family", "Work", "Colleagues", "Patients", "Client", "Tradesperson", "Insurance", "Doctor"];
    private static string Key(string value) => value.Normalize(NormalizationForm.FormC).Trim().ToLowerInvariant();
    private static string GroupKey(string value)
    {
        var key = Key(value);
        if (key is "coworkers" or "kollegen") return "colleagues";
        if (key == "patienten") return "patients";
        return Key(Presets.FirstOrDefault(preset => NativeLocalization.IsTranslation(preset, value.Trim())) ?? value);
    }
    private static JsonElement Child(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) ? value : default;
    private static string Text(JsonElement item, string name) => Child(item, name) is var value && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    private static IEnumerable<JsonElement> Items(JsonElement item) => item.ValueKind == JsonValueKind.Array ? item.EnumerateArray() : Enumerable.Empty<JsonElement>();
    private static IEnumerable<string> Strings(JsonElement item) => Items(item).Where(value => value.ValueKind == JsonValueKind.String).Select(value => value.GetString() ?? "");
    private static HashSet<string> Groups(JsonElement contact)
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        foreach (var line in Strings(Child(contact, "vcardRoundtrip")))
        {
            var match = Regex.Match(line, @"^(?:[A-Za-z0-9-]+\.)?CATEGORIES(?:;[^:]*)?:(.*)$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            if (!match.Success) continue;
            var part = new StringBuilder(); var escaped = false;
            foreach (var character in match.Groups[1].Value + ",")
            {
                if (escaped) { part.Append(character is 'n' or 'N' ? ' ' : character); escaped = false; }
                else if (character == '\\') escaped = true;
                else if (character == ',')
                {
                    var key = GroupKey(Regex.Replace(part.ToString(), @"[\x00-\x1f\x7f]", " "));
                    if (key.Length > 0 && key != "my contacts") result.Add(key);
                    part.Clear();
                }
                else part.Append(character);
            }
        }
        return result;
    }
    private static string CanonicalText(string value) => Regex.Replace(new string(value.Normalize(NormalizationForm.FormKD)
        .Where(character => CharUnicodeInfo.GetUnicodeCategory(character) != UnicodeCategory.NonSpacingMark).ToArray())
        .Replace("ß", "ss", StringComparison.Ordinal).ToLowerInvariant(), @"\s+", " ").Trim();
    private static string AnniversarySignature(JsonElement item)
    {
        var date = Text(item, "datum");
        var type = Text(item, "typ");
        return CanonicalText(Text(item, "name")) + "\0" + (date.Length >= 5 ? date[^5..] : date) + "\0" +
            (NativeLocalization.IsTranslation("Birthday", type) ? "birthday" : CanonicalText(type));
    }
    private static HashSet<string> AnniversaryKeys(JsonElement item)
    {
        var result = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (name, prefix) in new[] { ("id", "id:"), ("uid", "extern:"), ("icsSerienUid", "extern:"), ("kontaktId", "kontakt:") })
            if (Text(item, name).Trim() is { Length: > 0 } value) result.Add(prefix + value);
        return result;
    }

    internal static Func<JsonElement, bool> Create(JsonElement root, string area = "notifications")
    {
        var settings = Child(root, "einstellungen");
        var policy = Child(Child(settings, "adressen"), "gruppenAusschluss");
        var rule = Child(policy, area == "calendar" ? "overview" : area);
        var groups = Strings(Child(rule, "groups")).Select(GroupKey).ToHashSet(StringComparer.Ordinal);
        if (Child(policy, "enabled").ValueKind != JsonValueKind.True || groups.Count == 0 ||
            area == "calendar" && Child(rule, "calendar").ValueKind != JsonValueKind.True) return _ => false;
        var contacts = Items(Child(root, "kontakte")).Where(value => value.ValueKind == JsonValueKind.Object).ToArray();
        var parents = Enumerable.Range(0, contacts.Length).ToArray();
        int Root(int index) { while (parents[index] != index) { parents[index] = parents[parents[index]]; index = parents[index]; } return index; }
        var first = new Dictionary<string, int>(StringComparer.Ordinal);
        var homeCountry = Text(Child(settings, "regional"), "homeCountry");
        if (homeCountry.Length == 0) homeCountry = Text(Child(settings, "adressen"), "landCode");
        if (homeCountry.Length == 0) homeCountry = Text(Child(settings, "adressen"), "land");
        homeCountry = CanonicalText(homeCountry) switch
        {
            "" or "deutschland" or "germany" => "DE", "osterreich" or "oesterreich" or "austria" => "AT",
            "schweiz" or "switzerland" or "suisse" or "svizzera" => "CH", _ => homeCountry.ToUpperInvariant()
        };
        for (var index = 0; index < contacts.Length; index++)
            foreach (var key in ContactFields.StrongKeys(JsonNode.Parse(contacts[index].GetRawText())!.AsObject(), homeCountry))
                if (first.TryGetValue(key, out var previous)) parents[Root(index)] = Root(previous);
                else first.Add(key, index);
        var excluded = Enumerable.Range(0, contacts.Length).Where(index => Groups(contacts[index]).Overlaps(groups)).Select(Root).ToHashSet();
        var direct = new Dictionary<string, int>(StringComparer.Ordinal);
        for (var index = 0; index < contacts.Length; index++) if (Text(contacts[index], "id") is { Length: > 0 } id) direct[id] = index;
        var aliases = new Dictionary<string, int?>(StringComparer.Ordinal);
        for (var index = 0; index < contacts.Length; index++)
            foreach (var id in Strings(Child(Child(contacts[index], "kontaktAliase"), "ids")))
                if (!direct.ContainsKey(id)) aliases[id] = !aliases.TryGetValue(id, out var previous) || previous == index ? index : null;
        int? Resolve(JsonElement item)
        {
            var id = Text(item, "kontaktId");
            return direct.TryGetValue(id, out var index) ? index : aliases.GetValueOrDefault(id);
        }
        var linked = Items(Child(root, "jahrestage")).Where(item => Resolve(item) is { } index && excluded.Contains(Root(index)))
            .Select(item => (Signature: AnniversarySignature(item), Keys: AnniversaryKeys(item))).ToArray();
        var birthdaysOnly = Text(rule, "scope") != "anniversaries";
        return item =>
        {
            if (birthdaysOnly && !NativeLocalization.IsTranslation("Birthday", Text(item, "typ"))) return false;
            if (Resolve(item) is { } index) return excluded.Contains(Root(index));
            var signature = AnniversarySignature(item); var keys = AnniversaryKeys(item);
            return linked.Any(other => other.Signature == signature && other.Keys.Overlaps(keys));
        };
    }
}
