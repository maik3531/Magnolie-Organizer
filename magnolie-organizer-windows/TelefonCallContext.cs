using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    internal JsonObject CallControlSourceSnapshot()
    {
        if (disposed || cancellation.IsCancellationRequested || store.RestoreFenced || !freshCapabilities || !freshGrants ||
            transport is not ("wifi" or "bluetooth")) throw new InvalidOperationException("call_controls_not_fresh");
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.State == "paired" && value.PublicKey.SequenceEqual(peer.PublicKey));
        if (current is null || current.CapabilityRevision != Interlocked.Read(ref actorCapabilityRevision) ||
            current.GrantRevision != Interlocked.Read(ref actorGrantRevision)) throw new InvalidOperationException("call_source_changed");
        return new() { ["peer"] = current.Id, ["key"] = Convert.ToBase64String(current.PublicKey), ["connection"] = actorSourceEpoch,
            ["transport"] = transport, ["capabilities"] = current.Capabilities.DeepClone(), ["grants"] = current.Grants.DeepClone(),
            ["local_grants"] = store.LocalGrants() };
    }
}

internal sealed partial class TelefonCoordinator
{
    internal Action<TelefonConnection, TelefonPeer, string, JsonObject>? PrivateCallResultObserver { get; set; }
    private sealed record CallContextReceipt(TelefonConnection Connection, byte[] PublicKey, string BodyHash, long ReceivedMs);
    private readonly Dictionary<string, CallContextReceipt> callContextReceipts = new(StringComparer.Ordinal);
    private static string CallContextHash(JsonObject body) => Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(body))).ToLowerInvariant();

    internal void ObserveCallContext(TelefonConnection source, TelefonPeer peer, JsonObject body)
    {
        lock (gate)
        {
            // CurrentCall's durable fallback is not evidence for a new session.
            if (disposed || online.GetValueOrDefault(peer.Id) != source || !calls.TryGetValue(peer.Id, out var current) ||
                !JsonNode.DeepEquals(current, body)) return;
            foreach (var id in callContextReceipts.Where(value => online.GetValueOrDefault(value.Key) != value.Value.Connection).Select(value => value.Key).ToArray())
                callContextReceipts.Remove(id);
            if (!callContextReceipts.ContainsKey(peer.Id) && callContextReceipts.Count >= 128)
                callContextReceipts.Remove(callContextReceipts.MinBy(value => value.Value.ReceivedMs).Key);
            callContextReceipts[peer.Id] = new(source, peer.PublicKey.ToArray(), CallContextHash(body), Now());
        }
    }

    private JsonObject ExecuteMcpCallContext(JsonObject request)
    {
        try
        {
            TelefonProtocolContract.ExactObject(request, "action", "peerId", "fingerprint");
            return new() { ["ok"] = true, ["callContext"] = McpCallContext(McpText(request, "peerId", true), McpText(request, "fingerprint", true)) };
        }
        catch (InvalidDataException) { return new() { ["ok"] = false, ["code"] = "invalid_selection" }; }
        catch (Exception error) when (error is McpRequestException or McpConflictException or InvalidOperationException) { return new() { ["ok"] = false, ["code"] = "not_granted" }; }
    }

    internal JsonObject McpCallContext(string id, string fingerprint)
    {
        lock (gate)
        {
            if (disposed || !Enabled || store.RestoreFenced || !online.TryGetValue(id, out var connection)) throw new InvalidOperationException("call_source_unavailable");
            var peer = RequireMcpPeer(id, fingerprint); var authority = connection.CallControlSourceSnapshot();
            var local = authority["local_grants"]!.AsObject(); var remote = peer.Grants;
            bool Capability(string name, int version) => peer.Capabilities[name] is JsonObject value && value["available"]?.GetValue<bool>() == true &&
                value["versions"] is JsonArray versions && versions.Any(value => TelefonProtocolContract.Integer(value) == version);
            var permissions = new JsonObject();
            foreach (var name in new[] { "dial_request", "incoming_call_state", "answer_call", "end_call" })
                permissions[name] = Capability(name, name == "incoming_call_state" ? 2 : 1) && local[name]?.GetValue<bool>() == true && remote[name]?.GetValue<bool>() == true;
            JsonObject? observed = null;
            if (permissions["incoming_call_state"]!.GetValue<bool>() && callContextReceipts.TryGetValue(id, out var receipt) && receipt.Connection == connection &&
                receipt.PublicKey.SequenceEqual(peer.PublicKey) && calls.TryGetValue(id, out var current) && CallContextHash(current) == receipt.BodyHash)
                observed = new() { ["call_ref"] = current["call_ref"]!.DeepClone(),
                    ["revision"] = TelefonProtocolContract.Integer(current["revision"]).ToString(CultureInfo.InvariantCulture),
                    ["state"] = current["state"]!.DeepClone(), ["direction"] = current["direction"]!.DeepClone(),
                    ["phone_occurred_ms"] = current["occurred_ms"]!.DeepClone(), ["native_received_ms"] = receipt.ReceivedMs,
                    ["observation"] = "authenticated_session_event", ["phone_status_queried"] = false };
            authority["profile"] = identity.Id; authority["call"] = observed?.DeepClone();
            var revision = Convert.ToHexString(HMACSHA256.HashData(mcpRevisionKey, TelefonCrypto.Canonical(authority))).ToLowerInvariant();
            return new() { ["peer_id"] = peer.Id, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey), ["source_revision"] = revision,
                ["transport"] = authority["transport"]!.DeepClone(), ["permissions"] = permissions, ["call"] = observed,
                ["phone_status_queried"] = false, ["persisted"] = false };
        }
    }
}
