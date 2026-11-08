using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Separate media intent, never a personal-data setting or an access grant.
// Reuse the existing strict two-actor register implementation, not its policy.
internal static class MediaSyncSettings
{
    internal const int DiscoveryVersion = 23, Version = 1;
    internal const string Kind = "file_transfer.shared_settings";
    internal const string StartKind = "file_transfer.sync_request", ResultKind = "file_transfer.sync_result";

    internal static void ValidateStart(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "settings");
        if (TelefonProtocolContract.Integer(body["format"]) != 1 || body["settings"] is not JsonObject settings)
            throw new InvalidDataException("media_sync_request_invalid");
        Validate(settings);
        if (settings["settings"]!.AsObject().Count != Fields.Count) throw new InvalidDataException("media_sync_request_full_snapshot_required");
    }

    internal static void ValidateResult(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "request_id", "state");
        if (TelefonProtocolContract.Integer(body["format"]) != 1 || !TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(body, "request_id")) ||
            TelefonMessagingContract.String(body, "state") is not ("content_pass" or "review" or "held"))
            throw new InvalidDataException("media_sync_result_invalid");
    }
    private static readonly Dictionary<string, string> Fields = new(StringComparer.Ordinal)
    {
        ["photos_enabled"] = "custom_enabled", ["videos_enabled"] = "time_enabled",
        ["auto_mode"] = "auto_mode", ["skip_deletions"] = "skip_deletions",
        ["collection_mode"] = "content_mode", ["direction"] = "content_mode", ["enabled"] = "custom_enabled", ["photos_only"] = "skip_deletions"
    };

    private static JsonNode? SettingValue(string field, JsonNode? value, bool toRegisters)
    {
        if (field is not ("collection_mode" or "direction" or "auto_mode")) return value?.DeepClone();
        if (value is not JsonValue primitive || !primitive.TryGetValue<string>(out var text))
            throw new InvalidDataException("media_shared_settings_invalid_mode");
        var translated = (field, toRegisters, text) switch
        {
            ("collection_mode", true, "phone_inventory") => "phone_scope",
            ("collection_mode", true, "entire_collection") => "two_way",
            ("collection_mode", true, "import_only") => "phone_import",
            ("collection_mode", false, "phone_scope") => "phone_inventory",
            ("collection_mode", false, "two_way") => "entire_collection",
            ("collection_mode", false, "phone_import") => "import_only",
            ("direction", true, "phone_to_pc") => "phone_import",
            ("direction", true, "two_way") => "two_way",
            ("direction", true, "pc_to_phone") => "phone_scope",
            ("direction", false, "phone_import") => "phone_to_pc",
            ("direction", false, "two_way") => "two_way",
            ("direction", false, "phone_scope") => "pc_to_phone",
            ("auto_mode", _, "manual") => "manual",
            ("auto_mode", _, "wifi") => "wifi",
            _ => throw new InvalidDataException("media_shared_settings_invalid_mode")
        };
        return JsonValue.Create(translated);
    }

    private static JsonObject SettingRegister(string field, JsonNode? raw, bool toRegisters)
    {
        if (raw is not JsonObject edits) throw new InvalidDataException("media_shared_settings_invalid_register");
        var result = edits.DeepClone().AsObject();
        foreach (var (_, edit) in result)
        {
            if (edit is not JsonObject value) throw new InvalidDataException("media_shared_settings_invalid_edit");
            value["value"] = SettingValue(field, value["value"], toRegisters);
        }
        return result;
    }

    private static JsonObject Registers(string field, JsonNode? raw)
    {
        if (!Fields.TryGetValue(field, out var mapped)) throw new InvalidDataException("media_shared_settings_unknown_field");
        // Each media field has its OWN register. In particular module activation
        // and photo selection must never share a counter or overwrite each other.
        return SharedSyncSettings.Validate(new JsonObject { ["format"] = SharedSyncSettings.Version,
            ["settings"] = new JsonObject { [mapped] = SettingRegister(field, raw, true) } });
    }

    internal static JsonObject Validate(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "settings");
        if (TelefonProtocolContract.Integer(body["format"]) != Version || body["settings"] is not JsonObject values || values.Count < 1 || values.Count > Fields.Count)
            throw new InvalidDataException("media_shared_settings_invalid");
        foreach (var (field, raw) in values) _ = Registers(field, raw);
        return body;
    }

    private static void Scoped(JsonObject body, string localActor, string peerActor, bool complete)
    {
        Validate(body);
        if (complete && body["settings"]!.AsObject().Count != Fields.Count) throw new InvalidDataException("media_shared_settings_incomplete_local_state");
        foreach (var (field, raw) in body["settings"]!.AsObject())
        {
            var register = Registers(field, raw);
            _ = SharedSyncSettings.Merge(register, register, localActor, peerActor);
        }
    }

    internal static JsonObject Create(string localActor)
    {
        var defaults = new JsonObject { ["enabled"] = false, ["photos_enabled"] = true, ["videos_enabled"] = false,
            ["collection_mode"] = "phone_inventory", ["auto_mode"] = "manual", ["skip_deletions"] = false, ["direction"] = "phone_to_pc", ["photos_only"] = false };
        var fields = new JsonObject();
        foreach (var (field, value) in defaults) fields[field] = new JsonObject {
            [localActor] = new JsonObject { ["counter"] = 0, ["value"] = value!.DeepClone() } };
        return Validate(new JsonObject { ["format"] = Version, ["settings"] = fields });
    }

    internal static JsonObject Effective(JsonObject body)
    {
        Validate(body); var result = new JsonObject();
        foreach (var (field, raw) in body["settings"]!.AsObject())
        {
            var values = SharedSyncSettings.Effective(Registers(field, raw));
            result[field] = SettingValue(field, values[Fields[field]], false);
        }
        if (body["settings"]!["auto_mode"] is JsonObject modes)
        {
            var newest = modes.Max(edit => TelefonProtocolContract.Integer(edit.Value!["counter"]));
            result["auto_mode"] = modes.Any(edit => TelefonProtocolContract.Integer(edit.Value!["counter"]) == newest &&
                edit.Value!["value"]!.GetValue<string>() == "manual") ? "manual" : "wifi";
        }
        // Import scope never exports; returning to an inventory scope retains
        // the independently stored direction and its original edit history.
        if (result["collection_mode"]?.GetValue<string>() == "import_only" && result.ContainsKey("direction")) result["direction"] = "phone_to_pc";
        return result;
    }

    // Only authenticated stored records use this migration, never wire patches.
    // Do not rewrite existing registers or enable a filter during a passive read.
    internal static JsonObject NormalizeStored(JsonObject body, string localActor, string peerActor)
    {
        Scoped(body, localActor, peerActor, complete: false);
        var keys = body["settings"]!.AsObject().Select(field => field.Key).ToHashSet(StringComparer.Ordinal);
        if (!keys.SetEquals(Fields.Keys) && !keys.SetEquals(Fields.Keys.Where(field => field != "photos_only")))
            throw new InvalidDataException("media_shared_settings_incomplete_local_state");
        var result = body.DeepClone().AsObject();
        if (!keys.Contains("photos_only")) result["settings"]!["photos_only"] = new JsonObject {
            [localActor] = new JsonObject { ["counter"] = 0, ["value"] = false } };
        Scoped(result, localActor, peerActor, complete: true);
        return result;
    }

    internal static bool TransferRequestedFor(JsonObject body, string mediaType, bool toPhone)
    {
        if (!RequestedFor(body, mediaType)) return false;
        var direction = Effective(body)["direction"]!.GetValue<string>();
        return direction == "two_way" || direction == (toPhone ? "pc_to_phone" : "phone_to_pc");
    }

    internal static bool RequestedFor(JsonObject body, string mediaType)
    {
        if (body["settings"] is not JsonObject fields || fields.Count != Fields.Count || mediaType is not ("images" or "video"))
            throw new InvalidDataException("media_shared_settings_incomplete_local_state");
        var values = Effective(body);
        return values["enabled"]!.GetValue<bool>() && values[mediaType == "images" ? "photos_enabled" : "videos_enabled"]!.GetValue<bool>();
    }

    internal static JsonObject Change(JsonObject body, string localActor, string peerActor, string field, JsonNode value)
    {
        if (!Fields.TryGetValue(field, out var mapped)) throw new InvalidDataException("media_shared_settings_unknown_field");
        Scoped(body, localActor, peerActor, complete: true);
        var changed = SharedSyncSettings.Change(Registers(field, body["settings"]![field]), localActor, peerActor, mapped, SettingValue(field, value, true)!);
        var result = body.DeepClone().AsObject();
        result["settings"]![field] = SettingRegister(field, changed["settings"]![mapped], false);
        return Validate(result);
    }

    internal static JsonObject Merge(JsonObject body, JsonObject incoming, string localActor, string peerActor)
        => MergeOwned(body, incoming, localActor, peerActor, false);

    internal static JsonObject MergeCurrentChoices(JsonObject body, JsonObject incoming, string localActor, string peerActor)
        => MergeOwned(body, incoming, localActor, peerActor, true);

    private static JsonObject MergeOwned(JsonObject body, JsonObject incoming, string localActor, string peerActor, bool currentChoices)
    {
        Scoped(body, localActor, peerActor, complete: true); Scoped(incoming, localActor, peerActor, complete: false);
        var result = body.DeepClone().AsObject();
        foreach (var (field, raw) in incoming["settings"]!.AsObject())
        {
            var before = Registers(field, result["settings"]![field]); var next = Registers(field, raw);
            var merged = currentChoices ? SharedSyncSettings.MergeCurrentChoices(before, next, localActor, peerActor)
                : SharedSyncSettings.Merge(before, next, localActor, peerActor);
            result["settings"]![field] = SettingRegister(field, merged["settings"]![Fields[field]], false);
        }
        return Validate(result);
    }
}
