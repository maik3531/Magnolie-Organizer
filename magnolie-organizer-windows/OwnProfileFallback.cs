using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class OwnProfileFallback
{
    private static readonly Dictionary<string, string> Fields = new()
    { ["givenname"] = "vorname", ["sn"] = "nachname", ["o"] = "firma", ["street"] = "strasse", ["postalcode"] = "plz",
      ["l"] = "ort", ["c"] = "land", ["st"] = "region", ["mail"] = "email", ["telephonenumber"] = "telefon", ["homephone"] = "mobil" };

    internal static LibreOfficeUserDataResult Resolve(LibreOfficeUserDataResult office, JsonObject? profile, string purpose = "address")
    {
        if (profile?["version"]?.GetValue<int>() != 1 || profile["kind"]?.GetValue<string>() != "own_profile" || profile["data"] is not JsonObject data) return office;
        var own = Fields.ToDictionary(pair => pair.Key, pair => data[pair.Value] is JsonValue value && value.TryGetValue<string>(out var text) ? text.Trim() : "");
        var fields = office.Felder.ToDictionary(pair => pair.Key, pair => pair.Value);
        var take = own["l"].Length > 0 && (purpose == "location" ? string.IsNullOrWhiteSpace(fields.GetValueOrDefault("l")) :
            own["street"].Length > 0 && (string.IsNullOrWhiteSpace(fields.GetValueOrDefault("street")) || string.IsNullOrWhiteSpace(fields.GetValueOrDefault("l"))));
        if (take) foreach (var name in new[] { "givenname", "sn", "o", "street", "postalcode", "l", "c", "st" }) fields[name] = own[name];
        foreach (var name in new[] { "mail", "telephonenumber", "homephone" }) if (string.IsNullOrWhiteSpace(fields.GetValueOrDefault(name))) fields[name] = own[name];
        var lines = new[] { string.Join(' ', new[] { fields.GetValueOrDefault("givenname"), fields.GetValueOrDefault("sn") }.Where(value => !string.IsNullOrWhiteSpace(value))),
            fields.GetValueOrDefault("o"), fields.GetValueOrDefault("street"),
            string.Join(' ', new[] { fields.GetValueOrDefault("postalcode"), fields.GetValueOrDefault("l") }.Where(value => !string.IsNullOrWhiteSpace(value))), fields.GetValueOrDefault("c") };
        var sender = string.Join('\n', lines.Where(value => !string.IsNullOrWhiteSpace(value)));
        return new LibreOfficeUserDataResult(sender.Length > 0, fields, sender, sender.Length > 0 ? "" : office.Fehler, take ? "own_profile" : office.Quelle);
    }
}
