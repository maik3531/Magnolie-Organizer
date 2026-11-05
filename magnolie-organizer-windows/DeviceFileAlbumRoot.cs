using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaAlbumContext(string SourceEpoch, string? DisplayName)
{
    internal bool GrantsWriteAuthority => false;
    internal string Folder => DeviceFileNativeDirectory.ReceiveLeaf(PhotoDestinationPaths.MediaFolderComponent(DisplayName ?? "Album", "", "Album") + "-" + SourceEpoch[..12]);
}

internal sealed partial class TelefonStore
{
    // The original protected receive records are also the album ownership
    // ledger: reserve BEFORE mkdir, retain its native ID, never adopt a folder
    // from a name or random catalog/album UUID after losing that history.
    private JsonObject? FindNativeAlbumRoot(string peerId, string mediaType, NativeMediaDestination destination, string epoch)
    {
        if (!DeviceFileControl.Hash(epoch)) throw DeviceFileControl.Error("file_receive_album_scope_invalid");
        lock (gate)
        {
            var scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open();
            var roots = ReceiveHeads(db, null, scope).Where(head => head.Body["album_root"] is JsonObject album &&
                TelefonMessagingContract.String(album, "source_epoch") == epoch && TelefonMessagingContract.String(head.Body, "media_type") == mediaType &&
                TelefonMessagingContract.String(head.Body["binding"]!.AsObject(), "destination_token") == destination.DestinationToken &&
                TelefonMessagingContract.String(head.Body, "destination_version") == destination.Version &&
                JsonNode.DeepEquals(head.Body["destination"]!["identity"], NativeMediaReceiveJob.NativeIdentity(destination.RootIdentity)))
                .Select(head => head.Body["album_root"]!.AsObject()).ToArray();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("file_receive_album_scope_changed");
            if (roots.Length == 0) return null;
            if (roots.Any(root => root["identity"] is null || !JsonNode.DeepEquals(root, roots[0])))
                throw DeviceFileControl.Error("file_receive_original_album_history_required");
            return roots[0].DeepClone().AsObject();
        }
    }

    private static bool InitialAlbumIdentity(JsonObject before, JsonObject after)
        => TelefonMessagingContract.String(before, "phase") == "reserved" && TelefonMessagingContract.String(after, "phase") == "reserved" &&
            before["album_root"] is JsonObject old && after["album_root"] is JsonObject current && old["identity"] is null && current["identity"] is JsonObject &&
            JsonNode.DeepEquals(old["source_epoch"], current["source_epoch"]) && JsonNode.DeepEquals(old["folder"], current["folder"]) &&
            before["stage_identity"] is null && after["stage_identity"] is null;

    internal sealed partial class NativeMediaReceiveJob
    {
        private JsonObject? albumRoot;
        private DeviceFileNativeDirectory? albumDirectory;
        private DeviceFileNativeDirectory PublicationRoot => albumDirectory ?? root!;
        private static DeviceFileNativeDirectory.Identity AlbumIdentity(JsonObject value)
        {
            var identity = TelefonProtocolContract.ExactObject(value, "volume", "low", "high");
            ulong Hex(string key)
            {
                var text = TelefonMessagingContract.String(identity, key);
                if (text.Length != 16 || text.Any(c => !char.IsAsciiHexDigitLower(c))) throw DeviceFileControl.Error("file_receive_album_identity_invalid");
                return Convert.ToUInt64(text, 16);
            }
            var result = new DeviceFileNativeDirectory.Identity(Hex("volume"), Hex("low"), Hex("high"));
            if (result.FileIdLow == 0 && result.FileIdHigh == 0) throw DeviceFileControl.Error("file_receive_album_identity_invalid");
            return result;
        }
        internal static DeviceFileNativeDirectory.Identity NativeAlbumIdentity(JsonObject value) => AlbumIdentity(value);
        private static void ValidateAlbumRoot(JsonObject body)
        {
            if (!body.ContainsKey("album_root")) return;
            var album = TelefonProtocolContract.ExactObject(body["album_root"]!, "source_epoch", "folder", "identity");
            if (!DeviceFileControl.Hash(TelefonMessagingContract.String(album, "source_epoch"))) throw DeviceFileControl.Error("file_receive_album_scope_invalid");
            _ = DeviceFileNativeDirectory.ReceiveLeaf(TelefonMessagingContract.String(album, "folder"));
            if (album["identity"] is null)
            {
                if (TelefonMessagingContract.String(body, "phase") != "reserved") throw DeviceFileControl.Error("file_receive_original_album_history_required");
            }
            else if (AlbumIdentity(album["identity"]!.AsObject()).VolumeSerial != AlbumIdentity(body["destination"]!["identity"]!.AsObject()).VolumeSerial)
                throw DeviceFileControl.Error("file_receive_album_volume_changed");
            if (body["media"] is JsonObject media && !JsonNode.DeepEquals(media["source_epoch"], album["source_epoch"]))
                throw DeviceFileControl.Error("file_receive_album_scope_changed");
        }
    }
}
