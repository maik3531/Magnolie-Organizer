using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeSyncTransportHost
{
    internal static async Task<int> RunAsync(string? nativePhone = null, bool timerControl = false)
    {
        var phone = nativePhone ?? "22222222-2222-4222-8222-222222222222";
        var temporary = Path.Combine(Path.GetTempPath(), "time-sync-windows-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(temporary);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var capabilities = TelefonProtocolContract.DesktopCapabilities();
            if (timerControl) capabilities["items"]!["personal_tasks_sync"]!["versions"]!.AsArray().Add(13);
            var peer = new TelefonPeer(phone, "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: capabilities["items"]!.DeepClone().AsObject(),
                GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(phone, ownDevice: true, remoteOwnDevice: false);
            store.SetTimeSettings(phone, TimeSyncContract.NewSettings(true));
            var identity = store.LoadOrCreateIdentity();
            System.Security.Cryptography.CryptographicOperations.ZeroMemory(identity.PrivateKey);
            if (nativePhone is not null) {
                var initial = SharedSyncSettings.Effective(SharedSyncSettings.Create(identity.Id));
                initial["time_enabled"] = true; initial["time_mode"] = "two_way";
                store.InitializeSharedSettings(phone, peer.PublicKey, initial);
            }
            var imported = 0;
            var complete = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            TelefonCoordinator? coordinator = null;
            Task Emit(string name, object payload)
            {
                if (name != "App.personalTimeBatch") return Task.CompletedTask;
                var message = JsonSerializer.SerializeToNode(payload)!.AsObject(); var body = message["body"]!.AsObject();
                TestAssert.That(body["entries"]!.AsArray().OfType<JsonObject>().Any(record =>
                    record["note"]?.GetValue<string>() == "Phone time fixture"), "The phone record was not received.");
                TestAssert.That(!body.ContainsKey("calendar") && body["entries"]!.AsArray().OfType<JsonObject>().All(record =>
                    record["deleted"]?.GetValue<bool>() == false), "Notes sent an Organizer-only projection or deletion.");
                var target = Path.Combine(temporary, "document.json");
                using (var file = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough))
                { file.Write(Encoding.UTF8.GetBytes(body.ToJsonString())); file.Flush(true); }
                TestAssert.That(JsonNode.DeepEquals(JsonNode.Parse(File.ReadAllText(target)), body), "The document did not survive reopening.");
                TestAssert.That(coordinator!.CommitPersonalSync(phone, message["pending_message_id"]!.GetValue<string>(),
                    message["commit_token"]!.GetValue<string>(), "applied"), "The durable time receipt was rejected.");
                imported++; complete.TrySetResult(); return Task.CompletedTask;
            }
            using var owner = coordinator = new TelefonCoordinator(paths, Emit, dataStore: store, foregroundEnabled: timerControl, localOnly: true);
            if (timerControl) coordinator.SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject();
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
            using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(1);
            var port = ((IPEndPoint)listener.LocalEndpoint).Port;
            Console.WriteLine(nativePhone is not null ? new JsonObject { ["port"] = port, ["device_id"] = identity.Id }.ToJsonString() : port.ToString());
            using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
            var material = Enumerable.Repeat((byte)11, 32).Concat(Enumerable.Repeat((byte)12, 4))
                .Concat(Enumerable.Repeat((byte)13, 32)).Concat(Enumerable.Repeat((byte)14, 4)).ToArray();
            var handler = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var connection = new TelefonConnection(peer, socket.GetStream(), Enumerable.Repeat((byte)7, 32).ToArray(), material, store,
                (source, message) => (Task<TelefonAck?>)handler.Invoke(coordinator, [source, message, "wifi"])!, deadline.Token, "wifi");
            if (timerControl) {
                connection.SharedLocalCapabilities = coordinator.SharedLocalCapabilities;
                connection.TimerControlReportReceived = (source, report) => coordinator.ReceiveTimeControlReportAsync(source, peer, report);
            }
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator)
                .GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[phone] = connection;
            var receive = connection.RunAsync();
            try
            {
                if (timerControl) await connection.SendMessageAsync("capabilities.update", capabilities, 86400000);
                else await connection.SendCapabilitiesAsync(1);
                await connection.SendGrantsAsync(1, store.LocalGrants());
                await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000);
                while (coordinator.TimeSettings(phone)["ready"]?.GetValue<bool>() != true)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                if (timerControl) {
                    var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
                    while (coordinator.TimeControlSource(phone, fingerprint, true) is null ||
                        coordinator.SharedPreferences(phone)["ready"]?.GetValue<bool>() != true) {
                        if (receive.IsCompleted) await receive;
                        await Task.Delay(5, deadline.Token);
                    }
                    async Task<JsonObject> Call(JsonObject body) {
                        var result = await coordinator.RequestTimeControlAsync(phone, fingerprint, body, cancellation: deadline.Token);
                        var report = result["report"]!.AsObject();
                        TestAssert.That(report["status"]!.GetValue<string>() is "ok" or "duplicate", report.ToJsonString());
                        return report;
                    }
                    var before = await Call(TimeControlContract.Request(Guid.NewGuid().ToString("D")));
                    var operation = Guid.NewGuid().ToString("D");
                    var start = TimeControlContract.Request(Guid.NewGuid().ToString("D"), "start", operation,
                        before["revision"]!.GetValue<string>(), before["restore_epoch"]!.GetValue<string>(), activity: "Native timer TCP fixture");
                    var started = await Call(start);
                    JsonObject Command(string action, JsonObject current) => TimeControlContract.Request(Guid.NewGuid().ToString("D"), action,
                        Guid.NewGuid().ToString("D"), current["revision"]!.GetValue<string>(), current["restore_epoch"]!.GetValue<string>(), operation);
                    var paused = await Call(Command("pause", started));
                    TestAssert.That(paused["paused"]!.GetValue<bool>(), "Native timer did not pause.");
                    var replay = start.DeepClone().AsObject(); replay["request_id"] = Guid.NewGuid().ToString("D");
                    var duplicate = await Call(replay);
                    TestAssert.That(duplicate["status"]!.GetValue<string>() == "duplicate" && duplicate["paused"]!.GetValue<bool>(), "Timer replay rewrote native state.");
                    var resumed = await Call(Command("resume", duplicate));
                    TestAssert.That(!resumed["paused"]!.GetValue<bool>(), "Native timer did not resume.");
                    var timerFinished = await Call(Command("finish", resumed));
                    TestAssert.That(timerFinished["persisted"]!.GetValue<bool>() && timerFinished["entries"]!.AsArray().Count == 0 && imported == 0,
                        "Timer finish lacked native save proof or entered ordinary time import.");
                    var close = typeof(TelefonConnection).GetMethod("SendPlainAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
                    await (Task)close.Invoke(connection, [new JsonObject { ["type"] = "close", ["reason"] = "normal" }])!;
                    Console.WriteLine("C# native timer control: four durable commands and idempotent replay passed.");
                    return 0;
                }
                var entry = new JsonObject { ["id"] = "77777777-7777-4777-8777-777777777777", ["startMinute"] = 1000L,
                    ["endMinute"] = 1120L, ["pauseMinute"] = null, ["pauseMinutes"] = 15L, ["zone"] = "UTC",
                    ["type"] = "Desktop time fixture", ["note"] = "Desktop time fixture", ["modifiedMs"] = 1000L,
                    ["deleted"] = false, ["clock"] = new JsonObject { ["88888888-8888-4888-8888-888888888888"] = 1L }, ["pausePlan"] = null };
                var calendar = new JsonObject { ["enabled"] = true, ["country"] = "DE", ["regions"] = new JsonArray("DE-BE"),
                    ["holidays"] = new JsonArray(new JsonObject { ["date"] = "2026-10-03", ["name"] = "Synthetic national holiday",
                        ["country"] = "DE", ["nationwide"] = true, ["regions"] = new JsonArray() }) };
                var policies = store.TimeSettings(phone);
                foreach (var packet in TimeSyncContract.Batches(policies["local"]!.AsObject(), policies["remote"]!.AsObject(), new JsonArray(entry), calendar))
                    await coordinator.SendPersonalSyncAsync(phone, TimeSyncContract.Batch, packet);
                await coordinator.SendPersonalSyncAsync(phone, TimeSyncContract.Request,
                    TimeSyncContract.RequestBody(policies["local"]!.AsObject(), policies["remote"]!.AsObject()));
                var finished = await Task.WhenAny(complete.Task, receive).WaitAsync(deadline.Token);
                if (finished == receive) await receive;
                await complete.Task.WaitAsync(deadline.Token);
                TestAssert.That(imported == 1, "The time batch was applied more than once.");
                await coordinator.SendPersonalSyncAsync(phone, TimeSyncContract.Settings, new JsonObject { ["enabled"] = false });
                bool SettingsPending()
                {
                    using var database = store.OpenDatabase(); database.Open(); using var query = database.CreateCommand();
                    query.CommandText = "SELECT COUNT(*) FROM outbox WHERE peer_id=$peer AND kind='personal_sync.time_settings'";
                    query.Parameters.AddWithValue("$peer", phone); return Convert.ToInt64(query.ExecuteScalar()) != 0;
                }
                while (SettingsPending())
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                var send = typeof(TelefonConnection).GetMethod("SendPlainAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
                await (Task)send.Invoke(connection, [new JsonObject { ["type"] = "close", ["reason"] = "normal" }])!;
                Console.WriteLine("C# time synchronization: bidirectional durable records, calendar and revocation passed.");
            }
            catch (Exception error) { Console.Error.WriteLine(error); throw; }
            finally
            {
                deadline.Cancel();
                try { await receive; } catch (OperationCanceledException) { } catch (IOException) { }
                online.Remove(phone);
            }
            return 0;
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(temporary)) Directory.Delete(temporary, true);
        }
    }
}
