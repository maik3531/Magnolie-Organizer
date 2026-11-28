using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// A peer's complete-offer observation is distinct from both Saved and a
// native source-retirement decision.
internal sealed class RemotePublishedBatchReadback(JsonObject value)
{
    private readonly JsonObject body = value.DeepClone().AsObject();
    internal JsonObject Body => body.DeepClone().AsObject();
}

internal static class DevicePublishedBatchReadbackEnvelope
{
    internal const string Kind = DevicePublishedReadbackEnvelope.Kind;
    private const string DestinationDomain = "magnolie-published-readback-destination-v2\0";
    private const string BindingDomain = "magnolie-published-readback-binding-v2\0";
    private const string ReadbackDomain = "magnolie-published-readback-v2\0";
    private static readonly string[] Fields = ["format", "offer_id", "manifest_sha256", "transfer_id", "source_id", "media_type", "members", "permission_epoch", "readback_nonce"];
    private static readonly string[] MemberFields = ["size", "sha256", "mime_type", "publication_sha256", "row_sha256"];
    private static readonly Regex Id = new(@"\A[0-9a-f]{32}\z", RegexOptions.CultureInvariant);
    private static InvalidDataException Error() => DeviceFileControl.Error("file_published_batch_readback_invalid");
    private static string Text(JsonObject value, string key) => value[key] is JsonValue field && field.TryGetValue<string>(out var text) && text is not null
        ? text : throw Error();

    private static void ValidateContext(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, Fields);
        if (TelefonProtocolContract.Integer(value["format"]) != 2 || !TelefonProtocolContract.IsUuidV4(Text(value, "offer_id"))) throw Error();
        foreach (var key in new[] { "manifest_sha256", "permission_epoch", "readback_nonce" })
            if (!DeviceFileControl.Hash(Text(value, key))) throw Error();
        foreach (var key in new[] { "transfer_id", "source_id" })
            if (!Id.IsMatch(Text(value, key))) throw Error();
        var kind = Text(value, "media_type");
        if (kind is not ("images" or "video") || value["members"] is not JsonObject members || members.Count is < 1 or > DeviceFileManifest.MaxFiles)
            throw Error();
        var publications = new HashSet<string>(StringComparer.Ordinal);
        var rows = new HashSet<string>(StringComparer.Ordinal);
        long total = 0;
        foreach (var (fileId, raw) in members)
        {
            if (!Id.IsMatch(fileId) || raw is not JsonObject member) throw Error();
            TelefonProtocolContract.ExactObject(member, MemberFields);
            var size = TelefonProtocolContract.Integer(member["size"]);
            if (size is < 1 or > DeviceFileManifest.MaxFileBytes || !Regex.IsMatch(Text(member, "mime_type"),
                @"\A" + (kind == "images" ? "image/" : "video/") + @"[a-z0-9.+-]{1,80}\z", RegexOptions.CultureInvariant)) throw Error();
            foreach (var key in new[] { "sha256", "publication_sha256", "row_sha256" })
                if (!DeviceFileControl.Hash(Text(member, key))) throw Error();
            if (!publications.Add(Text(member, "publication_sha256")) || !rows.Add(Text(member, "row_sha256"))) throw Error();
            total += size;
        }
        if (total > DeviceFileManifest.MaxTotalBytes) throw Error();
    }

    internal static string DestinationToken(JsonObject context)
    {
        ValidateContext(context);
        return DeviceFileControl.Digest(DestinationDomain, context);
    }

    internal static JsonObject EncodeBody(JsonObject context, DeviceTransferBinding binding)
    {
        binding.Validate();
        var destination = DestinationToken(context);
        if (!DeviceFileControl.Identity(binding.SenderId) || !DeviceFileControl.Identity(binding.ReceiverId) ||
            binding.PermissionEpoch != Text(context, "permission_epoch") || binding.DestinationToken != destination) throw Error();
        var body = context.DeepClone().AsObject();
        body["destination_token"] = destination;
        body["binding_sha256"] = DeviceFileControl.Digest(BindingDomain, binding.Snapshot());
        body["readback_sha256"] = DeviceFileControl.Digest(ReadbackDomain, body);
        return body;
    }

    internal static RemotePublishedBatchReadback Parse(JsonObject message, JsonObject offer, DeviceTransferBinding binding, string mediaType, long now,
        bool historicalOffer = false)
    {
        if (mediaType is not ("images" or "video") || TelefonCrypto.Canonical(message).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes) throw Error();
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]);
        var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 || Text(message, "kind") != Kind ||
            !TelefonProtocolContract.IsUuidV4(Text(message, "message_id")) || created is < 0 or > 253402300799999 ||
            expires <= created || expires - created > DeviceFileControl.MaximumTtlMs || now >= expires || created > now + 300000) throw Error();
        var body = TelefonProtocolContract.ExactObject(message["body"]!, Fields.Concat(new[] { "destination_token", "binding_sha256", "readback_sha256" }).ToArray());
        var context = new JsonObject(Fields.Select(key => KeyValuePair.Create(key, body[key]?.DeepClone())));
        if (!JsonNode.DeepEquals(EncodeBody(context, binding), body)) throw Error();
        var members = body["members"]!.AsObject();
        var offerCreated = TelefonProtocolContract.Integer(offer["created_ms"]);
        var offerExpires = TelefonProtocolContract.Integer(offer["expires_ms"]);
        var manifest = DeviceFileOfferEnvelope.Validate(offer, binding.SenderId, binding.ReceiverId, historicalOffer ? offerCreated : now);
        if ((!historicalOffer && (now < offerCreated || now >= offerExpires || created < offerCreated || expires > offerExpires)) ||
            Text(body, "offer_id") != Text(offer, "message_id") || Text(body, "manifest_sha256") != manifest.Fingerprint ||
            Text(body, "transfer_id") != manifest.TransferId || Text(body, "source_id") != manifest.SourceId || Text(body, "media_type") != mediaType ||
            !members.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(manifest.Files.Select(file => file.Id))) throw Error();
        foreach (var file in manifest.Files)
        {
            var member = members[file.Id]!.AsObject();
            if (TelefonProtocolContract.Integer(member["size"]) != file.Size || Text(member, "sha256") != file.Sha256) throw Error();
        }
        return new(body);
    }
}

