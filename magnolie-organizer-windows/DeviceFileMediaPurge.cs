using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Constructed only AFTER the actual native confirmation, never from a bridge
// bool. Bound to one exact selection, current saved book and a short deadline.
internal sealed class NativeMediaPermanentConsent
{
    private readonly NativeMediaBookPermit permit;
    private readonly NativeMediaTrashEntry selection;
    private readonly long issued = Environment.TickCount64;
    private long last;
    private bool revoked;
    private NativeMediaPermanentConsent(NativeMediaBookPermit permit, NativeMediaTrashEntry selection)
    { this.permit = permit; this.selection = selection; last = issued; Require(permit, selection); }
    internal static NativeMediaPermanentConsent FromConfirmedNativeChoice(NativeMediaBookPermit permit, NativeMediaTrashEntry selection)
        => new(permit, selection);
    internal void Require(NativeMediaBookPermit current, NativeMediaTrashEntry selected)
    {
        lock (this)
        {
            try
            {
                var now = Environment.TickCount64;
                if (revoked || !ReferenceEquals(permit, current) || selection != selected || now < last || now - issued >= 60000)
                    throw DeviceFileControl.Error("media_trash_native_confirmation_required");
                permit.Require(); last = now;
            }
            catch { revoked = true; throw; }
        }
    }
}

internal sealed partial class TelefonStore
{
    internal sealed record NativeMediaTrashItem(NativeMediaTrashEntry Entry, string DisplayName, string MediaType);

    internal IReadOnlyList<NativeMediaTrashItem> NativeMediaTrashItems(string peerId)
    {
        lock (gate)
        {
            RequireNativeMediaStorageKey(); var scope = MediaPreferenceScope(peerId);
            using var db = OpenNativeMediaDatabase(); db.Open(); var jobs = ReceiveHeads(db, null, scope);
            var items = ReadMediaTrash(db, null, scope).Select(head =>
            {
                var job = jobs.SingleOrDefault(item => item.JobId == head.Entry.JobId && item.Version == TelefonMessagingContract.String(head.Body, "job_version"))
                    ?? throw DeviceFileControl.Error("media_trash_original_saved_job_required");
                var file = job.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(item => TelefonMessagingContract.String(item, "id") == head.Entry.FileId);
                return new NativeMediaTrashItem(head.Entry, DeviceFileNativeDirectory.ReceiveLeaf(TelefonMessagingContract.String(file, "path")), TelefonMessagingContract.String(job.Body, "media_type"));
            }).OrderByDescending(item => item.Entry.ChangedMs).ThenBy(item => item.Entry.Operation, StringComparer.Ordinal).ToArray();
            if (MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_trash_scope_changed");
            return items;
        }
    }

    internal static bool NativeMediaTrashExpired(NativeMediaTrashEntry entry, NativeMediaBookPermit permit, long now)
    {
        permit.Require();
        return permit.TrashEnabled && permit.RetentionDays > 0 && entry.State is "trashed" or "purge_prepared" &&
            now >= entry.ChangedMs && now <= DeviceFileControl.MaximumRevision && now - entry.ChangedMs >= permit.RetentionDays * 86400000L;
    }

    internal NativeMediaTrashEntry PurgeNativeMediaTrash(string peerId, NativeMediaTrashEntry selected, NativeMediaBookPermit permit,
        NativeMediaPermanentConsent? consent = null, long? retentionNow = null, CancellationToken token = default)
    {
        lock (gate)
        {
            if (selected.State is not ("trashed" or "purge_prepared")) throw DeviceFileControl.Error("media_trash_original_operation_required");
            var scope = MediaPreferenceScope(peerId); var revoked = false;
            void Current()
            {
                try
                {
                    token.ThrowIfCancellationRequested();
                    if (revoked || MediaPreferenceScope(peerId) != scope) throw DeviceFileControl.Error("media_trash_scope_changed");
                    RequireNativeMediaStorageKey(); permit.Require();
                    if (consent is not null) consent.Require(permit, selected);
                    else if (!NativeMediaTrashExpired(selected, permit, retentionNow ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()))
                        throw DeviceFileControl.Error("media_trash_retention_or_confirmation_required");
                }
                catch { revoked = true; throw; }
            }
            Current(); using var db = OpenNativeMediaDatabase(); db.Open();
            var original = ReadMediaTrash(db, null, scope).SingleOrDefault(head => head.Entry == selected)
                ?? throw DeviceFileControl.Error("media_trash_stale_selection");
            var heads = ReceiveHeads(db, null, scope);
            var job = heads.SingleOrDefault(head => head.JobId == selected.JobId && head.Version == TelefonMessagingContract.String(original.Body, "job_version"))
                ?? throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            if (!job.Body.ContainsKey("saved") || !job.Body.ContainsKey("source_end")) throw DeviceFileControl.Error("media_trash_original_saved_job_required");
            var manifest = job.Body["manifest"]!["files"]!.AsArray().OfType<JsonObject>().Single(file => TelefonMessagingContract.String(file, "id") == selected.FileId);
            var member = job.Body["files"]!.AsArray().OfType<JsonObject>().Single(file => TelefonMessagingContract.String(file, "id") == selected.FileId);
            var destinationOwner = new NativeCompletedDestinationOwner(this, scope, job);
            var destination = destinationOwner.Destination;
            using var root = destination.OpenNative();
            using var album = job.Body["album_root"] is JsonObject albumRoot
                ? root.OpenOriginalChild(TelefonMessagingContract.String(albumRoot, "folder"), NativeMediaReceiveJob.NativeAlbumIdentity(albumRoot["identity"]!.AsObject())) : null;
            var parent = album ?? root;
            void Bound()
            {
                Current(); _ = root.CurrentIdentity(); _ = parent.CurrentIdentity();
                destinationOwner.Require();
                // A preserved replacement original is not disposable until the
                // NEW job earned local Saved AND its correlated source END.
                if (ReceiveHeads(db, null, scope).Any(head => head.Body["replacements"] is JsonArray records &&
                    records.OfType<JsonObject>().Any(link => TelefonMessagingContract.String(link, "trash_operation") == selected.Operation) &&
                    (!head.Body.ContainsKey("saved") || !head.Body.ContainsKey("source_end"))))
                    throw DeviceFileControl.Error("media_trash_replacement_still_held");
            }
            var name = ".magnolie-trash-" + selected.Operation;
            Bound();
            var identity = parent.ExistingFileIdentity(name);
            // Missing original BEFORE preparation is not evidence of our
            // removal. A foreign occupied name is never removed on recovery.
            if (identity is null && selected.State != "purge_prepared") throw DeviceFileControl.Error("media_trash_original_file_required");
            if (identity is not null)
            {
                using var held = parent.OpenOriginalStagedFile(name, NativeMediaReceiveJob.NativeAlbumIdentity(member["identity"]!.AsObject()),
                    TelefonProtocolContract.Integer(manifest["size"]), TelefonMessagingContract.String(manifest, "sha256"));
                Bound();
                if (selected.State == "trashed")
                {
                    var preparing = original.Body.DeepClone().AsObject(); preparing["state"] = "purge_prepared"; preparing["previous_version"] = selected.Version;
                    original = AppendMediaTrash(scope, selected.Operation, selected.Version, preparing, Bound);
                }
                held.RemoveOriginal(Bound);
            }
            Bound();
            if (parent.ExistingFileIdentity(name) is not null) throw DeviceFileControl.Error("media_trash_removal_readback_failed");
            var completed = original.Body.DeepClone().AsObject(); completed["state"] = "purged"; completed["previous_version"] = original.Entry.Version;
            return AppendMediaTrash(scope, selected.Operation, original.Entry.Version, completed, Bound).Entry;
        }
    }
}

internal sealed record NativeMediaRemovalChoice(string PeerId, TelefonStore.NativeMediaTrashItem Item, NativeMediaBookPermit Permit);

internal sealed partial class TelefonCoordinator
{
    private NativeMediaBookPermit NativeMediaLocalBookPermit()
        => NativeMediaBookPermit.Capture(NativeProducerBook() ?? throw DeviceFileControl.Error("file_media_current_saved_book_required"), NativeSavedBook);

