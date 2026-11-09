using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DevicePublishedReadbackTests
{
    internal static Task RunAsync()
    {
        const string path = "contracts/file-published-readback-v1-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(path), path)))!.AsObject();
        var message = vector["message"]!.AsObject(); var offer = vector["offer"]!.AsObject();
        var wireBinding = vector["binding"]!.AsObject(); var now = vector["now_ms"]!.GetValue<long>();
        string Text(string key) => wireBinding[key]!.GetValue<string>();
        var binding = new DeviceTransferBinding(Text("sender_id"), Text("receiver_id"), Text("sender_identity_sha256"),
            Text("receiver_identity_sha256"), Text("permission_epoch"), Text("destination_token"));
        JsonObject Context(JsonObject body) => new(body.Where(pair => pair.Key is not ("destination_token" or "binding_sha256" or "readback_sha256"))
            .Select(pair => KeyValuePair.Create(pair.Key, pair.Value?.DeepClone())));
        var parsed = DevicePublishedReadbackEnvelope.Parse(message, offer, binding, "images", now);
        TestAssert.That(JsonNode.DeepEquals(parsed.Body, message["body"]) &&
            JsonNode.DeepEquals(DevicePublishedReadbackEnvelope.EncodeBody(Context(parsed.Body), binding), parsed.Body),
            "Published readback diverged from the common canonical vector.");
        var copy = parsed.Body; copy["row_sha256"] = new string('0', 64);
        TestAssert.That(!JsonNode.DeepEquals(copy, parsed.Body) && !parsed.GrantsWriteAuthority && !parsed.IsSavedReceipt && !parsed.AllowsChunkOutput,
            "Peer metadata mutated its owner or conferred native authority.");
        void Reject(Action<JsonObject> change)
        {
            var altered = message.DeepClone().AsObject(); change(altered);
            TestAssert.Throws<InvalidDataException>(() => DevicePublishedReadbackEnvelope.Parse(altered, offer, binding, "images", now),
                "Invalid publication readback admitted.");
        }
        Reject(value => value["extra"] = true); Reject(value => value["v"] = "1");
        Reject(value => value["expires_ms"] = now); Reject(value => value["created_ms"] = now - 2000);
        Reject(value => value["expires_ms"] = now + 60001); Reject(value => value["message_id"] = "not-a-uuid");
        Reject(value => value["body"]!["extra"] = true); Reject(value => value["body"]!["size"] = "123");
        Reject(value => value["body"]!["size"] = JsonNode.Parse("123.0")); Reject(value => value["body"]!["size"] = true);
        foreach (var key in new[] { "destination_token", "binding_sha256", "readback_sha256", "row_sha256", "publication_sha256", "readback_nonce" })
            Reject(value => value["body"]![key] = new string('0', 64));
        // Recompute ALL hashes and the destination binding: the manifest/offer
        // comparisons must reject semantic substitution, not merely stale hashes.
        foreach (var (key, replacement) in new (string, JsonNode)[] {
            ("offer_id", JsonValue.Create("99999999-9999-4999-8999-999999999999")!),
            ("manifest_sha256", JsonValue.Create(new string('0', 64))!),
            ("transfer_id", JsonValue.Create(new string('0', 32))!), ("source_id", JsonValue.Create(new string('0', 32))!),
            ("file_id", JsonValue.Create(new string('0', 32))!), ("size", JsonValue.Create(124)!),
            ("sha256", JsonValue.Create(new string('0', 64))!), ("media_type", JsonValue.Create("video")!) })
        {
            var context = Context(parsed.Body); context[key] = replacement.DeepClone();
            if (key == "media_type") context["mime_type"] = "video/mp4";
            var rebound = binding with { DestinationToken = DevicePublishedReadbackEnvelope.DestinationToken(context) };
            var altered = message.DeepClone().AsObject(); altered["body"] = DevicePublishedReadbackEnvelope.EncodeBody(context, rebound);
            TestAssert.Throws<InvalidDataException>(() => DevicePublishedReadbackEnvelope.Parse(altered, offer, rebound, "images", now),
                "Rehashed semantic substitution bypassed offer correlation: " + key);
        }
        TestAssert.Throws<InvalidDataException>(() => DevicePublishedReadbackEnvelope.Parse(message, offer, binding, "video", now), "Wrong native media domain admitted.");
        TestAssert.Throws<InvalidDataException>(() => DevicePublishedReadbackEnvelope.Parse(message, offer, binding with { ReceiverIdentitySha256 = new string('0', 64) }, "images", now), "Foreign native binding admitted.");
        var videoContext = Context(parsed.Body); videoContext["media_type"] = "video"; videoContext["mime_type"] = "video/mp4";
        var videoBinding = binding with { DestinationToken = DevicePublishedReadbackEnvelope.DestinationToken(videoContext) };
        var videoMessage = message.DeepClone().AsObject(); videoMessage["body"] = DevicePublishedReadbackEnvelope.EncodeBody(videoContext, videoBinding);
        var video = DevicePublishedReadbackEnvelope.Parse(videoMessage, offer, videoBinding, "video", now);
        TestAssert.That(!video.GrantsWriteAuthority && !video.IsSavedReceipt && !video.AllowsChunkOutput,
            "Video readback invented native completion authority.");
        return Task.CompletedTask;
    }
}