internal static class DeviceSavedBatchReadback
{
    internal const string RequestKind = "file_transfer.published.recover";
    private const string BindingDomain = "magnolie-pc-saved-readback-control-v1\0";
    private static InvalidDataException Error() => DeviceFileControl.Error("media_saved_readback_invalid_recovery");
    private static long Time(JsonObject message, string field) => TelefonProtocolContract.Integer(message[field]);
    private static string Text(JsonObject value, string key) => TelefonMessagingContract.String(value, key);

    internal static JsonObject Create(JsonObject offer, JsonObject saved, DeviceTransferBinding binding, long now)
    {
        var request = new JsonObject
        {
            ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = RequestKind,
            ["created_ms"] = now, ["expires_ms"] = checked(now + DeviceFileControl.MaximumTtlMs),
            ["body"] = new JsonObject
            {
                ["format"] = 1, ["binding_sha256"] = DeviceFileControl.Digest(BindingDomain, binding.Snapshot()),
                ["nonce"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(),
                ["offer"] = offer.DeepClone(), ["saved"] = saved.DeepClone()
            }
        };
        if (TelefonCrypto.Canonical(request).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes) throw Error();
        return request;
    }

    private static NativeMediaOffer ValidateReplyBinding(JsonObject request, JsonObject reply,
        JsonObject offer, JsonObject saved, DeviceTransferBinding requestBinding, DeviceTransferBinding replyBinding, long now)
    {
        var requestBody = TelefonProtocolContract.ExactObject(request["body"]!, "format", "binding_sha256", "nonce", "offer", "saved");
        var created = Time(request, "created_ms"); var expires = Time(request, "expires_ms");
        TelefonProtocolContract.ExactObject(request, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        if (Text(request, "type") != "message" || Time(request, "v") != 1 || Text(request, "kind") != RequestKind ||
            !TelefonProtocolContract.IsUuidV4(Text(request, "message_id")) ||
            created < 0 || created > now || now >= expires || expires > 253402300799999 ||
            expires - created > DeviceFileControl.MaximumTtlMs || Time(requestBody, "format") != 1 ||
            requestBody["binding_sha256"]?.GetValue<string>() != DeviceFileControl.Digest(BindingDomain, requestBinding.Snapshot()) ||
            !DeviceFileControl.Hash(Text(requestBody, "nonce")) ||
            !JsonNode.DeepEquals(requestBody["offer"], offer) || !JsonNode.DeepEquals(requestBody["saved"], saved) ||
            TelefonCrypto.Canonical(request).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes)
            throw Error();
        var media = MediaOfferEnvelope.Validate(offer, requestBinding.SenderId, requestBinding.ReceiverId,
            Time(offer, "created_ms"), allowPcBatch: true);
        var replyCreated = Time(reply, "created_ms");
        if (media.Originals.Count != 0 ||
            media.PcOrigins.Count != media.Manifest.Files.Count ||
            media.PcOrigins.Any(origin => origin.Value!["previous_publication_sha256"] is not null) ||
            requestBinding.DestinationToken != media.Manifest.Fingerprint ||
            replyBinding != (requestBinding with { DestinationToken = replyBinding.DestinationToken }) ||
            Time(saved, "created_ms") < Time(offer, "created_ms") || Time(saved, "created_ms") > created ||
            Time(saved, "expires_ms") > Time(offer, "expires_ms") ||
            replyCreated < created || replyCreated > now || Time(reply, "expires_ms") > expires ||
            Text(reply, "message_id") == Text(request, "message_id"))
            throw Error();
        return media;
    }

    // The live caller must obtain both bindings from the same authenticated reader.
    // The history caller verifies the recorded challenge using its protected scope.
    internal static RemotePublishedBatchReadback ParseReply(JsonObject request, JsonObject reply,
        JsonObject offer, JsonObject saved, RemoteSavedConfirmation receipts, DeviceTransferBinding requestBinding,
        DeviceTransferBinding replyBinding, long now)
    {
        var media = ValidateReplyBinding(request, reply, offer, saved, requestBinding, replyBinding, now);
        if (!media.PcBatch || media.MediaType != "images" ||
            receipts.Members.Select(member => member.ReceiptSha256).Distinct(StringComparer.Ordinal).Count() != media.Manifest.Files.Count)
            throw Error();
        var observed = DevicePublishedBatchReadbackEnvelope.Parse(reply, media.Offer, replyBinding, "images", now, historicalOffer: true);
        var body = observed.Body;
        if (Text(body, "readback_nonce") != Text(request["body"]!.AsObject(), "nonce") ||
            receipts.Members.Any(receipt =>
                Text(body["members"]![receipt.FileId]!.AsObject(), "publication_sha256") != receipt.ReceiptSha256 ||
                Text(body["members"]![receipt.FileId]!.AsObject(), "mime_type") != media.MimeTypes[receipt.FileId]!.GetValue<string>()))
            throw Error();
        return observed;
    }

    internal static RemotePublishedReadback ParseVideoReply(JsonObject request, JsonObject reply,
        JsonObject offer, JsonObject saved, RemoteSavedConfirmation receipt, DeviceTransferBinding requestBinding,
        DeviceTransferBinding replyBinding, long now)
    {
        var media = ValidateReplyBinding(request, reply, offer, saved, requestBinding, replyBinding, now);
        if (media.PcBatch || media.MediaType != "video" || media.Manifest.Files.Count != 1 ||
            media.MimeTypes[media.Manifest.Files[0].Id]?.GetValue<string>() != "video/mp4" ||
            receipt.Members.Count != 1) throw Error();
        var observed = DevicePublishedReadbackEnvelope.Parse(reply, media.Offer, replyBinding, "video", now, historicalOffer: true);
        var body = observed.Body;
        var member = receipt.Members[0];
        if (Text(body, "readback_nonce") != Text(request["body"]!.AsObject(), "nonce") ||
            Text(body, "file_id") != member.FileId || Text(body, "publication_sha256") != member.ReceiptSha256 ||
            Text(body, "mime_type") != "video/mp4") throw Error();
        return observed;
    }
}
