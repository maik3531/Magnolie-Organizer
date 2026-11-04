using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Pure source settings metadata, never native grants, media READ or workers.
internal sealed record DeviceFileSourceRequest(string RequestId, string Operation, string? ExpectedVersion, bool? Enabled,
    IReadOnlyList<string> Kinds, string? CatalogId = null, int After = 0,
    string? AlbumId = null, bool? DesktopChoice = null, string? RunId = null, string MediaType = "images",
    string? OriginalJobId = null, string? OriginalJobVersion = null);
internal sealed record DeviceFileSourceStatus(string RequestId, string Operation, string Version, long Revision,
    bool Enabled, bool Associated, bool RepairPending, IReadOnlyList<string> Kinds, DeviceFileSourceVideoStatus? Videos = null);
internal sealed record DeviceFileSourceVideoStatus(bool Enabled, long Revision)
{
    internal bool GrantsReadAuthority => false;
}
internal sealed record DeviceFileAlbumMetadata(string AlbumId, string Kind, string DisplayName, long VisibleImages, bool NeedsChoice);
internal sealed record DeviceFileCatalogPage(string CatalogId, int After, int? NextCursor, string Coverage, IReadOnlyList<DeviceFileAlbumMetadata> Albums, string MediaType = "images");
internal sealed record DeviceFilePermissionResult(string RequestId, string Version, string State, string MediaType = "images");
internal sealed record DeviceFileRunResult(string RequestId, string Operation, string Version, string RunId, string State, bool SourceIoEnded,
    string? OfferId = null, string? ManifestSha256 = null, string MediaType = "images");
internal sealed record DeviceFileMediaEntry(string FileId, string PhotoId, string MediaKind);
internal sealed record DeviceFileMediaPage(string RequestId, string Version, string RunId, string ManifestSha256, string SourceEpoch,
    string MediaType, bool InsertionWitness, int After, int? NextCursor, int TotalFiles, IReadOnlyList<DeviceFileMediaEntry> Entries)
{
    internal bool GrantsWriteAuthority => false;
    internal bool IsSavedReceipt => false;
}

