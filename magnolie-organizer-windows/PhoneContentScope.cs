using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>Bounded current-phone membership; fresh authentication and physical presence remain caller gates.</summary>
internal static class PhoneContentScope
{
    internal const int Version = 10;
    internal const string Kind = "personal_sync.content_scope";
    internal const string DataKind = "personal_sync.scoped_data";
    private static readonly HashSet<string> DataKinds = ["personal_sync.request", "personal_sync.batch", "personal_sync.report",
        "personal_sync.attachment_request", "personal_sync.attachment_chunk", "personal_sync.attachment_result"];
    internal const int MaximumMembers = 50000;
    private const int MinimumChunk = 32;
    private const int MaximumChunk = 256;
    private const int MaximumParts = (MaximumMembers + MinimumChunk - 1) / MinimumChunk;
    private const long MaximumRevision = 9007199254740991;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static readonly IComparer<string> IdOrder = Comparer<string>.Create((a, b) => Utf8.GetBytes(a).AsSpan().SequenceCompareTo(Utf8.GetBytes(b)));

    internal static bool Supported(JsonObject local, JsonObject remote)
    {
        static bool Marked(JsonObject items) => new[] { "personal_notes_sync", "personal_tasks_sync" }.All(name =>
            items[name] is JsonObject item && item["available"] is JsonValue enabled && enabled.TryGetValue<bool>(out var available) &&
            available && item["versions"] is JsonArray versions && versions.Any(value =>
                TelefonProtocolContract.TryInteger(value, out var marker) && marker == Version));
        return Marked(local) && Marked(remote);
    }

