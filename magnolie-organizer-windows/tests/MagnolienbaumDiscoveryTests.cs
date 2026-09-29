using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class MagnolienbaumDiscoveryTests
{
    internal static async Task RunAsync()
    {
        foreach (var enabled in new[] { false, true })
        {
            var root = Path.Combine(Path.GetTempPath(), "magnolie-discovery-" + Guid.NewGuid().ToString("N"));
            var paths = new WindowsPaths(root);
            paths.EnsureDirectories();
            using var reservation = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            var port = ((IPEndPoint)reservation.Client.LocalEndPoint!).Port;
            reservation.Dispose();
            var store = new MagnolienbaumStore(paths);
            var state = store.LoadOrCreate();
            state["port"] = port; state["an"] = enabled;
            store.SaveState(state);
            JsonArray? found = null;
            using var coordinator = new MagnolienbaumCoordinator(paths, (name, value) =>
            {
                if (name == "App.baumGefunden") found = JsonSerializer.SerializeToNode(value)!["nachbarn"]!.AsArray();
                return Task.CompletedTask;
            });
            try
            {
                await coordinator.ResumeAsync();
                using var peer = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                var receiver = Task.Run(async () =>
                {
                    var request = await peer.ReceiveAsync(deadline.Token);
                    TestAssert.That(request.RemoteEndPoint.Port == port && Encoding.UTF8.GetString(request.Buffer) == "MAGNOLIENBAUM?",
                        "Discovery used an ephemeral, non-allowed response port.");
                    foreach (var text in new[] { "[]", "{\"magnolie\":[],\"kennung\":\"invalid\"}",
                        "{\"magnolie\":\"baum-1\",\"kennung\":\"remote-fixture\"}" })
                        await peer.SendAsync(Encoding.UTF8.GetBytes(text), request.RemoteEndPoint, deadline.Token);
                    if (enabled)
                    {
                        await peer.SendAsync("MAGNOLIENBAUM?"u8.ToArray(), request.RemoteEndPoint, deadline.Token);
                        var response = await peer.ReceiveAsync(deadline.Token);
                        TestAssert.That(JsonNode.Parse(response.Buffer)?["kennung"]?.GetValue<string>() == state["kennung"]!.GetValue<string>(),
                            "An active search prevented the listener from answering another peer.");
                    }
                });
                await coordinator.SearchAsync([(IPEndPoint)peer.Client.LocalEndPoint!]);
                await receiver;
                TestAssert.That(found?.Count == 1 && found[0]?["kennung"]?.GetValue<string>() == "remote-fixture",
                    "Discovery lost the peer or accepted malformed packets.");
                await coordinator.SearchAsync([]);
                TestAssert.That(found?.Count == 0, "A later search reused stale discovery results.");
            }
            finally
            {
                await coordinator.ShutdownAsync();
                Directory.Delete(root, true);
            }
        }
    }
}
