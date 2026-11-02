using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Complete application-envelope preflight, deliberately not registered or
// advertised until actual dedicated consent and transfer handlers exist.
internal static class DeviceFileOfferEnvelope
{
    internal const string Kind = "file_transfer.offer";
    internal const int MaximumApplicationBytes = 262144;
    internal const long MaximumTtlMs = 60000;

    internal static JsonObject Create(DeviceFileManifest manifest, long now, string? messageId = null, long ttlMs = MaximumTtlMs)
    {
        if (ttlMs is < 1 or > MaximumTtlMs) throw new InvalidDataException("file_offer_invalid_ttl");
        var files = new JsonArray(manifest.Files.Select(file => (JsonNode)new JsonObject
        { ["id"] = file.Id, ["path"] = file.Path, ["size"] = file.Size, ["sha256"] = file.Sha256 }).ToArray());
        var wire = new JsonObject
        {
            ["format"] = 1, ["transfer_id"] = manifest.TransferId, ["source_id"] = manifest.SourceId,
            ["sender_id"] = manifest.SenderId, ["receiver_id"] = manifest.ReceiverId,
            ["chunk_bytes"] = DeviceFileManifest.ChunkBytes, ["total_bytes"] = manifest.TotalBytes, ["files"] = files
        };
        var message = new JsonObject
        {
            ["type"] = "message", ["v"] = 1, ["message_id"] = messageId ?? Guid.NewGuid().ToString("D"),
            ["kind"] = Kind, ["created_ms"] = now, ["expires_ms"] = checked(now + ttlMs),
            ["body"] = new JsonObject { ["version"] = 1, ["manifest"] = wire, ["manifest_sha256"] = manifest.Fingerprint }
        };
        Validate(message, manifest.SenderId, manifest.ReceiverId, now);
        return message;
    }

    // Called after the existing bounded strict/canonical transport decoder.
    // A valid offer is NOT permission to accept/save files or acquire a target.
    internal static DeviceFileManifest Validate(JsonObject message, string senderId, string receiverId, long now)
    {
        if (TelefonCrypto.Canonical(message).Length > MaximumApplicationBytes)
            throw new InvalidDataException("file_offer_envelope_too_large");
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]);
        var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (TelefonMessagingContract.String(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(message, "message_id")) ||
            TelefonMessagingContract.String(message, "kind") != Kind || created is < 0 or > 253402300799999 ||
            expires <= created || expires - created > MaximumTtlMs || now > expires + 300000 || created > now + 300000)
            throw new InvalidDataException("file_offer_invalid_envelope");
        var body = TelefonProtocolContract.ExactObject(message["body"]!, "version", "manifest", "manifest_sha256");
        if (TelefonProtocolContract.Integer(body["version"]) != 1) throw new InvalidDataException("file_offer_invalid_envelope");
        using var document = JsonDocument.Parse(body["manifest"]?.ToJsonString() ?? "null");
        var manifest = DeviceFileManifest.Parse(document.RootElement);
        if (manifest.SenderId != senderId || manifest.ReceiverId != receiverId ||
            TelefonMessagingContract.String(body, "manifest_sha256") != manifest.Fingerprint)
            throw new InvalidDataException("file_offer_manifest_binding_changed");
        return manifest;
    }
}
