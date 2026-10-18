using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private readonly byte[] mcpRevisionKey = RandomNumberGenerator.GetBytes(32);
    private sealed class McpConflictException : Exception { }
    private sealed class McpRequestException : Exception { }
    private sealed class McpEmission { internal volatile bool Active = true; }
    private readonly AsyncLocal<McpEmission?> mcpEmission = new();
    private readonly SemaphoreSlim mcpOperations = new(1, 1);

    private Task McpServiceTask(Func<Task> body)
    {
        if (mcpEmission.Value is { Active: true } && !ExecutionContext.IsFlowSuppressed())
        { using (ExecutionContext.SuppressFlow()) return Task.Run(body); }
        return Task.Run(body);
    }

    private void CheckMcpRevision(string? expected)
    {
        if (expected is not null && expected != McpStatus()["revision"]!.GetValue<string>()) throw new McpConflictException();
    }

    private TelefonPeer RequireMcpPeer(string id, string fingerprint, bool requirePaired = true)
    {
        var peer = store.LoadPeers().FirstOrDefault(peer => peer.Id == id && (!requirePaired || peer.State == "paired"));
        if (peer is null || !TelefonCrypto.Fingerprint(peer.PublicKey).Equals(fingerprint, StringComparison.OrdinalIgnoreCase)) throw new McpConflictException();
        return peer;
    }

    internal void AssertMcpTarget(string id, string fingerprint, string? revision = null)
    { lock (gate) { CheckMcpRevision(revision); RequireMcpPeer(id, fingerprint, requirePaired: false); } }

    internal async Task SetBluetoothPreferenceAsync(string id, bool enabled, string address, string? expectedFingerprint = null, string? expectedRevision = null)
    {
        if (enabled && !TelefonBluetoothSupport.Available) throw new NotSupportedException();
        address = address.Trim().ToUpperInvariant();
        lock (gate)
        {
            CheckMcpRevision(expectedRevision);
            if (expectedFingerprint is not null) RequireMcpPeer(id, expectedFingerprint);
            else if (Peers.All(peer => peer.Id != id)) throw new InvalidOperationException(T("The phone is not paired."));
            store.SetBluetoothPreference(id, enabled, address);
        }
        await ReportStatusAsync();
    }

    private static string[] McpEditableGrants() => TelefonProtocolContract.GrantNames.Where(name => !TelefonProtocolContract.IsDesktopGranted(name)).Order(StringComparer.Ordinal).ToArray();
    private static string McpText(JsonObject request, string key, bool required = false)
    {
        if (request[key] is null && !required) return "";
        if (request[key] is JsonValue value && value.TryGetValue<string>(out var text) && text.Length <= 512 && (!required || text.Length > 0)) return text;
        throw new McpRequestException();
    }
    private static bool McpFlag(JsonObject request, string key) => request[key] is JsonValue value && value.TryGetValue<bool>(out var flag) ? flag : throw new McpRequestException();

    internal async Task<JsonObject> ExecuteMcpAsync(JsonObject request, CancellationToken cancellation,
        Func<string, string, string, Task>? removeWithRuntime = null)
    {
        if (request["action"]?.GetValue<string>() is "device_status_query" or "device_status_cancel") return await ExecuteMcpStatusAsync(request, cancellation);
        if (!await mcpOperations.WaitAsync(0, cancellation).ConfigureAwait(false)) return new() { ["ok"] = false, ["code"] = "native_busy" };
        var previous = mcpEmission.Value; var capture = new McpEmission(); mcpEmission.Value = capture;
        try
        {
            var action = McpText(request, "action", true); var revision = McpText(request, "expectedRevision", true);
            var id = McpText(request, "peerId"); var fingerprint = McpText(request, "fingerprint");
            var enabled = (action is "settings" or "grant" or "bluetooth") && McpFlag(request, "enabled");
            var name = McpText(request, "name"); var address = McpText(request, "address").Trim().ToUpperInvariant();
            var accept = action == "pairing_confirm" && McpFlag(request, "accept");
            Func<Task> operation;
            PairingConfirmation? confirmation = null;
            lock (gate)
            {
                if (store.RestoreFenced) return new() { ["ok"] = false, ["code"] = "native_busy" };
                CheckMcpRevision(revision);
                if (action is "remove" or "grant" or "bluetooth") RequireMcpPeer(id, fingerprint, requirePaired: action != "remove");
                if (action == "grant" && !McpEditableGrants().Contains(name, StringComparer.Ordinal)) return new() { ["ok"] = false, ["code"] = "unsupported_feature" };
                if (action == "pairing_begin" && (!Enabled || !IsRunning)) throw new McpConflictException();
                if (action is "pairing_confirm" or "pairing_cancel")
                {
                    var attempt = McpText(request, "attemptId", true);
                    if (!confirmations.TryGetValue(id, out confirmation) || confirmation.AttemptId != attempt || confirmation.Completion.Task.IsCompleted || confirmation.Deadline <= Environment.TickCount64 ||
                        !confirmation.Public["fingerprint"]!.GetValue<string>().Equals(fingerprint, StringComparison.OrdinalIgnoreCase)) throw new McpConflictException();
                }
                operation = action switch
                {
                    "settings" => () => SwitchAsync(enabled, revision),
                    "pairing_begin" => () => StartPairingAsync(revision),
                    "pairing_confirm" or "pairing_cancel" => () =>
                    {
                        lock (gate)
                        {
                            CheckMcpRevision(revision);
                            if (!confirmations.TryGetValue(id, out var current) || !ReferenceEquals(current, confirmation)) throw new McpConflictException();
                            ConfirmPairing(id, action == "pairing_confirm" && accept);
                        }
                        return Task.CompletedTask;
                    },
                    "remove" => () => removeWithRuntime is null ? RemoveAsync(id, fingerprint, revision) : removeWithRuntime(id, fingerprint, revision),
                    "grant" => () => SetGrantAsync(id, name, enabled, fingerprint, revision),
                    "bluetooth" => () => SetBluetoothPreferenceAsync(id, enabled, address, fingerprint, revision),
                    _ => throw new McpRequestException()
                };
            }
            await operation().ConfigureAwait(false);
            cancellation.ThrowIfCancellationRequested();
            bool verified, persisted;
            lock (gate)
            {
                persisted = action switch
                {
                    "settings" => store.StoredEnabledMatches(enabled),
                    "remove" => store.LoadPeers().All(peer => peer.Id != id),
                    "grant" => store.StoredGrantMatches(name, enabled),
                    "bluetooth" => store.StoredBluetoothMatches(id, enabled, address),
                    _ => false
                };
                if (action is "grant" or "bluetooth") RequireMcpPeer(id, fingerprint);
                verified = action switch
                {
                    "settings" => persisted && Enabled == enabled && IsRunning == enabled,
                    "pairing_begin" => McpStatus()["pairing_open"]!.GetValue<bool>(),
                    "pairing_confirm" or "pairing_cancel" => confirmation is not null && confirmation.Completion.Task.IsCompletedSuccessfully && confirmation.Completion.Task.Result == (action == "pairing_confirm" && accept),
                    _ => persisted
                };
            }
            if (!verified) return new() { ["ok"] = false, ["code"] = "verification_failed" };
            return new() { ["ok"] = true, ["status"] = McpStatus(), ["action"] = action, ["localVerified"] = true, ["persisted"] = persisted, ["deliveryConfirmed"] = false };
        }
        catch (McpConflictException) { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (McpRequestException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (NotSupportedException) { return new() { ["ok"] = false, ["code"] = "unsupported_feature" }; }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (InvalidOperationException error) when (error.Message == "binding_conflict") { return new() { ["ok"] = false, ["code"] = "conflict" }; }
        catch (Exception) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
        finally { capture.Active = false; mcpEmission.Value = previous; mcpOperations.Release(); }
    }

    private static JsonObject McpGrants(JsonObject value)
    {
        var result = new JsonObject();
        foreach (var (key, raw) in value.OrderBy(item => item.Key, StringComparer.Ordinal))
            if (key.Length <= 80 && raw is JsonValue scalar && scalar.TryGetValue<bool>(out var enabled)) result[key] = enabled;
        return result;
    }

    private static JsonObject McpCapabilities(JsonObject value)
    {
        var result = new JsonObject();
        foreach (var (key, raw) in value.OrderBy(item => item.Key, StringComparer.Ordinal))
        {
            if (key.Length > 80 || raw is not JsonObject item) continue;
            result[key] = new JsonObject { ["available"] = item["available"] is JsonValue flag && flag.TryGetValue<bool>(out var available) && available,
                ["versions"] = new JsonArray((item["versions"] as JsonArray ?? []).OfType<JsonValue>()
                    .Where(version => version.TryGetValue<int>(out var number) && number is >= 0 and <= 1000).Take(32).Select(version => version.DeepClone()).ToArray()) };
        }
        return result;
    }

    private static JsonObject McpBluetoothStatus()
    {
        var reason = TelefonBluetoothSupport.Reason;
        if (reason.Length > 80 || !System.Text.RegularExpressions.Regex.IsMatch(reason, "^[a-z0-9_]+$")) reason = "unavailable";
        return new() { ["available"] = TelefonBluetoothSupport.Available, ["reason"] = reason, ["paired_devices_supported"] = false, ["devices"] = new JsonArray() };
    }

    internal JsonObject McpStatus()
    {
        lock (gate)
        {
            var peers = store.LoadPeers().OrderBy(peer => peer.Id, StringComparer.Ordinal).ToArray();
            var publicPeers = new JsonArray(); var controls = new JsonArray();
            var grants = McpGrants(store.LocalGrants());
            foreach (var peer in peers)
            {
                var address = store.BluetoothAddress(peer.Id);
                publicPeers.Add(new JsonObject { ["id"] = peer.Id, ["name"] = peer.Name, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey), ["state"] = peer.State,
                    ["online"] = online.ContainsKey(peer.Id), ["transport"] = OnlineTransport(peer.Id), ["bluetooth_enabled"] = address.Length > 0, ["bluetooth_address"] = address,
                    ["local_grants"] = grants.DeepClone(), ["remote_grants"] = McpGrants(peer.Grants), ["remote_capabilities"] = McpCapabilities(peer.Capabilities) });
                controls.Add(new JsonObject { ["id"] = peer.Id, ["key"] = Convert.ToBase64String(peer.PublicKey), ["state"] = peer.State, ["bluetooth"] = address,
                    ["remote_grants"] = peer.Grants.DeepClone(), ["remote_grant_revision"] = peer.GrantRevision, ["remote_capabilities"] = peer.Capabilities.DeepClone(), ["remote_capability_revision"] = peer.CapabilityRevision });
            }
            var pending = new JsonArray(confirmations.Values.Where(item => !item.Completion.Task.IsCompleted && item.Deadline > Environment.TickCount64)
                .OrderBy(item => item.AttemptId, StringComparer.Ordinal).Select(item =>
                {
                    var value = item.Public.DeepClone().AsObject(); value["decision_pending"] = true; return (JsonNode)value;
                }).ToArray());
            var pairingOpen = pairingToken is not null && pairingUntil > DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var control = new JsonObject { ["id"] = identity.Id, ["key"] = Convert.ToBase64String(identity.PublicKey), ["enabled"] = Enabled,
                ["stored_enabled"] = store.Enabled, ["peers"] = controls, ["local_grants"] = grants, ["pairing"] = pairingOpen,
                ["pairing_token"] = pairingToken is null ? "" : Convert.ToBase64String(pairingToken), ["pending"] = pending.DeepClone() };
            var bytes = Encoding.UTF8.GetBytes(control.ToJsonString());
            string revision;
            try { revision = Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, bytes)).ToLowerInvariant(); }
            finally { Array.Clear(bytes); }
            return new JsonObject { ["revision"] = revision, ["available"] = true, ["enabled"] = Enabled, ["listening"] = IsRunning,
                ["id"] = identity.Id, ["name"] = identity.Name, ["fingerprint"] = TelefonCrypto.Fingerprint(identity.PublicKey), ["port"] = Port,
                ["pairing_open"] = pairingOpen, ["pending_pairings"] = pending, ["binding_conflict"] = peers.Length > 1, ["error_present"] = error.Length > 0,
                ["capabilities"] = McpCapabilities(TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject()),
                ["editable_grants"] = new JsonArray(McpEditableGrants().Select(name => (JsonNode?)JsonValue.Create(name)).ToArray()), ["bluetooth"] = McpBluetoothStatus(), ["peers"] = publicPeers };
        }
    }
}
