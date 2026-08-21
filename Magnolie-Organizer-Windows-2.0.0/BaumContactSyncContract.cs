using System.Globalization;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class BaumContactSyncContract
{
    private const int MaxText = 4096;
    private static readonly HashSet<string> RootFields =
        ["art", "fassung", "freigabeId", "version", "quelle", "geaendert", "kontakt"];
    private static readonly HashSet<string> ContactFields =
        ["vorname", "nachname", "firma", "notiz", "geburtstag", "telefone", "emailEintraege", "anschriften"];
    private static readonly HashSet<string> DeleteFields =
        ["art", "fassung", "freigabeId", "version", "quelle", "geaendert"];

    internal static void Validate(JsonNode content)
    {
        if (content is not JsonObject root || !Only(root, RootFields) || Text(root, "art") != "kontakt_sync" ||
            Integer(root, "fassung") != 1 || Long(root, "version") <= 0 || Long(root, "geaendert") <= 0)
            throw Invalid();
        RequiredText(root, "freigabeId", 128);
        RequiredText(root, "quelle", 128);
        if (root["kontakt"] is not JsonObject contact ||
            contact.Any(item => !ContactFields.Contains(item.Key) && item.Key != "foto") ||
            ContactFields.Any(field => !contact.ContainsKey(field))) throw Invalid();
        foreach (var field in new[] { "vorname", "nachname", "firma", "notiz", "geburtstag" })
            OptionalText(contact, field, field == "notiz" ? 65536 : MaxText);
        var birthday = Text(contact, "geburtstag");
        if (birthday.Length > 0 && (!DateOnly.TryParseExact(birthday, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out var date) || date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) != birthday))
            throw Invalid();
        if (contact.TryGetPropertyValue("foto", out var photoNode))
        {
            if (photoNode is not JsonValue photoValue || !photoValue.TryGetValue<string>(out var photo)) throw Invalid();
            ValidatePhoto(photo);
        }
        ValidateList(contact, "telefone", 100, ["art", "wert"], item =>
        {
            OptionalText(item, "art", 80); RequiredText(item, "wert", MaxText);
        });
        ValidateList(contact, "emailEintraege", 100, ["art", "wert"], item =>
        {
            OptionalText(item, "art", 80); RequiredText(item, "wert", MaxText);
        });
        ValidateList(contact, "anschriften", 50,
            ["art", "strasse", "plz", "ort", "region", "land"], item =>
        {
            foreach (var field in new[] { "art", "strasse", "plz", "ort", "region", "land" })
                OptionalText(item, field, field == "art" ? 80 : MaxText);
            if (new[] { "strasse", "plz", "ort", "region", "land" }.All(field => Text(item, field).Length == 0))
                throw Invalid();
        });
        if (contact.All(item => item.Key is "telefone" or "emailEintraege" or "anschriften" || Text(contact, item.Key).Length == 0) &&
            contact["telefone"]!.AsArray().Count == 0 && contact["emailEintraege"]!.AsArray().Count == 0 &&
            contact["anschriften"]!.AsArray().Count == 0) throw Invalid();
    }

    internal static void ValidateDelete(JsonNode content)
    {
        if (content is not JsonObject root || !Only(root, DeleteFields) ||
            Text(root, "art") != "kontakt_loeschen" || Integer(root, "fassung") != 1 ||
            Long(root, "version") <= 0 || Long(root, "geaendert") <= 0) throw InvalidDelete();
        RequiredText(root, "freigabeId", 128);
        RequiredText(root, "quelle", 128);
    }

    private static void ValidateList(JsonObject parent, string name, int maximum, HashSet<string> fields,
        Action<JsonObject> validate)
    {
        if (parent[name] is not JsonArray values || values.Count > maximum) throw Invalid();
        foreach (var value in values)
        {
            if (value is not JsonObject item || !Only(item, fields)) throw Invalid();
            validate(item);
        }
    }

    private static bool Only(JsonObject value, HashSet<string> fields) =>
        value.Count == fields.Count && value.All(item => fields.Contains(item.Key));

    private static void RequiredText(JsonObject value, string name, int maximum)
    {
        OptionalText(value, name, maximum);
        if (Text(value, name).Length == 0) throw Invalid();
    }

    private static void OptionalText(JsonObject value, string name, int maximum)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<string>(out var text) || text.Length > maximum ||
            text.Any(character => char.IsControl(character) && character is not '\r' and not '\n' and not '\t') ||
            text.Contains("data:", StringComparison.OrdinalIgnoreCase))
            throw Invalid();
    }

    private static void ValidatePhoto(string value)
    {
        if (value.Length == 0) return;
        if (value.Length > 2_800_000 || value.Any(char.IsWhiteSpace)) throw Invalid();
        var prefixes = new[] { "data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64," };
        var prefix = prefixes.FirstOrDefault(value.StartsWith);
        if (prefix is null) throw Invalid();
        var encoded = value[prefix.Length..];
        try
        {
            var bytes = Convert.FromBase64String(encoded);
            if (bytes.Length == 0 || Convert.ToBase64String(bytes) != encoded) throw Invalid();
        }
        catch (FormatException) { throw Invalid(); }
    }

    private static string Text(JsonObject value, string name) => value[name]!.GetValue<string>();
    private static int Integer(JsonObject value, string name) =>
        value[name] is JsonValue node && node.TryGetValue<int>(out var result) ? result : int.MinValue;
    private static long Long(JsonObject value, string name) =>
        value[name] is JsonValue node && node.TryGetValue<long>(out var result) ? result : long.MinValue;
    private static InvalidDataException Invalid() => new("Der Kontakt entspricht nicht dem kontakt_sync-Vertrag.");
    private static InvalidDataException InvalidDelete() => new("Die Löschung entspricht nicht dem kontakt_loeschen-Vertrag.");
}
