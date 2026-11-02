using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSavedEnvelopeTests
{
    internal static Task RunAsync()
    {
        const long now = 1800000000000;
        foreach (var count in new[] { 2, 128 })
        {
            var files = Enumerable.Range(1, count).Select(index => new DeviceManifestFile(index.ToString("x32"), $"Camera/a{index:000}.jpg", 5, new string('f', 64))).ToArray();
            var manifest = new DeviceFileManifest(new string('a', 32), new string('b', 32), "sender_fixture_01", "receiver_fixture_01", files, count * 5);
            var accepted = new RemoteFileAcceptance("11111111-1111-4111-8111-111111111111", manifest.Fingerprint, manifest.TransferId, new string('c', 64), new string('d', 64), new string('e', 64));
            var receipts = new JsonArray(files.Select(file => (JsonNode)new JsonObject {
                ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["receipt_sha256"] = new string('0', 64) }).ToArray());
            var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = DeviceFileSavedEnvelope.Kind,
                ["message_id"] = "22222222-2222-4222-8222-222222222222", ["created_ms"] = now, ["expires_ms"] = now + 60000,
                ["body"] = new JsonObject { ["format"] = 1, ["transfer_id"] = manifest.TransferId, ["manifest_sha256"] = manifest.Fingerprint,
                    ["acceptance_sha256"] = accepted.AcceptanceSha256, ["permission_epoch"] = accepted.PermissionEpoch,
                    ["destination_token"] = accepted.DestinationToken, ["receipts"] = receipts } };
            RemoteSavedConfirmation Read(JsonObject value) => DeviceFileSavedEnvelope.Parse(value, manifest, accepted, now);
            TestAssert.That(Read(message).Members.Count == count, "Complete historical receipt set rejected.");
            TestAssert.That(!System.Text.Encoding.UTF8.GetString(TelefonCrypto.Canonical(message)).Contains("Camera/"), "Receipt projection exposed paths.");
            foreach (var (key, value) in new (string, JsonNode?)[] { ("success", JsonValue.Create(true)), ("quota_retired", JsonValue.Create(true)),
                ("receipts", new JsonArray()), ("permission_epoch", JsonValue.Create(new string('a', 64))) })
            {
                var invalid = (JsonObject)message.DeepClone(); invalid["body"]!.AsObject()[key] = value;
                TestAssert.Throws<InvalidDataException>(() => Read(invalid), "Partial/mismatched receipt or sync claim accepted.");
            }
            var booleanSize = (JsonObject)message.DeepClone(); booleanSize["body"]!["receipts"]![0]!.AsObject()["size"] = true;
            TestAssert.Throws<InvalidDataException>(() => Read(booleanSize), "Boolean saved size accepted.");
            TestAssert.Throws<InvalidDataException>(() => DeviceFileSavedEnvelope.Parse(message, manifest, accepted, now + 60000), "Expired saved confirmation accepted.");
        }
        return Task.CompletedTask;
    }
}
