using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Private pure preparation only. Native caller supplies accepted scope and fresh
// source/writer callbacks. No queue, transport, data mutation or historical rights.
internal static class PersonalActorOutgoingProducer
{
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static readonly IComparer<string> IdOrder = Comparer<string>.Create((left, right) => Utf8.GetBytes(left).AsSpan().SequenceCompareTo(Utf8.GetBytes(right)));
    private static bool Hex(string? value) => value is { Length: 64 } && value.All(letter => letter is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Text(JsonObject value, string key, string fallback = "") => value.TryGetPropertyValue(key, out var node)
        ? node?.GetValue<string>() ?? throw new InvalidDataException("invalid_native_text") : fallback;
    private static bool Identifier(string value)
    {
        try { return value.Length != 0 && value == value.Trim() && !value.Contains('\0') && Utf8.GetByteCount(value) <= 160; }
        catch (EncoderFallbackException) { return false; }
    }
    private static string NoteId(string value, JsonObject state)
    {
        var aliases = state["note_aliases"]?.AsObject() ?? new JsonObject(); var seen = new HashSet<string>(StringComparer.Ordinal);
        if (!Identifier(value)) throw new InvalidDataException("invalid_native_note_identity");
        while (aliases.TryGetPropertyValue(value, out var raw))
        {
            var target = raw?.GetValue<string>() ?? "";
            if (!seen.Add(value) || !Identifier(target) || IdOrder.Compare(target, value) >= 0)
                throw new InvalidDataException("invalid_native_note_alias");
            value = target;
        }
        return value;
    }
    private static string NoteWireId(string value, JsonObject state) => NoteId(Text(state["note_ids"]?.AsObject() ?? new JsonObject(), value, value), state);
    private static string AttachmentId(string parent, string value, JsonObject state)
    {
        var aliases = state["attachment_aliases"]?.AsObject() ?? new JsonObject(); var seen = new HashSet<string>(StringComparer.Ordinal);
        if (!Identifier(value)) throw new InvalidDataException("invalid_native_attachment_identity");
        parent = NoteId(parent, state);
        while (true)
        {
            var targets = new List<string>();
            foreach (var (key, raw) in aliases)
            {
                var parts = key.Split('\0');
                if (parts.Length != 2 || parts[1] != value || NoteId(parts[0], state) != parent) continue;
                var target = raw?.GetValue<string>() ?? "";
                if (!Identifier(target) || IdOrder.Compare(target, value) >= 0) throw new InvalidDataException("invalid_native_attachment_alias");
                targets.Add(target);
            }
            if (targets.Count == 0) return value;
            if (!seen.Add(value)) throw new InvalidDataException("invalid_native_attachment_alias");
            value = targets.OrderBy(item => item, IdOrder).First();
        }
    }

    internal static IReadOnlyList<JsonObject> Prepare(NativeActorBookSnapshot snapshot, JsonObject acceptedScope, string peerId, string runId,
        Func<NativeBookSaveState?> currentSavedBook, Func<string?> currentSource)
    {
        PersonalSyncActorContract.Start(runId);
        if (!TelefonProtocolContract.IsUuidV4(peerId)) throw new InvalidDataException("invalid_native_peer");
        var source = currentSource();
        if (!Hex(source) || currentSavedBook() != snapshot.SavedBook) throw new InvalidOperationException("actor_producer_source_changed");
        var manifest = PhoneContentScope.Validate(acceptedScope.DeepClone().AsObject());
        var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
        var book = JsonNode.Parse(snapshot.Text)!.AsObject(); var state = book["personalSync"]?.AsObject() ?? new JsonObject();
        var entities = state["entities"]?.AsObject() ?? new JsonObject();
        var liveNotes = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        foreach (var node in book["notizen"]?.AsArray() ?? new JsonArray())
        {
            var note = node!.AsObject();
            if (!liveNotes.TryAdd(NoteWireId(Text(note, "id"), state), note)) throw new InvalidDataException("ambiguous_native_note_identity");
        }
        var liveTasks = (book["aufgaben"]?.AsArray() ?? new JsonArray()).Select(value => Text(value!.AsObject(), "id")).ToHashSet(StringComparer.Ordinal);
        var proposals = new List<JsonObject>();
        if (Text(state, "peer_device_id") == peerId)
        foreach (var (key, raw) in entities)
        {
            if (raw is not JsonObject meta || Text(meta, "state") != "deleted" || Text(meta, "status") != "local_pending" || Text(meta, "peer_device_id") != peerId) continue;
            var parts = key.Split('\0'); var kind = parts[0]; string id, parent;
            if (kind == "note" && parts.Length == 2)
            { id = parts[1]; parent = ""; if (!notes.Contains(id) || liveNotes.ContainsKey(id)) continue; }
            else if (kind == "task" && parts.Length == 2)
            { id = parts[1]; parent = ""; if (!tasks.Contains(id) || liveTasks.Contains(id)) continue; }
            else if (kind == "attachment" && parts.Length == 3)
            {
                parent = parts[1]; id = parts[2];
                if (!notes.Contains(parent) || !liveNotes.TryGetValue(parent, out var note) ||
                    Text(note, "baumQuelle").Length != 0 && note["persoenlichVerknuepft"]?.GetValue<bool>() != true) continue;
                if ((note["anhaenge"]?.AsArray() ?? new JsonArray()).Any(value => AttachmentId(parent, Text(value!.AsObject(), "id"), state) == id)) continue;
            }
            else continue;
            if (Text(meta, "parent_id") != parent || meta["conflict"]?.GetValue<bool>() == true || Text(meta, "hash").Length != 0)
                throw new InvalidDataException("invalid_native_tombstone");
            var clock = PersonalSyncContract.NormalizeClock(meta["clock"] ?? throw new InvalidDataException("invalid_native_clock"));
            var priorHash = Text(meta, "prior_hash"); var proposalId = Text(meta, "proposal_id");
            if (proposalId != PersonalSyncContract.DeletionProposalId(peerId, kind, id, parent, clock, priorHash))
                throw new InvalidDataException("native_tombstone_proposal_identity_changed");
            proposals.Add(new JsonObject { ["proposal_id"] = proposalId, ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
                ["clock"] = clock.DeepClone(), ["prior_hash"] = priorHash, ["deleted_ms"] = meta["deleted_ms"]?.DeepClone(), ["label"] = Text(meta, "label") });
            if (proposals.Count > 256) throw new InvalidDataException("actor_producer_target_capacity");
        }
        proposals = proposals.OrderBy(value => Text(value, "proposal_id"), IdOrder).ToList();
        if (proposals.Select(value => Text(value, "proposal_id")).Distinct(StringComparer.Ordinal).Count() != proposals.Count)
            throw new InvalidDataException("ambiguous_native_proposal_identity");
        var batchId = Guid.NewGuid().ToString("D"); var bodies = new List<JsonObject>();
        for (var start = 0; start < proposals.Count; start += 32)
        {
            var body = new JsonObject { ["format"] = 1, ["run_id"] = runId, ["proposal_batch_id"] = batchId, ["sequence"] = start / 32,
                ["last"] = start + 32 >= proposals.Count, ["proposals"] = new JsonArray(proposals.Skip(start).Take(32).Select(value => (JsonNode)value.DeepClone()).ToArray()) };
            PersonalSyncContract.ValidateBody("personal_sync.deletion_proposals", body); bodies.Add(body);
        }
        if (currentSource() != source || currentSavedBook() != snapshot.SavedBook) throw new InvalidOperationException("actor_producer_source_changed");
        return bodies;
    }
}
