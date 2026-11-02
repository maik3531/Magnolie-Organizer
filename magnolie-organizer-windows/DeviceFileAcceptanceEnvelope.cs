using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record RemoteFileAcceptance(string OfferId, string ManifestSha256, string TransferId,
    string AcceptanceSha256, string PermissionEpoch, string DestinationToken);

// Pure wire metadata; not native destination admission, a grant or saved receipt.
internal static class DeviceFileAcceptanceEnvelope
{
    internal const string Kind="file_transfer.accept";
    internal static RemoteFileAcceptance Parse(JsonObject message,long now)
    {
        static InvalidDataException Error()=>new("file_accept_invalid_envelope");
        static string Text(JsonObject value,string key)=>value[key] is JsonValue field && field.TryGetValue<string>(out var text)?text:throw Error();
        if (TelefonCrypto.Canonical(message).Length>DeviceFileControl.MaximumWireBytes) throw Error();
        TelefonProtocolContract.ExactObject(message,"type","v","message_id","kind","created_ms","expires_ms","body");
        var created=TelefonProtocolContract.Integer(message["created_ms"]);var expires=TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message,"type")!="message" || TelefonProtocolContract.Integer(message["v"])!=1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message,"message_id")) || Text(message,"kind")!=Kind ||
            created is <0 or >253402300799999 || expires<=created || expires-created>DeviceFileControl.MaximumTtlMs ||
            now>=expires || created>now+300000) throw Error();
        var body=TelefonProtocolContract.ExactObject(message["body"]!,"format","offer_id","manifest_sha256","transfer_id","acceptance_sha256","permission_epoch","destination_token");
        var offer=Text(body,"offer_id");var transfer=Text(body,"transfer_id");
        if (TelefonProtocolContract.Integer(body["format"])!=1 || !TelefonProtocolContract.IsUuidV4(offer) ||
            transfer.Length!=32 || !transfer.All(char.IsAsciiHexDigitLower)) throw Error();
        string Hash(string key)=>DeviceFileControl.Hash(Text(body,key))?Text(body,key):throw Error();
        return new(offer,Hash("manifest_sha256"),transfer,Hash("acceptance_sha256"),Hash("permission_epoch"),Hash("destination_token"));
    }
}
