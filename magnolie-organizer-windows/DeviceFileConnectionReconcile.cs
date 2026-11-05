using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    internal sealed record NativeMediaBatchOutcome(NativeMediaSourceRun Run, NativeMediaReconcilePlan Plan, string? ReceivedJobId)
    {
        internal bool NeedsReview => Plan.Members.Any(item => item.Action is not ("copy_phone_new" or "unchanged" or "keep_local_edit"));
    }

    internal NativeMediaReconcilePlan PlanNativeMediaRun(NativeMediaSourceRun run)
    {
        RequireOwnedMediaRun(run);
        if (run.Resume is not null || run.Transfer is not null || run.OfferedManifest is null || run.OfferedMessageId != run.Result.OfferId || Now() >= run.OfferedExpires)
            throw DeviceFileControl.Error("file_receive_native_preview_required");
        return store.PlanNativeMediaBatch(peer.Id, run.Lease.MediaType, run.OfferedManifest, run.Pages,
            CaptureNativeMediaReceiveBinding(run.Lease.Version, run.Lease.MediaType), new(run.Pages[0].SourceEpoch, run.AlbumMetadata?.DisplayName));
    }

    internal async Task<NativeMediaSourceRun> SelectNativeMediaRunAsync(NativeMediaSourceRun preview, IReadOnlyList<string> fileIds, CancellationToken token = default)
    {
        RequireOwnedMediaRun(preview);
        var choice = CaptureNativeSourceChoice(preview.Lease.MediaType, true, true); var read = NativeSourceReadGuard(choice, preview.Lease.Version);
        var manifest = preview.OfferedManifest ?? throw DeviceFileControl.Error("file_receive_native_preview_required");
        var ids = fileIds.ToArray(); var selected = ids.ToHashSet(StringComparer.Ordinal);
        var originals = manifest.Files.Where(file => selected.Contains(file.Id)).ToArray();
        var media = DeviceFileSources.CorrelateMediaPages(preview.Pages, manifest).Where(entry => selected.Contains(entry.FileId)).ToArray();
        void Require()
        {
            RequireOwnedMediaRun(preview); read();
            if (preview.Resume is not null || preview.Transfer is not null || preview.Result.State != "snapshot_ready" || !preview.Result.SourceIoEnded ||
                preview.OfferedManifest != manifest || preview.OfferedMessageId != preview.Result.OfferId || Now() >= preview.OfferedExpires ||
                ids.Length is < 1 or > 16 || originals.Length != ids.Length || !ids.SequenceEqual(ids.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal)))
                throw DeviceFileControl.Error("file_receive_native_selection_invalid");
        }
        Require();
        var message = DeviceFileSources.CreateRequest("select_run", Now(), preview.Lease.Version, runId: preview.Lease.RunId,
            manifestSha256: manifest.Fingerprint, selectedFileIds: ids, mediaType: preview.Lease.MediaType);
        NativeMediaSourceRun? retained = null;
        await ExchangeNativeSourceCommandAsync<DeviceFileRunResult>(choice, message, DeviceFileSources.RunResultKind,
            raw => DeviceFileSources.ParseRunResult(raw, message["message_id"]!.GetValue<string>(), "select_run", preview.Lease.Version, Now(), expectedMediaType: preview.Lease.MediaType),
            Require, token, accept: (ticket, value) =>
            {
                var result = (DeviceFileRunResult)value;
                if (result.RunId == preview.Lease.RunId || result.Batched != preview.Result.Batched ||
                    preview.Result.BatchEnd is not null && result.BatchEnd != preview.Result.BatchEnd)
                    throw DeviceFileControl.Error("file_receive_native_selection_owner_changed");
                lock (fileRouteGate)
                {
                    var lease = choice.Owner.RetainSourceRun(ticket, result.RunId, result.Version, preview.Lease.MediaType);
                    retained = new(choice.Owner, lease, preview.CatalogId, preview.AlbumId, preview.DesktopChoice, result)
                    { AlbumScope = preview.AlbumScope, SelectedFiles = originals, SelectedMedia = media, AlbumMetadata = preview.AlbumMetadata, AlbumOperation = preview.AlbumOperation };
                    nativeMediaSourceRun = retained; preview.Owner.ReleaseSourceRun(preview.Lease);
                }
            });
        return retained ?? throw DeviceFileControl.Error("file_receive_native_selection_owner_changed");
    }

    private async Task PrepareNativeMediaPreviewAsync(NativeMediaSourceRun run, CancellationToken token)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation, token); deadline.CancelAfter(TimeSpan.FromSeconds(60));
        while (run.Result.State == "preparing")
        {
            await ReadNativeMediaRunAsync(run, deadline.Token);
            if (run.Result.State == "preparing") await Task.Delay(100, deadline.Token);
        }
        if (run.Result.State != "snapshot_ready") throw DeviceFileControl.Error("file_receive_native_snapshot_not_ready");
        while (run.Pages.Count == 0 || run.Pages[^1].NextCursor is not null) await ReadNativeMediaPageAsync(run, deadline.Token);
        if (run.OfferedManifest is null) await OfferNativeMediaRunAsync(run, deadline.Token);
        if (run.OfferedManifest is null) throw DeviceFileControl.Error("file_receive_native_offer_required");
    }

    internal sealed record NativeMediaAlbumOutcome(IReadOnlyList<string> ReceivedJobs, IReadOnlyList<NativeMediaReconcileMember> Members)
    {
        internal bool NeedsReview => Members.Any(item => item.Action is not ("copy_phone_new" or "unchanged" or "keep_local_edit"));
        internal bool ProvesDeletion => false;
    }

    // Explicit native album operation, not a startup/automatic worker. Preserve
    // the original cursor across subset run IDs and stop only this operation's
    // current owner after cancellation; never touch another actor's run.
    internal async Task<NativeMediaAlbumOutcome> SynchronizeNativeMediaAlbumAsync(string sourceVersion, string catalogId,
        string albumId, bool desktopChoice, string mediaType = "images", CancellationToken token = default)
    {
        var operation = new object(); var jobs = new List<string>(); var members = new List<NativeMediaReconcileMember>();
        try
        {
            var run = await StartNativeMediaBatchAsync(sourceVersion, catalogId, albumId, desktopChoice, mediaType, token, operation);
            for (var batch = 0; batch < 50000; batch++)
            {
                using (var snapshot = CancellationTokenSource.CreateLinkedTokenSource(cancellation, token))
                {
                    snapshot.CancelAfter(TimeSpan.FromSeconds(60));
                    while (run.Result.State == "preparing")
                    {
                        await ReadNativeMediaRunAsync(run, snapshot.Token);
                        if (run.Result.State == "preparing") await Task.Delay(100, snapshot.Token);
                    }
                }
                if (run.Result.State == "empty_ready")
                { await CancelNativeMediaRunAsync(run, token); await EndNativeMediaRunAsync(run, token); }
                else
                {
                    var outcome = await ReconcileNativeMediaBatchAsync(run, token); run = outcome.Run;
                    if (members.Count + outcome.Plan.Members.Count > 50000) throw DeviceFileControl.Error("file_receive_native_album_bound");
                    members.AddRange(outcome.Plan.Members); if (outcome.ReceivedJobId is not null) jobs.Add(outcome.ReceivedJobId);
                }
                if (run.Result.BatchEnd is true)
                {
                    await EndNativeMediaAlbumAsync(run, token);
                    return new(jobs.AsReadOnly(), members.AsReadOnly());
                }
                if (run.Result.BatchEnd is not false) throw DeviceFileControl.Error("file_receive_native_album_end_unknown");
                run = await NextNativeMediaBatchAsync(run, token);
            }
            throw DeviceFileControl.Error("file_receive_native_album_bound");
        }
        catch
        {
            // Drain any accepted reply callback before inspecting owned state.
            await fileControlIo.WaitAsync(CancellationToken.None); NativeMediaSourceRun? held;
            try { held = CurrentNativeMediaSourceRun; }
            finally { fileControlIo.Release(); }
            if (held is not null && ReferenceEquals(held.AlbumOperation, operation))
            {
                using var cleanup = CancellationTokenSource.CreateLinkedTokenSource(cancellation); cleanup.CancelAfter(TimeSpan.FromSeconds(15));
                try
                {
                    if (held.Result.RunEnded) await EndNativeMediaAlbumAsync(held, cleanup.Token);
                    else await StopNativeMediaReceiveAsync(held, cleanup.Token);
                }
                catch { /* Original stage/history/source ownership stays held for explicit repair; preserve the original failure. */ }
            }
            throw;
        }
    }

    // Per-batch operation; the returned source reference owns the album cursor
    // after a subset changes the source run ID. Conflicts are not called Saved.
    internal async Task<NativeMediaBatchOutcome> ReconcileNativeMediaBatchAsync(NativeMediaSourceRun run, CancellationToken token = default)
    {
        await PrepareNativeMediaPreviewAsync(run, token);
        var plan = PlanNativeMediaRun(run);
        var copy = plan.Members.Where(member => member.Action == "copy_phone_new").Select(member => member.FileId).Order(StringComparer.Ordinal).ToArray();
        if (copy.Length == 0)
        {
            await CancelNativeMediaRunAsync(run, token); await EndNativeMediaRunAsync(run, token);
            return new(run, plan, null); // No new native job, baseline or fabricated Saved for unchanged/kept/conflicting files.
        }
        if (copy.Length != plan.Members.Count)
        {
            run = await SelectNativeMediaRunAsync(run, copy, token);
            await PrepareNativeMediaPreviewAsync(run, token);
        }
        return new(run, plan, await ReceiveNativeMediaRunAsync(run, token));
    }
}
