using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeClipboardReceiveTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-clipboard-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            const string peer = "cccccccccccccccccccccccccccccccc";
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            using var certificate = KdeConnectTests.Certificate(peer);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (var local = store.LoadOrCreate().Certificate) { }
            store.Pin(new(peer, "Clipboard fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var proposals = new ConcurrentQueue<KdeClipboardReceiveProposal>();
            backend.ClipboardProposed += proposals.Enqueue;
            TestAssert.Throws<InvalidOperationException>(() => backend.ConfigureClipboardReceive(true, "not-paired", true, () => true),
                "Clipboard receiving accepted an unpaired source.");
            var phone = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, peer, certificate, clipboard: true,
                desktopIdentity: greeting => TestAssert.That(!greeting.Body["incomingCapabilities"]!.AsArray().Any(
                    value => value?.GetValue<string>() == KdeConnectDirectBackend.ClipboardPacket), "Clipboard was advertised before opt-in."));
            using var client = phone.Client; using var stream = phone.Stream;
            await KdeConnectTests.WaitForDeviceAsync(backend, peer);
            var permitted = true;
            backend.ConfigureClipboardReceive(true, peer, false, () => permitted);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            async Task Send(string text, long? timestamp = null)
            {
                var body = new JsonObject { ["content"] = text };
                if (timestamp is not null) body["timestamp"] = timestamp.Value;
                await stream.WriteAsync(KdeConnectProtocol.Encode(timestamp is null ? KdeConnectDirectBackend.ClipboardPacket :
                    KdeConnectDirectBackend.ClipboardConnectPacket, body), deadline.Token);
            }
            async Task Wait(int count)
            { while (proposals.Count < count) await Task.Delay(10, deadline.Token); }
            await Send("Actual TLS clipboard <not markup>"); await Wait(1);
            var first = proposals.Single();
            TestAssert.That(!first.Automatic && first.DeviceId == peer && first.Text == "Actual TLS clipboard <not markup>" &&
                backend.CurrentClipboardReceiveProposal(first.Id) == first, "Default clipboard receive skipped confirmation or changed text.");
            TestAssert.That(backend.TakeClipboardReceive(first.Id, false) is null && backend.CurrentClipboardReceiveProposal(first.Id) is null,
                "Rejected clipboard offer remained usable.");
            await Send("Initial clipboard", 10); await Wait(2);
            await Send("Duplicate initial clipboard", 10);
            await Send("Barrier after duplicate"); await Wait(3);
            TestAssert.That(proposals.Count == 3 && !proposals.Any(value => value.Text == "Duplicate initial clipboard"),
                "A repeated clipboard-connect timestamp was accepted twice.");
            var pending = proposals.Last(); permitted = false;
            TestAssert.That(backend.TakeClipboardReceive(pending.Id, true) is null, "Revoked book permission still applied clipboard text.");
            permitted = true; backend.ConfigureClipboardReceive(true, peer, true, () => permitted);
            TestAssert.That(backend.CurrentClipboardReceiveProposal(proposals.ElementAt(1).Id) is null, "Configuration change retained an old offer.");
            await Send(""); await Wait(4); var automatic = proposals.Last();
            TestAssert.That(automatic.Automatic && backend.TakeClipboardReceive(automatic.Id, true) == "" &&
                backend.TakeClipboardReceive(automatic.Id, true) is null, "Explicit auto/empty clipboard was lost or applied twice.");
            backend.ConfigureClipboardReceive(false, "", false);
        }
        finally { Directory.Delete(root, recursive: true); }
    }
}
