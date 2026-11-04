using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileVideoSourceMetadataTests
{
    internal static Task CodecAsync()
    {
        const string relative = "contracts/file-transfer-video-sources-v1-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!.AsObject();
        var now = vector["now_ms"]!.GetValue<long>(); var golden = vector["commands"]![0]!.AsObject();
        var command = DeviceFileSources.ParseRequest(golden, now);
        var made = DeviceFileSources.CreateRequest("configure_videos", now, new string('a', 64), true, messageId: command.RequestId);
        var bytes = TelefonCrypto.Canonical(made);
        TestAssert.That(bytes.SequenceEqual(TelefonCrypto.Canonical(golden)) &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == vector["canonical_sha256"]![0]!.GetValue<string>() &&
            command.Kinds.Count == 0 && command.Enabled == true, "Native video-config metadata differs from the shared Python/Notes vector.");
        foreach (var mutate in new Action<JsonObject>[] {
            value => value["body"]!["enabled"] = 1, value => value["body"]!["enabled"] = "true",
            value => value["body"]!["expected_version"] = "absent", value => value["body"]!["kinds"] = new JsonArray(),
            value => value["body"]!["media_type"] = "video", value => value["body"]!["path"] = "/private",
            value => value["body"]!["read_granted"] = true })
        {
            var changed = golden.DeepClone().AsObject(); mutate(changed);
            TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(changed, now), "Video-config metadata accepted aliases or extra authority.");
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CreateRequest("configure_videos", now, new string('a', 64), true, ["camera"]), "Video configuration rewrote image-kind selection.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CreateRequest("configure_videos", now, new string('a', 64), true, after: 0), "Video configuration accepted paging scope.");
        TestAssert.That(DeviceFileSources.ParseRequest(DeviceFileSources.CreateRequest("configure_videos", now, new string('a', 64), false), now).Enabled == false, "Explicit video OFF metadata failed.");
        return Task.CompletedTask;
    }

    internal static Task StatusCodecAsync()
    {
        var request = DeviceFileSources.CreateRequest("status", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        var reply = DeviceFileConnectionSourcesTests.Reply(request); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var id = request["message_id"]!.GetValue<string>();
        reply["body"]!["videos"] = new JsonObject { ["enabled"] = true, ["revision"] = 1 };
        var original = reply.ToJsonString();
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseResult(reply, id, "status", now), "Unnegotiated video extension accepted.");
        var status = DeviceFileSources.ParseResult(reply, id, "status", now, expectVideos: true);
        TestAssert.That(status.Videos is { Enabled: true, Revision: 1, GrantsReadAuthority: false } && !status.Enabled && status.Kinds.Count == 0,
            "Video metadata became READ or overwrote independent image settings.");
        TestAssert.That(reply.ToJsonString() == original, "Status parsing rewrote the authenticated reply.");
        foreach (var value in new JsonNode?[] { null, JsonValue.Create(true),
            new JsonObject { ["enabled"] = 1, ["revision"] = 1 }, new JsonObject { ["enabled"] = true, ["revision"] = 0 },
            new JsonObject { ["enabled"] = false, ["revision"] = -1 }, new JsonObject { ["enabled"] = false, ["revision"] = true },
            new JsonObject { ["enabled"] = false, ["revision"] = DeviceFileControl.MaximumRevision + 1 },
            new JsonObject { ["enabled"] = true, ["revision"] = 1, ["read_granted"] = true } })
        {
            var changed = reply.DeepClone().AsObject(); changed["body"]!["videos"] = value;
            TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseResult(changed, id, "status", now, true), "Invalid video counters or READ alias accepted.");
        }
        reply["body"]!["videos"] = new JsonObject { ["enabled"] = false, ["revision"] = 0 };
        TestAssert.That(DeviceFileSources.ParseResult(reply, id, "status", now, true).Videos is { Enabled: false, Revision: 0 }, "Initial video OFF metadata rejected.");
        reply["body"]!.AsObject().Remove("videos");
        TestAssert.That(DeviceFileSources.ParseResult(reply, id, "status", now, true).Videos is null, "Absent video status was invented.");
        return Task.CompletedTask;
    }

    internal static Task ScopedCommandsAsync()
    {
        const string relative = "contracts/file-transfer-video-sources-v1-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!.AsObject();
        var now = vector["now_ms"]!.GetValue<long>();
        foreach (var index in new[] { 1, 2, 3, 4 })
        {
            var golden = vector["commands"]![index]!.AsObject(); var original = golden.ToJsonString();
            var parsed = DeviceFileSources.ParseRequest(golden, now);
            var made = DeviceFileSources.CreateRequest(parsed.Operation, now, parsed.ExpectedVersion,
                messageId: parsed.RequestId, catalogId: parsed.CatalogId, albumId: parsed.AlbumId,
                desktopChoice: parsed.DesktopChoice, runId: parsed.RunId,
                after: parsed.Operation == "media_page" ? parsed.After : null, mediaType: "video",
                originalJobId: parsed.OriginalJobId, originalJobVersion: parsed.OriginalJobVersion);
            TestAssert.That(parsed.MediaType == "video" && TelefonCrypto.Canonical(made).SequenceEqual(TelefonCrypto.Canonical(golden)) &&
                Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(made))).ToLowerInvariant() == vector["canonical_sha256"]![index]!.GetValue<string>() &&
                golden.ToJsonString() == original, "Typed video command lost canonical bytes or rewrote input.");
            foreach (var scope in new JsonNode[] { JsonValue.Create("images")!, JsonValue.Create("videos")!, JsonValue.Create(true)! })
            {
                var wrong = golden.DeepClone().AsObject(); wrong["body"]!["media_type"] = scope;
                TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(wrong, now), "Video scope alias was inferred or coerced.");
            }
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CreateRequest("status", now, mediaType: "video"), "Video scope replaced status negotiation.");
        var resume = vector["commands"]![3]!.DeepClone().AsObject();
        foreach (var key in new[] { "original_job_id", "original_job_version" })
        {
            var missing = resume.DeepClone().AsObject(); missing["body"]!.AsObject().Remove(key);
            TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(missing, now), "Resume lost its exact original job witness.");
        }
        resume["body"]!["operation"] = "run";
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRequest(resume, now), "Original resume was silently substituted with an ordinary run.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.CreateRequest("run", now, new string('a',64),
            originalJobId: new string('b',32), originalJobVersion: new string('c',64)), "Run factory ignored original-job intent.");
        var image = DeviceFileSources.CreateRequest("discover", now, new string('a', 64));
        TestAssert.That(!image["body"]!.AsObject().ContainsKey("media_type") && DeviceFileSources.ParseRequest(image, now).MediaType == "images", "Legacy image wire shape changed.");
        return Task.CompletedTask;
    }

    internal static Task ScopedResultsAsync()
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var id = Guid.NewGuid().ToString("D"); var run = Guid.NewGuid().ToString("D"); var version = new string('a', 64);
        JsonObject Message(string kind, string operation, JsonObject extra)
        {
            var value = DeviceFileSources.CreateRequest("status", now, messageId: id); value["kind"] = kind;
            var body = new JsonObject { ["format"] = 1, ["request_id"] = id, ["operation"] = operation,
                ["version"] = version, ["media_type"] = "video" };
            foreach (var field in extra) body[field.Key] = field.Value?.DeepClone();
            value["body"] = body; return value;
        }
        var catalog = Message(DeviceFileSources.CatalogKind, "discover", new() { ["page"] = new JsonObject {
            ["format"] = 1, ["catalog_id"] = Guid.NewGuid().ToString("D"), ["after"] = 0, ["next_cursor"] = null,
            ["coverage"] = "full_videos", ["proves_deletion"] = false, ["albums"] = new JsonArray(new JsonObject {
                ["album_id"] = Guid.NewGuid().ToString("D"), ["kind"] = "camera", ["display_name"] = "Synthetic videos", ["visible_images"] = 1, ["needs_choice"] = false }) } });
        TestAssert.That(DeviceFileSources.ParseCatalog(catalog, id, "discover", version, now, expectedMediaType: "video").MediaType == "video", "Explicit video catalog rejected.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseCatalog(catalog, id, "discover", version, now), "Image command consumed a video catalog.");
        catalog["body"]!["page"]!["proves_deletion"] = true;
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseCatalog(catalog, id, "discover", version, now, expectedMediaType: "video"), "Video coverage became deletion proof.");
        var permission = Message(DeviceFileSources.PermissionResultKind, "request_read", new() { ["state"] = "foreground_required" });
        TestAssert.That(DeviceFileSources.ParsePermissionResult(permission, id, version, now, "video").MediaType == "video", "Video permission UI metadata rejected.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParsePermissionResult(permission, id, version, now), "Image command consumed video permission metadata.");
        var result = Message(DeviceFileSources.RunResultKind, "run", new() { ["run_id"] = run, ["state"] = "preparing", ["source_io_ended"] = false });
        TestAssert.That(DeviceFileSources.ParseRunResult(result, id, "run", version, now, expectedMediaType: "video").MediaType == "video", "Typed video run metadata rejected.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseRunResult(result, id, "run", version, now), "Image command consumed a video run.");
        var media = Message(DeviceFileSources.MediaKind, "media_page", new() { ["run_id"] = run, ["page"] = new JsonObject {
            ["format"] = 1, ["manifest_sha256"] = new string('b', 64), ["source_epoch"] = new string('c', 64), ["media_type"] = "video",
            ["insertion_witness"] = true, ["after"] = 0, ["next_cursor"] = null, ["total_files"] = 1,
            ["entries"] = new JsonArray(new JsonObject { ["file_id"] = new string('d', 32), ["photo_id"] = new string('e', 64), ["media_kind"] = "video" }) } });
        var page = DeviceFileSources.ParseMediaPage(media, id, version, run, now, expectedMediaType: "video");
        TestAssert.That(page.MediaType == "video" && !page.GrantsWriteAuthority && !page.IsSavedReceipt, "Video page became authority or Saved.");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseMediaPage(media, id, version, run, now, expectedMediaType: "images"), "Image receiver consumed a video page.");
        media["body"]!.AsObject().Remove("media_type");
        TestAssert.Throws<InvalidDataException>(() => DeviceFileSources.ParseMediaPage(media, id, version, run, now, expectedMediaType: "video"), "Inner video tag replaced required outer command scope.");
        TestAssert.That(!DeviceFileSources.ParseMediaPage(media, id, version, run, now).GrantsWriteAuthority, "Legacy unbound media inspection gained data authority.");
        return Task.CompletedTask;
    }

    internal static async Task CurrentChannelAsync()
    {
        foreach (var supported in new[] { false, true })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
            var owner = await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture, supported);
            var pending = fixture.Connection.ReadNativeFileSourceStatusAsync();
            var reply = DeviceFileConnectionSourcesTests.Reply(DeviceFileConnectionSourcesTests.Request(fixture));
            reply["body"]!["videos"] = new JsonObject { ["enabled"] = true, ["revision"] = 3 };
            if (supported)
            {
                await fixture.Connection.HandlePlainAsync(reply);
                var status = await pending;
                TestAssert.That(status.Videos is { Enabled: true, Revision: 3, GrantsReadAuthority: false } &&
                    owner.Binding(new string('c', 64)) is null, "Current marker-22 metadata invented source SEND/READ.");
            }
            else
            {
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(fixture.Connection.HandlePlainAsync(reply), "Base-only channel accepted video metadata.");
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(pending, "Unsupported video extension completed native status.");
            }
        }
    }

    internal static async Task WithdrawalAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        await DeviceFileConnectionTransportTests.OpenOffSourceAsync(fixture);
        var old = fixture.Connection.ReadNativeFileSourceStatusAsync(); DeviceFileConnectionSourcesTests.Request(fixture);
        await fixture.Connection.HandlePlainAsync(fixture.Message("capabilities.update", 2, video: false));
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(old.WaitAsync(TimeSpan.FromSeconds(2)), "Video withdrawal left an old native status witness active.");
        TestAssert.That(fixture.Connection.FileMetadataReady() && !fixture.Connection.FileMetadataReady(videos: true), "Video-only withdrawal destroyed base metadata or retained marker 22.");
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        var fresh = fixture.Connection.ReadNativeFileSourceStatusAsync();
        await fixture.Connection.HandlePlainAsync(DeviceFileConnectionSourcesTests.Reply(DeviceFileConnectionSourcesTests.Request(fixture)));
        TestAssert.That((await fresh).Videos is null, "Fresh base-only status reused a withdrawn video witness.");
    }
}
