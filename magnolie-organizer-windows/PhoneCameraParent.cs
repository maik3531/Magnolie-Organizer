using System.Net.Sockets;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private readonly object webcamGate = new();
    private PhoneCameraControlBinding? webcamBinding;
    private readonly Queue<(string Request, string Nonce)> webcamProbes = new();
    private sealed class WebcamAck(string id, PhoneCameraControlBinding binding)
    {
        internal readonly string Id = id;
        internal readonly PhoneCameraControlBinding Binding = binding;
        internal bool Observed;
    }
    private readonly Queue<WebcamAck> webcamAcks = new();
    private sealed record WrittenCapabilities(string Id, long Revision, JsonObject Body);
    private WrittenCapabilities? lastWebcamCapabilities;
    private readonly Dictionary<string, WeakReference<PhoneCameraControlBinding>?> webcamDiscoveryAcks = new();

    partial void NativeWebcamControl(JsonObject message, ref Task? handling) => handling = HandleWebcamControlAsync(message);
    partial void NativeWebcamAck(JsonObject message, ref bool consumed) => consumed = ObserveWebcamAck(message);
    partial void CheckNativeWebcamOwner() => CheckWebcamControl();
    partial void RetireNativeWebcamOwner() => RetireWebcamControl();
    internal void RequireWebcamBinding(PhoneCameraControlBinding binding)
    {
        RequireWebcamParent();
        if (!ReferenceEquals(Volatile.Read(ref webcamBinding), binding)) throw new InvalidOperationException("webcam_original_binding_required");
        if (binding.DiscoveryWritten && Volatile.Read(ref lastWebcamCapabilities)?.Id != binding.DiscoveryId)
            throw new InvalidOperationException("webcam_original_discovery_superseded");
    }
    internal (Socket Listener, System.Net.IPAddress Remote) OpenWebcamListener(PhoneCameraControlBinding binding)
    {
        RequireWebcamBinding(binding);
        var original = ((NetworkStream)stream).Socket;
        if (original.LocalEndPoint is not System.Net.IPEndPoint local || original.RemoteEndPoint is not System.Net.IPEndPoint remote)
            throw new InvalidOperationException("webcam_original_ip_parent_required");
        var listener = new Socket(original.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
        try
        {
            listener.Bind(new System.Net.IPEndPoint(local.Address, 0)); listener.Listen(1);
            binding.RequireCurrent(); return (listener, remote.Address);
        }
        catch { listener.Dispose(); throw; }
    }
    internal PhoneCameraControlBinding BindWebcamControl(Action originalCurrent, Action retire, bool needsDiscovery = false)
    {
        ArgumentNullException.ThrowIfNull(originalCurrent); ArgumentNullException.ThrowIfNull(retire);
        RequireWebcamParent(); originalCurrent();
        var binding = new PhoneCameraControlBinding(this, originalCurrent, retire, needsDiscovery);
        if (Interlocked.CompareExchange(ref webcamBinding, binding, null) is not null)
            throw new InvalidOperationException("webcam_original_owner_busy");
        binding.RequireCurrent(); return binding;
    }
    internal void ReleaseWebcamBinding(PhoneCameraControlBinding binding) => Interlocked.CompareExchange(ref webcamBinding, null, binding);
    internal bool ClaimWebcamProbe(JsonObject body)
    {
        lock (webcamGate)
        {
            var request = body["request_id"]!.GetValue<string>(); var nonce = body["nonce"]!.GetValue<string>();
            if (webcamProbes.Any(value => value.Request == request || value.Nonce == nonce)) return false;
            if (webcamProbes.Count == 16) return false; // Never forget old probe authority on this parent.
            webcamProbes.Enqueue((request, nonce)); return true;
        }
    }
    private void RetireWebcamControl() => Volatile.Read(ref webcamBinding)?.Dispose();
    private void CheckWebcamControl()
    {
        try { Volatile.Read(ref webcamBinding)?.RequireCurrent(); }
        catch (Exception) { } // Original native owner already retired, not a peer transport error.
    }

    private async Task HandleWebcamControlAsync(JsonObject message)
    {
        PhoneCameraControl.ValidateMessage(message, Now());
        if (message["kind"]!.GetValue<string>() != PhoneCameraControl.Request || transport != "wifi" || Volatile.Read(ref webcamBinding) is not { } binding)
        {
            await RejectUnavailableWebcamControlAsync(message);
            return;
        }
        var status = "rejected"; var error = "not_granted";
        try { if (binding.Submit(message)) { status = "accepted"; error = "none"; } }
        catch (Exception) { binding.Dispose(); }
        // ACK means queued control, never capture, output readiness or SEND.
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = message["message_id"]!.DeepClone(), ["status"] = status, ["error"] = error };
        await SendWebcamFrameAsync(ack, () => { });
    }
    internal async Task SendBoundWebcamReportAsync(PhoneCameraControlBinding binding, JsonObject message,
        PhoneCameraSession.OutputAuthority? original = null)
    {
        binding.RequireCurrent();
        if ((message["body"]!["op"]!.GetValue<string>() == "send") != (original is not null))
            throw new InvalidOperationException("webcam_typed_send_publication_required");
        void Current()
        {
            binding.RequireCurrent();
            original?.RequirePublication(binding);
        }
        Current();
        lock (webcamGate)
        {
            if (webcamAcks.Count == 16) webcamAcks.Dequeue();
            webcamAcks.Enqueue(new WebcamAck(message["message_id"]!.GetValue<string>(), binding));
        }
        try { await SendWebcamEphemeralAsync(message, Current); }
        catch
        {
            // A pre-commit output loss retires its session, not the original
            // control transport: finally must still be able to publish STOP.
            // Attempted IO remains fail-closed inside the actual crypto sender.
            if (original is null) binding.Dispose();
            throw;
        }
    }
    private bool ObserveWebcamAck(JsonObject ack)
    {
        PhoneCameraControlBinding? owner;
        lock (webcamGate)
        {
            var id = ack["message_id"]!.GetValue<string>();
            if (webcamDiscoveryAcks.TryGetValue(id, out var discovery))
            {
                // Keep the ID, not the owner, for the rest of this parent.
                webcamDiscoveryAcks[id] = null;
                owner = ack["status"]!.GetValue<string>() == "rejected" && discovery?.TryGetTarget(out var original) == true ? original : null;
            }
            else
            {
                var receipt = webcamAcks.FirstOrDefault(value => value.Id == id);
                if (receipt is null) return false;
                if (receipt.Observed) return true;
                receipt.Observed = true; owner = receipt.Binding;
            }
        }
        if (ack["status"]!.GetValue<string>() == "rejected") owner?.Dispose();
        return true; // Never feed original ephemeral IDs to durable retry policy.
    }

    partial void RememberNativeWebcamCapabilities(JsonObject frame)
    {
        // The original writer is held here; older queued duplicates do not
        // supersede the latest revision the phone can accept.
        if (frame["kind"]?.GetValue<string>() != "capabilities.update" || frame["body"] is not JsonObject body ||
            frame["message_id"] is not JsonValue id || !id.TryGetValue<string>(out var messageId) || messageId is null ||
            !TelefonProtocolContract.TryInteger(body["revision"], out var revision) || revision <= (lastWebcamCapabilities?.Revision ?? 0)) return;
        Volatile.Write(ref lastWebcamCapabilities, new(messageId, revision, body.DeepClone().AsObject()));
    }

    internal Task AdvertiseWebcamAsync(PhoneCameraControlBinding binding, Action requireStarting) => ChangeWebcamDiscoveryAsync(binding, requireStarting);
    internal Task WithdrawWebcamAsync(PhoneCameraControlBinding binding) => ChangeWebcamDiscoveryAsync(binding, null);

    private async Task ChangeWebcamDiscoveryAsync(PhoneCameraControlBinding binding, Action? requireStarting)
    {
        bool withdraw = requireStarting is null;
        void Current()
        {
            if (requireStarting is null) return;
            binding.RequireCurrent(); requireStarting();
        }
        Current();
        var witness = Volatile.Read(ref lastWebcamCapabilities);
        if (withdraw && (!binding.DiscoveryWritten || witness?.Id != binding.DiscoveryId)) return;
        if (witness is null) throw new InvalidOperationException("webcam_original_capabilities_required");
        var body = witness.Body.DeepClone().AsObject();
        var versions = body["items"]!["device_status"]!["versions"]!.AsArray();
        var index = versions.ToList().FindIndex(value => TelefonProtocolContract.TryInteger(value, out var version) && version == PhoneCameraControl.Version);
        if (withdraw && index >= 0) versions.RemoveAt(index);
        else if (!withdraw && index < 0 && versions.Count < 16) versions.Add(PhoneCameraControl.Version);
        else throw new InvalidOperationException("webcam_original_capability_budget");
        long revision = store.NextOwnRevision("capabilities");
        if (revision <= witness.Revision) throw new InvalidOperationException("webcam_original_capabilities_revision");
        body["revision"] = revision;
        var message = LiveControlEnvelope("capabilities.update", body);
        var id = message["message_id"]!.GetValue<string>();
        await SendWebcamFrameAsync(message, Current, () =>
        {
            if (!ReferenceEquals(lastWebcamCapabilities, witness)) throw new InvalidOperationException("webcam_original_capabilities_changed");
            lock (webcamGate)
            {
                // Keep a matching terminal slot for every admitted discovery.
                if (webcamDiscoveryAcks.Count >= (withdraw ? 32 : 16)) throw new InvalidOperationException("webcam_discovery_ack_capacity");
                if (!withdraw) binding.MarkDiscoveryWriting(id);
                webcamDiscoveryAcks.Add(id, withdraw ? null : new(binding));
            }
        }, preserveCompletedFrame: true, onWritten: withdraw ? null : binding.MarkDiscoveryWritten);
    }
    /// <summary>
    /// Bounded original-parent write for an explicit native webcam owner. Does
    /// not enqueue, persist, ACK, grant consent, advertise or start capture.
    /// Owner guard must only read live native identity and never acquire store
    /// or coordinator monitors while the original crypto writer is held.
    /// </summary>
    internal async Task SendWebcamEphemeralAsync(JsonObject message, Action originalCurrent)
    {
        ArgumentNullException.ThrowIfNull(originalCurrent);
        var snapshot = message.DeepClone().AsObject();
        PhoneCameraControl.ValidateMessage(snapshot, Now());
        if (snapshot["kind"]!.GetValue<string>() != PhoneCameraControl.Report)
            throw new InvalidDataException("webcam_desktop_report_required");
        await SendWebcamFrameAsync(snapshot, originalCurrent);
    }

}
