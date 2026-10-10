using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>Common function preferences; authentication, ownership and OS rights stay caller gates.</summary>
internal static class SharedSyncSettings
{
    internal const int Version = 9;
    internal const string Kind = "personal_sync.shared_settings";
    private const long MaximumCounter = 9007199254740991;
    private static readonly JsonObject Defaults = new()
    { ["content_mode"] = "phone_scope", ["auto_mode"] = "manual", ["skip_deletions"] = true,
      ["custom_enabled"] = false, ["time_enabled"] = false, ["time_mode"] = "phone_import" };

    internal static bool Supported(JsonObject local, JsonObject remote)
    {
        static bool Marked(JsonObject items) => new[] { "personal_notes_sync", "personal_tasks_sync" }.All(name =>
            items[name] is JsonObject item && item["available"] is JsonValue enabled && enabled.TryGetValue<bool>(out var available) &&
            available && item["versions"] is JsonArray versions && versions.Any(value =>
                TelefonProtocolContract.TryInteger(value, out var marker) && marker == Version));
        return Marked(local) && Marked(remote);
    }

    private static void Actor(string value)
    { if (!TelefonProtocolContract.IsUuidV4(value)) throw new InvalidDataException("Invalid shared settings actor."); }
    private static void Value(string field, JsonNode? value)
    {
        if (!Defaults.ContainsKey(field)) throw new InvalidDataException("Unknown common function setting.");
        if (field is "content_mode" or "time_mode" or "auto_mode")
        {
            if (value is not JsonValue text || !text.TryGetValue<string>(out var mode) ||
                (field == "auto_mode" ? mode is not ("manual" or "wifi" or "connection") :
                    field == "content_mode" ? mode is not ("phone_import" or "phone_scope" or "two_way") : mode is not ("phone_import" or "two_way")))
                throw new InvalidDataException("Invalid common function mode.");
        }
        else if (value is not JsonValue boolean || !boolean.TryGetValue<bool>(out _))
            throw new InvalidDataException("Invalid common function switch.");
    }

    private static long Counter(JsonObject edit)
    {
        var value = TelefonProtocolContract.Integer(edit["counter"]);
        if (value is < 0 or > MaximumCounter) throw new InvalidDataException("Invalid shared setting counter.");
        return value;
    }

    internal static JsonObject Validate(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "settings");
        if (TelefonProtocolContract.Integer(body["format"]) != Version || body["settings"] is not JsonObject fields ||
            fields.Count < 1 || fields.Count > Defaults.Count) throw new InvalidDataException("Invalid shared function settings.");
        foreach (var (field, raw) in fields)
        {
            if (!Defaults.ContainsKey(field) || raw is not JsonObject edits || edits.Count is < 1 or > 2)
                throw new InvalidDataException("Invalid shared setting register.");
            foreach (var (origin, rawEdit) in edits)
            {
                Actor(origin);
                var edit = rawEdit as JsonObject ?? throw new InvalidDataException("Invalid shared setting edit.");
                TelefonProtocolContract.ExactObject(edit, "counter", "value"); Counter(edit); Value(field, edit["value"]);
            }
        }
        return body;
    }

    internal static JsonObject Create(string localActor, JsonObject? initial = null)
    {
        Actor(localActor); var values = Defaults.DeepClone().AsObject();
        if (initial is not null) foreach (var (field, value) in initial)
        { Value(field, value); values[field] = value!.DeepClone(); }
        var fields = new JsonObject();
        foreach (var (field, value) in values) fields[field] = new JsonObject
        { [localActor] = new JsonObject { ["counter"] = 0, ["value"] = value!.DeepClone() } };
        return Validate(new JsonObject { ["format"] = Version, ["settings"] = fields });
    }

    internal static JsonObject Effective(JsonObject body)
    {
        Validate(body); var result = new JsonObject();
        foreach (var (field, raw) in body["settings"]!.AsObject())
        {
            var edits = raw!.AsObject().Select(item => item.Value!.AsObject()).ToArray();
            var newest = edits.Max(Counter); var values = edits.Where(edit => Counter(edit) == newest).Select(edit => edit["value"]!).ToArray();
            result[field] = field switch
            {
                "content_mode" => JsonValue.Create(new[] { "phone_import", "phone_scope", "two_way" }.First(mode => values.Any(value => value.GetValue<string>() == mode))),
                "time_mode" => JsonValue.Create(values.Any(value => value.GetValue<string>() == "phone_import") ? "phone_import" : "two_way"),
                "custom_enabled" or "time_enabled" => JsonValue.Create(values.All(value => value.GetValue<bool>())),
                "skip_deletions" => JsonValue.Create(values.Any(value => value.GetValue<bool>())),
                _ => JsonValue.Create((newest == 0 ? new[] { "wifi", "manual", "connection" } : new[] { "manual", "wifi", "connection" })
                    .First(mode => values.Any(value => value.GetValue<string>() == mode)))
            };
        }
        return result;
    }

    private static void Scoped(JsonObject body, string localActor, string peerActor)
    {
        Validate(body); Actor(localActor); Actor(peerActor);
        if (localActor == peerActor || body["settings"]!.AsObject().Any(field => field.Value!.AsObject().Any(edit => edit.Key != localActor && edit.Key != peerActor)))
            throw new InvalidDataException("Shared settings belong to a different paired device.");
    }

    internal static JsonObject Change(JsonObject body, string localActor, string peerActor, string field, JsonNode value)
    {
        Scoped(body, localActor, peerActor); Value(field, value);
        var result = body.DeepClone().AsObject(); var fields = result["settings"]!.AsObject();
        var edits = fields[field] as JsonObject ?? new JsonObject();
        var counter = edits.Count == 0 ? 1 : edits.Max(edit => Counter(edit.Value!.AsObject())) + 1;
        if (counter > MaximumCounter) throw new InvalidDataException("Shared setting counter exhausted.");
        edits[localActor] = new JsonObject { ["counter"] = counter, ["value"] = value.DeepClone() }; fields[field] = edits;
        return Validate(result);
    }

    internal static JsonObject Merge(JsonObject body, JsonObject incoming, string localActor, string peerActor)
    {
        Scoped(body, localActor, peerActor); Scoped(incoming, localActor, peerActor);
        var result = body.DeepClone().AsObject(); var fields = result["settings"]!.AsObject();
        foreach (var (field, raw) in incoming["settings"]!.AsObject())
        {
            var target = fields[field] as JsonObject ?? new JsonObject();
            foreach (var (origin, rawEdit) in raw!.AsObject())
            {
                var edit = rawEdit!.AsObject(); var previous = target[origin] as JsonObject;
                if (origin == localActor)
                {
                    if (previous is null || Counter(edit) > Counter(previous) ||
                        Counter(edit) == Counter(previous) && !JsonNode.DeepEquals(edit, previous))
                        throw new InvalidDataException("Unknown or conflicting local setting echo.");
                    continue;
                }
                if (previous is not null)
                {
                    if (Counter(edit) < Counter(previous)) continue;
                    if (Counter(edit) == Counter(previous) && !JsonNode.DeepEquals(edit, previous))
                        throw new InvalidDataException("Conflicting shared setting edit.");
                }
                target[origin] = edit.DeepClone();
            }
            fields[field] = target;
        }
        return Validate(result);
    }
}
