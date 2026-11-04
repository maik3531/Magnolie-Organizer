using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private sealed class NativeSourceStatusPending(NativeFileControlSession owner, NativeReceiverCommandTicket ticket,
        JsonObject message, (string SessionEpoch, long Sequence) witness, bool expectVideos)
    {
        internal readonly NativeFileControlSession Owner = owner;
        internal readonly NativeReceiverCommandTicket Ticket = ticket;
        internal readonly JsonObject Message = message;
        internal readonly (string SessionEpoch, long Sequence) Witness = witness;
        internal readonly bool ExpectVideos = expectVideos;
        internal readonly TaskCompletionSource<DeviceFileSourceStatus> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool OutputConfirmed;
    }
    private NativeSourceStatusPending? nativeSourceStatus;

    internal async Task<DeviceFileSourceStatus> ReadNativeFileSourceStatusAsync(CancellationToken callerCancellation = default)
    {
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, callerCancellation);
        lifetime.CancelAfter(TimeSpan.FromMilliseconds(DeviceFileControl.MaximumTtlMs));
        lifetime.Token.ThrowIfCancellationRequested();
        var owner = RequireNativeFileControls();
        var ticket = owner.ReceiverCommandTicket();
        NativeSourceStatusPending? pending = null;
        try
        {
            pending = new(owner, ticket, DeviceFileSources.CreateRequest("status", Now()), owner.ReceiverCommandWitness(ticket), FileMetadataReady(videos: true));
            lock (fileRouteGate)
            {
                if (fileRouteFaulted || !ReferenceEquals(fileControls, owner) || nativeSourceStatus is not null)
                    throw DeviceFileControl.Error("file_sources_native_command_busy");
                nativeSourceStatus = pending;
            }
            await fileControlIo.WaitAsync(lifetime.Token);
            try { await SendNativeSourceStatusAsync(pending, lifetime.Token); }
            finally { fileControlIo.Release(); }
            // The receive lane must be free while waiting for the response.
            return await pending.Completion.Task.WaitAsync(lifetime.Token);
        }
        catch (OperationCanceledException error) when (!cancellation.IsCancellationRequested && !callerCancellation.IsCancellationRequested)
        { throw new TimeoutException("file_sources_native_command_timeout", error); }
        finally
        {
            lock (fileRouteGate)
                if (ReferenceEquals(nativeSourceStatus, pending)) nativeSourceStatus = null;
            if (pending is not null)
            {
                pending.Completion.TrySetCanceled();
                if (pending.Completion.Task.IsFaulted) _ = pending.Completion.Task.Exception;
            }
            owner.FinishReceiverCommand(ticket); // Also legal after exact owner disposal.
        }
    }

    private void RequireNativeSourceStatus(NativeSourceStatusPending pending)
    {
        RequireNativeFileControls(pending.Owner);
        if (pending.ExpectVideos && !FileMetadataReady(videos: true)) throw DeviceFileControl.Error("file_sources_native_video_metadata_changed");
        lock (fileRouteGate)
            if (!ReferenceEquals(nativeSourceStatus, pending)) throw DeviceFileControl.Error("file_sources_native_command_changed");
        if (!pending.Owner.ReceiverCommandCurrent(pending.Ticket))
            throw DeviceFileControl.Error("file_sources_native_command_expired");
        var witness = pending.Owner.RemoteControlWitness();
        if (witness is null || witness.Value.SessionEpoch != pending.Witness.SessionEpoch || witness.Value.Sequence < pending.Witness.Sequence)
            throw DeviceFileControl.Error("file_sources_native_control_changed");
        DeviceFileSources.ParseRequest(pending.Message, Now());
    }

    private async Task SendNativeSourceStatusAsync(NativeSourceStatusPending pending, CancellationToken token)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token);
        var outputStarted = false;
        try
        {
            RequireNativeSourceStatus(pending);
            var envelope = Seal(pending.Message);
            outputStarted = true;
            await TelefonCoordinator.WriteFrameAsync(stream, envelope, deadline.Token);
            lastSentMs = Now();
            RequireNativeSourceStatus(pending);
            lock (fileRouteGate)
            {
                if (!ReferenceEquals(nativeSourceStatus, pending)) throw DeviceFileControl.Error("file_sources_native_command_changed");
                pending.OutputConfirmed = true;
            }
        }
        catch
        {
            CloseNativeFileRoute();
            if (outputStarted) stream.Dispose();
            throw;
        }
        finally { writer.Release(); }
    }

    private async Task ReceiveNativeSourceStatusAsync(JsonObject message)
    {
        await fileControlIo.WaitAsync(cancellation);
        try
        {
            NativeSourceStatusPending pending;
            lock (fileRouteGate)
            {
                pending = nativeSourceStatus ?? throw DeviceFileControl.Error("file_sources_native_unsolicited_result");
                if (!pending.OutputConfirmed) throw DeviceFileControl.Error("file_sources_native_output_unconfirmed");
            }
            RequireNativeSourceStatus(pending);
            var status = DeviceFileSources.ParseResult(message, pending.Message["message_id"]!.GetValue<string>(), "status", Now(), pending.ExpectVideos);
            RequireNativeSourceStatus(pending);
            if (!pending.Completion.TrySetResult(status)) throw DeviceFileControl.Error("file_sources_native_duplicate_result");
        }
        catch { CloseNativeFileRoute(); throw; }
        finally { fileControlIo.Release(); }
    }

    private void CheckNativeSourceStatusControl(NativeFileControlSession owner)
    {
        NativeSourceStatusPending? pending;
        lock (fileRouteGate) pending = nativeSourceStatus;
        if (pending is not null && ReferenceEquals(pending.Owner, owner) && !owner.ReceiverCommandCurrent(pending.Ticket))
            CloseNativeSourceStatus("file_sources_native_control_changed", pending);
    }

    private void CloseNativeSourceStatus(string reason = "file_sources_native_owner_closed", NativeSourceStatusPending? expected = null)
    {
        NativeSourceStatusPending? pending;
        lock (fileRouteGate)
        {
            if (expected is not null && !ReferenceEquals(nativeSourceStatus, expected)) return;
            pending = nativeSourceStatus; nativeSourceStatus = null;
        }
        pending?.Completion.TrySetException(DeviceFileControl.Error(reason));
    }
}
