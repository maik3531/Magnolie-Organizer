using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    // Reference-owned native metadata; neither a browser token nor receive consent.
    internal sealed class NativeMediaSourceRun
    {
        internal readonly NativeFileControlSession Owner;
        internal readonly NativeFileControlSession.SourceRunLease Lease;
        internal readonly string CatalogId, AlbumId;
        internal readonly bool DesktopChoice;
        internal readonly List<DeviceFileMediaPage> Pages = [];
        internal (string SourceEpoch, string MediaType, bool InsertionWitness)? AlbumScope;
        internal NativeMediaResumeLookup? Resume;
        internal DeviceFileManifest? OfferedManifest { get; private set; }
        internal string? OfferedMessageId { get; private set; }
        internal long OfferedExpires { get; private set; }
        internal DeviceFileRunResult Result { get; private set; }
        internal NativeMediaSourceRun(NativeFileControlSession owner, NativeFileControlSession.SourceRunLease lease,
            string catalogId, string albumId, bool desktopChoice, DeviceFileRunResult result)
        { Owner = owner; Lease = lease; CatalogId = catalogId; AlbumId = albumId; DesktopChoice = desktopChoice; Result = result; }
        internal bool GrantsReadAuthority => false;
        internal void Update(DeviceFileRunResult result) => Result = result;
        internal void RememberOffer(DeviceFileManifest? manifest, string? messageId = null, long expires = 0)
        { OfferedManifest = manifest; OfferedMessageId = messageId; OfferedExpires = expires; }
    }
    private NativeMediaSourceRun? nativeMediaSourceRun, nativeEndedMediaBatch;

    internal NativeMediaSourceRun? CurrentNativeMediaSourceRun
    {
        get { lock (fileRouteGate) return nativeMediaSourceRun ?? nativeEndedMediaBatch; }
    }

    private void RequireOwnedMediaRun(NativeMediaSourceRun run, bool ended = false)
    {
        RequireNativeFileControls(run.Owner);
        lock (fileRouteGate)
            if (!ReferenceEquals(ended ? nativeEndedMediaBatch : nativeMediaSourceRun, run))
                throw DeviceFileControl.Error("file_sources_native_original_run_required");
    }

    internal async Task<NativeMediaSourceRun> StartNativeMediaBatchAsync(string expectedVersion, string catalogId,
        string albumId, bool desktopChoice, string mediaType = "images", CancellationToken token = default)
    {
        var choice = CaptureNativeSourceChoice(mediaType, true, true); var read = NativeSourceReadGuard(choice, expectedVersion);
        void Require()
        {
            read();
            lock (fileRouteGate)
                if (nativeMediaSourceRun is not null || nativeEndedMediaBatch is not null)
                    throw DeviceFileControl.Error("file_sources_native_original_run_pending");
        }
        Require();
        var message = DeviceFileSources.CreateRequest("batch_run", Now(), expectedVersion, catalogId: catalogId,
            albumId: albumId, desktopChoice: desktopChoice, mediaType: mediaType);
        NativeMediaSourceRun? retained = null;
        await ExchangeNativeSourceCommandAsync<DeviceFileRunResult>(choice, message, DeviceFileSources.RunResultKind,
            raw => DeviceFileSources.ParseRunResult(raw, message["message_id"]!.GetValue<string>(), "batch_run", expectedVersion, Now(), expectedMediaType: mediaType),
            Require, token, accept: (ticket, value) =>
            {
                var result = (DeviceFileRunResult)value;
                lock (fileRouteGate)
                {
                    var lease = choice.Owner.RetainSourceRun(ticket, result.RunId, result.Version, mediaType);
                    retained = new(choice.Owner, lease, catalogId, albumId, desktopChoice, result);
                    nativeMediaSourceRun = retained;
                }
            });
        return retained ?? throw DeviceFileControl.Error("file_sources_native_original_run_required");
    }

    internal Task<DeviceFileRunResult> ReadNativeMediaRunAsync(NativeMediaSourceRun run, CancellationToken token = default)
        => ExchangeOwnedMediaRunAsync(run, run.Resume is null ? "run_status" : "resume_status", token);
    internal Task<DeviceFileRunResult> CancelNativeMediaRunAsync(NativeMediaSourceRun run, CancellationToken token = default)
        => ExchangeOwnedMediaRunAsync(run, run.Resume is null ? "cancel_run" : "cancel_resume", token);
    internal Task<DeviceFileRunResult> OfferNativeMediaRunAsync(NativeMediaSourceRun run, CancellationToken token = default)
        => ExchangeOwnedMediaRunAsync(run, run.Resume is null ? "offer_run" : "offer_resume", token);
    internal Task<DeviceFileRunResult> EndNativeMediaRunAsync(NativeMediaSourceRun run, CancellationToken token = default)
        => ExchangeOwnedMediaRunAsync(run, run.Resume is null ? "end_run" : "end_resume", token);
    internal Task<DeviceFileRunResult> EndNativeMediaAlbumAsync(NativeMediaSourceRun run, CancellationToken token = default)
        => ExchangeOwnedMediaRunAsync(run, "end_album", token);

    private async Task<DeviceFileRunResult> ExchangeOwnedMediaRunAsync(NativeMediaSourceRun run, string operation, CancellationToken token)
    {
        var ended = operation == "end_album"; var offering = operation is "offer_run" or "offer_resume";
        var cleanup = !offering;
        RequireOwnedMediaRun(run, ended);
        // Cleanup deliberately bypasses saved positive choice/root/data/video
        // readiness: only this retained source lease can address this exact run.
        var choice = cleanup ? new NativeSourceChoice(run.Owner, run.Lease.MediaType,
            new NativeMediaPreferences(0, null, false, false, false), null, false, false, null) :
            CaptureNativeSourceChoice(run.Lease.MediaType, true, true);
        var read = cleanup ? null : NativeSourceReadGuard(choice, run.Lease.Version);
        void Require()
        {
            RequireOwnedMediaRun(run, ended); read?.Invoke();
            var state = run.Result;
            if (offering && (state.State != "snapshot_ready" || !state.SourceIoEnded) ||
                offering && run.Pages.Count != 0 && run.Pages[^1].NextCursor is not null ||
                operation == "offer_resume" && run.Pages.Count == 0 ||
                (operation is "end_run" or "end_resume") && !state.SourceIoEnded || ended && (!state.RunEnded || run.Resume is not null))
                throw DeviceFileControl.Error("file_sources_native_run_not_quiescent");
        }
        Require();
        if (offering) lock (fileRouteGate) run.RememberOffer(null);
        var message = DeviceFileSources.CreateRequest(operation, Now(), run.Lease.Version, runId: run.Lease.RunId, mediaType: run.Lease.MediaType);
        return await ExchangeNativeSourceCommandAsync<DeviceFileRunResult>(choice, message, DeviceFileSources.RunResultKind,
            raw => DeviceFileSources.ParseRunResult(raw, message["message_id"]!.GetValue<string>(), operation, run.Lease.Version, Now(), run.Lease.RunId, run.Lease.MediaType),
            Require, token, cleanup ? run.Lease : null, accept: (ticket, value) =>
            {
                var result = (DeviceFileRunResult)value;
                lock (fileRouteGate)
                {
                    var old = run.Result;
                    if (offering && run.Pages.Count != 0 && result.ManifestSha256 != run.Pages[0].ManifestSha256)
                        throw DeviceFileControl.Error("file_sources_native_offer_manifest_changed");
                    if (offering && NativeSourceOfferedManifest(ticket) is { } offered)
                    {
                        DeviceFileSources.CorrelateMediaPages(run.Pages, offered.Manifest);
                        run.RememberOffer(offered.Manifest, result.OfferId, offered.Expires);
                    }
                    if (!result.RunEnded && (old.Batched != result.Batched || old.Batched && old.BatchEnd is not null && old.BatchEnd != result.BatchEnd) ||
                        old.SourceIoEnded && !result.SourceIoEnded ||
                        (old.State is "cancel_pending" or "canceled_held") && result.State is not ("cancel_pending" or "canceled_held") ||
                        (old.State is "failed_held" or "empty_ready") && result.State != old.State && result.State != "canceled_held")
                        throw DeviceFileControl.Error("file_sources_native_run_state_rollback");
                    // END replies omit batch_end; retain album cursor provenance.
                    run.Update(result.RunEnded ? result with { Batched = old.Batched, BatchEnd = old.BatchEnd } : result);
                    if (operation is "end_run" or "end_resume")
                    {
                        nativeMediaSourceRun = null;
                        if (old.Batched) nativeEndedMediaBatch = run;
                        else run.Owner.ReleaseSourceRun(run.Lease);
                    }
                    else if (ended)
                    {
                        nativeEndedMediaBatch = null; run.Owner.ReleaseSourceRun(run.Lease);
                    }
                }
            });
    }

    internal async Task<NativeMediaSourceRun> NextNativeMediaBatchAsync(NativeMediaSourceRun previous, CancellationToken token = default)
    {
        RequireOwnedMediaRun(previous, ended: true);
        var choice = CaptureNativeSourceChoice(previous.Lease.MediaType, true, true);
        var read = NativeSourceReadGuard(choice, previous.Lease.Version);
        void Require()
        {
            RequireOwnedMediaRun(previous, ended: true); read();
            lock (fileRouteGate)
                if (nativeMediaSourceRun is not null || !previous.Result.RunEnded || previous.Result.BatchEnd is not false)
                    throw DeviceFileControl.Error("file_sources_native_no_next_batch");
        }
        Require();
        var message = DeviceFileSources.CreateRequest("next_batch", Now(), previous.Lease.Version,
            runId: previous.Lease.RunId, mediaType: previous.Lease.MediaType);
        NativeMediaSourceRun? retained = null;
        await ExchangeNativeSourceCommandAsync<DeviceFileRunResult>(choice, message, DeviceFileSources.RunResultKind,
            raw => DeviceFileSources.ParseRunResult(raw, message["message_id"]!.GetValue<string>(), "next_batch", previous.Lease.Version, Now(), expectedMediaType: previous.Lease.MediaType),
            Require, token, accept: (ticket, value) =>
            {
                var result = (DeviceFileRunResult)value;
                if (result.RunId == previous.Lease.RunId) throw DeviceFileControl.Error("file_sources_native_run_reused");
                lock (fileRouteGate)
                {
                    var lease = choice.Owner.RetainSourceRun(ticket, result.RunId, result.Version, previous.Lease.MediaType);
                    retained = new(choice.Owner, lease, previous.CatalogId, previous.AlbumId, previous.DesktopChoice, result);
                    retained.AlbumScope = previous.AlbumScope;
                    nativeMediaSourceRun = retained; nativeEndedMediaBatch = null;
                    previous.Owner.ReleaseSourceRun(previous.Lease);
                }
            });
        return retained ?? throw DeviceFileControl.Error("file_sources_native_original_run_required");
    }

    internal async Task<DeviceFileMediaPage> ReadNativeMediaPageAsync(NativeMediaSourceRun run, CancellationToken token = default)
    {
        RequireOwnedMediaRun(run);
        var choice = CaptureNativeSourceChoice(run.Lease.MediaType, true, true); var read = NativeSourceReadGuard(choice, run.Lease.Version);
        int after;
        lock (fileRouteGate)
            after = run.Pages.Count == 0 ? 0 : run.Pages[^1].NextCursor ?? throw DeviceFileControl.Error("file_sources_native_media_pages_complete");
        void Require()
        {
            RequireOwnedMediaRun(run); read();
            lock (fileRouteGate)
                if (run.Result.State != "snapshot_ready" || !run.Result.SourceIoEnded ||
                    (run.Pages.Count == 0 ? 0 : run.Pages[^1].NextCursor) != after)
                    throw DeviceFileControl.Error("file_sources_native_media_page_not_ready");
        }
        Require();
        var operation = run.Resume is null ? "media_page" : "resume_media_page";
        var message = DeviceFileSources.CreateRequest(operation, Now(), run.Lease.Version, runId: run.Lease.RunId, after: after, mediaType: run.Lease.MediaType);
        return await ExchangeNativeSourceCommandAsync<DeviceFileMediaPage>(choice, message, DeviceFileSources.MediaKind,
            raw => DeviceFileSources.ParseMediaPage(raw, message["message_id"]!.GetValue<string>(), run.Lease.Version, run.Lease.RunId, Now(), after,
                expectedManifestSha256: run.Resume?.Selection.Manifest.Fingerprint, expectedMediaType: run.Lease.MediaType, expectedOperation: operation), Require, token, accept: (_, value) =>
            {
                var page = (DeviceFileMediaPage)value;
                lock (fileRouteGate)
                {
                    var first = run.Pages.FirstOrDefault(); var scope = (page.SourceEpoch, page.MediaType, page.InsertionWitness);
                    if (run.Result.Batched && page.TotalFiles > 16 || first is not null && (first.ManifestSha256 != page.ManifestSha256 || first.TotalFiles != page.TotalFiles) ||
                        run.AlbumScope is not null && run.AlbumScope.Value != scope ||
                        run.Pages.SelectMany(old => old.Entries).Any(old => page.Entries.Any(entry => old.FileId == entry.FileId || old.PhotoId == entry.PhotoId)) ||
                        run.Result.ManifestSha256 is not null && run.Result.ManifestSha256 != page.ManifestSha256)
                        throw DeviceFileControl.Error("file_sources_native_media_scope_changed");
                    if (run.Resume is not null && page.NextCursor is null)
                        DeviceFileSources.CorrelateMediaPages(run.Pages.Append(page).ToArray(), run.Resume.Selection.Manifest);
                    run.AlbumScope = scope; run.Pages.Add(page);
                }
            });
    }

    internal sealed record NativeMediaResumeLookup(TelefonStore.NativeMediaResumeSelection Selection, DeviceFileResumeHistory History);

    internal async Task<NativeMediaSourceRun> StartNativeMediaResumeAsync(NativeMediaResumeLookup original,
        TelefonStore.NativeMediaReceiveJob recovered, string catalogId, string albumId, bool desktopChoice, CancellationToken token = default)
    {
        var selected = original.Selection; var remote = original.History;
        if (selected.PeerId != peer.Id) throw DeviceFileControl.Error("file_receive_foreign_resume_selection");
        var choice = CaptureNativeSourceChoice(selected.MediaType, true, true); var read = NativeSourceReadGuard(choice, remote.Version);
        void Require()
        {
            read(); recovered.RequireRecoveredSourceResume(selected, remote);
            lock (fileRouteGate)
                if (nativeMediaSourceRun is not null || nativeEndedMediaBatch is not null || choice.Destination?.Version != selected.DestinationVersion)
                    throw DeviceFileControl.Error("file_sources_native_original_run_pending");
        }
        Require();
        var message = DeviceFileSources.CreateRequest("resume_run", Now(), remote.Version, catalogId: catalogId, albumId: albumId,
            desktopChoice: desktopChoice, mediaType: selected.MediaType, originalJobId: remote.JobId, originalJobVersion: remote.JobVersion);
        NativeMediaSourceRun? retained = null;
        await ExchangeNativeSourceCommandAsync<DeviceFileRunResult>(choice, message, DeviceFileSources.RunResultKind,
            raw => DeviceFileSources.ParseRunResult(raw, message["message_id"]!.GetValue<string>(), "resume_run", remote.Version, Now(), expectedMediaType: selected.MediaType),
            Require, token, accept: (ticket, value) =>
            {
                var result = (DeviceFileRunResult)value;
                lock (fileRouteGate)
                {
                    var lease = choice.Owner.RetainSourceRun(ticket, result.RunId, result.Version, selected.MediaType);
                    retained = new(choice.Owner, lease, catalogId, albumId, desktopChoice, result) { Resume = original };
                    nativeMediaSourceRun = retained;
                }
            });
        return retained ?? throw DeviceFileControl.Error("file_sources_native_original_run_required");
    }

    internal async Task<NativeMediaResumeLookup> LookupNativeMediaResumeAsync(TelefonStore.NativeMediaResumeSelection selected,
        string sourceVersion, CancellationToken token = default)
    {
        store.RequireNativeMediaResumeSelection(selected);
        if (selected.PeerId != peer.Id) throw DeviceFileControl.Error("file_receive_foreign_resume_selection");
        var choice = CaptureNativeSourceChoice(selected.MediaType, true, true); var read = NativeSourceReadGuard(choice, sourceVersion);
        void Authority()
        {
            read();
            lock (fileRouteGate)
                if (nativeMediaSourceRun is not null || nativeEndedMediaBatch is not null || choice.Destination?.Version != selected.DestinationVersion)
                    throw DeviceFileControl.Error("file_receive_original_source_history_required");
        }
        void Require() { Authority(); store.RequireNativeMediaResumeSelection(selected); }
        Require();
        var message = DeviceFileSources.CreateRequest("resume_lookup", Now(), sourceVersion, mediaType: selected.MediaType,
            sourceId: selected.Manifest.SourceId, transferId: selected.Manifest.TransferId, manifestSha256: selected.Manifest.Fingerprint);
        TelefonStore.NativeMediaResumeSelection? recorded = null;
        var result = await ExchangeNativeSourceCommandAsync<DeviceFileResumeHistory>(choice, message, DeviceFileSources.ResumeKind,
            raw =>
            {
                var history = DeviceFileSources.ParseResumeHistory(raw, message["message_id"]!.GetValue<string>(), sourceVersion, selected.Manifest, Now(), selected.MediaType);
                if (TelefonProtocolContract.Integer(raw["expires_ms"]) > TelefonProtocolContract.Integer(message["expires_ms"]))
                    throw DeviceFileControl.Error("file_sources_native_resume_deadline_changed");
                return history;
            }, Require, token, accept: (_, value) => recorded = store.RecordNativeSourceResumeHistory(selected, (DeviceFileResumeHistory)value, Authority));
        return new(recorded ?? throw DeviceFileControl.Error("file_receive_original_source_history_required"), result);
    }
}
