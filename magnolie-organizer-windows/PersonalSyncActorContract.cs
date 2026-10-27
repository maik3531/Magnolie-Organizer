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
    internal const string CancelKind = "personal_sync.actor_cancel";
    private const string StoragePeerPrefix = "@mcp-actor-";
    private static readonly HashSet<string> DataKinds = ["personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result",
        "personal_sync.deletion_proposals", "personal_sync.deletion_decision", PhoneContentScope.DataKind];
    private static string Text(JsonObject value, string field) => value[field] is JsonValue scalar && scalar.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("Invalid actor text field.");

    internal static bool IsReservedMessage(JsonObject value) =>
        value["type"] is JsonValue type && type.TryGetValue<string>(out var messageType) && messageType == "message" &&
        value["kind"] is JsonValue kind && kind.TryGetValue<string>(out var name) && IsReservedKind(name);

    internal static bool IsReservedKind(string? name) => name is StartKind or DataKind or AckKind or CancelKind;
    internal static string StoragePeer(string runId) { _ = Start(runId); return StoragePeerPrefix + runId; }
    internal static bool IsStoragePeer(string? value) => value?.StartsWith(StoragePeerPrefix, StringComparison.Ordinal) == true;

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

    internal static JsonObject ValidateCancel(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "format", "run_id");
        if (TelefonProtocolContract.Integer(body["format"]) != Version || !TelefonProtocolContract.IsUuidV4(Text(body, "run_id")))
            throw new InvalidDataException("Invalid actor cancellation identity.");
        return body;
    }
    internal static JsonObject Cancel(string runId) => ValidateCancel(new JsonObject { ["format"] = Version, ["run_id"] = runId });

    // Private native review binding, not a wire envelope or permission to save.
    internal static JsonObject DeletionReview(string runId, JsonObject? plan, JsonArray nativeIntents)
    {
        _ = Start(runId);
        if (nativeIntents.Count > 256) throw new InvalidDataException("invalid_actor_deletion_review");
        var references = new SortedDictionary<string, JsonObject>(StringComparer.Ordinal);
        var proposals = new SortedDictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var raw in nativeIntents)
        {
            var intent = raw as JsonObject ?? throw new InvalidDataException("invalid_actor_native_intent");
            TelefonProtocolContract.ExactObject(intent, "kind", "message_id", "commit_token", "body");
            var kind = Text(intent, "kind");
            if (kind is not ("personal_sync.deletion_proposals" or "personal_sync.deletion_decision") || intent["body"] is not JsonObject body)
                throw new InvalidDataException("invalid_actor_native_intent");
            PersonalSyncContract.ValidateBody(kind, body);
            if (Text(body, "run_id") != runId) throw new InvalidDataException("actor_deletion_run_changed");
            var id = Text(intent, "message_id"); var token = Text(intent, "commit_token");
            _ = Ack(runId, id);
            if (token.Length == 0 || System.Text.Encoding.UTF8.GetByteCount(token) > 256 || references.ContainsKey(id))
                throw new InvalidDataException("invalid_actor_native_intent");
            references[id] = new JsonObject { ["kind"] = kind, ["message_id"] = id, ["commit_token"] = token };
            if (kind != "personal_sync.deletion_proposals") continue;
            foreach (var proposal in body["proposals"]!.AsArray().OfType<JsonObject>())
            {
                if (Text(proposal, "kind") is not ("note" or "task" or "attachment")) throw new InvalidDataException("actor_deletion_kind_not_supported");
                var proposalId = Text(proposal, "proposal_id");
                if (proposals.TryGetValue(proposalId, out var previous) && !JsonNode.DeepEquals(previous, proposal))
                    throw new InvalidDataException("actor_deletion_proposal_changed");
                proposals[proposalId] = proposal;
            }
        }
        if (plan is null && nativeIntents.Count == 0) return new JsonObject { ["choices"] = new JsonArray(), ["intents"] = new JsonArray() };
        if (plan is null) throw new InvalidDataException("actor_deletion_review_required");
        TelefonProtocolContract.ExactObject(plan, "choices", "intents");
        if (plan["choices"] is not JsonArray choices || choices.Count > 256 || plan["intents"] is not JsonArray reviewed || reviewed.Count != references.Count)
            throw new InvalidDataException("actor_deletion_review_required");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in reviewed)
        {
            var reference = raw as JsonObject ?? throw new InvalidDataException("actor_deletion_intent_changed");
            TelefonProtocolContract.ExactObject(reference, "kind", "message_id", "commit_token"); var id = Text(reference, "message_id");
            if (!seen.Add(id) || !references.TryGetValue(id, out var native) || !JsonNode.DeepEquals(reference, native))
                throw new InvalidDataException("actor_deletion_intent_changed");
        }
        var decisions = new SortedDictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var raw in choices)
        {
            var choice = raw as JsonObject ?? throw new InvalidDataException("actor_deletion_choice_changed");
            TelefonProtocolContract.ExactObject(choice, "proposal_id", "decision", "expected_clock", "allow_conflict");
            var id = Text(choice, "proposal_id");
            if (decisions.ContainsKey(id) || !proposals.TryGetValue(id, out var proposal) || Text(choice, "decision") is not ("delete" or "restore") ||
                choice["allow_conflict"] is not JsonValue flag || !flag.TryGetValue<bool>(out _) || !JsonNode.DeepEquals(choice["expected_clock"], proposal["clock"]))
                throw new InvalidDataException("actor_deletion_choice_changed");
            decisions[id] = choice;
        }
        if (!decisions.Keys.SequenceEqual(proposals.Keys)) throw new InvalidDataException("actor_deletion_choice_missing");
        return new JsonObject { ["choices"] = new JsonArray(decisions.Values.Select(value => value.DeepClone()).ToArray()),
            ["intents"] = new JsonArray(references.Values.Select(value => value.DeepClone()).ToArray()) };
    }

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
