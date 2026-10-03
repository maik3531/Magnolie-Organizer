using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneContactReadTests
{
    internal static Task RunAsync()
    {
        var request = new JsonObject { ["version"] = 5, ["request_id"] = Guid.NewGuid().ToString("D"),
            ["action"] = "index", ["offset"] = 0, ["uids"] = new JsonArray() };
        PhoneContactRead.ValidateRequest(request);
        foreach (var action in new[] { "delete", "write", "import" })
        {
            var invalid = request.DeepClone().AsObject(); invalid["action"] = action;
            TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateRequest(invalid), "A contact write operation was accepted.");
        }
        var report = new JsonObject { ["version"] = 5, ["request_id"] = request["request_id"]!.DeepClone(),
            ["action"] = "index", ["offset"] = 0, ["total"] = 0, ["contacts"] = new JsonArray() };
        PhoneContactRead.ValidateReport(report);
        report["total"] = 1;
        TestAssert.Throws<InvalidDataException>(() => PhoneContactRead.ValidateReport(report), "An empty nonfinal page could cause an endless read.");
        var fingerprint = new string('a', 64);
        TestAssert.That(KdeContactImport.Binding("notes:fixture", fingerprint, "uid", "notes") !=
            KdeContactImport.Binding("notes:fixture", fingerprint, "uid"), "KDE and Notes source bindings collided.");
        return Task.CompletedTask;
    }

    internal static async Task<int> HostAsync()
    {
        const string phone = "22222222-2222-4222-8222-222222222222";
        var root = Path.Combine(Path.GetTempPath(), "contact-read-host-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)19, 32).ToArray());
            var peer = new TelefonPeer(phone, "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                GrantRevision: 1, StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(phone, ownDevice: true, remoteOwnDevice: false);
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store);
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
                TestAssert.That(!coordinator.ContactReadAvailable(phone), "Stored capabilities enabled contact access before fresh session controls.");
                await connection.SendCapabilitiesAsync(1); await connection.SendGrantsAsync(1, store.LocalGrants());
                await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60_000);
                while (!connection.ContactReadReady)
                {
                    if (receive.IsCompleted) await receive;
                    await Task.Delay(5, deadline.Token);
                }
                var index = await coordinator.ReadContactsAsync(phone, null, deadline.Token);
                TestAssert.That(index["contacts"]!.AsArray().Count == 130 && index["device_id"]!.GetValue<string>() == "notes:" + phone,
                    "Paged Notes contact index was incomplete or attributed to KDE.");
                var cards = await coordinator.ReadContactsAsync(phone, new JsonArray("fixture-000"), deadline.Token);
                var contact = ExchangeCodec.ParseVCard(cards["contacts"]![0]!["vcard"]!.GetValue<string>()).Kontakte.Single()!.AsObject();
                TestAssert.That(contact["vorname"]!.GetValue<string>() == "Fixture" && contact["foto"]!.GetValue<string>().StartsWith("data:image/png;base64,", StringComparison.Ordinal) &&
                    contact["sozialeMedien"]!.AsArray().Count == 1, "Contact, photo or explicit messenger source was lost in transport.");
                KdeContactImport.Project(cards, "notes:" + phone, ["fixture-000"], "notes");
                TestAssert.That(cards["contacts"]![0]!["bindung"]!.GetValue<string>().StartsWith("urn:magnolie:import:notes:", StringComparison.Ordinal),
                    "Notes preview lacks its own authenticated source binding.");
                TestAssert.That(store.LoadStatus(phone) is null, "A contact response leaked into ordinary device-status history.");
                var confirmed = store.LoadPeers().Single();
                store.SavePeers([confirmed with { State = "pair_commit_pending" }]);
                TestAssert.That(!coordinator.ContactReadAvailable(phone), "An unconfirmed pairing inherited contact-read access.");
                store.SavePeers([confirmed]);
                store.SetPersonalSettings(phone, ownDevice: false);
                TestAssert.That(!coordinator.ContactReadAvailable(phone), "Own-device revocation left contact access enabled.");
                try { await coordinator.ReadContactsAsync(phone, null, deadline.Token); throw new Exception("Revoked contact read reached the network."); }
                catch (InvalidOperationException) { }
                var send = typeof(TelefonConnection).GetMethod("SendPlainAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
                await (Task)send.Invoke(connection, [new JsonObject { ["type"] = "close", ["reason"] = "normal" }])!;
                Console.WriteLine("C# Notes contact paging, photo, messenger preview, source binding and revocation passed.");
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
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }
}
