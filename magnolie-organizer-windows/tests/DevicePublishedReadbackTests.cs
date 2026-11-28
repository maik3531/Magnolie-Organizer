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

    internal static Task BatchAsync()
    {
        const string path = "contracts/file-published-readback-batch-v2-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(path), path)))!.AsObject();
        var message = vector["message"]!.AsObject();
        var offer = vector["offer"]!.AsObject();
        var wire = vector["binding"]!.AsObject();
        var now = vector["now_ms"]!.GetValue<long>();
        string Text(string key) => wire[key]!.GetValue<string>();
        var binding = new DeviceTransferBinding(Text("sender_id"), Text("receiver_id"), Text("sender_identity_sha256"),
            Text("receiver_identity_sha256"), Text("permission_epoch"), Text("destination_token"));
        JsonObject Context() => new(message["body"]!.AsObject().Where(pair => pair.Key is not ("destination_token" or "binding_sha256" or "readback_sha256"))
            .Select(pair => KeyValuePair.Create(pair.Key, pair.Value?.DeepClone())));
        var result = DevicePublishedBatchReadbackEnvelope.Parse(message, offer, binding, "images", now);
        TestAssert.That(JsonNode.DeepEquals(result.Body, message["body"]) &&
            JsonNode.DeepEquals(DevicePublishedBatchReadbackEnvelope.EncodeBody(Context(), binding), result.Body),
            "Whole-offer readback diverged from the common canonical bytes.");
        var copy = result.Body;
        copy["members"]!.AsObject().Clear();
        TestAssert.That(result.Body["members"]!.AsObject().Count == 2, "A caller changed the original observed readback.");
        TestAssert.Throws<InvalidDataException>(() => DevicePublishedReadbackEnvelope.Parse(message, offer, binding, "images", now),
            "The single-file path accepted a whole-offer readback.");
        var ids = Context()["members"]!.AsObject().Select(pair => pair.Key).ToArray();
        void RejectRehashed(Action<JsonObject> change)
        {
            var context = Context();
            change(context);
            var rebound = binding with { DestinationToken = DevicePublishedBatchReadbackEnvelope.DestinationToken(context) };
            var altered = message.DeepClone().AsObject();
            altered["body"] = DevicePublishedBatchReadbackEnvelope.EncodeBody(context, rebound);
            TestAssert.Throws<InvalidDataException>(() => DevicePublishedBatchReadbackEnvelope.Parse(altered, offer, rebound, "images", now),
                "Rehashed metadata substituted for the original complete offer.");
        }
        RejectRehashed(value => value["members"]!.AsObject().Remove(ids[1]));
        RejectRehashed(value => value["members"]![ids[1]]!["size"] = 457);
        RejectRehashed(value => value["members"]![ids[1]]!["sha256"] = new string('0', 64));
        RejectRehashed(value => value["offer_id"] = "99999999-9999-4999-8999-999999999999");
        foreach (var key in new[] { "row_sha256", "publication_sha256" })
        {
            var aliased = Context();
            aliased["members"]![ids[1]]![key] = aliased["members"]![ids[0]]![key]!.DeepClone();
            TestAssert.Throws<InvalidDataException>(() => DevicePublishedBatchReadbackEnvelope.DestinationToken(aliased),
                "A row or publication fingerprint was reused for another member.");
        }
        var extended = message.DeepClone().AsObject();
        extended["expires_ms"] = offer["expires_ms"]!.GetValue<long>() + 1;
        TestAssert.Throws<InvalidDataException>(() => DevicePublishedBatchReadbackEnvelope.Parse(extended, offer, binding, "images", now),
            "A readback extended the original offer lifetime.");
        TestAssert.Throws<InvalidDataException>(() => DevicePublishedBatchReadbackEnvelope.Parse(message, offer,
            binding with { ReceiverIdentitySha256 = new string('0', 64) }, "images", now), "Foreign binding accepted the readback.");
        VerifyHistoricalPhotoBatch(offer, binding, Context(), now);
        return Task.CompletedTask;
    }

    private static void VerifyHistoricalPhotoBatch(JsonObject offer, DeviceTransferBinding originalBinding, JsonObject context, long savedAt)
    {
        const string sender = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
        const string receiver = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb";
        var created = TelefonProtocolContract.Integer(offer["created_ms"]);
        var fixture = DeviceFileOfferEnvelope.Validate(offer, originalBinding.SenderId, originalBinding.ReceiverId, created);
        var manifest = new DeviceFileManifest(fixture.TransferId, fixture.SourceId, sender, receiver, fixture.Files, fixture.TotalBytes);
        var settings = MediaSyncSettings.Change(MediaSyncSettings.Create(sender), sender, receiver, "enabled", JsonValue.Create(true)!);
        settings = MediaSyncSettings.Change(settings, sender, receiver, "direction", JsonValue.Create("pc_to_phone")!);
        settings = MediaSyncSettings.Change(settings, sender, receiver, "collection_mode", JsonValue.Create("entire_collection")!);
        var members = context["members"]!.AsObject();
        var mime = new JsonObject(members.Select(pair => KeyValuePair.Create(pair.Key, pair.Value!["mime_type"]?.DeepClone())));
        var origins = new JsonObject(manifest.Files.Select(file => KeyValuePair.Create<string, JsonNode?>(file.Id,
            new JsonObject { ["format"] = 1, ["origin_sha256"] = file.Id + file.Id, ["previous_publication_sha256"] = null })));
        var historical = MediaOfferEnvelope.Create(manifest, settings, "images", mime, new(), created,
            offer["message_id"]!.GetValue<string>(), origins, pcBatch: true);
        var accepted = new RemoteFileAcceptance(
            historical["message_id"]!.GetValue<string>(), manifest.Fingerprint, manifest.TransferId,
            new string('f', 64), originalBinding.PermissionEpoch, originalBinding.DestinationToken);
        var receiptRows = new JsonArray(manifest.Files.Select(file => (JsonNode?)new JsonObject { ["file_id"] = file.Id, ["size"] = file.Size,
            ["sha256"] = file.Sha256, ["receipt_sha256"] = members[file.Id]!["publication_sha256"]!.DeepClone() }).ToArray());
        var saved = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = DeviceFileSavedEnvelope.Kind, ["created_ms"] = savedAt, ["expires_ms"] = historical["expires_ms"]!.DeepClone(),
            ["body"] = new JsonObject { ["format"] = 1, ["transfer_id"] = manifest.TransferId, ["manifest_sha256"] = manifest.Fingerprint,
                ["acceptance_sha256"] = accepted.AcceptanceSha256, ["permission_epoch"] = accepted.PermissionEpoch,
                ["destination_token"] = accepted.DestinationToken, ["receipts"] = receiptRows } };
        var receipts = DeviceFileSavedEnvelope.Parse(saved, manifest, accepted, savedAt);
        var fresh = originalBinding with { SenderId = sender, ReceiverId = receiver, DestinationToken = manifest.Fingerprint, PermissionEpoch = new string('a', 64) };
        var now = TelefonProtocolContract.Integer(historical["expires_ms"]) + 60000;
        var challenge = DeviceSavedBatchReadback.Create(historical, saved, fresh, now);
        context["manifest_sha256"] = manifest.Fingerprint;
        context["readback_nonce"] = challenge["body"]!["nonce"]!.DeepClone();
        context["permission_epoch"] = fresh.PermissionEpoch;
        var replyBinding = fresh with { DestinationToken = DevicePublishedBatchReadbackEnvelope.DestinationToken(context) };
        var reply = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = DevicePublishedBatchReadbackEnvelope.Kind, ["created_ms"] = now, ["expires_ms"] = challenge["expires_ms"]!.DeepClone(),
            ["body"] = DevicePublishedBatchReadbackEnvelope.EncodeBody(context, replyBinding) };
        TestAssert.That(JsonNode.DeepEquals(reply["body"], DeviceSavedBatchReadback.ParseReply(challenge, reply, historical, saved,
            receipts, fresh, replyBinding, now).Body), "Historical offer expiry blocked a fresh authenticated read-only response.");
        var replay = DeviceSavedBatchReadback.Create(historical, saved, fresh, now);
        TestAssert.Throws<InvalidDataException>(() => DeviceSavedBatchReadback.ParseReply(replay, reply, historical, saved,
            receipts, fresh, replyBinding, now), "A different challenge nonce accepted an old response.");
        TestAssert.Throws<InvalidDataException>(() => DeviceSavedBatchReadback.ParseReply(challenge, reply, historical, saved,
            receipts, fresh, replyBinding with { ReceiverIdentitySha256 = new string('0', 64) }, now), "A foreign binding accepted a recovery response.");
        TestAssert.Throws<InvalidDataException>(() => DeviceSavedBatchReadback.ParseReply(challenge, reply, historical, saved,
            receipts, fresh, replyBinding, TelefonProtocolContract.Integer(challenge["expires_ms"])), "An expired recovery response was accepted.");
    }
}
