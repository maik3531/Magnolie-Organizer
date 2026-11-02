using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileChunkEnvelopeTests
{
    internal static Task RunAsync()
    {
        const long now = 1800000000000;
        foreach (var length in new[] { 5, DeviceFileManifest.ChunkBytes })
        {
            var data = Enumerable.Range(0, length).Select(value => (byte)(value % 251)).ToArray();
            var hash = Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();
            var manifest = new DeviceFileManifest(new string('a', 32), new string('b', 32), "sender_fixture_01", "receiver_fixture_01",
                [new(new string('c', 32), "photo.jpg", data.Length, hash)], data.Length);
            var accepted = new RemoteFileAcceptance("11111111-1111-4111-8111-111111111111", manifest.Fingerprint, manifest.TransferId, new string('d', 64), new string('e', 64), new string('f', 64));
            var request = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = DeviceFileChunkEnvelope.RequestKind,
                ["message_id"] = "22222222-2222-4222-8222-222222222222", ["created_ms"] = now, ["expires_ms"] = now + 60000,
                ["body"] = new JsonObject { ["format"] = 1, ["transfer_id"] = manifest.TransferId, ["manifest_sha256"] = manifest.Fingerprint,
                    ["acceptance_sha256"] = accepted.AcceptanceSha256, ["permission_epoch"] = accepted.PermissionEpoch, ["destination_token"] = accepted.DestinationToken,
                    ["file_id"] = manifest.Files[0].Id, ["chunk_index"] = 0 } };
            var response = (JsonObject)request.DeepClone(); response["kind"] = DeviceFileChunkEnvelope.ResultKind;
            var body = response["body"]!.AsObject(); body["request_id"] = request["message_id"]!.DeepClone(); body["data_base64"] = Convert.ToBase64String(data); body["data_sha256"] = hash;
            byte[] Read(JsonObject value) => DeviceFileChunkEnvelope.ParseResponse(value, request, manifest, accepted, now);
            TestAssert.That(Read(response).SequenceEqual(data), "Exact complete chunk did not survive codec readback.");
            foreach (var (key, value) in new (string, JsonNode?)[] { ("chunk_index", JsonValue.Create(true)), ("data_sha256", JsonValue.Create(new string('a', 64))),
                ("destination_token", JsonValue.Create(new string('a', 64))), ("saved", JsonValue.Create(true)), ("data_base64", JsonValue.Create(Convert.ToBase64String(data) + "\n")) })
            {
                var invalid = (JsonObject)response.DeepClone(); invalid["body"]!.AsObject()[key] = value;
                TestAssert.Throws<InvalidDataException>(() => Read(invalid), "Invalid chunk metadata/correlation/data accepted.");
            }
            TestAssert.Throws<InvalidDataException>(() => DeviceFileChunkEnvelope.ParseResponse(response, request, manifest, accepted, now + 60000), "Expired chunk accepted.");
        }
        return Task.CompletedTask;
    }
}
