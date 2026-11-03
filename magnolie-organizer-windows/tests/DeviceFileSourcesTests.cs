using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSourcesTests
{
    internal static Task RunAsync()
    {
        const string relative = "contracts/file-transfer-sources-v1-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!.AsObject();
        var now = vector["now_ms"]!.GetValue<long>(); var golden = vector["configure"]!.AsObject();
        var command = DeviceFileSources.ParseRequest(golden, now);
        var made = DeviceFileSources.CreateRequest("configure", now, new string('a', 64), true, ["camera", "screenshots"], command.RequestId);
        var bytes = TelefonCrypto.Canonical(made);
        TestAssert.That(bytes.SequenceEqual(TelefonCrypto.Canonical(golden)) && bytes.Length == vector["canonical_bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == vector["canonical_sha256"]!.GetValue<string>(), "Source command golden mismatch.");
        TestAssert.That(DeviceFileSources.ParseRequest(DeviceFileSources.CreateRequest("status", now), now).Operation == "status", "Status codec failed.");
        foreach (var (key, value) in new (string, JsonNode?)[] { ("enabled", JsonValue.Create(1)), ("enabled", JsonValue.Create("true")),
            ("format", JsonValue.Create(true)), ("expected_version", JsonValue.Create("absent")), ("send_files", JsonValue.Create(true)),
            ("automatic", JsonValue.Create(true)), ("read_granted", JsonValue.Create(true)), ("path", JsonValue.Create("/private")),
            ("kinds", new JsonArray("camera", "camera")), ("kinds", new JsonArray("screenshots", "camera")), ("kinds", new JsonArray()) })
        {
            var invalid = (JsonObject)golden.DeepClone(); invalid["body"]!.AsObject()[key] = value;
            TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(invalid, now), "Source command alias/extra authority accepted.");
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(golden, now + 60000), "Expired source command accepted.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CreateRequest("run", now), "Unsupported run accepted.");
        var reply = (JsonObject)golden.DeepClone(); reply["kind"] = DeviceFileSources.ResultKind;
        reply["body"] = new JsonObject { ["format"] = 1, ["request_id"] = command.RequestId, ["operation"] = "configure", ["version"] = new string('b', 64),
            ["revision"] = 2, ["enabled"] = true, ["associated"] = true, ["repair_pending"] = false, ["kinds"] = new JsonArray("camera") };
        var status = DeviceFileSources.ParseResult(reply, command.RequestId, "configure", now);
        TestAssert.That(status.Enabled && status.Associated && status.Kinds.SequenceEqual(["camera"]), "Correlated source result rejected.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseResult(reply, Guid.NewGuid().ToString(), "configure", now), "Wrong request result accepted.");
        reply["body"]!.AsObject()["revision"] = true;
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseResult(reply, command.RequestId, "configure", now), "Boolean revision accepted.");
        var discover = DeviceFileSources.CreateRequest("discover", now, new string('a', 64));
        TestAssert.That(DeviceFileSources.ParseRequest(discover, now).Operation == "discover", "Discovery request rejected.");
        const string catalogId = "22222222-2222-4222-8222-222222222222";
        var pageRequest = DeviceFileSources.CreateRequest("catalog_page", now, new string('a', 64), catalogId: catalogId, after: 1);
        TestAssert.That(DeviceFileSources.ParseRequest(pageRequest, now).After == 1, "Paging request rejected.");
        pageRequest["body"]!.AsObject()["after"] = true;
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(pageRequest, now), "Boolean catalog cursor accepted.");
        var catalog = (JsonObject)discover.DeepClone(); catalog["kind"] = DeviceFileSources.CatalogKind;
        catalog["body"] = new JsonObject { ["format"] = 1, ["request_id"] = discover["message_id"]!.DeepClone(), ["operation"] = "discover",
            ["version"] = new string('a', 64), ["page"] = new JsonObject { ["format"] = 1, ["catalog_id"] = catalogId, ["after"] = 0,
                ["next_cursor"] = null, ["coverage"] = "full_images", ["proves_deletion"] = false, ["albums"] = new JsonArray(new JsonObject {
                    ["album_id"] = "33333333-3333-4333-8333-333333333333", ["kind"] = "camera", ["display_name"] = "Camera",
                    ["visible_images"] = 3, ["needs_choice"] = false }) } };
        DeviceFileCatalogPage ReadCatalog(JsonObject value) => DeviceFileSources.ParseCatalog(value, discover["message_id"]!.GetValue<string>(), "discover", new string('a', 64), now);
        TestAssert.That(ReadCatalog(catalog).Albums.Single().DisplayName == "Camera", "Native album metadata rejected.");
        foreach (var (key, value) in new (string, JsonNode?)[] { ("proves_deletion", JsonValue.Create(true)), ("proves_deletion", JsonValue.Create(0)),
            ("next_cursor", JsonValue.Create(0)), ("next_cursor", JsonValue.Create(2)), ("after", JsonValue.Create(true)), ("path", JsonValue.Create("/private")) })
        {
            var invalid = (JsonObject)catalog.DeepClone(); invalid["body"]!["page"]!.AsObject()[key] = value;
            TestAssert.Throws<InvalidDataException>(() => ReadCatalog(invalid), "Invalid catalog scope/deletion metadata accepted.");
        }
        var duplicates = (JsonObject)catalog.DeepClone(); var entries = duplicates["body"]!["page"]!["albums"]!.AsArray(); entries.Add(entries[0]!.DeepClone());
        TestAssert.Throws<InvalidDataException>(() => ReadCatalog(duplicates), "Duplicate native album IDs accepted.");
        var read = DeviceFileSources.CreateRequest("request_read", now, new string('a', 64));
        TestAssert.That(DeviceFileSources.ParseRequest(read, now).Operation == "request_read", "Explicit native UI request rejected.");
        var permission = (JsonObject)read.DeepClone(); permission["kind"] = DeviceFileSources.PermissionResultKind;
        permission["body"] = new JsonObject { ["format"] = 1, ["request_id"] = read["message_id"]!.DeepClone(), ["operation"] = "request_read",
            ["version"] = new string('a', 64), ["state"] = "foreground_required" };
        DeviceFilePermissionResult ReadPermission(JsonObject value) => DeviceFileSources.ParsePermissionResult(value, read["message_id"]!.GetValue<string>(), new string('a', 64), now);
        TestAssert.That(ReadPermission(permission).State == "foreground_required", "Native foreground-pending result rejected.");
        foreach (var (key, value) in new (string, JsonNode?)[] { ("read_granted", JsonValue.Create(true)), ("state", JsonValue.Create("granted")),
            ("version", JsonValue.Create(new string('b', 64))), ("state", JsonValue.Create(true)) })
        {
            var invalid = (JsonObject)permission.DeepClone(); invalid["body"]!.AsObject()[key] = value;
            TestAssert.Throws<InvalidDataException>(() => ReadPermission(invalid), "Permission UI metadata became authority or mismatched state.");
        }
        var runRequest = DeviceFileSources.CreateRequest("run", now, new string('a',64), catalogId: catalogId,
            albumId: "33333333-3333-4333-8333-333333333333", desktopChoice: true);
        TestAssert.That(DeviceFileSources.ParseRequest(runRequest, now).DesktopChoice == true, "Exact native album start rejected.");
        const string runId = "44444444-4444-4444-8444-444444444444";
        var runReply = (JsonObject)runRequest.DeepClone(); runReply["kind"] = DeviceFileSources.RunResultKind;
        runReply["body"] = new JsonObject { ["format"] = 1, ["request_id"] = runRequest["message_id"]!.DeepClone(), ["operation"] = "run",
            ["version"] = new string('a',64), ["run_id"] = runId, ["state"] = "preparing", ["source_io_ended"] = false };
        DeviceFileRunResult ReadRun(JsonObject value) => DeviceFileSources.ParseRunResult(value, runRequest["message_id"]!.GetValue<string>(), "run", new string('a',64), now);
        TestAssert.That(ReadRun(runReply).RunId == runId, "Correlated source preparation state rejected.");
        foreach (var (key,value) in new (string,JsonNode?)[] { ("success",JsonValue.Create(true)), ("quota_retired",JsonValue.Create(true)),
            ("state",JsonValue.Create("success")), ("source_io_ended",JsonValue.Create(true)), ("source_io_ended",JsonValue.Create(1)) })
        {
            var invalid=(JsonObject)runReply.DeepClone(); invalid["body"]!.AsObject()[key]=value;
            TestAssert.Throws<InvalidDataException>(() => ReadRun(invalid), "Run metadata became sync success/false END.");
        }
        var offerRequest = DeviceFileSources.CreateRequest("offer_run", now, new string('a',64), runId: runId);
        TestAssert.That(DeviceFileSources.ParseRequest(offerRequest, now).RunId == runId, "Offer command lost native run correlation.");
        var offerReply = (JsonObject)offerRequest.DeepClone(); offerReply["kind"] = DeviceFileSources.RunResultKind;
        var offerId = Guid.NewGuid().ToString();
        offerReply["body"] = new JsonObject { ["format"] = 1, ["request_id"] = offerRequest["message_id"]!.DeepClone(),
            ["operation"] = "offer_run", ["version"] = new string('a',64), ["run_id"] = runId,
            ["state"] = "snapshot_ready", ["source_io_ended"] = true, ["offer_id"] = offerId, ["manifest_sha256"] = new string('b',64) };
        DeviceFileRunResult ReadOffer(JsonObject value) => DeviceFileSources.ParseRunResult(value,
            offerRequest["message_id"]!.GetValue<string>(), "offer_run", new string('a',64), now, runId);
        TestAssert.That(ReadOffer(offerReply).OfferId == offerId && ReadOffer(offerReply).ManifestSha256 == new string('b',64), "Offer output metadata lost correlation.");
        foreach (var (key,value) in new (string,JsonNode?)[] { ("offer_id",JsonValue.Create("path")),
            ("manifest_sha256",JsonValue.Create(new string('B',64))), ("state",JsonValue.Create("preparing")),
            ("state",JsonValue.Create("failed_held")), ("source_io_ended",JsonValue.Create(false)),
            ("source_io_ended",JsonValue.Create(1)), ("success",JsonValue.Create(true)),
            ("run_id",JsonValue.Create(Guid.NewGuid().ToString())), ("version",JsonValue.Create(new string('c',64))),
            ("request_id",JsonValue.Create(Guid.NewGuid().ToString())), ("operation",JsonValue.Create("run_status")) })
        {
            var invalid=(JsonObject)offerReply.DeepClone(); invalid["body"]!.AsObject()[key]=value;
            TestAssert.Throws<InvalidDataException>(() => ReadOffer(invalid), "Invalid offer result accepted.");
        }
        foreach (var key in new[] { "offer_id", "manifest_sha256" })
        {
            var invalid=(JsonObject)offerReply.DeepClone(); invalid["body"]!.AsObject().Remove(key);
            TestAssert.Throws<InvalidDataException>(() => ReadOffer(invalid), "Incomplete offer result accepted.");
            var other=(JsonObject)runReply.DeepClone(); other["body"]!.AsObject()[key]=offerReply["body"]![key]!.DeepClone();
            TestAssert.Throws<InvalidDataException>(() => ReadRun(other), "Offer-only fields accepted on another operation.");
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRunResult(offerReply,
            offerRequest["message_id"]!.GetValue<string>(), "offer_run", new string('a',64), now+60000, runId), "Expired offer result accepted.");
        const string mediaVectorPath = "contracts/file-transfer-media-v1-vectors.json";
        var mediaVector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(mediaVectorPath), mediaVectorPath)))!.AsObject();
        var mediaGolden = mediaVector["request"]!.AsObject();
        var mediaCommand = DeviceFileSources.CreateRequest("media_page", now, new string('a',64),
            messageId: mediaGolden["message_id"]!.GetValue<string>(), runId: "33333333-3333-4333-8333-333333333333", after: 0);
        var mediaBytes = TelefonCrypto.Canonical(mediaCommand);
        TestAssert.That(mediaBytes.SequenceEqual(TelefonCrypto.Canonical(mediaGolden)) && mediaBytes.Length == mediaVector["canonical_bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(mediaBytes)).ToLowerInvariant() == mediaVector["canonical_sha256"]!.GetValue<string>(), "Media page command golden mismatch.");
        DeviceFileManifest MediaManifest(int count) => new(new string('1',32), new string('2',32), "sender_fixture_01", "receiver_fixture_01",
            Enumerable.Range(0,count).Select(index => new DeviceManifestFile((index+1).ToString("x32"), $"image{index}.jpg", 1,
                Convert.ToHexString(SHA256.HashData(new byte[] {120})).ToLowerInvariant())).ToArray(), count);
        JsonObject MediaMessage(int count = 1, int after = 0)
        {
            var full = MediaManifest(count); var end = Math.Min(after+8,count);
            var value = DeviceFileSources.CreateRequest("media_page", now, new string('a',64), runId: runId, after: after);
            var requestId = value["message_id"]!.DeepClone(); value["kind"] = DeviceFileSources.MediaKind;
            value["body"] = new JsonObject { ["format"] = 1, ["request_id"] = requestId, ["operation"] = "media_page",
                ["version"] = new string('a',64), ["run_id"] = runId, ["page"] = new JsonObject {
                    ["format"] = 1, ["manifest_sha256"] = full.Fingerprint, ["source_epoch"] = new string('b',64),
                    ["media_type"] = "images", ["insertion_witness"] = true, ["after"] = after, ["next_cursor"] = end<count ? JsonValue.Create(end) : null,
                    ["total_files"] = count, ["entries"] = new JsonArray(Enumerable.Range(after,end-after).Select(index => (JsonNode?)new JsonObject {
                        ["file_id"] = full.Files[index].Id, ["photo_id"] = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"photo-{index}"))).ToLowerInvariant(),
                        ["media_kind"] = "image" }).ToArray()) } };
            return value;
        }
        DeviceFileMediaPage ReadMedia(JsonObject value, int after = 0) => DeviceFileSources.ParseMediaPage(value,
            value["body"]!["request_id"]!.GetValue<string>(), new string('a',64), runId, now, after);
        var media = ReadMedia(MediaMessage());
        TestAssert.That(!media.GrantsWriteAuthority && !media.IsSavedReceipt &&
            DeviceFileSources.CorrelateMediaPages([media],MediaManifest(1)).Count == 1, "Media metadata became authority or lost full manifest correlation.");
        foreach (var (key,value) in new (string,JsonNode?)[] { ("format",JsonValue.Create(true)), ("after",JsonValue.Create(true)),
            ("after",JsonValue.Create(1)), ("total_files",JsonValue.Create(0)), ("total_files",JsonValue.Create(129)),
            ("next_cursor",JsonValue.Create(1)), ("next_cursor",JsonValue.Create(true)), ("insertion_witness",JsonValue.Create(1)),
            ("source_epoch",JsonValue.Create("native-row-id")), ("manifest_sha256",JsonValue.Create(new string('A',64))),
            ("media_type",JsonValue.Create("photos")), ("read_granted",JsonValue.Create(true)), ("entries",new JsonArray()) })
        {
            var invalid=MediaMessage();invalid["body"]!["page"]!.AsObject()[key]=value;
            TestAssert.Throws<InvalidDataException>(() => ReadMedia(invalid), "Invalid bounded media page accepted.");
        }
        foreach (var (key,value) in new (string,JsonNode?)[] { ("file_id",JsonValue.Create("path")), ("photo_id",JsonValue.Create("raw-row-id")),
            ("media_kind",JsonValue.Create("video")), ("native_member",JsonValue.Create("123:456")), ("camera_origin_proven",JsonValue.Create(true)) })
        {
            var invalid=MediaMessage();invalid["body"]!["page"]!["entries"]![0]!.AsObject()[key]=value;
            TestAssert.Throws<InvalidDataException>(() => ReadMedia(invalid), "Media member adopted raw identity, video or camera claims.");
        }
        var firstMedia=ReadMedia(MediaMessage(9));var lastMedia=ReadMedia(MediaMessage(9,8),8);
        TestAssert.That(DeviceFileSources.CorrelateMediaPages([firstMedia,lastMedia],MediaManifest(9)).Count==9, "Complete media paging rejected.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CorrelateMediaPages([firstMedia],MediaManifest(9)), "Partial media page treated as complete.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CorrelateMediaPages([lastMedia,firstMedia],MediaManifest(9)), "Out-of-order media pages accepted.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CorrelateMediaPages([firstMedia,lastMedia with { SourceEpoch=new string('c',64) }],MediaManifest(9)), "Source namespace changed across media pages.");
        var duplicate=lastMedia with { Entries=Array.AsReadOnly(new[] { lastMedia.Entries[0] with { PhotoId=firstMedia.Entries[0].PhotoId } }) };
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CorrelateMediaPages([firstMedia,duplicate],MediaManifest(9)), "Duplicate opaque photo identity across pages accepted.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseMediaPage(MediaMessage(),Guid.NewGuid().ToString(),new string('a',64),runId,now), "Wrong media request accepted.");
        var expiring=MediaMessage();
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseMediaPage(expiring,expiring["body"]!["request_id"]!.GetValue<string>(),new string('a',64),runId,now+60000), "Expired media result accepted.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseMediaPage(expiring,expiring["body"]!["request_id"]!.GetValue<string>(),new string('a',64),runId,now,expectedManifestSha256:new string('c',64)), "Wrong expected media manifest accepted.");
        var invalidMediaRequest=(JsonObject)mediaGolden.DeepClone();invalidMediaRequest["body"]!["after"]=true;
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(invalidMediaRequest,now), "Boolean native media cursor accepted.");
        return Task.CompletedTask;
    }
}
