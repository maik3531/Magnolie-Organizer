using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Private native controller observation only. NOT incoming admission, typed
// action permission, content selection, packet/ACK/queue/transport authority.
// Native caller must hold source/writer guards and use operation-live observers.
internal sealed class PersonalActorIncomingLiveTargetObservation
{
    private readonly string peerId, runId, sourceRevision;
    private readonly NativeBookSaveState saved;
    private readonly JsonObject before;
    private readonly Func<bool> currentOwner;
    private readonly Func<string?> currentSource;
    private readonly Func<NativeActorBookSnapshot?> currentSnapshot;
    private readonly Func<JsonObject?> currentScope;
    private readonly Dictionary<string, JsonObject> observed = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> identities = new(StringComparer.Ordinal);
    private static string Text(JsonObject value, string key, string fallback = "") => value[key]?.GetValue<string>() ?? fallback;
    private static bool Hex(string value) => value.Length == 64 && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');

    internal PersonalActorIncomingLiveTargetObservation(string peerId, string runId, Func<bool> currentOwner, Func<string?> currentSource,
        Func<NativeActorBookSnapshot?> currentSnapshot, Func<JsonObject?> currentScope)
    {
        PersonalSyncActorContract.Start(peerId); PersonalSyncActorContract.Start(runId);
        ArgumentNullException.ThrowIfNull(currentOwner); ArgumentNullException.ThrowIfNull(currentSource);
        ArgumentNullException.ThrowIfNull(currentSnapshot); ArgumentNullException.ThrowIfNull(currentScope);
        this.peerId = peerId; this.runId = runId; this.currentOwner = currentOwner; this.currentSource = currentSource;
        this.currentSnapshot = currentSnapshot; this.currentScope = currentScope;
        if (!currentOwner()) throw new InvalidOperationException("actor_target_owner_changed");
        sourceRevision = currentSource() ?? "";
        if (!Hex(sourceRevision)) throw new InvalidOperationException("actor_target_source_changed");
        saved = (currentSnapshot() ?? throw new InvalidOperationException("actor_target_native_book_missing")).SavedBook;
        before = (currentScope() ?? throw new InvalidOperationException("actor_target_scope_changed")).DeepClone().AsObject(); PhoneContentScope.Validate(before);
        CheckCurrent();
    }
    private NativeActorBookSnapshot Snapshot()
    {
        var value = currentSnapshot();
        if (value is null || value.SavedBook != saved) throw new InvalidOperationException("actor_target_book_changed");
        return value;
    }
    private void CheckSource()
    {
        if (!currentOwner()) throw new InvalidOperationException("actor_target_owner_changed");
        if (currentSource() != sourceRevision) throw new InvalidOperationException("actor_target_source_changed");
        if (!JsonNode.DeepEquals(currentScope(), before)) throw new InvalidOperationException("actor_target_scope_changed");
    }
    private void CheckCurrent() { CheckSource(); Snapshot(); CheckSource(); }

    internal JsonObject Observe(string expectedRunId, JsonObject target) => ObserveMany(expectedRunId, [target])[0];

    internal IReadOnlyList<JsonObject> ObserveMany(string expectedRunId, IReadOnlyList<JsonObject> targets)
    {
        CheckCurrent();
        if (expectedRunId != runId) throw new InvalidOperationException("actor_target_proof_changed");
        if (targets.Count is < 1 or > 256) throw new InvalidDataException("actor_target_capacity");
        var book = JsonNode.Parse(Snapshot().Text)!.AsObject();
        var previous = observed.ToArray(); var previousIdentities = identities.ToArray();
        var result = new List<JsonObject>(); var seen = new HashSet<string>(StringComparer.Ordinal);
        try
        {
            foreach (var target in targets)
            {
                var value = ObserveTarget(expectedRunId, target, book);
                if (!seen.Add(Text(value["target"]!.AsObject(), "proposal_id"))) throw new InvalidDataException("actor_target_duplicate_group");
                result.Add(value);
            }
            CheckCurrent();
        }
        catch
        {
            observed.Clear(); foreach (var entry in previous) observed.Add(entry.Key, entry.Value);
            identities.Clear(); foreach (var entry in previousIdentities) identities.Add(entry.Key, entry.Value);
            throw;
        }
        return result;
    }

