using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Exact existing KontaktSync.hash projection, not a document/renderer hash,
// source permission, enabled transport capability or baseline SaveACK.
internal static class NotesOriginalReturnHash
{
    private static readonly string[] Scalars = ["vorname", "nachname", "firma", "notiz", "geburtstag", "jubilaeum", "anzeigename", "foto"];
    internal static string ContentHash(JsonObject content)
    {
        var allowed = Scalars.Concat(["vcardName", "telefone", "emailEintraege", "anschriften", "gruppen"]).ToHashSet();
        if (content.Any(pair => !allowed.Contains(pair.Key))) throw new InvalidDataException("notes_original_projection_required");
        var text = Scalars.ToDictionary(name => name, name => content.ContainsKey(name) ? Text(content[name]) : "");
        var names = TextList(content, "vcardName");
        var phones = Rows(content, "telefone", ["art", "wert"])
            .Where(value => Trim(Text(value["wert"])).Length > 0)
            .DistinctBy(value => new string(Text(value["wert"]).Where(character => character == '+' || char.IsDigit(character)).ToArray()).TrimStart('+')).ToArray();
        var emails = Rows(content, "emailEintraege", ["art", "wert"])
            .Where(value => Trim(Text(value["wert"])).Length > 0)
            .DistinctBy(value => RootLower(Trim(Text(value["wert"])))).ToArray();
        string PostalKey(JsonObject value) => string.Join('|', new[] { "strasse", "plz", "ort", "region", "land" }
            .Select(name => RootLower(Trim(Text(value[name])))));
        var postal = Rows(content, "anschriften", ["art", "strasse", "plz", "ort", "region", "land"])
            .Where(value => Trim(PostalKey(value)).Length > 0).DistinctBy(PostalKey).ToArray();
        string[]? groups = content["gruppen"] is null ? null : TextList(content, "gruppen")
            .Select(value => Trim(value).Normalize(NormalizationForm.FormC)).Where(value => value.Length > 0)
            .DistinctBy(RootLower).OrderBy(value => value, StringComparer.Ordinal).ToArray();
        var fn = string.Join(' ', new[] { text["vorname"], text["nachname"] }.Where(value => value.Length > 0));
        var n = "N:" + EscapeName(text["nachname"]) + ";" + EscapeName(text["vorname"]) + ";;;";
        var legacy = text["jubilaeum"].Length == 0 && (text["anzeigename"].Length == 0 || text["anzeigename"] == fn) &&
            names.All(value => value == n || value == "FN:" + EscapeName(fn));
        var result = new JsonObject();
        foreach (var name in new[] { "vorname", "nachname", "firma", "notiz", "geburtstag" }) result[name] = text[name];
        if (groups is not null || !legacy)
        {
            result["jubilaeum"] = text["jubilaeum"]; result["anzeigename"] = text["anzeigename"];
            result["vcardName"] = new JsonArray(names.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        }
        if (text["foto"].Length > 0) result["foto"] = text["foto"];
        if (groups is not null) result["gruppen"] = new JsonArray(groups.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        result["telefone"] = new JsonArray(phones.Cast<JsonNode?>().ToArray());
        result["emailEintraege"] = new JsonArray(emails.Cast<JsonNode?>().ToArray());
        result["anschriften"] = new JsonArray(postal.Cast<JsonNode?>().ToArray());
        var output = new StringBuilder(); Write(output, result);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(output.ToString()))).ToLowerInvariant();
    }

    private static string Text(JsonNode? node)
    {
        if (node is not JsonValue primitive || !primitive.TryGetValue<string>(out var value))
            throw new InvalidDataException("notes_original_text_required");
        for (var index = 0; index < value.Length; index++)
            if (char.IsSurrogate(value[index]) && !(char.IsHighSurrogate(value[index]) && ++index < value.Length && char.IsLowSurrogate(value[index])))
                throw new InvalidDataException("notes_original_text_required");
        return value;
    }
    private static string[] TextList(JsonObject content, string name)
    {
        if (!content.ContainsKey(name)) return [];
        if (content[name] is not JsonArray values) throw new InvalidDataException("notes_original_list_required");
        return values.Select(Text).ToArray();
    }
    private static JsonObject[] Rows(JsonObject content, string name, string[] fields)
    {
        if (!content.ContainsKey(name)) return [];
        if (content[name] is not JsonArray values) throw new InvalidDataException("notes_original_list_required");
        return values.Select(value =>
        {
            if (value is not JsonObject row || !row.Select(pair => pair.Key).ToHashSet().SetEquals(fields))
                throw new InvalidDataException("notes_original_row_required");
            var owned = new JsonObject();
            foreach (var field in fields) owned[field] = Text(row[field]);
            return owned;
        }).ToArray();
    }
    private static bool Blank(char value) => value is '\t' or '\n' or '\v' or '\f' or '\r' or '\u001c' or '\u001d' or '\u001e' or '\u001f' ||
        char.GetUnicodeCategory(value) is UnicodeCategory.SpaceSeparator or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator;
    private static string Trim(string value)
    {
        var start = 0; var end = value.Length;
        while (start < end && Blank(value[start])) start++;
        while (end > start && Blank(value[end - 1])) end--;
        return value[start..end];
    }
    private static string EscapeName(string value) => value.Replace("\\", "\\\\").Replace("\r\n", "\\n").Replace("\n", "\\n").Replace(";", "\\;").Replace(",", "\\,");

