using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class PhoneContactRead
{
    internal const int Version = 5;
    internal const int ProfileVersion = 7;
    internal const int PageSize = 128;
    internal const int MaximumContacts = 10_000;
    internal const int MaximumCardBytes = 96 * 1024;
    internal const int MaximumReportBytes = 128 * 1024;

    internal static bool ValidUid(string value) => value.Length > 0 && value.EnumerateRunes().Count() <= 256 && !value.Any(char.IsControl);
    private static string Text(JsonObject value, string name) => value[name]?.GetValue<string>() ?? throw new InvalidDataException("invalid_contact_schema");
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
}
