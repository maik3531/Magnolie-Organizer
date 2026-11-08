using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    internal sealed class NativeMediaSendRun
    {
        internal readonly TelefonConnection Connection;
        internal readonly TelefonStore.NativePreparedMediaSource Cache;
        internal readonly NativeFileControlSession Owner;
        internal readonly string PermissionEpoch;
        internal readonly JsonObject Offer;
        internal readonly CancellationTokenSource Lifetime;
        internal readonly TaskCompletionSource<RemoteFileAcceptance> Accepted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<RemoteSavedConfirmation> Saved = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource<RemotePublishedReadback> Readback = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly bool ExpectReadback;
        internal bool OutputDrained;
        internal TelefonStore.NativeMediaSourceExchange Exchange = null!;
        internal RemoteFileAcceptance? Acceptance;
        internal NativeMediaSendRun(TelefonConnection connection, TelefonStore.NativePreparedMediaSource cache,
            NativeFileControlSession owner, string permissionEpoch, CancellationTokenSource lifetime, bool expectReadback = false)
        { Connection = connection; Cache = cache; Owner = owner; PermissionEpoch = permissionEpoch; Lifetime = lifetime; ExpectReadback = expectReadback; Offer = cache.CreateMediaOffer(Now()); }
        internal void Require()
        {
            Lifetime.Token.ThrowIfCancellationRequested(); Cache.Require(); Exchange?.Require(); Connection.RequireNativeFileControls(Owner);
            var token = Acceptance?.DestinationToken ?? new string('0', 64);
            var current = Owner.Binding(token, senderIsLocal: true);
            lock (Connection.fileRouteGate)
                if (!ReferenceEquals(Connection.nativeMediaSend, this) || current is null || current.PermissionEpoch != PermissionEpoch ||
                    current.SenderId != Cache.Manifest.SenderId || current.ReceiverId != Cache.Manifest.ReceiverId || Now() >= Offer["expires_ms"]!.GetValue<long>())
                    throw DeviceFileControl.Error("media_source_send_original_owner_required");
        }
    }
    private NativeMediaSendRun? nativeMediaSend;

    internal async Task<RemoteSavedConfirmation> SendNativeMappedMediaSourceAsync(TelefonStore.NativePreparedMediaSource cache, CancellationToken token = default) =>
        (await SendNativeMappedMediaSourceCoreAsync(cache, false, token)).Saved;

    // Explicit composition entry only. Both values remain peer metadata even
    // after this method's actual encrypted writer has drained in finally.
    internal async Task<(RemoteSavedConfirmation Saved, RemotePublishedReadback Readback)> SendNativeMappedMediaSourceWithReadbackAsync(
        TelefonStore.NativePreparedMediaSource cache, CancellationToken token = default)
    {
        var result = await SendNativeMappedMediaSourceCoreAsync(cache, true, token);
        return (result.Saved, result.Readback ?? throw DeviceFileControl.Error("media_source_send_readback_required"));
    }

    // Explicit local terminal stage. The protected source cache/history remains
    // retained; return values are still peer metadata, not deletion authority.
    internal async Task<(RemoteSavedConfirmation Saved, RemotePublishedReadback Readback)> SendNativeMappedMediaSourceToSourceEndAsync(
        TelefonStore.NativePreparedMediaSource cache, CancellationToken token = default)
    {
        var result = await SendNativeMappedMediaSourceCoreAsync(cache, true, token, endSource: true);
        return (result.Saved, result.Readback ?? throw DeviceFileControl.Error("media_source_send_readback_required"));
    }

    private async Task<(RemoteSavedConfirmation Saved, RemotePublishedReadback? Readback)> SendNativeMappedMediaSourceCoreAsync(
        TelefonStore.NativePreparedMediaSource cache, bool expectReadback, CancellationToken token, bool endSource = false)
    {
        if (!ReferenceEquals(cache.OwnerStore, store) || !ReferenceEquals(cache.ConnectionOwner, this))
            throw DeviceFileControl.Error("media_source_send_native_cache_required");
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, token); lifetime.CancelAfter(TimeSpan.FromSeconds(60));
        NativeMediaSendRun? run = null;
        var sourceEndReady = false;
        try
        {
            await fileControlIo.WaitAsync(lifetime.Token);
            try
            {
                cache.Require(); var owner = RequireNativeFileControls();
                var binding = owner.Binding(new string('0', 64), senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_send_grant_required");
                run = new(this, cache, owner, binding.PermissionEpoch, lifetime, expectReadback);
                lock (fileRouteGate)
                {
                    if (nativeMediaSend is not null || nativeMediaSourceRun is not null || nativeEndedMediaBatch is not null || nativeMediaTransfer is not null || nativeSourceCommand is not null || nativeSourceStatus is not null)
                        throw DeviceFileControl.Error("media_source_send_io_busy");
                    nativeMediaSend = run;
                }
                run.Require(); cache.BeginSendAttempt(this); run.Exchange = new(run);
                await WriteNativeMediaFrameAsync(run.Offer, run.Require, lifetime.Token);
                run.Exchange.OfferSent(); // Only after secure output AND all original native guards returned.
            }
            finally { fileControlIo.Release(); }
            _ = await run.Accepted.Task.WaitAsync(lifetime.Token);
            var saved = await run.Saved.Task.WaitAsync(lifetime.Token); run.Require();
            var readback = expectReadback ? await run.Readback.Task.WaitAsync(lifetime.Token) : null; run.Require();
            sourceEndReady = endSource && readback is not null;
            return (saved, readback); // Remote assertions ONLY. Never local Saved/END, deletion, retirement or full UI completion.
        }
        finally
        {
            if (run is not null)
            {
                lifetime.Cancel();
                // Drain a response's actual encrypted write before releasing this cache/native file owner.
                await fileControlIo.WaitAsync(CancellationToken.None);
                try
                {
                    lock (fileRouteGate) if (ReferenceEquals(nativeMediaSend, run)) nativeMediaSend = null;
                    run.OutputDrained = true;
                }
                finally { fileControlIo.Release(); }
                if (sourceEndReady) run.Exchange.SourceEnd();
            }
        }
    }

    private async Task ReceiveNativeMediaSendAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        NativeMediaSendRun? run = null;
        try
        {
            lock (fileRouteGate) run = nativeMediaSend;
            if (run is null) throw DeviceFileControl.Error("media_source_send_unsolicited_reply");
            run.Require(); var kind = message["kind"]!.GetValue<string>();
            if (kind == DeviceFileAcceptanceEnvelope.Kind)
            {
                if (run.Acceptance is not null) throw DeviceFileControl.Error("media_source_send_duplicate_acceptance");
                var accepted = DeviceFileAcceptanceEnvelope.Parse(message, Now());
                if (accepted.OfferId != run.Offer["message_id"]!.GetValue<string>() || accepted.ManifestSha256 != run.Cache.Manifest.Fingerprint ||
                    accepted.TransferId != run.Cache.Manifest.TransferId || accepted.PermissionEpoch != run.PermissionEpoch ||
                    message["expires_ms"]!.GetValue<long>() > run.Offer["expires_ms"]!.GetValue<long>() ||
                    run.Owner.Binding(accepted.DestinationToken, senderIsLocal: true) is null)
                    throw DeviceFileControl.Error("media_source_send_acceptance_changed");
                run.Exchange.Accepted(message["body"]!.AsObject()); run.Acceptance = accepted; run.Require(); run.Accepted.TrySetResult(accepted);
            }
            else
            {
                var accepted = run.Acceptance ?? throw DeviceFileControl.Error("media_source_send_actual_acceptance_required");
                if (kind == DeviceFileChunkEnvelope.RequestKind)
                {
                    var request = DeviceFileChunkEnvelope.ParseRequest(message, Now());
                    if (request.TransferId != accepted.TransferId || request.ManifestSha256 != accepted.ManifestSha256 ||
                        request.AcceptanceSha256 != accepted.AcceptanceSha256 || request.PermissionEpoch != accepted.PermissionEpoch || request.DestinationToken != accepted.DestinationToken ||
                        request.Expires > run.Offer["expires_ms"]!.GetValue<long>() || request.FileId != run.Cache.Manifest.Files[0].Id)
                        throw DeviceFileControl.Error("media_source_send_chunk_changed");
                    run.Exchange.PlanChunk(request);
                    var bytes = run.Cache.ReadChunk(request.ChunkIndex);
                    try
                    {
                        var body = message["body"]!.DeepClone().AsObject(); body["request_id"] = request.RequestId;
                        body["data_base64"] = Convert.ToBase64String(bytes); body["data_sha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
                        var response = NativeFileMessage(DeviceFileChunkEnvelope.ResultKind, body, Now(), request.Expires);
                        await WriteNativeMediaFrameAsync(response, run.Require, run.Lifetime.Token); run.Exchange.ChunkSent(request);
                    }
                    finally { CryptographicOperations.ZeroMemory(bytes); }
                }
                else if (kind == DevicePublishedReadbackEnvelope.Kind)
                {
                    if (!run.ExpectReadback || !run.Saved.Task.IsCompletedSuccessfully || run.Readback.Task.IsCompleted)
                        throw DeviceFileControl.Error("media_source_send_unexpected_readback");
                    var media = MediaOfferEnvelope.Validate(run.Offer, run.Cache.Manifest.SenderId, run.Cache.Manifest.ReceiverId, Now());
                    var body = message["body"] as JsonObject ?? throw DeviceFileControl.Error("media_source_send_readback_required");
                    var destination = body["destination_token"]?.GetValue<string>() ?? throw DeviceFileControl.Error("media_source_send_readback_required");
                    var binding = run.Owner.Binding(destination, senderIsLocal: true) ?? throw DeviceFileControl.Error("media_source_send_grant_required");
                    var readback = DevicePublishedReadbackEnvelope.Parse(message, media.Offer, binding, media.MediaType, Now());
                    var member = run.Saved.Task.Result.Members.Single();
                    if (body["publication_sha256"]?.GetValue<string>() != member.ReceiptSha256 ||
                        body["mime_type"]?.GetValue<string>() != media.MimeTypes[member.FileId]?.GetValue<string>())
                        throw DeviceFileControl.Error("media_source_send_publication_changed");
                    run.Require(); run.Exchange.PeerReadback(readback.Body); run.Readback.TrySetResult(readback);
                }
                else
                {
                    var saved = DeviceFileSavedEnvelope.Parse(message, run.Cache.Manifest, accepted, Now());
                    if (message["expires_ms"]!.GetValue<long>() > run.Offer["expires_ms"]!.GetValue<long>()) throw DeviceFileControl.Error("media_source_send_saved_expired");
                    run.Exchange.PeerSaved(message["body"]!.AsObject()); run.Saved.TrySetResult(saved);
                }
            }
        }
        catch (Exception error)
        {
            if (run is not null) { run.Accepted.TrySetException(error); run.Saved.TrySetException(error); if (run.ExpectReadback) run.Readback.TrySetException(error); run.Lifetime.Cancel(); }
            CloseNativeFileRoute(); // Preserve reserved-frame failure isolation; never fall back to ordinary reception.
            throw;
        }
        finally { fileControlIo.Release(); }
    }
    private void CloseNativeMediaSend() { lock (fileRouteGate) nativeMediaSend?.Lifetime.Cancel(); }
    private void CheckNativeMediaSendControl()
    {
        NativeMediaSendRun? run; lock (fileRouteGate) run = nativeMediaSend;
        if (run is null) return;
        try { run.Require(); } catch { CloseNativeMediaSend(); }
    }
}
