using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class BaumContactSyncContract
{
    private const int MaxText = 2048;
    private const int MaxNote = 20000;
    private const int MaxList = 100;
    private static readonly HashSet<string> RootFields =
        ["art", "fassung", "freigabeId", "version", "quelle", "geaendert", "kontakt"];
    private static readonly HashSet<string> ContactFields =
        ["vorname", "nachname", "firma", "notiz", "geburtstag", "telefone", "emailEintraege", "anschriften"];
    private static readonly HashSet<string> DeleteFields =
        ["art", "fassung", "freigabeId", "version", "quelle", "geaendert"];
    private static readonly HashSet<string> DeleteMarkers = new(StringComparer.OrdinalIgnoreCase)
        { "delete", "deleted", "deletion", "tombstone", "loeschen", "löschen", "geloescht", "gelöscht" };

    internal static void Validate(JsonNode content)
    {
        if (content is not JsonObject root || !Only(root, RootFields) || Text(root, "art") != "kontakt_sync" ||
            Integer(root, "fassung") != 1 || Long(root, "version") <= 0 || Long(root, "geaendert") < 0)
            throw Invalid();
        RequiredText(root, "freigabeId", 128);
        RequiredText(root, "quelle", 128);
        if (root["kontakt"] is not JsonObject contact ||
            contact.Any(item => !ContactFields.Contains(item.Key) && item.Key != "foto") ||
            ContactFields.Any(field => !contact.ContainsKey(field))) throw Invalid();
        foreach (var field in new[] { "vorname", "nachname", "firma", "notiz", "geburtstag" })
            OptionalText(contact, field, field == "notiz" ? MaxNote : MaxText);
        var birthday = Text(contact, "geburtstag");
        if (birthday.Length > 0 && !ExchangeCodec.TryParseCanonicalDate(birthday, out _, out _, out _))
            throw Invalid();
        if (contact.TryGetPropertyValue("foto", out var photoNode))
        {
            if (photoNode is not JsonValue photoValue || !photoValue.TryGetValue<string>(out var photo)) throw Invalid();
            ValidatePhoto(photo);
        }
        ValidateList(contact, "telefone", MaxList, ["art", "wert"], item =>
        {
            ListText(item, "art", true); ListText(item, "wert");
        });
        ValidateList(contact, "emailEintraege", MaxList, ["art", "wert"], item =>
        {
            ListText(item, "art", true); ListText(item, "wert");
        });
        ValidateList(contact, "anschriften", MaxList,
            ["art", "strasse", "plz", "ort", "region", "land"], item =>
        {
            foreach (var field in new[] { "art", "strasse", "plz", "ort", "region", "land" })
                ListText(item, field, field == "art");
        });
    }

    internal static void ValidateDelete(JsonNode content)
    {
        if (content is not JsonObject root || !Only(root, DeleteFields) ||
            Text(root, "art") != "kontakt_loeschen" || Integer(root, "fassung") != 1 ||
            Long(root, "version") <= 0 || Long(root, "geaendert") < 0) throw InvalidDelete();
        RequiredText(root, "freigabeId", 128);
        RequiredText(root, "quelle", 128);
    }

    internal static void ValidateImport(JsonNode content, string kind)
    {
        if (content is not JsonObject root || Text(root, "art") != kind || Integer(root, "fassung") != 1)
            throw InvalidImport();
        RequiredText(root, "importId", 128);
        if (kind == "kontakt_import_manifest")
        {
            if (!Only(root, ["art", "fassung", "importId", "anzahl", "herkuenfte"]) ||
                Integer(root, "anzahl") is < 1 or > 250) throw InvalidImport();
            ValidateOrigins(root, 64, true);
            return;
        }
        if (kind != "kontakt_import_karte" ||
            !Only(root, ["art", "fassung", "importId", "bindung", "herkuenfte", "kontakt"])) throw InvalidImport();
        var binding = Text(root, "bindung");
        if (!binding.StartsWith("urn:magnolie:import:android:", StringComparison.Ordinal) ||
            binding.Length != "urn:magnolie:import:android:".Length + 64 ||
            binding["urn:magnolie:import:android:".Length..].Any(character =>
                character is not (>= '0' and <= '9') and not (>= 'a' and <= 'f'))) throw InvalidImport();
        ValidateOrigins(root, 16, false);
        var candidate = new JsonObject { ["art"] = "kontakt_sync", ["fassung"] = 1,
            ["freigabeId"] = binding, ["version"] = 1, ["quelle"] = "android-import", ["geaendert"] = 0,
            ["kontakt"] = root["kontakt"]?.DeepClone() };
        Validate(candidate);
    }

    private static void ValidateOrigins(JsonObject root, int maximum, bool counts)
    {
        if (root["herkuenfte"] is not JsonArray origins || origins.Count is < 1 || origins.Count > maximum) throw InvalidImport();
        var fields = counts ? new HashSet<string> { "kontoTyp", "kontoName", "dataSet", "anzahl" } :
            new HashSet<string> { "kontoTyp", "kontoName", "dataSet" };
        foreach (var node in origins)
        {
            if (node is not JsonObject origin || !Only(origin, fields)) throw InvalidImport();
            foreach (var field in new[] { "kontoTyp", "kontoName", "dataSet" }) OptionalText(origin, field, 128);
            if (counts && Integer(origin, "anzahl") is < 1 or > 250) throw InvalidImport();
        }
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
        var text = Text(value, name);
        if (text.Length == 0 || text.EnumerateRunes().Any(rune => rune.Value < 32)) throw Invalid();
    }

    private static void OptionalText(JsonObject value, string name, int maximum)
    {
        if (value[name] is not JsonValue node || !node.TryGetValue<string>(out var text) ||
            text.EnumerateRunes().Count() > maximum)
            throw Invalid();
    }

    private static void ListText(JsonObject value, string name, bool type = false)
    {
        OptionalText(value, name, MaxText);
        var text = Text(value, name);
        if (text.StartsWith("data:", StringComparison.OrdinalIgnoreCase) ||
            type && DeleteMarkers.Contains(text.Trim())) throw Invalid();
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
    private static long Long(JsonObject value, string name)
    {
        if (value[name] is JsonValue node)
        {
            if (node.TryGetValue<long>(out var result)) return result;
            if (node.TryGetValue<int>(out var integer)) return integer;
        }
        return long.MinValue;
    }
    private static InvalidDataException Invalid() => new("Der Kontakt entspricht nicht dem kontakt_sync-Vertrag.");
    private static InvalidDataException InvalidDelete() => new("Die Löschung entspricht nicht dem kontakt_loeschen-Vertrag.");
    private static InvalidDataException InvalidImport() => new("Der Kontakt entspricht nicht dem kontakt_import-Vertrag.");
}
