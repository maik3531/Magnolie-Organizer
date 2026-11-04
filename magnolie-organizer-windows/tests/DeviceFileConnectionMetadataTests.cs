using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionMetadataTests
{
    internal sealed class ProbeStream : MemoryStream
    {
        internal bool Fail;
        internal Action? BeforeWrite;
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            BeforeWrite?.Invoke();
            if (Fail) throw new IOException("Synthetic secure ACK write failure");
            return base.WriteAsync(buffer, cancellationToken);
        }
        // Only the fixture permits retry after the actual transport writer's
        // Dispose-on-failure. Production sockets are never kept alive this way.
        protected override void Dispose(bool disposing) { }
    }

    internal sealed class Fixture : IDisposable
    {
        private readonly string root = Path.Combine(Path.GetTempPath(), "file-metadata-ack-" + Guid.NewGuid().ToString("N"));
        internal readonly TelefonStore Store;
        internal readonly WindowsPaths Paths;
        internal readonly TelefonPeer Peer;
        internal readonly ProbeStream Stream = new();
        internal readonly TelefonConnection Connection;
        internal bool Reject;
        internal Action? DuringReceive;
        internal Fixture()
        {
            Paths = new(root);
            Store = new(Paths, Enumerable.Repeat((byte)29, 32).ToArray());
            Store.Enabled = true;
            Peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)13, 32).ToArray(),
                FilePairingEpoch: new string('e', 64));
            Store.SavePeers([Peer]);
            Connection = NewConnection(Stream);
        }
        internal TelefonConnection NewConnection(Stream stream) => new(Peer, stream, new byte[16], new byte[72], Store,
            (_, message) => {
                DuringReceive?.Invoke();
                var kind = message["kind"]!.GetValue<string>(); var body = message["body"]!.AsObject();
                if (Reject) return Task.FromResult<TelefonAck?>(new(message["message_id"]!.GetValue<string>(), "rejected", "not_granted"));
                if (kind == "capabilities.update") Store.UpdatePeerProtocol(Peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null);
                if (kind == "grants.update") Store.UpdatePeerProtocol(Peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject());
                return Task.FromResult<TelefonAck?>(null);
            }, CancellationToken.None, "wifi");
        internal JsonObject Message(string kind, long revision = 1, bool video = true, bool own = true)
        {
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            JsonObject body = kind switch
            {
                "capabilities.update" => TelefonProtocolContract.DesktopCapabilities(),
                "grants.update" => new() { ["revision"] = revision, ["grants"] = Store.LocalGrants().DeepClone() },
                _ => new() { ["format"] = 1, ["own_device"] = own }
            };
            if (kind == "capabilities.update")
            {
                body["revision"] = revision;
                body["items"]!["device_status"]!["versions"] = video ? new JsonArray(1, 21, 22) : new JsonArray(1, 21);
            }
            return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
        }
        internal async Task SeedAsync()
        {
            foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
                await Connection.HandlePlainAsync(Message(kind));
            TestAssert.That(Connection.FileMetadataReady() && Connection.FileMetadataReady(videos: true), "Successful current secure metadata ACKs did not establish the read-only witness.");
        }
        public void Dispose()
        {
            Connection.Dispose(); Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    internal static async Task SecureAckAsync()
    {
        foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
        {
            using var fixture = new Fixture(); var connection = fixture.Connection;
            TestAssert.That(!connection.FileMetadataReady(), "Cached pairing created current-channel metadata authority.");
            await fixture.SeedAsync();
            var current = fixture.Message(kind, 2);
            fixture.DuringReceive = () => TestAssert.That(!connection.FileMetadataReady(), "Native callback observed authority before ACK.");
            fixture.Stream.BeforeWrite = () => TestAssert.That(!connection.FileMetadataReady(), "Metadata became current before secure ACK write completion.");
            fixture.Stream.Fail = true;
            try { await connection.HandlePlainAsync(current); throw new Exception("Synthetic ACK write failure did not reach the real writer."); }
            catch (IOException) { }
            TestAssert.That(!connection.FileMetadataReady(), "Failed secure ACK retained its old positive witness: " + kind);
            fixture.Stream.Fail = false;
            await connection.HandlePlainAsync(current); // Exact matching duplicate after durable commit, fresh ACK now succeeds.
            fixture.Stream.BeforeWrite = null;
            if (kind == "personal_sync.settings")
            {
                TestAssert.That(!connection.FileMetadataReady(), "A different historical own-device duplicate silently reconsented after failed ACK.");
                await connection.HandlePlainAsync(fixture.Message(kind));
            }
            TestAssert.That(connection.FileMetadataReady(videos: true), "Successful exact duplicate ACK did not restore its current receipt: " + kind);
            using var reconnect = fixture.NewConnection(new MemoryStream());
            TestAssert.That(!reconnect.FileMetadataReady(), "A new channel inherited persisted or another owner's ACK receipts.");
        }
    }

    internal static async Task WithdrawalAsync()
    {
        using var fixture = new Fixture(); var connection = fixture.Connection;
        await fixture.SeedAsync();
        var oldCapabilities = fixture.Message("capabilities.update", 2, video: false);
        await connection.HandlePlainAsync(oldCapabilities);
        TestAssert.That(connection.FileMetadataReady() && !connection.FileMetadataReady(videos: true), "Video-only capability withdrawal destroyed base metadata or retained video.");
        var fresh = fixture.Message("capabilities.update", 3);
        await connection.HandlePlainAsync(fresh);
        TestAssert.That(connection.FileMetadataReady(videos: true), "Fresh video capability ACK did not restore availability.");
        await connection.HandlePlainAsync(oldCapabilities);
        TestAssert.That(!connection.FileMetadataReady(), "Superseded duplicate became a current metadata receipt.");
        await connection.HandlePlainAsync(fresh);
        TestAssert.That(connection.FileMetadataReady(videos: true), "Exact current duplicate did not renew the ACK witness.");
        var positiveOwn = fixture.Message("personal_sync.settings");
        await connection.HandlePlainAsync(positiveOwn);
        await connection.HandlePlainAsync(fixture.Message("personal_sync.settings", own: false));
        TestAssert.That(!connection.FileMetadataReady(), "Explicit remote own-device withdrawal retained metadata authority.");
        await connection.HandlePlainAsync(positiveOwn);
        TestAssert.That(!connection.FileMetadataReady(), "Historical positive own-device replay undid withdrawal.");
        await connection.HandlePlainAsync(fixture.Message("personal_sync.settings"));
        TestAssert.That(connection.FileMetadataReady(), "Fresh positive own-device metadata failed to reestablish witness.");
        fixture.Reject = true;
        await connection.HandlePlainAsync(fixture.Message("grants.update", 2));
        TestAssert.That(!connection.FileMetadataReady(), "Rejected native callback left a positive grant receipt.");
        fixture.Reject = false;
        await connection.HandlePlainAsync(fixture.Message("grants.update", 3));
        TestAssert.That(connection.FileMetadataReady(), "Fresh granted revision failed.");
        fixture.Store.SavePeers([fixture.Store.LoadPeers().Single() with { FilePairingEpoch = new string('a', 64) }]);
        TestAssert.That(!connection.FileMetadataReady(), "Same-key new pairing inherited old-channel receipts.");
        fixture.Store.SavePeers([fixture.Store.LoadPeers().Single() with { FilePairingEpoch = fixture.Peer.FilePairingEpoch,
            PublicKey = Enumerable.Repeat((byte)14, 32).ToArray() }]);
        TestAssert.That(!connection.FileMetadataReady(), "Replaced peer key inherited old metadata receipts.");
        fixture.Store.SavePeers([fixture.Store.LoadPeers().Single() with { PublicKey = fixture.Peer.PublicKey }]);
        foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
            await connection.HandlePlainAsync(fixture.Message(kind, 4));
        TestAssert.That(!connection.FileMetadataReady(), "Restoring an old pairing revived a revoked channel.");
        connection.Dispose();
        TestAssert.That(!connection.FileMetadataReady(), "Disposed connection retained metadata witness.");
    }

    internal static async Task ChangedDuringAckAsync()
    {
        using var fixture = new Fixture(); await fixture.SeedAsync();
        var update = fixture.Message("capabilities.update", 2);
        fixture.Stream.BeforeWrite = () => fixture.Store.SavePeers([fixture.Store.LoadPeers().Single() with { FilePairingEpoch = new string('a', 64) }]);
        await fixture.Connection.HandlePlainAsync(update);
        TestAssert.That(!fixture.Connection.FileMetadataReady(), "Pairing replacement during real secure ACK became authority.");
    }

    internal static async Task FailedWithdrawalAckAsync()
    {
        using var fixture = new Fixture(); await fixture.SeedAsync();
        var positive = fixture.Message("personal_sync.settings");
        await fixture.Connection.HandlePlainAsync(positive);
        fixture.Stream.Fail = true;
        try { await fixture.Connection.HandlePlainAsync(fixture.Message("personal_sync.settings", own: false)); throw new Exception("Missing fixture ACK fault."); }
        catch (IOException) { }
        fixture.Stream.Fail = false;
        await fixture.Connection.HandlePlainAsync(positive);
        TestAssert.That(!fixture.Connection.FileMetadataReady(), "Failed withdrawal ACK allowed historical positive reconsent.");
        await fixture.Connection.HandlePlainAsync(fixture.Message("personal_sync.settings"));
        TestAssert.That(fixture.Connection.FileMetadataReady(), "Fresh native own-device control could not reconsent.");
    }

    internal static async Task DurableChangesAsync()
    {
        foreach (var change in new[] { "key", "pairing", "unpaired", "disabled", "legacy" })
        {
            using var fixture = new Fixture(); await fixture.SeedAsync();
            var before = fixture.Store.LoadPeers().Single();
            var changed = change switch {
                "key" => before with { PublicKey = Enumerable.Repeat((byte)14, 32).ToArray() },
                "pairing" => before with { FilePairingEpoch = new string('a', 64) },
                "unpaired" => before with { State = "pair_commit_pending" },
                "legacy" => before with { FilePairingEpoch = null }, _ => before
            };
            fixture.Store.SavePeers([changed]);
            if (change == "disabled") fixture.Store.Enabled = false;
            TestAssert.That(!fixture.Connection.FileMetadataReady(), "Durable channel withdrawal retained readiness: " + change);
            fixture.Store.SavePeers([before]); fixture.Store.Enabled = true;
            TestAssert.That(!fixture.Connection.FileMetadataReady(), "Restored state revived revoked channel: " + change);
        }
        using var metadata = new Fixture(); await metadata.SeedAsync();
        var original = metadata.Store.LoadPeers().Single();
        metadata.Store.UpdatePeerProtocol(original.Id, original.CapabilityRevision + 1, original.Capabilities, 0, null);
        TestAssert.That(!metadata.Connection.FileMetadataReady(), "A saved revision alone replaced the secure ACK receipt.");
        metadata.Store.SavePeers([original]);
        TestAssert.That(!metadata.Connection.FileMetadataReady(), "Restoring saved metadata revived an invalidated ACK receipt.");
    }
}
