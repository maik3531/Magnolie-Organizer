using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed class TimerControlWait
    {
        internal required string PeerId, Fingerprint, Source, Action, OperationId;
        internal required byte[] PublicKey;
        internal required TelefonConnection Connection;
        internal required long Deadline;
        internal required CancellationTokenSource Cancellation;
        internal readonly TaskCompletionSource<JsonObject> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }
    private readonly Dictionary<string, TimerControlWait> timerControls = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> retiredTimerControls = new(StringComparer.Ordinal);

    private async Task<JsonObject> ExecuteMcpTimeControlAsync(JsonObject request, CancellationToken cancellation)
    {
        try
        {
            var action = McpText(request, "action", true); var id = McpText(request, "peerId", true); var fingerprint = McpText(request, "fingerprint", true);
            if (action == "time_control_source") {
                var timerAction = McpText(request, "timerAction"); if (timerAction.Length == 0) timerAction = "read";
                if (timerAction is not ("read" or "start" or "pause" or "resume" or "finish")) throw new InvalidDataException();
                var source = TimeControlSource(id, fingerprint, timerAction != "read");
                bool supported;
                lock (gate) {
                    var peer = RequireMcpPeer(id, fingerprint); var local = SharedLocalCapabilities()["personal_tasks_sync"];
                    var remote = peer.Capabilities["personal_tasks_sync"];
                    supported = local?["available"]?.GetValue<bool>() == true && remote?["available"]?.GetValue<bool>() == true &&
                        (local?["versions"] as JsonArray ?? []).Any(value => TelefonProtocolContract.Integer(value) == TimeControlContract.Version) &&
                        (remote?["versions"] as JsonArray ?? []).Any(value => TelefonProtocolContract.Integer(value) == TimeControlContract.Version);
                }
                return new() { ["ok"] = source is not null, ["sourceRevision"] = source ?? "", ["code"] = source is not null ? "none" : supported ? "not_granted" : "unsupported_feature" };
            }
            if (action == "time_control_cancel") return new() { ["ok"] = true, ["request_id"] = McpText(request, "requestId", true),
                ["cancel_requested"] = CancelTimeControl(id, fingerprint, McpText(request, "requestId", true)), ["remote_recall_confirmed"] = false };
            if (action != "time_control_query" || request["body"] is not JsonObject body) throw new InvalidDataException();
            return new() { ["ok"] = true, ["timeControl"] = await RequestTimeControlAsync(id, fingerprint, body, McpText(request, "sourceRevision", true), cancellation) };
        }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled_after_dispatch" }; }
        catch (TimeoutException) { return new() { ["ok"] = false, ["code"] = "native_timeout_after_dispatch" }; }
        catch (McpConflictException) { return new() { ["ok"] = false, ["code"] = "source_changed" }; }
        catch (Exception error) when (error is InvalidDataException or McpRequestException or FormatException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (InvalidOperationException error) { return new() { ["ok"] = false, ["code"] = error.Message == "timer_control_busy" ? "native_busy" : "source_changed" }; }
        catch (IOException) { return new() { ["ok"] = false, ["code"] = "native_operation_failed_after_dispatch" }; }
    }

    internal string? TimeControlSource(string id, string fingerprint, bool mutation)
    {
        lock (gate)
        {
            if (disposed || !Enabled || store.RestoreFenced) return null;
            try
            {
                var peer = RequireMcpPeer(id, fingerprint); RequireSolePeer(id);
                if (!online.TryGetValue(peer.Id, out var connection)) return null;
                var snapshot = connection.TimerControlSourceSnapshot(mutation); snapshot["profile"] = identity.Id;
                return Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, TelefonCrypto.Canonical(snapshot))).ToLowerInvariant();
            }
            catch (Exception error) when (error is InvalidOperationException or InvalidDataException or McpRequestException) { return null; }
        }
    }

    internal async Task<JsonObject> RequestTimeControlAsync(string id, string fingerprint, JsonObject body, string expectedSource = "", CancellationToken cancellation = default)
    {
        TimeControlContract.ValidateRequest(body); cancellation.ThrowIfCancellationRequested();
        var requestId = body["request_id"]!.GetValue<string>(); TimerControlWait pending;
        lock (gate)
        {
            var now = Environment.TickCount64;
            foreach (var key in retiredTimerControls.Where(value => value.Value <= now).Select(value => value.Key).ToArray()) retiredTimerControls.Remove(key);
            var action = body["action"]!.GetValue<string>();
            var source = TimeControlSource(id, fingerprint, action != "read") ?? throw new InvalidOperationException("timer_source_changed");
            if (expectedSource.Length != 0 && expectedSource != source) throw new McpConflictException();
            if (timerControls.Count >= 8 || retiredTimerControls.Count + timerControls.Count >= 128) throw new InvalidOperationException("timer_control_busy");
            if (timerControls.ContainsKey(requestId) || retiredTimerControls.ContainsKey(requestId)) throw new McpConflictException();
            var peer = RequireMcpPeer(id, fingerprint);
            pending = new() { PeerId = id, Fingerprint = fingerprint, PublicKey = peer.PublicKey.ToArray(), Connection = online[id], Source = source,
                Action = action, OperationId = body["operation_id"]!.GetValue<string>(), Deadline = now + 15000,
                Cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellation, online[id].TimeCancellation) };
            timerControls.Add(requestId, pending);
        }
        try
        {
            var now = Now();
            var wire = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = TimeControlContract.RequestKind, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
            TelefonMessageContract.ValidateMessage(wire, now, false);
            pending.Cancellation.Token.ThrowIfCancellationRequested();
            await pending.Connection.SendPlainAsync(wire);
            var report = await pending.Completion.Task.WaitAsync(TimeSpan.FromSeconds(15), pending.Cancellation.Token);
            lock (gate)
            {
                pending.Cancellation.Token.ThrowIfCancellationRequested();
                if (Environment.TickCount64 >= pending.Deadline || TimeControlSource(id, fingerprint, pending.Action != "read") != pending.Source ||
                    online.GetValueOrDefault(id) != pending.Connection) throw new InvalidOperationException("timer_source_changed_after_dispatch");
                return new() { ["report"] = report.DeepClone(), ["source_revision"] = pending.Source, ["dispatch_started"] = true };
            }
        }
        finally
        {
            lock (gate)
            {
                timerControls.Remove(requestId); retiredTimerControls[requestId] = Math.Max(Environment.TickCount64, pending.Deadline) + 660000;
                pending.Cancellation.Dispose();
            }
        }
    }

    internal bool CancelTimeControl(string id, string fingerprint, string requestId)
    {
        lock (gate)
        {
            if (!timerControls.TryGetValue(requestId, out var pending) || pending.PeerId != id ||
                !TelefonCrypto.Fingerprint(pending.PublicKey).Equals(fingerprint, StringComparison.OrdinalIgnoreCase)) return false;
            pending.Cancellation.Cancel(); return true;
        }
    }

    internal Task ReceiveTimeControlReportAsync(TelefonConnection source, TelefonPeer peer, JsonObject message)
    {
        lock (gate)
        {
            try
            {
                TelefonMessageContract.ValidateMessage(message, Now(), true);
                if (message["kind"]!.GetValue<string>() != TimeControlContract.ReportKind || TelefonProtocolContract.Integer(message["expires_ms"]) <= Now()) return Task.CompletedTask;
                var report = message["body"]!.AsObject(); var id = report["request_id"]!.GetValue<string>();
                if (!timerControls.TryGetValue(id, out var pending) || pending.Cancellation.IsCancellationRequested || Environment.TickCount64 >= pending.Deadline ||
                    pending.PeerId != peer.Id || !pending.PublicKey.SequenceEqual(peer.PublicKey) || pending.Connection != source || online.GetValueOrDefault(peer.Id) != source ||
                    report["operation_id"]!.GetValue<string>() != pending.OperationId || TimeControlSource(peer.Id, pending.Fingerprint, pending.Action != "read") != pending.Source) return Task.CompletedTask;
                pending.Completion.TrySetResult(report.DeepClone().AsObject());
            }
            catch (Exception error) when (error is InvalidDataException or TelefonMessageException or InvalidOperationException or FormatException) { }
        }
        return Task.CompletedTask;
    }
}
