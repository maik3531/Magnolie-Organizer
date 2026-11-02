using System.Security.Cryptography;
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
        return Task.CompletedTask;
    }
}
