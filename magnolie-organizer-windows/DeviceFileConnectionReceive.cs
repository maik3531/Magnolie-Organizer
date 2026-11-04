using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    internal sealed class NativeMediaTransfer(NativeMediaSourceRun source, TelefonStore.NativeMediaReceiveJob job,
        RemoteFileAcceptance acceptance, Action require, CancellationToken token, Action stop)
    {
        internal readonly NativeMediaSourceRun Source = source;
        internal readonly TelefonStore.NativeMediaReceiveJob Job = job;
        internal readonly RemoteFileAcceptance Acceptance = acceptance; // Wire view of the durable LOCAL acceptance.
        internal readonly Action Require = require;
        internal readonly CancellationToken Token = token;
        internal readonly Action Stop = stop;
        internal readonly TaskCompletionSource<bool> Drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool ActiveIo = true, SavedOutputConfirmed, Failed;
    }
    private sealed class NativeMediaChunkPending(NativeMediaTransfer transfer, JsonObject message)
    {
        internal readonly NativeMediaTransfer Transfer = transfer;
        internal readonly JsonObject Message = message;
        internal readonly DeviceFileChunkRequest Request = DeviceFileChunkEnvelope.ParseRequest(message, Now());
        internal readonly long Issued = Environment.TickCount64;
        internal readonly TaskCompletionSource<bool> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool OutputConfirmed, ResponseObserved;
    }
    private NativeMediaTransfer? nativeMediaTransfer;
    private NativeMediaChunkPending? nativeMediaChunk;
    private NativeMediaChunkPending? nativeRetiredMediaChunk;

    private static JsonObject NativeFileMessage(string kind, JsonObject body, long now, long? expires = null) => new()
    {
        ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind,
        ["created_ms"] = now, ["expires_ms"] = expires ?? checked(now + DeviceFileControl.MaximumTtlMs), ["body"] = body
    };

    private void RequireNativeMediaTransfer(NativeMediaTransfer transfer)
    {
        transfer.Token.ThrowIfCancellationRequested(); transfer.Require();
        lock (fileRouteGate)
            if (transfer.Failed || !ReferenceEquals(nativeMediaTransfer, transfer) || !ReferenceEquals(transfer.Source.Transfer, transfer))
                throw DeviceFileControl.Error("file_receive_native_transfer_changed");
    }

    // One explicit native operation owns admission, wire requests, durable
    // checkpoints, no-replace publication, local receipts and actual source END.
    // It never selects a run from incoming IDs or routes data to the book inbox.
    internal async Task<string> ReceiveNativeMediaRunAsync(NativeMediaSourceRun run, CancellationToken callerCancellation = default)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, callerCancellation);
        lifetime.Token.ThrowIfCancellationRequested(); RequireOwnedMediaRun(run);
        var choice = CaptureNativeSourceChoice(run.Lease.MediaType, true, true); var read = NativeSourceReadGuard(choice, run.Lease.Version);
        void Authority()
        {
            RequireOwnedMediaRun(run); read();
            if (run.Result.State != "snapshot_ready" || !run.Result.SourceIoEnded || run.Result.RunEnded)
                throw DeviceFileControl.Error("file_receive_native_source_not_ready");
        }
        Authority();
        NativeMediaTransfer? transfer = null;
        TelefonStore.NativeMediaReceiveJob? job = null;
        await fileControlIo.WaitAsync(lifetime.Token);
        try
        {
            Authority();
            lock (fileRouteGate)
                if (nativeMediaTransfer is not null || run.Transfer is not null || nativeSourceCommand is not null || nativeSourceStatus is not null ||
                    run.OfferedManifest is null || run.OfferedMessageId != run.Result.OfferId || Now() >= run.OfferedExpires)
                    throw DeviceFileControl.Error("file_receive_native_offer_required");
            var manifest = run.OfferedManifest!;
            DeviceFileSources.CorrelateMediaPages(run.Pages, manifest);
            var binding = CaptureNativeMediaReceiveBinding(run.Lease.Version, run.Lease.MediaType);
            if (run.Resume is null) job = store.BeginNativeMediaReceiveJob(peer.Id, run.Lease.MediaType, manifest, binding);
            else
            {
                job = run.Recovered ?? throw DeviceFileControl.Error("file_receive_original_recovered_owner_required");
                job.RequireRecoveredSourceResume(run.Resume.Selection, run.Resume.History);
                if (job.Manifest.Fingerprint != manifest.Fingerprint) throw DeviceFileControl.Error("file_receive_original_manifest_changed");
            }
            job.BindNativeMediaContext(run.CatalogId, run.AlbumId, run.Pages);
            var accepted = job.PrepareNativeAcceptance(run.OfferedMessageId!);
            transfer = new(run, job, accepted, Authority, lifetime.Token, lifetime.Cancel);
            lock (fileRouteGate) { nativeMediaTransfer = transfer; run.Transfer = transfer; }
            var message = NativeFileMessage(DeviceFileAcceptanceEnvelope.Kind, new JsonObject { ["format"] = 1, ["offer_id"] = accepted.OfferId,
                ["manifest_sha256"] = accepted.ManifestSha256, ["transfer_id"] = accepted.TransferId, ["acceptance_sha256"] = accepted.AcceptanceSha256,
                ["permission_epoch"] = accepted.PermissionEpoch, ["destination_token"] = accepted.DestinationToken }, Now(), run.OfferedExpires);
            _ = DeviceFileAcceptanceEnvelope.Parse(message, Now());
            await WriteNativeMediaFrameAsync(message, () => RequireNativeMediaTransfer(transfer), lifetime.Token);
        }
        catch
        {
            if (transfer is not null) { transfer.Failed = true; transfer.ActiveIo = false; transfer.Drained.TrySetResult(true); }
            lock (fileRouteGate) if (ReferenceEquals(nativeMediaTransfer, transfer)) nativeMediaTransfer = null;
            job?.Dispose(); throw;
        }
        finally { fileControlIo.Release(); }
        try
        {
            while (job!.NextNativeChunk() is { } next)
                await RequestNativeMediaChunkAsync(transfer!, next.FileId, next.Index, lifetime.Token);
            await fileControlIo.WaitAsync(lifetime.Token);
            try
            {
                RequireNativeMediaTransfer(transfer!); job.PublishAll();
                var receipts = job.CommitNativeSavedReceipts(); RequireNativeMediaTransfer(transfer!);
                var accepted = transfer!.Acceptance;
                var saved = NativeFileMessage(DeviceFileSavedEnvelope.Kind, new JsonObject { ["format"] = 1, ["transfer_id"] = accepted.TransferId,
                    ["manifest_sha256"] = accepted.ManifestSha256, ["acceptance_sha256"] = accepted.AcceptanceSha256,
                    ["permission_epoch"] = accepted.PermissionEpoch, ["destination_token"] = accepted.DestinationToken, ["receipts"] = receipts }, Now());
                // Pure wire preflight does not create the local proof: the above
                // protected commit/readback and held-file publication did that.
                _ = DeviceFileSavedEnvelope.Parse(saved, job.Manifest, accepted, Now());
                await WriteNativeMediaFrameAsync(saved, () => RequireNativeMediaTransfer(transfer), lifetime.Token);
                transfer.SavedOutputConfirmed = true; transfer.ActiveIo = false;
            }
            finally { fileControlIo.Release(); }
            // Once Saved was actually sent, finish its metadata END even if the
            // user cancels data work meanwhile. Connection shutdown still stops it.
            await CancelNativeMediaRunAsync(run, cancellation); // Android END requires an acknowledged stopped original run.
            await EndNativeMediaRunAsync(run, cancellation); // Actual correlated END, never publication == END.
            return job.JobId;
        }
        finally
        {
            // Drain the actual receive lane before closing its native handles.
            await fileControlIo.WaitAsync(CancellationToken.None);
            try
            {
                if (transfer is not null) transfer.ActiveIo = false;
                lock (fileRouteGate)
                {
                    if (ReferenceEquals(nativeMediaTransfer, transfer)) nativeMediaTransfer = null;
                    if (nativeMediaChunk is not null && ReferenceEquals(nativeMediaChunk.Transfer, transfer))
                    { nativeMediaChunk.Completion.TrySetCanceled(); nativeMediaChunk = null; }
                }
                job!.Dispose(); // Original history and interrupted bytes remain.
            }
            finally { fileControlIo.Release(); transfer?.Drained.TrySetResult(true); }
        }
    }

    private async Task WriteNativeMediaFrameAsync(JsonObject message, Action require, CancellationToken token)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token); var started = false;
        try
        {
            void Current()
            {
                require();
                if (Now() >= TelefonProtocolContract.Integer(message["expires_ms"])) throw DeviceFileControl.Error("file_receive_native_message_expired");
            }
            Current(); var envelope = Seal(message); started = true;
            await TelefonCoordinator.WriteFrameAsync(stream, envelope, deadline.Token); lastSentMs = Now(); Current();
        }
        catch { if (started) { CloseNativeFileRoute(); stream.Dispose(); } throw; }
        finally { writer.Release(); }
    }

    private async Task RequestNativeMediaChunkAsync(NativeMediaTransfer transfer, string fileId, int index, CancellationToken token)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(token); lifetime.CancelAfter(TimeSpan.FromMilliseconds(DeviceFileControl.MaximumTtlMs));
        var accepted = transfer.Acceptance;
        var message = NativeFileMessage(DeviceFileChunkEnvelope.RequestKind, new JsonObject { ["format"] = 1, ["transfer_id"] = accepted.TransferId,
            ["manifest_sha256"] = accepted.ManifestSha256, ["acceptance_sha256"] = accepted.AcceptanceSha256, ["permission_epoch"] = accepted.PermissionEpoch,
            ["destination_token"] = accepted.DestinationToken, ["file_id"] = fileId, ["chunk_index"] = index }, Now());
        var pending = new NativeMediaChunkPending(transfer, message);
        try
        {
            await fileControlIo.WaitAsync(lifetime.Token);
            try
            {
                RequireNativeMediaTransfer(transfer);
                lock (fileRouteGate)
                {
                    if (nativeMediaChunk is not null) throw DeviceFileControl.Error("file_receive_native_chunk_busy");
                    nativeMediaChunk = pending;
                }
                await WriteNativeMediaFrameAsync(message, () => RequireNativeMediaChunk(pending), lifetime.Token);
                pending.OutputConfirmed = true;
            }
            finally { fileControlIo.Release(); }
            await pending.Completion.Task.WaitAsync(lifetime.Token);
        }
        catch (OperationCanceledException error) when (!token.IsCancellationRequested)
        { throw new TimeoutException("file_receive_native_chunk_timeout", error); }
        finally
        {
            lock (fileRouteGate)
            {
                if (ReferenceEquals(nativeMediaChunk, pending)) nativeMediaChunk = null;
                if (!pending.Completion.Task.IsCompletedSuccessfully && !pending.ResponseObserved) nativeRetiredMediaChunk = pending;
            }
            if (pending.Completion.Task.IsFaulted) _ = pending.Completion.Task.Exception;
        }
    }

    private void RequireNativeMediaChunk(NativeMediaChunkPending pending)
    {
        RequireNativeMediaTransfer(pending.Transfer);
        lock (fileRouteGate)
            if (!ReferenceEquals(nativeMediaChunk, pending) || pending.Completion.Task.IsCompleted)
                throw DeviceFileControl.Error("file_receive_native_chunk_changed");
        var tick = Environment.TickCount64;
        if (tick < pending.Issued || tick - pending.Issued >= DeviceFileControl.MaximumTtlMs || Now() >= pending.Request.Expires)
            throw DeviceFileControl.Error("file_receive_native_chunk_expired");
    }

    private async Task ReceiveNativeMediaChunkAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        byte[]? bytes = null;
        NativeMediaChunkPending? pending = null;
        try
        {
            bool retired;
            lock (fileRouteGate)
            {
                pending = nativeMediaChunk ?? nativeRetiredMediaChunk ?? throw DeviceFileControl.Error("file_receive_native_unsolicited_chunk");
                retired = !ReferenceEquals(nativeMediaChunk, pending);
            }
            if (!pending.OutputConfirmed) throw DeviceFileControl.Error("file_receive_native_unconfirmed_chunk_request");
            if (retired || pending.Transfer.Token.IsCancellationRequested)
            {
                RequireNativeFileControls(pending.Transfer.Source.Owner);
                var witness = pending.Transfer.Source.Owner.RemoteControlWitness();
                if (witness?.SessionEpoch != pending.Transfer.Source.Lease.RemoteSession ||
                    Environment.TickCount64 - pending.Issued >= DeviceFileControl.MaximumTtlMs)
                    throw DeviceFileControl.Error("file_receive_native_retired_chunk_scope_changed");
                bytes = DeviceFileChunkEnvelope.ParseResponse(message, pending.Message, pending.Transfer.Job.Manifest, pending.Transfer.Acceptance, Now());
                pending.ResponseObserved = true;
                lock (fileRouteGate) if (ReferenceEquals(nativeRetiredMediaChunk, pending)) nativeRetiredMediaChunk = null;
                pending.Completion.TrySetCanceled(); return; // Drain one exact old response, never write/ACK/regrant.
            }
            RequireNativeMediaChunk(pending);
            if (TelefonProtocolContract.Integer(message["expires_ms"]) > pending.Request.Expires) throw DeviceFileControl.Error("file_receive_native_chunk_deadline_changed");
            bytes = DeviceFileChunkEnvelope.ParseResponse(message, pending.Message, pending.Transfer.Job.Manifest, pending.Transfer.Acceptance, Now());
            pending.ResponseObserved = true;
            RequireNativeMediaChunk(pending);
            pending.Transfer.Job.ReceiveChunk(pending.Request.FileId, pending.Request.ChunkIndex, bytes);
            RequireNativeMediaChunk(pending); pending.Completion.TrySetResult(true);
        }
        catch (OperationCanceledException) when (pending?.Transfer.Token.IsCancellationRequested == true)
        { pending.Completion.TrySetCanceled(); }
        catch { CloseNativeFileRoute(); throw; }
        finally { if (bytes is not null) CryptographicOperations.ZeroMemory(bytes); fileControlIo.Release(); }
    }

    internal async Task<bool> StopNativeMediaReceiveAsync(NativeMediaSourceRun run, CancellationToken token = default)
    {
        RequireOwnedMediaRun(run);
        var transfer = run.Transfer;
        if (transfer is not null)
        {
            if (!transfer.SavedOutputConfirmed && !transfer.Drained.Task.IsCompleted) transfer.Stop();
            await transfer.Drained.Task.WaitAsync(token);
            if (run.Result.RunEnded) return true;
        }
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation, token); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await CancelNativeMediaRunAsync(run, deadline.Token);
        for (var attempt = 0; !run.Result.SourceIoEnded && attempt < 4; attempt++) await ReadNativeMediaRunAsync(run, deadline.Token);
        if (!run.Result.SourceIoEnded) return false; // Original owner remains held, not a claimed stop.
        await EndNativeMediaRunAsync(run, deadline.Token);
        if (run.Result.Batched) await EndNativeMediaAlbumAsync(run, deadline.Token);
        return true;
    }

    private void CloseNativeMediaData(string reason = "file_receive_native_route_closed")
    {
        lock (fileRouteGate)
        {
            if (nativeMediaTransfer is not null) nativeMediaTransfer.Failed = true;
            nativeMediaChunk?.Completion.TrySetException(DeviceFileControl.Error(reason));
        }
    }

    private void CheckNativeMediaTransferControl()
    {
        NativeMediaTransfer? transfer;
        lock (fileRouteGate) transfer = nativeMediaTransfer;
        if (transfer is null || !transfer.ActiveIo) return;
        try { RequireNativeMediaTransfer(transfer); }
        catch { CloseNativeMediaData("file_receive_native_control_changed"); }
    }
}
