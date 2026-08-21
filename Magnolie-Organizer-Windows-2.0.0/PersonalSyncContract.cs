using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class PersonalSyncContract
{
    internal const int ChunkRaw = 180_000;
    internal const int MaximumAttachment = 8 * 1024 * 1024;
    private const long MaximumTimestamp = 253402300799999;
    private const long MaximumSafeInteger = 9007199254740991;
    private static readonly HashSet<string> Kinds = new(StringComparer.Ordinal) { "note", "task", "notebook" };
    private static readonly HashSet<string> DeletionKinds = new(Kinds, StringComparer.Ordinal) { "attachment" };
    private static readonly Dictionary<string, string> MimeKinds = new(StringComparer.Ordinal)
    { ["image/jpeg"] = "image", ["image/png"] = "image", ["image/webp"] = "image", ["image/gif"] = "image", ["application/pdf"] = "pdf" };

    internal static void ValidateBody(string kind, JsonObject body)
    {
        switch (kind)
        {
            case "personal_sync.settings":
                Exact(body, "format", "own_device"); Number(body, "format", 1, 1); Bool(body, "own_device"); break;
            case "personal_sync.request": ValidateRequest(body); break;
            case "personal_sync.batch": ValidateBatch(body); break;
            case "personal_sync.report": ValidateReport(body); break;
            case "personal_sync.attachment_request": ValidateAttachmentRequest(body); break;
            case "personal_sync.attachment_chunk": ValidateAttachmentChunk(body); break;
            case "personal_sync.attachment_result": ValidateAttachmentResult(body); break;
            case "personal_sync.deletion_proposals": ValidateDeletionProposals(body); break;
            case "personal_sync.deletion_decision": ValidateDeletionDecision(body); break;
            default: throw new InvalidDataException("Unbekannte Personal-Sync-Nachricht.");
        }
    }

    internal static string ProjectionHash(JsonObject value) => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(value))).ToLowerInvariant();

    internal static string RecordsHash(JsonArray records)
    {
        var keys = records.Select(item =>
        {
            var record = item as JsonObject ?? throw new InvalidDataException("Datensatz erwartet.");
            return (Kind: String(record, "kind"), Id: String(record, "id"));
        }).ToArray();
        if (!keys.SequenceEqual(keys.Distinct().OrderBy(item => item.Kind, Utf8Comparer.Instance).ThenBy(item => item.Id, Utf8Comparer.Instance)))
            throw new InvalidDataException("Datensatzsortierung ungültig.");
        return Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(records))).ToLowerInvariant();
    }

    internal static JsonArray NormalizeClock(JsonNode? node)
    {
        if (node is not JsonArray clock || clock.Count is < 1 or > 16) throw new InvalidDataException("Vektoruhr ungültig.");
        var result = new JsonArray(); string? previous = null;
        foreach (var raw in clock)
        {
            var item = raw as JsonObject ?? throw new InvalidDataException("Vektoruhr ungültig."); Exact(item, "actor_id", "counter");
            var actor = String(item, "actor_id"); Uuid4(actor); var counter = Number(item, "counter", 1, MaximumSafeInteger);
            if (previous is not null && Utf8Comparer.Instance.Compare(actor, previous) <= 0) throw new InvalidDataException("Vektoruhr ist nicht streng sortiert.");
            previous = actor; result.Add(new JsonObject { ["actor_id"] = actor, ["counter"] = counter });
        }
        return result;
    }

    internal static string CompareClocks(JsonNode left, JsonNode right)
    {
        var a = ClockMap(NormalizeClock(left)); var b = ClockMap(NormalizeClock(right)); var greater = false; var smaller = false;
        foreach (var key in a.Keys.Union(b.Keys)) { greater |= a.GetValueOrDefault(key) > b.GetValueOrDefault(key); smaller |= a.GetValueOrDefault(key) < b.GetValueOrDefault(key); }
        return greater && smaller ? "concurrent" : greater ? "dominates" : smaller ? "dominated" : "equal";
    }

    internal static JsonArray MergeClocks(JsonNode left, JsonNode right)
    {
        var values = ClockMap(NormalizeClock(left));
        foreach (var item in ClockMap(NormalizeClock(right))) values[item.Key] = Math.Max(values.GetValueOrDefault(item.Key), item.Value);
        if (values.Count > 16) throw new InvalidDataException("Vektoruhrüberlauf.");
        return new JsonArray(values.OrderBy(item => item.Key, Utf8Comparer.Instance).Select(item => (JsonNode)new JsonObject { ["actor_id"] = item.Key, ["counter"] = item.Value }).ToArray());
    }

    internal static string ConflictId(string kind, string id, string loserHash)
    {
        if (!Kinds.Contains(kind) || !Identifier(id) || !Hash(loserHash)) throw new InvalidDataException("Konfliktidentität ungültig.");
        return ShapedUuid(SHA256.HashData(Encoding.UTF8.GetBytes(kind + "\0" + id + "\0" + loserHash)));
    }

    internal static string DeletionProposalId(string peerId, string kind, string id, string parentId, JsonNode clock, string priorHash)
    {
        Uuid4(peerId); if (!DeletionKinds.Contains(kind) || !Identifier(id) || !Identifier(parentId, true) || !Hash(priorHash)) throw new InvalidDataException("Löschvorschlagsidentität ungültig.");
        var normalized = NormalizeClock(clock);
        var material = new JsonArray(peerId, kind, id, parentId, normalized.DeepClone(), priorHash);
        return ShapedUuid(SHA256.HashData(Encoding.UTF8.GetBytes("personal-deletion-v1\0").Concat(TelefonCrypto.Canonical(material)).ToArray()));
    }

    internal static string? MimeFromMagic(ReadOnlySpan<byte> raw)
    {
        if (raw.StartsWith(new byte[] { 0xff, 0xd8, 0xff })) return "image/jpeg";
        if (raw.StartsWith(new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a })) return "image/png";
        if (raw.Length >= 12 && raw[..4].SequenceEqual("RIFF"u8) && raw[8..12].SequenceEqual("WEBP"u8)) return "image/webp";
        if (raw.StartsWith("GIF87a"u8) || raw.StartsWith("GIF89a"u8)) return "image/gif";
        if (raw.StartsWith("%PDF-"u8)) return "application/pdf";
        return null;
    }

    internal static (string Mime, byte[] Data) DecodeDataUrl(string value)
    {
        if (value.Length > 12_000_000 || !value.StartsWith("data:", StringComparison.Ordinal)) throw new InvalidDataException("Attachment-Data-URL ungültig.");
        const string marker = ";base64,"; var split = value.IndexOf(marker, StringComparison.Ordinal);
        if (split <= 5 || value.IndexOf(marker, split + marker.Length, StringComparison.Ordinal) >= 0) throw new InvalidDataException("Attachment-Data-URL ungültig.");
        var mime = value[5..split]; if (!MimeKinds.ContainsKey(mime)) throw new InvalidDataException("Attachment-MIME ungültig.");
        var encoded = value[(split + marker.Length)..]; byte[] raw;
        try { raw = Convert.FromBase64String(encoded); } catch (FormatException error) { throw new InvalidDataException("Attachment-Base64 ungültig.", error); }
        if (raw.Length is < 1 or > MaximumAttachment || Convert.ToBase64String(raw) != encoded || MimeFromMagic(raw) != mime) throw new InvalidDataException("Attachment-Inhalt ungültig.");
        return (mime, raw);
    }

    private static void ValidateRequest(JsonObject body)
    {
        Exact(body, "format", "run_id", "trigger", "modules"); Number(body, "format", 1, 2); Uuid4(String(body, "run_id")); Enum(body, "trigger", "manual", "auto_wifi");
        if (body["modules"] is not JsonArray modules || !new[] { "notes", "tasks", "notes\0tasks" }.Contains(string.Join("\0", modules.Select(item => String(item)))))
            throw new InvalidDataException("Personal-Sync-Module ungültig.");
    }

    private static void ValidateBatch(JsonObject body)
    {
        var format = Number(body, "format", 1, 2); Exact(body, format == 2 ? ["format", "run_id", "batch_id", "sequence", "last", "reply", "records", "records_hash"] : ["format", "run_id", "batch_id", "sequence", "last", "reply", "records"]);
        Uuid4(String(body, "run_id")); Uuid4(String(body, "batch_id")); Number(body, "sequence", 0, 100000); Bool(body, "last"); Bool(body, "reply");
        if (body["records"] is not JsonArray records || records.Count > 32) throw new InvalidDataException("Personal-Sync-Batch ungültig.");
        var keys = new List<(string Kind, string Id)>(); foreach (var raw in records) { var record = raw as JsonObject ?? throw new InvalidDataException(); ValidateRecord(record, (int)format); keys.Add((String(record, "kind"), String(record, "id"))); }
        if (!keys.SequenceEqual(keys.Distinct().OrderBy(item => item.Kind, Utf8Comparer.Instance).ThenBy(item => item.Id, Utf8Comparer.Instance)) || TelefonCrypto.Canonical(body).Length > 192 * 1024 || format == 2 && !Hash(String(body, "records_hash")))
            throw new InvalidDataException("Personal-Sync-Batchsortierung ungültig.");
    }

    private static void ValidateRecord(JsonObject record, int format)
    {
        Exact(record, "kind", "id", "state", "clock", "hash", "modified_ms", "value"); var kind = String(record, "kind"); var id = String(record, "id");
        if (!Kinds.Contains(kind) || !Identifier(id) || String(record, "state") != "live" || !Hash(String(record, "hash"))) throw new InvalidDataException("Personal-Sync-Datensatz ungültig.");
        NormalizeClock(record["clock"]); var modified = Number(record, "modified_ms", 0, MaximumTimestamp); var value = record["value"] as JsonObject ?? throw new InvalidDataException();
        ValidateValue(kind, value, format); if (ProjectionHash(value) != String(record, "hash") || modified != Number(value, "modified_ms", 0, MaximumTimestamp)) throw new InvalidDataException("Projektionshash ungültig.");
    }

    private static void ValidateValue(string kind, JsonObject value, int format)
    {
        if (kind == "note")
        {
            Exact(value, format == 2 ? ["title", "text", "html", "notebook_id", "symbol", "created_ms", "modified_ms", "attachments"] : ["title", "text", "html", "notebook_id", "symbol", "created_ms", "modified_ms"]);
            Text(value, "title"); Text(value, "text"); Text(value, "html"); Text(value, "notebook_id", 160, true); Text(value, "symbol", 160); Number(value, "created_ms", 0, MaximumTimestamp); Number(value, "modified_ms", 0, MaximumTimestamp);
            if (format == 2) { if (value["attachments"] is not JsonArray values || values.Count > 64) throw new InvalidDataException(); var ids = values.Select(raw => ValidateAttachmentDescriptor(raw as JsonObject ?? throw new InvalidDataException())).ToArray(); if (ids.Distinct(StringComparer.Ordinal).Count() != ids.Length) throw new InvalidDataException("Doppelte Attachment-ID."); }
        }
        else if (kind == "task")
        {
            Exact(value, "title", "note", "due", "priority", "completed", "remind", "lead_days", "reminder_minute", "created_ms", "modified_ms");
            Text(value, "title"); Text(value, "note"); var due = Text(value, "due", 160); if (due.Length != 0 && (due.Length != 10 || due[4] != '-' || due[7] != '-' || due.Where((_, index) => index is not (4 or 7)).Any(character => !char.IsAsciiDigit(character)))) throw new InvalidDataException("Fälligkeitsdatum ungültig.");
            Number(value, "priority", 1, 3); Bool(value, "completed"); Bool(value, "remind"); Number(value, "lead_days", 0, 365); Number(value, "reminder_minute", 0, 1439); Number(value, "created_ms", 0, MaximumTimestamp); Number(value, "modified_ms", 0, MaximumTimestamp);
        }
        else { Exact(value, "name", "modified_ms"); Text(value, "name"); Number(value, "modified_ms", 0, MaximumTimestamp); }
    }

    internal static string ValidateAttachmentDescriptor(JsonObject value)
    {
        Exact(value, "attachment_id", "name", "kind", "mime", "size", "sha256"); var id = String(value, "attachment_id"); var name = String(value, "name"); var mime = String(value, "mime");
        if (!Identifier(id) || Encoding.UTF8.GetByteCount(name) is < 1 or > 720 || name.Any(character => character < 32 || character == 127 || character is '/' or '\\') ||
            !MimeKinds.TryGetValue(mime, out var expected) || String(value, "kind") != expected || Number(value, "size", 1, MaximumAttachment) < 1 || !Hash(String(value, "sha256"))) throw new InvalidDataException("Attachment-Deskriptor ungültig.");
        return id;
    }

    private static void ValidateReport(JsonObject body)
    {
        var format = Number(body, "format", 1, 2); Exact(body, format == 2 ? ["format", "run_id", "state", "trigger", "transport", "sent", "received", "conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms", "error", "deletions", "attachments"] : ["format", "run_id", "state", "trigger", "transport", "sent", "received", "conflicts", "attachments_omitted", "oversized_skipped", "started_ms", "finished_ms", "error", "deletions"]);
        Uuid4(String(body, "run_id")); Enum(body, "state", "complete", "partial", "blocked", "failed"); Enum(body, "trigger", "manual", "auto_wifi"); Enum(body, "transport", "wifi", "bluetooth");
        Counts(body, "sent", "notes", "tasks", "notebooks"); Counts(body, "received", "notes", "tasks", "notebooks"); Number(body, "conflicts", 0, MaximumSafeInteger); Number(body, "attachments_omitted", 0, MaximumSafeInteger); Number(body, "oversized_skipped", 0, MaximumSafeInteger);
        var started = Number(body, "started_ms", 0, MaximumTimestamp); var finished = Number(body, "finished_ms", 0, MaximumTimestamp); if (finished < started) throw new InvalidDataException("Berichtszeitachse ungültig.");
        Enum(body, "error", "none", "offline", "not_granted", "too_large", "save_failed", "protocol", "unknown");
        if (format == 2) Counts(body, "attachments", "declared", "requested", "sent", "received", "reused", "preserved", "failed", "bytes");
        var deletions = body["deletions"] as JsonObject ?? throw new InvalidDataException(); Exact(deletions, "pending", "deleted", "restored", "conflicts", "blocked", "trash");
        foreach (var name in new[] { "pending", "deleted", "restored", "conflicts", "blocked" }) Number(deletions, name, 0, MaximumSafeInteger); Counts(deletions, "trash", "notes", "tasks", "notebooks", "attachments");
    }

    private static void ValidateAttachmentRequest(JsonObject body)
    {
        AttachmentIdentity(body, "format", "run_id", "reply", "records_hash", "wants"); if (body["wants"] is not JsonArray wants || wants.Count is < 1 or > 64) throw new InvalidDataException();
        var hashes = new List<string>(); foreach (var raw in wants) { var want = raw as JsonObject ?? throw new InvalidDataException(); Exact(want, "sha256", "ranges"); var hash = String(want, "sha256"); if (!Hash(hash) || want["ranges"] is not JsonArray ranges || ranges.Count is < 1 or > 128) throw new InvalidDataException(); long previous = -1; foreach (var rangeRaw in ranges) { if (rangeRaw is not JsonArray range || range.Count != 2) throw new InvalidDataException(); var start = NodeNumber(range[0], 0, 46); var end = NodeNumber(range[1], 1, 47); if (start >= end || start < previous) throw new InvalidDataException(); previous = end; } hashes.Add(hash); }
        if (!hashes.SequenceEqual(hashes.Distinct().Order(Utf8Comparer.Instance))) throw new InvalidDataException("Attachment-Anforderung unsortiert.");
    }

    private static void ValidateAttachmentChunk(JsonObject body)
    {
        AttachmentIdentity(body, "format", "run_id", "reply", "records_hash", "sha256", "index", "data"); if (!Hash(String(body, "sha256"))) throw new InvalidDataException(); Number(body, "index", 0, 46);
        var encoded = String(body, "data"); byte[] raw; try { raw = Convert.FromBase64String(encoded); } catch (FormatException error) { throw new InvalidDataException("Chunk-Base64 ungültig.", error); }
        if (raw.Length is < 1 or > ChunkRaw || Convert.ToBase64String(raw) != encoded || TelefonCrypto.Canonical(body).Length > 192 * 1024) throw new InvalidDataException("Attachment-Chunk ungültig.");
    }

    private static void ValidateAttachmentResult(JsonObject body)
    {
        AttachmentIdentity(body, "format", "run_id", "reply", "records_hash", "sha256", "state", "error"); if (!Hash(String(body, "sha256"))) throw new InvalidDataException();
        var state = Enum(body, "state", "complete", "failed"); var error = Enum(body, "error", "none", "not_found", "invalid", "too_large", "save_failed"); if ((state == "complete") != (error == "none")) throw new InvalidDataException("Attachment-Ergebnis ungültig.");
    }

    private static void ValidateDeletionProposals(JsonObject body)
    {
        Exact(body, "format", "run_id", "proposal_batch_id", "sequence", "last", "proposals"); Number(body, "format", 1, 1); Uuid4(String(body, "run_id")); Uuid4(String(body, "proposal_batch_id")); Number(body, "sequence", 0, 100000); Bool(body, "last");
        if (body["proposals"] is not JsonArray values || values.Count > 32) throw new InvalidDataException(); var ids = new List<string>();
        foreach (var raw in values) { var value = raw as JsonObject ?? throw new InvalidDataException(); Exact(value, "proposal_id", "kind", "id", "parent_id", "clock", "prior_hash", "deleted_ms", "label"); var proposal = String(value, "proposal_id"); Uuid4(proposal); var kind = String(value, "kind"); var id = String(value, "id"); var parent = String(value, "parent_id"); var label = String(value, "label"); if (!DeletionKinds.Contains(kind) || !Identifier(id) || !Identifier(parent, true) || (kind == "attachment") != (parent.Length != 0) || !Hash(String(value, "prior_hash")) || Encoding.UTF8.GetByteCount(label) > 240 || label.Any(character => character < 32 || character == 127)) throw new InvalidDataException(); NormalizeClock(value["clock"]); Number(value, "deleted_ms", 0, MaximumTimestamp); ids.Add(proposal); }
        OrderedIds(ids, body);
    }

    private static void ValidateDeletionDecision(JsonObject body)
    {
        Exact(body, "format", "run_id", "decision_id", "decisions"); Number(body, "format", 1, 1); Uuid4(String(body, "run_id")); Uuid4(String(body, "decision_id"));
        if (body["decisions"] is not JsonArray values || values.Count is < 1 or > 32) throw new InvalidDataException(); var ids = new List<string>();
        foreach (var raw in values) { var value = raw as JsonObject ?? throw new InvalidDataException(); Exact(value, "proposal_id", "decision", "expected_clock"); var id = String(value, "proposal_id"); Uuid4(id); Enum(value, "decision", "delete", "restore"); NormalizeClock(value["expected_clock"]); ids.Add(id); }
        OrderedIds(ids, body);
    }

    private static void AttachmentIdentity(JsonObject body, params string[] fields) { Exact(body, fields); Number(body, "format", 2, 2); Uuid4(String(body, "run_id")); Bool(body, "reply"); if (!Hash(String(body, "records_hash"))) throw new InvalidDataException(); }
    private static void Counts(JsonObject parent, string name, params string[] fields) { var value = parent[name] as JsonObject ?? throw new InvalidDataException(); Exact(value, fields); foreach (var field in fields) Number(value, field, 0, MaximumSafeInteger); }
    private static void OrderedIds(List<string> ids, JsonObject body) { if (!ids.SequenceEqual(ids.Distinct().Order(Utf8Comparer.Instance)) || TelefonCrypto.Canonical(body).Length > 192 * 1024) throw new InvalidDataException("Identitäten unsortiert."); }
    private static Dictionary<string, long> ClockMap(JsonArray clock) => clock.Select(raw => raw!.AsObject()).ToDictionary(item => String(item, "actor_id"), item => Number(item, "counter", 1, MaximumSafeInteger), StringComparer.Ordinal);
    private static string ShapedUuid(byte[] hash) { var bytes = hash[..16]; bytes[6] = (byte)((bytes[6] & 0x0f) | 0x40); bytes[8] = (byte)((bytes[8] & 0x3f) | 0x80); return new Guid(bytes.AsSpan(), bigEndian: true).ToString("D"); }
    private static bool Identifier(string value, bool allowEmpty = false) => Encoding.UTF8.GetByteCount(value) <= 160 && !value.Contains('\0') && value == value.Trim() && (allowEmpty || value.Length != 0);
    private static bool Hash(string value) => value.Length == 64 && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Text(JsonObject body, string name, int maximum = 128 * 1024, bool identifier = false) { var value = String(body, name); if (Encoding.UTF8.GetByteCount(value) > maximum || identifier && value != value.Trim()) throw new InvalidDataException("Text ungültig."); return value; }
    private static string Enum(JsonObject body, string name, params string[] values) { var value = String(body, name); if (!values.Contains(value, StringComparer.Ordinal)) throw new InvalidDataException("Auswahlwert ungültig."); return value; }
    private static string String(JsonObject body, string name) => TelefonMessagingContract.String(body, name);
    private static string String(JsonNode? node) { if (node is not JsonValue value || !value.TryGetValue<string>(out var text)) throw new InvalidDataException("Text erwartet."); return text; }
    private static bool Bool(JsonObject body, string name) => TelefonMessagingContract.Boolean(body, name);
    private static long Number(JsonObject body, string name, long minimum, long maximum) => NodeNumber(body[name], minimum, maximum);
    private static long NodeNumber(JsonNode? node, long minimum, long maximum) { if (!TelefonProtocolContract.TryInteger(node, out var value) || value < minimum || value > maximum) throw new InvalidDataException("Ganzzahl ungültig."); return value; }
    private static void Uuid4(string value) { if (!TelefonProtocolContract.IsUuidV4(value)) throw new InvalidDataException("UUIDv4 ungültig."); }
    private static void Exact(JsonObject body, params string[] fields) => TelefonProtocolContract.ExactObject(body, fields);

    private sealed class Utf8Comparer : IComparer<string>
    {
        internal static readonly Utf8Comparer Instance = new();
        public int Compare(string? left, string? right) => (left, right) switch
        { (null, null) => 0, (null, _) => -1, (_, null) => 1, _ => Encoding.UTF8.GetBytes(left).AsSpan().SequenceCompareTo(Encoding.UTF8.GetBytes(right)) };
    }
}
