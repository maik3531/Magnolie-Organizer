using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class DeviceFileControlEnvelope
{
    internal static JsonObject Create(DeviceFileControlPacket packet, long now)
    {
        var message = new JsonObject { ["type"] = "message", ["v"] = 1,
            ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = DeviceFileControl.Kind,
            ["created_ms"] = now, ["expires_ms"] = checked(now + DeviceFileControl.MaximumTtlMs), ["body"] = packet.Wire() };
        Validate(message, now);
        return message;
    }

    internal static DeviceFileControlPacket Validate(JsonObject message, long now)
    {
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]);
        var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (now is < 0 or > 253402300799999 || created is < 0 or > 253402300799999 ||
            TelefonMessagingContract.String(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            TelefonMessagingContract.String(message, "kind") != DeviceFileControl.Kind ||
            !TelefonProtocolContract.IsUuidV4(TelefonMessagingContract.String(message, "message_id")) ||
            expires <= created || expires - created > DeviceFileControl.MaximumTtlMs || now >= expires || created > now + 300000 ||
            TelefonCrypto.Canonical(message).Length > DeviceFileControl.MaximumWireBytes || message["body"] is not JsonObject)
            throw DeviceFileControl.Error("file_control_invalid_envelope");
        return DeviceFileControlPacket.Parse(message["body"]!.AsObject());
    }
}
