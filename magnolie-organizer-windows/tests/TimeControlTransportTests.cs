using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeControlTransportTests
{
    internal static async Task RunAsync()
    {
        foreach (var scenario in new[] { "read", "command", "cancel", "wrong_operation", "unsupported" }) await Run(scenario);
    }
    private static async Task Run(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-time-control-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            capabilities["personal_tasks_sync"]!["versions"] = new JsonArray(1, 7, 13); capabilities["personal_tasks_sync"]!["available"] = true;
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned timer", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities, GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var local = TimeSyncContract.NewSettings(true); var remote = TimeSyncContract.NewSettings(true);
            store.SetTimeSettings(peer.Id, local); store.SetTimeSettings(peer.Id, remote, true);
            var callbacks = new List<string>();
            using var coordinator = new TelefonCoordinator(paths, (kind, _) => { callbacks.Add(kind); return Task.CompletedTask; }, dataStore: store, foregroundEnabled: true, localOnly: true);
            coordinator.SharedLocalCapabilities = () => capabilities.DeepClone().AsObject();
            using var wire = new MemoryStream(); using var lifetime = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store, (_, _) => Task.FromResult<TelefonAck?>(null), lifetime.Token, "wifi");
            connection.SharedLocalCapabilities = coordinator.SharedLocalCapabilities;
            connection.TimerControlReportReceived = (source, report) => coordinator.ReceiveTimeControlReportAsync(source, peer, report);
            void Set(string name, object value) => typeof(TelefonConnection).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(connection, value);
            foreach (var flag in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" }) Set(flag, true);
            Set("actorRemoteOwnDecision", true); Set("actorCapabilityRevision", 1L); Set("actorGrantRevision", 1L);
            Set("sentTimePolicy", local); Set("receivedTimePolicy", remote);
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            if (scenario == "unsupported")
            {
                capabilities["personal_tasks_sync"]!["versions"] = new JsonArray(1, 7);
                TestAssert.That(coordinator.TimeControlSource(peer.Id, fingerprint, false) is null, "Unnegotiated timer advertised a native source.");
                var unsupported = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "time_control_source", ["peerId"] = peer.Id, ["fingerprint"] = fingerprint }, default);
                TestAssert.That(unsupported["code"]!.GetValue<string>() == "unsupported_feature", "Old peers were offered fake timer control.");
                return;
            }
            var id = Guid.NewGuid().ToString("D"); var operation = scenario == "command" ? Guid.NewGuid().ToString("D") : "";
            var body = TimeControlContract.Request(id, operation.Length == 0 ? "read" : "start", operation,
                operation.Length == 0 ? "" : new string('a', 64), operation.Length == 0 ? "" : "native-book");
            var request = scenario == "read" ? coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "time_control_query", ["peerId"] = peer.Id,
                ["fingerprint"] = fingerprint, ["sourceRevision"] = coordinator.TimeControlSource(peer.Id, fingerprint, false), ["body"] = body.DeepClone() }, lifetime.Token)
                : coordinator.RequestTimeControlAsync(peer.Id, fingerprint, body, cancellation: lifetime.Token);
            TestAssert.That(!request.IsCompleted && wire.Length > 0, "Timer did not issue a live correlated request.");
            if (scenario == "cancel")
            {
                TestAssert.That(!coordinator.CancelTimeControl(Guid.NewGuid().ToString("D"), fingerprint, id), "Foreign owner cancelled timer request.");
                TestAssert.That(coordinator.CancelTimeControl(peer.Id, fingerprint, id), "Owning timer request could not be cancelled.");
                try { await request; throw new Exception("Cancelled timer request succeeded."); } catch (OperationCanceledException) { }
                return;
            }
            const string vectorsPath = "contracts/time-control-v13.json";
            var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(vectorsPath), vectorsPath)))!;
            var report = vectors["reports"]![operation.Length == 0 ? 0 : 1]!.DeepClone().AsObject();
            report["request_id"] = id; report["operation_id"] = operation;
            if (operation.Length != 0) report["applied_entry_id"] = operation;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            JsonObject Packet(JsonObject value) => new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = TimeControlContract.ReportKind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = value.DeepClone() };
            if (scenario == "wrong_operation")
            {
                var wrong = report.DeepClone().AsObject(); wrong["request_id"] = Guid.NewGuid().ToString("D");
                await connection.HandlePlainAsync(Packet(wrong)); TestAssert.That(!request.IsCompleted, "Unmatched timer report completed another request.");
            }
            await connection.HandlePlainAsync(Packet(report)); var result = await request;
            if (scenario == "read") {
                TestAssert.That(result["ok"]!.GetValue<bool>(), "Private native MCP timer facade failed.");
                result = result["timeControl"]!.AsObject();
            }
            TestAssert.That(JsonNode.DeepEquals(result["report"], report) && result["dispatch_started"]!.GetValue<bool>() && callbacks.Count == 0,
                "Native timer report lost source/correlation or leaked to GUI.");
            await connection.HandlePlainAsync(Packet(report));
            TestAssert.That(callbacks.Count == 0, "Late timer report entered GUI/cache replay.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
