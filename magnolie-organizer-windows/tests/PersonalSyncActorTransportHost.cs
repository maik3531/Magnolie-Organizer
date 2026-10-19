using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Actual native coordinator/channel/private stagers, synthetic established session only.
internal static class PersonalSyncActorTransportHost
{
    internal static async Task<int> RunAsync(string phoneId, string phonePublic)
    {
        var temporary = Path.Combine(Path.GetTempPath(), "actor-windows-host-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(temporary);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var identity = store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
            var capabilities = TelefonProtocolContract.DesktopCapabilities();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) capabilities["items"]![name]!["versions"]!.AsArray().Add(12);
            var peer = new TelefonPeer(phoneId, "Owned actor phone", Convert.FromBase64String(phonePublic),
                StoredCapabilities: capabilities["items"]!.DeepClone().AsObject());
            store.SavePeers([peer]); store.SetPersonalSettings(phoneId, ownDevice: true, remoteOwnDevice: false);
            store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
            var initial = SharedSyncSettings.Effective(SharedSyncSettings.Create(identity.Id)); initial["auto_mode"] = "manual";
            store.InitializeSharedSettings(phoneId, peer.PublicKey, initial);
            var guiAdoptions = 0;
            using var coordinator = new TelefonCoordinator(paths, (name, _) => {
                if (name == "App.telefonPersonalSync") guiAdoptions++;
                return Task.CompletedTask;
            }, dataStore: store, foregroundEnabled: true, localOnly: true)
                { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
            var book = new NativeBookOwnerScope(); book.SetReady(true);
            coordinator.NativeBookSource = () => book.Current("owned-native-actor-book", true);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(50));
            using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(1);
            Console.WriteLine(new JsonObject { ["port"] = ((IPEndPoint)listener.LocalEndpoint).Port,
                ["device_id"] = identity.Id, ["static_public"] = Convert.ToBase64String(identity.PublicKey) }.ToJsonString());
            using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
            var material = Enumerable.Repeat((byte)11, 32).Concat(Enumerable.Repeat((byte)12, 4))
                .Concat(Enumerable.Repeat((byte)13, 32)).Concat(Enumerable.Repeat((byte)14, 4)).ToArray();
            var receiveMethod = typeof(TelefonCoordinator).GetMethod("HandleMessageAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            string? cancellingRun = null;
            var cancelReceipt = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            using var connection = new TelefonConnection(peer, socket.GetStream(), Enumerable.Repeat((byte)7, 32).ToArray(), material, store,
                (source, message) => (Task<TelefonAck?>)receiveMethod.Invoke(coordinator, [source, message, "wifi"])!, deadline.Token, "wifi")
                { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject(),
                    ActorMessageReceived = async (source, message) => {
                        if (message["kind"]?.GetValue<string>() == PersonalSyncActorContract.AckKind &&
                            cancellingRun is not null && message["body"]?["run_id"]?.GetValue<string>() == cancellingRun)
                            cancelReceipt.TrySetResult();
                        await coordinator.ReceivePersonalActorAsync(source, peer, message);
                    }, ActorPump = coordinator.PumpPersonalActorAsync };
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online[phoneId] = connection;
            var receive = connection.RunAsync();
            try
            {
                var caps = capabilities.DeepClone().AsObject(); caps["revision"] = store.NextOwnRevision("capabilities");
                await connection.SendMessageAsync("capabilities.update", caps, 86400000);
                await connection.SendGrantsAsync(store.NextOwnRevision("grants"), store.LocalGrants());
                await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000);
                var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
                while (coordinator.CurrentActorSource(phoneId, fingerprint) is null)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(10, deadline.Token);
                }
                var handle = await coordinator.CreatePersonalActorAsync(phoneId, fingerprint, deadline.Token);
                await coordinator.StartPersonalActorAsync(handle, deadline.Token);
                var personal = new PersonalSyncStore(store);
                PersonalSyncStagedBatch? staged;
                do
                {
                    if (receive.IsCompleted) await receive;
                    staged = personal.ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())
                        .FirstOrDefault(value => value.PeerId == PersonalSyncActorContract.StoragePeer(handle.ActorId));
                    if (staged is null) await Task.Delay(10, deadline.Token);
                } while (staged is null);
                TestAssert.That(staged.Records.Where(value => value!["kind"]!.GetValue<string>() == "note").Select(value => value!["id"]!.GetValue<string>()).SequenceEqual(["phone-note"]), "Actor note snapshot changed.");
                TestAssert.That(staged.Records.Where(value => value!["kind"]!.GetValue<string>() == "task").Select(value => value!["id"]!.GetValue<string>()).SequenceEqual(["phone-task"]), "Actor task snapshot changed.");
                var descriptor = staged.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
                    .SelectMany(value => value["value"]!["attachments"]!.AsArray().OfType<JsonObject>()).Single();
                var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
                var hash = descriptor["sha256"]!.GetValue<string>();
                await coordinator.WithPersonalActorStoreAsync(registry => {
                    registry.RequireCurrent(handle);
                    return true;
                });
                while (personal.MissingAttachmentRanges(privatePeer, handle.ActorId, false, staged.RecordsHash, hash,
                    "incoming", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Count != 0)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(10, deadline.Token);
                }
                var attachment = personal.ReadVerifiedAttachment(privatePeer, handle.ActorId, false, staged.RecordsHash, hash,
                    "incoming", "wifi", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                TestAssert.That(attachment.SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3 }), "Native actor attachment integrity failed.");
                CryptographicOperations.ZeroMemory(attachment);
                TestAssert.That(guiAdoptions == 0, "Actor snapshot reached GUI adoption.");
                cancellingRun = handle.ActorId;
                await coordinator.CancelPersonalActorAsync(handle, deadline.Token);
                await cancelReceipt.Task.WaitAsync(TimeSpan.FromSeconds(5), deadline.Token);
                await connection.SendPlainAsync(new JsonObject { ["type"] = "close", ["reason"] = "normal" });
                Console.WriteLine(new JsonObject { ["actor_id"] = handle.ActorId, ["private_core_records"] = staged.Records.Count,
                    ["lost_marked_ack_replayed"] = false, ["attachment_integrity_verified"] = true,
                    ["gui_adoption"] = false, ["book_persisted"] = false }.ToJsonString());
            }
            finally
            {
                deadline.Cancel();
                try { await receive; } catch (OperationCanceledException) { } catch (IOException) { }
                online.Remove(phoneId);
            }
            return 0;
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }
}
