using MagnolieOrganizer.Windows;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpKdeLifecycleTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-mcp-kde-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var adapter = new KdeConnectSms(new WindowsPaths(root));
            TestAssert.That(adapter.McpStatus() is null && adapter.McpStatus() is null,
                "Read-only KDE metadata initialized another native listener instead of reporting the uninitialized integration.");
            if (Environment.GetEnvironmentVariable("MAGNOLIE_MCP_KDE_PRIVATE_NET") == "1")
            {
                var hostNamespace = Environment.GetEnvironmentVariable("MAGNOLIE_MCP_KDE_HOST_NETNS");
                var currentNamespace = new FileInfo("/proc/self/ns/net").LinkTarget;
                TestAssert.That(!string.IsNullOrEmpty(hostNamespace) && !string.IsNullOrEmpty(currentNamespace) && currentNamespace != hostNamespace,
                    "KDE native transport acceptance requires an owned private network namespace.");
                await PrivateNetworkAsync(Path.Combine(root, "private"));
            }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task PrivateNetworkAsync(string root)
    {
        var paths = new WindowsPaths(root);
        await using var backend = new KdeConnectDirectBackend(paths, new KdeConnectTests.TestProtector(), activeDiscovery: false);
        var initial = backend.McpStatus();
        TestAssert.That(initial["revision"]!.GetValue<string>() == backend.McpStatus()["revision"]!.GetValue<string>() && initial["owned_listener"]!.GetValue<bool>(),
            "Actual private native KDE control snapshot was unstable or used another integration.");
        var store = new KdeConnectIdentityStore(paths, new KdeConnectTests.TestProtector());
        var remote = new KdeConnectIdentityStore(new WindowsPaths(Path.Combine(root, "remote")), new KdeConnectTests.TestProtector()).LoadOrCreate();
        try
        {
            var pin = KdeConnectProtocol.CertificatePin(remote.Certificate);
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            store.Confirm(new KdeConnectPeer(remote.Id, "Owned private peer", pin, now, true, "127.0.0.1", 1716, now), new HashSet<string>());
            var state = backend.McpStatus();
            TestAssert.That(state["peers"]![0]!["fingerprint"]!.GetValue<string>() == pin && state["revision"]!.GetValue<string>() != initial["revision"]!.GetValue<string>(), "Actual KDE peer store/pin change was absent from the native control snapshot.");
            var wrong = await backend.McpActionAsync(new() { ["action"] = "remove", ["expectedRevision"] = state["revision"]!.GetValue<string>(), ["peerId"] = remote.Id, ["fingerprint"] = "wrong" }, default);
            TestAssert.That(!wrong["ok"]!.GetValue<bool>() && store.LoadPeers().Count == 1, "Wrong KDE certificate pin changed the actual private peer store.");
            var removed = await backend.McpActionAsync(new() { ["action"] = "remove", ["expectedRevision"] = state["revision"]!.GetValue<string>(), ["peerId"] = remote.Id, ["fingerprint"] = pin }, default);
            TestAssert.That(removed["ok"]!.GetValue<bool>() && removed["persisted"]!.GetValue<bool>() && !removed["deliveryConfirmed"]!.GetValue<bool>() && store.LoadPeers().Count == 0,
                "Actual KDE removal did not verify native store absence or claimed remote delivery.");
            var refreshed = await backend.McpRefreshAsync(backend.McpStatus()["revision"]!.GetValue<string>(), default);
            TestAssert.That(refreshed["ok"]!.GetValue<bool>() && !refreshed["persisted"]!.GetValue<bool>(), "Actual KDE refresh did not preserve runtime/store distinction.");
            await PrivatePairingAsync(backend, paths, root);
        }
        finally { remote.Certificate.Dispose(); }
    }

    private static async Task PrivatePairingAsync(KdeConnectDirectBackend local, WindowsPaths paths, string root)
    {
        var remotePaths = new WindowsPaths(Path.Combine(root, "pairing-remote"));
        await using var remote = new KdeConnectDirectBackend(remotePaths, new KdeConnectTests.TestProtector(), activeDiscovery: false);
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var candidates = (System.Collections.Concurrent.ConcurrentDictionary<string, KdeConnectDiscovered>)typeof(KdeConnectDirectBackend).GetField("candidates", flags)!.GetValue(local)!;
        candidates[remote.LocalDeviceId] = new(new KdeConnectIdentity(remote.LocalDeviceId, "Owned pairing remote", remote.ListenerPort,
            [KdeConnectProtocol.SmsRequest], [KdeConnectProtocol.SmsMessages], "phone"), System.Net.IPAddress.Loopback, DateTimeOffset.UtcNow);
        var state = local.McpStatus();
        var candidate = state["candidates"]!.AsArray().OfType<JsonObject>().Single(item => item["id"]!.GetValue<string>() == remote.LocalDeviceId);
        var guiPairEvents = 0;
        local.PairingChanged += _ => Interlocked.Increment(ref guiPairEvents);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var begun = await local.McpActionAsync(new() { ["action"] = "pairing_begin", ["expectedRevision"] = state["revision"]!.GetValue<string>(),
            ["candidateId"] = remote.LocalDeviceId, ["sourceToken"] = candidate["source_token"]!.GetValue<string>() }, deadline.Token);
        TestAssert.That(begun["ok"]!.GetValue<bool>() && !begun["persisted"]!.GetValue<bool>(), "Actual private KDE TLS pairing did not reach a pending MCP-owned verification request: " + begun.ToJsonString());
        JsonObject? remotePending = null;
        while (remotePending is null)
        {
            deadline.Token.ThrowIfCancellationRequested();
            remotePending = remote.McpStatus()["pending"]!.AsArray().OfType<JsonObject>().FirstOrDefault();
            if (remotePending is null) await Task.Delay(10, deadline.Token);
        }
        await remote.ConfirmPairingAsync(remotePending["id"]!.GetValue<string>(), true, deadline.Token);
        JsonObject? pending = null;
        do
        {
            deadline.Token.ThrowIfCancellationRequested();
            state = local.McpStatus(); pending = state["pending"]!.AsArray().OfType<JsonObject>().FirstOrDefault();
            if (pending is null || !pending["remote_confirmed"]!.GetValue<bool>()) await Task.Delay(10, deadline.Token);
        } while (pending is null || !pending["remote_confirmed"]!.GetValue<bool>());
        var paired = await local.McpActionAsync(new() { ["action"] = "pairing_confirm", ["expectedRevision"] = state["revision"]!.GetValue<string>(),
            ["peerId"] = pending["id"]!.GetValue<string>(), ["fingerprint"] = pending["fingerprint"]!.GetValue<string>(), ["attemptId"] = pending["attempt_id"]!.GetValue<string>(), ["accept"] = true }, deadline.Token);
        TestAssert.That(paired["ok"]!.GetValue<bool>() && paired["persisted"]!.GetValue<bool>() && paired["pairedVerified"]!.GetValue<bool>() && !paired["deliveryConfirmed"]!.GetValue<bool>(),
            "Private KDE mutual confirmation did not verify the actual local trust-store commit: " + paired.ToJsonString());
        var stored = new KdeConnectIdentityStore(paths, new KdeConnectTests.TestProtector()).LoadPeers().Single(peer => peer.Id == remote.LocalDeviceId);
        TestAssert.That(stored.Paired && stored.CertificatePin == pending["fingerprint"]!.GetValue<string>() && guiPairEvents == 0,
            "Actual private TLS peer pin was not persisted or an MCP-owned late reply opened legacy GUI pairing feedback.");
    }
}
