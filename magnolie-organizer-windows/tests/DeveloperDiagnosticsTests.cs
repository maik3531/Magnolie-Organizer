using System.Collections;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeveloperDiagnosticsTests
{
    internal static async Task<int> HostAsync()
    {
        const string phone = "22222222-2222-4222-8222-222222222222";
        var root = Path.Combine(Path.GetTempPath(), "developer-read-host-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var peer = new TelefonPeer(phone, "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(phone, ownDevice: true, remoteOwnDevice: false);
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(55));
            using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(1);
            Console.WriteLine(((IPEndPoint)listener.LocalEndpoint).Port);
            using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
            var material = Enumerable.Repeat((byte)11, 32).Concat(Enumerable.Repeat((byte)12, 4))
                .Concat(Enumerable.Repeat((byte)13, 32)).Concat(Enumerable.Repeat((byte)14, 4)).ToArray();
            var handler = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptDeveloperRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var reject = typeof(TelefonCoordinator).GetMethod("RejectContactRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var connection = new TelefonConnection(peer, socket.GetStream(), Enumerable.Repeat((byte)7, 32).ToArray(), material, store,
                (source, message) => (Task<TelefonAck?>)handler.Invoke(coordinator, [source, message, "wifi"])!, deadline.Token, "wifi",
                rejectContactRead: (source, sender, ack) => (bool)reject.Invoke(coordinator, [source, sender, ack])!,
                receiveDeveloper: (source, sender, message) => (TelefonAck)accept.Invoke(coordinator, [source, sender, message])!);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator)
                .GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[phone] = connection;
            var receive = connection.RunAsync();
            try
            {
                TestAssert.That(!connection.DeveloperReadReady, "Cached controls authorized developer read.");
                await connection.SendCapabilitiesAsync(1); await connection.SendGrantsAsync(1, store.LocalGrants());
                await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000);
                while (!connection.DeveloperReadReady)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                var report = await coordinator.ReadDeveloperDiagnosticsAsync(phone, deadline.Token);
                TestAssert.That(report["format"]!.GetValue<int>() == 1 && report["events"]!.AsArray().Last()!["stage"]!.GetValue<string>() == "online",
                    "Encrypted Notes diagnostic report incomplete.");
                foreach (var scenario in new[] { "fresh_controls_missing", "disabled", "bluetooth", "own_revoked" })
                {
                    try { await coordinator.ReadDeveloperDiagnosticsAsync(phone, deadline.Token); throw new Exception("Notes released diagnostics: " + scenario); }
                    catch (IOException error) { TestAssert.That(error.Message.Contains("not_granted"), "Unexpected Notes diagnostic denial: " + error.Message); }
                }
                TestAssert.That(store.LoadStatus(phone) is null, "Developer report leaked into status history.");
                await connection.SendPlainAsync(new JsonObject { ["type"] = "close", ["reason"] = "normal" });
                await receive.WaitAsync(TimeSpan.FromSeconds(5));
                socket.Client.Shutdown(SocketShutdown.Send);
                Console.WriteLine("Windows/Notes encrypted diagnostics and Notes disabled/BT/own revocation: PASS");
                return 0;
            }
            finally
            {
                deadline.Cancel();
                try { await receive; } catch (OperationCanceledException) { } catch (IOException) { }
                online.Remove(phone);
            }
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    internal static async Task RunAsync()
    {
        foreach (var change in new[] { "none", "own", "grant", "bluetooth", "fresh", "key", "channel", "expired", "content", "too_many", "duplicate", "disabled_ack" })
            await ReadAsync(change);
    }

    private static async Task ReadAsync(string change)
    {
        var root = Path.Combine(Path.GetTempPath(), "developer-read-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            capabilities["device_status"]!["versions"]!.AsArray().Add(11);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Fixture", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store);
            var accept = typeof(TelefonCoordinator).GetMethod("AcceptDeveloperRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var reject = typeof(TelefonCoordinator).GetMethod("RejectContactRead", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var stream = new MemoryStream();
            using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            using var connection = new TelefonConnection(peer, stream, new byte[16], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), cancel.Token, "wifi",
                rejectContactRead: (source, sender, ack) => (bool)reject.Invoke(coordinator, [source, sender, ack])!,
                receiveDeveloper: (source, sender, message) => (TelefonAck)accept.Invoke(coordinator, [source, sender, message])!);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator)
                .GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            TestAssert.That(!connection.DeveloperReadReady, "Cached controls enabled developer access.");
            foreach (var flag in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
                typeof(TelefonConnection).GetField(flag, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(connection, true);
            TestAssert.That(connection.DeveloperReadReady, "Synthetic confirmed own Wi-Fi session unavailable.");
            var read = coordinator.ReadDeveloperDiagnosticsAsync(peer.Id, cancel.Token);
            var requests = (IDictionary)typeof(TelefonCoordinator).GetField("developerReads", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            TestAssert.That(requests.Count == 1, "Developer request not reserved before send.");
            var requestId = requests.Keys.Cast<string>().Single();
            var wait = requests[requestId]!;
            var messageId = (string)wait.GetType().GetProperty("MessageId")!.GetValue(wait)!;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var body = new JsonObject { ["version"] = 11, ["request_id"] = requestId, ["format"] = 1, ["app_version"] = "fixture",
                ["events"] = new JsonArray(new JsonObject { ["time_ms"] = now, ["stage"] = "online", ["transport"] = "wifi", ["failure"] = false }) };
            if (change == "own") store.SetPersonalSettings(peer.Id, ownDevice: false);
            if (change == "grant") store.SavePeers([peer with { Grants = new JsonObject(peer.Grants.Select(pair =>
                KeyValuePair.Create(pair.Key, pair.Key == "device_status" ? JsonValue.Create(false) as JsonNode : pair.Value?.DeepClone()))) }]);
            if (change == "bluetooth") typeof(TelefonConnection).GetField("transport", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(connection, "bluetooth");
            if (change == "fresh") typeof(TelefonConnection).GetField("freshOwnSettings", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(connection, false);
            if (change == "key") store.SavePeers([peer with { PublicKey = new byte[32] }]);
            if (change == "channel") online.Remove(peer.Id);
            if (change == "content") body["contacts"] = new JsonArray("private");
            if (change == "too_many") body["events"] = new JsonArray(Enumerable.Range(0, 129).Select(_ => body["events"]![0]!.DeepClone()).ToArray());
            var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = "device_status.report", ["created_ms"] = now - (change == "expired" ? 120000 : 0),
                ["expires_ms"] = now + (change == "expired" ? -60000 : 60000), ["body"] = body };
            if (change == "disabled_ack")
                await connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = messageId, ["status"] = "rejected", ["error"] = "not_granted" });
            else await connection.HandlePlainAsync(message);
            if (change is "none" or "duplicate")
            {
                var result = await read;
                TestAssert.That(result["app_version"]!.GetValue<string>() == "fixture" && result["events"]!.AsArray().Count == 1,
                    "Developer response lost technical diagnostics.");
                if (change == "duplicate")
                {
                    var ack = (TelefonAck)accept.Invoke(coordinator, [connection, peer, message])!;
                    TestAssert.That(ack.Status == "rejected", "Completed developer request accepted replay.");
                }
            }
            else if (change == "disabled_ack")
            {
                try { await read; throw new Exception("Disabled diagnosis succeeded."); }
                catch (IOException error) { TestAssert.That(error.Message.Contains("not_granted"), "Disabled acknowledgement lost its error."); }
            }
            else
            {
                TestAssert.That(!read.IsCompletedSuccessfully, "Revoked or invalid response released data: " + change);
                cancel.Cancel();
                try { await read; throw new Exception("Invalid developer read succeeded: " + change); }
                catch (OperationCanceledException) { }
            }
            TestAssert.That(requests.Count == 0 && store.LoadStatus(peer.Id) is null && store.Due(peer.Id, now).Count == 0,
                "Developer response persisted or waiter leaked.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }
}
