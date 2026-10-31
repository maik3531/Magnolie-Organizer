using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Native-only saved claim/scope correlation. This neither writes a book nor
// sends a packet; callbacks must observe live native state under owner gates.
internal sealed class PersonalActorDecisionCompletion
{
    private static readonly Regex Hex = new("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
    private readonly string runId, authority;
    private readonly JsonObject before;
    private readonly JsonArray targets, decisions;
    private readonly NativeBookSaveState savedBook;
    private readonly Func<string?> currentAuthority;
    private readonly Func<JsonObject?> currentScope;
    private readonly Func<NativeBookSaveState?> currentSavedBook;
    private readonly Func<JsonArray> persistedControls;
    private readonly Dictionary<string, JsonObject> frames = new(StringComparer.Ordinal), received = new(StringComparer.Ordinal);
    internal Func<string, JsonObject?, bool?> Validator { get; }

    internal PersonalActorDecisionCompletion(string runId, JsonArray nativeTargets, IReadOnlyList<JsonObject> queuedDecisions,
        Func<string?> currentAuthority, Func<JsonObject?> currentScope, Func<NativeBookSaveState?> currentSavedBook,
        Func<JsonArray> persistedControls)
    {
        PersonalSyncActorContract.Start(runId);
        this.runId = runId; this.currentAuthority = currentAuthority; this.currentScope = currentScope;
        this.currentSavedBook = currentSavedBook; this.persistedControls = persistedControls;
        before = (currentScope() ?? throw new InvalidOperationException("actor_completion_not_ready")).DeepClone().AsObject();
        PhoneContentScope.Validate(before);
        authority = currentAuthority() ?? throw new InvalidOperationException("actor_completion_not_ready");
        if (!Hex.IsMatch(authority)) throw new InvalidOperationException("actor_completion_not_ready");
        savedBook = CheckedSavedBook(currentSavedBook()); targets = nativeTargets.DeepClone().AsArray(); decisions = [];
        if (queuedDecisions.Count is < 1 or > 256) throw new InvalidDataException("invalid_actor_completion_controls");
        foreach (var queued in queuedDecisions)
        {
            var wire = queued.DeepClone().AsObject();
            if (Text(wire, "kind") != PersonalSyncActorContract.DataKind) throw new InvalidDataException("invalid_actor_completion_controls");
            var id = Text(wire, "message_id");
            if (!TelefonProtocolContract.IsUuidV4(id)) throw new InvalidDataException("invalid_actor_completion_controls");
            var (kind, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
            if (kind != "personal_sync.deletion_decision" || Text(body, "run_id") != runId || !frames.TryAdd(id, wire))
                throw new InvalidDataException("invalid_actor_completion_controls");
            foreach (var decision in body["decisions"]!.AsArray()) decisions.Add(decision!.DeepClone());
        }
        PersonalSyncActorContract.CompletionMembers(runId, before, targets, decisions);
        Validator = Validate; // Stable delegate identity is part of native ownership.
    }

    private static string Text(JsonObject value, string key) => TelefonMessagingContract.String(value, key);
    private static bool Success(JsonObject value) => Text(value, "status") is "accepted" or "duplicate";
    private static NativeBookSaveState CheckedSavedBook(NativeBookSaveState? value) =>
        value is not null && value.Sequence > 0 && Hex.IsMatch(value.BookSource) && Hex.IsMatch(value.Sha256)
            ? value : throw new InvalidOperationException("native_book_not_saved");

    private JsonObject Ack(JsonObject wire)
    {
        if (Text(wire, "kind") != PersonalSyncActorContract.AckKind) throw new InvalidDataException("unexpected_actor_completion_control");
        var body = wire["body"]!.AsObject(); PersonalSyncActorContract.ValidateAck(body);
        var id = Text(body, "message_id");
        if (Text(body, "run_id") != runId || !frames.ContainsKey(id)) throw new InvalidDataException("unexpected_actor_completion_control");
        if (received.TryGetValue(id, out var previous) && Success(previous) && Text(body, "status") == "rejected")
            throw new InvalidDataException("actor_completion_outcome_changed");
        return body;
    }

    private bool? Validate(string operation, JsonObject? wire)
    {
        if (operation is not ("begin" or "put" or "read" or "send" or "finish" or "maintain")) throw new InvalidDataException("unexpected_actor_completion_operation");
        JsonObject? body = null;
        if (operation == "send")
        {
            if (wire is null || !frames.TryGetValue(Text(wire, "message_id"), out var queued) || !JsonNode.DeepEquals(queued, wire))
                throw new InvalidDataException("unexpected_actor_completion_control");
        }
        else if (wire is not null) body = Ack(wire);
        try { if (CheckedSavedBook(currentSavedBook()) != savedBook) return false; }
        catch (InvalidOperationException) { return false; }
        var actualAuthority = currentAuthority(); if (actualAuthority is null) return null;
        if (actualAuthority != authority) return false;
        var actual = currentScope(); if (actual is null) return null;
        try { PhoneContentScope.Validate(actual); } catch (InvalidDataException) { return false; }
        var atBefore = JsonNode.DeepEquals(PhoneContentScope.Reference(actual), PhoneContentScope.Reference(before));
        var atAfter = false;
        try { PersonalSyncActorContract.RequireCompletionScope(runId, before, targets, decisions, actual); atAfter = true; }
        catch (InvalidDataException) { }
        if (!atBefore && !atAfter) return false;
        if (body is not null && Success(body) && !atAfter) return null;
        if (operation == "finish" && (!atAfter || received.Count != frames.Count || received.Values.Any(value => !Success(value)))) return null;
        return true;
    }

    internal void RecordPersisted(JsonObject wire)
    {
        if (Validate("put", wire) != true) throw new InvalidOperationException("actor_completion_not_ready");
        var expected = TelefonCrypto.Canonical(wire);
        if (!persistedControls().OfType<JsonObject>().Any(value => TelefonCrypto.Canonical(value).AsSpan().SequenceEqual(expected)))
            throw new InvalidOperationException("actor_completion_control_not_persisted");
        var body = Ack(wire); received[Text(body, "message_id")] = body.DeepClone().AsObject();
    }

    internal JsonObject Summary() => new() { ["expected"] = frames.Count, ["received"] = received.Count,
        ["saved"] = received.Values.Count(Success), ["rejected"] = received.Values.Count(value => Text(value, "status") == "rejected") };
}
