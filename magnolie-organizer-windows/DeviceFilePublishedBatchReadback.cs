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

    internal static RemotePublishedBatchReadback Parse(JsonObject message, JsonObject offer, DeviceTransferBinding binding, string mediaType, long now)
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
        var manifest = DeviceFileOfferEnvelope.Validate(offer, binding.SenderId, binding.ReceiverId, now);
        var members = body["members"]!.AsObject();
        var offerCreated = TelefonProtocolContract.Integer(offer["created_ms"]);
        var offerExpires = TelefonProtocolContract.Integer(offer["expires_ms"]);
        if (now < offerCreated || now >= offerExpires || created < offerCreated || expires > offerExpires ||
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
