using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed class StatusReadWait
    {
        internal required string PeerId, RequestId, MessageId;
        internal required byte[] PublicKey;
        internal required TelefonConnection Connection;
        internal required bool Include;
        internal required int Version;
        internal required long Deadline;
        internal required CancellationTokenSource Cancellation;
        internal readonly TaskCompletionSource<JsonObject> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }
    private sealed record StatusReadResult(string PeerId, byte[] PublicKey, TelefonConnection Connection, bool Include,
        int Version, JsonObject Report, long Received, long Expires, long Deadline);
    private readonly Dictionary<string, StatusReadWait> statusReads = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> retiredStatusReads = new(StringComparer.Ordinal);
    private readonly Dictionary<string, StatusReadResult> statusReadResults = new(StringComparer.Ordinal);
    private void PurgeStatusReads()
    {
        var now = Environment.TickCount64;
        foreach (var key in retiredStatusReads.Where(item => item.Value <= now).Select(item => item.Key).ToArray()) retiredStatusReads.Remove(key);
        foreach (var key in statusReadResults.Where(item => item.Value.Deadline <= now || item.Value.Expires <= Now()).Select(item => item.Key).ToArray()) statusReadResults.Remove(key);
    }
    internal async Task<string> ReadDeviceStatusAsync(string id, string fingerprint, string revision, string queryId,
        bool includeIdentifiers, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (!TelefonProtocolContract.IsUuidV4(queryId)) throw new InvalidDataException("invalid_status_request");
        StatusReadWait pending;
        lock (gate)
        {
            PurgeStatusReads(); CheckMcpRevision(revision);
            var peer = RequireMcpPeer(id, fingerprint);
            if (!Enabled || !online.TryGetValue(id, out var source) || !source.StatusReadReady(includeIdentifiers)) throw new InvalidOperationException("device_status_not_granted");
            if (statusReads.Count >= 8 || statusReads.Count + retiredStatusReads.Count >= 128 || statusReadResults.Count >= 8)
                throw new InvalidOperationException("device_status_busy");
            if (statusReads.ContainsKey(queryId) || retiredStatusReads.ContainsKey(queryId)) throw new McpConflictException();
            var body = DeviceStatusRequest(queryId, peer.Capabilities["device_status"]?["versions"] as JsonArray, includeIdentifiers);
            pending = new StatusReadWait { PeerId = id, PublicKey = peer.PublicKey.ToArray(), Connection = source,
                RequestId = queryId, MessageId = Guid.NewGuid().ToString("D"), Include = includeIdentifiers,
                Version = body["version"]?.GetValue<int>() ?? 1, Deadline = Environment.TickCount64 + 10000,
                Cancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellation) };
            statusReads.Add(queryId, pending);
        }
        try
        {
            await RequestDeviceStatusAsync(id, queryId, includeIdentifiers, ephemeral: true, messageId: pending.MessageId);
            var result = await pending.Completion.Task.WaitAsync(TimeSpan.FromSeconds(10), pending.Cancellation.Token);
            lock (gate)
            {
                pending.Cancellation.Token.ThrowIfCancellationRequested();
                if (!online.TryGetValue(id, out var current) || !ReferenceEquals(current, pending.Connection) ||
                    !current.StatusReadReady(includeIdentifiers) || Environment.TickCount64 >= pending.Deadline ||
                    !Peers.Any(peer => peer.Id == id && peer.PublicKey.SequenceEqual(pending.PublicKey))) throw new InvalidOperationException("device_status_source_changed");
                var expires = result["expires_ms"]!.GetValue<long>();
                statusReadResults[queryId] = new(id, pending.PublicKey.ToArray(), pending.Connection, includeIdentifiers, pending.Version,
                    result["report"]!.DeepClone().AsObject(), result["received_ms"]!.GetValue<long>(), expires,
                    Environment.TickCount64 + Math.Max(0, Math.Min(60000, expires - Now())));
            }
            return queryId;
        }
        finally
        {
            lock (gate)
            {
                statusReads.Remove(queryId);
                // Request skew + normal report lifetime + report skew. A late
                // scoped reply must never fall into the ordinary GUI/cache path.
                retiredStatusReads[queryId] = Math.Max(Environment.TickCount64, pending.Deadline) + 15 * 60 * 1000;
                pending.Cancellation.Dispose();
            }
        }
    }
    private bool RejectMcpStatusRead(TelefonConnection source, TelefonPeer peer, TelefonAck ack)
    {
        lock (gate)
        {
            var pending = statusReads.Values.FirstOrDefault(item => item.MessageId == ack.MessageId && item.PeerId == peer.Id);
            if (pending is null || ack.Status != "rejected" || !pending.PublicKey.SequenceEqual(peer.PublicKey) ||
                !ReferenceEquals(source, pending.Connection) || !online.TryGetValue(peer.Id, out var current) || !ReferenceEquals(current, source) ||
                pending.Cancellation.IsCancellationRequested || Environment.TickCount64 >= pending.Deadline) return false;
            return pending.Completion.TrySetException(new IOException("device_status_" + ack.Error));
        }
    }
    private TelefonAck? AcceptMcpStatusRead(TelefonConnection source, TelefonPeer peer, JsonObject message)
    {
        if (message["body"] is not JsonObject body || body["request_id"] is not JsonValue value || !value.TryGetValue<string>(out var query)) return null;
        lock (gate)
        {
            PurgeStatusReads();
            statusReads.TryGetValue(query, out var pending);
            if (pending is null && !retiredStatusReads.ContainsKey(query)) return null;
            var messageId = message["message_id"]?.GetValue<string>() ?? "";
            try
            {
                TelefonMessageContract.ValidateMessage(message, Now(), true);
                TelefonDeviceStatusContract.ValidateReport(body);
                if (pending is null) return new(messageId, "rejected", "expired");
                if (pending.PeerId != peer.Id || !pending.PublicKey.SequenceEqual(peer.PublicKey) || !ReferenceEquals(source, pending.Connection) ||
                    !online.TryGetValue(peer.Id, out var current) || !ReferenceEquals(source, current) || !source.StatusReadReady(pending.Include))
                    return new(messageId, "rejected", "not_granted");
                if (pending.Completion.Task.IsCompleted || pending.Cancellation.IsCancellationRequested || Environment.TickCount64 >= pending.Deadline ||
                    Now() >= TelefonProtocolContract.Integer(message["expires_ms"])) return new(messageId, "rejected", "expired");
                var ttl = TelefonProtocolContract.Integer(message["expires_ms"]) - TelefonProtocolContract.Integer(message["created_ms"]);
                var version = body["version"]?.GetValue<int>() ?? (body.ContainsKey("app_version") ? 3 : body.ContainsKey("sdk_int") ? 2 : 1);
                if (ttl > (pending.Include ? 60000 : 300000) || version != pending.Version || !pending.Include && body.ContainsKey("identifiers"))
                    return new(messageId, "rejected", "invalid_schema");
                var now = Now();
                pending.Completion.TrySetResult(new JsonObject { ["report"] = body.DeepClone(), ["received_ms"] = now,
                    ["expires_ms"] = Math.Min(TelefonProtocolContract.Integer(message["expires_ms"]), now + 60000) });
                return new(messageId, "accepted", "none");
            }
            catch (TelefonMessageException error) { return new(error.MessageId, "rejected", error.Error); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException or FormatException)
            { return new(messageId, "rejected", "invalid_schema"); }
        }
    }
    internal bool CancelDeviceStatus(string id, string fingerprint, string queryId)
    {
        lock (gate)
        {
            PurgeStatusReads();
            var cancelled = false;
            if (statusReads.TryGetValue(queryId, out var pending) && pending.PeerId == id && TelefonCrypto.Fingerprint(pending.PublicKey).Equals(fingerprint, StringComparison.OrdinalIgnoreCase))
            { pending.Cancellation.Cancel(); cancelled = true; }
            if (statusReadResults.TryGetValue(queryId, out var result) && result.PeerId == id && TelefonCrypto.Fingerprint(result.PublicKey).Equals(fingerprint, StringComparison.OrdinalIgnoreCase))
            { statusReadResults.Remove(queryId); cancelled = true; }
            return cancelled;
        }
    }
    internal JsonObject CurrentMcpDeviceStatus(string queryId)
    {
        lock (gate)
        {
            PurgeStatusReads();
            if (!statusReadResults.Remove(queryId, out var result) || !online.TryGetValue(result.PeerId, out var current) ||
                !ReferenceEquals(current, result.Connection) || !current.StatusReadReady(result.Include) ||
                !Peers.Any(peer => peer.Id == result.PeerId && peer.PublicKey.SequenceEqual(result.PublicKey)))
                return new() { ["ok"] = false, ["code"] = "source_changed" };
            return new() { ["ok"] = true, ["deviceStatus"] = new JsonObject { ["peer_id"] = result.PeerId,
                ["fingerprint"] = TelefonCrypto.Fingerprint(result.PublicKey), ["transport"] = "wifi", ["protocol_version"] = result.Version,
                ["received_ms"] = result.Received, ["expires_ms"] = result.Expires, ["include_identifiers"] = result.Include,
                ["report"] = result.Report.DeepClone(), ["source_verified"] = true, ["request_correlated"] = true, ["persisted"] = false } };
        }
    }
    private async Task<JsonObject> ExecuteMcpStatusAsync(JsonObject request, CancellationToken cancellation)
    {
        try
        {
            var action = McpText(request, "action", true); var id = McpText(request, "peerId", true);
            var fingerprint = McpText(request, "fingerprint", true); var query = McpText(request, "queryId", true);
            if (!TelefonProtocolContract.IsUuidV4(query)) return new() { ["ok"] = false, ["code"] = "invalid_selection" };
            if (action == "device_status_cancel") return new() { ["ok"] = true, ["action"] = action,
                ["cancelled"] = CancelDeviceStatus(id, fingerprint, query), ["persisted"] = false };
            var include = request["includeIdentifiers"] is not null && McpFlag(request, "includeIdentifiers");
            var token = await ReadDeviceStatusAsync(id, fingerprint, McpText(request, "expectedRevision", true), query, include, cancellation);
            return new() { ["ok"] = true, ["action"] = action, ["deviceStatusToken"] = token, ["persisted"] = false };
        }
        catch (McpConflictException) { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (McpRequestException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (TimeoutException) { return new() { ["ok"] = false, ["code"] = "native_timeout" }; }
        catch (InvalidOperationException error) { return new() { ["ok"] = false, ["code"] = error.Message == "device_status_busy" ? "native_busy" : "not_granted" }; }
        catch (InvalidDataException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (IOException) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
    }
}

internal sealed partial class TelefonConnection
{
    private readonly Func<TelefonConnection, TelefonPeer, JsonObject, TelefonAck?>? receiveStatusRead;
    internal bool StatusReadReady(bool includeIdentifiers)
    {
        if (disposed || transport != "wifi" || cancellation.IsCancellationRequested || store.RestoreFenced || !freshCapabilities || !freshGrants) return false;
        var peers = store.LoadPeers();
        var current = peers.SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
        if (peers.Count != 1 || current is null || current.State != "paired" || current.Grants["device_status"]?.GetValue<bool>() != true ||
            !TelefonCoordinator.RemoteCapability(current, "device_status") || current.Capabilities["device_status"]?["versions"] is not JsonArray versions ||
            !versions.Any(value => TelefonProtocolContract.Integer(value) == 1)) return false;
        return !includeIdentifiers || freshOwnSettings && store.IdentifiersAllowed(current);
    }
    private async Task<bool> HandleMcpStatusReadAsync(JsonObject message)
    {
        if (message["kind"]?.GetValue<string>() != "device_status.report") return false;
        var ack = receiveStatusRead?.Invoke(this, peer, message);
        if (ack is null) return false;
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
        return true;
    }
}
