using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalCustomTransportTests
{
    internal static async Task<int> HostAsync()
    {
        const string marker = "contracts/personal-custom-v4-vectors.json";
        var root = TestSource.Root(marker);
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(root, marker)))!.AsObject();
        var consent = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "contracts/personal-custom-consent-v4-vectors.json")))!.AsObject();
        var temporary = Path.Combine(Path.GetTempPath(), "personal-custom-host-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new TelefonStore(new WindowsPaths(temporary), Enumerable.Repeat((byte)19, 32).ToArray());
            var peer = new TelefonPeer(consent["other_source_id"]!.GetValue<string>(), "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray(),
                StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
                StoredGrants: TelefonProtocolContract.DesktopGrants());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            store.SetCustomSettings(peer.Id, consent["remote"]!.AsObject(), false);
            store.SetCustomSettings(peer.Id, consent["local"]!.AsObject(), true);
            using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(1);
            Console.WriteLine(((IPEndPoint)listener.LocalEndpoint).Port);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
            var material = Enumerable.Repeat((byte)11, 32).Concat(Enumerable.Repeat((byte)12, 4))
                .Concat(Enumerable.Repeat((byte)13, 32)).Concat(Enumerable.Repeat((byte)14, 4)).ToArray();
            using var connection = new TelefonConnection(peer, socket.GetStream(), Enumerable.Repeat((byte)7, 32).ToArray(), material, store,
                (_, message) => {
                    if (message["kind"]!.GetValue<string>() != "personal_sync.custom_settings") throw new InvalidDataException();
                    store.SetCustomSettings(peer.Id, message["body"]!.AsObject(), true);
                    return Task.FromResult<TelefonAck?>(null);
                }, deadline.Token, "wifi");
            var run = connection.RunAsync();
            var stale = vectors["batch"]!.DeepClone().AsObject(); stale["revision"] = 3;
            foreach (var body in new[] { vectors["batch"]!.AsObject(), vectors["batch"]!.AsObject(), vectors["deletion"]!.AsObject(), stale })
            {
                var id = store.Enqueue(peer.Id, "personal_sync.custom_batch", body, 60_000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                while (store.OutboxMessage(peer.Id, id) is not null)
                {
                    if (run.IsCompleted) await run;
                    await Task.Delay(10, deadline.Token);
                }
            }
            while (store.CustomSettings(peer.Id)["remote"]?["enabled"]?.GetValue<bool>() != false)
            {
                if (run.IsCompleted) await run;
                await Task.Delay(10, deadline.Token);
            }
            TestAssert.That(!store.CustomAllowed(peer.Id, "personal_sync.custom_batch", vectors["batch"]!.AsObject(), true), "Revoked native send remained authorized.");
            // Allow the native receiver to finish its durable settings ACK before closing.
            await Task.Delay(50, deadline.Token);
            deadline.Cancel();
            try { await run; } catch (OperationCanceledException) { } catch (IOException) { }
            return 0;
        }
        finally { if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }
}
