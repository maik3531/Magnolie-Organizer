using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    // Refs #330. One live original offer/clock/control owner on the existing
    // file IO lane. Neither this run nor its remote DATA grants native END.
    internal sealed class NativeMediaBatchSendRun
    {
        internal readonly TelefonConnection Connection;
        internal readonly TelefonStore.NativePreparedMediaBatch Cache;
        internal readonly NativeFileControlSession Owner;
        internal readonly string PermissionEpoch;
        internal readonly JsonObject Offer;
        internal readonly CancellationTokenSource Lifetime;
        private readonly Func<bool>? counterpartCurrent;
        internal readonly TaskCompletionSource<RemoteFileAcceptance> Accepted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<RemoteSavedConfirmation> Saved = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<RemotePublishedBatchReadback> Readback = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TelefonStore.NativeMediaBatchSourceExchange Exchange = null!;
        internal RemoteFileAcceptance? Acceptance;
        internal long AcceptanceExpires;
        internal bool OutputDrained;

        internal NativeMediaBatchSendRun(TelefonConnection connection, TelefonStore.NativePreparedMediaBatch cache,
            NativeFileControlSession owner, string epoch, CancellationTokenSource lifetime, Func<bool>? counterpartCurrent = null)
        {
            Connection = connection; Cache = cache; Owner = owner; PermissionEpoch = epoch; Lifetime = lifetime;
            this.counterpartCurrent = counterpartCurrent; Offer = cache.CreateMediaOffer(Now());
        }

        internal void Require()
        {
            Lifetime.Token.ThrowIfCancellationRequested();
            RequireBatchCounterpart(counterpartCurrent);
            if (Exchange is null) Cache.Require(); else Exchange.Require();
            Connection.RequireNativeFileControls(Owner);
            var binding = Owner.Binding(Acceptance?.DestinationToken ?? new string('0', 64), senderIsLocal: true);
            lock (Connection.fileRouteGate)
                if (!ReferenceEquals(Connection.nativeMediaBatchSend, this) || binding is null || binding.PermissionEpoch != PermissionEpoch ||
                    binding.SenderId != Cache.Manifest.SenderId || binding.ReceiverId != Cache.Manifest.ReceiverId ||
                    Now() >= Offer["expires_ms"]!.GetValue<long>() || Acceptance is not null && Now() >= AcceptanceExpires)
                    throw DeviceFileControl.Error("media_source_batch_send_original_owner_required");
        }
    }

    private NativeMediaBatchSendRun? nativeMediaBatchSend;
    private TelefonStore.NativeBatchSourceRetirement? nativeBatchRetirement;

    internal void RequireNativeBatchRetirementLane(TelefonStore.NativeBatchSourceRetirement owner)
    {
        lock (fileRouteGate)
            if (!ReferenceEquals(nativeBatchRetirement, owner) || fileControlIo.CurrentCount != 0)
                throw DeviceFileControl.Error("media_source_batch_actual_output_drain_required");
    }

    // The worker supplies this connection's fresh authenticated
    // agreement, never a cached device status, UI choice or number of files.
    internal Task<(RemoteSavedConfirmation Saved, RemotePublishedBatchReadback Readback)> SendConnectedMediaBatchToSourceEndAsync(
        TelefonStore.NativePreparedMediaBatch cache, DeviceFileNativeDirectory output, IReadOnlyDictionary<string, NativeMediaBackupVersion> selected,
        Func<bool> nativePermit, Func<bool> counterpartCurrent, CancellationToken token = default, Action<string>? boundary = null) =>
        SendNativeMediaBatchCoreAsync(cache, output, selected, nativePermit, boundary, token,
            counterpartCurrent ?? throw DeviceFileControl.Error("media_source_batch_counterpart_required"));

    private static void RequireBatchCounterpart(Func<bool>? counterpartCurrent)
    {
        if (counterpartCurrent is not null && !counterpartCurrent()) throw DeviceFileControl.Error("media_source_batch_counterpart_required");
    }

    private async Task<(RemoteSavedConfirmation Saved, RemotePublishedBatchReadback Readback)> SendNativeMediaBatchCoreAsync(
        TelefonStore.NativePreparedMediaBatch cache, DeviceFileNativeDirectory? output, IReadOnlyDictionary<string, NativeMediaBackupVersion>? selected,
        Func<bool>? nativePermit, Action<string>? boundary, CancellationToken token, Func<bool>? counterpartCurrent = null)
    {
        RequireBatchCounterpart(counterpartCurrent);
        if (!ReferenceEquals(cache.OwnerStore, store) || !ReferenceEquals(cache.ConnectionOwner, this))
            throw DeviceFileControl.Error("media_source_send_native_cache_required");
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, token);
        lifetime.CancelAfter(TimeSpan.FromSeconds(60)); // Once for the original root, never per member/request.
        NativeMediaBatchSendRun? run = null;
        TelefonStore.NativeBatchSourceRetirement? retirement = null;
        var retirementReady = false;
        try
        {
            await fileControlIo.WaitAsync(lifetime.Token);
            try
            {
                RequireBatchCounterpart(counterpartCurrent);
                cache.Require(); var owner = RequireNativeFileControls();
                var binding = owner.Binding(new string('0', 64), senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_send_grant_required");
                run = new(this, cache, owner, binding.PermissionEpoch, lifetime, counterpartCurrent);
                lock (fileRouteGate)
                {
                    if (NativeMediaSendBusy || nativeMediaSourceRun is not null ||
                        nativeEndedMediaBatch is not null || nativeMediaTransfer is not null || nativeSourceCommand is not null || nativeSourceStatus is not null)
                        throw DeviceFileControl.Error("media_source_send_io_busy");
                    nativeMediaBatchSend = run;
                }
                run.Require(); cache.BeginSendAttempt(this); run.Exchange = new(run);
                await WriteNativeMediaFrameAsync(run.Offer, run.Require, lifetime.Token);
                run.Exchange.OfferSent();
            }
            finally { fileControlIo.Release(); }
            _ = await run.Accepted.Task.WaitAsync(lifetime.Token);
            var saved = await run.Saved.Task.WaitAsync(lifetime.Token); run.Require();
            var readback = await run.Readback.Task.WaitAsync(lifetime.Token); run.Require();
            if (output is not null)
            {
                var localPermit = nativePermit ?? throw DeviceFileControl.Error("media_backup_native_permit_changed");
                retirement = new(run, output, selected ?? throw DeviceFileControl.Error("media_source_batch_complete_backup_map_required"),
                    () => !token.IsCancellationRequested && !cancellation.IsCancellationRequested && localPermit(), boundary);
                retirement.Plan(); retirementReady = true;
            }
            return (saved, readback); // Peer assertions, never retirement/backup/deletion or native END.
        }
        finally
        {
            if (run is not null)
            {
                lifetime.Cancel();
                await fileControlIo.WaitAsync(CancellationToken.None); // Actual encrypted output return before releasing route ownership.
                try
                {
                    lock (fileRouteGate) if (ReferenceEquals(nativeMediaBatchSend, run)) nativeMediaBatchSend = null;
                    run.OutputDrained = true;
                    // Local native ownership, not a renewed wire grant. The
                    // serial output lane stays held through actual root END.
                    if (retirementReady)
                    {
                        lock (fileRouteGate) nativeBatchRetirement = retirement;
                        try { retirement!.RunAfterOutputDrain(); }
                        finally { lock (fileRouteGate) if (ReferenceEquals(nativeBatchRetirement, retirement)) nativeBatchRetirement = null; }
                    }
                    else if (retirement is not null) cache.Dispose();
                }
                finally { fileControlIo.Release(); }
            }
        }
    }

    private async Task ReceiveNativeMediaBatchSendAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        NativeMediaBatchSendRun? run = null;
        try
        {
            lock (fileRouteGate) run = nativeMediaBatchSend;
            if (run is null) throw DeviceFileControl.Error("media_source_send_unsolicited_reply");
            run.Require(); var kind = message["kind"]!.GetValue<string>();
            if (run.Acceptance is not null && TelefonProtocolContract.Integer(message["expires_ms"]) > run.AcceptanceExpires)
                throw DeviceFileControl.Error("media_source_batch_original_acceptance_deadline_required");
            if (kind == DeviceFileAcceptanceEnvelope.Kind)
            {
                if (run.Acceptance is not null) throw DeviceFileControl.Error("media_source_send_duplicate_acceptance");
                var accepted = DeviceFileAcceptanceEnvelope.Parse(message, Now());
                if (accepted.OfferId != run.Offer["message_id"]!.GetValue<string>() || accepted.ManifestSha256 != run.Cache.Manifest.Fingerprint ||
                    accepted.TransferId != run.Cache.Manifest.TransferId || accepted.PermissionEpoch != run.PermissionEpoch ||
                    message["expires_ms"]!.GetValue<long>() > run.Offer["expires_ms"]!.GetValue<long>() ||
                    TelefonProtocolContract.Integer(message["created_ms"]) < TelefonProtocolContract.Integer(run.Offer["created_ms"]) ||
                    run.Owner.Binding(accepted.DestinationToken, senderIsLocal: true) is null)
                    throw DeviceFileControl.Error("media_source_send_acceptance_changed");
                run.Exchange.Accepted(message); run.AcceptanceExpires = TelefonProtocolContract.Integer(message["expires_ms"]);
                run.Acceptance = accepted; run.Require(); run.Accepted.TrySetResult(accepted);
                return;
            }
            var acceptance = run.Acceptance ?? throw DeviceFileControl.Error("media_source_send_actual_acceptance_required");
            if (kind == DeviceFileChunkEnvelope.RequestKind)
            {
                var request = DeviceFileChunkEnvelope.ParseRequest(message, Now());
                if (request.TransferId != acceptance.TransferId || request.ManifestSha256 != acceptance.ManifestSha256 ||
                    request.AcceptanceSha256 != acceptance.AcceptanceSha256 || request.PermissionEpoch != acceptance.PermissionEpoch ||
                    request.DestinationToken != acceptance.DestinationToken || request.Expires > run.Offer["expires_ms"]!.GetValue<long>())
                    throw DeviceFileControl.Error("media_source_send_chunk_changed");
                run.Exchange.PlanChunk(request);
                var bytes = run.Cache.ReadChunk(request.FileId, request.ChunkIndex);
                try
                {
                    var body = message["body"]!.DeepClone().AsObject(); body["request_id"] = request.RequestId;
                    body["data_base64"] = Convert.ToBase64String(bytes); body["data_sha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
                    var response = NativeFileMessage(DeviceFileChunkEnvelope.ResultKind, body, Now(), request.Expires);
                    await WriteNativeMediaFrameAsync(response, run.Require, run.Lifetime.Token); run.Exchange.ChunkSent(request);
                }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            else if (kind == DevicePublishedBatchReadbackEnvelope.Kind)
            {
                if (!run.Saved.Task.IsCompletedSuccessfully || run.Readback.Task.IsCompleted)
                    throw DeviceFileControl.Error("media_source_send_unexpected_readback");
                var media = MediaOfferEnvelope.Validate(run.Offer, run.Cache.Manifest.SenderId, run.Cache.Manifest.ReceiverId, Now(), allowPcBatch: true);
                if (!media.PcBatch) throw DeviceFileControl.Error("media_source_batch_original_offer_required");
                var body = message["body"] as JsonObject ?? throw DeviceFileControl.Error("media_source_send_readback_required");
                var destination = body["destination_token"]?.GetValue<string>() ?? throw DeviceFileControl.Error("media_source_send_readback_required");
                var binding = run.Owner.Binding(destination, senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_send_grant_required");
                var readback = DevicePublishedBatchReadbackEnvelope.Parse(message, media.Offer, binding, media.MediaType, Now());
                foreach (var receipt in run.Saved.Task.Result.Members)
                {
                    var member = body["members"]![receipt.FileId]!;
                    if (member["publication_sha256"]?.GetValue<string>() != receipt.ReceiptSha256 ||
                        member["mime_type"]?.GetValue<string>() != media.MimeTypes[receipt.FileId]?.GetValue<string>())
                        throw DeviceFileControl.Error("media_source_send_publication_changed");
                }
                run.Require(); run.Exchange.PeerReadback(message); run.Readback.TrySetResult(readback);
            }
            else if (kind == DeviceFileSavedEnvelope.Kind)
            {
                var saved = DeviceFileSavedEnvelope.Parse(message, run.Cache.Manifest, acceptance, Now());
                if (message["expires_ms"]!.GetValue<long>() > run.Offer["expires_ms"]!.GetValue<long>())
                    throw DeviceFileControl.Error("media_source_send_saved_expired");
                run.Exchange.PeerSaved(message); run.Saved.TrySetResult(saved);
            }
            else throw DeviceFileControl.Error("media_source_batch_send_unexpected_reply");
        }
        catch (Exception error)
        {
            if (run is not null)
            {
                run.Accepted.TrySetException(error); run.Saved.TrySetException(error); run.Readback.TrySetException(error); run.Lifetime.Cancel();
            }
            CloseNativeFileRoute(); throw;
        }
        finally { fileControlIo.Release(); }
    }

    private void CheckNativeMediaBatchSendControl()
    {
        NativeMediaBatchSendRun? run; lock (fileRouteGate) run = nativeMediaBatchSend;
        if (run is null) return;
        try { run.Require(); } catch { run.Lifetime.Cancel(); }
    }
}