    private static string Text(JsonObject value, string field) => value[field] is JsonValue raw && raw.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("Scope text missing.");
    private static long Number(JsonObject value, string field) => TelefonProtocolContract.Integer(value[field]);
    private static string Identifier(string value)
    {
        if (string.IsNullOrEmpty(value) || value != value.Trim() || value.Contains('\0') || Utf8.GetByteCount(value) > 160)
            throw new InvalidDataException("Invalid scope identity.");
        return value;
    }
    private static void Header(JsonObject value)
    {
        if (Number(value, "format") != Version || !TelefonProtocolContract.IsUuidV4(Text(value, "epoch")) ||
            Number(value, "revision") is < 1 or > MaximumRevision) throw new InvalidDataException("Invalid scope header.");
    }
    private static string Digest(JsonObject members) => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(members))).ToLowerInvariant();
    private static IReadOnlyList<string> Ids(JsonObject value, string field)
    {
        if (value[field] is not JsonArray list) throw new InvalidDataException("Scope identities missing.");
        var result = list.Select(raw => raw is JsonValue item && item.TryGetValue<string>(out var text)
            ? Identifier(text) : throw new InvalidDataException("Invalid scope identity.")).ToArray();
        if (!result.SequenceEqual(result.Distinct(StringComparer.Ordinal).Order(IdOrder)))
            throw new InvalidDataException("Scope identities must be unique and UTF-8 sorted.");
        return result;
    }

    internal static JsonObject Validate(JsonObject manifest)
    {
        TelefonProtocolContract.ExactObject(manifest, "format", "epoch", "revision", "scope_hash", "members"); Header(manifest);
        var members = manifest["members"] as JsonObject ?? throw new InvalidDataException("Scope members missing.");
        TelefonProtocolContract.ExactObject(members, "notes", "tasks");
        if (Ids(members, "notes").Count + Ids(members, "tasks").Count > MaximumMembers || Text(manifest, "scope_hash") != Digest(members))
            throw new InvalidDataException("Invalid scope count or hash.");
        return manifest;
    }

    internal static JsonObject Create(IEnumerable<string> notes, IEnumerable<string> tasks, long revision = 1, string? epoch = null)
    {
        JsonArray List(IEnumerable<string> ids) => new(ids.Select(Identifier).Distinct(StringComparer.Ordinal).Order(IdOrder)
            .Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        var members = new JsonObject { ["notes"] = List(notes), ["tasks"] = List(tasks) };
        return Validate(new JsonObject { ["format"] = Version, ["epoch"] = epoch ?? Guid.NewGuid().ToString("D"),
            ["revision"] = revision, ["scope_hash"] = Digest(members), ["members"] = members });
    }

    internal static JsonObject Advance(JsonObject current, IEnumerable<string> notes, IEnumerable<string> tasks)
    {
        Validate(current); var candidate = Create(notes, tasks, Number(current, "revision"));
        if (JsonNode.DeepEquals(candidate["members"], current["members"])) return current;
        candidate["revision"] = Number(current, "revision") + 1;
        return Validate(candidate);
    }

    internal static JsonObject Reference(JsonObject manifest)
    {
        Validate(manifest); return new JsonObject { ["scope_epoch"] = Text(manifest, "epoch"),
            ["scope_revision"] = Number(manifest, "revision"), ["scope_hash"] = Text(manifest, "scope_hash") };
    }

    internal static void RequireCurrent(JsonObject body, JsonObject manifest)
    {
        var expected = Reference(manifest);
        if (Number(body, "scope_revision") != Number(expected, "scope_revision") ||
            Text(body, "scope_epoch") != Text(expected, "scope_epoch") || Text(body, "scope_hash") != Text(expected, "scope_hash"))
            throw new InvalidDataException("Stale or different content scope.");
    }

    internal static void ValidateReference(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "scope_epoch", "scope_revision", "scope_hash");
        var hash = Text(value, "scope_hash");
        if (!TelefonProtocolContract.IsUuidV4(Text(value, "scope_epoch")) || Number(value, "scope_revision") is < 1 or > MaximumRevision ||
            hash.Length != 64 || hash.Any(letter => !"0123456789abcdef".Contains(letter))) throw new InvalidDataException("Invalid scope reference.");
    }

    internal static JsonObject ValidateData(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, "format", "scope", "kind", "body");
        var kind = Text(value, "kind");
        if (Number(value, "format") != Version || !DataKinds.Contains(kind) || value["scope"] is not JsonObject scope || value["body"] is not JsonObject body)
            throw new InvalidDataException("Invalid scoped data envelope.");
        ValidateReference(scope);
        if (Number(body, "format") != (kind.StartsWith("personal_sync.attachment_", StringComparison.Ordinal) ? 2 : 3))
            throw new InvalidDataException("Invalid scoped record format.");
        PersonalSyncContract.ValidateBody(kind, body);
        if (TelefonCrypto.Canonical(value).Length > 256 * 1024) throw new InvalidDataException("Scoped data envelope too large.");
        return value;
    }

    internal static JsonObject Wrap(string kind, JsonObject body, JsonObject manifest) => ValidateData(new JsonObject
    { ["format"] = Version, ["scope"] = Reference(manifest), ["kind"] = kind, ["body"] = body.DeepClone() });

    internal static (string Kind, JsonObject Body) Unwrap(JsonObject value, JsonObject manifest)
    {
        ValidateData(value); RequireCurrent(value["scope"]!.AsObject(), manifest);
        return (Text(value, "kind"), value["body"]!.DeepClone().AsObject());
    }

    internal static JsonObject ValidatePart(JsonObject part)
    {
        TelefonProtocolContract.ExactObject(part, "format", "epoch", "revision", "scope_hash", "part", "parts", "members"); Header(part);
        var hash = Text(part, "scope_hash");
        if (hash.Length != 64 || hash.Any(letter => !"0123456789abcdef".Contains(letter)) || Number(part, "parts") is < 1 or > MaximumParts ||
            Number(part, "part") < 0 || Number(part, "part") >= Number(part, "parts") ||
            part["members"] is not JsonArray members || members.Count > MaximumChunk) throw new InvalidDataException("Invalid scope part.");
        var entries = new List<(string Kind, string Id)>();
        foreach (var raw in members)
        {
            var member = raw as JsonObject ?? throw new InvalidDataException("Invalid scope member.");
            TelefonProtocolContract.ExactObject(member, "kind", "id"); var kind = Text(member, "kind");
            if (kind is not ("note" or "task")) throw new InvalidDataException("Invalid scope kind.");
            entries.Add((kind, Identifier(Text(member, "id"))));
        }
        if (!entries.SequenceEqual(entries.Distinct().OrderBy(item => item.Kind, StringComparer.Ordinal).ThenBy(item => item.Id, IdOrder)) ||
            TelefonCrypto.Canonical(part).Length > 192 * 1024) throw new InvalidDataException("Unordered, repeated or oversized scope part.");
        return part;
    }

    internal static IReadOnlyList<JsonObject> Chunks(JsonObject manifest, int size = MaximumChunk)
    {
        Validate(manifest); if (size is < MinimumChunk or > MaximumChunk) throw new InvalidDataException("Invalid scope chunk size.");
        var members = manifest["members"]!.AsObject();
        var entries = new[] { (Kind: "note", Bucket: "notes"), (Kind: "task", Bucket: "tasks") }.SelectMany(type =>
            Ids(members, type.Bucket).Select(id => new JsonObject { ["kind"] = type.Kind, ["id"] = id })).ToArray();
        var count = Math.Max(1, (entries.Length + size - 1) / size);
        return Enumerable.Range(0, count).Select(index => ValidatePart(new JsonObject
        {
            ["format"] = Version, ["epoch"] = Text(manifest, "epoch"), ["revision"] = Number(manifest, "revision"),
            ["scope_hash"] = Text(manifest, "scope_hash"), ["part"] = index, ["parts"] = count,
            ["members"] = new JsonArray(entries.Skip(index * size).Take(size).Select(value => value.DeepClone()).ToArray())
        })).ToArray();
    }

    internal static JsonObject Assemble(IEnumerable<JsonObject> parts)
    {
        var byIndex = new Dictionary<long, JsonObject>(); JsonObject? header = null;
        foreach (var part in parts)
        {
            ValidatePart(part);
            var shape = new JsonObject(); foreach (var field in new[] { "format", "epoch", "revision", "scope_hash", "parts" }) shape[field] = part[field]!.DeepClone();
            if (header is not null && !JsonNode.DeepEquals(header, shape)) throw new InvalidDataException("Mixed scope generations.");
            header = shape; var index = Number(part, "part");
            if (byIndex.TryGetValue(index, out var previous) && !JsonNode.DeepEquals(previous, part)) throw new InvalidDataException("Conflicting scope duplicate.");
            byIndex[index] = part;
        }
        if (header is null || byIndex.Count != Number(header, "parts")) throw new InvalidDataException("Incomplete scope.");
        var members = new JsonObject { ["notes"] = new JsonArray(), ["tasks"] = new JsonArray() };
        for (var index = 0L; index < Number(header, "parts"); index++) foreach (var raw in byIndex[index]["members"]!.AsArray())
        {
            var member = raw!.AsObject(); members[Text(member, "kind") == "note" ? "notes" : "tasks"]!.AsArray().Add(member["id"]!.DeepClone());
        }
        header.Remove("parts"); header["members"] = members; return Validate(header);
    }

    internal static IReadOnlyList<JsonObject> FilterRecords(IReadOnlyList<JsonObject> records, JsonObject manifest)
    {
        Validate(manifest); var members = manifest["members"]!.AsObject();
        var notes = Ids(members, "notes").ToHashSet(StringComparer.Ordinal); var tasks = Ids(members, "tasks").ToHashSet(StringComparer.Ordinal);
        var selected = new HashSet<(string Kind, string Id)>(); var notebooks = new HashSet<string>(StringComparer.Ordinal);
        foreach (var record in records)
        {
            var kind = Text(record, "kind"); var id = Text(record, "id");
            if (Text(record, "state") != "live" || !(kind == "note" && notes.Contains(id) || kind == "task" && tasks.Contains(id))) continue;
            selected.Add((kind, id));
            if (kind == "note" && record["value"] is JsonObject value && value["notebook_id"] is JsonValue raw && raw.TryGetValue<string>(out var book) && book != "")
                notebooks.Add(Identifier(book));
        }
        return records.Where(record => Text(record, "state") == "live" && (selected.Contains((Text(record, "kind"), Text(record, "id"))) ||
            Text(record, "kind") == "notebook" && notebooks.Contains(Text(record, "id")))).ToArray();
    }

    /// <summary>Fresh authenticated connection evidence, never reconstructed from a saved manifest.</summary>
    internal sealed class Session(string peerId, string publicKey, long generation)
    {
        private JsonObject? header, manifest;
        private readonly Dictionary<long, JsonObject> pieces = new();
        private bool failed;
        private int memberCount;
        private void Bound(string peer, string key, long current)
        {
            if (peer != peerId || key != publicKey || current != generation)
                throw new InvalidOperationException("Content scope connection changed.");
        }

        internal JsonObject? Receive(string peer, string key, long current, JsonObject part)
        {
            Bound(peer, key, current);
            if (failed) throw new InvalidDataException("Scope session failed.");
            try
            {
                ValidatePart(part);
                var shape = new JsonObject();
                foreach (var field in new[] { "format", "epoch", "revision", "scope_hash", "parts" }) shape[field] = part[field]!.DeepClone();
                if (header is not null)
                {
                    if (Number(shape, "revision") < Number(header, "revision")) return null;
                    if (Number(shape, "revision") == Number(header, "revision") && !JsonNode.DeepEquals(shape, header) ||
                        Number(shape, "revision") > Number(header, "revision") && Text(shape, "epoch") == Text(header, "epoch"))
                        throw new InvalidDataException("Conflicting scope generation.");
                }
                if (!JsonNode.DeepEquals(header, shape))
                { header = shape; pieces.Clear(); manifest = null; memberCount = 0; }
                var index = Number(part, "part");
                if (pieces.TryGetValue(index, out var previous))
                {
                    if (!JsonNode.DeepEquals(previous, part)) throw new InvalidDataException("Conflicting scope replay.");
                }
                else
                {
                    memberCount += part["members"]!.AsArray().Count;
                    if (memberCount > MaximumMembers) throw new InvalidDataException("Scope session too large.");
                    pieces[index] = part.DeepClone().AsObject();
                }
                if (pieces.Count == Number(shape, "parts")) manifest = Assemble(pieces.Values);
                return manifest?.DeepClone().AsObject();
            }
            catch { failed = true; manifest = null; pieces.Clear(); memberCount = 0; throw; }
        }

        internal JsonObject Current(string peer, string key, long current, JsonObject claimed)
        {
            Bound(peer, key, current);
            if (failed || manifest is null) throw new InvalidOperationException("Scope is not current on this connection.");
            RequireCurrent(claimed, manifest);
            return manifest.DeepClone().AsObject();
        }
    }
}
