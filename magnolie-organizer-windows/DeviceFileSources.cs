using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Pure source settings metadata, never native grants, media READ or workers.
internal sealed record DeviceFileSourceRequest(string RequestId, string Operation, string? ExpectedVersion, bool? Enabled,
    IReadOnlyList<string> Kinds, string? CatalogId = null, int After = 0);
internal sealed record DeviceFileSourceStatus(string RequestId, string Operation, string Version, long Revision,
    bool Enabled, bool Associated, bool RepairPending, IReadOnlyList<string> Kinds);
internal sealed record DeviceFileAlbumMetadata(string AlbumId, string Kind, string DisplayName, long VisibleImages, bool NeedsChoice);
internal sealed record DeviceFileCatalogPage(string CatalogId, int After, int? NextCursor, string Coverage, IReadOnlyList<DeviceFileAlbumMetadata> Albums);

internal static class DeviceFileSources
{
    internal const string RequestKind = "file_transfer.sources.request";
    internal const string ResultKind = "file_transfer.sources.result";
    internal const string CatalogKind = "file_transfer.sources.catalog";
    private static readonly string[] Kinds = ["camera", "downloads", "screenshots", "whatsapp_received"];
    private static InvalidDataException Error() => new("file_sources_invalid_message");
    private static string Text(JsonObject value, string key) =>
        value[key] is JsonValue field && field.TryGetValue<string>(out var text) ? text : throw Error();
    private static bool Flag(JsonObject value, string key) =>
        value[key] is JsonValue field && field.TryGetValue<bool>(out var flag) ? flag : throw Error();
    private static long Number(JsonObject value, string key) =>
        TelefonProtocolContract.TryInteger(value[key], out var number) ? number : throw Error();
    private static void Exact(JsonObject value, params string[] keys)
    {
        if (!value.Select(item => item.Key).ToHashSet(StringComparer.Ordinal).SetEquals(keys)) throw Error();
    }
    private static IReadOnlyList<string> Selection(JsonNode? node)
    {
        if (node is not JsonArray values || values.Count > Kinds.Length) throw Error();
        var result = values.Select(value => value is JsonValue field && field.TryGetValue<string>(out var text) &&
            Kinds.Contains(text, StringComparer.Ordinal) ? text : throw Error()).ToArray();
        if (!result.SequenceEqual(result.Order(StringComparer.Ordinal).Distinct(StringComparer.Ordinal))) throw Error();
        return Array.AsReadOnly(result);
    }
    private static JsonObject Body(JsonObject message, string kind, long now)
    {
        Exact(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = Number(message, "created_ms"); var expires = Number(message, "expires_ms");
        if (now < 0 || Text(message, "type") != "message" || Number(message, "v") != 1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message, "message_id")) || Text(message, "kind") != kind ||
            created is < 0 or > 253402300799999 || expires <= created || expires - created > DeviceFileControl.MaximumTtlMs ||
            now >= expires || created - Math.Min(now, created) > 300000 ||
            TelefonCrypto.Canonical(message).Length > DeviceFileControl.MaximumWireBytes || message["body"] is not JsonObject body ||
            Number(body, "format") != 1) throw Error();
        return body;
    }
    internal static DeviceFileSourceRequest ParseRequest(JsonObject message, long now)
    {
        var body = Body(message, RequestKind, now); var operation = Text(body, "operation");
        if (operation == "status")
        {
            Exact(body, "format", "operation");
            return new(Text(message, "message_id"), operation, null, null, Array.Empty<string>());
        }
        if (operation is "discover" or "catalog_page")
        {
            Exact(body, operation == "discover" ? ["format", "operation", "expected_version"] : ["format", "operation", "expected_version", "catalog_id", "after"]);
            var expected = Text(body, "expected_version");
            if (!DeviceFileControl.Hash(expected)) throw Error();
            string? catalog = null; var after = 0L;
            if (operation == "catalog_page")
            {
                catalog = Text(body, "catalog_id"); after = Number(body, "after");
                if (!TelefonProtocolContract.IsUuidV4(catalog) || after is < 0 or > 128) throw Error();
            }
            return new(Text(message, "message_id"), operation, expected, null, Array.Empty<string>(), catalog, (int)after);
        }
        Exact(body, "format", "operation", "expected_version", "enabled", "kinds");
        var version = Text(body, "expected_version"); var enabled = Flag(body, "enabled"); var kinds = Selection(body["kinds"]);
        if (operation != "configure" || !DeviceFileControl.Hash(version) || enabled && kinds.Count == 0) throw Error();
        return new(Text(message, "message_id"), operation, version, enabled, kinds);
    }
    internal static JsonObject CreateRequest(string operation, long now, string? expectedVersion = null, bool? enabled = null,
        IEnumerable<string>? kinds = null, string? messageId = null, string? catalogId = null, int? after = null)
    {
        if (now is < 0 or > 253402300739999) throw Error();
        var body = new JsonObject { ["format"] = 1, ["operation"] = operation };
        if (operation is "discover" or "catalog_page")
        {
            if (enabled is not null || kinds is not null || operation == "discover" && (catalogId is not null || after is not null)) throw Error();
            body["expected_version"] = expectedVersion;
            if (operation == "catalog_page") { body["catalog_id"] = catalogId; body["after"] = after; }
        }
        else if (operation == "configure")
        {
            if (catalogId is not null || after is not null) throw Error();
            body["expected_version"] = expectedVersion; body["enabled"] = enabled;
            body["kinds"] = new JsonArray((kinds ?? []).Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        }
        else if (expectedVersion is not null || enabled is not null || kinds is not null || catalogId is not null || after is not null) throw Error();
        var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = messageId ?? Guid.NewGuid().ToString(),
            ["kind"] = RequestKind, ["created_ms"] = now, ["expires_ms"] = now + DeviceFileControl.MaximumTtlMs, ["body"] = body };
        ParseRequest(message, now); return message;
    }
    internal static DeviceFileSourceStatus ParseResult(JsonObject message, string expectedRequestId, string expectedOperation, long now)
    {
        var body = Body(message, ResultKind, now);
        Exact(body, "format", "request_id", "operation", "version", "revision", "enabled", "associated", "repair_pending", "kinds");
        var id = Text(body, "request_id"); var operation = Text(body, "operation"); var version = Text(body, "version");
        var revision = Number(body, "revision"); var enabled = Flag(body, "enabled"); var associated = Flag(body, "associated");
        var repair = Flag(body, "repair_pending"); var kinds = Selection(body["kinds"]);
        if (!TelefonProtocolContract.IsUuidV4(id) || id != expectedRequestId || operation != expectedOperation ||
            operation is not ("status" or "configure") || !DeviceFileControl.Hash(version) || revision is < 0 or > DeviceFileControl.MaximumRevision ||
            enabled && kinds.Count == 0 || revision == 0 && (enabled || associated || kinds.Count != 0)) throw Error();
        return new(id, operation, version, revision, enabled, associated, repair, kinds);
    }

    internal static DeviceFileCatalogPage ParseCatalog(JsonObject message, string expectedRequestId, string expectedOperation,
        string expectedVersion, long now, string? expectedCatalogId = null, int expectedAfter = 0)
    {
        var body = Body(message, CatalogKind, now);
        Exact(body, "format", "request_id", "operation", "version", "page");
        var requestId = Text(body, "request_id"); var operation = Text(body, "operation"); var version = Text(body, "version");
        if (!TelefonProtocolContract.IsUuidV4(requestId) || requestId != expectedRequestId || operation != expectedOperation ||
            operation is not ("discover" or "catalog_page") || !DeviceFileControl.Hash(version) || version != expectedVersion ||
            body["page"] is not JsonObject page || expectedAfter is < 0 or > 128) throw Error();
        Exact(page, "format", "catalog_id", "after", "next_cursor", "coverage", "proves_deletion", "albums");
        var catalogId = Text(page, "catalog_id"); var after = Number(page, "after"); var coverage = Text(page, "coverage");
        if (Number(page, "format") != 1 || !TelefonProtocolContract.IsUuidV4(catalogId) || after is < 0 or > 128 || after != expectedAfter ||
            Flag(page, "proves_deletion") || coverage is not ("none" or "selected_only" or "full_images") || page["albums"] is not JsonArray albums ||
            albums.Count + after > 128 || coverage == "none" && albums.Count != 0 ||
            operation == "catalog_page" && (!TelefonProtocolContract.IsUuidV4(expectedCatalogId) || catalogId != expectedCatalogId) ||
            operation == "discover" && (expectedCatalogId is not null || after != 0)) throw Error();
        int? next = null;
        if (page["next_cursor"] is not null)
        {
            var cursor = Number(page, "next_cursor");
            if (albums.Count == 0 || cursor != after + albums.Count || cursor > 128) throw Error();
            next = (int)cursor;
        }
        var result = new List<DeviceFileAlbumMetadata>(); var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var raw in albums)
        {
            if (raw is not JsonObject album) throw Error();
            Exact(album, "album_id", "kind", "display_name", "visible_images", "needs_choice");
            var id = Text(album, "album_id"); var kind = Text(album, "kind"); var label = Text(album, "display_name");
            var count = Number(album, "visible_images"); var choice = Flag(album, "needs_choice");
            if (!TelefonProtocolContract.IsUuidV4(id) || !ids.Add(id) || !Kinds.Contains(kind, StringComparer.Ordinal) ||
                label.Length is < 1 or > 256 || label.Any(character => character < 32 || character == 127) || count is < 0 or > 50000) throw Error();
            result.Add(new(id, kind, label, count, choice));
        }
        return new(catalogId, (int)after, next, coverage, result.AsReadOnly());
    }
}
