using System.Net;
using System.Text.Json.Nodes;
using System.Security.Cryptography.X509Certificates;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeFilesystemTests
{
    internal static async Task<int> NativeProbeAsync(string configuration)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var root = Path.GetDirectoryName(Path.GetFullPath(configuration))!;
        if (!Path.GetFileName(root).StartsWith("Magnolie-Kernel171-", StringComparison.Ordinal))
            throw new InvalidDataException("An owned filesystem fixture is required.");
        var config = JsonNode.Parse(await File.ReadAllTextAsync(configuration))!.AsObject();
        var address = IPAddress.Parse(config["host"]!.GetValue<string>());
        var report = KdeSftpDescription.Parse(new JsonObject { ["port"] = config["port"]!.DeepClone(),
            ["user"] = "kdeconnect", ["path"] = "/", ["password"] = "native-fixture-password" });
        using var certificate = X509Certificate2.CreateFromPem(config["certificate"]!.GetValue<string>());
        using var wrong = KdeConnectTests.Certificate("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
        string? shown = null;
        Action<string>? diagnostics = config["diagnostics"]?.GetValue<bool>() == true ? Console.Error.WriteLine : null;
        await using var browser = new KdeWindowsFilesystemBrowser(Path.Combine(root, "profile space,comma"), show: path =>
        {
            TestAssert.That(File.ReadAllText(Path.Combine(path, "fixture.txt")) == "fixture-only", "The kernel mount did not expose the owned SFTP fixture.");
            shown = path;
        }, diagnostics: diagnostics);
        TestAssert.That(browser.Available, "Installed SSHFS-Win and the versioned WinFsp driver were not detected.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(75));
        var wrongRejected = false;
        try { await browser.OpenAsync("wrong-key", address, report, KdeSftpDescription.PublicHostKey(wrong), () => true, deadline.Token); }
        catch (IOException) { wrongRejected = true; }
        TestAssert.That(wrongRejected && shown is null, "A wrong pinned SSH host key reached the file manager.");
        await browser.OpenAsync("fixture", address, report, KdeSftpDescription.PublicHostKey(certificate), () => true, deadline.Token);
        TestAssert.That(shown is not null, "Native mount readiness did not reach the directory handler.");
        Console.WriteLine("MOUNTED " + new JsonObject { ["point"] = shown }.ToJsonString());
        TestAssert.That(await Console.In.ReadLineAsync(deadline.Token) == "CLOSE", "The bounded native Explorer handshake did not finish.");
        await browser.CloseAsync("fixture");
        TestAssert.That(!File.Exists(Path.Combine(shown!, "fixture.txt")) && !Directory.Exists(shown), "Owned kernel mount or mount directory remained after close.");
        Console.WriteLine("NATIVE FILESYSTEM PASS: installed driver/client, pinned host-key rejection, kernel SFTP read, space/comma paths and unmount cleanup");
        return 0;
    }

    private static JsonObject Body() => new() { ["ip"] = "203.0.113.99", ["port"] = 1739, ["user"] = "kdeconnect",
        ["path"] = "/", ["password"] = "synthetic-only-password" };

    internal static async Task RunAsync()
    {
        var prerequisites = FilesystemRuntimeSetup.Packages();
        TestAssert.That(prerequisites.Count == 2 && prerequisites.Select(package => package.Kind).Order().SequenceEqual(new[] { "client", "driver" }) &&
            prerequisites.All(package => package.Publisher == "NAVIMATICS LLC" && package.Url.StartsWith("https://github.com/winfsp/", StringComparison.Ordinal) &&
                package.Sha256.Length == 64 && Convert.FromHexString(package.Sha256).Length == 32),
            "Installer prerequisites lost their embedded source/publisher/checksum binding.");
        TestAssert.That(KdeWindowsFilesystemBrowser.IsWinFspDriver("WinFsp", 2) &&
            KdeWindowsFilesystemBrowser.IsWinFspDriver("WinFsp+20261024T091731Z", 2),
            "Legacy or current side-by-side WinFsp driver service was not detected.");
        foreach (var name in new[] { "WinFsp.Launcher", "WinFsp.Np", "WinFsp+", "Other" })
            TestAssert.That(!KdeWindowsFilesystemBrowser.IsWinFspDriver(name, 2), "An unrelated service was accepted as the filesystem driver.");
        TestAssert.That(!KdeWindowsFilesystemBrowser.IsWinFspDriver("WinFsp+20261024T091731Z", 16),
            "A user-mode service was accepted as a filesystem driver.");
        foreach (var (field, value) in new (string, JsonNode?)[] { ("port", JsonValue.Create(true)), ("port", JsonValue.Create(0)),
            ("user", JsonValue.Create("-option")), ("path", JsonValue.Create("/a/../b")), ("password", JsonValue.Create("bad\npassword")),
            ("url", JsonValue.Create("file:///")), ("multiPaths", new JsonArray("../bad")) })
        {
            var body = Body(); body[field] = value;
            TestAssert.Throws<InvalidDataException>(() => KdeSftpDescription.Parse(body), "Hostile SFTP description accepted: " + field);
        }
        var report = KdeSftpDescription.Parse(Body());
        TestAssert.That(!report.ToString().Contains(report.Password), "SFTP description revealed its password.");
        var args = KdeWindowsFilesystemBrowser.Arguments(IPAddress.Parse("192.0.2.10"), report, "/cygdrive/c/owned/files", "/cygdrive/c/owned/known_hosts", "Magnolie-fixture");
        TestAssert.That(!string.Join(' ', args).Contains(report.Password) && !string.Join(' ', args).Contains("203.0.113.99") &&
            args.Contains("StrictHostKeyChecking=yes") && args.Contains("GlobalKnownHostsFile=/dev/null") && args.Contains("password_stdin") &&
            args.Contains("kdeconnect@192.0.2.10:/"), "Native arguments lost source pin, host-key policy or password isolation.");
        var unsupported = KdeConnectProtocol.IdentityBody("fixture", "Fixture", 1716);
        var supported = KdeConnectProtocol.IdentityBody("fixture", "Fixture", 1716, filesystemSupported: true);
        TestAssert.That(!unsupported["incomingCapabilities"]!.AsArray().Any(node => node?.GetValue<string>() == KdeSftpDescription.Packet) &&
            supported["incomingCapabilities"]!.AsArray().Any(node => node?.GetValue<string>() == KdeSftpDescription.Packet), "Unsupported filesystem was advertised.");
        await LoopbackAsync();
    }

    private sealed class Browser : IKdeFilesystemBrowser
    {
        internal bool Enabled = true;
        internal int Opens;
        internal Action? Before;
        internal string LastPublicKey = "";
        public bool Available => Enabled;
        public Task OpenAsync(string token, IPAddress address, KdeSftpDescription report, string publicKey, Func<bool> current, CancellationToken cancellation)
        {
            Before?.Invoke(); cancellation.ThrowIfCancellationRequested();
            if (!current()) throw new InvalidOperationException("filesystem_source_changed");
            TestAssert.That(address.Equals(IPAddress.Loopback) && report.Password == "synthetic-only-password", "Reply overrode authenticated endpoint or credentials.");
            Opens++; LastPublicKey = publicKey; return Task.CompletedTask;
        }
        public Task CloseAsync(string? token = null) => Task.CompletedTask;
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private static async Task LoopbackAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "kde-filesystem-test-" + Guid.NewGuid().ToString("N"));
        const string phone = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        try
        {
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            using var certificate = KdeConnectTests.Certificate(phone);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (store.LoadOrCreate().Certificate) { }
            store.Pin(new KdeConnectPeer(phone, "Filesystem fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            var browser = new Browser();
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false, filesystem: browser);
            var connected = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, phone, certificate, filesystem: true);
            using var client = connected.Client; using var stream = connected.Stream;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            JsonObject? device = null;
            while (device is null)
            {
                device = backend.FilesystemStatus()["devices"]!.AsArray().FirstOrDefault()?.AsObject();
                if (device is null) await Task.Delay(10, deadline.Token);
            }
            var token = device["token"]!.GetValue<string>();
            async Task Request()
            {
                while (true)
                {
                    var packet = await KdeConnectProtocol.ReadAsync(stream, deadline.Token);
                    if (packet.Type == KdeSftpDescription.Request)
                    {
                        TestAssert.That(packet.Body.Count == 1 && packet.Body["startBrowsing"]!.GetValue<bool>(), "Filesystem request became an arbitrary operation.");
                        return;
                    }
                }
            }
            await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await backend.OpenFilesystemAsync(phone, "bad", deadline.Token); }, "Wrong token accepted.");
            browser.Enabled = false;
            TestAssert.That(backend.FilesystemStatus()["devices"]!.AsArray().Count == 0, "Missing native client was exposed."); browser.Enabled = true;
            var read = backend.OpenFilesystemAsync(phone, token, deadline.Token);
            await Request(); await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSftpDescription.Packet, Body()), deadline.Token);
            TestAssert.That((await read)["state"]!.GetValue<string>() == "opened" && browser.Opens == 1 &&
                browser.LastPublicKey == KdeSftpDescription.PublicHostKey(certificate), "Result lost pinned host key or native result.");
            var allowed = true; browser.Before = () => allowed = false;
            var revoke = backend.OpenFilesystemAsync(phone, token, deadline.Token, () => allowed);
            await Request(); await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSftpDescription.Packet, Body()), deadline.Token);
            await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await revoke; }, "Revoked caller opened file manager.");
            TestAssert.That(browser.Opens == 1, "Rejected operation reached file manager."); browser.Before = null;
            var malformed = backend.OpenFilesystemAsync(phone, token, deadline.Token);
            await Request(); var invalid = Body(); invalid["command"] = "anything";
            await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSftpDescription.Packet, invalid), deadline.Token);
            await TestAssert.ThrowsAsync<IOException>(async () => { await malformed; }, "Unexpected fields became native arguments.");
            using var cancel = new CancellationTokenSource();
            var pending = backend.OpenFilesystemAsync(phone, token, cancel.Token);
            await Request(); cancel.Cancel();
            await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await pending; }, "Cancelled request retained its reader.");
            await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSftpDescription.Packet, Body()), deadline.Token);
            TestAssert.That(backend.FilesystemStatus()["devices"]!.AsArray().Count == 0 && browser.Opens == 1, "Late reply could feed a future request.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
