using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraParentTests
{
    private static JsonObject Message(string op = "probe", string kind = PhoneCameraControl.Request)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60_000,
            ["body"] = new JsonObject { ["version"] = 24, ["request_id"] = Guid.NewGuid().ToString("D"), ["nonce"] = new string('a', 64), ["op"] = op } };
    }

    private static JsonObject Reply()
    {
        var message = Message("unavailable", PhoneCameraControl.Report);
        message["body"]!["reason"] = "unsupported";
        return message;
    }

    private sealed class Fixture : IDisposable
    {
        private readonly string root = Path.Combine(Path.GetTempPath(), "magnolie-camera-parent-" + Guid.NewGuid().ToString("N"));
        private readonly TcpClient desktop;
        private readonly TcpClient phone;
        private readonly CancellationTokenSource deadline = new(TimeSpan.FromSeconds(10));
        internal readonly TelefonStore Store;
        internal readonly TelefonPeer Peer = new(Guid.NewGuid().ToString("D"), "Controlled original parent", new byte[32]);
        internal readonly TelefonConnection Connection;
        internal int LegacyReceives;
        internal SemaphoreSlim Writer => (SemaphoreSlim)typeof(TelefonConnection).GetField("writer", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(Connection)!;
        internal bool HasUnexpectedFrame => phone.GetStream().DataAvailable;
        internal Fixture(string transport = "wifi")
        {
            var paths = new WindowsPaths(root); Store = new TelefonStore(paths, new byte[32]);
            var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
            try
            {
                phone = new TcpClient(); phone.Connect((IPEndPoint)listener.LocalEndpoint);
                desktop = listener.AcceptTcpClient();
            }
            finally { listener.Stop(); }
            Connection = new TelefonConnection(Peer, desktop.GetStream(), new byte[16],
                Enumerable.Range(0, 72).Select(value => (byte)value).ToArray(), Store,
                (_, _) => { LegacyReceives++; return Task.FromResult<TelefonAck?>(null); }, deadline.Token, transport);
        }
        internal async Task Send(JsonObject message, long sequence)
        {
            var header = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["sid"] = Convert.ToBase64String(new byte[16]), ["seq"] = sequence, ["dir"] = "phone_to_desktop" };
            var clear = TelefonCrypto.Canonical(message); var encrypted = new byte[clear.Length]; var tag = new byte[16];
            var nonce = Enumerable.Range(32, 4).Select(value => (byte)value).Concat(new byte[8]).ToArray();
            System.Buffers.Binary.BinaryPrimitives.WriteInt64BigEndian(nonce.AsSpan(4), sequence);
            using var aes = new AesGcm(Enumerable.Range(0, 32).Select(value => (byte)value).ToArray(), 16);
            aes.Encrypt(nonce, clear, encrypted, tag, TelefonCrypto.Canonical(header));
            header["ciphertext"] = Convert.ToBase64String(encrypted.Concat(tag).ToArray());
            await TelefonCoordinator.WriteFrameAsync(phone.GetStream(), header, deadline.Token);
        }
        internal void NoPersistentControls()
        {
            using var db = Store.OpenDatabase(); db.Open(); using var count = db.CreateCommand();
            count.CommandText = "SELECT (SELECT COUNT(*) FROM outbox)+(SELECT COUNT(*) FROM inbox)+(SELECT COUNT(*) FROM dedupe)";
            TestAssert.That((long)count.ExecuteScalar()! == 0 && LegacyReceives == 0, "Webcam entered legacy callbacks/history/dedupe/outbox");
        }
        internal async Task<JsonObject> Read(long expectedSequence)
        {
            var frame = await TelefonCoordinator.ReadFrameAsync(phone.GetStream(), 8192, deadline.Token);
            TestAssert.That(frame["seq"]!.GetValue<long>() == expectedSequence &&
                frame["sid"]!.GetValue<string>() == Convert.ToBase64String(new byte[16]) &&
                frame["dir"]!.GetValue<string>() == "desktop_to_phone", "Wrong original crypto envelope");
            var header = frame.DeepClone().AsObject(); header.Remove("ciphertext");
            var ciphertext = Convert.FromBase64String(frame["ciphertext"]!.GetValue<string>());
            var clear = new byte[ciphertext.Length - 16];
            var nonce = Enumerable.Range(68, 4).Select(value => (byte)value).Concat(new byte[8]).ToArray();
            System.Buffers.Binary.BinaryPrimitives.WriteInt64BigEndian(nonce.AsSpan(4), expectedSequence);
            using var aes = new AesGcm(Enumerable.Range(36, 32).Select(value => (byte)value).ToArray(), 16);
            aes.Decrypt(nonce, ciphertext.AsSpan(0, clear.Length), ciphertext.AsSpan(clear.Length), clear, TelefonCrypto.Canonical(header));
            return JsonNode.Parse(clear)!.AsObject();
        }
        public void Dispose()
        {
            Connection.Dispose(); desktop.Dispose(); phone.Dispose(); deadline.Dispose();
            // Windows retains the SQLite file through this fixture's pooled
            // connections. Release only the exact OWN pool, never global pools.
            using (var ownPool = Store.OpenDatabase()) Microsoft.Data.Sqlite.SqliteConnection.ClearPool(ownPool);
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    internal static Task SchemaAsync()
    {
        var probe = Message();
        PhoneCameraControl.ValidateMessage(probe, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        foreach (var version in new JsonNode[] { JsonValue.Create("24")!, JsonValue.Create(24.0)!, JsonValue.Create(true)! })
        {
            var invalid = probe.DeepClone().AsObject(); invalid["body"]!["version"] = version;
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraControl.ValidateMessage(invalid, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), "Version alias admitted");
        }
        foreach (var mutate in new Action<JsonObject>[] {
            value => value["body"]!["url"] = "http://phone/camera",
            value => value["kind"] = PhoneCameraControl.Report,
            value => value["body"]!["nonce"] = new string('A', 64),
            value => value["body"]!["request_id"] = Guid.Empty.ToString("D"),
            value => value["expires_ms"] = value["created_ms"]!.GetValue<long>() + 60_001,
            value => value["expires_ms"] = value["created_ms"]!.GetValue<long>() - 1,
            value => value["body"]!["padding"] = new string('a', 4096) })
        {
            var invalid = probe.DeepClone().AsObject(); mutate(invalid);
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraControl.ValidateMessage(invalid, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), "Malformed/oversized envelope admitted");
        }
        var offer = Message("offer", PhoneCameraControl.Report); var body = offer["body"]!.AsObject();
        body["session"] = new string('b', 32); body["secret"] = new string('c', 64); body["port"] = 24401; body["muted"] = false; body["front"] = true;
        PhoneCameraControl.ValidateMessage(offer, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        body["muted"] = 1;
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraControl.ValidateMessage(offer, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), "Numeric mute admitted");
        return Task.CompletedTask;
    }

    internal static async Task OriginalWriterAsync()
    {
        using var fixture = new Fixture();
        var message = Reply();
        await fixture.Connection.SendWebcamEphemeralAsync(message, () => { });
        TestAssert.That(JsonNode.DeepEquals(message, await fixture.Read(0)), "Original ephemeral cipher differs");
        var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = 123 };
        await fixture.Connection.SendPlainAsync(ping);
        TestAssert.That(JsonNode.DeepEquals(ping, await fixture.Read(1)), "Ordinary writer no longer shares original sequence");
        TestAssert.That(fixture.Store.OutboxMessage(fixture.Peer.Id, message["message_id"]!.GetValue<string>()) is null,
            "Ephemeral control was persisted");
    }

    internal static async Task BoundedAdmissionAsync()
    {
        using var fixture = new Fixture();
        await fixture.Writer.WaitAsync();
        try
        {
            await TestAssert.ThrowsAsync<OperationCanceledException>(() => fixture.Connection.SendWebcamEphemeralAsync(Reply(), () => { }), "Writer admission not bounded");
        }
        finally { fixture.Writer.Release(); }
        TestAssert.That(!fixture.HasUnexpectedFrame, "Busy writer emitted a control");
        var healthy = Reply(); await fixture.Connection.SendWebcamEphemeralAsync(healthy, () => { });
        TestAssert.That(JsonNode.DeepEquals(healthy, await fixture.Read(0)), "Busy admission consumed counter/closed healthy original parent");
    }

    internal static async Task RevocationAndSnapshotAsync()
    {
        using var fixture = new Fixture();
        var checks = 0;
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => fixture.Connection.SendWebcamEphemeralAsync(Reply(),
            () => { if (++checks == 3) throw new InvalidOperationException("original owner retired after encryption"); }), "Late original guard not rechecked");
        TestAssert.That(checks == 3 && !fixture.HasUnexpectedFrame, "Prepublication rejection emitted bytes");
        var original = Reply(); var expected = original.DeepClone();
        await fixture.Writer.WaitAsync();
        var sending = fixture.Connection.SendWebcamEphemeralAsync(original, () => { });
        original["body"]!["nonce"] = new string('d', 64);
        fixture.Writer.Release(); await sending;
        TestAssert.That(JsonNode.DeepEquals(expected, await fixture.Read(0)), "Late caller mutation replaced original captured control");
    }

    internal static async Task PostWriteRevocationAsync()
    {
        using var fixture = new Fixture();
        await TestAssert.ThrowsAsync<InvalidDataException>(() => fixture.Connection.SendWebcamEphemeralAsync(Message(), () => { }), "Desktop wrote a phone-role REQUEST");
        var checks = 0; var message = Reply();
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => fixture.Connection.SendWebcamEphemeralAsync(message,
            () => { if (++checks == 4) throw new InvalidOperationException("original owner revoked during IO"); }), "Publication reported ready after owner revocation");
        TestAssert.That(checks == 4 && JsonNode.DeepEquals(message, await fixture.Read(0)), "Did not reach actual ciphertext IO before retirement");
        await TestAssert.ThrowsAsync<Exception>(() => fixture.Connection.SendPlainAsync(new JsonObject { ["type"] = "ping" }), "Uncertain original parent remained writable");
    }

    internal static async Task AuthenticatedIncomingAsync()
    {
        using var fixture = new Fixture(); using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var retired = 0;
        using var owner = fixture.Connection.BindWebcamControl(() => { }, () => retired++);
        var run = fixture.Connection.RunAsync();
        try
        {
            var probe = Message(); await fixture.Send(probe, 0);
            var ack = await fixture.Read(0);
            TestAssert.That(ack["type"]!.GetValue<string>() == "ack" && ack["status"]!.GetValue<string>() == "accepted" &&
                ack["message_id"]!.GetValue<string>() == probe["message_id"]!.GetValue<string>(), "Actual authenticated dispatcher did not ACK queued control");
            var received = await owner.ReadAsync(timeout.Token);
            TestAssert.That(JsonNode.DeepEquals(probe, received), "Original parent control changed on handoff");
            fixture.NoPersistentControls();
            await fixture.Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" }, 1);
            await run.WaitAsync(timeout.Token);
            TestAssert.Throws<InvalidOperationException>(owner.RequireCurrent, "Closed original parent left native owner usable");
            TestAssert.That(owner.IsRetired && retired == 1, "Original owner not retired exactly once");
        }
        finally
        {
            fixture.Connection.Dispose();
            try { await run.WaitAsync(timeout.Token); } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
        }
    }

    internal static async Task ReservedRejectionAndStorageAsync()
    {
        foreach (var transport in new[] { "wifi", "bluetooth" })
        {
            using var fixture = new Fixture(transport);
            await fixture.Connection.HandlePlainAsync(Message());
            var rejected = await fixture.Read(0);
            TestAssert.That(rejected["status"]!.GetValue<string>() == "rejected" && rejected["error"]!.GetValue<string>() == "not_granted", "Missing native owner did not reject ephemerally");
            await fixture.Connection.HandlePlainAsync(Reply());
            var role = await fixture.Read(1);
            TestAssert.That(role["error"]!.GetValue<string>() == "invalid_schema", "Phone REPORT role admitted");
            fixture.NoPersistentControls();
        }
        using var storage = new Fixture();
        foreach (var version in new JsonNode[] { JsonValue.Create(24)!, JsonValue.Create("24")!, JsonValue.Create(24.0)! })
        {
            var value = Message(); value["body"]!["version"] = version;
            TestAssert.That(PhoneCameraControl.IsReserved(value), "Reserved version alias fell through");
            TestAssert.Throws<InvalidDataException>(() => storage.Store.Enqueue(storage.Peer.Id, PhoneCameraControl.Request, value["body"]!.AsObject(), 1000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), "Reserved control entered durable outbox");
            TestAssert.Throws<InvalidDataException>(() => storage.Store.CommitIncoming(storage.Peer.Id, value, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), (_, _) => null), "Reserved rejection entered durable dedupe");
        }
        storage.NoPersistentControls();
    }

    private static JsonObject Follow(JsonObject probe, string op, string session = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    {
        var value = Message(op); value["body"]!["request_id"] = probe["body"]!["request_id"]!.DeepClone();
        value["body"]!["nonce"] = probe["body"]!["nonce"]!.DeepClone(); value["body"]!["session"] = session; return value;
    }

    internal static async Task BoundedInboxAsync()
    {
        using var fixture = new Fixture(); using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var retired = 0; using var owner = fixture.Connection.BindWebcamControl(() => { }, () => retired++);
        var probe = Message(); await fixture.Connection.HandlePlainAsync(probe); await fixture.Read(0);
        await owner.ReadAsync(deadline.Token); owner.BindSession(new string('b', 32));
        for (int i = 0; i < 5; ++i)
        {
            await fixture.Connection.HandlePlainAsync(Follow(probe, "prepared"));
            var ack = await fixture.Read(i + 1);
            TestAssert.That(ack["status"]!.GetValue<string>() == (i < 4 ? "accepted" : "rejected"), "Four-control queue bound not enforced");
        }
        TestAssert.That(owner.IsRetired && retired == 1, "Queue overflow did not retire original owner");
        await fixture.Connection.SendPlainAsync(new JsonObject { ["type"] = "ping" }); await fixture.Read(6);
        fixture.NoPersistentControls();
    }

    internal static async Task ReplayAndOldOwnerAsync()
    {
        using var fixture = new Fixture(); using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var oldRetired = 0; var newRetired = 0;
        using var old = fixture.Connection.BindWebcamControl(() => { }, () => oldRetired++);
        var probe = Message(); await fixture.Connection.HandlePlainAsync(probe); await fixture.Read(0); await old.ReadAsync(deadline.Token);
        var report = Reply(); report["body"]!["request_id"] = probe["body"]!["request_id"]!.DeepClone(); report["body"]!["nonce"] = probe["body"]!["nonce"]!.DeepClone();
        await old.SendAsync(report); await fixture.Read(1); old.Dispose();
        using var current = fixture.Connection.BindWebcamControl(() => { }, () => newRetired++);
        await fixture.Connection.HandlePlainAsync(probe);
        TestAssert.That((await fixture.Read(2))["status"]!.GetValue<string>() == "rejected", "Old probe rebound to replacement owner");
        await fixture.Connection.HandlePlainAsync(Follow(probe, "stop"));
        TestAssert.That((await fixture.Read(3))["status"]!.GetValue<string>() == "rejected" && !current.IsRetired, "Foreign old STOP retired new owner");
        await fixture.Connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = report["message_id"]!.DeepClone(), ["status"] = "rejected", ["error"] = "temporary_failure" });
        TestAssert.That(!current.IsRetired && oldRetired == 1 && newRetired == 0, "Old rejected ACK touched replacement or retried");
        var fresh = Message(); fresh["body"]!["nonce"] = new string('d', 64);
        await fixture.Connection.HandlePlainAsync(fresh); var accepted = await fixture.Read(4);
        TestAssert.That(accepted["status"]!.GetValue<string>() == "accepted", "Fresh original replacement probe refused");
        await current.ReadAsync(deadline.Token);
        await fixture.Connection.HandlePlainAsync(fresh);
        TestAssert.That((await fixture.Read(5))["status"]!.GetValue<string>() == "rejected", "Duplicate native control was replayed");
        var currentReport = Reply(); currentReport["body"]!["request_id"] = fresh["body"]!["request_id"]!.DeepClone(); currentReport["body"]!["nonce"] = fresh["body"]!["nonce"]!.DeepClone();
        await current.SendAsync(currentReport); await fixture.Read(6);
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = currentReport["message_id"]!.DeepClone(), ["status"] = "accepted", ["error"] = "none" };
        await fixture.Connection.HandlePlainAsync(ack); ack["status"] = "rejected"; ack["error"] = "temporary_failure";
        await fixture.Connection.HandlePlainAsync(ack);
        TestAssert.That(!current.IsRetired && newRetired == 0, "Contradictory duplicate ACK replayed retirement");
        fixture.NoPersistentControls();
    }

    internal static async Task OwnerRevocationAndBoundedAckAsync()
    {
        using var fixture = new Fixture(); var current = true; var retired = 0;
        using var owner = fixture.Connection.BindWebcamControl(() => { if (!current) throw new InvalidOperationException("Original native UI authority lost"); }, () => retired++);
        current = false; await fixture.Connection.HandlePlainAsync(Message());
        TestAssert.That((await fixture.Read(0))["status"]!.GetValue<string>() == "rejected" && owner.IsRetired && retired == 1, "Original authority loss did not reject/retire");
        current = true; TestAssert.Throws<InvalidOperationException>(owner.RequireCurrent, "Restored flag revived old owner");
        await fixture.Writer.WaitAsync();
        try { await TestAssert.ThrowsAsync<OperationCanceledException>(() => fixture.Connection.HandlePlainAsync(Message()), "Ephemeral ACK writer admission unbounded"); }
        finally { fixture.Writer.Release(); }
        TestAssert.That(!fixture.HasUnexpectedFrame, "Timed-out ACK published");
        await fixture.Connection.SendPlainAsync(new JsonObject { ["type"] = "ping" }); await fixture.Read(1);
        fixture.NoPersistentControls();
    }

    internal static Task BrokenRetirementCallbackAsync()
    {
        using var fixture = new Fixture();
        var owner = fixture.Connection.BindWebcamControl(() => { }, () => throw new IOException("controlled retirement callback failure"));
        fixture.Connection.Dispose();
        TestAssert.That(owner.IsRetired && owner.RetirementError is IOException, "Broken native retirement prevented parent cleanup or lost its failure");
        return Task.CompletedTask;
    }
}
