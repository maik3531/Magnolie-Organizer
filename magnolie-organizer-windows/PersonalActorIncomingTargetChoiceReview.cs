using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Native explicit-choice draft only. NOT incoming admission, a save capability,
// mutation or ACK permission. Original frames and fresh observations must come
// from protected native callbacks under source/book guards; no route enables it.
internal sealed class PersonalActorIncomingTargetChoiceReview
{
    private readonly string runId, authority;
    private readonly JsonObject before;
    private readonly NativeBookSaveState saved;
    private readonly Func<IReadOnlyList<JsonObject>> currentFrames;
    private readonly Func<IReadOnlyList<JsonObject>, IReadOnlyList<JsonObject>> currentObservations;
    private readonly Func<string?> currentAuthority;
    private readonly Func<JsonObject?> currentScope;
    private readonly Func<NativeBookSaveState?> currentSaved;
    private readonly JsonObject[] targets;
    private readonly Dictionary<string, string> frameHashes;
    private static string Text(JsonObject value, string key) => value[key]!.GetValue<string>();
    private static bool Hex(string? value) => value is { Length: 64 } && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Hash(JsonNode value) => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(value))).ToLowerInvariant();
    private static JsonArray Array(IEnumerable<JsonObject> values) => new(values.Select(value => (JsonNode)value.DeepClone()).ToArray());
    private static JsonObject Saved(NativeBookSaveState value) => new() { ["book_source"] = value.BookSource, ["sequence"] = value.Sequence, ["sha256"] = value.Sha256 };
    private static bool Boolean(JsonNode? value, bool expected) => value is JsonValue primitive && primitive.TryGetValue<bool>(out var actual) && actual == expected;
    private static bool Keys(JsonObject value, params string[] keys) => new HashSet<string>(value.Select(pair => pair.Key), StringComparer.Ordinal).SetEquals(keys);

    internal PersonalActorIncomingTargetChoiceReview(string runId, Func<IReadOnlyList<JsonObject>> currentFrames,
        Func<IReadOnlyList<JsonObject>, IReadOnlyList<JsonObject>> currentObservations, Func<string?> currentAuthority,
        Func<JsonObject?> currentScope, Func<NativeBookSaveState?> currentSaved)
    {
        PersonalSyncActorContract.Start(runId); this.runId = runId;
        ArgumentNullException.ThrowIfNull(currentFrames); ArgumentNullException.ThrowIfNull(currentObservations);
        ArgumentNullException.ThrowIfNull(currentAuthority); ArgumentNullException.ThrowIfNull(currentScope); ArgumentNullException.ThrowIfNull(currentSaved);
        this.currentFrames = currentFrames; this.currentObservations = currentObservations;
        this.currentAuthority = currentAuthority; this.currentScope = currentScope; this.currentSaved = currentSaved;
        authority = currentAuthority() ?? throw new InvalidOperationException("actor_target_review_source_changed");
        if (!Hex(authority)) throw new InvalidOperationException("actor_target_review_source_changed");
        before = (currentScope() ?? throw new InvalidOperationException("actor_target_review_scope_changed")).DeepClone().AsObject();
        PhoneContentScope.Validate(before);
        saved = CheckedSaved();
        (targets, frameHashes) = OriginalFrames();
        Current();
    }

    private NativeBookSaveState CheckedSaved()
    {
        var value = currentSaved();
        if (value is null || !Hex(value.BookSource) || !Hex(value.Sha256) || value.Sequence is < 1 or > 9_007_199_254_740_991)
            throw new InvalidOperationException("actor_target_review_book_changed");
        return value;
    }
    private void Current()
    {
        if (currentAuthority() != authority) throw new InvalidOperationException("actor_target_review_source_changed");
        if (!JsonNode.DeepEquals(currentScope(), before)) throw new InvalidOperationException("actor_target_review_scope_changed");
        if (CheckedSaved() != saved) throw new InvalidOperationException("actor_target_review_book_changed");
        var original = OriginalFrames();
        if (!JsonNode.DeepEquals(Array(original.Targets), Array(targets)) || original.Hashes.Count != frameHashes.Count ||
            original.Hashes.Any(value => frameHashes.GetValueOrDefault(value.Key) != value.Value))
            throw new InvalidOperationException("actor_target_review_frame_changed");
    }

    private (JsonObject[] Targets, Dictionary<string, string> Hashes) OriginalFrames()
    {
        var frames = currentFrames();
        if (frames.Count is < 1 or > 256) throw new InvalidDataException("invalid_actor_target_review_frames");
        var hashes = new Dictionary<string, string>(StringComparer.Ordinal); var sequences = new Dictionary<int, bool>(); string? batch = null;
        var result = new List<JsonObject>(); var ids = new HashSet<string>(StringComparer.Ordinal); var identities = new HashSet<string>(StringComparer.Ordinal);
        foreach (var wire in frames)
        {
            if (Text(wire, "kind") != PersonalSyncActorContract.DataKind) throw new InvalidDataException("invalid_actor_target_review_frame");
            var frameId = Text(wire, "message_id"); PersonalSyncActorContract.Start(frameId);
            var (kind, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
            if (kind != "personal_sync.deletion_proposals" || Text(body, "run_id") != runId) throw new InvalidDataException("invalid_actor_target_review_frame");
            var hash = Hash(wire);
            if (hashes.TryGetValue(frameId, out var old)) { if (old != hash) throw new InvalidDataException("actor_target_review_frame_changed"); continue; }
            var sequence = body["sequence"]!.GetValue<int>();
            if (sequences.ContainsKey(sequence) || batch is not null && batch != Text(body, "proposal_batch_id")) throw new InvalidDataException("invalid_actor_target_review_group");
            hashes.Add(frameId, hash); sequences.Add(sequence, body["last"]!.GetValue<bool>()); batch = Text(body, "proposal_batch_id");
            foreach (var proposal in body["proposals"]!.AsArray().OfType<JsonObject>())
            {
                var target = new JsonObject();
                foreach (var key in new[] { "proposal_id", "kind", "id", "parent_id", "prior_hash", "clock" }) target[key] = proposal[key]!.DeepClone();
                var targetKind = Text(target, "kind"); var parent = Text(target, "parent_id"); var id = Text(target, "id");
                if (targetKind is not ("note" or "task" or "attachment") || !ids.Add(Text(target, "proposal_id")) || !identities.Add(new JsonArray(targetKind, parent, id).ToJsonString()))
                    throw new InvalidDataException("ambiguous_actor_target_review_target");
                var member = targetKind == "attachment" ? parent : id;
                if (before["members"]![targetKind == "task" ? "tasks" : "notes"]!.AsArray().Any(value => value!.GetValue<string>() == member))
                    throw new InvalidOperationException("actor_target_review_content_target");
                result.Add(target);
            }
        }
        if (result.Count is < 1 or > 256 || !sequences.Keys.Order().SequenceEqual(Enumerable.Range(0, sequences.Count)) || sequences.Any(value => value.Value != (value.Key == sequences.Count - 1)))
            throw new InvalidDataException("invalid_actor_target_review_group");
        return (result.OrderBy(value => Text(value, "proposal_id"), StringComparer.Ordinal).ToArray(), hashes);
    }

    internal JsonObject Review()
    {
        Current();
        var observations = currentObservations(targets.Select(value => value.DeepClone().AsObject()).ToArray());
        if (observations.Count != targets.Length) throw new InvalidDataException("invalid_actor_target_review_observations");
        var expected = targets.ToDictionary(value => Text(value, "proposal_id"), StringComparer.Ordinal);
        var checkedValues = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var observation in observations)
        {
            if (!Keys(observation, "target", "local_state", "local_hash", "local_clock", "native_saved_book", "metadata_matches", "requires_conflict_choice"))
                throw new InvalidDataException("invalid_actor_target_review_observation");
            var target = observation["target"]!.AsObject(); var id = Text(target, "proposal_id");
            if (!expected.TryGetValue(id, out var original) || !JsonNode.DeepEquals(target, original) || checkedValues.ContainsKey(id) ||
                Text(observation, "local_state") is not ("live" or "deleted") || !Boolean(observation["requires_conflict_choice"], true) || !Hex(Text(observation, "local_hash")) ||
                !JsonNode.DeepEquals(observation["native_saved_book"], Saved(saved))) throw new InvalidDataException("invalid_actor_target_review_observation");
            var clock = PersonalSyncContract.NormalizeClock(observation["local_clock"]);
            var matches = Text(observation, "local_hash") == Text(target, "prior_hash") && JsonNode.DeepEquals(clock, target["clock"]);
            if (!Boolean(observation["metadata_matches"], matches)) throw new InvalidDataException("invalid_actor_target_review_metadata");
            checkedValues.Add(id, observation.DeepClone().AsObject());
        }
        var binding = new JsonObject { ["run_id"] = runId, ["source"] = authority, ["saved_book"] = Saved(saved), ["content_scope"] = before.DeepClone(),
            ["frame_hashes"] = new JsonArray(frameHashes.OrderBy(value => value.Key, StringComparer.Ordinal).Select(value => (JsonNode)new JsonArray(value.Key, value.Value)).ToArray()),
            ["targets"] = Array(targets), ["observations"] = Array(targets.Select(value => checkedValues[Text(value, "proposal_id")])) };
        Current();
        return new JsonObject { ["revision"] = Hash(binding), ["targets"] = binding["targets"]!.DeepClone(), ["observations"] = binding["observations"]!.DeepClone(),
            ["content_scope"] = before.DeepClone(), ["action_authorized"] = false };
    }

    internal JsonObject DraftChoices(string expectedRevision, IReadOnlyList<JsonObject> choices)
    {
        var review = Review();
        if (Text(review, "revision") != expectedRevision) throw new InvalidOperationException("actor_target_review_revision_changed");
        if (choices.Count != targets.Length) throw new InvalidDataException("actor_target_review_explicit_choices_required");
        var expected = targets.ToDictionary(value => Text(value, "proposal_id"), StringComparer.Ordinal); var seen = new HashSet<string>(StringComparer.Ordinal); var decisions = new List<JsonObject>();
        foreach (var choice in choices)
        {
            if (!Keys(choice, "proposal_id", "decision", "expected_clock", "confirm_conflict") || !Boolean(choice["confirm_conflict"], true) ||
                !expected.TryGetValue(Text(choice, "proposal_id"), out var target) || !seen.Add(Text(choice, "proposal_id")) || !JsonNode.DeepEquals(choice["expected_clock"], target["clock"]))
                throw new InvalidDataException("actor_target_review_explicit_choices_required");
            var decision = new JsonObject(); foreach (var key in new[] { "proposal_id", "decision", "expected_clock" }) decision[key] = choice[key]!.DeepClone();
            PersonalSyncContract.ValidateBody("personal_sync.deletion_decision", new JsonObject { ["format"] = 1, ["run_id"] = runId,
                ["decision_id"] = runId, ["decisions"] = new JsonArray(decision.DeepClone()) });
            decisions.Add(decision);
        }
        var deletedParents = decisions.Where(value => Text(value, "decision") == "delete" && Text(expected[Text(value, "proposal_id")], "kind") == "note")
            .Select(value => Text(expected[Text(value, "proposal_id")], "id")).ToHashSet(StringComparer.Ordinal);
        if (decisions.Any(value => Text(value, "decision") == "restore" && Text(expected[Text(value, "proposal_id")], "kind") == "attachment" && deletedParents.Contains(Text(expected[Text(value, "proposal_id")], "parent_id"))))
            throw new InvalidDataException("actor_target_review_parent_unavailable");
        Current();
        var result = new JsonObject { ["review_revision"] = expectedRevision, ["decisions"] = Array(decisions.OrderBy(value => Text(value, "proposal_id"), StringComparer.Ordinal)),
            ["conflicts_explicitly_confirmed"] = true, ["content_scope"] = before.DeepClone(), ["action_authorized"] = false };
        result["choice_revision"] = Hash(result); return result;
    }
}
