using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private readonly object fileRouteGate = new();
    private readonly SemaphoreSlim fileControlIo = new(1, 1);
    private NativeFileControlSession? fileControls;
    private NativeFileControlIdentity? fileLocalIdentity;
    private bool fileRouteFaulted;

    internal NativeFileControlSession OpenNativeFileControls(Func<NativeLocalFileGrant?> currentLocal)
    {
        ArgumentNullException.ThrowIfNull(currentLocal);
        if (!FileMetadataReady()) throw DeviceFileControl.Error("file_control_metadata_pending");
        var identity = store.ReadFileIdentity();
        var owner = new NativeFileControlSession(identity, () => CurrentFileControlPeer(identity), currentLocal);
        lock (fileRouteGate)
        {
            if (disposed || fileRouteFaulted || fileControls is not null)
            { owner.Dispose(); throw DeviceFileControl.Error("file_control_native_owner_unavailable"); }
            fileControls = owner; fileLocalIdentity = identity;
        }
        return owner;
    }

    private NativeFileControlPeer? CurrentFileControlPeer(NativeFileControlIdentity expected)
    {
        try
        {
            if (!FileMetadataReady()) return null;
            var local = store.ReadFileIdentity();
            if (local != expected) { CloseNativeFileRoute(); return null; }
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
            if (!FileMetadataChannelCurrent(current) || !FileMetadataReady()) return null;
            var personal = store.PersonalSettings(peer.Id);
            return new(current!.Id, Convert.ToHexString(SHA256.HashData(current.PublicKey)).ToLowerInvariant(), this,
                true, current.State == "paired", personal.OwnDevice, personal.RemoteOwnDevice, true, current.FilePairingEpoch);
        }
        catch { CloseNativeFileRoute(); throw; }
    }

    private NativeFileControlSession RequireNativeFileControls(NativeFileControlSession? expected = null)
    {
        NativeFileControlSession owner;
        lock (fileRouteGate)
        {
            if (disposed || fileRouteFaulted || fileControls is null || expected is not null && !ReferenceEquals(expected, fileControls))
                throw DeviceFileControl.Error("file_control_native_owner_changed");
            owner = fileControls;
        }
        if (!FileMetadataReady()) throw DeviceFileControl.Error("file_control_metadata_pending");
        return owner;
    }

    internal async Task<bool> SendNativeFileControlsAsync()
    {
        await fileControlIo.WaitAsync(cancellation);
        try
        {
            var sent = await SendNativeFileControlsCoreAsync(RequireNativeFileControls()); CheckNativeMediaSendControl(); return sent;
        }
        finally { fileControlIo.Release(); }
    }

    private async Task<bool> SendNativeFileControlsCoreAsync(NativeFileControlSession owner)
    {
        if (!owner.NeedsPacket) return false;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token);
        var outputStarted = false;
        try
        {
            RequireNativeFileControls(owner);
            var packet = owner.Packet();
            var message = DeviceFileControlEnvelope.Create(packet, Now());
            var envelope = Seal(message);
            outputStarted = true;
            await TelefonCoordinator.WriteFrameAsync(stream, envelope, deadline.Token);
            lastSentMs = Now();
            RequireNativeFileControls(owner);
            DeviceFileControlEnvelope.Validate(message, Now());
            owner.MarkSent(packet); // Actual secure write, never enqueue acceptance.
            return true;
        }
        catch
        {
            CloseNativeFileRoute();
            if (outputStarted) stream.Dispose();
            throw;
        }
        finally { writer.Release(); }
    }

    partial void ReceiveNativeFileMessage(JsonObject message, ref Task? handling)
    {
        handling = ReceiveNativeFileControlAsync(message);
    }

    private async Task ReceiveNativeFileControlAsync(JsonObject message)
    {
        var kind = message["kind"]?.GetValue<string>();
        if (kind is DeviceFileAcceptanceEnvelope.Kind or DeviceFileChunkEnvelope.RequestKind or DeviceFileSavedEnvelope.Kind or DevicePublishedReadbackEnvelope.Kind)
        {
            await ReceiveNativeMediaSendAsync(message);
            return;
        }
        if (kind == DeviceFileChunkEnvelope.ResultKind)
        {
            await ReceiveNativeMediaChunkAsync(message);
            return;
        }
        if (kind == DeviceFileOfferEnvelope.Kind)
        {
            await ReceiveNativeSourceOfferAsync(message);
            return;
        }
        bool commandPending;
        lock (fileRouteGate) commandPending = nativeSourceCommand is not null;
        if (kind is DeviceFileSources.CatalogKind or DeviceFileSources.PermissionResultKind or DeviceFileSources.RunResultKind or DeviceFileSources.MediaKind or DeviceFileSources.ResumeKind || kind == DeviceFileSources.ResultKind && commandPending)
        {
            await ReceiveNativeSourceCommandAsync(message);
            return;
        }
        if (message["kind"]?.GetValue<string>() == DeviceFileSources.ResultKind)
        {
            await ReceiveNativeSourceStatusAsync(message);
            return;
        }
        // Reserved but unjoined data cannot enter the generic inbox/outbox.
        if (message["kind"]?.GetValue<string>() != DeviceFileControl.Kind)
        {
            CloseNativeFileRoute();
            throw DeviceFileControl.Error("file_control_data_handler_unavailable");
        }
        await fileControlIo.WaitAsync(cancellation);
        try
        {
            var owner = RequireNativeFileControls();
            var packet = DeviceFileControlEnvelope.Validate(message, Now());
            NativeFileControlIdentity identity;
            lock (fileRouteGate) identity = fileLocalIdentity ?? throw DeviceFileControl.Error("file_control_native_owner_changed");
            var current = CurrentFileControlPeer(identity) ?? throw DeviceFileControl.Error("file_control_native_scope_changed");
            owner.ObserveRemote(packet, current);
            CheckNativeSourceStatusControl(owner);
            CheckNativeSourceCommandControl(owner);
            CheckNativeMediaTransferControl();
            CheckNativeMediaSendControl();
            await SendNativeFileControlsCoreAsync(owner);
        }
        catch { CloseNativeFileRoute(); throw; }
        finally { fileControlIo.Release(); }
    }

    partial void CloseNativeFileRoute()
    {
        NativeFileControlSession? owner;
        lock (fileRouteGate)
        {
            fileRouteFaulted = true; owner = fileControls;
            fileControls = null; fileLocalIdentity = null;
        }
        CloseNativeSourceStatus();
        CloseNativeSourceCommands();
        CloseNativeMediaData();
        CloseNativeMediaSend();
        owner?.Dispose();
    }
}
