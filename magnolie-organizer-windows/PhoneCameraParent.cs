using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class PhoneCameraControl
{
    internal const string Request = "device_status.request";
    internal const string Report = "device_status.report";
    private static readonly string[] Base = ["version", "request_id", "nonce", "op"];
    private static readonly HashSet<string> Reasons = ["disabled", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired"];

    // Reserve malformed aliases too, before ordinary persistence/rejection paths.
    internal static bool IsReserved(string? kind, JsonObject? body) =>
        kind is Request or Report && body?["version"] is JsonValue version &&
        (TelefonProtocolContract.TryInteger(version, out var integer) && integer == 24 ||
         version.TryGetValue<string>(out var text) && text == "24" ||
         version.TryGetValue<double>(out var number) && number == 24);
    internal static bool IsReserved(JsonObject message) =>
        IsReserved(message["kind"] is JsonValue kind && kind.TryGetValue<string>(out var text) ? text : null, message["body"] as JsonObject);

    private static string Text(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("webcam_control_invalid");
    private static void Hex(JsonNode? node, int count)
    {
        if (!Regex.IsMatch(Text(node), "\\A[0-9a-f]{" + count + "}\\z"))
            throw new InvalidDataException("webcam_control_invalid");
    }
    internal static void ValidateBody(JsonObject body, string kind)
    {
        if (kind is not (Request or Report) || TelefonProtocolContract.Integer(body["version"]) != 24 ||
            !TelefonProtocolContract.IsUuidV4(Text(body["request_id"])))
            throw new InvalidDataException("webcam_control_invalid");
        Hex(body["nonce"], 64);
        var op = Text(body["op"]);
        var (direction, fields) = op switch
        {
            "probe" => (Request, Array.Empty<string>()),
            "offer" => (Report, new[] { "session", "secret", "port", "muted", "front" }),
            "unavailable" => (Report, new[] { "reason" }),
            "prepared" => (Request, new[] { "session" }),
            "send" => (Report, new[] { "session" }),
            "stop" => (kind, new[] { "session" }),
            "error" => (kind, new[] { "session", "reason" }),
            _ => throw new InvalidDataException("webcam_control_invalid")
        };
        if (direction != kind) throw new InvalidDataException("webcam_control_invalid");
        TelefonProtocolContract.ExactObject(body, Base.Concat(fields).ToArray());
        if (fields.Contains("session")) Hex(body["session"], 32);
        if (fields.Contains("reason") && !Reasons.Contains(Text(body["reason"])))
            throw new InvalidDataException("webcam_control_invalid");
        if (op == "offer")
        {
            Hex(body["secret"], 64);
            if (TelefonProtocolContract.Integer(body["port"]) is < 1024 or > 65535 ||
                body["muted"] is not JsonValue mute || !mute.TryGetValue<bool>(out _) ||
                body["front"] is not JsonValue front || !front.TryGetValue<bool>(out _))
                throw new InvalidDataException("webcam_control_invalid");
        }
    }
    internal static void ValidateMessage(JsonObject message, long now)
    {
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]);
        var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message["type"]) != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message["message_id"])) || created < 0 || created > now + 300_000 ||
            expires <= created || expires - created > 60_000 || expires <= now ||
            TelefonCrypto.Canonical(message).Length > 4096 || message["body"] is not JsonObject body)
            throw new InvalidDataException("webcam_control_invalid");
        ValidateBody(body, Text(message["kind"]));
    }
}

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

    private void RequireWebcamParent(bool wifiOnly = true)
    {
        if (Volatile.Read(ref disposed) || cancellation.IsCancellationRequested || RemoteCloseReason.Length > 0 || wifiOnly &&
            (transport != "wifi" || stream is not NetworkStream network || !network.Socket.Connected))
            throw new InvalidOperationException("webcam_original_parent_required");
    }
    internal void RequireWebcamBinding(PhoneCameraControlBinding binding)
    {
        RequireWebcamParent();
        if (!ReferenceEquals(Volatile.Read(ref webcamBinding), binding)) throw new InvalidOperationException("webcam_original_binding_required");
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
    internal PhoneCameraControlBinding BindWebcamControl(Action originalCurrent, Action retire)
    {
        ArgumentNullException.ThrowIfNull(originalCurrent); ArgumentNullException.ThrowIfNull(retire);
        RequireWebcamParent(); originalCurrent();
        var binding = new PhoneCameraControlBinding(this, originalCurrent, retire);
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
        var status = "rejected"; var error = "not_granted";
        if (message["kind"]!.GetValue<string>() != PhoneCameraControl.Request) error = "invalid_schema";
        else if (transport == "wifi" && Volatile.Read(ref webcamBinding) is { } binding)
        {
            try { if (binding.Submit(message)) { status = "accepted"; error = "none"; } }
            catch (Exception) { binding.Dispose(); }
        }
        // ACK means queued control, never capture, output readiness or SEND.
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = message["message_id"]!.DeepClone(), ["status"] = status, ["error"] = error };
        await SendWebcamFrameAsync(ack, () => { });
    }
    internal async Task SendBoundWebcamReportAsync(PhoneCameraControlBinding binding, JsonObject message)
    {
        binding.RequireCurrent();
        lock (webcamGate)
        {
            if (webcamAcks.Count == 16) webcamAcks.Dequeue();
            webcamAcks.Enqueue(new WebcamAck(message["message_id"]!.GetValue<string>(), binding));
        }
        try { await SendWebcamEphemeralAsync(message, binding.RequireCurrent); }
        catch { binding.Dispose(); throw; }
    }
    private bool ObserveWebcamAck(JsonObject ack)
    {
        PhoneCameraControlBinding? owner;
        lock (webcamGate)
        {
            var receipt = webcamAcks.FirstOrDefault(value => value.Id == ack["message_id"]!.GetValue<string>());
            if (receipt is null) return false;
            if (receipt.Observed) return true;
            receipt.Observed = true; owner = receipt.Binding;
        }
        if (ack["status"]!.GetValue<string>() == "rejected") owner.Dispose();
        return true; // Never feed original ephemeral IDs to durable retry policy.
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

    private async Task SendWebcamFrameAsync(JsonObject snapshot, Action originalCurrent)
    {
        void Current()
        {
            RequireWebcamParent(snapshot["type"]!.GetValue<string>() != "ack");
            originalCurrent();
        }
        Current();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(2));
        await writer.WaitAsync(deadline.Token);
        var attempted = false;
        try
        {
            Current();
            if (snapshot["type"]!.GetValue<string>() == "message") PhoneCameraControl.ValidateMessage(snapshot, Now());
            else TelefonProtocolContract.ValidateAck(snapshot);
            deadline.Token.ThrowIfCancellationRequested();
            if (sendSequence == long.MaxValue) throw new InvalidOperationException("webcam_control_sequence_exhausted");
            var header = Header(sendSequence, "desktop_to_phone");
            var clear = TelefonCrypto.Canonical(snapshot);
            var cipher = new byte[clear.Length]; var tag = new byte[16];
            try
            {
                using var aes = new AesGcm(sendKey, 16);
                aes.Encrypt(sendPrefix.Concat(LongBytes(sendSequence)).ToArray(), clear, cipher, tag, TelefonCrypto.Canonical(header));
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
            header["ciphertext"] = Convert.ToBase64String(cipher.Concat(tag).ToArray());
            Current();
            deadline.Token.ThrowIfCancellationRequested();
            sendSequence++;
            attempted = true;
            await TelefonCoordinator.WriteFrameAsync(stream, header, deadline.Token);
            Current();
            deadline.Token.ThrowIfCancellationRequested();
            lastSentMs = Now();
        }
        catch
        {
            // No counter consumed/healthy-parent close on admission rejection.
            // Once ciphertext IO was attempted, that original sequence/pipe
            // cannot be retried, guessed, replaced or used for another frame.
            if (attempted) stream.Dispose();
            throw;
        }
        finally { writer.Release(); }
    }
}
