using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

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
            Integer(root, "fassung") is not (1 or 2) || Long(root, "version") <= 0 || Long(root, "geaendert") < 0)
            throw Invalid();
        RequiredText(root, "freigabeId", 128);
        RequiredText(root, "quelle", 128);
        var fields = new HashSet<string>(ContactFields);
        if (Integer(root, "fassung") == 2) fields.UnionWith(["jubilaeum", "anzeigename", "vcardName"]);
        if (root["kontakt"] is not JsonObject contact ||
            contact.Any(item => !fields.Contains(item.Key) && item.Key != "foto") ||
            fields.Any(field => !contact.ContainsKey(field))) throw Invalid();
        foreach (var field in new[] { "vorname", "nachname", "firma", "notiz", "geburtstag" })
            OptionalText(contact, field, field == "notiz" ? MaxNote : MaxText);
        var birthday = Text(contact, "geburtstag");
        if (birthday.Length > 0 && !ExchangeCodec.TryParseCanonicalDate(birthday, out _, out _, out _))
            throw Invalid();
        if (Integer(root, "fassung") == 2)
        {
            OptionalText(contact, "anzeigename", MaxText);
            OptionalText(contact, "jubilaeum", MaxText);
            var anniversary = Text(contact, "jubilaeum");
            if (anniversary.Length > 0 && !ExchangeCodec.TryParseCanonicalDate(anniversary, out _, out _, out _)) throw Invalid();
            if (contact["vcardName"] is not JsonArray names || names.Count > 32) throw Invalid();
            foreach (var name in names)
                if (name is not JsonValue value || !value.TryGetValue<string>(out var line) ||
                    line.EnumerateRunes().Count() > MaxText || line.Any(c => c < 32 || c == 127) ||
                    !Regex.IsMatch(line, @"\A(?:[A-Za-z0-9-]+\.)?(?:N|FN)(?:;[^:]*)?:", RegexOptions.IgnoreCase)) throw Invalid();
        }
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
        if (content is not JsonObject root || Text(root, "art") != kind || Integer(root, "fassung") is not (1 or 2))
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
        var candidate = new JsonObject { ["art"] = "kontakt_sync", ["fassung"] = Integer(root, "fassung"),
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
            foreach (var field in new[] { "kontoTyp", "kontoName", "dataSet" })
            {
                OptionalText(origin, field, 128);
                if (Integer(root, "fassung") == 2 && Text(origin, field).Any(c => c < 32)) throw InvalidImport();
            }
            if (counts && Integer(origin, "anzahl") is < 1 or > 250) throw InvalidImport();
        }
    }

    internal static JsonObject Capabilities(bool response) => new()
    {
        ["art"] = "kontakt_faehigkeiten", ["fassung"] = 1,
        ["kontakt_sync"] = new JsonArray(1, 2), ["kontakt_import"] = new JsonArray(1, 2), ["antwort"] = response
    };

    internal static void ValidateCapabilities(JsonNode content)
    {
        if (content is not JsonObject root || !Only(root, ["art", "fassung", "kontakt_sync", "kontakt_import", "antwort"]) ||
            Text(root, "art") != "kontakt_faehigkeiten" || Integer(root, "fassung") != 1 ||
            root["antwort"] is not JsonValue answer || !answer.TryGetValue<bool>(out _)) throw Invalid();
        foreach (var field in new[] { "kontakt_sync", "kontakt_import" })
        {
            if (root[field] is not JsonArray versions || !(field == "kontakt_import" && versions.Count == 0 ||
                JsonNode.DeepEquals(versions, new JsonArray(1)) || JsonNode.DeepEquals(versions, new JsonArray(1, 2)))) throw Invalid();
        }
    }

    internal static int PeerVersion(JsonObject partner, string kind) =>
        partner["bestaetigt"]?.GetValue<bool>() == true && partner["kontaktFaehigkeiten"] is JsonObject caps &&
        JsonNode.DeepEquals(caps[kind], new JsonArray(1, 2)) ? 2 : 1;

    internal static JsonObject ForPeer(JsonObject partner, JsonObject payload)
    {
        var kind = Text(payload, "art");
        if (kind == "kontakt")
        {
            if (PeerVersion(partner, "kontakt_sync") == 2) return payload;
            var projection = new JsonObject();
            foreach (var field in new[] { "vorname", "nachname", "anzeigename", "jubilaeum" }) projection[field] = payload[field]?.DeepClone() ?? JsonValue.Create("");
            foreach (var field in new[] { "firma", "notiz", "geburtstag" }) projection[field] = "";
            foreach (var field in new[] { "telefone", "emailEintraege", "anschriften" }) projection[field] = new JsonArray();
            projection["vcardName"] = new JsonArray((payload["vcardRoundtrip"] as JsonArray ?? []).Where(line => line is JsonValue v && v.TryGetValue<string>(out var s) &&
                Regex.IsMatch(s, @"\A(?:[A-Za-z0-9-]+\.)?(?:N|FN)[;:]", RegexOptions.IgnoreCase)).Select(line => line?.DeepClone()).ToArray());
            _ = ForPeer(partner, new JsonObject { ["art"] = "kontakt_sync", ["fassung"] = 2, ["freigabeId"] = "preview",
                ["version"] = 1, ["quelle"] = "preview", ["geaendert"] = 0, ["kontakt"] = projection });
            return payload;
        }
        if (kind is not ("kontakt_sync" or "kontakt_import_manifest" or "kontakt_import_karte")) return payload;
        if (kind != "kontakt_sync" && partner["kontaktFaehigkeiten"] is JsonObject capabilities &&
            capabilities["kontakt_import"] is JsonArray { Count: 0 })
            throw new InvalidDataException(NativeLocalization.Gettext("Not sent."));
        if (kind == "kontakt_sync") Validate(payload); else ValidateImport(payload, kind);
        var version = PeerVersion(partner, kind == "kontakt_sync" ? kind : "kontakt_import");
        if (Integer(payload, "fassung") <= version) return payload;
        // Import preview and cards must agree; never rewrite an import after consent.
        if (kind != "kontakt_sync") throw new InvalidDataException(NativeLocalization.Gettext("Not sent."));
        var contact = payload["kontakt"]!.AsObject();
        string Escape(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n").Replace("\n", "\\n").Replace(";", "\\;").Replace(",", "\\,");
        var display = string.Join(' ', new[] { Text(contact, "vorname"), Text(contact, "nachname") }.Where(s => s.Length > 0));
        var n = "N:" + Escape(Text(contact, "nachname")) + ";" + Escape(Text(contact, "vorname")) + ";;;";
        if (Text(contact, "jubilaeum").Length > 0 || Text(contact, "anzeigename") is { Length: > 0 } fn && fn != display ||
            contact["vcardName"]!.AsArray().Any(line => line!.GetValue<string>() != n && line.GetValue<string>() != "FN:" + Escape(display)))
            throw new InvalidDataException(NativeLocalization.Gettext("Not sent."));
        payload = payload.DeepClone().AsObject(); payload["fassung"] = 1;
        foreach (var field in new[] { "jubilaeum", "anzeigename", "vcardName" }) payload["kontakt"]!.AsObject().Remove(field);
        return payload;
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

    private static string Text(JsonObject value, string name) =>
        value[name] is JsonValue node && node.TryGetValue<string>(out var text) ? text : "";
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
    private static InvalidDataException Invalid() => new(NativeLocalization.Gettext("The data is invalid."));
    private static InvalidDataException InvalidDelete() => new("Die Löschung entspricht nicht dem kontakt_loeschen-Vertrag.");
    private static InvalidDataException InvalidImport() => new(NativeLocalization.Gettext("The data is invalid."));
}
