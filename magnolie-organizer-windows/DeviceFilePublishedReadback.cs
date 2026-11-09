using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Parsed peer metadata ONLY. Neither a local saved receipt nor actual local
// source END/cache-retirement authority can be constructed from this object.
internal sealed class RemotePublishedReadback(JsonObject value)
{
    private readonly JsonObject body = value.DeepClone().AsObject();
    internal JsonObject Body => body.DeepClone().AsObject();
    internal bool GrantsWriteAuthority => false;
    internal bool IsSavedReceipt => false;
    internal bool AllowsChunkOutput => false;
}

internal static class DevicePublishedReadbackEnvelope
{
    internal const string Kind = "file_transfer.published.readback";
    private const string DestinationDomain = "magnolie-published-readback-destination-v1\0";
    private const string BindingDomain = "magnolie-published-readback-binding-v1\0";
    private const string ReadbackDomain = "magnolie-published-readback-v1\0";
    private static readonly string[] ContextFields = ["format", "offer_id", "manifest_sha256", "transfer_id", "source_id", "file_id", "size", "sha256",
        "media_type", "mime_type", "publication_sha256", "row_sha256", "permission_epoch", "readback_nonce"];
    private static readonly Regex Id = new("\\A[0-9a-f]{32}\\z", RegexOptions.CultureInvariant);

    private static InvalidDataException Error() => DeviceFileControl.Error("file_published_readback_invalid");
    private static string Text(JsonObject value, string key) => value[key] is JsonValue field && field.TryGetValue<string>(out var text) && text is not null ? text : throw Error();
    private static void ValidateContext(JsonObject value)
    {
        TelefonProtocolContract.ExactObject(value, ContextFields);
        if (TelefonProtocolContract.Integer(value["format"]) != 1 || !TelefonProtocolContract.IsUuidV4(Text(value, "offer_id")) ||
            TelefonProtocolContract.Integer(value["size"]) is < 1 or > DeviceFileManifest.MaxFileBytes) throw Error();
        foreach (var key in new[] { "manifest_sha256", "sha256", "publication_sha256", "row_sha256", "permission_epoch", "readback_nonce" })
            if (!DeviceFileControl.Hash(Text(value, key))) throw Error();
        foreach (var key in new[] { "transfer_id", "source_id", "file_id" }) if (!Id.IsMatch(Text(value, key))) throw Error();
        var kind = Text(value, "media_type");
        if (kind is not ("images" or "video") || !Regex.IsMatch(Text(value, "mime_type"),
            "\\A" + (kind == "images" ? "image/" : "video/") + "[a-z0-9.+-]{1,80}\\z", RegexOptions.CultureInvariant)) throw Error();
    }

    internal static string DestinationToken(JsonObject context)
    { ValidateContext(context); return DeviceFileControl.Digest(DestinationDomain, context); }

    // Pure canonical codec, not a factory for native provider/readback receipts.
    internal static JsonObject EncodeBody(JsonObject context, DeviceTransferBinding binding)
    {
        ValidateContext(context); binding.Validate();
        if (!DeviceFileControl.Identity(binding.SenderId) || !DeviceFileControl.Identity(binding.ReceiverId) ||
            binding.PermissionEpoch != Text(context, "permission_epoch") || binding.DestinationToken != DestinationToken(context)) throw Error();
        var value = context.DeepClone().AsObject();
        value["destination_token"] = binding.DestinationToken;
        value["binding_sha256"] = DeviceFileControl.Digest(BindingDomain, binding.Snapshot());
        value["readback_sha256"] = DeviceFileControl.Digest(ReadbackDomain, value);
        return value;
    }

    internal static RemotePublishedReadback Parse(JsonObject message, JsonObject offer, DeviceTransferBinding binding, string mediaType, long now)
    {
        if (mediaType is not ("images" or "video") || TelefonCrypto.Canonical(message).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes) throw Error();
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]); var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 || Text(message, "kind") != Kind ||
            !TelefonProtocolContract.IsUuidV4(Text(message, "message_id")) || created is < 0 or > 253402300799999 ||
            expires <= created || expires - created > DeviceFileControl.MaximumTtlMs || now >= expires || created > now + 300000) throw Error();
        var body = TelefonProtocolContract.ExactObject(message["body"]!, ContextFields.Concat(new[] { "destination_token", "binding_sha256", "readback_sha256" }).ToArray());
        var context = new JsonObject(ContextFields.Select(key => KeyValuePair.Create(key, body[key]?.DeepClone())));
        if (!JsonNode.DeepEquals(EncodeBody(context, binding), body)) throw Error();
        var manifest = DeviceFileOfferEnvelope.Validate(offer, binding.SenderId, binding.ReceiverId, now);
        var offerCreated = TelefonProtocolContract.Integer(offer["created_ms"]); var offerExpires = TelefonProtocolContract.Integer(offer["expires_ms"]);
        if (now < offerCreated || now >= offerExpires || created < offerCreated || expires > offerExpires || manifest.Files.Count != 1) throw Error();
        var file = manifest.Files[0];
        if (Text(body, "offer_id") != Text(offer, "message_id") || Text(body, "manifest_sha256") != manifest.Fingerprint ||
            Text(body, "transfer_id") != manifest.TransferId || Text(body, "source_id") != manifest.SourceId || Text(body, "file_id") != file.Id ||
            TelefonProtocolContract.Integer(body["size"]) != file.Size || Text(body, "sha256") != file.Sha256 || Text(body, "media_type") != mediaType) throw Error();
        return new(body);
    }
}
