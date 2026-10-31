using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Typed resource 20 codec; actual provider permission and source binding remain caller gates.
internal static class PhoneContactGroupTitleWrite
{
    internal const int Version = 20;
    internal const bool RuntimeEnabled = true;
    internal const int MaximumBytes = 16 * 1024;
    private static string Text(JsonNode? node, int maximum, bool empty = false)
    {
        if (node is not JsonValue value || !value.TryGetValue<string>(out var text) || text is null ||
            !empty && string.IsNullOrWhiteSpace(text) || text.Any(char.IsControl) || text.EnumerateRunes().Count() > maximum)
            throw new InvalidDataException("invalid_contact_group_title");
        try { _ = new UTF8Encoding(false, true).GetByteCount(text); }
        catch (EncoderFallbackException) { throw new InvalidDataException("invalid_contact_group_title"); }
        return text;
    }
    private static string Header(JsonObject value)
    {
        if (TelefonProtocolContract.Integer(value["version"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(value["request_id"], 36)) ||
            !PhoneContactRead.ValidUid(Text(value["uid"], 256)))
            throw new InvalidDataException("invalid_contact_group_title_schema");
        var action = Text(value["action"], 16);
        if (action is not ("prepare" or "apply" or "inspect")) throw new InvalidDataException("invalid_contact_group_title_action");
        var oldTitle = Text(value["old_title"], 256); var newTitle = Text(value["new_title"], 256);
        if (oldTitle == newTitle || new[] { oldTitle, newTitle }.Any(title => title != title.Trim().Normalize(NormalizationForm.FormC)))
            throw new InvalidDataException("invalid_contact_group_title");
        return action;
    }
    internal static void ValidateRequestShape(JsonObject value)
    {
        var action = Header(value);
        TelefonProtocolContract.ExactObject(value, action switch {
            "prepare" => ["version", "request_id", "action", "uid", "old_title", "new_title"],
            "inspect" => ["version", "request_id", "action", "uid", "old_title", "new_title", "group_id", "account"],
            _ => ["version", "request_id", "action", "uid", "old_title", "new_title", "token"] });
        if (action == "apply" && !TelefonProtocolContract.IsUuidV4(Text(value["token"], 36)))
            throw new InvalidDataException("invalid_contact_group_title_token");
        if (action == "inspect") IdentityFields(value);
        if (TelefonCrypto.Canonical(value).Length > MaximumBytes) throw new InvalidDataException("contact_group_title_too_large");
    }
    internal static void ValidateReportShape(JsonObject value)
    {
        var action = Header(value);
        TelefonProtocolContract.ExactObject(value, new[] { "version", "request_id", "action", "uid", "old_title", "new_title", "state", "group_id", "account", "group_identity" }
            .Concat(action == "inspect" ? ["current_title"] : new[] { "token" }).ToArray());
        IdentityFields(value);
        var identity = Text(value["group_identity"], 64);
        if (identity.Length != 64 || identity.Any(character => character is not (>= '0' and <= '9' or >= 'a' and <= 'f')) ||
            action != "inspect" && !TelefonProtocolContract.IsUuidV4(Text(value["token"], 36)) ||
            Text(value["state"], 16) != (action == "inspect" ? "current" : action == "prepare" ? "prepared" : "saved"))
            throw new InvalidDataException("invalid_contact_group_title_report");
        if (action == "inspect") _ = Text(value["current_title"], 256);
        if (TelefonCrypto.Canonical(value).Length > MaximumBytes) throw new InvalidDataException("contact_group_title_too_large");
    }
    private static void IdentityFields(JsonObject value)
    {
        var id = Text(value["group_id"], 19);
        if (!long.TryParse(id, NumberStyles.None, CultureInfo.InvariantCulture, out var groupId) || groupId <= 0 ||
            id != groupId.ToString(CultureInfo.InvariantCulture))
            throw new InvalidDataException("invalid_contact_group_title_report");
        var account = TelefonProtocolContract.ExactObject(value["account"]!, "name", "type", "data_set");
        foreach (var pair in account) _ = Text(pair.Value, 256, empty: true);
    }
    internal static void ValidateCorrelatedReport(JsonObject report, JsonObject request, JsonObject? prepared = null)
    {
        ValidateRequestShape(request); ValidateReportShape(report);
        foreach (var key in new[] { "request_id", "action", "uid", "old_title", "new_title" })
            if (!JsonNode.DeepEquals(report[key], request[key])) throw new InvalidDataException("contact_group_title_source_changed");
        if (request["action"]!.GetValue<string>() == "inspect")
        {
            if (!JsonNode.DeepEquals(report["group_id"], request["group_id"]) || !JsonNode.DeepEquals(report["account"], request["account"]))
                throw new InvalidDataException("contact_group_title_source_changed");
            return;
        }
        if (request["action"]!.GetValue<string>() != "apply") return;
        if (prepared is null) throw new InvalidDataException("contact_group_title_preparation_missing");
        ValidateReportShape(prepared);
        if (prepared["action"]!.GetValue<string>() != "prepare" || !JsonNode.DeepEquals(report["token"], request["token"]))
            throw new InvalidDataException("contact_group_title_preparation_changed");
        foreach (var key in new[] { "uid", "old_title", "new_title", "token", "group_id", "account", "group_identity" })
            if (!JsonNode.DeepEquals(report[key], prepared[key])) throw new InvalidDataException("contact_group_title_preparation_changed");
    }
    internal static bool MatchesSavedIntent(JsonObject inspection, JsonObject prepared)
    {
        ValidateReportShape(inspection); ValidateReportShape(prepared);
        return inspection["action"]!.GetValue<string>() == "inspect" && prepared["action"]!.GetValue<string>() == "prepare" &&
            new[] { "uid", "old_title", "new_title", "group_id", "account", "group_identity" }.All(key => JsonNode.DeepEquals(inspection[key], prepared[key])) &&
            JsonNode.DeepEquals(inspection["current_title"], prepared["new_title"]);
    }
}
