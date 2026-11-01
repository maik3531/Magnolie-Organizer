using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Native-only post-data review and separate SaveACK claim. No document writes,
// outgoing ACKs, target authority or registry ownership are created here.
internal sealed class PersonalActorPostDataReview
{
    private static readonly Regex Hex = new("\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);
    private readonly string runId, authority;
    private readonly JsonArray targets;
    private readonly JsonArray fixedTargets, fixedDecisions;
    private readonly Dictionary<string, JsonObject> fixedFrames;
    private readonly JsonObject before, reportAck;
    private readonly NativeBookSaveState beforeSaved;
    private readonly Func<string?> currentAuthority;
    private readonly Func<JsonObject?> currentScope;
    private readonly Func<NativeBookSaveState?> currentSavedBook;
    private readonly Func<JsonArray> persistedControls;
    private readonly Dictionary<string, JsonObject> expected = new(StringComparer.Ordinal);
    private JsonObject? claim, savedScope, savedFrames;
    private NativeBookSaveState? saved;
    internal Func<string, JsonObject?, bool?> Validator { get; }
    internal NativeBookSaveState? SavedBook => saved;

    internal PersonalActorPostDataReview(string runId, JsonArray nativeTargets, JsonObject beforeScope, string reportId,
        JsonObject dataReportAck, Func<string?> currentAuthority, Func<JsonObject?> currentScope,
        Func<NativeBookSaveState?> currentSavedBook, Func<JsonArray> persistedControls,
        JsonArray? nativeFixedTargets = null, IReadOnlyList<JsonObject>? fixedDecisionFrames = null)
    {
        PersonalSyncActorContract.Start(runId); PersonalSyncActorContract.Start(reportId);
        this.runId = runId; targets = nativeTargets.DeepClone().AsArray(); before = beforeScope.DeepClone().AsObject();
        this.currentAuthority = currentAuthority; this.currentScope = currentScope;
        this.currentSavedBook = currentSavedBook; this.persistedControls = persistedControls;
        if (targets.Count is < 1 or > 256) throw new InvalidDataException("invalid_actor_review_targets");
        var dummy = new JsonArray();
        foreach (var target in targets.OfType<JsonObject>())
        {
            expected.Add(Text(target, "proposal_id"), target);
            dummy.Add(new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = target["clock"]!.DeepClone() });
        }
        PersonalSyncActorContract.CompletionMembers(runId, before, targets, dummy);
        // Native fixed choices were already adopted by the ordinary SaveACK.
        // Bind their original targets/frames for scope and receipt union, but
        // never include them in the list of late document mutations.
        (fixedTargets, fixedFrames, fixedDecisions) = CheckedFixedEvidence(runId, before, targets, nativeFixedTargets, fixedDecisionFrames);
        reportAck = dataReportAck.DeepClone().AsObject();
        if (Text(reportAck, "kind") != PersonalSyncActorContract.AckKind) throw new InvalidOperationException("actor_data_report_ack_required");
        var body = reportAck["body"]!.AsObject(); PersonalSyncActorContract.ValidateAck(body);
        if (Text(body, "run_id") != runId || Text(body, "message_id") != reportId || Text(body, "status") is not ("accepted" or "duplicate"))
            throw new InvalidOperationException("actor_data_report_ack_required");
        authority = currentAuthority() ?? throw new InvalidOperationException("actor_decision_review_not_ready");
        if (!Hex.IsMatch(authority)) throw new InvalidOperationException("actor_decision_review_not_ready");
        beforeSaved = CheckedSaved(currentSavedBook()); Validator = Validate;
    }

    internal static (JsonArray Targets, Dictionary<string, JsonObject> Frames, JsonArray Decisions) CheckedFixedEvidence(
        string runId, JsonObject beforeScope, JsonArray lateTargets, JsonArray? nativeFixedTargets, IReadOnlyList<JsonObject>? fixedDecisionFrames)
    {
        // Native target/frame evidence only. Never synthesize a report ACK just
        // to reuse a constructor before the ordinary report has been received.
        var targets = nativeFixedTargets?.DeepClone().AsArray() ?? [];
        if (lateTargets.Count + targets.Count > 256 || fixedDecisionFrames?.Count > 256)
            throw new InvalidDataException("invalid_actor_fixed_review_targets");
        var frames = new Dictionary<string, JsonObject>(StringComparer.Ordinal); var decisions = new JsonArray();
        foreach (var wire in fixedDecisionFrames ?? [])
        {
            if (Text(wire, "kind") != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(Text(wire, "message_id")))
                throw new InvalidDataException("invalid_actor_fixed_review_frame");
            var semantic = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
            if (semantic.Kind != "personal_sync.deletion_decision" || Text(semantic.Body, "run_id") != runId || !frames.TryAdd(Text(wire, "message_id"), wire.DeepClone().AsObject()))
                throw new InvalidDataException("invalid_actor_fixed_review_frame");
            foreach (var decision in semantic.Body["decisions"]!.AsArray()) decisions.Add(decision!.DeepClone());
        }
        PersonalSyncActorContract.CompletionMembers(runId, beforeScope, targets, decisions);
        var union = Union(lateTargets, targets);
        var dummy = new JsonArray(union.OfType<JsonObject>().Select(target => (JsonNode)new JsonObject {
            ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = target["clock"]!.DeepClone() }).ToArray());
        PersonalSyncActorContract.CompletionMembers(runId, beforeScope, union, dummy);
        return (targets, frames, decisions);
    }

