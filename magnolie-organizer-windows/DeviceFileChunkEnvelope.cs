using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record DeviceFileChunkRequest(string RequestId, long Expires, string TransferId, string ManifestSha256,
    string AcceptanceSha256, string PermissionEpoch, string DestinationToken, string FileId, int ChunkIndex);

// Strict metadata/data preflight only. No native receiver admission or disk write.
internal static class DeviceFileChunkEnvelope
{
    internal const string RequestKind = "file_transfer.chunk.request";
    internal const string ResultKind = "file_transfer.chunk";
    private static readonly string[] Fields = ["format", "transfer_id", "manifest_sha256", "acceptance_sha256", "permission_epoch", "destination_token", "file_id", "chunk_index"];
    private static InvalidDataException Error() => new("file_chunk_invalid_message");
    private static string Text(JsonObject value, string key) => value[key] is JsonValue field && field.TryGetValue<string>(out var text) ? text : throw Error();
    private static string Hash(JsonObject value, string key) => DeviceFileControl.Hash(Text(value, key)) ? Text(value, key) : throw Error();
    private static string Id(JsonObject value, string key)
    {
        var id = Text(value, key);
        return id.Length == 32 && id.All(char.IsAsciiHexDigitLower) ? id : throw Error();
    }
    private static JsonObject Body(JsonObject message, string kind, long now, int budget)
    {
        if (TelefonCrypto.Canonical(message).Length > budget) throw Error();
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]); var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message, "type") != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 || !TelefonProtocolContract.IsUuidV4(Text(message, "message_id")) ||
            Text(message, "kind") != kind || created is < 0 or > 253402300799999 || expires <= created || expires - created > DeviceFileControl.MaximumTtlMs ||
            now >= expires || created > now + 300000 || message["body"] is not JsonObject body || TelefonProtocolContract.Integer(body["format"]) != 1) throw Error();
        return body;
    }
    internal static DeviceFileChunkRequest ParseRequest(JsonObject message, long now)
    {
        var body = Body(message, RequestKind, now, DeviceFileControl.MaximumWireBytes);
        TelefonProtocolContract.ExactObject(body, Fields);
        var index = TelefonProtocolContract.Integer(body["chunk_index"]);
        if (index < 0 || index >= DeviceFileManifest.MaxFileBytes / DeviceFileManifest.ChunkBytes) throw Error();
        return new(Text(message, "message_id"), TelefonProtocolContract.Integer(message["expires_ms"]), Id(body, "transfer_id"),
            Hash(body, "manifest_sha256"), Hash(body, "acceptance_sha256"), Hash(body, "permission_epoch"), Hash(body, "destination_token"), Id(body, "file_id"), (int)index);
    }
    internal static byte[] ParseResponse(JsonObject message, JsonObject request, DeviceFileManifest manifest, RemoteFileAcceptance accepted, long now)
    {
        var expected = ParseRequest(request, now);
        var body = Body(message, ResultKind, now, DeviceFileOfferEnvelope.MaximumApplicationBytes);
        TelefonProtocolContract.ExactObject(body, Fields.Concat(["request_id", "data_base64", "data_sha256"]).ToArray());
        if (Text(body, "request_id") != expected.RequestId || Id(body, "transfer_id") != expected.TransferId ||
            Hash(body, "manifest_sha256") != expected.ManifestSha256 || Hash(body, "acceptance_sha256") != expected.AcceptanceSha256 ||
            Hash(body, "permission_epoch") != expected.PermissionEpoch || Hash(body, "destination_token") != expected.DestinationToken ||
            Id(body, "file_id") != expected.FileId || TelefonProtocolContract.Integer(body["chunk_index"]) != expected.ChunkIndex ||
            manifest.TransferId != accepted.TransferId || manifest.Fingerprint != accepted.ManifestSha256 ||
            expected.TransferId != accepted.TransferId || expected.ManifestSha256 != accepted.ManifestSha256 ||
            expected.AcceptanceSha256 != accepted.AcceptanceSha256 || expected.PermissionEpoch != accepted.PermissionEpoch || expected.DestinationToken != accepted.DestinationToken) throw Error();
        var file = manifest.Files.SingleOrDefault(value => value.Id == expected.FileId) ?? throw Error();
        var length = Math.Min(DeviceFileManifest.ChunkBytes, file.Size - (long)expected.ChunkIndex * DeviceFileManifest.ChunkBytes);
        if (length <= 0) throw Error();
        var encoded = Text(body, "data_base64"); byte[] bytes;
        try { bytes = Convert.FromBase64String(encoded); }
        catch (FormatException) { throw Error(); }
        if (bytes.Length != length || Convert.ToBase64String(bytes) != encoded ||
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() != Hash(body, "data_sha256")) throw Error();
        return bytes; // Caller must still check actual native grants and durable staging/readback.
    }
}
