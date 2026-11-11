using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

// Always-present protocol boundary, including builds that omit every optional
// webcam module. This reserves/rejects controls; it is not a provider or grant.
internal static class PhoneCameraControl
{
    internal const string Request = "device_status.request";
    internal const string Report = "device_status.report";
    private static readonly string[] Base = ["version", "request_id", "nonce", "op"];
    private static readonly HashSet<string> Reasons = ["disabled", "unsupported", "foreground_required", "permission_denied", "capture_failed", "output_failed", "retired"];

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
        if (!Regex.IsMatch(Text(node), "\\A[0-9a-f]{" + count + "}\\z")) throw new InvalidDataException("webcam_control_invalid");
    }
    internal static void ValidateBody(JsonObject body, string kind)
    {
        if (kind is not (Request or Report) || TelefonProtocolContract.Integer(body["version"]) != 24 ||
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

internal sealed partial class TelefonConnection
{
    partial void NativeWebcamControl(JsonObject message, ref Task? handling);
    partial void NativeWebcamAck(JsonObject message, ref bool consumed);
    partial void CheckNativeWebcamOwner();
    partial void RetireNativeWebcamOwner();
    // Elided in the product (no implementation). The test host observes the
    // actual queued writer task without replacing sender behavior or polling.
    partial void ObserveNativeWebcamWriterWait(JsonObject snapshot, Task waiting);

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
    private bool ConsumeWebcamAck(JsonObject message)
    { var consumed = false; NativeWebcamAck(message, ref consumed); return consumed; }
    private void RequireWebcamParent(bool wifiOnly = true)
    {
        if (Volatile.Read(ref disposed) || cancellation.IsCancellationRequested || RemoteCloseReason.Length > 0 || wifiOnly &&
            (transport != "wifi" || stream is not NetworkStream network || !network.Socket.Connected))
            throw new InvalidOperationException("webcam_original_parent_required");
    }
    private async Task SendWebcamFrameAsync(JsonObject snapshot, Action originalCurrent)
    {
        void Current() { RequireWebcamParent(snapshot["type"]!.GetValue<string>() != "ack"); originalCurrent(); }
        Current();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(2));
        var waiting = writer.WaitAsync(deadline.Token);
        ObserveNativeWebcamWriterWait(snapshot, waiting);
        await waiting; var attempted = false;
        try
        {
            Current();
            if (snapshot["type"]!.GetValue<string>() == "message") PhoneCameraControl.ValidateMessage(snapshot, Now());
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
            Current(); deadline.Token.ThrowIfCancellationRequested(); sendSequence++; attempted = true;
            await TelefonCoordinator.WriteFrameAsync(stream, header, deadline.Token);
            Current(); deadline.Token.ThrowIfCancellationRequested(); lastSentMs = Now();
        }
        catch
        {
            // Never retry a counter/frame whose ciphertext IO was attempted.
            if (attempted) stream.Dispose();
            throw;
        }
        finally { writer.Release(); }
    }
}
