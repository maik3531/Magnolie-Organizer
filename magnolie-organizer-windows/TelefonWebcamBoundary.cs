using System.Net.Sockets;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Always-present protocol boundary, including builds that omit every optional
// webcam module. This reserves/rejects controls; it is not a provider or grant.
internal static class PhoneCameraControl
{
    internal const int Version = 24;
    internal const string Request = "device_status.request";
    internal const string Report = "device_status.report";
    private static readonly string[] Base = ["version", "request_id", "nonce", "op"];
    private static readonly HashSet<string> Reasons = ["disabled", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired"];

    internal static bool IsReserved(string? kind, JsonObject? body) =>
        kind is Request or Report && body?["version"] is JsonValue version &&
        (TelefonProtocolContract.TryInteger(version, out var integer) && integer == Version ||
         version.TryGetValue<string>(out var text) && text == "24" ||
         version.TryGetValue<double>(out var number) && number == Version);
    internal static bool IsReserved(JsonObject message) =>
        IsReserved(message["kind"] is JsonValue kind && kind.TryGetValue<string>(out var text) ? text : null, message["body"] as JsonObject);
    private static string Text(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("webcam_control_invalid");
    private static void Hex(JsonNode? node, int count)
    {
        if (!Regex.IsMatch(Text(node), "\\A[0-9a-f]{" + count + "}\\z")) throw new InvalidDataException("webcam_control_invalid");
    }
    internal static void ValidateBody(JsonObject body, string kind)
    {
        if (kind is not (Request or Report) || TelefonProtocolContract.Integer(body["version"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(body["request_id"]))) throw new InvalidDataException("webcam_control_invalid");
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
        if (fields.Contains("reason") && !Reasons.Contains(Text(body["reason"]))) throw new InvalidDataException("webcam_control_invalid");
        if (op == "offer")
        {
            Hex(body["secret"], 64);
            if (TelefonProtocolContract.Integer(body["port"]) is < 1024 or > 65535 ||
                body["muted"] is not JsonValue mute || !mute.TryGetValue<bool>(out _) ||
                body["front"] is not JsonValue front || !front.TryGetValue<bool>(out _)) throw new InvalidDataException("webcam_control_invalid");
        }
    }
    internal static void ValidateMessage(JsonObject message, long now)
    {
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]); var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message["type"]) != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message["message_id"])) || created < 0 || created > now + 300_000 ||
            expires <= created || expires - created > 60_000 || expires <= now ||
            TelefonCrypto.Canonical(message).Length > 4096 || message["body"] is not JsonObject body) throw new InvalidDataException("webcam_control_invalid");
        ValidateBody(body, Text(message["kind"]));
    }
}

