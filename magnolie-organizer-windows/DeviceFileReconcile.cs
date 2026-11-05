using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record NativeMediaReconcileMember(string FileId, string PhotoId, string Target, string Action,
    string? BaselineJob, string? BaselineReceipt)
{
    internal bool GrantsWriteAuthority => false;
}
internal sealed record NativeMediaReconcilePlan(string ManifestSha256, string SourceEpoch, string MediaType,
    IReadOnlyList<NativeMediaReconcileMember> Members)
{
    internal bool ProvesDeletion => false;
}

internal sealed partial class TelefonStore
{
    // Plan from the protected LOCAL saved/END records and actual held-file
    // observations. A peer's catalog/absence or a remote Saved hint is not a
    // baseline, native file grant, target reassociation or deletion witness.
    internal NativeMediaReconcilePlan PlanNativeMediaBatch(string peerId, string mediaType, DeviceFileManifest manifest,
        IReadOnlyList<DeviceFileMediaPage> pages, Func<DeviceTransferBinding?> currentBinding, NativeMediaAlbumContext? album = null)
    {
        var media = DeviceFileSources.CorrelateMediaPages(pages, manifest); var first = pages[0];
        MediaDestinationKind(mediaType);
        var destination = ReadNativeMediaDestination(peerId, mediaType) ?? throw DeviceFileControl.Error("file_receive_native_destination_required");
        var binding = currentBinding() ?? throw DeviceFileControl.Error("file_receive_current_binding_required");
        var preferences = ReadNativeMediaPreferences(peerId);
        if (first.MediaType != mediaType || manifest.Files.Count > 16 || binding.DestinationToken != destination.DestinationToken ||
            binding.SenderId != manifest.SenderId || binding.ReceiverId != manifest.ReceiverId)
            throw DeviceFileControl.Error("file_receive_native_media_scope_changed");
        NativeMediaPreferenceScope scope;
        List<ReceiveHead> heads;
        lock (gate)
        {
            scope = MediaPreferenceScope(peerId); using var db = OpenNativeMediaDatabase(); db.Open(); heads = ReceiveHeads(db, null, scope);
        }
        void Current()
        {
            RequireNativeMediaStorageKey();
            if (currentBinding() != binding || ReadNativeMediaDestination(peerId, mediaType) != destination ||
                ReadNativeMediaPreferences(peerId) != preferences || MediaPreferenceScope(peerId) != scope ||
                scope.PeerId != binding.SenderId || scope.PeerKey != binding.SenderIdentitySha256 || scope.LocalId != binding.ReceiverId || scope.LocalKey != binding.ReceiverIdentitySha256 ||
                !(mediaType == "images" ? preferences.PhotosEnabled : preferences.VideosEnabled))
                throw DeviceFileControl.Error("file_receive_native_reconcile_scope_changed");
        }
        Current(); using var root = destination.OpenNative();
        var albumRoot = FindNativeAlbumRoot(peerId, mediaType, destination, first.SourceEpoch);
        using var albumDirectory = albumRoot is null ? null : root.OpenOriginalChild(TelefonMessagingContract.String(albumRoot, "folder"),
            NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject()));
        var publication = albumDirectory ?? root;
        var folder = albumRoot is not null ? TelefonMessagingContract.String(albumRoot, "folder") : album?.DisplayName is null ? "" : album.Folder;
        var newAlbum = albumRoot is null && folder.Length != 0;
        // Read-only name occupancy is not adoption/authority. Actual creation
        // below remains held-handle-relative FILE_CREATE with no replacement.
        var occupiedAlbum = newAlbum && (Directory.Exists(Path.Combine(root.NativePath, folder)) || File.Exists(Path.Combine(root.NativePath, folder)));
        Current();
        var result = new List<NativeMediaReconcileMember>();
        foreach (var (file, entry) in manifest.Files.Zip(media))
        {
            Current();
            var histories = heads.Where(head => head.Body["media"] is JsonObject old &&
                TelefonMessagingContract.String(old, "source_epoch") == first.SourceEpoch &&
                TelefonMessagingContract.String(old, "media_type") == mediaType &&
                TelefonMessagingContract.String(head.Body, "destination_version") == destination.Version &&
                old["entries"]!.AsArray().OfType<JsonObject>().Any(item => TelefonMessagingContract.String(item, "photo_id") == entry.PhotoId) &&
                JsonNode.DeepEquals(head.Body["destination"], new JsonObject { ["native_path"] = destination.NativePath, ["volume_path"] = destination.VolumePath,
                    ["identity"] = NativeMediaReceiveJob.NativeIdentity(destination.RootIdentity), ["token"] = destination.DestinationToken })).ToArray();
            var saved = histories.Where(head => head.Body.ContainsKey("saved") && head.Body.ContainsKey("source_end")).ToArray();
            ReceiveHead? baseline = saved.Length == 1 && histories.Length == 1 ? saved[0] : null;
            var target = file.Path; JsonObject? oldFile = null; JsonObject? oldMember = null; string? receipt = null;
            if (baseline is not null)
            {
                var oldId = baseline.Body["media"]!["entries"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "photo_id") == entry.PhotoId)["file_id"]!.GetValue<string>();
                oldFile = baseline.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == oldId);
                oldMember = baseline.Body["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == oldId);
                target = TelefonMessagingContract.String(oldFile, "path");
                receipt = baseline.Body["saved"]!["receipts"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "file_id") == oldId)["receipt_sha256"]!.GetValue<string>();
            }
            _ = DeviceFileNativeDirectory.ReceiveLeaf(target);
            string action;
            if (album?.DisplayName is not null && histories.Any(head => !head.Body.ContainsKey("album_root"))) action = "pause_legacy_album_mapping";
            else if (occupiedAlbum) action = "pause_unknown_album_root";
            else if (histories.Length != 0 && baseline is null) action = "pause_original_history";
            else
            {
                DeviceFileNativeDirectory.ManagedObservation? observed = null; var unknown = false;
                try { if (!newAlbum) observed = publication.ObserveManagedFile(target, Current); }
                catch (IOException) { unknown = true; }
                catch (InvalidDataException) { unknown = true; }
                Current();
                var association = new NativePhotoAssociation(binding, first.SourceEpoch, entry.PhotoId,
                    DeviceFileControl.Digest("magnolie-windows-media-target-v1\0", new JsonArray(destination.DestinationToken, folder, target)));
                var phone = new NativePhotoObservation("present", new(file.Sha256, file.Size), insertionProven: first.InsertionWitness);
                var managed = observed is not null && oldMember is not null && JsonNode.DeepEquals(NativeMediaReceiveJob.NativeIdentity(observed.Identity), oldMember["identity"]);
                var desktop = unknown ? new NativePhotoObservation("unknown") : observed is null ? new NativePhotoObservation("missing") :
                    new NativePhotoObservation("present", new(observed.Sha256, observed.Size), managed);
                // The original protected identity/root/source are checked above;
                // only the CURRENT live data binding renews comparison authority.
                // No historical permission epoch is promoted to a grant.
                var common = oldFile is null ? null : new NativePhotoBaseline(association,
                    new(TelefonMessagingContract.String(oldFile, "sha256"), TelefonProtocolContract.Integer(oldFile["size"])), receipt!);
                action = PhotoSyncPlan.Compare(association, common, phone, desktop, preferences.ComparisonPolicy, new(CreateDesktop: true)).Kind;
                if (action == "copy_phone_new" && heads.Any(head =>
                    TelefonMessagingContract.String(head.Body["binding"]!.AsObject(), "destination_token") == destination.DestinationToken &&
                    string.Equals(head.Body["album_root"]?["folder"]?.GetValue<string>() ?? "", folder, StringComparison.OrdinalIgnoreCase) &&
                    head.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Any(item => string.Equals(TelefonMessagingContract.String(item, "path"), target, StringComparison.OrdinalIgnoreCase))))
                    action = "pause_original_history";
            }
            result.Add(new(file.Id, entry.PhotoId, folder.Length == 0 ? target : folder + "/" + target, action, baseline?.JobId, receipt));
        }
        Current(); return new(manifest.Fingerprint, first.SourceEpoch, mediaType, result.AsReadOnly());
    }
}
