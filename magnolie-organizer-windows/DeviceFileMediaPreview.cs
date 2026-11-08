using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaPreviewRaster(string MimeType, int Width, int Height, string DataBase64);

// Native renderer receives only verified bytes, never a path/URI or write owner.
internal delegate NativeMediaPreviewRaster NativeMediaPreviewRenderer(byte[] bytes, string kind, int side, Action current);

internal static class NativeMediaPreviewBytes
{
    internal const int MaximumBytes = 16 * 1024 * 1024;
    internal static NativeMediaPreviewRaster Read(DeviceFileNativeDirectory.DeviceFileNativeStagedFile held,
        long size, string hash, string kind, int side, Action current, NativeMediaPreviewRenderer renderer)
    {
        current();
        if (size is < 1 or > MaximumBytes || side is not (192 or 1024) || kind is not ("images" or "video"))
            throw DeviceFileControl.Error("media_preview_bound");
        var before = NativeMediaBackupBytes.Verify(held, size, hash, current);
        var bytes = new byte[(int)size];
        try
        {
            for (var offset = 0; offset < bytes.Length;)
            {
                current(); var chunk = held.ReadExact(offset, Math.Min(DeviceFileManifest.ChunkBytes, bytes.Length - offset));
                try { chunk.CopyTo(bytes, offset); offset += chunk.Length; }
                finally { CryptographicOperations.ZeroMemory(chunk); }
            }
            current(); var result = renderer(bytes, kind, side, current); current();
            if (result.MimeType is not ("image/png" or "image/jpeg") || result.Width < 1 || result.Height < 1 ||
                Math.Max(result.Width, result.Height) > side || result.DataBase64.Length > 699052)
                throw DeviceFileControl.Error("media_preview_raster_bound");
            if (NativeMediaBackupBytes.Verify(held, size, hash, current) != before)
                throw DeviceFileControl.Error("media_preview_original_changed");
            current(); return result;
        }
        finally { CryptographicOperations.ZeroMemory(bytes); }
    }
}

internal sealed partial class TelefonStore
{
    internal NativeMediaPreviewRaster PreviewNativeMediaTrash(string peerId, NativeMediaTrashEntry selected,
        Func<bool> nativePermit, int side, NativeMediaPreviewRenderer renderer)
    {
        lock (gate)
        {
            if (selected.State is not ("prepared" or "trashed" or "restore_prepared" or "purge_prepared"))
                throw DeviceFileControl.Error("media_trash_original_operation_required");
            var scope = MediaPreferenceScope(peerId); var revoked = false;
            void Current()
            {
                try
                {
                    if (revoked || !nativePermit() || MediaPreferenceScope(peerId) != scope)
                        throw DeviceFileControl.Error("media_trash_native_permit_changed");
                    RequireNativeMediaStorageKey();
                }
                catch { revoked = true; throw; }
            }
            Current(); using var db = OpenNativeMediaDatabase(); db.Open();
            var original = ReadMediaTrash(db, null, scope).SingleOrDefault(head => head.Entry == selected)
                ?? throw DeviceFileControl.Error("media_trash_stale_selection");
            var job = ReceiveHeads(db, null, scope).SingleOrDefault(head => head.JobId == selected.JobId &&
                head.Version == TelefonMessagingContract.String(original.Body, "job_version"))
                ?? throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            if (!job.Body.ContainsKey("saved") || !job.Body.ContainsKey("source_end"))
                throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            var file = job.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>()
                .Single(item => TelefonMessagingContract.String(item, "id") == selected.FileId);
            var member = job.Body["files"]!.AsArray().OfType<JsonObject>()
                .Single(item => TelefonMessagingContract.String(item, "id") == selected.FileId);
            var kind = TelefonMessagingContract.String(job.Body, "media_type");
            var destination = ReadNativeMediaDestination(peerId, kind) ?? throw DeviceFileControl.Error("media_trash_original_destination_required");
            if (destination.Version != TelefonMessagingContract.String(job.Body, "destination_version") ||
                destination.DestinationToken != TelefonMessagingContract.String(job.Body["binding"]!.AsObject(), "destination_token"))
                throw DeviceFileControl.Error("media_trash_original_destination_required");
            using var root = destination.OpenNative();
            using var album = job.Body["album_root"] is JsonObject albumRoot ? root.OpenOriginalChild(
                TelefonMessagingContract.String(albumRoot, "folder"), NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject())) : null;
            var parent = album ?? root;
            void Bound()
            {
                Current(); _ = root.CurrentIdentity(); _ = parent.CurrentIdentity();
                if (ReadNativeMediaDestination(peerId, kind) != destination ||
                    ReadMediaTrash(db, null, scope).SingleOrDefault(head => head.Entry.Operation == selected.Operation)?.Entry != selected)
                    throw DeviceFileControl.Error("media_trash_stale_selection");
            }
            Bound();
            // Only the retained trash name. An unmoved prepared original or an
            // already removed purge payload is NOT recreated for viewing.
            using var held = parent.OpenOriginalStagedFile(".magnolie-trash-" + selected.Operation,
                NativeMediaReceiveJob.NativeAlbumIdentity(member["identity"]!.AsObject()),
                TelefonProtocolContract.Integer(file["size"]), TelefonMessagingContract.String(file, "sha256"));
            return NativeMediaPreviewBytes.Read(held, TelefonProtocolContract.Integer(file["size"]),
                TelefonMessagingContract.String(file, "sha256"), kind, side, Bound, renderer);
        }
    }
}

internal sealed partial class TelefonCoordinator
{
    internal NativeMediaPreviewRaster PreviewNativeMediaTrashUi(string peerId, string operation, string version,
        int side, NativeMediaPreviewRenderer renderer)
    {
        var permit = NativeMediaLocalBookPermit(); var item = SelectedNativeMediaTrash(peerId, operation, version);
        return NativeMediaLocalOperation(() => store.PreviewNativeMediaTrash(peerId, item.Entry,
            () => { permit.Require(); return true; }, side, renderer));
    }
}