// Always-built reservation for #245, separate from webcam v24 and its grants.
internal static class PhoneScreenControl
{
    internal const int Version = 26;
    internal const string Request = "device_status.request", Report = "device_status.report";
    private static readonly string[] Base = ["version", "request_id", "nonce", "op"];
    private static readonly HashSet<string> Reasons = ["not_granted", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired"];

    internal static bool IsReserved(string? kind, JsonObject? body) => kind is Request or Report && body?["version"] is JsonValue version &&
        (TelefonProtocolContract.TryInteger(version, out var integer) && integer == Version ||
         version.TryGetValue<string>(out string? text) && text == "26" ||
         version.TryGetValue<double>(out var number) && number == Version);

    internal static bool IsReserved(JsonObject message) => IsReserved(
        message["kind"] is JsonValue kind && kind.TryGetValue<string>(out var value) ? value : null, message["body"] as JsonObject);

    private static string Text(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text)
        ? text : throw new InvalidDataException("screen_control_invalid");

    private static void Hex(JsonNode? node, int count)
    {
        var text = Text(node);
        if (text.Length != count || text.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f')))
            throw new InvalidDataException("screen_control_invalid");
    }

    internal static void ValidateMessage(JsonObject message, long now)
    {
        TelefonProtocolContract.ExactObject(message, "type", "v", "message_id", "kind", "created_ms", "expires_ms", "body");
        var created = TelefonProtocolContract.Integer(message["created_ms"]);
        var expires = TelefonProtocolContract.Integer(message["expires_ms"]);
        if (Text(message["type"]) != "message" || TelefonProtocolContract.Integer(message["v"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(Text(message["message_id"])) || created < 0 || created > now + 60_000 ||
            expires <= created || expires - created > 60_000 || expires <= now || TelefonCrypto.Canonical(message).Length > 4096 ||
            message["body"] is not JsonObject body) throw new InvalidDataException("screen_control_envelope_invalid");
        ValidateBody(body, Text(message["kind"]));
    }

    internal static void ValidateBody(JsonObject body, string kind)
    {
        if (kind is not (Request or Report) || TelefonProtocolContract.Integer(body["version"]) != Version ||
            !TelefonProtocolContract.IsUuidV4(Text(body["request_id"]))) throw new InvalidDataException("screen_control_invalid");
        Hex(body["nonce"], 64);
        var op = Text(body["op"]);
        var (direction, fields) = op switch
        {
            "probe" => (Request, Array.Empty<string>()),
            "offer" => (Report, new[] { "session", "secret", "port", "width", "height", "density" }),
            "prepared" => (Request, new[] { "session" }),
            "send" => (Report, new[] { "session" }),
            "stop" => (kind, new[] { "session" }),
            "error" => (kind, new[] { "session", "reason" }),
            _ => throw new InvalidDataException("screen_control_invalid")
        };
        if (direction != kind) throw new InvalidDataException("screen_control_invalid");
        TelefonProtocolContract.ExactObject(body, Base.Concat(fields).ToArray());
        if (fields.Contains("session")) Hex(body["session"], 32);
        if (op == "error" && !Reasons.Contains(Text(body["reason"]))) throw new InvalidDataException("screen_control_invalid");
        if (op == "offer")
        {
            Hex(body["secret"], 64);
            var width = TelefonProtocolContract.Integer(body["width"]);
            var height = TelefonProtocolContract.Integer(body["height"]);
            if (width is < 2 or > 1920 || height is < 2 or > 1920 || width * height > 1920 * 1080 ||
                TelefonProtocolContract.Integer(body["port"]) is < 1024 or > 65535 ||
                TelefonProtocolContract.Integer(body["density"]) is < 1 or > 1000)
                throw new InvalidDataException("screen_control_invalid");
        }
    }
}

internal sealed partial class TelefonConnection
{
    partial void NativeWebcamControl(JsonObject message, ref Task? handling);
    partial void NativeWebcamAck(JsonObject message, ref bool consumed);
    partial void CheckNativeWebcamOwner();
    partial void RetireNativeWebcamOwner();
    // Elided in the product (no implementation). The test host observes the
    // actual queued writer task without replacing sender behavior or polling.
    partial void ObserveNativeWebcamWriterWait(JsonObject snapshot, Task waiting);
    partial void RememberNativeWebcamCapabilities(JsonObject frame);
    partial void FenceNativeWebcamParent();
    internal void FenceWebcamParent() => FenceNativeWebcamParent();

    private async Task DispatchWebcamControlAsync(JsonObject message)
    {
        PhoneCameraControl.ValidateMessage(message, Now());
        Task? handling = null; NativeWebcamControl(message, ref handling);
        if (handling is not null) { await handling; return; }
        await RejectUnavailableWebcamControlAsync(message);
    }
    private async Task RejectUnavailableWebcamControlAsync(JsonObject message)
    {
        PhoneCameraControl.ValidateMessage(message, Now());
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = message["message_id"]!.DeepClone(),
            ["status"] = "rejected", ["error"] = message["kind"]!.GetValue<string>() == PhoneCameraControl.Request ? "not_granted" : "invalid_schema" };
        await SendWebcamFrameAsync(ack, () => { });
    }

    private async Task RejectUnavailableScreenControlAsync(JsonObject message)
    {
        if (message["message_id"] is not JsonValue id || !id.TryGetValue<string>(out var value) ||
            !TelefonProtocolContract.IsUuidV4(value)) throw new InvalidDataException("screen_control_invalid");
        var reason = "not_granted";
        var accepted = false;
        try
        {
            PhoneScreenControl.ValidateMessage(message, Now());
            if (message["kind"]!.GetValue<string>() != PhoneScreenControl.Request) reason = "invalid_schema";
            else accepted = ObserveScreenControl(message);
        }
        catch (InvalidDataException) { reason = "invalid_schema"; }
        await SendWebcamFrameAsync(new JsonObject { ["type"] = "ack", ["message_id"] = value,
            ["status"] = accepted ? "accepted" : "rejected", ["error"] = accepted ? "none" : reason }, () => { });
    }

    private readonly object screenGate = new();
    private object? screenAdvertisement;
    private string? screenAdvertisementId;
    private bool screenAdvertisementWriting;
    private readonly HashSet<string> screenProbeIds = [];
    private readonly HashSet<string> screenProbeNonces = [];
    private readonly Dictionary<string, WeakReference<ScreenControl>> screenAcks = [];
    private ScreenProbe? screenProbe;
    private ScreenControl? screenControl;

    internal sealed class ScreenProbe(TelefonConnection parent, object marker, string id, string nonce, long deadline)
    {
        internal readonly TelefonConnection Parent = parent;
        internal readonly object Marker = marker;
        internal readonly string Id = id, Nonce = nonce;
        internal readonly long Deadline = deadline;
        internal bool Fresh => Stopwatch.GetTimestamp() < Deadline;
    }

    // Called only by the separately gated native composition. Default callers
    // continue using SendCapabilitiesAsync, which never advertises v26.
    internal async Task SendScreenCapabilitiesAsync(long revision, Action originalCurrent)
    {
        RequireWebcamParent(); originalCurrent();
        var body = TelefonProtocolContract.DesktopCapabilities();
        body["revision"] = revision;
        body["items"]!["device_status"]!["versions"]!.AsArray().Add(PhoneScreenControl.Version);
        var marker = new object();
        var message = LiveControlEnvelope("capabilities.update", body);
        lock (screenGate)
        {
            if (screenAdvertisementId is not null) throw new InvalidOperationException("screen_original_advertisement_already_used");
            screenAdvertisement = marker;
            screenAdvertisementId = message["message_id"]!.GetValue<string>();
        }
        try
        {
            await SendWebcamFrameAsync(message, originalCurrent, () =>
            {
                lock (screenGate)
                {
                    if (!ReferenceEquals(screenAdvertisement, marker)) throw new InvalidOperationException("screen_advertisement_retired");
                    screenAdvertisementWriting = true;
                }
            });
        }
        catch { RetireScreenControl(); throw; }
    }

    internal ScreenProbe? CurrentScreenProbe()
    {
        lock (screenGate) return screenProbe is { Fresh: true } value && screenAdvertisement is not null && screenControl is null ? value : null;
    }

    internal ScreenControl BindScreenControl(ScreenProbe expected, Action current, Action stop)
    {
        RequireWebcamParent(); current();
        lock (screenGate)
        {
            if (!ReferenceEquals(screenProbe, expected) || !ReferenceEquals(expected.Parent, this) ||
                !ReferenceEquals(expected.Marker, screenAdvertisement) || !expected.Fresh || screenControl is not null)
                throw new InvalidOperationException("screen_original_probe_changed");
            screenProbe = null; // Never re-offer this same probe.
            return screenControl = new ScreenControl(this, expected, current, stop);
        }
    }

    private bool ObserveScreenControl(JsonObject message)
    {
        if (transport != "wifi" || stream is not NetworkStream) return false;
        var body = message["body"]!.AsObject();
        ScreenControl? owner;
        lock (screenGate)
        {
            if (screenAdvertisement is not { } marker || !screenAdvertisementWriting) return false;
            if (body["op"]!.GetValue<string>() == "probe")
            {
                var id = body["request_id"]!.GetValue<string>();
                var nonce = body["nonce"]!.GetValue<string>();
                long budget = TelefonProtocolContract.Integer(message["expires_ms"]) - Now();
                if (budget <= 0 || screenProbeIds.Count == 1024 || screenProbeIds.Contains(id) || screenProbeNonces.Contains(nonce)) return false;
                screenProbeIds.Add(id); screenProbeNonces.Add(nonce);
                screenProbe = new ScreenProbe(this, marker, id, nonce, Stopwatch.GetTimestamp() + budget * Stopwatch.Frequency / 1000);
                return true;
            }
            owner = screenControl;
        }
        return owner?.Observe(body) == true;
    }

    private void RetireScreenControl()
    {
        ScreenControl? owner;
        lock (screenGate) { screenAdvertisement = null; screenAdvertisementWriting = false; screenProbe = null; owner = screenControl; }
        owner?.Stop();
    }

    private bool ConsumeScreenAck(string id, string status)
    {
        WeakReference<ScreenControl>? receipt;
        bool advertisement;
        lock (screenGate)
        {
            advertisement = screenAdvertisementId == id;
            if (!screenAcks.TryGetValue(id, out receipt) && !advertisement) return false;
        }
        if (status == "rejected")
        {
            if (advertisement) RetireScreenControl();
            else if (receipt?.TryGetTarget(out var owner) == true) owner.Stop();
        }
        return true;
    }

    private static JsonObject LiveControlEnvelope(string kind, JsonObject body)
    {
        var now = Now();
        return new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = kind, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body };
    }

    internal sealed class ScreenControl
    {
        private readonly TelefonConnection parent;
        private readonly ScreenProbe probe;
        private readonly Action originalCurrent, requestStop;
        private readonly object gate = new();
        private readonly TaskCompletionSource prepared = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly string session = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
        private int phase; // adopted, offered, prepared, publishing SEND, sending, retired
        private int released;
        internal Task Prepared => prepared.Task;
        internal long Deadline => probe.Deadline;
        internal byte[] SessionId => Convert.FromHexString(session);
        internal bool Retired => Volatile.Read(ref phase) == 5;

        internal ScreenControl(TelefonConnection parent, ScreenProbe probe, Action originalCurrent, Action requestStop)
        { this.parent = parent; this.probe = probe; this.originalCurrent = originalCurrent; this.requestStop = requestStop; }

        internal void Current()
        {
            parent.RequireWebcamParent(); originalCurrent();
            if (Retired || (!probe.Fresh && Volatile.Read(ref phase) != 4)) throw new InvalidOperationException("screen_original_owner_retired");
        }

        internal (Socket Listener, System.Net.IPAddress Peer) OpenListener()
        {
            Current();
            var socket = ((NetworkStream)parent.stream).Socket;
            if (socket.LocalEndPoint is not System.Net.IPEndPoint local || socket.RemoteEndPoint is not System.Net.IPEndPoint remote)
                throw new InvalidOperationException("screen_original_ip_parent_required");
            var listener = new Socket(socket.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                if (socket.AddressFamily == AddressFamily.InterNetworkV6) listener.DualMode = false;
                listener.Bind(new System.Net.IPEndPoint(local.Address, 0)); listener.Listen(1);
                Current(); return (listener, remote.Address);
            }
            catch { listener.Dispose(); throw; }
        }

        private JsonObject Body(string op) => new() { ["version"] = PhoneScreenControl.Version,
            ["op"] = op, ["request_id"] = probe.Id, ["nonce"] = probe.Nonce, ["session"] = session };

        internal async Task OfferAsync(byte[] key, int port, int width, int height, int density)
        {
            Current();
            lock (gate) { if (phase != 0) throw new InvalidOperationException("screen_offer_already_used"); phase = 1; }
            var offer = Body("offer");
            offer["secret"] = Convert.ToHexString(key).ToLowerInvariant(); offer["port"] = port;
            offer["width"] = width; offer["height"] = height; offer["density"] = density;
            try { await WriteAsync(offer, Current); } catch { Stop(); throw; }
        }

        internal async Task SendAsync(Action requireProvenData)
        {
            Current();
            lock (gate) { if (phase != 2) throw new InvalidOperationException("screen_prepared_required"); phase = 3; }
            void Require() { Current(); requireProvenData(); if (Volatile.Read(ref phase) != 3) throw new InvalidOperationException("screen_send_retired"); }
            try
            {
                await WriteAsync(Body("send"), Require);
                Require();
                lock (gate) { if (phase != 3) throw new InvalidOperationException("screen_send_retired"); phase = 4; }
            }
            catch { Stop(); throw; }
        }

        internal void RequireSend()
        { Current(); if (Volatile.Read(ref phase) != 4) throw new InvalidOperationException("screen_original_send_required"); }

        internal async Task StopPeerAsync()
        {
            if (!Retired) throw new InvalidOperationException("screen_owner_not_retired");
            lock (gate) if (!offerAttempted || remoteStopped || terminalWritten) return; else terminalWritten = true;
            await WriteAsync(Body("stop"), () => parent.RequireWebcamParent());
        }

        private bool offerAttempted, remoteStopped, terminalWritten;
        internal bool Observe(JsonObject body)
        {
            if (body["request_id"]!.GetValue<string>() != probe.Id || body["nonce"]!.GetValue<string>() != probe.Nonce ||
                body["session"]?.GetValue<string>() != session) return false;
            try { Current(); } catch (Exception) { Stop(); return false; }
            lock (gate)
            {
                if (phase is 0 or 5) return false;
                if (body["op"]!.GetValue<string>() is "stop" or "error") remoteStopped = true;
                else
                {
                    if (phase != 1 || !offerAttempted || body["op"]!.GetValue<string>() != "prepared") return false;
                    phase = 2; prepared.TrySetResult(); return true;
                }
            }
            Stop(); return true;
        }

        private Task WriteAsync(JsonObject body, Action guard)
        {
            var message = LiveControlEnvelope(PhoneScreenControl.Report, body);
            var id = message["message_id"]!.GetValue<string>();
            lock (parent.screenGate)
            {
                if (parent.screenAcks.Count >= 4096) throw new InvalidOperationException("screen_ack_capacity");
                parent.screenAcks.Add(id, new WeakReference<ScreenControl>(this));
            }
            return parent.SendWebcamFrameAsync(message, guard, () =>
            {
                lock (gate)
                {
                    switch (body["op"]!.GetValue<string>())
                    {
                        case "offer" when phase == 1: offerAttempted = true; break;
                        case "send" when phase == 3:
                        case "stop" when phase == 5: break;
                        default: throw new InvalidOperationException("screen_write_owner_retired");
                    }
                }
            }, preserveCompletedFrame: true);
        }

        internal void Stop()
        {
            lock (gate) { if (phase == 5) return; phase = 5; prepared.TrySetCanceled(); }
            try { requestStop(); } catch (Exception) { /* Outer owner verifies its own drain. */ }
        }

        internal void ReleaseAfterDrain()
        {
            if (!Retired) throw new InvalidOperationException("screen_owner_not_retired");
            if (Interlocked.Exchange(ref released, 1) != 0) return;
            lock (parent.screenGate) if (ReferenceEquals(parent.screenControl, this)) parent.screenControl = null;
        }
    }
    private bool ConsumeWebcamAck(JsonObject message)
    { var consumed = false; NativeWebcamAck(message, ref consumed); return consumed; }
    private void RequireWebcamParent(bool wifiOnly = true)
    {
        if (Volatile.Read(ref disposed) || cancellation.IsCancellationRequested || RemoteCloseReason.Length > 0 || wifiOnly &&
            (transport != "wifi" || stream is not NetworkStream network || !network.Socket.Connected))
            throw new InvalidOperationException("webcam_original_parent_required");
    }
    private async Task SendWebcamFrameAsync(JsonObject snapshot, Action originalCurrent, Action? onWriting = null,
        bool preserveCompletedFrame = false, Action? onWritten = null)
    {
        void Current() { RequireWebcamParent(snapshot["type"]!.GetValue<string>() != "ack"); originalCurrent(); }
        Current();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(2));
        var waiting = writer.WaitAsync(deadline.Token);
        ObserveNativeWebcamWriterWait(snapshot, waiting);
        await waiting; var attempted = false; var completed = false;
        try
        {
            Current();
            if (PhoneScreenControl.IsReserved(snapshot)) PhoneScreenControl.ValidateMessage(snapshot, Now());
            else if (snapshot["kind"]?.GetValue<string>() == "capabilities.update" && snapshot["body"] is JsonObject capabilities)
                TelefonProtocolContract.ValidateCapabilities(capabilities);
            else if (snapshot["type"]!.GetValue<string>() == "message") PhoneCameraControl.ValidateMessage(snapshot, Now());
            else TelefonProtocolContract.ValidateAck(snapshot);
            deadline.Token.ThrowIfCancellationRequested();
            if (sendSequence == long.MaxValue) throw new InvalidOperationException("webcam_control_sequence_exhausted");
            var header = Header(sendSequence, "desktop_to_phone"); var clear = TelefonCrypto.Canonical(snapshot);
            var cipher = new byte[clear.Length]; var tag = new byte[16];
            try
            {
                using var aes = new AesGcm(sendKey, 16);
                aes.Encrypt(sendPrefix.Concat(LongBytes(sendSequence)).ToArray(), clear, cipher, tag, TelefonCrypto.Canonical(header));
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
            header["ciphertext"] = Convert.ToBase64String(cipher.Concat(tag).ToArray());
            Current(); deadline.Token.ThrowIfCancellationRequested(); onWriting?.Invoke(); sendSequence++; attempted = true;
            await TelefonCoordinator.WriteFrameAsync(stream, header, deadline.Token);
            completed = true;
            RememberNativeWebcamCapabilities(snapshot);
            onWritten?.Invoke();
            Current(); deadline.Token.ThrowIfCancellationRequested(); lastSentMs = Now();
        }
        catch
        {
            // An incomplete encrypted frame cannot be retried. Callers with
            // exact retirement controls can preserve a fully written frame.
            if (attempted && !(preserveCompletedFrame && completed)) stream.Dispose();
            throw;
        }
        finally { writer.Release(); }
    }
}
