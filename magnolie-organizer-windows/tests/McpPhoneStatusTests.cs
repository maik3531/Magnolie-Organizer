using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpPhoneStatusTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-mcp-phone-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)7, 32).ToArray());
            store.LoadOrCreateIdentity(); store.Enabled = false;
            var peer = new TelefonPeer("11111111-1111-4111-8111-111111111111", "Owned phone", TelefonCrypto.GenerateX25519().Public);
            store.SavePeers([peer]);
            store.SaveStatus(peer.Id, new JsonObject { ["private"] = "owned-private-cached-status" });
            using var service = new TelefonCoordinator(paths, (_, _) => throw new InvalidOperationException("MCP status emitted a GUI event."), dataStore: store, localOnly: true);
            var initial = service.McpStatus();
            TestAssert.That(initial["revision"]!.GetValue<string>() == service.McpStatus()["revision"]!.GetValue<string>() &&
                !initial["listening"]!.GetValue<bool>() && !initial["enabled"]!.GetValue<bool>(), "Native phone status started a listener or changed on a stable read.");
            TestAssert.That(!initial.ToJsonString().Contains("owned-private", StringComparison.Ordinal) && !initial.ToJsonString().Contains("pairing_token", StringComparison.Ordinal), "Public phone status exposed cached content or pairing tokens.");
            TestAssert.That(initial["peers"]![0]!["id"]!.GetValue<string>() == peer.Id, "Native phone peer inventory was not read from the real store.");
            store.SavePeers([peer with { LastSeenMs = 123456 }]);
            TestAssert.That(service.McpStatus()["revision"]!.GetValue<string>() == initial["revision"]!.GetValue<string>(), "A volatile peer timestamp changed the control revision.");
            store.SetLocalGrant("selected_notifications_readonly", true);
            var changed = service.McpStatus();
            TestAssert.That(changed["revision"]!.GetValue<string>() != initial["revision"]!.GetValue<string>() && changed["peers"]![0]!["local_grants"]!["selected_notifications_readonly"]!.GetValue<bool>(), "Actual local grant changes were absent from the public phone snapshot/revision.");
            await ActionsAsync(Path.Combine(root, "actions"));
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task ActionsAsync(string root)
    {
        var paths = new WindowsPaths(root);
        var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)8, 32).ToArray());
        store.LoadOrCreateIdentity(); store.Enabled = false;
        var peer = new TelefonPeer("22222222-2222-4222-8222-222222222222", "Owned actions phone", TelefonCrypto.GenerateX25519().Public);
        store.SavePeers([peer]);
        var emitted = new System.Collections.Concurrent.ConcurrentQueue<string>(); var kdeReads = 0;
        using var service = new TelefonCoordinator(paths, (callback, _) => { emitted.Enqueue(callback); return Task.CompletedTask; },
            () => { kdeReads++; return Task.FromResult<object>(new { available = false }); }, dataStore: store, localOnly: true);
        async Task<JsonObject> Action(string action, JsonObject? extra = null)
        {
            var state = service.McpStatus();
            var request = new JsonObject { ["action"] = action, ["expectedRevision"] = state["revision"]!.GetValue<string>(), ["peerId"] = peer.Id, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey) };
            if (extra is not null) foreach (var (key, value) in extra) request[key] = value?.DeepClone();
            return await service.ExecuteMcpAsync(request, default);
        }
        var initial = service.McpStatus()["revision"]!.GetValue<string>();
        var disabled = await Action("settings", new() { ["enabled"] = false });
        TestAssert.That(disabled["ok"]!.GetValue<bool>() && disabled["persisted"]!.GetValue<bool>() && store.StoredEnabledMatches(false), "Native disabled preference was not committed/read back.");
        var granted = await Action("grant", new() { ["name"] = "selected_notifications_readonly", ["enabled"] = true });
        TestAssert.That(granted["ok"]!.GetValue<bool>() && granted["persisted"]!.GetValue<bool>() && !granted["deliveryConfirmed"]!.GetValue<bool>() && store.StoredGrantMatches("selected_notifications_readonly", true), "Native permission write was not separated from delivery.");
        var wrong = await Action("grant", new() { ["name"] = "selected_notifications_readonly", ["enabled"] = false, ["fingerprint"] = "wrong" });
        TestAssert.That(!wrong["ok"]!.GetValue<bool>() && wrong["code"]!.GetValue<string>() == "conflict" && store.StoredGrantMatches("selected_notifications_readonly", true), "Wrong phone fingerprint changed a local grant.");
        var stale = await Action("remove", new() { ["expectedRevision"] = initial });
        TestAssert.That(!stale["ok"]!.GetValue<bool>() && stale["code"]!.GetValue<string>() == "conflict", "Stale phone control revision reached removal.");
        var fixedGrant = await Action("grant", new() { ["name"] = "device_status", ["enabled"] = false });
        TestAssert.That(!fixedGrant["ok"]!.GetValue<bool>() && fixedGrant["code"]!.GetValue<string>() == "unsupported_feature", "A fixed protocol grant became freely writable.");
        store.SetBluetoothPreference(peer.Id, true, "AA:BB:CC:DD:EE:FF");
        var bluetooth = await Action("bluetooth", new() { ["enabled"] = false, ["address"] = "" });
        TestAssert.That(bluetooth["ok"]!.GetValue<bool>() && bluetooth["persisted"]!.GetValue<bool>() && store.StoredBluetoothMatches(peer.Id, false, ""), "Bluetooth preference did not use the actual shared native store.");
        store.SavePending(peer, Enumerable.Repeat((byte)1, 32).ToArray(), Enumerable.Repeat((byte)2, 32).ToArray(), Enumerable.Repeat((byte)3, 32).ToArray(), DateTimeOffset.UtcNow.AddMinutes(1).ToUnixTimeMilliseconds());
        var pendingRemoved = await Action("remove");
        TestAssert.That(pendingRemoved["ok"]!.GetValue<bool>() && pendingRemoved["persisted"]!.GetValue<bool>() && store.LoadPeers().Count == 0, "Pending native phone binding could not be removed with its exact public identity.");
        store.SavePeers([peer]);
        var enabled = await Action("settings", new() { ["enabled"] = true });
        TestAssert.That(enabled["ok"]!.GetValue<bool>() && enabled["status"]!["listening"]!.GetValue<bool>(), "Native enablement did not start the owned private listener.");
        var opened = await Action("pairing_begin");
        TestAssert.That(opened["ok"]!.GetValue<bool>() && !opened["persisted"]!.GetValue<bool>() && opened["status"]!["pairing_open"]!.GetValue<bool>(), "Opening a pairing window claimed a durable phone binding.");
        var removed = await Action("remove");
        TestAssert.That(removed["ok"]!.GetValue<bool>() && removed["persisted"]!.GetValue<bool>() && store.LoadPeers().Count == 0, "Native removal did not verify binding absence.");
        TestAssert.That(emitted.Count == 0 && kdeReads == 0, "MCP phone controls emitted GUI callbacks or implicitly queried/started KDE.");
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var listener = (System.Net.Sockets.TcpListener)typeof(TelefonCoordinator).GetField("listener", flags)!.GetValue(service)!;
        var token = (byte[])typeof(TelefonCoordinator).GetField("pairingToken", flags)!.GetValue(service)!;
        using var client = new System.Net.Sockets.TcpClient();
        var endpoint = (System.Net.IPEndPoint)listener.LocalEndpoint;
        await client.ConnectAsync(endpoint.Address, endpoint.Port);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var init = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_init", ["pairing_token"] = Convert.ToBase64String(token),
            ["device_id"] = "33333333-3333-4333-8333-333333333333", ["role"] = "phone", ["display_name"] = "Owned incoming phone",
            ["static_public"] = Convert.ToBase64String(TelefonCrypto.GenerateX25519().Public), ["ephemeral_public"] = Convert.ToBase64String(TelefonCrypto.GenerateX25519().Public),
            ["nonce"] = Convert.ToBase64String(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32)), ["versions"] = new JsonArray(1) };
        await TelefonCoordinator.WriteFrameAsync(client.GetStream(), init, deadline.Token);
        var response = await TelefonCoordinator.ReadFrameWithinAsync(client.GetStream(), 65536, TimeSpan.FromSeconds(5), deadline.Token);
        TestAssert.That(response["type"]!.GetValue<string>() == "pair_response", "Owned phone handshake did not reach the actual pairing engine.");
        JsonObject? pending = null;
        while (pending is null)
        {
            deadline.Token.ThrowIfCancellationRequested();
            pending = service.McpStatus()["pending_pairings"]!.AsArray().OfType<JsonObject>().FirstOrDefault();
            if (pending is null) await Task.Delay(10, deadline.Token);
        }
        var reject = await Action("pairing_cancel", new() { ["peerId"] = pending["id"]!.GetValue<string>(), ["fingerprint"] = pending["fingerprint"]!.GetValue<string>(), ["attemptId"] = pending["attempt_id"]!.GetValue<string>() });
        TestAssert.That(reject["ok"]!.GetValue<bool>() && !reject["persisted"]!.GetValue<bool>() && store.LoadPeers().Count == 0, "Pairing decision acceptance was confused with completed authentication.");
        while (!emitted.Contains("App.telefonPaarung")) { deadline.Token.ThrowIfCancellationRequested(); await Task.Delay(10, deadline.Token); }
        client.Close();
    }
}