internal static class DeviceFileSources
{
    internal const string RequestKind = "file_transfer.sources.request";
    internal const string ResultKind = "file_transfer.sources.result";
    internal const string CatalogKind = "file_transfer.sources.catalog";
    internal const string PermissionResultKind = "file_transfer.sources.permission_result";
    internal const string RunResultKind = "file_transfer.sources.run_result";
    internal const string MediaKind = "file_transfer.sources.media";
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
    private static bool ScopedOperation(string operation) => operation is "discover" or "catalog_page" or "request_read" or
        "run" or "run_status" or "cancel_run" or "offer_run" or "media_page" or "resume_run";
    private static JsonObject ScopedBody(JsonObject message, string kind, long now, string expectedMediaType)
    {
        if (expectedMediaType is not ("images" or "video")) throw Error();
        var body = Body(message, kind, now);
        if (expectedMediaType == "images")
        {
            if (body.ContainsKey("media_type")) throw Error();
            return body;
        }
        if (Text(body, "media_type") != "video") throw Error();
        var copy = body.DeepClone().AsObject(); copy.Remove("media_type");
        return copy;
    }
    internal static DeviceFileSourceRequest ParseRequest(JsonObject message, long now)
    {
        var body = Body(message, RequestKind, now); var operation = Text(body, "operation");
        if (body.ContainsKey("media_type"))
        {
            if (!ScopedOperation(operation) || Text(body, "media_type") != "video") throw Error();
            var unscoped = message.DeepClone().AsObject(); unscoped["body"]!.AsObject().Remove("media_type");
            return ParseRequest(unscoped, now) with { MediaType = "video" };
        }
        if (operation == "resume_run")
        {
            Exact(body, "format", "operation", "expected_version", "catalog_id", "album_id", "desktop_choice", "original_job_id", "original_job_version");
            var expected = Text(body, "expected_version"); var catalog = Text(body, "catalog_id"); var album = Text(body, "album_id");
            var choice = Flag(body, "desktop_choice"); var original = Text(body, "original_job_id"); var originalVersion = Text(body, "original_job_version");
            if (!DeviceFileControl.Hash(expected) || !TelefonProtocolContract.IsUuidV4(catalog) || !TelefonProtocolContract.IsUuidV4(album) ||
                !Regex.IsMatch(original, "\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant) || !DeviceFileControl.Hash(originalVersion)) throw Error();
            return new(Text(message, "message_id"), operation, expected, null, Array.Empty<string>(), catalog,
                AlbumId: album, DesktopChoice: choice, OriginalJobId: original, OriginalJobVersion: originalVersion);
        }
        if (operation == "media_page")
        {
            Exact(body, "format", "operation", "expected_version", "run_id", "after");
            var expected = Text(body, "expected_version"); var run = Text(body, "run_id"); var after = Number(body, "after");
            if (!DeviceFileControl.Hash(expected) || !TelefonProtocolContract.IsUuidV4(run) || after is < 0 or > 128) throw Error();
            return new(Text(message, "message_id"), operation, expected, null, Array.Empty<string>(), After: (int)after, RunId: run);
        }
        if (operation is "run" or "run_status" or "cancel_run" or "offer_run")
        {
            Exact(body, operation == "run" ? ["format", "operation", "expected_version", "catalog_id", "album_id", "desktop_choice"] :
                ["format", "operation", "expected_version", "run_id"]);
            var expected = Text(body, "expected_version");
            if (!DeviceFileControl.Hash(expected)) throw Error();
            if (operation == "run")
            {
                var catalog = Text(body, "catalog_id"); var album = Text(body, "album_id"); var choice = Flag(body, "desktop_choice");
                if (!TelefonProtocolContract.IsUuidV4(catalog) || !TelefonProtocolContract.IsUuidV4(album)) throw Error();
                return new(Text(message, "message_id"), operation, expected, null, Array.Empty<string>(), catalog, AlbumId: album, DesktopChoice: choice);
            }
            var run = Text(body, "run_id");
            if (!TelefonProtocolContract.IsUuidV4(run)) throw Error();
            return new(Text(message, "message_id"), operation, expected, null, Array.Empty<string>(), RunId: run);
        }
        if (operation == "status")
        {
            Exact(body, "format", "operation");
            return new(Text(message, "message_id"), operation, null, null, Array.Empty<string>());
        }
        if (operation is "discover" or "catalog_page" or "request_read")
        {
            Exact(body, operation != "catalog_page" ? ["format", "operation", "expected_version"] : ["format", "operation", "expected_version", "catalog_id", "after"]);
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
        if (operation == "configure_videos")
        {
            Exact(body, "format", "operation", "expected_version", "enabled");
            var expected = Text(body, "expected_version"); var videoEnabled = Flag(body, "enabled");
            if (!DeviceFileControl.Hash(expected)) throw Error();
            return new(Text(message, "message_id"), operation, expected, videoEnabled, Array.Empty<string>());
        }
        Exact(body, "format", "operation", "expected_version", "enabled", "kinds");
        var version = Text(body, "expected_version"); var enabled = Flag(body, "enabled"); var kinds = Selection(body["kinds"]);
        if (operation != "configure" || !DeviceFileControl.Hash(version) || enabled && kinds.Count == 0) throw Error();
        return new(Text(message, "message_id"), operation, version, enabled, kinds);
    }
    internal static JsonObject CreateRequest(string operation, long now, string? expectedVersion = null, bool? enabled = null,
        IEnumerable<string>? kinds = null, string? messageId = null, string? catalogId = null, int? after = null,
        string? albumId = null, bool? desktopChoice = null, string? runId = null, string mediaType = "images",
        string? originalJobId = null, string? originalJobVersion = null)
    {
        if (now is < 0 or > 253402300739999) throw Error();
        if (mediaType is not ("images" or "video") || mediaType == "video" && !ScopedOperation(operation)) throw Error();
        var body = new JsonObject { ["format"] = 1, ["operation"] = operation };
        if (operation is not ("run" or "run_status" or "cancel_run" or "offer_run" or "media_page" or "resume_run") && (albumId is not null || desktopChoice is not null || runId is not null)) throw Error();
        if (operation != "resume_run" && (originalJobId is not null || originalJobVersion is not null)) throw Error();
        if (operation == "resume_run")
        {
            if (enabled is not null || kinds is not null || after is not null || runId is not null) throw Error();
            body["expected_version"] = expectedVersion; body["catalog_id"] = catalogId; body["album_id"] = albumId;
            body["desktop_choice"] = desktopChoice; body["original_job_id"] = originalJobId; body["original_job_version"] = originalJobVersion;
        }
        else if (operation == "media_page")
        {
            if (enabled is not null || kinds is not null || catalogId is not null || albumId is not null || desktopChoice is not null) throw Error();
            body["expected_version"] = expectedVersion; body["run_id"] = runId; body["after"] = after;
        }
        else if (operation is "run" or "run_status" or "cancel_run" or "offer_run")
        {
            if (enabled is not null || kinds is not null || after is not null) throw Error();
            body["expected_version"] = expectedVersion;
            if (operation == "run")
            {
                if (runId is not null) throw Error();
                body["catalog_id"] = catalogId; body["album_id"] = albumId; body["desktop_choice"] = desktopChoice;
            }
            else
            {
                if (catalogId is not null || albumId is not null || desktopChoice is not null) throw Error();
                body["run_id"] = runId;
            }
        }
        else if (operation is "discover" or "catalog_page" or "request_read")
        {
            if (enabled is not null || kinds is not null || operation != "catalog_page" && (catalogId is not null || after is not null)) throw Error();
            body["expected_version"] = expectedVersion;
            if (operation == "catalog_page") { body["catalog_id"] = catalogId; body["after"] = after; }
        }
        else if (operation == "configure_videos")
        {
            if (catalogId is not null || after is not null || kinds is not null && kinds.Any()) throw Error();
            body["expected_version"] = expectedVersion; body["enabled"] = enabled;
        }
        else if (operation == "configure")
        {
            if (catalogId is not null || after is not null) throw Error();
            body["expected_version"] = expectedVersion; body["enabled"] = enabled;
            body["kinds"] = new JsonArray((kinds ?? []).Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
        }
        else if (expectedVersion is not null || enabled is not null || kinds is not null || catalogId is not null || after is not null) throw Error();
        if (mediaType == "video") body["media_type"] = "video";
        var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = messageId ?? Guid.NewGuid().ToString(),
            ["kind"] = RequestKind, ["created_ms"] = now, ["expires_ms"] = now + DeviceFileControl.MaximumTtlMs, ["body"] = body };
        ParseRequest(message, now); return message;
    }
    internal static DeviceFileSourceStatus ParseResult(JsonObject message, string expectedRequestId, string expectedOperation, long now, bool expectVideos = false)
    {
        var body = Body(message, ResultKind, now);
        DeviceFileSourceVideoStatus? videos = null;
        if (body.ContainsKey("videos"))
        {
            if (!expectVideos || body["videos"] is not JsonObject video) throw Error();
            Exact(video, "enabled", "revision");
            var enabledVideo = Flag(video, "enabled"); var revisionVideo = Number(video, "revision");
            if (revisionVideo is < 0 or > DeviceFileControl.MaximumRevision || revisionVideo == 0 && enabledVideo) throw Error();
            videos = new(enabledVideo, revisionVideo);
        }
        Exact(body, videos is null ? ["format", "request_id", "operation", "version", "revision", "enabled", "associated", "repair_pending", "kinds"] :
            ["format", "request_id", "operation", "version", "revision", "enabled", "associated", "repair_pending", "kinds", "videos"]);
        var id = Text(body, "request_id"); var operation = Text(body, "operation"); var version = Text(body, "version");
        var revision = Number(body, "revision"); var enabled = Flag(body, "enabled"); var associated = Flag(body, "associated");
        var repair = Flag(body, "repair_pending"); var kinds = Selection(body["kinds"]);
        if (!TelefonProtocolContract.IsUuidV4(id) || id != expectedRequestId || operation != expectedOperation ||
            operation is not ("status" or "configure" or "configure_videos") || !DeviceFileControl.Hash(version) || revision is < 0 or > DeviceFileControl.MaximumRevision ||
            enabled && kinds.Count == 0 || revision == 0 && (enabled || associated || kinds.Count != 0)) throw Error();
        return new(id, operation, version, revision, enabled, associated, repair, kinds, videos);
    }

    internal static DeviceFileCatalogPage ParseCatalog(JsonObject message, string expectedRequestId, string expectedOperation,
        string expectedVersion, long now, string? expectedCatalogId = null, int expectedAfter = 0, string expectedMediaType = "images")
    {
        var body = ScopedBody(message, CatalogKind, now, expectedMediaType);
        Exact(body, "format", "request_id", "operation", "version", "page");
        var requestId = Text(body, "request_id"); var operation = Text(body, "operation"); var version = Text(body, "version");
        if (!TelefonProtocolContract.IsUuidV4(requestId) || requestId != expectedRequestId || operation != expectedOperation ||
            operation is not ("discover" or "catalog_page") || !DeviceFileControl.Hash(version) || version != expectedVersion ||
            body["page"] is not JsonObject page || expectedAfter is < 0 or > 128) throw Error();
        Exact(page, "format", "catalog_id", "after", "next_cursor", "coverage", "proves_deletion", "albums");
        var catalogId = Text(page, "catalog_id"); var after = Number(page, "after"); var coverage = Text(page, "coverage");
        if (Number(page, "format") != 1 || !TelefonProtocolContract.IsUuidV4(catalogId) || after is < 0 or > 128 || after != expectedAfter ||
            Flag(page, "proves_deletion") || !(coverage is "none" or "selected_only" || coverage == (expectedMediaType == "video" ? "full_videos" : "full_images")) || page["albums"] is not JsonArray albums ||
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
        return new(catalogId, (int)after, next, coverage, result.AsReadOnly(), expectedMediaType);
    }

    internal static DeviceFilePermissionResult ParsePermissionResult(JsonObject message, string expectedRequestId, string expectedVersion, long now, string expectedMediaType = "images")
    {
        var body = ScopedBody(message, PermissionResultKind, now, expectedMediaType);
        Exact(body, "format", "request_id", "operation", "version", "state");
        var id = Text(body, "request_id"); var version = Text(body, "version"); var state = Text(body, "state");
        if (!TelefonProtocolContract.IsUuidV4(id) || id != expectedRequestId || Text(body, "operation") != "request_read" ||
            !DeviceFileControl.Hash(version) || version != expectedVersion || state is not ("requested" or "notification_posted" or "foreground_required" or "failed")) throw Error();
        return new(id, version, state, expectedMediaType);
    }

    internal static DeviceFileRunResult ParseRunResult(JsonObject message, string expectedRequestId, string expectedOperation,
        string expectedVersion, long now, string? expectedRunId = null, string expectedMediaType = "images")
    {
        var body = ScopedBody(message, RunResultKind, now, expectedMediaType);
        var id = Text(body, "request_id"); var operation = Text(body, "operation"); var version = Text(body, "version");
        Exact(body, operation == "offer_run" ?
            ["format", "request_id", "operation", "version", "run_id", "state", "source_io_ended", "offer_id", "manifest_sha256"] :
            ["format", "request_id", "operation", "version", "run_id", "state", "source_io_ended"]);
        var run = Text(body, "run_id"); var state = Text(body, "state"); var ended = Flag(body, "source_io_ended");
        var offer = operation == "offer_run" ? Text(body, "offer_id") : null;
        var manifest = operation == "offer_run" ? Text(body, "manifest_sha256") : null;
        if (!TelefonProtocolContract.IsUuidV4(id) || id != expectedRequestId || operation != expectedOperation ||
            operation is not ("run" or "run_status" or "cancel_run" or "offer_run") || !DeviceFileControl.Hash(version) || version != expectedVersion ||
            !TelefonProtocolContract.IsUuidV4(run) || operation != "run" && (!TelefonProtocolContract.IsUuidV4(expectedRunId) || run != expectedRunId) ||
            operation == "run" && expectedRunId is not null && run != expectedRunId ||
            state is not ("preparing" or "snapshot_ready" or "cancel_pending" or "canceled_held" or "failed_held") ||
            ended != (state is "snapshot_ready" or "canceled_held" or "failed_held") ||
            operation == "cancel_run" && state is not ("cancel_pending" or "canceled_held") ||
            operation == "offer_run" && (state != "snapshot_ready" || !TelefonProtocolContract.IsUuidV4(offer) || !DeviceFileControl.Hash(manifest))) throw Error();
        return new(id, operation, version, run, state, ended, offer, manifest, expectedMediaType);
    }

    internal static DeviceFileMediaPage ParseMediaPage(JsonObject message, string expectedRequestId, string expectedVersion,
        string expectedRunId, long now, int expectedAfter = 0, string? expectedManifestSha256 = null, string? expectedSourceEpoch = null,
        string? expectedMediaType = null)
    {
        var body = expectedMediaType is null ? Body(message, MediaKind, now) : ScopedBody(message, MediaKind, now, expectedMediaType);
        Exact(body, "format", "request_id", "operation", "version", "run_id", "page");
        var id = Text(body, "request_id"); var version = Text(body, "version"); var run = Text(body, "run_id");
        if (!TelefonProtocolContract.IsUuidV4(id) || id != expectedRequestId || Text(body, "operation") != "media_page" ||
            !DeviceFileControl.Hash(version) || version != expectedVersion || !TelefonProtocolContract.IsUuidV4(run) || run != expectedRunId ||
            body["page"] is not JsonObject page || expectedAfter is < 0 or > 128) throw Error();
        Exact(page, "format", "manifest_sha256", "source_epoch", "media_type", "insertion_witness", "after", "next_cursor", "total_files", "entries");
        var manifest = Text(page, "manifest_sha256"); var epoch = Text(page, "source_epoch"); var mediaType = Text(page, "media_type");
        var insertion = Flag(page, "insertion_witness"); var after = Number(page, "after"); var total = Number(page, "total_files");
        if (Number(page, "format") != 1 || !DeviceFileControl.Hash(manifest) || !DeviceFileControl.Hash(epoch) ||
            expectedManifestSha256 is not null && manifest != expectedManifestSha256 || expectedSourceEpoch is not null && epoch != expectedSourceEpoch ||
            mediaType is not ("images" or "video") || expectedMediaType is not null && mediaType != expectedMediaType ||
            total is < 1 or > 128 || after < 0 || after > total || after != expectedAfter ||
            page["entries"] is not JsonArray raw || raw.Count > 8 || raw.Count == 0 && after < total || after + raw.Count > total) throw Error();
        var end = after + raw.Count; int? next = null;
        if (page["next_cursor"] is not null)
        {
            var cursor = Number(page, "next_cursor");
            if (cursor is < 0 or > 128) throw Error();
            next = (int)cursor;
        }
        if (end < total ? next != end : next is not null) throw Error();
        var entries = new List<DeviceFileMediaEntry>(); var files = new HashSet<string>(StringComparer.Ordinal); var photos = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in raw)
        {
            if (item is not JsonObject entry) throw Error();
            Exact(entry, "file_id", "photo_id", "media_kind");
            var file = Text(entry, "file_id"); var photo = Text(entry, "photo_id"); var kind = Text(entry, "media_kind");
            if (!Regex.IsMatch(file, "\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant) || !DeviceFileControl.Hash(photo) ||
                (mediaType == "video" ? kind != "video" : kind is not ("image" or "animation" or "unknown_image")) || !files.Add(file) || !photos.Add(photo)) throw Error();
            entries.Add(new(file, photo, kind));
        }
        return new(id, version, run, manifest, epoch, mediaType, insertion, (int)after, next, (int)total, entries.AsReadOnly());
    }

    internal static IReadOnlyList<DeviceFileMediaEntry> CorrelateMediaPages(IReadOnlyList<DeviceFileMediaPage> pages, DeviceFileManifest manifest)
    {
        if (pages.Count == 0) throw Error();
        var first = pages[0]; int? cursor = 0; var entries = new List<DeviceFileMediaEntry>();
        foreach (var page in pages)
        {
            if (cursor is null || page.After != cursor || page.ManifestSha256 != manifest.Fingerprint || page.TotalFiles != manifest.Files.Count ||
                page.Version != first.Version || page.RunId != first.RunId || page.SourceEpoch != first.SourceEpoch ||
                page.MediaType != first.MediaType || page.InsertionWitness != first.InsertionWitness) throw Error();
            entries.AddRange(page.Entries); cursor = page.NextCursor;
        }
        if (cursor is not null || !entries.Select(entry => entry.FileId).SequenceEqual(manifest.Files.Select(file => file.Id)) ||
            entries.Select(entry => entry.PhotoId).Distinct(StringComparer.Ordinal).Count() != entries.Count) throw Error();
        return entries.AsReadOnly();
    }
}