    internal IReadOnlyList<TelefonStore.NativeMediaTrashItem> ReadNativeMediaTrashUi(string peerId)
    {
        var permit = NativeMediaLocalBookPermit(); var items = store.NativeMediaTrashItems(peerId); permit.Require(); return items;
    }

    private TelefonStore.NativeMediaTrashItem SelectedNativeMediaTrash(string peerId, string operation, string version)
        => store.NativeMediaTrashItems(peerId).SingleOrDefault(item => item.Entry.Operation == operation && item.Entry.Version == version)
            ?? throw DeviceFileControl.Error("media_trash_stale_selection");

    internal NativeMediaRemovalChoice PrepareNativeMediaRemovalChoice(string peerId, string operation, string version)
    {
        var permit = NativeMediaLocalBookPermit(); var item = SelectedNativeMediaTrash(peerId, operation, version);
        if (item.Entry.State is not ("trashed" or "purge_prepared")) throw DeviceFileControl.Error("media_trash_original_operation_required");
        permit.Require(); return new(peerId, item, permit);
    }

    internal NativeMediaTrashEntry RemoveConfirmedNativeMediaTrash(NativeMediaRemovalChoice choice, NativeMediaPermanentConsent consent)
        => NativeMediaLocalOperation(() => store.PurgeNativeMediaTrash(choice.PeerId, choice.Item.Entry, choice.Permit, consent));

    internal NativeMediaTrashEntry RestoreNativeMediaTrashUi(string peerId, string operation, string version)
        => NativeMediaLocalOperation(() =>
        {
            var permit = NativeMediaLocalBookPermit(); var item = SelectedNativeMediaTrash(peerId, operation, version);
            bool Current() { permit.Require(); return true; }
            return item.Entry.State == "prepared" ? store.RecoverNativeMediaTrashOperation(peerId, item.Entry, Current)
                : store.RestoreNativeMediaTrash(peerId, item.Entry, Current);
        });

    private T NativeMediaLocalOperation<T>(Func<T> action)
    {
        if (Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0) throw DeviceFileControl.Error("file_media_native_worker_busy");
        try { return action(); }
        finally { Interlocked.Exchange(ref nativeMediaWorker, 0); }
    }

    internal int SweepNativeMediaTrashFromSavedBook(string peerId, CancellationToken token = default)
    {
        var permit = NativeMediaLocalBookPermit();
        if (!permit.TrashEnabled || permit.RetentionDays == 0 || Interlocked.CompareExchange(ref nativeMediaWorker, 1, 0) != 0) return 0;
        try
        {
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var removed = 0;
            foreach (var entry in store.NativeMediaTrashHistory(peerId).Where(item => TelefonStore.NativeMediaTrashExpired(item, permit, now)).Take(16))
            {
                token.ThrowIfCancellationRequested(); permit.Require();
                try { store.PurgeNativeMediaTrash(peerId, entry, permit, retentionNow: now, token: token); removed++; }
                catch (Exception error) when (error is IOException or InvalidDataException)
                { permit.Require(); /* This exact original stays HOLD; never delete a substitute. */ }
            }
            return removed;
        }
        finally { Interlocked.Exchange(ref nativeMediaWorker, 0); }
    }
}
