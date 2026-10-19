using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>Correlated content starts; authentication and current ownership remain caller gates.
/// Not advertised before actor-scoped staging/commit is connected.</summary>
internal static class PersonalSyncActorContract
{
    internal const int Version = 12;
    internal const string StartKind = "personal_sync.actor_start";
    internal const string DataKind = "personal_sync.actor_data";
    internal const string AckKind = "personal_sync.actor_ack";
    private static readonly HashSet<string> DataKinds = ["personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
        "personal_sync.deletion_proposals", "personal_sync.deletion_decision", PhoneContentScope.DataKind];
    private static string Text(JsonObject value, string field) => value[field] is JsonValue scalar && scalar.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("Invalid actor text field.");

    internal static bool IsReservedMessage(JsonObject value) =>
        value["type"] is JsonValue type && type.TryGetValue<string>(out var messageType) && messageType == "message" &&
        value["kind"] is JsonValue kind && kind.TryGetValue<string>(out var name) && IsReservedKind(name);

    internal static bool IsReservedKind(string? name) => name is StartKind or DataKind or AckKind;

    internal static JsonObject ValidateStart(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "run_id", "trigger");
        if (TelefonProtocolContract.Integer(body["format"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(body, "run_id")) || Text(body, "trigger") != "manual")
            throw new InvalidDataException("Invalid actor-scoped synchronization start.");
        return body;
    }

    internal static JsonObject Start(string runId) => ValidateStart(new JsonObject
    { ["format"] = Version, ["run_id"] = runId, ["trigger"] = "manual" });

    internal static JsonObject ValidateAck(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "run_id", "message_id", "status", "error");
        if (TelefonProtocolContract.Integer(body["format"]) != Version || !TelefonProtocolContract.IsUuidV4(Text(body, "run_id")))
            throw new InvalidDataException("Invalid actor acknowledgement identity.");
        TelefonProtocolContract.ValidateAck(new JsonObject { ["type"] = "ack", ["message_id"] = body["message_id"]?.DeepClone(),
            ["status"] = body["status"]?.DeepClone(), ["error"] = body["error"]?.DeepClone() });
        return body;
    }

    internal static JsonObject Ack(string runId, string messageId, string status = "accepted", string error = "none") =>
        ValidateAck(new JsonObject { ["format"] = Version, ["run_id"] = runId, ["message_id"] = messageId, ["status"] = status, ["error"] = error });

    internal static JsonObject ValidateData(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "format", "run_id", "kind", "body");
        var runId = Text(value, "run_id"); var kind = Text(value, "kind");
        if (TelefonProtocolContract.Integer(value["format"]) != Version || !TelefonProtocolContract.IsUuidV4(runId) ||
            !DataKinds.Contains(kind) || value["body"] is not JsonObject body)
            throw new InvalidDataException("Invalid actor data envelope.");
        JsonObject recordBody;
        if (kind == PhoneContentScope.DataKind) { PhoneContentScope.ValidateData(body); recordBody = body["body"]!.AsObject(); }
        else { PersonalSyncContract.ValidateBody(kind, body); recordBody = body; }
        if (recordBody["run_id"]?.GetValue<string>() != runId || (recordBody.ContainsKey("trigger") && recordBody["trigger"]?.GetValue<string>() != "manual") ||
            TelefonCrypto.Canonical(value).Length > PersonalSyncContract.MaxChunkBody)
            throw new InvalidDataException("Actor data identity or size mismatch.");
        return value;
    }

    internal static JsonObject Wrap(string runId, string kind, JsonObject body) => ValidateData(new JsonObject
    { ["format"] = Version, ["run_id"] = runId, ["kind"] = kind, ["body"] = body.DeepClone() });

    internal static (string Kind, JsonObject Body) Unwrap(JsonObject value)
    {
        ValidateData(value);
        return (value["kind"]!.GetValue<string>(), value["body"]!.DeepClone().AsObject());
    }

    // The caller validates the original message header; ACK identity/lifetime do not change.
    internal static JsonObject WireMessage(JsonObject message, string runId)
    {
        var result = message.DeepClone().AsObject();
        result["body"] = Wrap(runId, Text(message, "kind"), message["body"]!.AsObject());
        result["kind"] = DataKind;
        if (TelefonCrypto.Canonical(result).Length > PersonalSyncContract.MaxChunkBody)
            throw new InvalidDataException("Actor wire frame too large.");
        return result;
    }

    // Explicit semantic inspection must never replace the persisted/sent actor wire frame.
    internal static JsonObject SemanticMessage(JsonObject message)
    {
        if (message["kind"]?.GetValue<string>() != DataKind) return message;
        var inner = Unwrap(message["body"]!.AsObject()); var result = message.DeepClone().AsObject();
        result["kind"] = inner.Kind; result["body"] = inner.Body;
        return result;
    }

    internal static bool Supported(JsonObject local, JsonObject remote) => SharedSyncSettings.Supported(local, remote) &&
        new[] { local, remote }.All(items => new[] { "personal_notes_sync", "personal_tasks_sync" }.All(name =>
            items[name]?["available"] is JsonValue flag && flag.TryGetValue<bool>(out var available) && available &&
            items[name]?["versions"] is JsonArray versions && versions.Any(value =>
                TelefonProtocolContract.TryInteger(value, out var number) && number == Version)));
}
