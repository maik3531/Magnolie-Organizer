using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Real coordinator + connection validation/queue/crypto writer, synthetic streams and profiles.
internal static class OutgoingDialTests
{
    private const string PeerId = "11111111-1111-4111-8111-111111111111";
    private const string CallId = "22222222-2222-4222-8222-222222222222";
    private const string EndId = "33333333-3333-4333-8333-333333333333";
    private static MethodInfo Method(Type type, string name) => type.GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic)!;
    private static FieldInfo Field(Type type, string name) => type.GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!;
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    private static JsonObject Message(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1,
        ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["created_ms"] = Now(), ["expires_ms"] = Now() + 60_000,
        ["body"] = body.DeepClone() };
    private static JsonObject Event(string state, int revision, long start) => new() {
        ["call_ref"] = CallId, ["revision"] = (long)revision, ["state"] = state, ["direction"] = "outgoing",
        ["control_origin"] = "desktop", ["number"] = "", ["number_status"] = "not_shared", ["started_ms"] = start,
        ["offhook_ms"] = revision >= 2 ? start + 1 : 0, ["ended_ms"] = state == "idle" ? start + 2 : 0,
        ["occurred_ms"] = start + revision, ["spam_status"] = "unknown", ["battery_percent"] = -1, ["battery_captured_ms"] = 0 };

    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "magnolie-scoped-call-" + Guid.NewGuid().ToString("N"));
        internal readonly TelefonStore Store;
        internal readonly TelefonCoordinator Host;
        internal readonly TelefonPeer Peer;
        internal readonly List<JsonObject> Events = [];
        internal readonly List<JsonObject> Results = [];
        internal readonly MemoryStream Wire = new();
        internal TelefonConnection Connection;
        internal Fixture(bool legacy = false)
        {
            var paths = new WindowsPaths(Root); paths.EnsureDirectories(); Store = new TelefonStore(paths, new byte[32]);
            var caps = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            if (legacy) caps["dial_request"]!["versions"] = new JsonArray(1);
            Peer = new(PeerId, "Synthetic phone", new byte[32], StoredCapabilities: caps, StoredGrants: TelefonProtocolContract.DesktopGrants());
            Store.SavePeers([Peer]);
            Host = new(paths, (name, value) => {
                var body = System.Text.Json.JsonSerializer.SerializeToNode(value)!.AsObject();
                if (name == "App.telefonEingehenderAnruf") Events.Add(body);
                if (name == "App.telefonWaehlstatus" || name == "App.telefonAuflegestatus") Results.Add(body);
                return Task.CompletedTask;
            }, dataStore: Store, localOnly: true);
            Connection = Connect();
        }
        internal TelefonConnection Connect()
        {
            var authorize = Method(typeof(TelefonCoordinator), "AuthorizeCall").CreateDelegate<Func<TelefonPeer, string, JsonObject, string?>>(Host);
            var send = Method(typeof(TelefonCoordinator), "SendCall").CreateDelegate<Func<TelefonConnection, TelefonPeer, JsonObject, Action, bool>>(Host);
            var receive = Method(typeof(TelefonCoordinator), "HandleMessageAsync");
            var connection = new TelefonConnection(Peer, Wire, new byte[16], new byte[72], Store,
                (peer, message) => (Task<TelefonAck?>)receive.Invoke(Host, [peer, message, "wifi"])!, CancellationToken.None, "wifi",
                authorizeCall: authorize, sendCall: send);
            ((Dictionary<string, TelefonConnection>)Field(typeof(TelefonCoordinator), "online").GetValue(Host)!)[Peer.Id] = connection;
            return connection;
        }
        internal Task Dial() => Host.RequestDialAsync(PeerId, "+12025550123", CallId);
        internal Task Receive(string kind, JsonObject body) => Receive(Message(kind, body));
        internal async Task Receive(JsonObject message) => await (Task)Method(typeof(TelefonConnection), "HandlePlainAsync").Invoke(Connection, [message])!;
        internal JsonObject[] WireMessages()
        {
            using var stream = new MemoryStream(Wire.ToArray()); var result = new List<JsonObject>();
            while (stream.Position < stream.Length) {
                var envelope = TelefonCoordinator.ReadFrameAsync(stream, 1_048_576, CancellationToken.None).GetAwaiter().GetResult();
                var bytes = Convert.FromBase64String(envelope["ciphertext"]!.GetValue<string>()); envelope.Remove("ciphertext");
                var nonce = new byte[12]; System.Buffers.Binary.BinaryPrimitives.WriteInt64BigEndian(nonce.AsSpan(4), envelope["seq"]!.GetValue<long>());
                var plain = new byte[bytes.Length - 16]; using var aes = new System.Security.Cryptography.AesGcm(new byte[32], 16);
                aes.Decrypt(nonce, bytes.AsSpan(0, plain.Length), bytes.AsSpan(plain.Length), plain, TelefonCrypto.Canonical(envelope));
                result.Add(JsonNode.Parse(plain)!.AsObject());
            }
            return result.ToArray();
        }
        internal Task End(string callRef, long revision, string? command = null) => Host.RequestEndCallAsync(PeerId, callRef, revision, command ?? Guid.NewGuid().ToString("D"));
        public void Dispose() { Host.Dispose(); Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); Directory.Delete(Root, true); }
    }
    private static async Task Denied(Func<Task> action, string reason)
    {
        try { await action(); } catch (InvalidOperationException) { return; }
        throw new Exception("Not denied: " + reason);
    }
    internal static async Task<int> RunAsync(string? trace = null, string? output = null)
    {
        var start = Now() - 10;
        var captured = trace is null ? [] : JsonNode.Parse(File.ReadAllText(trace))!.AsArray().OfType<JsonObject>().ToArray();
        foreach (var message in captured.Where(e => e.ContainsKey("kind")))
            TelefonMessageContract.ValidateMessage(message, message["created_ms"]!.GetValue<long>(), true);
        var events = trace is null ? new[] { Event("ringing", 1, start), Event("offhook", 2, start), Event("idle", 3, start) }
            : captured.Any(e => e.ContainsKey("kind")) ? captured.Where(e => e["kind"]?.GetValue<string>() == "incoming_call_state.event")
                .Select(e => e["body"]!.AsObject()).OrderBy(e => e["revision"]!.GetValue<long>()).ToArray() : captured;
        var dialResult = captured.FirstOrDefault(e => e["kind"]?.GetValue<string>() == "dial_request.result")?["body"]?.DeepClone().AsObject()
            ?? new JsonObject { ["client_ref"] = CallId, ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = Now() };
        // Wire timestamps are synthetic capture time; only envelope clocks are refreshed.
        Check(events.Length == 3 && events.All(e => e["call_ref"]!.GetValue<string>() == CallId), "Android trace identity");
        using (var f = new Fixture())
        {
            foreach (var e in events) await f.Receive("incoming_call_state.event", e);
            Check(f.Events.Count == 0, "Unsolicited outgoing events accepted");
            f.Store.RememberCommand(PeerId, Guid.NewGuid().ToString("D"), Now());
            await f.Dial(); Check(f.Wire.Length > 0, "Dial not sent");
            await Denied(() => f.Dial(), "double dial");
            await Denied(() => f.End(CallId, 1), "end before active callback");
            // Events are allowed before dial_result; wrong directions/IDs never inherit scope.
            foreach (var direction in new[] { "incoming", "unknown" }) {
                var e = events[0].DeepClone().AsObject(); e["direction"] = direction;
                await f.Receive("incoming_call_state.event", e);
            }
            var wrong = events[0].DeepClone().AsObject(); wrong["call_ref"] = Guid.NewGuid().ToString("D");
            await f.Receive("incoming_call_state.event", wrong); Check(f.Events.Count == 0, "Scope broadened to another call");
            // New message IDs avoid confusing an earlier deliberate rejection with this fresh attempt.
            await f.Receive("incoming_call_state.event", events[0]);
            f.Connection = f.Connect(); // Android lifecycle publishing may reconnect.
            await f.Receive("incoming_call_state.event", events[1]);
            Check(f.Events.Count == 2 && f.Events[1]["end_authorized"]?.GetValue<bool>() == true, "Scoped offhook missing before result");
            await Denied(() => f.End(Guid.NewGuid().ToString("D"), 2), "other call end");
            await Denied(() => f.End(CallId, 1), "stale revision end");
            await Denied(() => f.Host.RequestAnswerAsync(PeerId, CallId, Guid.NewGuid().ToString("D")), "outgoing answer grant");
            var command = EndId; await f.End(CallId, 2, command);
            Check(f.WireMessages().Count(m => m["kind"]?.GetValue<string>() == "dial_request.command") == 1, "More than one actual dial write");
            Check(f.WireMessages().Single(m => m["kind"]?.GetValue<string>() == "end_call.command")["body"]?["call_ref"]?.GetValue<string>() == CallId, "Actual end write not bound");
            var result = captured.FirstOrDefault(e => e["kind"]?.GetValue<string>() == "end_call.result" && e["body"]?["command_ref"]?.GetValue<string>() == EndId)?["body"]?.DeepClone().AsObject()
                ?? new JsonObject { ["command_ref"] = command, ["call_ref"] = CallId, ["state"] = "submitted", ["error"] = "none", ["occurred_ms"] = Now() };
            result["call_ref"] = Guid.NewGuid().ToString("D");
            await f.Receive("end_call.result", result); Check(!f.Results.Any(r => r.ContainsKey("command_ref")), "Wrong-call end result accepted");
            result["call_ref"] = CallId; await f.Receive("end_call.result", result);
            await f.Receive("incoming_call_state.event", events[2]);
            await f.Receive("dial_request.result", dialResult);
            await f.Receive("incoming_call_state.event", events[2]);
            await f.Receive("incoming_call_state.event", events[1]);
            Check(f.Events.Count == 3, "Duplicate/reordered callback reopened a terminal call");
            await Denied(() => f.End(CallId, 3), "end after idle");
            Check(JsonNode.DeepEquals(f.Store.LocalGrants(), TelefonProtocolContract.DesktopGrants()), "Dial changed global grants");
            if (output is not null) File.WriteAllText(output, new JsonArray(f.Events.Select(e => (JsonNode)e.DeepClone()).ToArray()).ToJsonString());
        }
        foreach (var order in new[] { "result-first", "offhook-first", "idle-first" })
        {
            using var f = new Fixture(); await f.Dial();
            if (order == "result-first") await f.Receive("dial_request.result", dialResult);
            if (order == "result-first") await f.Receive("incoming_call_state.event", events[0]);
            if (order != "idle-first") await f.Receive("incoming_call_state.event", events[1]);
            await f.Receive("incoming_call_state.event", events[2]);
            await f.Receive("incoming_call_state.event", events[0]);
            if (order != "result-first") await f.Receive("dial_request.result", dialResult);
            Check(f.Events.Count == (order == "result-first" ? 3 : order == "offhook-first" ? 2 : 1), order);
            await Denied(() => f.End(CallId, 3), order + " terminal control");
        }
        using (var f = new Fixture())
        {
            f.Store.RememberCommand(PeerId, CallId, Now());
            await f.Receive("dial_request.result", dialResult);
            foreach (var e in events) await f.Receive("incoming_call_state.event", e);
            Check(f.Events.Count == 0 && f.Results.Count == 0, "Durable historic command minted runtime scope");
        }
        using (var f = new Fixture())
        {
            var writer = (SemaphoreSlim)Field(typeof(TelefonConnection), "writer").GetValue(f.Connection)!;
            await writer.WaitAsync(); var dial = f.Dial();
            var early = f.Receive("incoming_call_state.event", events[0]);
            Check(f.Events.Count == 0, "Queued-but-unsent dial accepted lifecycle");
            writer.Release(); await Task.WhenAll(dial, early);
            Check(f.Events.Count == 0, "Pre-send rejection replayed after sending");
        }
        using (var f = new Fixture())
        {
            var writer = (SemaphoreSlim)Field(typeof(TelefonConnection), "writer").GetValue(f.Connection)!;
            await writer.WaitAsync(); var dial = f.Dial();
            var revoke = f.Host.SetGrantAsync(PeerId, "end_call", false);
            writer.Release(); await revoke; await Denied(() => dial, "revocation while waiting to write");
            Check(!f.WireMessages().Any(m => m["kind"]?.GetValue<string>() == "dial_request.command"), "Revoked queued dial was written");
        }
        foreach (var revoke in new[] { "local", "remote", "unpair", "key", "restart", "failed", "expiry", "shutdown" })
        {
            using var f = new Fixture(); await f.Dial();
            if (revoke == "local") await f.Host.SetGrantAsync(PeerId, "end_call", false);
            if (revoke == "remote") { var grants = TelefonProtocolContract.DesktopGrants(); grants["dial_request"] = false;
                await f.Receive("grants.update", new JsonObject { ["revision"] = 10, ["grants"] = grants }); }
            if (revoke == "unpair") await f.Host.RemoveAsync(PeerId);
            if (revoke == "shutdown") await f.Host.SwitchAsync(false);
            if (revoke == "key") f.Store.SavePeers([f.Peer with { PublicKey = Enumerable.Repeat((byte)1, 32).ToArray() }]);
            if (revoke == "restart") Field(typeof(TelefonCoordinator), "pendingDial").SetValue(f.Host, null);
            if (revoke == "failed") await f.Receive("dial_request.result", new JsonObject { ["client_ref"] = CallId, ["state"] = "failed", ["error"] = "os_restricted", ["occurred_ms"] = Now() });
            if (revoke == "expiry") {
                var pending = Field(typeof(TelefonCoordinator), "pendingDial").GetValue(f.Host)!;
                pending.GetType().GetProperty("Deadline")!.SetValue(pending, Environment.TickCount64 - 1);
            }
            if (revoke is not ("unpair" or "shutdown")) await f.Receive("incoming_call_state.event", events[0]);
            else Check((string?)Method(typeof(TelefonCoordinator), "AuthorizeCall").Invoke(f.Host,
                [f.Peer, "incoming_call_state.event", events[0]]) == "not_granted", "Unpaired/stopped authority retained");
            Check(f.Events.Count == 0, "Scope revived after " + revoke);
        }
        using (var old = new Fixture(legacy: true)) {
            await old.Dial(); await old.Receive("incoming_call_state.event", events[0]);
            Check(old.Events.Count == 0, "Legacy peer unexpectedly negotiated scope");
            old.Store.SetLocalGrant("incoming_call_state", true);
            var grants = old.Peer.Grants.DeepClone().AsObject(); grants["incoming_call_state"] = true;
            old.Store.UpdatePeerProtocol(PeerId, 0, null, 20, grants);
            await old.Receive("incoming_call_state.event", events[0]); Check(old.Events.Count == 1, "Legacy explicit global grant stopped working");
        }
        if (trace is not null && output is not null)
        foreach (var name in new[] { "scoped-timeout", "scoped-incoming-collision" })
        {
            var file = Path.Combine(Path.GetDirectoryName(trace)!, name + ".json");
            Check(File.Exists(file), "Missing Android boundary fixture: " + name);
            using var f = new Fixture(); await f.Dial();
            foreach (var value in JsonNode.Parse(File.ReadAllText(file))!.AsArray().OfType<JsonObject>())
                await f.Receive("incoming_call_state.event", value);
            Check(f.Events.Count == 2 && f.Events[1]["state"]?.GetValue<string>() == "idle", name + " terminal not received");
            await Denied(() => f.End(CallId, 2), name + " cannot end incoming or absent call");
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(output)!, "host-" + name + ".json"),
                new JsonArray(f.Events.Select(e => (JsonNode)e.DeepClone()).ToArray()).ToJsonString());
        }
        Console.WriteLine("Scoped outgoing C# host: lifecycle, pending result reorder, exact commands, revoke/unpair/key/expiry/restart, legacy passed.");
        return 0;
    }
}
