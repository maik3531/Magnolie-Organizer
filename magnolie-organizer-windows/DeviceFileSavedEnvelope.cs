using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record RemoteSavedMember(string FileId, long Size, string Sha256, string ReceiptSha256);
internal sealed record RemoteSavedConfirmation(string TransferId, string ManifestSha256, string AcceptanceSha256,
    string PermissionEpoch, string DestinationToken, IReadOnlyList<RemoteSavedMember> Members);

// Remote historical assertion, not a local saved receipt, live presence or grant.
internal static class DeviceFileSavedEnvelope
{
    internal const string Kind = "file_transfer.saved";
    internal static RemoteSavedConfirmation Parse(JsonObject message, DeviceFileManifest manifest, RemoteFileAcceptance accepted, long now)
    {
        static InvalidDataException Error() => new("file_saved_invalid_confirmation");
        static string Text(JsonObject value, string key) => value[key] is JsonValue field && field.TryGetValue<string>(out var text) ? text : throw Error();
        static string Hash(JsonObject value, string key) => DeviceFileControl.Hash(Text(value, key)) ? Text(value, key) : throw Error();
        if (TelefonCrypto.Canonical(message).Length > DeviceFileOfferEnvelope.MaximumApplicationBytes) throw Error();
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]); var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message, "message_id")) || Text(message, "kind") != Kind || created is < 0 or > 253402300799999 ||
            expires <= created || expires - created > DeviceFileControl.MaximumTtlMs || now >= expires || created > now + 300000) throw Error();
        var body = TelefonProtocolContract.ExactObject(message["body"]!, "format", "transfer_id", "manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token", "receipts");
        if (TelefonProtocolContract.Integer(body["format"]) != 1 || Text(body, "transfer_id") != manifest.TransferId || Hash(body, "manifest_sha256") != manifest.Fingerprint ||
            manifest.TransferId != accepted.TransferId || manifest.Fingerprint != accepted.ManifestSha256 || Hash(body, "acceptance_sha256") != accepted.AcceptanceSha256 ||
            Hash(body, "permission_epoch") != accepted.PermissionEpoch || Hash(body, "destination_token") != accepted.DestinationToken ||
            body["receipts"] is not JsonArray receipts || receipts.Count != manifest.Files.Count) throw Error();
        var result = new List<RemoteSavedMember>();
        foreach (var (raw, file) in receipts.Zip(manifest.Files))
        {
            if (raw is not JsonObject receipt) throw Error();
            TelefonProtocolContract.ExactObject(receipt, "file_id", "size", "sha256", "receipt_sha256");
            if (Text(receipt, "file_id") != file.Id || TelefonProtocolContract.Integer(receipt["size"]) != file.Size || Hash(receipt, "sha256") != file.Sha256) throw Error();
            result.Add(new(file.Id, file.Size, file.Sha256, Hash(receipt, "receipt_sha256")));
        }
        return new(manifest.TransferId, manifest.Fingerprint, accepted.AcceptanceSha256, accepted.PermissionEpoch, accepted.DestinationToken, result.AsReadOnly());
    }
}
