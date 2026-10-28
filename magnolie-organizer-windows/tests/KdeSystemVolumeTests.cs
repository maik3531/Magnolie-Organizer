using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeSystemVolumeTests
{
    private sealed class Outputs : IKdeAudioOutputs
    {
        internal int Volume = 40;
        internal bool Muted = true;
        internal bool Enabled = true;
        internal bool Present = true;
        internal int? CoercedVolume;
        internal Action? BeforeRead;
        internal readonly List<string> Writes = [];
        internal readonly List<bool> MuteHistory = [];
        public IReadOnlyList<KdeAudioOutput> Read()
        {
            BeforeRead?.Invoke();
            return Present ? [new("owned-sink", "Owned output", Volume, Muted, Enabled)] : [];
        }
        private void Check(string name, Func<bool> permitted)
        {
            if (!permitted()) throw new InvalidOperationException("revoked");
            TestAssert.That(name == "owned-sink" && Present, "An unlisted output reached the native adapter.");
        }
        public void SetVolume(string name, int volume, Func<bool> permitted)
        { Check(name, permitted); Writes.Add("volume"); Volume = CoercedVolume ?? volume; }
        public void SetMute(string name, bool muted, Func<bool> permitted)
        { Check(name, permitted); Writes.Add("mute"); MuteHistory.Add(muted); Muted = muted; }
        public void SetDefault(string name, Func<bool> permitted)
        { Check(name, permitted); Writes.Add("default"); Enabled = true; }
    }

    private static JsonObject Json(string value) => JsonNode.Parse(value)!.AsObject();
    private static JsonObject Sink(JsonObject response) => response["sinkList"]![0]!.AsObject();

    internal static async Task RunAsync()
    {
        foreach (var invalid in new[] { "{}", "{\"requestSinks\":1}", "{\"requestSinks\":false}",
            "{\"requestSinks\":true,\"muted\":false}", "{\"name\":\"owned-sink\"}",
            "{\"name\":\"owned-sink\",\"volume\":true}", "{\"name\":\"owned-sink\",\"volume\":1.5}",
            "{\"name\":\"owned-sink\",\"volume\":-1}", "{\"name\":\"owned-sink\",\"volume\":101}",
            "{\"name\":\"owned-sink\",\"muted\":0}", "{\"name\":\"owned-sink\",\"enabled\":\"true\"}",
            "{\"name\":\"owned-sink\",\"muted\":false,\"command\":\"anything\"}" })
            TestAssert.Throws<InvalidDataException>(() => KdeSystemVolume.Parse(Json(invalid)), "Malformed system volume command accepted.");
        TestAssert.That(KdeSystemVolume.Parse(Json("{\"requestSinks\":true}")).Name is null, "Sink-list query rejected.");
        var disabled = KdeConnectProtocol.IdentityBody("owned", "Owned", 1716);
        var enabled = KdeConnectProtocol.IdentityBody("owned", "Owned", 1716, systemVolumeSupported: true);
        TestAssert.That(!disabled["incomingCapabilities"]!.AsArray().Any(node => node!.GetValue<string>() == KdeSystemVolume.Request) &&
            enabled["incomingCapabilities"]!.AsArray().Any(node => node!.GetValue<string>() == KdeSystemVolume.Request) &&
            enabled["outgoingCapabilities"]!.AsArray().Any(node => node!.GetValue<string>() == KdeSystemVolume.Packet), "System volume availability is not advertised accurately.");

        var outputs = new Outputs();
        await using var volume = new KdeSystemVolume(outputs);
        var query = await volume.ReceiveAsync(Json("{\"requestSinks\":true}"), () => true, CancellationToken.None);
        TestAssert.That(Sink(query)["muted"]!.GetValue<bool>() && outputs.Writes.Count == 0, "Read-only query unmuted the system.");
        var unmute = await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"muted\":false}"), () => true, CancellationToken.None);
        TestAssert.That(!Sink(unmute)["muted"]!.GetValue<bool>() && outputs.Volume == 40 && outputs.Writes.SequenceEqual(new[] { "mute" }), "Explicit system unmute changed player/volume state.");
        outputs.Muted = true; outputs.Writes.Clear(); outputs.CoercedVolume = 58;
        var changed = await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"volume\":60}"), () => true, CancellationToken.None);
        TestAssert.That(Sink(changed)["volume"]!.GetValue<int>() == 58 && !outputs.Muted && outputs.Writes.SequenceEqual(new[] { "volume", "mute" }), "Volume action did not unmute or report actual native readback.");
        outputs.MuteHistory.Clear();
        var both = await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"volume\":30,\"muted\":true}"), () => true, CancellationToken.None);
        TestAssert.That(Sink(both)["muted"]!.GetValue<bool>() && outputs.MuteHistory.SequenceEqual(new[] { true }), "Combined explicit mute temporarily unmuted the system.");
        outputs.Enabled = false; outputs.Writes.Clear();
        var selected = await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"enabled\":true}"), () => true, CancellationToken.None);
        TestAssert.That(Sink(selected)["enabled"]!.GetValue<bool>() && outputs.Writes.SequenceEqual(new[] { "default" }), "Explicit output selection was not read back from the native driver.");
        outputs.Writes.Clear();
        await TestAssert.ThrowsAsync<InvalidOperationException>(async () => {
            await volume.ReceiveAsync(Json("{\"name\":\"other\",\"muted\":false}"), () => true, CancellationToken.None); }, "Unlisted output accepted.");
        var allowed = true; outputs.BeforeRead = () => allowed = false;
        await TestAssert.ThrowsAsync<InvalidOperationException>(async () => {
            await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"muted\":false}"), () => allowed, CancellationToken.None); }, "Revocation during native lookup reached mutation.");
        TestAssert.That(outputs.Writes.Count == 0, "Rejected command changed an output.");
        outputs.BeforeRead = null;
        using (var cancel = new CancellationTokenSource())
        {
            cancel.Cancel();
            await TestAssert.ThrowsAsync<OperationCanceledException>(async () => {
                await volume.ReceiveAsync(Json("{\"name\":\"owned-sink\",\"muted\":false}"), () => true, cancel.Token); }, "Cancelled action changed an output.");
        }
        await LoopbackAsync(true);
        await LoopbackAsync(false);
    }

    private static async Task LoopbackAsync(bool supported)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-system-volume-" + Guid.NewGuid().ToString("N"));
        const string phone = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        try
        {
            var paths = new WindowsPaths(root); var protector = new KdeConnectTests.TestProtector();
            using var certificate = KdeConnectTests.Certificate(phone);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (store.LoadOrCreate().Certificate) { }
            store.Pin(new KdeConnectPeer(phone, "Owned audio fixture", KdeConnectProtocol.CertificatePin(certificate), 1));
            var outputs = new Outputs();
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false,
                systemVolume: new KdeSystemVolume(outputs));
            var connected = await KdeConnectTests.ConnectIncomingPhoneAsync(backend, phone, certificate, systemVolume: supported);
            using var client = connected.Client; using var stream = connected.Stream;
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            async Task<JsonObject> ReadUntil(Func<JsonObject, bool> predicate)
            {
                while (true)
                {
                    var packet = await KdeConnectProtocol.ReadAsync(stream, deadline.Token);
                    if (packet.Type == KdeSystemVolume.Packet && predicate(packet.Body)) return packet.Body;
                }
            }
            await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSystemVolume.Request, Json("{\"requestSinks\":true}")), deadline.Token);
            if (supported)
            {
                var initial = await ReadUntil(body => Sink(body)["muted"]!.GetValue<bool>());
                TestAssert.That(outputs.Writes.Count == 0 && Sink(initial)["name"]!.GetValue<string>() == "owned-sink", "Initial TLS state changed mute.");
                await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSystemVolume.Request,
                    Json("{\"name\":\"owned-sink\",\"volume\":65}")), deadline.Token);
                await ReadUntil(body => Sink(body)["volume"]!.GetValue<int>() == 65 && !Sink(body)["muted"]!.GetValue<bool>());
                TestAssert.That(outputs.Writes.SequenceEqual(new[] { "volume", "mute" }), "Pinned TLS system control did not reach the output adapter exactly once.");
            }
            else
            {
                var barrier = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                backend.SmsReceived += _ => barrier.TrySetResult();
                await stream.WriteAsync(KdeConnectProtocol.Encode(KdeSystemVolume.Request,
                    Json("{\"name\":\"owned-sink\",\"muted\":false}")), deadline.Token);
                var row = new JsonObject { ["_id"] = 1, ["thread_id"] = 1,
                    ["addresses"] = new JsonArray(new JsonObject { ["address"] = "+491701234567" }),
                    ["body"] = "Owned ordering barrier", ["date"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["type"] = 1, ["read"] = 1, ["sub_id"] = 0, ["event"] = 1 };
                await stream.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsMessages,
                    new JsonObject { ["version"] = 2, ["messages"] = new JsonArray(row) }), deadline.Token);
                await barrier.Task.WaitAsync(deadline.Token);
                TestAssert.That(outputs.Writes.Count == 0 && outputs.Muted, "Unnegotiated system-volume packets changed an output.");
            }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
