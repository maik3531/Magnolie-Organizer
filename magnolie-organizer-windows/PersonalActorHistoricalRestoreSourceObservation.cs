using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Metadata-only current local restore source proof, NOT save/data/origin rights.
// Caller retains its native source/writer guard; no source snapshot cache or
// accepted-batch/peer-blob fallback. One bounded fresh native parse per group.
internal sealed class PersonalActorHistoricalRestoreSourceObservation : PersonalActorIncomingLiveTargetObservation
{
    private readonly int wireFormat;
    internal PersonalActorHistoricalRestoreSourceObservation(string peerId, string runId, int wireFormat, Func<bool> currentOwner,
        Func<string?> currentSource, Func<NativeActorBookSnapshot?> currentSnapshot, Func<JsonObject?> currentScope)
        : base(peerId, runId, currentOwner, currentSource, currentSnapshot, currentScope)
    {
        if (wireFormat is not (3 or 14)) throw new InvalidDataException("actor_historical_restore_format");
        this.wireFormat = wireFormat;
    }
    private static string Text(JsonObject value, string key, string fallback = "") => value[key]?.GetValue<string>() is { Length: > 0 } text ? text : fallback;
    private static long Number(JsonObject value, string key, long fallback = 0, bool zeroDefault = true)
    {
        if (value[key] is null) return fallback;
        var number = TelefonProtocolContract.Integer(value[key]);
        if (number is < -9007199254740991 or > 9007199254740991) throw new InvalidDataException("invalid_native_restore_source");
        return number == 0 && zeroDefault ? fallback : number;
    }
    private static bool Flag(JsonObject value, string key) => value[key]?.GetValue<bool>() ?? false;
    private JsonObject Projection(JsonObject state, string kind, string id, JsonObject entry, JsonObject meta)
    {
        var value = new JsonObject { ["title"] = Text(entry, "titel"), ["created_ms"] = Number(entry, "angelegt"), ["modified_ms"] = Number(meta, "modified_ms") };
        if (kind == "note")
        {
            var notebookState = new JsonObject { ["note_ids"] = state["notebook_ids"]?.DeepClone() ?? new JsonObject(),
                ["note_aliases"] = state["notebook_aliases"]?.DeepClone() ?? new JsonObject() };
            value["text"] = Text(entry, "text"); value["html"] = Text(entry, "html"); value["symbol"] = Text(entry, "symbol", "notiz");
            value["notebook_id"] = PersonalActorOutgoingProducer.NoteWireId(Text(entry, "notizbuchId", "notizbuch-lose-notizen"), notebookState);
            var attachments = entry["anhaenge"]?.AsArray() ?? [];
            if (attachments.Count > 64) throw new InvalidDataException("invalid_native_restore_source");
            var descriptors = new JsonArray();
            foreach (var raw in attachments)
            {
                var attachment = raw!.AsObject();
                var (mime, bytes) = PersonalSyncContract.DecodeDataUrl(Text(attachment, "daten", Text(attachment, "data")));
                try
                {
                    var descriptor = new JsonObject { ["attachment_id"] = PersonalActorOutgoingProducer.AttachmentId(id, Text(attachment, "id"), state),
                        ["name"] = Text(attachment, "name"), ["kind"] = mime == "application/pdf" ? "pdf" : "image", ["mime"] = mime,
                        ["size"] = bytes.Length, ["sha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() };
                    PersonalSyncContract.ValidateAttachmentDescriptor(descriptor); descriptors.Add(descriptor);
                }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            value["attachments"] = descriptors;
        }
        else
        {
            value["note"] = Text(entry, "notiz"); value["due"] = Text(entry, "faellig"); value["priority"] = Number(entry, "prio", 2);
            value["completed"] = Flag(entry, "erledigt"); value["remind"] = Flag(entry, "erinnern");
            value["lead_days"] = Number(entry, "individuelleErinnerungTage", Number(entry, "vorlaufTage"));
            value["reminder_minute"] = Number(entry, "erinnerungsMinute", 480, zeroDefault: false);
            value["uid"] = Text(entry, "uid"); value["parent_uid"] = Text(entry, "elternUid"); value["order"] = Math.Max(0, Number(entry, "reihenfolge"));
        }
        if (wireFormat == 14) value["origin_app"] = Text(entry, "ursprungApp") is "notes" or "organizer" ? Text(entry, "ursprungApp") : "";
        return value;
    }
    protected override JsonObject ObserveTarget(string expectedRunId, JsonObject target, JsonObject book)
    {
        var observation = base.ObserveTarget(expectedRunId, target, book);
        var kind = Text(target, "kind"); var id = Text(target, "id");
        if (kind is not ("note" or "task") || Text(observation, "local_state") != "deleted" || !Flag(observation, "metadata_matches"))
            throw new InvalidOperationException("actor_historical_restore_target_not_ready");
        var state = book["personalSync"]!.AsObject(); var meta = state["entities"]![kind + "\0" + id]!.AsObject();
        var sources = (book["papierkorb"]?.AsArray() ?? []).OfType<JsonObject>().Where(piece => Text(piece, "art") == kind &&
            piece["eintrag"] is JsonObject entry && (kind == "task" ? Text(entry, "id") == id : PersonalActorOutgoingProducer.NoteWireId(Text(entry, "id"), state) == id)).ToArray();
        if (sources.Length != 1) throw new InvalidOperationException("restore_unavailable");
        var source = sources[0]; var content = source["eintrag"]!.AsObject();
        if (Text(source, "id").Length == 0 || book["papierkorb"]!.AsArray().OfType<JsonObject>().Count(piece => Text(piece, "id") == Text(source, "id")) != 1 ||
            (kind == "note" ? Text(content, "baumQuelle").Length != 0 && !Flag(content, "persoenlichVerknuepft") :
            new[] { "vonZweig", "fremdId", "delegiertAn", "herkunft" }.Any(field => Text(content, field).Length != 0)))
            throw new InvalidOperationException("restore_unavailable");
        if (kind == "note" && state["entities"]!.AsObject().Any(pair => pair.Key.StartsWith("attachment\0" + id + "\0", StringComparison.Ordinal) &&
            pair.Value is JsonObject child && Text(child, "state") == "deleted")) throw new InvalidOperationException("actor_historical_child_review_required");
        if (PersonalSyncContract.ProjectionHash(Projection(state, kind, id, content, meta)) != Text(meta, "prior_hash"))
            throw new InvalidOperationException("restore_unavailable");
        var result = observation.DeepClone().AsObject();
        result["local_restore_source"] = new JsonObject { ["trash_id"] = Text(source, "id"), ["sha256"] = NativeBookJson.Hash(source) };
        result["action_authorized"] = false;
        return result;
    }
}