    private JsonObject ObserveTarget(string expectedRunId, JsonObject target, JsonObject book)
    {
        if (expectedRunId != runId || target.Count != 6 || !new HashSet<string>(target.Select(value => value.Key), StringComparer.Ordinal)
            .SetEquals(["proposal_id", "kind", "id", "parent_id", "prior_hash", "clock"])) throw new InvalidOperationException("actor_target_proof_changed");
        var proposal = target.DeepClone().AsObject(); proposal["deleted_ms"] = 0; proposal["label"] = "";
        PersonalSyncContract.ValidateBody("personal_sync.deletion_proposals", new JsonObject { ["format"] = 1, ["run_id"] = runId,
            ["proposal_batch_id"] = runId, ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(proposal) });
        var kind = Text(target, "kind"); var id = Text(target, "id"); var parent = Text(target, "parent_id"); var proposalId = Text(target, "proposal_id");
        if (kind is not ("note" or "task" or "attachment")) throw new InvalidOperationException("actor_target_kind_not_supported");
        if (before["members"]![kind == "task" ? "tasks" : "notes"]!.AsArray().Any(value => value!.GetValue<string>() == (kind == "attachment" ? parent : id)))
            throw new InvalidOperationException("actor_target_already_in_content_scope");
        var identity = kind + "\0" + parent + "\0" + id;
        if (observed.TryGetValue(proposalId, out var old) && !JsonNode.DeepEquals(old["target"], target) ||
            identities.TryGetValue(identity, out var prior) && prior != proposalId) throw new InvalidOperationException("actor_target_proof_changed");
        if (old is null && observed.Count >= 256) throw new InvalidDataException("actor_target_capacity");
        var state = book["personalSync"]?.AsObject() ?? new JsonObject();
        var key = kind + "\0" + (kind == "attachment" ? parent + "\0" : "") + id;
        var meta = state["entities"]?[key] as JsonObject;
        if (Text(state, "peer_device_id") != peerId || meta is null || Text(meta, "peer_device_id") != peerId)
            throw new InvalidOperationException("actor_target_live_native_proof_missing");
        var pending = Text(meta, "state") == "deleted" && Text(meta, "status") == "local_pending";
        var localHash = Text(meta, pending ? "prior_hash" : "hash");
        if (Text(meta, "state") != "live" && !pending || Text(meta, "parent_id") != parent || meta["conflict"]?.GetValue<bool>() == true || !Hex(localHash))
            throw new InvalidOperationException("actor_target_live_native_proof_missing");
        var clock = PersonalSyncContract.NormalizeClock(meta["clock"]!);
        if (pending)
        {
            var local = new JsonObject { ["proposal_id"] = meta["proposal_id"]?.DeepClone(), ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
                ["clock"] = clock.DeepClone(), ["prior_hash"] = localHash, ["deleted_ms"] = meta["deleted_ms"]?.DeepClone(), ["label"] = Text(meta, "label") };
            PersonalSyncContract.ValidateBody("personal_sync.deletion_proposals", new JsonObject { ["format"] = 1, ["run_id"] = runId,
                ["proposal_batch_id"] = runId, ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(local) });
            if (Text(meta, "hash").Length != 0 || Text(meta, "proposal_id") != PersonalSyncContract.DeletionProposalId(peerId, kind, id, parent, clock, localHash))
                throw new InvalidOperationException("actor_target_pending_native_proof_missing");
        }
        bool own;
        if (kind == "task")
        {
            var live = (book["aufgaben"]?.AsArray() ?? []).OfType<JsonObject>().Where(value => Text(value, "id") == id).ToArray();
            own = pending ? live.Length == 0 : live.Length == 1 && !new[] { "vonZweig", "fremdId", "delegiertAn", "herkunft" }.Any(field =>
                live[0][field] is { } node && (node is not JsonValue value || (value.TryGetValue<bool>(out var flag) ? flag : value.TryGetValue<string>(out var text) ? text.Length != 0 : true)));
        }
        else
        {
            var live = (book["notizen"]?.AsArray() ?? []).OfType<JsonObject>().Where(value => PersonalActorOutgoingProducer.NoteWireId(Text(value, "id"), state) == (kind == "attachment" ? parent : id)).ToArray();
            own = kind == "note" && pending ? live.Length == 0 : live.Length == 1 && (Text(live[0], "baumQuelle").Length == 0 || live[0]["persoenlichVerknuepft"]?.GetValue<bool>() == true);
            if (own && kind == "attachment") own = (live[0]["anhaenge"]?.AsArray() ?? []).OfType<JsonObject>().Count(value => PersonalActorOutgoingProducer.AttachmentId(parent, Text(value, "id"), state) == id) == (pending ? 0 : 1);
        }
        if (!own) throw new InvalidOperationException("actor_target_live_native_proof_missing");
        // The local metadata hash/clock are observations, NOT claims that this
        // hash was recomputed from current content. The actual saved book is
        // independently pinned; future typed conflict/save gates remain needed.
        var result = new JsonObject { ["target"] = target.DeepClone(), ["local_state"] = pending ? "deleted" : "live", ["local_hash"] = localHash, ["local_clock"] = clock.DeepClone(),
            ["native_saved_book"] = new JsonObject { ["book_source"] = saved.BookSource, ["sequence"] = saved.Sequence, ["sha256"] = saved.Sha256 },
            ["metadata_matches"] = localHash == Text(target, "prior_hash") && JsonNode.DeepEquals(clock, target["clock"]),
            ["requires_conflict_choice"] = true };
        observed[proposalId] = result; identities[identity] = proposalId;
        return result.DeepClone().AsObject();
    }
}
