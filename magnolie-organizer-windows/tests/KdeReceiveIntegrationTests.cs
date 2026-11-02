using System.Collections.Concurrent;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeReceiveIntegrationTests
{
    private const string PhoneId = "cccccccccccccccccccccccccccccccc";

    private static byte[] Announcement(string name, long size, int port, long count, long total) => Encoding.UTF8.GetBytes(
        new JsonObject { ["id"] = 1, ["type"] = KdeShareProtocol.Request,
            ["body"] = new JsonObject { ["filename"] = name, ["numberOfFiles"] = count, ["totalPayloadSize"] = total },
            ["payloadSize"] = size, ["payloadTransferInfo"] = new JsonObject { ["port"] = port } }.ToJsonString() + "\n");

    private static async Task SendAsync(SslStream control, X509Certificate2 certificate, string desktopPin,
        string name, byte[] data, long count, long total, CancellationToken cancellation)
    {
        var listener = KdeConnectTests.BindKdeListener();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var send = ServeAsync();
        async Task ServeAsync()
        {
            using var client = await listener.AcceptTcpClientAsync(cancellation);
            await using var tls = new SslStream(client.GetStream(), false, (_, presented, _, _) =>
            {
                if (presented is null) return false;
                using var actual = new X509Certificate2(presented);
                return KdeConnectProtocol.CertificatePin(actual) == desktopPin;
            });
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
            {
                ServerCertificate = certificate, ClientCertificateRequired = true, EnabledSslProtocols = SslProtocols.Tls12,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck
            }, cancellation);
            await tls.WriteAsync(data, cancellation); await tls.FlushAsync(cancellation);
        }
        try
        {
            await control.WriteAsync(Announcement(name, data.Length, port, count, total), cancellation);
            await send.WaitAsync(cancellation);
        }
        finally { listener.Stop(); }
    }

    private static async Task WaitAsync(Func<bool> ready, CancellationToken cancellation)
    {
        while (!ready()) await Task.Delay(10, cancellation);
    }

    internal static async Task RunAsync()
    {
        await ReceiveAndRetryAsync();
        await DisabledAndOtherPeerAsync();
        await DisableIncompleteAsync();
        await PreserveUnexpectedCacheFileAsync();
    }

    private static async Task ReceiveAndRetryAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-receive-integration-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var defaults = Path.Combine(root, "default"); var selected = Path.Combine(root, "selected");
        Directory.CreateDirectory(defaults); Directory.CreateDirectory(selected);
        try
        {
            var paths = new WindowsPaths(Path.Combine(root, "profile")); var protector = new KdeConnectTests.TestProtector();
            using var certificate = KdeConnectTests.Certificate(PhoneId);
            var store = new KdeConnectIdentityStore(paths, protector);
            string desktopPin;
            using (var local = store.LoadOrCreate().Certificate) desktopPin = KdeConnectProtocol.CertificatePin(local);
            store.Pin(new(PhoneId, "Owned file fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            var proposals = new ConcurrentQueue<KdeFileReceiveProposal>();
            var savedEvents = new ConcurrentQueue<KdeSavedIncomingFile>();
            string stagingRoot;
            await using (var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false))
            {
                backend.FileProposed += proposals.Enqueue; backend.FileSaved += savedEvents.Enqueue;
                TestAssert.That(!backend.FileReceiveStatus()["file_enabled"]!.GetValue<bool>() &&
                    !Directory.EnumerateDirectories(paths.KdeConnect, "incoming-*").Any(), "Disabled native receiver created staging resources.");
                backend.ConfigureFileReceive(true, PhoneId, defaults, () => true);
                stagingRoot = Directory.EnumerateDirectories(paths.KdeConnect, "incoming-*").Single();
                var phone = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, PhoneId, certificate, share: true, desktopIdentity: greeting =>
                {
                    var capabilities = greeting.Body["incomingCapabilities"]!.AsArray();
                    TestAssert.That(capabilities.Any(value => value?.GetValue<string>() == KdeShareProtocol.Request) &&
                        capabilities.Any(value => value?.GetValue<string>() == KdeShareProtocol.Update), "Explicit receiver opt-in did not reach the genuine TLS identity.");
                });
                using var client = phone.Client; using var stream = phone.Stream;
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                await KdeConnectTests.WaitForDeviceAsync(backend, PhoneId);
                await SendAsync(stream, certificate, desktopPin, "first.txt", [1], 2, 3, deadline.Token);
                TestAssert.That(proposals.IsEmpty && !Directory.EnumerateFiles(selected).Any(), "Incomplete batch acquired acceptance or a destination file.");
                await SendAsync(stream, certificate, desktopPin, "second.txt", [2, 2], 2, 3, deadline.Token);
                await WaitAsync(() => proposals.Count == 1, deadline.Token);
                var proposal = proposals.Single();
                TestAssert.That(proposal.Files.Select(value => value.Name).SequenceEqual(["first.txt", "second.txt"]) &&
                    proposal.Size == 3 && backend.FileReceiveStatus()["pending_count"]!.GetValue<int>() == 1,
                    "Native backend did not offer the exact two-file list once.");
                var damaged = Directory.GetFiles(stagingRoot, "*.part").Single(path => new FileInfo(path).Length == 2);
                File.WriteAllBytes(damaged, [9, 9]);
                var partial = await backend.AcceptFileReceiveAsync(proposal.Id, selected, deadline.Token);
                TestAssert.That(!partial["ok"]!.GetValue<bool>() && partial["saved_count"]!.GetValue<int>() == 1 &&
                    File.ReadAllBytes(Path.Combine(selected, "first.txt")).SequenceEqual(new byte[] { 1 }) &&
                    backend.FileReceiveStatus()["reserved_bytes"]!.GetValue<long>() == 3,
                    "Partial publication lost the saved receipt or released the remaining staging budget.");
                File.WriteAllBytes(damaged, [2, 2]); // Only our exact synthetic corruption fixture is repaired.
                TestAssert.That(proposals.Last().DestinationFixed, "Retry forgot the initial explicit destination.");
                var completed = await backend.AcceptFileReceiveAsync(proposal.Id, "", deadline.Token);
                TestAssert.That(completed["ok"]!.GetValue<bool>() && completed["saved_count"]!.GetValue<int>() == 2 &&
                    File.ReadAllBytes(Path.Combine(selected, "second.txt")).SequenceEqual(new byte[] { 2, 2 }) &&
                    Directory.GetFiles(selected).Length == 2 && Directory.GetFiles(defaults).Length == 0 &&
                    savedEvents.Count == 2 && savedEvents.Select(value => value.Id).Distinct().Count() == 2,
                    "Native retry used another folder, duplicated a file or emitted duplicate saved receipts.");
                await WaitAsync(() => backend.FileReceiveStatus()["pending_count"]!.GetValue<int>() == 0, deadline.Token);
                await SendAsync(stream, certificate, desktopPin, "later.txt", [3], 1, 1, deadline.Token);
                await WaitAsync(() => proposals.Count == 3, deadline.Token);
                var later = proposals.Last();
                TestAssert.That(later.Id != proposal.Id && !File.Exists(Path.Combine(selected, "later.txt")),
                    "A later unrelated send inherited previous batch acceptance.");
                await backend.RejectFileReceiveAsync(later.Id);
                TestAssert.That(backend.FileReceiveStatus()["pending_count"]!.GetValue<int>() == 0 &&
                    !Directory.GetFiles(stagingRoot, "*.part").Any(), "Reject retained normal owned staging/slots.");
            }
            TestAssert.That(!Directory.Exists(stagingRoot), "Backend shutdown left its owned receiver root/marker behind.");
            TestAssert.That(Directory.GetFiles(selected).Length == 2, "Shutdown deleted the actually accepted destination files.");
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static async Task DisabledAndOtherPeerAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-receive-disabled-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            const string otherId = "dddddddddddddddddddddddddddddddd";
            using var certificate = KdeConnectTests.Certificate(otherId);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (store.LoadOrCreate().Certificate) { }
            store.Pin(new(PhoneId, "Selected fixture", new string('a', 64), 1));
            store.Pin(new(otherId, "Other fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var phone = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, otherId, certificate, share: true,
                desktopIdentity: greeting => TestAssert.That(!greeting.Body["incomingCapabilities"]!.AsArray()
                    .Any(value => value?.GetValue<string>() == KdeShareProtocol.Request), "Disabled receiver advertised a receive grant."));
            using var client = phone.Client; using var stream = phone.Stream;
            await KdeConnectTests.WaitForDeviceAsync(backend, otherId);
            foreach (var enabledForAnotherPeer in new[] { false, true })
            {
                if (enabledForAnotherPeer) backend.ConfigureFileReceive(true, PhoneId, "", () => true);
                var listener = KdeConnectTests.BindKdeListener();
                using var deadline = new CancellationTokenSource(TimeSpan.FromMilliseconds(500));
                try
                {
                    var accept = listener.AcceptTcpClientAsync(deadline.Token);
                    await stream.WriteAsync(Announcement("unselected.txt", 1, ((IPEndPoint)listener.LocalEndpoint).Port, 1, 1));
                    var connected = false;
                    try { using var unexpected = await accept; connected = true; }
                    catch (OperationCanceledException) { }
                    TestAssert.That(!connected && backend.FileReceiveStatus()["pending_count"]!.GetValue<int>() == 0,
                        "Disabled/unselected peer caused a payload connection or pending offer.");
                }
                finally { listener.Stop(); }
            }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }

    private static async Task DisableIncompleteAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-receive-disable-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            using var certificate = KdeConnectTests.Certificate(PhoneId);
            var store = new KdeConnectIdentityStore(paths, protector);
            string desktopPin;
            using (var local = store.LoadOrCreate().Certificate) desktopPin = KdeConnectProtocol.CertificatePin(local);
            var keyBefore = SHA256.HashData(File.ReadAllBytes(paths.KdeConnectIdentityKey));
            store.Pin(new(PhoneId, "Disable fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            await using (var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false))
            {
                var proposals = new ConcurrentQueue<KdeFileReceiveProposal>(); backend.FileProposed += proposals.Enqueue;
                backend.ConfigureFileReceive(true, PhoneId, "", () => true);
                var phone = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, PhoneId, certificate, share: true);
                using var client = phone.Client; using var stream = phone.Stream;
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(15));
                await KdeConnectTests.WaitForDeviceAsync(backend, PhoneId);
                await SendAsync(stream, certificate, desktopPin, "incomplete.txt", [1], 2, 2, deadline.Token);
                backend.ConfigureFileReceive(false, "", "");
                await WaitAsync(() => backend.FileReceiveStatus()["pending_count"]!.GetValue<int>() == 0, deadline.Token);
                TestAssert.That(proposals.IsEmpty && !backend.FileReceiveStatus()["file_enabled"]!.GetValue<bool>() &&
                    Directory.GetFiles(Directory.EnumerateDirectories(paths.KdeConnect, "incoming-*").Single(), "*.part").Length == 0,
                    "Disabling an incomplete receive leaked a grant, proposal, quota or staging file.");
                TestAssert.That((await backend.GetStatusAsync()).Available && keyBefore.SequenceEqual(SHA256.HashData(File.ReadAllBytes(paths.KdeConnectIdentityKey))),
                    "Disabling file reception disconnected/replaced the ordinary pinned device identity.");
            }
            TestAssert.That(!Directory.EnumerateDirectories(paths.KdeConnect, "incoming-*").Any(), "Disabled receiver root survived normal backend shutdown.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }

    private static async Task PreserveUnexpectedCacheFileAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-receive-owned-cleanup-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            var store = new KdeConnectIdentityStore(paths, protector);
            using (store.LoadOrCreate().Certificate) { }
            store.Pin(new(PhoneId, "Cleanup fixture", new string('a', 64), 1));
            var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            try
            {
                backend.ConfigureFileReceive(true, PhoneId, "", () => true);
                var area = Directory.EnumerateDirectories(paths.KdeConnect, "incoming-*").Single();
                var unknown = Path.Combine(area, "not-owned-by-the-receiver.txt");
                File.WriteAllText(unknown, "synthetic unrelated work");
                await TestAssert.ThrowsAsync<IOException>(() => backend.DisposeAsync().AsTask(),
                    "Nonempty unexpected cache directory was silently/recursively discarded or cleanup falsely passed.");
                TestAssert.That(File.ReadAllText(unknown) == "synthetic unrelated work", "Receiver shutdown deleted unfamiliar data.");
                var listener = new TcpListener(IPAddress.Any, backend.ListenerPort);
                try { listener.Start(); }
                finally { listener.Stop(); }
            }
            finally { await backend.DisposeAsync(); }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
}
