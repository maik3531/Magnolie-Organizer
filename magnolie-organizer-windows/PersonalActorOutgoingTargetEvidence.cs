using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Private outgoing tombstone evidence only. NOT connected to any controller,
// IPC/capability, data session, queue, ACK or transport. Incoming proofs and
// independent typed-choice/receipt semantics must be integrated separately.
internal sealed class PersonalActorOutgoingTargetEvidence
{
    private readonly Func<bool> currentOwner;
    private readonly Func<string?> currentSource;
    private readonly Func<NativeActorBookSnapshot?> currentSnapshot;
    private readonly Func<JsonObject?> currentScope;
    private readonly string runId, sourceRevision;
    private readonly NativeBookSaveState bookBinding;
    private readonly JsonObject before;
    private readonly Dictionary<string, JsonObject> targets = new(StringComparer.Ordinal);

    internal PersonalActorOutgoingTargetEvidence(string peerId, string runId, Func<bool> currentOwner,
        Func<string?> currentSource, Func<NativeActorBookSnapshot?> currentSnapshot, Func<JsonObject?> currentScope)
    {
        PersonalSyncActorContract.Start(peerId); PersonalSyncActorContract.Start(runId);
        ArgumentNullException.ThrowIfNull(currentOwner); ArgumentNullException.ThrowIfNull(currentSource);
        ArgumentNullException.ThrowIfNull(currentSnapshot); ArgumentNullException.ThrowIfNull(currentScope);
        this.runId = runId; this.currentOwner = currentOwner; this.currentSource = currentSource;
        this.currentSnapshot = currentSnapshot; this.currentScope = currentScope;
        if (!currentOwner()) throw new InvalidOperationException("actor_target_owner_changed");
        sourceRevision = currentSource() ?? "";
        if (sourceRevision.Length != 64 || sourceRevision.Any(value => value is not (>= '0' and <= '9' or >= 'a' and <= 'f')))
            throw new InvalidOperationException("actor_target_source_changed");
        var snapshot = currentSnapshot() ?? throw new InvalidOperationException("actor_target_native_book_missing");
        bookBinding = snapshot.SavedBook;
        before = (currentScope() ?? throw new InvalidOperationException("actor_target_scope_changed")).DeepClone().AsObject(); PhoneContentScope.Validate(before);
        var notes = before["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        var tasks = before["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        var book = JsonNode.Parse(snapshot.Text)!.AsObject();
        foreach (var (key, raw) in book["personalSync"]?["entities"]?.AsObject() ?? new JsonObject())
        {
            if (raw is not JsonObject meta || meta["state"]?.GetValue<string>() != "deleted" || meta["status"]?.GetValue<string>() != "local_pending") continue;
            var parts = key.Split('\0');
            if (parts.Length == 2 && parts[0] is "note" or "task") (parts[0] == "note" ? notes : tasks).Add(parts[1]);
            else if (parts.Length == 3 && parts[0] == "attachment") notes.Add(parts[1]);
        }
        // Validation-only index: NEVER registered as accepted data membership.
        // Existing native producer validates canonical absence/parent/proposal
        // identity independently. No content manifest is exposed by this type.
        var index = PhoneContentScope.Create(notes, tasks);
        var bodies = PersonalActorOutgoingProducer.Prepare(snapshot, index, peerId, runId, () => CheckedSnapshot().SavedBook, CheckedSource);
        foreach (var proposal in bodies.SelectMany(value => value["proposals"]!.AsArray().OfType<JsonObject>()))
        {
            var kind = proposal["kind"]!.GetValue<string>();
            var membership = before["members"]![kind == "task" ? "tasks" : "notes"]!.AsArray();
            var id = proposal[kind == "attachment" ? "parent_id" : "id"]!.GetValue<string>();
            if (membership.Any(value => value!.GetValue<string>() == id)) continue;
            var target = new JsonObject(new[] { "proposal_id", "kind", "id", "parent_id", "prior_hash", "clock" }
                .Select(key => new KeyValuePair<string, JsonNode?>(key, proposal[key]!.DeepClone())));
            targets.Add(target["proposal_id"]!.GetValue<string>(), target);
        }
        CheckCurrent();
    }

    private string CheckedSource()
    {
        if (!currentOwner()) throw new InvalidOperationException("actor_target_owner_changed");
        if (currentSource() != sourceRevision) throw new InvalidOperationException("actor_target_source_changed");
        if (!JsonNode.DeepEquals(currentScope(), before)) throw new InvalidOperationException("actor_target_scope_changed");
        return sourceRevision;
    }
    private NativeActorBookSnapshot CheckedSnapshot()
    {
        var snapshot = currentSnapshot();
        if (snapshot is null || snapshot.SavedBook != bookBinding) throw new InvalidOperationException("actor_target_book_changed");
        return snapshot;
    }
    private void CheckCurrent() { CheckedSource(); CheckedSnapshot(); CheckedSource(); }
    internal JsonArray Targets()
    {
        CheckCurrent();
        return new JsonArray(targets.OrderBy(value => value.Key, StringComparer.Ordinal).Select(value => (JsonNode)value.Value.DeepClone()).ToArray());
    }
    internal bool RequireExact(string expectedRunId, JsonObject target)
    {
        CheckCurrent();
        if (expectedRunId != runId || target["proposal_id"] is not JsonValue id || !id.TryGetValue<string>(out var proposalId) ||
            !targets.TryGetValue(proposalId, out var original) || !JsonNode.DeepEquals(original, target)) throw new InvalidOperationException("actor_target_proof_changed");
        return true;
    }
}
