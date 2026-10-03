using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

/** Real coordinator and encrypted stream, with synthetic established-session keys. */
internal static class PersonalNoteModeTransportHost
{
    internal static async Task<int> RunAsync()
    {
        const string phone = "22222222-2222-4222-8222-222222222222";
        var temporary = Path.Combine(Path.GetTempPath(), "note-mode-windows-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(temporary);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var personal = new PersonalSyncStore(store);
            var peer = new TelefonPeer(phone, "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]);
            store.SetPersonalSettings(phone, ownDevice: true, remoteOwnDevice: false);
            store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
            store.SetNoteSettings(phone, PersonalSyncContract.NoteSettings("phone_import"), false);
            store.SetDesktopFeatures(true, true);
            var imported = 0;
            var complete = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            TelefonCoordinator? coordinator = null;
            Task Emit(string name, object payload)
            {
                if (name != "App.telefonPersonalSync") return Task.CompletedTask;
                var message = JsonSerializer.SerializeToNode(payload)!.AsObject();
                var body = message["body"]!.AsObject();
                if (message["kind"]!.GetValue<string>() == "personal_sync.batch")
                {
                    var note = body["records"]!.AsArray().OfType<JsonObject>().Single(record => record["kind"]!.GetValue<string>() == "note");
                    TestAssert.That(note["id"]!.GetValue<string>() == "phone-note" &&
                        note["value"]!["title"]!.GetValue<string>() == "Offline note" &&
                        note["value"]!["html"]!.GetValue<string>() == "<b>Phone formatting</b>", "The native receiver changed the phone note.");
                    var attachment = note["value"]!["attachments"]!.AsArray().Single()!.AsObject();
                    var bytes = personal.ReadVerifiedAttachment(phone, body["run_id"]!.GetValue<string>(), body["reply"]!.GetValue<bool>(),
                        body["records_hash"]!.GetValue<string>(), attachment["sha256"]!.GetValue<string>(), "incoming", "wifi", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    TestAssert.That(Encoding.ASCII.GetString(bytes) == "%PDF-1.4\n", "The native receiver changed attachment bytes.");
                    var target = Path.Combine(temporary, "import.json");
                    using (var file = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough))
                    { file.Write(Encoding.UTF8.GetBytes(body.ToJsonString())); file.Flush(true); }
                    TestAssert.That(JsonNode.DeepEquals(JsonNode.Parse(File.ReadAllText(target)), body), "Import data did not survive its durable reopen.");
                    TestAssert.That(coordinator!.CommitPersonalSync(phone, message["pending_message_id"]!.GetValue<string>(),
                        message["commit_token"]!.GetValue<string>(), "applied"), "The native import commit was rejected.");
                    imported++;
                }
                if (message["kind"]!.GetValue<string>() == "personal_sync.report" && body["state"]!.GetValue<string>() == "complete")
                    complete.TrySetResult();
                return Task.CompletedTask;
            }
            using var owner = coordinator = new TelefonCoordinator(paths, Emit, dataStore: store);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
            using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(1);
            Console.WriteLine(((IPEndPoint)listener.LocalEndpoint).Port);
            using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
            var material = Enumerable.Repeat((byte)11, 32).Concat(Enumerable.Repeat((byte)12, 4))
                .Concat(Enumerable.Repeat((byte)13, 32)).Concat(Enumerable.Repeat((byte)14, 4)).ToArray();
            var handler = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            using var connection = new TelefonConnection(peer, socket.GetStream(), Enumerable.Repeat((byte)7, 32).ToArray(), material, store,
                (source, message) => (Task<TelefonAck?>)handler.Invoke(coordinator, [source, message, "wifi"])!, deadline.Token, "wifi");
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator)
                .GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[phone] = connection;
            var receive = connection.RunAsync();
            try
            {
                await connection.SendCapabilitiesAsync(1);
                await connection.SendGrantsAsync(1, store.LocalGrants());
                await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60_000);
                await connection.SendNoteSettingsAsync(true);
                while (!connection.NotePolicyReady)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                var run = Guid.NewGuid().ToString("D");
                var request = new JsonObject { ["format"] = 2, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") };
                personal.RememberRun(phone, request, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                var value = new JsonObject { ["title"] = "Desktop private", ["text"] = "Never send", ["html"] = "", ["notebook_id"] = "private",
                    ["symbol"] = "note", ["created_ms"] = 1, ["modified_ms"] = 1, ["attachments"] = new JsonArray() };
                var records = new JsonArray(new JsonObject { ["kind"] = "note", ["id"] = "desktop-private", ["state"] = "live",
                    ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Guid.NewGuid().ToString("D"), ["counter"] = 1 }),
                    ["hash"] = PersonalSyncContract.ProjectionHash(value), ["modified_ms"] = 1, ["value"] = value });
                var forbidden = new JsonObject { ["format"] = 2, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString("D"),
                    ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records"] = records, ["records_hash"] = PersonalSyncContract.RecordsHash(records) };
                var queued = store.Enqueue(phone, "personal_sync.batch", forbidden, 60_000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                await connection.PumpOutboxNowAsync();
                TestAssert.That(store.OutboxMessage(phone, queued) is null, "A forbidden reverse note remained sendable.");
                var empty = forbidden.DeepClone().AsObject(); empty["batch_id"] = Guid.NewGuid().ToString("D");
                empty["records"] = new JsonArray(); empty["records_hash"] = PersonalSyncContract.RecordsHash(new JsonArray());
                await coordinator.SendPersonalSyncAsync(phone, "personal_sync.request", request);
                await coordinator.SendPersonalSyncAsync(phone, "personal_sync.batch", empty);
                var finished = await Task.WhenAny(complete.Task, receive).WaitAsync(deadline.Token);
                if (finished == receive) await receive;
                await complete.Task.WaitAsync(deadline.Token);
                TestAssert.That(imported == 1 && personal.ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Count == 0,
                    "The native import was duplicated or not committed.");
                await coordinator.SetDesktopFeaturesAsync(false, false);
                bool FeaturesPending()
                {
                    using var database = store.OpenDatabase(); database.Open(); using var query = database.CreateCommand();
                    query.CommandText = "SELECT COUNT(*) FROM outbox WHERE peer_id=$peer AND kind='personal_sync.desktop_features'";
                    query.Parameters.AddWithValue("$peer", phone); return Convert.ToInt64(query.ExecuteScalar()) != 0;
                }
                while (FeaturesPending())
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                var send = typeof(TelefonConnection).GetMethod("SendPlainAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
                await (Task)send.Invoke(connection, [new JsonObject { ["type"] = "close", ["reason"] = "normal" }])!;
                Console.WriteLine("C# import, attachment, durable commit, reverse-note suppression and desktop availability passed.");
            }
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
