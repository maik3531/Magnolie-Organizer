using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class KdeConnectDirectBackend
{
    private readonly byte[] mcpControlKey = RandomNumberGenerator.GetBytes(32);
    private sealed class McpControlScope { internal volatile bool Active = true; }
    private sealed class McpControlConflict : Exception { }
    private readonly AsyncLocal<McpControlScope?> mcpControlEmission = new();
    private readonly SemaphoreSlim mcpControlOperations = new(1, 1);

    private Task McpServiceTask(Func<Task> body)
    {
        if (mcpControlEmission.Value is { Active: true } && !ExecutionContext.IsFlowSuppressed())
        { using (ExecutionContext.SuppressFlow()) return Task.Run(body); }
        return body();
    }

    private string McpPeerDigest() => McpDigest(new JsonObject { ["peers"] = new JsonArray(store.LoadPeers().OrderBy(peer => peer.Id, StringComparer.Ordinal)
        .Select(peer => (JsonNode)new JsonObject { ["id"] = peer.Id, ["name"] = peer.Name, ["fingerprint"] = peer.CertificatePin, ["paired"] = peer.Paired }).ToArray()) });

    private void CheckMcpControl(string? revision, string? id = null, string? fingerprint = null, bool requirePaired = true)
    {
        if (revision is not null && revision != McpStatus()["revision"]!.GetValue<string>()) throw new McpControlConflict();
        if (id is not null && !store.LoadPeers().Any(peer => peer.Id == id && (!requirePaired || peer.Paired) && peer.CertificatePin.Equals(fingerprint, StringComparison.OrdinalIgnoreCase))) throw new McpControlConflict();
    }

    private static string McpValue(JsonObject request, string key) => request[key]?.GetValue<string>() ?? "";

    internal async Task<JsonObject> McpActionAsync(JsonObject request, CancellationToken cancellation)
    {
        var action = McpValue(request, "action");
        if (action == "refresh") return await McpRefreshAsync(McpValue(request, "expectedRevision"), cancellation).ConfigureAwait(false);
        if (!await mcpControlOperations.WaitAsync(0, cancellation).ConfigureAwait(false)) return new() { ["ok"] = false, ["code"] = "native_busy" };
        var previous = mcpControlEmission.Value; var capture = new McpControlScope(); mcpControlEmission.Value = capture;
        try
        {
            var revision = McpValue(request, "expectedRevision");
            CheckMcpControl(revision);
            var persisted = false; var paired = false;
            if (action is "pairing_begin" or "pairing_complete" or "pairing_renew")
            {
                var snapshot = McpStatus();
                var id = McpValue(request, "candidateId");
                var candidate = snapshot["candidates"]!.AsArray().OfType<JsonObject>().SingleOrDefault(candidate => candidate["id"]!.GetValue<string>() == id);
                if (candidate is null || candidate["source_token"]!.GetValue<string>() != McpValue(request, "sourceToken") || !pending.IsEmpty) throw new McpControlConflict();
                var known = store.LoadPeers().Where(peer => peer.Paired).ToArray();
                if (action == "pairing_renew")
                {
                    if (known.Length != 1 || known[0].Id != McpValue(request, "replacementId") || !known[0].CertificatePin.Equals(McpValue(request, "replacementFingerprint"), StringComparison.OrdinalIgnoreCase) || known[0].Name != candidate["name"]!.GetValue<string>()) throw new McpControlConflict();
                }
                else if (known.Length != 0) throw new McpControlConflict();
                var peerControl = McpPeerDigest();
                void Guard(string stage, KdeConnectDiscovered selected)
                {
                    if (selected.Identity.DeviceId != id || selected.Address.ToString() != candidate["address"]!.GetValue<string>() || selected.Identity.TcpPort != candidate["port"]!.GetValue<int>() || McpPeerDigest() != peerControl) throw new McpControlConflict();
                    if (stage == "select")
                    {
                        CheckMcpControl(revision);
                        var current = McpStatus()["candidates"]!.AsArray().OfType<JsonObject>().SingleOrDefault(candidate => candidate["id"]!.GetValue<string>() == id);
                        if (current is null || current["source_token"]!.GetValue<string>() != McpValue(request, "sourceToken")) throw new McpControlConflict();
                    }
                    else if (!pending.IsEmpty) throw new McpControlConflict();
                }
                await BeginPairingCoreAsync(null, cancellation, id, Guard).ConfigureAwait(false);
                if (!pending.TryGetValue(id, out var created) || !created.McpOwned) return new() { ["ok"] = false, ["code"] = "verification_failed" };
                created.McpPeerControl = peerControl;
            }
            else if (action is "pairing_confirm" or "pairing_cancel")
            {
                var id = McpValue(request, "peerId"); var fingerprint = McpValue(request, "fingerprint"); var attempt = McpValue(request, "attemptId");
                var accept = false;
                if (action == "pairing_confirm" && (request["accept"] is not JsonValue flag || !flag.TryGetValue<bool>(out accept)))
                    return new() { ["ok"] = false, ["code"] = "invalid_selection" };
                PendingPairing? captured = null;
                void Guard(string stage, PendingPairing current)
                {
                    if (stage == "entry") CheckMcpControl(revision);
                    if (current.McpAttemptId != attempt || current.ExpiresAt <= DateTimeOffset.UtcNow || !string.Equals(McpConnectionPin(current.Connection), fingerprint, StringComparison.OrdinalIgnoreCase) ||
                        !pending.TryGetValue(id, out var actual) || !ReferenceEquals(actual, current) || current.McpPeerControl is not null && current.McpPeerControl != McpPeerDigest()) throw new McpControlConflict();
                    captured = current;
                }
                await ConfirmPairingCoreAsync(id, accept, cancellation, Guard).ConfigureAwait(false);
                var stored = store.LoadPeers().SingleOrDefault(peer => peer.Id == id && peer.Paired && peer.CertificatePin.Equals(fingerprint, StringComparison.OrdinalIgnoreCase));
                paired = accept && captured?.McpStoreCommitted == true && stored is not null; persisted = paired;
                if (accept ? !paired && (captured is null || !captured.LocalConfirmed || !pending.TryGetValue(id, out var remaining) || !ReferenceEquals(remaining, captured)) : pending.TryGetValue(id, out var rejected) && ReferenceEquals(rejected, captured))
                    return new() { ["ok"] = false, ["code"] = "verification_failed" };
            }
            else if (action == "remove")
            {
                var id = McpValue(request, "peerId");
                Remove(id, McpValue(request, "fingerprint"), revision);
                persisted = store.LoadPeers().All(peer => peer.Id != id);
                if (!persisted) return new() { ["ok"] = false, ["code"] = "verification_failed" };
            }
            else return new() { ["ok"] = false, ["code"] = "unsupported_feature" };
            cancellation.ThrowIfCancellationRequested();
            return new() { ["ok"] = true, ["action"] = action, ["status"] = McpStatus(), ["localVerified"] = true, ["persisted"] = persisted, ["pairedVerified"] = paired, ["deliveryConfirmed"] = false };
        }
        catch (McpControlConflict) { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (Exception) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
        finally { capture.Active = false; mcpControlEmission.Value = previous; mcpControlOperations.Release(); }
    }

    private string McpDigest(JsonObject value)
    {
        var bytes = Encoding.UTF8.GetBytes(value.ToJsonString());
        try { return Convert.ToHexString(HMACSHA256.HashData(mcpControlKey, bytes)).ToLowerInvariant(); }
        finally { Array.Clear(bytes); }
    }

    private static string? McpConnectionPin(Connection? connection)
    {
        try { return connection is null || connection.Closed ? null : KdeConnectProtocol.CertificatePin(connection.Certificate); }
        catch (Exception error) when (error is CryptographicException or ObjectDisposedException) { return null; }
    }

    internal JsonObject McpStatus()
    {
        lock (activeGate)
        {
            var now = DateTimeOffset.UtcNow;
            var known = store.LoadPeers().OrderBy(peer => peer.Id, StringComparer.Ordinal).ToArray();
            var peers = new JsonArray(); var peerControl = new JsonArray();
            foreach (var peer in known)
            {
                active.TryGetValue(peer.Id, out var connection);
                peers.Add(new JsonObject { ["id"] = peer.Id, ["name"] = peer.Name, ["fingerprint"] = peer.CertificatePin, ["paired"] = peer.Paired,
                    ["reachable"] = McpConnectionPin(connection) == peer.CertificatePin, ["type"] = connection?.Identity.DeviceType ?? "unknown" });
                peerControl.Add(new JsonObject { ["id"] = peer.Id, ["name"] = peer.Name, ["fingerprint"] = peer.CertificatePin, ["paired"] = peer.Paired });
            }
            var confirmed = known.Where(peer => peer.Paired).Select(peer => peer.Id).ToHashSet(StringComparer.Ordinal);
            var discoveries = new JsonArray();
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var candidate in candidates.Values.Where(candidate => now - candidate.SeenAt <= CandidateLifetime && !confirmed.Contains(candidate.Identity.DeviceId)).OrderBy(candidate => candidate.Identity.DeviceId, StringComparer.Ordinal))
            {
                staged.TryGetValue(candidate.Identity.DeviceId, out var connection);
                var fingerprint = McpConnectionPin(connection);
                var source = new JsonObject { ["id"] = candidate.Identity.DeviceId, ["address"] = candidate.Address.ToString(), ["port"] = candidate.Identity.TcpPort,
                    ["fingerprint"] = fingerprint, ["generation"] = connection?.Generation ?? 0 };
                discoveries.Add(new JsonObject { ["id"] = candidate.Identity.DeviceId, ["name"] = candidate.Identity.DeviceName, ["fingerprint"] = fingerprint,
                    ["source_token"] = McpDigest(source), ["reachable"] = fingerprint is not null, ["address"] = candidate.Address.ToString(), ["port"] = candidate.Identity.TcpPort });
                ids.Add(candidate.Identity.DeviceId);
            }
            foreach (var (id, connection) in staged.OrderBy(item => item.Key, StringComparer.Ordinal))
            {
                var fingerprint = McpConnectionPin(connection);
                if (confirmed.Contains(id) || ids.Contains(id) || fingerprint is null) continue;
                var source = new JsonObject { ["id"] = id, ["address"] = connection.Address.ToString(), ["port"] = connection.Port, ["fingerprint"] = fingerprint, ["generation"] = connection.Generation };
                discoveries.Add(new JsonObject { ["id"] = id, ["name"] = connection.Identity.DeviceName, ["fingerprint"] = fingerprint, ["source_token"] = McpDigest(source), ["reachable"] = true,
                    ["address"] = connection.Address.ToString(), ["port"] = connection.Port });
            }
            var pendingPublic = new JsonArray();
            foreach (var pairing in pending.Values.Where(pairing => pairing.ExpiresAt > now).OrderBy(pairing => pairing.Connection.Identity.DeviceId, StringComparer.Ordinal))
            {
                var fingerprint = McpConnectionPin(pairing.Connection);
                if (fingerprint is null) continue;
                pendingPublic.Add(new JsonObject { ["id"] = pairing.Connection.Identity.DeviceId, ["name"] = pairing.Connection.Identity.DeviceName,
                    ["fingerprint"] = fingerprint, ["attempt_id"] = pairing.McpAttemptId, ["code"] = pairing.Code, ["expires_ms"] = pairing.ExpiresAt.ToUnixTimeMilliseconds(),
                    ["local_confirmed"] = pairing.LocalConfirmed, ["remote_confirmed"] = pairing.RemoteConfirmed });
            }
            var localFingerprint = KdeConnectProtocol.CertificatePin(local.Certificate);
            var control = new JsonObject { ["integration"] = "direct", ["id"] = local.Id, ["fingerprint"] = localFingerprint,
                ["peers"] = peerControl, ["candidates"] = discoveries.DeepClone(), ["pending"] = pendingPublic.DeepClone() };
            return new JsonObject { ["revision"] = McpDigest(control), ["integration"] = "direct", ["running"] = !disposed && !lifetime.IsCancellationRequested,
                ["owned_listener"] = true, ["listening"] = !disposed && tcpListening && udp is not null, ["listen_port"] = ListenerPort,
                ["local_id"] = local.Id, ["local_fingerprint"] = localFingerprint,
                ["capabilities"] = new JsonObject { ["refresh"] = true, ["pairing"] = true, ["remove"] = true, ["receive_preferences"] = false },
                ["peers"] = peers, ["candidates"] = discoveries, ["pending"] = pendingPublic, ["error_present"] = !tcpListening || udp is null };
        }
    }

    internal async Task<JsonObject> McpRefreshAsync(string expectedRevision, CancellationToken cancellation)
    {
        if (!await mcpControlOperations.WaitAsync(0, cancellation).ConfigureAwait(false)) return new() { ["ok"] = false, ["code"] = "native_busy" };
        var previous = mcpControlEmission.Value; var capture = new McpControlScope(); mcpControlEmission.Value = capture;
        try
        {
            if (expectedRevision.Length > 0 && McpStatus()["revision"]!.GetValue<string>() != expectedRevision) return new() { ["ok"] = false, ["code"] = "conflict" };
            await DiscoverAsync(TimeSpan.FromSeconds(1), cancellation).ConfigureAwait(false);
            return new() { ["ok"] = true, ["action"] = "refresh", ["status"] = McpStatus(), ["localVerified"] = true, ["persisted"] = false, ["deliveryConfirmed"] = false };
        }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (Exception) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
        finally { capture.Active = false; mcpControlEmission.Value = previous; mcpControlOperations.Release(); }
    }
}