    private static string Text(JsonObject value, string key) => value[key]?.GetValue<string>() ?? "";
    private static JsonArray Union(JsonArray first, JsonArray second) => new(first.Concat(second).Select(value => value!.DeepClone()).ToArray());
    private static string Hash(JsonNode value) => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(value))).ToLowerInvariant();
    private static NativeBookSaveState CheckedSaved(NativeBookSaveState? value) =>
        value is not null && value.Sequence > 0 && Hex.IsMatch(value.BookSource) && Hex.IsMatch(value.Sha256)
            ? value : throw new InvalidOperationException("native_book_not_saved");
    private bool? Authority() { var actual = currentAuthority(); return actual is null ? null : actual == authority; }
    private JsonObject Decision(JsonObject wire)
    {
        if (Text(wire, "kind") != PersonalSyncActorContract.DataKind || !TelefonProtocolContract.IsUuidV4(Text(wire, "message_id")))
            throw new InvalidDataException("unexpected_actor_review_control");
        var (kind, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
        if (kind != "personal_sync.deletion_decision" || Text(body, "run_id") != runId) throw new InvalidDataException("unexpected_actor_review_control");
        foreach (var decision in body["decisions"]!.AsArray().OfType<JsonObject>())
            if (!expected.TryGetValue(Text(decision, "proposal_id"), out var target) || !JsonNode.DeepEquals(target["clock"], decision["expected_clock"]))
                throw new InvalidDataException("actor_review_decision_changed");
        return body;
    }
    private bool MatchesClaim(NativeBookSaveState value) => claim is not null && value.BookSource == Text(claim, "book_source") &&
        value.Sequence > claim["before_sequence"]!.GetValue<long>() && value.Sha256 == Text(claim, "after_sha256");

    private bool? Validate(string operation, JsonObject? wire)
    {
        if (operation is not ("begin" or "put" or "read" or "maintain" or "handoff")) throw new InvalidDataException("actor_decision_review_metadata_only");
        if (wire is not null)
        {
            if (operation != "put") throw new InvalidDataException("unexpected_actor_review_control");
            Decision(wire);
            if (savedFrames is not null && Text(savedFrames, Text(wire, "message_id")) != Hash(wire)) throw new InvalidDataException("actor_review_frame_changed_after_save");
        }
        var authorityState = Authority(); if (authorityState != true) return authorityState;
        var observed = currentSavedBook(); if (observed is null) return null;
        if (operation == "handoff")
        {
            if (saved is null) return null;
            if (observed != saved) return false;
            var actual = currentScope(); if (actual is null) return null;
            PhoneContentScope.Validate(actual);
            // No recursive protected-store reads inside a registry transaction.
            return JsonNode.DeepEquals(actual, savedScope);
        }
        if (observed == (saved ?? beforeSaved)) return true;
        if (saved is null && MatchesClaim(observed)) return operation == "read" ? true : null;
        return false;
    }

    internal JsonObject Review(bool requireSaved = true)
    {
        if (requireSaved && Validate("read", null) != true) throw new InvalidOperationException("actor_decision_review_not_ready");
        var frames = persistedControls(); if (frames.Count > 256 || frames.Any(value => value is not JsonObject)) throw new InvalidDataException("invalid_actor_review_controls");
        var decisions = new Dictionary<string, JsonObject>(StringComparer.Ordinal); var wires = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var wire in frames.OfType<JsonObject>())
        {
            var body = Decision(wire); var id = Text(wire, "message_id");
            if (fixedFrames.ContainsKey(id)) throw new InvalidDataException("actor_review_frame_direction_collision");
            if (wires.TryGetValue(id, out var previous))
            { if (!JsonNode.DeepEquals(previous, wire)) throw new InvalidDataException("actor_review_frame_changed"); continue; }
            wires.Add(id, wire.DeepClone().AsObject());
            foreach (var decision in body["decisions"]!.AsArray().OfType<JsonObject>())
                if (!decisions.TryAdd(Text(decision, "proposal_id"), decision.DeepClone().AsObject())) throw new InvalidDataException("actor_review_decision_duplicate");
        }
        if (!expected.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(decisions.Keys)) throw new InvalidOperationException("actor_producer_decisions_incomplete");
        var actual = currentScope() ?? throw new InvalidOperationException("actor_decision_review_not_ready");
        var choices = new JsonArray(decisions.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => (JsonNode)pair.Value).ToArray());
        PersonalSyncActorContract.RequireCompletionScope(runId, before, Union(targets, fixedTargets), Union(choices, fixedDecisions), actual);
        var hashes = new JsonObject(); foreach (var pair in wires.OrderBy(pair => pair.Key, StringComparer.Ordinal)) hashes[pair.Key] = Hash(pair.Value);
        var binding = new JsonObject { ["run_id"] = runId, ["targets"] = targets.DeepClone(), ["decisions"] = choices.DeepClone(), ["scope"] = actual.DeepClone(),
            ["report_ack"] = reportAck.DeepClone(), ["saved_before"] = new JsonObject { ["book_source"] = beforeSaved.BookSource, ["sequence"] = beforeSaved.Sequence, ["sha256"] = beforeSaved.Sha256 }, ["frames"] = hashes.DeepClone() };
        var fixedHashes = new JsonObject();
        if (fixedTargets.Count > 0)
        {
            foreach (var pair in fixedFrames.OrderBy(pair => pair.Key, StringComparer.Ordinal)) fixedHashes[pair.Key] = Hash(pair.Value);
            binding["fixed_targets"] = fixedTargets.DeepClone(); binding["fixed_decisions"] = fixedDecisions.DeepClone(); binding["fixed_frames"] = fixedHashes.DeepClone();
        }
        if (Authority() != true || requireSaved && Validate("read", null) != true) throw new InvalidOperationException("actor_decision_review_not_ready");
        var result = new JsonObject { ["revision"] = Hash(binding), ["decisions"] = choices, ["scope"] = actual.DeepClone(), ["frame_hashes"] = hashes, ["book_persisted"] = saved is not null };
        if (fixedTargets.Count > 0)
        { result["fixed_targets"] = fixedTargets.DeepClone(); result["fixed_decisions"] = fixedDecisions.DeepClone(); result["fixed_frame_hashes"] = fixedHashes; }
        return result;
    }

    internal JsonObject PrepareSave(string expectedRevision, string afterSha256)
    {
        if (!Hex.IsMatch(afterSha256)) throw new InvalidDataException("invalid_actor_review_save_hash");
        var review = Review(); if (Text(review, "revision") != expectedRevision) throw new InvalidOperationException("actor_review_revision_changed");
        claim ??= new JsonObject { ["claim_token"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), ["revision"] = expectedRevision,
            ["after_sha256"] = afterSha256, ["book_source"] = beforeSaved.BookSource, ["before_sequence"] = beforeSaved.Sequence };
        if (Text(claim, "revision") != expectedRevision || Text(claim, "after_sha256") != afterSha256) throw new InvalidOperationException("actor_review_save_claim_changed");
        var result = claim.DeepClone().AsObject(); result["book_persisted"] = saved is not null; return result;
    }

    internal JsonObject ConfirmSaved(string claimToken)
    {
        if (claim is null || !Hex.IsMatch(claimToken) || !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(claimToken), Convert.FromHexString(Text(claim, "claim_token"))))
            throw new InvalidOperationException("actor_review_save_claim_unavailable");
        if (Authority() != true) throw new InvalidOperationException("actor_decision_review_not_ready");
        var review = Review(requireSaved: false);
        if (Text(review, "revision") != Text(claim, "revision")) throw new InvalidOperationException("actor_review_revision_changed");
        var observed = CheckedSaved(currentSavedBook());
        if (!MatchesClaim(observed) || saved is not null && saved != observed) throw new InvalidOperationException("actor_review_save_proof_missing");
        if (Authority() != true || currentSavedBook() != observed) throw new InvalidOperationException("actor_review_save_outcome_unknown");
        saved = observed; savedScope = review["scope"]!.DeepClone().AsObject(); savedFrames = review["frame_hashes"]!.DeepClone().AsObject();
        return new JsonObject { ["book_persisted"] = true, ["save_sequence"] = observed.Sequence, ["book_sha256"] = observed.Sha256, ["phone_persisted"] = false };
    }
}
