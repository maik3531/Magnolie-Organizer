using System.Collections.Generic;
using System.Reflection;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpDeviceStatusTests
{
    internal static async Task RunAsync()
    {
        foreach (var scenario in new[] { "basic", "identifiers", "own_off_basic", "own_off", "grant_off", "key_changed", "channel_changed", "cancel", "replay", "wrong_channel" })
            await ReadAsync(scenario);
    }
    private static async Task ReadAsync(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-owned-status-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            capabilities["device_status"]!["versions"] = new JsonArray(1, 2, 3, 4); capabilities["device_status"]!["available"] = true;
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var guiEvents = new List<string>();
            using var coordinator = new TelefonCoordinator(paths, (callback, _) => { guiEvents.Add(callback); return Task.CompletedTask; },
                dataStore: store, foregroundEnabled: true, localOnly: true);
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptMcpStatusRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var reject = typeof(TelefonCoordinator).GetMethod("RejectContactRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var stream = new MemoryStream(); using var lifetime = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            using var connection = new TelefonConnection(peer, stream, new byte[16], new byte[72], store, (_, _) => Task.FromResult<TelefonAck?>(null), lifetime.Token, "wifi",
                rejectContactRead: (source, sender, ack) => (bool)reject.Invoke(coordinator, [source, sender, ack])!,
                receiveStatusRead: (source, sender, message) => (TelefonAck?)accept.Invoke(coordinator, [source, sender, message]));
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            TestAssert.That(!connection.StatusReadReady(false), "Cached capabilities/grants authorized status access.");
            foreach (var flag in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
                typeof(TelefonConnection).GetField(flag, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(connection, true);
            var include = scenario is not ("basic" or "own_off_basic");
            if (scenario == "own_off_basic") store.SetPersonalSettings(peer.Id, ownDevice: false, remoteOwnDevice: false);
            var query = Guid.NewGuid().ToString("D"); var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            var read = coordinator.ReadDeviceStatusAsync(peer.Id, fingerprint, coordinator.McpStatus()["revision"]!.GetValue<string>(), query, include, lifetime.Token);
            var ordinary = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "resources", "telefon-control-contract.json")))!["device_status_v3"]!.DeepClone().AsObject();
            ordinary["request_id"] = query; ordinary["captured_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (include)
            {
                ordinary["version"] = 4;
                ordinary["identifiers"] = new JsonObject {
                    ["phone_number"] = new JsonObject { ["status"] = "permission_missing", ["value"] = "" },
                    ["serial"] = new JsonObject { ["status"] = "os_restricted", ["value"] = "" },
                    ["imei"] = new JsonObject { ["status"] = "available", ["value"] = "000000000000001" } };
            }
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            JsonObject Packet() => new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = "device_status.report",
                ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = ordinary.DeepClone() };
            if (scenario == "cancel")
            {
                TestAssert.That(coordinator.CancelDeviceStatus(peer.Id, fingerprint, query), "Pending native status read could not be cancelled.");
                try { await read; throw new InvalidOperationException("Cancelled status query succeeded."); } catch (OperationCanceledException) { }
                await connection.HandlePlainAsync(Packet());
            }
            else
            {
                if (scenario == "wrong_channel")
                {
                    using var otherStream = new MemoryStream(); using var other = new TelefonConnection(peer, otherStream, new byte[16], new byte[72], store,
                        (_, _) => Task.FromResult<TelefonAck?>(null), lifetime.Token, "wifi");
                    var ack = (TelefonAck)accept.Invoke(coordinator, [other, peer, Packet()])!;
                    TestAssert.That(ack.Status == "rejected" && !read.IsCompleted, "Wrong channel completed the scoped query.");
                }
                await connection.HandlePlainAsync(Packet()); var token = await read;
                if (scenario == "own_off") store.SetPersonalSettings(peer.Id, ownDevice: false);
                if (scenario == "grant_off") store.SavePeers([peer with { Grants = new JsonObject(peer.Grants.Select(item =>
                    KeyValuePair.Create(item.Key, item.Key == "device_status" ? JsonValue.Create(false) as JsonNode : item.Value?.DeepClone()))) }]);
                if (scenario == "key_changed") store.SavePeers([peer with { PublicKey = Enumerable.Repeat((byte)20, 32).ToArray() }]);
                if (scenario == "channel_changed") online.Remove(peer.Id);
                var result = coordinator.CurrentMcpDeviceStatus(token);
                if (scenario is "own_off" or "grant_off" or "key_changed" or "channel_changed")
                    TestAssert.That(result["ok"]!.GetValue<bool>() == false && !result.ToJsonString().Contains("000000000000001", StringComparison.Ordinal), "Revoked source/identifier permission leaked a queued result.");
                else
                {
                    var data = result["deviceStatus"]!.AsObject();
                    TestAssert.That(result["ok"]!.GetValue<bool>() && data["include_identifiers"]!.GetValue<bool>() == include &&
                        data["request_correlated"]!.GetValue<bool>() && !data["persisted"]!.GetValue<bool>(), "Scoped status result lost its real source/correlation flags.");
                    TestAssert.That(data["report"]!.AsObject().ContainsKey("identifiers") == include, "Default status read inherited GUI identifier permission.");
                    if (include) TestAssert.That(data["report"]!["identifiers"]!["imei"]!["value"]!.GetValue<string>() == "000000000000001", "Explicit transient identifier was lost.");
                    TestAssert.That(coordinator.CurrentMcpDeviceStatus(token)["ok"]!.GetValue<bool>() == false, "Sensitive result could be consumed twice.");
                }
                if (scenario == "replay") await connection.HandlePlainAsync(Packet());
            }
            TestAssert.That(guiEvents.Count == 0 && store.LoadStatus(peer.Id) is null, "Scoped/late status report reached the GUI or durable cache.");
            using var database = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = paths.TelefonDatabase }.ToString()); database.Open();
            foreach (var table in new[] { "inbox", "outbox" })
            {
                using var command = database.CreateCommand(); command.CommandText = "SELECT COUNT(*) FROM " + table;
                TestAssert.That(Convert.ToInt64(command.ExecuteScalar()) == 0, "Scoped status report entered durable " + table);
            }
            online.Clear();
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
