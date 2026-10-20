using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpCallContextTests
{
    private static FieldInfo Field(Type type, string name) => type.GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!;
    internal static async Task RunAsync()
    {
        foreach (var scenario in new[] { "event", "retained", "reconnect", "offline", "key", "fingerprint", "controls", "local_grant", "remote_grant" }) await Run(scenario);
    }
    private static async Task Run(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-call-context-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, new byte[32]);
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            var grants = TelefonProtocolContract.DesktopGrants();
            foreach (var name in new[] { "incoming_call_state", "incoming_call_number", "answer_call", "end_call" }) { grants[name] = true; store.SetLocalGrant(name, true); }
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned call phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: grants);
            store.SavePeers([peer]);
            var events = new List<string>();
            using var host = new TelefonCoordinator(paths, (name, _) => { events.Add(name); return Task.CompletedTask; }, dataStore: store, foregroundEnabled: true, localOnly: true);
            using var wire = new MemoryStream();
            var online = (IDictionary<string, TelefonConnection>)Field(typeof(TelefonCoordinator), "online").GetValue(host)!;
            var calls = (IDictionary<string, JsonObject>)Field(typeof(TelefonCoordinator), "calls").GetValue(host)!;
            var receive = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            TelefonConnection Connect()
            {
                var result = new TelefonConnection(peer, wire, new byte[16], new byte[72], store,
                    (source, message) => (Task<TelefonAck?>)receive.Invoke(host, [source, message, "wifi"])!, default, "wifi") { CallContextObserved = host.ObserveCallContext };
                Field(typeof(TelefonConnection), "freshCapabilities").SetValue(result, true);
                Field(typeof(TelefonConnection), "freshGrants").SetValue(result, true);
                Field(typeof(TelefonConnection), "actorCapabilityRevision").SetValue(result, 1L);
                Field(typeof(TelefonConnection), "actorGrantRevision").SetValue(result, 1L);
                online[peer.Id] = result; return result;
            }
            using var connection = Connect();
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var body = new JsonObject { ["call_ref"] = Guid.NewGuid().ToString("D"), ["revision"] = 9007199254740993L, ["state"] = "ringing", ["direction"] = "incoming",
                ["number"] = "+49301234567", ["number_status"] = "available", ["started_ms"] = now, ["offhook_ms"] = 0L, ["ended_ms"] = 0L,
                ["occurred_ms"] = now, ["spam_status"] = "unknown", ["control_origin"] = "phone", ["battery_percent"] = -1, ["battery_captured_ms"] = 0L };
            JsonObject Packet(JsonObject value) => new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = "incoming_call_state.event", ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = value.DeepClone() };
            JsonObject Request(byte[]? key = null) => new() { ["action"] = "call_context_read", ["peerId"] = peer.Id, ["fingerprint"] = TelefonCrypto.Fingerprint(key ?? peer.PublicKey) };
            var before = await host.ExecuteMcpAsync(Request(), default);
            TestAssert.That(before["ok"]!.GetValue<bool>() && before["callContext"]!["call"] is null, "Cold call context adopted a retained record.");
            if (scenario == "retained") calls[peer.Id] = body.DeepClone().AsObject();
            else await connection.HandlePlainAsync(Packet(body));
            TelefonConnection? replacement = null;
            try
            {
                if (scenario == "reconnect") { replacement = Connect(); var late = body.DeepClone().AsObject(); late["revision"] = 9007199254740994L; await connection.HandlePlainAsync(Packet(late)); }
                if (scenario == "offline") online.Remove(peer.Id);
                var expectedKey = peer.PublicKey;
                if (scenario == "key") { expectedKey = Enumerable.Repeat((byte)113, 32).ToArray(); store.SavePeers([peer with { PublicKey = expectedKey }]); }
                if (scenario == "fingerprint") expectedKey = Enumerable.Repeat((byte)114, 32).ToArray();
                if (scenario == "controls") Field(typeof(TelefonConnection), "freshCapabilities").SetValue(connection, false);
                if (scenario == "local_grant") store.SetLocalGrant("incoming_call_state", false);
                if (scenario == "remote_grant") { var changed = grants.DeepClone().AsObject(); changed["incoming_call_state"] = false; store.SavePeers([peer with { GrantRevision = 2, StoredGrants = changed }]); }
                events.Clear(); var length = wire.Length;
                var result = await host.ExecuteMcpAsync(Request(expectedKey), default);
                if (scenario is "offline" or "key" or "fingerprint" or "controls" or "remote_grant")
                    TestAssert.That(result["ok"]!.GetValue<bool>() == false && result["code"]!.GetValue<string>() == "not_granted", "Changed authority leaked call data: " + scenario);
                else
                {
                    TestAssert.That(result["ok"]!.GetValue<bool>(), result.ToJsonString()); var context = result["callContext"]!.AsObject();
                    TestAssert.That(!context.ToJsonString().Contains("+49301234567", StringComparison.Ordinal) && context["persisted"]!.GetValue<bool>() == false &&
                        context["phone_status_queried"]!.GetValue<bool>() == false, "Call context leaked a number or claimed a phone query/save.");
                    if (scenario == "event") TestAssert.That(context["call"]?["revision"]?.GetValue<string>() == "9007199254740993" &&
                        context["call"]?["observation"]?.GetValue<string>() == "authenticated_session_event", "Accepted event lost native provenance or integer precision.");
                    else TestAssert.That(context["call"] is null, "Retained or reconnected call was mislabeled as current: " + scenario);
                }
                TestAssert.That(events.Count == 0 && wire.Length == length, "Reading call authority sent network traffic or GUI events.");
            }
            finally { replacement?.Dispose(); }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
