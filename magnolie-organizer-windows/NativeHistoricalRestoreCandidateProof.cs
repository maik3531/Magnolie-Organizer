using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Independent exact candidate evidence, NOT origin/save/data/receipt authority.
// No book, attachment bytes or provider callback survives this preparation.
internal sealed class NativeHistoricalRestoreCandidateProof
{
    internal string SourceRevision { get; }
    internal NativeBookSaveState BeforeSavedBook { get; }
    internal string BeforeContentSha256 { get; }
    internal string AfterSha256 { get; }
    internal string AfterContentSha256 { get; }
    internal string BeforeScopeJson { get; }
    internal string BeforeLiveJson { get; }
    internal string AfterLiveJson { get; }
    internal string TargetRevision { get; }
    internal string SourceProofRevision { get; }
    private NativeHistoricalRestoreCandidateProof(string source, NativeBookSaveState saved, string beforeContentHash, string afterHash, string afterContentHash,
        JsonObject scope, JsonObject beforeLive, JsonObject afterLive, string targetHash, string sourceHash)
    {
        SourceRevision = source; BeforeSavedBook = saved; BeforeContentSha256 = beforeContentHash; AfterSha256 = afterHash;
        AfterContentSha256 = afterContentHash;
        BeforeScopeJson = PhoneContentScope.Reference(scope).ToJsonString(); BeforeLiveJson = beforeLive.ToJsonString(); AfterLiveJson = afterLive.ToJsonString();
        TargetRevision = targetHash; SourceProofRevision = sourceHash;
    }
    public override string ToString() => "NativeHistoricalRestoreCandidateProof";
    private static string Text(JsonObject value, string key) => value[key]?.GetValue<string>() ?? "";
    private static bool Same(JsonNode? left, JsonNode? right) => TelefonCrypto.Canonical(left!).AsSpan().SequenceEqual(TelefonCrypto.Canonical(right!));
    private static JsonArray Array(IEnumerable<JsonObject> values) => new(values.Select(value => (JsonNode)value.DeepClone()).ToArray());
    private static JsonObject Live(JsonObject book)
    {
        var state = book["personalSync"]!.AsObject();
        var notes = (book["notizen"]?.AsArray() ?? []).OfType<JsonObject>().Where(value => Text(value, "baumQuelle").Length == 0 || value["persoenlichVerknuepft"]?.GetValue<bool>() == true)
            .Select(value => PersonalActorOutgoingProducer.NoteWireId(Text(value, "id"), state)).ToArray();
        var tasks = (book["aufgaben"]?.AsArray() ?? []).OfType<JsonObject>().Where(value => !new[] { "vonZweig", "fremdId", "delegiertAn", "herkunft" }.Any(key => Text(value, key).Length != 0))
            .Select(value => Text(value, "id")).ToArray();
        if (notes.Distinct(StringComparer.Ordinal).Count() != notes.Length || tasks.Distinct(StringComparer.Ordinal).Count() != tasks.Length)
            throw new InvalidDataException("actor_historical_live_identity_ambiguous");
        return PhoneContentScope.Create(notes, tasks)["members"]!.DeepClone().AsObject();
    }
    private static void UniqueKeys(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in value.EnumerateObject())
            { if (!keys.Add(item.Name)) throw new InvalidDataException("actor_historical_candidate_duplicate_key"); UniqueKeys(item.Value); }
        }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) UniqueKeys(item);
    }
    internal static NativeHistoricalRestoreCandidateProof Prepare(string peerId, string runId, int wireFormat, IReadOnlyList<JsonObject> nativeTargets,
        IReadOnlyList<JsonObject> explicitChoices, string candidateText, Func<bool> currentOwner, Func<string?> currentSource,
        Func<NativeActorBookSnapshot?> currentSnapshot, Func<JsonObject?> currentScope)
    {
        var targets = nativeTargets.Select(value => value.DeepClone().AsObject()).ToArray();
        var choices = explicitChoices.Select(value => value.DeepClone().AsObject()).ToArray();
        var sourceRevision = currentSource() ?? throw new InvalidOperationException("actor_target_source_changed");
        var scope = currentScope()?.DeepClone().AsObject() ?? throw new InvalidOperationException("actor_target_scope_changed");
        var snapshot = currentSnapshot() ?? throw new InvalidOperationException("actor_target_native_book_missing");
        void Current()
        {
            if (!currentOwner() || currentSource() != sourceRevision || !Same(currentScope(), scope) || currentSnapshot()?.SavedBook != snapshot.SavedBook)
                throw new InvalidOperationException("actor_historical_candidate_source_changed");
        }
        Current();
        var observer = new PersonalActorHistoricalRestoreSourceObservation(peerId, runId, wireFormat, currentOwner, currentSource, currentSnapshot, currentScope);
        var sources = observer.ObserveMany(runId, targets);
        var before = JsonNode.Parse(snapshot.Text)!.AsObject(); var expected = before.DeepClone().AsObject(); var state = expected["personalSync"]!.AsObject();
        if (choices.Length != targets.Length) throw new InvalidDataException("actor_historical_explicit_restore_required");
        var indexed = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var choice in choices)
        {
            TelefonProtocolContract.ExactObject(choice, "proposal_id", "decision", "expected_clock", "confirm_conflict");
            if (!indexed.TryAdd(Text(choice, "proposal_id"), choice)) throw new InvalidDataException("actor_historical_explicit_restore_required");
        }
        foreach (var target in targets)
            if (!indexed.TryGetValue(Text(target, "proposal_id"), out var choice) || Text(choice, "decision") != "restore" ||
                choice["confirm_conflict"]?.GetValue<bool>() != true || !Same(choice["expected_clock"], target["clock"]))
                throw new InvalidDataException("actor_historical_explicit_restore_required");
        var beforeLive = Live(before);
        if (!Same(beforeLive, scope["members"])) throw new InvalidOperationException("actor_historical_live_selection_not_ready");
        var counter = TelefonProtocolContract.Integer(state["counter"]); var localActor = Text(state, "actor_id");
        if (counter < 0 || counter > 9007199254740991 - targets.Length || (state["applied_decisions"]?.AsArray().Count ?? 0) + targets.Length > 500)
            throw new InvalidDataException("actor_historical_candidate_capacity");
        PersonalSyncContract.NormalizeClock(new JsonArray(new JsonObject { ["actor_id"] = localActor, ["counter"] = counter + 1 }));
        for (var index = 0; index < targets.Length; index++)
        {
            var target = targets[index]; var kind = Text(target, "kind"); var id = Text(target, "id"); var key = kind + "\0" + id;
            var trashId = sources[index]["local_restore_source"]!["trash_id"]!.GetValue<string>();
            var trash = expected["papierkorb"]!.AsArray(); var piece = trash.OfType<JsonObject>().Single(value => Text(value, "id") == trashId);
            var entry = piece["eintrag"]!.DeepClone().AsObject();
            if (kind == "task" && Text(entry, "elternUid").Length != 0) throw new InvalidOperationException("actor_historical_task_graph_not_ready");
            expected[kind == "note" ? "notizen" : "aufgaben"]!.AsArray().Add(entry); trash.Remove(piece);
            var meta = state["entities"]![key]!.AsObject(); state["counter"] = ++counter;
            var clocks = meta["clock"]!.AsArray().OfType<JsonObject>().ToDictionary(value => Text(value, "actor_id"), value => TelefonProtocolContract.Integer(value["counter"]), StringComparer.Ordinal);
            clocks[localActor] = Math.Max(clocks.GetValueOrDefault(localActor), counter);
            var clock = PersonalSyncContract.NormalizeClock(Array(clocks.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => new JsonObject { ["actor_id"] = pair.Key, ["counter"] = pair.Value })));
            if (!clock.OfType<JsonObject>().Any(value => TelefonProtocolContract.Integer(value["counter"]) > target["clock"]!.AsArray().OfType<JsonObject>()
                    .Where(old => Text(old, "actor_id") == Text(value, "actor_id")).Select(old => TelefonProtocolContract.Integer(old["counter"])).FirstOrDefault()))
                throw new InvalidOperationException("actor_historical_restore_clock_not_advanced");
            meta["clock"] = clock; meta["state"] = "live"; meta["status"] = "restored"; meta["hash"] = ""; meta["proposal_id"] = ""; meta["acknowledged_by_peer"] = false;
            var requests = state["restoration_requests"]?.AsArray() ?? new JsonArray();
            if (!requests.Any(value => value?.GetValue<string>() == key)) requests.Add(key);
            state["restoration_requests"] = requests.DeepClone();
            var applied = state["applied_decisions"]?.AsArray() ?? new JsonArray();
            if (applied.OfType<JsonObject>().Any(value => Text(value, "proposal_id") == Text(target, "proposal_id"))) throw new InvalidOperationException("actor_historical_candidate_replayed");
            applied.Add(new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = target["clock"]!.DeepClone(),
                ["kind"] = kind, ["id"] = id, ["parent_id"] = "" }); state["applied_decisions"] = applied.DeepClone();
        }
        if (candidateText.Length > 256L * 1024 * 1024 || Encoding.UTF8.GetByteCount(candidateText) > 256L * 1024 * 1024) throw new InvalidDataException("actor_historical_candidate_capacity");
        using (var document = JsonDocument.Parse(candidateText)) UniqueKeys(document.RootElement);
        var candidate = JsonNode.Parse(candidateText)!.AsObject();
        if (!Same(candidate, expected)) throw new InvalidOperationException("actor_historical_candidate_delta_changed");
        var afterLive = Live(candidate);
        var wanted = PhoneContentScope.Create(beforeLive["notes"]!.AsArray().Select(value => value!.GetValue<string>()).Concat(targets.Where(value => Text(value, "kind") == "note").Select(value => Text(value, "id"))),
            beforeLive["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).Concat(targets.Where(value => Text(value, "kind") == "task").Select(value => Text(value, "id"))))["members"]!;
        if (!Same(afterLive, wanted)) throw new InvalidOperationException("actor_historical_live_delta_changed");
        Current();
        return new(sourceRevision, snapshot.SavedBook, PersonalSyncContract.ProjectionHash(before),
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(candidateText))).ToLowerInvariant(), PersonalSyncContract.ProjectionHash(candidate), scope, beforeLive, afterLive,
            PersonalSyncContract.ProjectionHash(new JsonObject { ["targets"] = Array(targets), ["choices"] = Array(choices) }),
            PersonalSyncContract.ProjectionHash(new JsonObject { ["sources"] = Array(sources) }));
    }
}
