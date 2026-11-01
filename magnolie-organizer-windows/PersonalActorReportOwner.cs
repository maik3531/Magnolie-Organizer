using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Metadata-only handoff BEFORE ordinary report dispatch. No book adoption or
// deletion ACK success; native ownership/epoch/TTLs remain registry gates.
internal sealed class PersonalActorReportOwner
{
    private static readonly Regex Hex = new("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
    private readonly string runId, authority;
    private readonly JsonArray targets;
    private readonly JsonObject before, report;
    private readonly NativeBookSaveState dataSavedBook;
    private readonly Func<string?> currentAuthority;
    private readonly Func<JsonArray> persistedControls;
    private readonly Dictionary<string, JsonObject> expected = new(StringComparer.Ordinal);
    private readonly HashSet<string> producerIds = new(StringComparer.Ordinal);
    private PersonalActorPostDataReview? review;
    internal Func<string, JsonObject?, bool?> Validator { get; }
    internal JsonArray NativeTargets => targets.DeepClone().AsArray();
    internal NativeBookSaveState DataSavedBook => dataSavedBook;
    internal JsonObject OriginalScope => before.DeepClone().AsObject();
    internal PersonalActorPostDataReview? ActiveReview => review;

    internal PersonalActorReportOwner(string runId, JsonArray nativeTargets, JsonObject beforeScope, JsonObject reportFrame,
        NativeBookSaveState dataSavedBook, Func<string?> currentAuthority, Func<JsonArray> persistedControls,
        IReadOnlyList<JsonObject>? producerFrames = null)
    {
        PersonalSyncActorContract.Start(runId); this.runId = runId;
        this.currentAuthority = currentAuthority; this.persistedControls = persistedControls;
        targets = nativeTargets.DeepClone().AsArray(); before = beforeScope.DeepClone().AsObject();
        if (targets.Count is < 1 or > 256) throw new InvalidDataException("invalid_actor_review_targets");
        var dummy = new JsonArray();
        foreach (var target in targets.OfType<JsonObject>())
        {
            expected.Add(Text(target, "proposal_id"), target);
            dummy.Add(new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = target["clock"]!.DeepClone() });
        }
        PersonalSyncActorContract.CompletionMembers(runId, before, targets, dummy);
        report = reportFrame.DeepClone().AsObject();
        if (Text(report, "kind") != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(Text(report, "message_id")))
            throw new InvalidDataException("actor_ordinary_report_required");
        var (kind, body) = PersonalSyncActorContract.Unwrap(report["body"]!.AsObject());
        if (kind != "personal_sync.report" || Text(body, "run_id") != runId || Text(body, "state") != "complete" || Text(body, "error") != "none")
            throw new InvalidDataException("actor_ordinary_report_required");
        if (dataSavedBook.Sequence <= 0 || !Hex.IsMatch(dataSavedBook.BookSource) || !Hex.IsMatch(dataSavedBook.Sha256))
            throw new InvalidOperationException("native_book_not_saved");
        this.dataSavedBook = dataSavedBook;
        if (producerFrames?.Count is < 1 or > 8) throw new InvalidDataException("invalid_actor_producer_frames");
        var witnessed = new HashSet<string>(StringComparer.Ordinal);
        foreach (var wire in producerFrames ?? [])
        {
            if (Text(wire, "kind") != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(Text(wire, "message_id")) || !producerIds.Add(Text(wire, "message_id")))
                throw new InvalidDataException("actor_producer_frame_changed");
            var semantic = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
            if (semantic.Kind != "personal_sync.deletion_proposals" || Text(semantic.Body, "run_id") != runId) throw new InvalidDataException("actor_producer_frame_changed");
            foreach (var value in semantic.Body["proposals"]!.AsArray().OfType<JsonObject>())
            {
                var target = new JsonObject();
                foreach (var key in new[] { "proposal_id", "kind", "id", "parent_id", "prior_hash", "clock" }) target[key] = value[key]!.DeepClone();
                var id = Text(value, "proposal_id");
                if (!expected.TryGetValue(id, out var native) || !JsonNode.DeepEquals(native, target) || !witnessed.Add(id)) throw new InvalidDataException("actor_producer_frame_changed");
            }
        }
        if (producerFrames is not null && !witnessed.SetEquals(expected.Keys)) throw new InvalidDataException("actor_producer_frames_incomplete");
        authority = currentAuthority() ?? throw new InvalidOperationException("actor_report_owner_not_ready");
        if (!Hex.IsMatch(authority)) throw new InvalidOperationException("actor_report_owner_not_ready");
        Validator = Validate;
    }
    private static string Text(JsonObject value, string key) => value[key]?.GetValue<string>() ?? "";
    private string Control(JsonObject wire)
    {
        if (Text(wire, "kind") == PersonalSyncActorContract.AckKind)
        {
            var body = wire["body"]!.AsObject(); PersonalSyncActorContract.ValidateAck(body);
            var id = Text(body, "message_id");
            if (Text(body, "run_id") != runId || id != Text(report, "message_id") && !producerIds.Contains(id)) throw new InvalidDataException("unexpected_actor_report_control");
            return id == Text(report, "message_id") ? "report_ack" : "producer_ack";
        }
        if (Text(wire, "kind") != PersonalSyncActorContract.DataKind) throw new InvalidDataException("unexpected_actor_report_control");
        var semantic = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
        if (semantic.Kind != "personal_sync.deletion_decision" || Text(semantic.Body, "run_id") != runId) throw new InvalidDataException("unexpected_actor_report_control");
        foreach (var decision in semantic.Body["decisions"]!.AsArray().OfType<JsonObject>())
            if (!expected.TryGetValue(Text(decision, "proposal_id"), out var target) || !JsonNode.DeepEquals(target["clock"], decision["expected_clock"]))
                throw new InvalidDataException("actor_review_decision_changed");
        return "decision";
    }
    private bool? Validate(string operation, JsonObject? wire)
    {
        if (operation is not ("begin" or "put" or "read" or "maintain" or "handoff" or "send_report")) throw new InvalidDataException("actor_report_owner_metadata_only");
        var current = currentAuthority(); if (current is null) return null; if (current != authority) return false;
        if (operation == "send_report")
        { if (!JsonNode.DeepEquals(report, wire)) throw new InvalidDataException("actor_ordinary_report_changed"); return true; }
        if (wire is not null)
        {
            if (operation != "put") throw new InvalidDataException("unexpected_actor_report_control");
            if (Control(wire) is "report_ack" or "producer_ack") return true;
        }
        if (review is not null) return review.Validator(operation, wire);
        return operation == "handoff" ? null : true;
    }
    internal PersonalActorPostDataReview BeginReview(Func<JsonObject?> currentScope, Func<NativeBookSaveState?> currentSavedBook)
    {
        if (Validate("read", null) != true) throw new InvalidOperationException("actor_report_owner_not_ready");
        var controls = persistedControls();
        if (controls.Any(value => value is not JsonObject)) throw new InvalidDataException("invalid_actor_report_controls");
        var ack = controls.OfType<JsonObject>().FirstOrDefault(wire => Control(wire) == "report_ack" && Text(wire["body"]!.AsObject(), "status") is ("accepted" or "duplicate"));
        if (ack is null) throw new InvalidOperationException("actor_data_report_ack_required");
        if (review is not null) return review;
        if (currentSavedBook() != dataSavedBook) throw new InvalidOperationException("actor_ordinary_saved_book_changed");
        var created = new PersonalActorPostDataReview(runId, targets, before, Text(report, "message_id"), ack, currentAuthority, currentScope, currentSavedBook,
            () => new JsonArray(persistedControls().OfType<JsonObject>().Where(wire => Control(wire) == "decision").Select(wire => (JsonNode)wire.DeepClone()).ToArray()));
        if (currentAuthority() != authority) throw new InvalidOperationException("actor_report_owner_changed");
        if (currentSavedBook() != dataSavedBook) throw new InvalidOperationException("actor_ordinary_saved_book_changed");
        review = created; return created;
    }
}
