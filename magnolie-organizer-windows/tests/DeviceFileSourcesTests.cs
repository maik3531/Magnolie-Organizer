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
        return Task.CompletedTask;
    }
}