    private static string RootLower(string value)
    {
        // Java ROOT string casing expands dotted I and determines final sigma
        // inside ROOT words. .NET invariant simple casing is not equivalent.
        if (!value.Contains('Σ') && !value.Contains('\u0130')) return value.ToLowerInvariant();
        static bool Cased(Rune rune)
        {
            var number = rune.Value;
            return Rune.GetUnicodeCategory(rune) is UnicodeCategory.LowercaseLetter or UnicodeCategory.UppercaseLetter or UnicodeCategory.TitlecaseLetter ||
                number is 0x345 or 0x37a or >= 0x2b0 and <= 0x2b8 or >= 0x2c0 and <= 0x2c1 or >= 0x2e0 and <= 0x2e4 or
                    >= 0x1d2c and <= 0x1d61 or >= 0x2160 and <= 0x217f or >= 0x24b6 and <= 0x24e9;
        }
        static char Kind(Rune rune)
        {
            var category = Rune.GetUnicodeCategory(rune); var number = rune.Value;
            var cjk = number is 0x3005 or 0x309d or 0x309e or 0x30fd or 0x30fe or >= 0x4e00 and <= 0x9fa5 or >= 0xf900 and <= 0xfa2d or
                >= 0x3041 and <= 0x3094 or >= 0x30a1 and <= 0x30fc or >= 0x3099 and <= 0x309c;
            if (!cjk && category is UnicodeCategory.UppercaseLetter or UnicodeCategory.LowercaseLetter or UnicodeCategory.TitlecaseLetter or
                UnicodeCategory.ModifierLetter or UnicodeCategory.OtherLetter or UnicodeCategory.SpacingCombiningMark) return 'L';
            return category is UnicodeCategory.DecimalDigitNumber or UnicodeCategory.LetterNumber or UnicodeCategory.OtherNumber ? 'N' : '\0';
        }
        static bool Middle(Rune rune, char previous, char following) => previous != '\0' && previous == following &&
            (previous == 'L' && (Rune.GetUnicodeCategory(rune) is UnicodeCategory.DashPunctuation or UnicodeCategory.ConnectorPunctuation || rune.Value is 0xad or 0x2027 or '"' or '\'' or '.') ||
             previous == 'N' && rune.Value is '"' or '\'' or ',' or 0x66b or '.');
        var original = value.EnumerateRunes().ToArray();
        var chars = original.Select((rune, index) => (rune, index)).Where(item => Rune.GetUnicodeCategory(item.rune) != UnicodeCategory.Format).ToArray();
        int UnitEnd(int start)
        {
            var end = start + 1;
            while (end < chars.Length && Rune.GetUnicodeCategory(chars[end].rune) is UnicodeCategory.NonSpacingMark or UnicodeCategory.EnclosingMark) end++;
            return end;
        }
        var finals = new HashSet<int>(); var offset = 0;
        while (offset < chars.Length)
        {
            var previous = Kind(chars[offset].rune);
            if (previous == '\0') { offset++; continue; }
            var start = offset; var end = UnitEnd(offset);
            while (end < chars.Length)
            {
                var following = Kind(chars[end].rune);
                if (following != '\0') { previous = following; end = UnitEnd(end); }
                else if (end + 1 < chars.Length && Middle(chars[end].rune, previous, Kind(chars[end + 1].rune)))
                { previous = Kind(chars[end + 1].rune); end = UnitEnd(end + 1); }
                else break;
            }
            var remaining = chars[start..end].Count(item => Cased(item.rune)); var before = 0;
            for (var index = start; index < end; index++)
            {
                var cased = Cased(chars[index].rune); if (cased) remaining--;
                if (chars[index].rune.Value == 'Σ' && before > 0 && remaining == 0) finals.Add(chars[index].index);
                if (cased) before++;
            }
            offset = end;
        }
        var output = new StringBuilder();
        for (var index = 0; index < original.Length; index++)
            if (original[index].Value == 0x130) output.Append("i\u0307");
            else if (original[index].Value == 'Σ') output.Append(finals.Contains(index) ? 'ς' : 'σ');
            else output.Append(Rune.ToLowerInvariant(original[index]).ToString());
        return output.ToString();
    }

    // KontaktSync.hash uses Kotlin serializer insertion order and raw Unicode,
    // unlike sorted/ASCII FS1 canonicalization or System.Text.Json's encoder.
    private static void Write(StringBuilder output, JsonNode node)
    {
        if (node is JsonObject obj)
        {
            output.Append('{'); var first = true;
            foreach (var pair in obj)
            {
                if (!first) output.Append(','); first = false;
                Quote(output, pair.Key); output.Append(':'); Write(output, pair.Value!);
            }
            output.Append('}');
        }
        else if (node is JsonArray array)
        {
            output.Append('[');
            for (var index = 0; index < array.Count; index++) { if (index > 0) output.Append(','); Write(output, array[index]!); }
            output.Append(']');
        }
        else Quote(output, Text(node));
    }
    private static void Quote(StringBuilder output, string value)
    {
        output.Append('"');
        foreach (var character in value)
            switch (character)
            {
                case '\b': output.Append("\\b"); break; case '\f': output.Append("\\f"); break;
                case '\n': output.Append("\\n"); break; case '\r': output.Append("\\r"); break; case '\t': output.Append("\\t"); break;
                case '"': output.Append("\\\""); break; case '\\': output.Append("\\\\"); break;
                default: if (character < 32) output.Append("\\u").Append(((int)character).ToString("x4")); else output.Append(character); break;
            }
        output.Append('"');
    }
}
