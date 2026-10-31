using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Typed phone/email transport; provider projection semantics stay native and
// the consent, field mask, source binding and actual readback remain independent guards.
internal static class PhoneContactValueWrite
{
    internal const int Version = 19;
    internal const int MaximumBytes = 128 * 1024;
    private static readonly string[] Fields = ["telefone", "emailEintraege"];
    internal static IEnumerable<string> ReadableFields(string vcard, JsonObject contact)
    {
        var unfolded = Regex.Replace(vcard, @"\r?\n[ \t]", "");
        foreach (var (property, field) in new[] { ("TEL", "telefone"), ("EMAIL", "emailEintraege") })
            if (contact[field] is JsonArray rows && Regex.Matches(unfolded, @"(?im)^(?:[A-Za-z0-9-]+\.)?" + property + @"(?:;|:)").Count == rows.Count)
                yield return field;
    }
    private static string Text(JsonNode? node, int maximum, bool empty = false)
    {
        if (node is not JsonValue value || !value.TryGetValue<string>(out var text) || text is null ||
            !empty && string.IsNullOrWhiteSpace(text) || text.Any(char.IsControl) || text.EnumerateRunes().Count() > maximum)
            throw new InvalidDataException("invalid_contact_value");
        try { _ = new UTF8Encoding(false, true).GetByteCount(text); }
        catch (EncoderFallbackException) { throw new InvalidDataException("invalid_contact_value"); }
        return text;
    }
    private static string Header(JsonObject value)
    {
        if (TelefonProtocolContract.Integer(value["version"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(value["request_id"], 36)) || !PhoneContactRead.ValidUid(Text(value["uid"], 256)) ||
            TelefonCrypto.Canonical(value).Length > MaximumBytes) throw new InvalidDataException("invalid_contact_value_schema");
        var action = Text(value["action"], 16);
        return action is "prepare" or "apply" ? action : throw new InvalidDataException("invalid_contact_value_action");
    }
    internal static string[] FieldNames(JsonObject value)
    {
        if (value["field_names"] is not JsonArray array || array.Count is < 1 or > 2)
            throw new InvalidDataException("invalid_contact_fields");
        var names = array.Select(node => Text(node, 32)).ToArray();
        if (names.Distinct(StringComparer.Ordinal).Count() != names.Length || names.Any(name => !Fields.Contains(name)))
            throw new InvalidDataException("invalid_contact_fields");
        return names;
    }
    internal static string[] ValidateFieldsShape(JsonObject value)
    {
        if (value["fields"] is not JsonObject fields || fields.Count is < 1 or > 2 || fields.Any(pair => !Fields.Contains(pair.Key)))
            throw new InvalidDataException("invalid_contact_fields");
        foreach (var pair in fields)
        {
            if (pair.Value is not JsonArray rows || rows.Count > 100) throw new InvalidDataException("invalid_contact_values");
            foreach (var row in rows)
            {
                var entry = TelefonProtocolContract.ExactObject(row!, "art", "wert");
                if (Text(entry["art"], 32) is not ("privat" or "arbeit" or "mobil" or "sonstige"))
                    throw new InvalidDataException("invalid_contact_kind");
                _ = Text(entry["wert"], 4096);
            }
            if (Rows(rows).Distinct().Count() != rows.Count) throw new InvalidDataException("duplicate_contact_value");
        }
        return fields.Select(pair => pair.Key).ToArray();
    }
    internal static void ValidateRequestShape(JsonObject value)
    {
        var action = Header(value);
        TelefonProtocolContract.ExactObject(value, action == "prepare" ?
            ["version", "request_id", "action", "uid", "field_names"] : ["version", "request_id", "action", "uid", "token", "fields"]);
        if (action == "prepare") _ = FieldNames(value);
        else
        {
            if (!TelefonProtocolContract.IsUuidV4(Text(value["token"], 36))) throw new InvalidDataException("invalid_contact_value_token");
            _ = ValidateFieldsShape(value);
        }
    }
    internal static void ValidateReportShape(JsonObject value)
    {
        var action = Header(value);
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "uid", "token", "account", "state", "fields");
        if (!TelefonProtocolContract.IsUuidV4(Text(value["token"], 36)) || Text(value["state"], 16) != (action == "prepare" ? "prepared" : "saved"))
            throw new InvalidDataException("invalid_contact_value_report");
        var account = TelefonProtocolContract.ExactObject(value["account"]!, "name", "type", "data_set");
        foreach (var pair in account) _ = Text(pair.Value, 256, empty: true);
        _ = ValidateFieldsShape(value);
    }
    private static IEnumerable<(string Kind, string Value)> Rows(JsonArray rows) => rows.Select(row =>
        (Text(row!["art"], 32), Text(row["wert"], 4096)));

    internal static void ValidateCorrelatedReport(JsonObject report, JsonObject request, JsonObject? preparedAccount = null)
    {
        ValidateRequestShape(request); ValidateReportShape(report);
        foreach (var key in new[] { "request_id", "action", "uid" })
            if (!JsonNode.DeepEquals(report[key], request[key])) throw new InvalidDataException("contact_value_source_changed");
        var names = ValidateFieldsShape(report).ToHashSet(StringComparer.Ordinal);
        if (!names.SetEquals(request["action"]!.GetValue<string>() == "prepare" ? FieldNames(request) : ValidateFieldsShape(request)))
            throw new InvalidDataException("contact_value_fields_changed");
        if (request["action"]!.GetValue<string>() != "apply") return;
        if (!JsonNode.DeepEquals(report["token"], request["token"]) || preparedAccount is null || !JsonNode.DeepEquals(report["account"], preparedAccount))
            throw new InvalidDataException("contact_value_account_changed");
        foreach (var name in names)
            if (!Rows(report["fields"]![name]!.AsArray()).ToHashSet().SetEquals(Rows(request["fields"]![name]!.AsArray())))
                throw new InvalidDataException("contact_value_readback_failed");
    }
}
