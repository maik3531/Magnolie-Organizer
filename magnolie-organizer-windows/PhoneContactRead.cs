using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class PhoneContactRead
{
    internal const int Version = 5;
    internal const int ProfileVersion = 7;
    internal const int GroupWriteVersion = 17;
    internal const int GroupProbeVersion = 18;
    internal static bool IsGroupVersion(long version) => version is GroupWriteVersion or GroupProbeVersion;
    internal static bool IsScopedContactVersion(long version) => IsGroupVersion(version) || version is PhoneContactValueWrite.Version or PhoneContactGroupTitleWrite.Version;
    internal const int PageSize = 128;
    internal const int MaximumContacts = 10_000;
    internal const int MaximumCardBytes = 96 * 1024;
    internal const int MaximumReportBytes = 128 * 1024;

    internal static IEnumerable<KeyValuePair<string, JsonNode?>> GuiAvailability(JsonObject? nativeStatus)
    {
        foreach (var name in new[] { "contacts_read_available", "contact_groups_write_available", "contact_values_write_available", "contact_group_titles_write_available" })
            yield return KeyValuePair.Create<string, JsonNode?>(name, JsonValue.Create(nativeStatus?[name]?.GetValue<bool>() == true));
    }

    internal static bool ValidUid(string value) => value.Length > 0 && value.EnumerateRunes().Count() <= 256 && !value.Any(char.IsControl);
    private static string Text(JsonObject value, string name) => value[name] is JsonValue part && part.TryGetValue<string>(out var text) && text is not null
        ? text : throw new InvalidDataException("invalid_contact_schema");
    private static long Number(JsonObject value, string name) => TelefonProtocolContract.Integer(value[name]);

    internal static string[] ValidateRequest(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "offset", "uids");
        if (Number(value, "version") is not (Version or ProfileVersion) || !TelefonProtocolContract.IsUuidV4(Text(value, "request_id")) || value["uids"] is not JsonArray array)
            throw new InvalidDataException("invalid_contact_request");
        var uids = array.Select(node => node!.GetValue<string>()).ToArray();
        var action = Text(value, "action"); var offset = Number(value, "offset");
        if (Number(value, "version") == ProfileVersion)
        {
            if (action != "profile" || offset != 0 || uids.Length != 0) throw new InvalidDataException("invalid_profile_request");
            return uids;
        }
        if (uids.Any(uid => !ValidUid(uid)) || uids.Distinct(StringComparer.Ordinal).Count() != uids.Length ||
            !(action == "index" && offset is >= 0 and <= MaximumContacts && uids.Length == 0 ||
              action == "cards" && offset == 0 && uids.Length is >= 1 and <= 5)) throw new InvalidDataException("invalid_contact_request");
        return uids;
    }

    internal static void ValidateReport(JsonObject value)
    {
        if (Number(value, "version") == ProfileVersion)
        {
            TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "offset", "total", "contacts", "profile");
            var profile = TelefonProtocolContract.ExactObject(value["profile"]!, "state", "vcard");
            var state = Text(profile, "state"); var card = Text(profile, "vcard");
            if (!TelefonProtocolContract.IsUuidV4(Text(value, "request_id")) || Text(value, "action") != "profile" || Number(value, "offset") != 0 ||
                value["contacts"] is not JsonArray empty || empty.Count != 0 || state is not ("available" or "unavailable") ||
                Number(value, "total") != (state == "available" ? 1 : 0) || state == "unavailable" && card.Length != 0 ||
                state == "available" && (!card.StartsWith("BEGIN:VCARD\r\n") || !card.EndsWith("END:VCARD\r\n") || Encoding.UTF8.GetByteCount(card) > MaximumCardBytes))
                throw new InvalidDataException("invalid_profile_report");
            return;
        }
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "offset", "total", "contacts");
        if (Number(value, "version") != Version || !TelefonProtocolContract.IsUuidV4(Text(value, "request_id")) || value["contacts"] is not JsonArray contacts)
            throw new InvalidDataException("invalid_contact_report");
        var action = Text(value, "action"); var offset = Number(value, "offset"); var total = Number(value, "total");
        if (total is < 0 or > MaximumContacts || offset < 0 || offset > total ||
            !(action == "index" && contacts.Count <= PageSize && offset + contacts.Count <= total && (contacts.Count > 0 || offset == total) ||
              action == "cards" && offset == 0 && contacts.Count is >= 1 and <= 5 && total == contacts.Count))
            throw new InvalidDataException("invalid_contact_report");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var node in contacts)
        {
            var item = TelefonProtocolContract.ExactObject(node!, action == "index" ? ["uid", "timestamp"] : ["uid", "timestamp", "vcard"]);
            var uid = Text(item, "uid");
            if (!ValidUid(uid) || !seen.Add(uid) || Number(item, "timestamp") is < 0 or > 253402300799999L)
                throw new InvalidDataException("invalid_contact_report");
            if (action == "cards")
            {
                var card = Text(item, "vcard");
                if (!card.StartsWith("BEGIN:VCARD\r\n", StringComparison.Ordinal) || !card.EndsWith("END:VCARD\r\n", StringComparison.Ordinal) ||
                    Encoding.UTF8.GetByteCount(card) > MaximumCardBytes) throw new InvalidDataException("invalid_contact_vcard");
            }
        }
        if (TelefonCrypto.Canonical(value).Length > MaximumReportBytes) throw new InvalidDataException("contact_report_too_large");
    }

    private static bool ValidGroupText(string value, bool empty = false)
    {
        try { _ = new UTF8Encoding(false, true).GetByteCount(value); }
        catch (EncoderFallbackException) { return false; }
        return (empty || !string.IsNullOrWhiteSpace(value)) && value.EnumerateRunes().Count() <= 256 && !value.Any(char.IsControl);
    }

    internal static string[] GroupNames(JsonObject value, string field, int maximum = 100)
    {
        if (value[field] is not JsonArray array || array.Count > maximum) throw new InvalidDataException("invalid_contact_groups");
        var names = array.Select(node => node is JsonValue part && part.TryGetValue<string>(out var text) && text is not null
            ? text : throw new InvalidDataException("invalid_contact_groups")).ToArray();
        if (names.Any(name => !ValidGroupText(name)) || names.Select(name => name.Normalize(NormalizationForm.FormC).Trim().ToLowerInvariant()).Distinct(StringComparer.Ordinal).Count() != names.Length)
            throw new InvalidDataException("invalid_contact_groups");
        return names;
    }

    private static void GroupHeader(JsonObject value)
    {
        if (Number(value, "version") != GroupWriteVersion || !TelefonProtocolContract.IsUuidV4(Text(value, "request_id")) ||
            !ValidUid(Text(value, "uid")) || !ValidGroupText(Text(value, "uid"), empty: true) || Text(value, "action") is not ("prepare" or "apply") ||
            TelefonCrypto.Canonical(value).Length > MaximumReportBytes) throw new InvalidDataException("invalid_contact_group_schema");
    }

    internal static void ValidateGroupRequest(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, Text(value, "action") == "apply" ?
            ["version", "request_id", "action", "uid", "token", "groups"] : ["version", "request_id", "action", "uid"]);
        GroupHeader(value);
        if (Text(value, "action") == "apply")
        {
            if (!TelefonProtocolContract.IsUuidV4(Text(value, "token"))) throw new InvalidDataException("invalid_contact_group_token");
            GroupNames(value, "groups");
        }
    }

    internal static void ValidateGroupReport(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "uid", "token", "state", "groups", "catalog", "account");
        GroupHeader(value);
        if (!TelefonProtocolContract.IsUuidV4(Text(value, "token")) || Text(value, "state") != (Text(value, "action") == "prepare" ? "prepared" : "saved"))
            throw new InvalidDataException("invalid_contact_group_report");
        GroupNames(value, "groups"); var catalog = GroupNames(value, "catalog", 1000);
        if (Text(value, "action") == "apply" && catalog.Length != 0) throw new InvalidDataException("invalid_contact_group_report");
        var account = TelefonProtocolContract.ExactObject(value["account"]!, "name", "type", "data_set");
        if (account.Any(pair => !ValidGroupText(Text(account, pair.Key), empty: true))) throw new InvalidDataException("invalid_contact_group_account");
    }

    internal static void ValidateGroupProbeRequest(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "uid");
        if (Number(value, "version") != GroupProbeVersion || Text(value, "action") != "diagnostics") throw new InvalidDataException("invalid_contact_group_probe");
        var header = value.DeepClone().AsObject(); header["version"] = GroupWriteVersion; header["action"] = "prepare";
        ValidateGroupRequest(header);
    }

    internal static void ValidateGroupProbeReport(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "version", "request_id", "action", "uid", "state", "stage", "error_type", "reason",
            "raw_count", "version_count", "account_count", "mime_supported", "reader_complete");
        ValidateGroupProbeRequest(new JsonObject(new[] { "version", "request_id", "action", "uid" }
            .Select(key => KeyValuePair.Create(key, value[key]?.DeepClone()))));
        if (Text(value, "state") is not ("available" or "failed") ||
            Text(value, "stage") is not ("request" or "permission" or "snapshot" or "snapshot_shape" or "uid" or "raw_versions" or "account_scope" or "groups" or "catalog" or "report" or "complete") ||
            !System.Text.RegularExpressions.Regex.IsMatch(Text(value, "error_type"), @"\A[A-Za-z][A-Za-z0-9]{0,63}\z") ||
            Text(value, "reason") is not ("none" or "contact_groups_ambiguous_account" or "contact_groups_unknown" or "contact_groups_unavailable" or "contact_groups_incomplete" or "provider_failure"))
            throw new InvalidDataException("invalid_contact_group_probe");
        foreach (var key in new[] { "raw_count", "version_count", "account_count" })
            if (Number(value, key) is < 0 or > 10000) throw new InvalidDataException("invalid_contact_group_probe");
        foreach (var key in new[] { "mime_supported", "reader_complete" })
            if (value[key] is not JsonValue flag || !flag.TryGetValue<bool>(out _)) throw new InvalidDataException("invalid_contact_group_probe");
        if (Text(value, "state") == "available" && (Text(value, "stage") != "complete" || Text(value, "error_type") != "None" ||
            Text(value, "reason") != "none" || value["reader_complete"]!.GetValue<bool>() != true)) throw new InvalidDataException("invalid_contact_group_probe");
    }
}
