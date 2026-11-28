using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonOutboxFairnessTests
{
    internal static async Task RunAsync()
    {
        foreach (var transport in new[] { "wifi", "bluetooth" })
            await HeldActorsAsync(65, transport);
        await HeldActorsAsync(96, "wifi");
        await ControlPriorityAsync();
        await WaitingProducerRawPageAsync();
        await RemovedRowsAsync(false);
        await RemovedRowsAsync(true);
        await NewSessionAndWrapAsync();
        await OrdinaryWaitAsync(SharedSyncSettings.StartKind);
        await OrdinaryWaitAsync(TimeSyncContract.Request);
        await OrdinaryOrderAndTransportAsync();
    }

    private sealed class Fixture : IDisposable
    {
        private readonly string root = Path.Combine(Path.GetTempPath(), "magnolie-outbox-fairness-" + Guid.NewGuid().ToString("N"));
        internal readonly TelefonStore Store;
        internal readonly TelefonPeer Peer;
        internal readonly long Now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1000;
        internal readonly MemoryStream Stream = new();
        internal readonly TelefonConnection Connection;

        internal Fixture(string transport = "wifi")
        {
            Store = new TelefonStore(new WindowsPaths(root), testStorageKey: Enumerable.Repeat((byte)33, 32).ToArray());
            Peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned fairness fixture", TelefonCrypto.GenerateX25519().Public);
            Store.SavePeers([Peer]);
            Connection = NewConnection(Stream, transport);
        }

        internal TelefonConnection NewConnection(Stream stream, string transport = "wifi") =>
            new(Peer, stream, new byte[16], new byte[72], Store, (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, transport);

        internal List<string> Held(int count)
        {
            var run = Guid.NewGuid().ToString("D");
            var request = new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            new PersonalSyncStore(Store).RememberRun(PersonalSyncActorContract.StoragePeer(run), request, Now);
            return Enumerable.Range(0, count).Select(sequence => Store.Enqueue(Peer.Id, "personal_sync.batch",
                new JsonObject { ["format"] = 3, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString("D"),
                    ["sequence"] = sequence, ["last"] = sequence == count - 1, ["reply"] = false,
                    ["records_hash"] = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945", ["records"] = new JsonArray() },
                60000, Now, actorRunId: run)).ToList();
        }

        internal string Status(string policy = "any", long? created = null) => Store.Enqueue(Peer.Id, "device_status.request",
            new JsonObject { ["request_id"] = Guid.NewGuid().ToString("D") }, 60000, created ?? Now, policy);

        internal int Attempts(string id)
        {
            using var db = Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
            query.CommandText = "SELECT attempts FROM outbox WHERE message_id=$id"; query.Parameters.AddWithValue("$id", id);
            return Convert.ToInt32(query.ExecuteScalar());
        }

        public void Dispose()
        {
            Connection.Dispose(); Stream.Dispose();
            using (var pool = Store.OpenDatabase()) SqliteConnection.ClearPool(pool);
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    private static async Task HeldActorsAsync(int count, string transport)
    {
        using var fixture = new Fixture(transport);
        var held = fixture.Held(count); var ordinary = fixture.Status();
        var original = held.ToDictionary(id => id, id => fixture.Store.OutboxMessage(fixture.Peer.Id, id)!.DeepClone());
        for (var cycle = 0; cycle < count / 32; cycle++)
        {
            await fixture.Connection.PumpOutboxNowAsync();
            TestAssert.That(fixture.Stream.Length == 0, "Unadmitted actor data reached the ordinary transport.");
            TestAssert.That(fixture.Store.Due(fixture.Peer.Id, fixture.Now + 1, transport: transport).Select(item => item.Id).SequenceEqual(held.Take(32)),
                "A pump cursor changed the existing read/actor due selection.");
        }
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Stream.Length > 0 && fixture.Attempts(ordinary) == 1, "Held actor pages starved ordinary traffic.");
        TestAssert.That(held.All(id => fixture.Attempts(id) == 0 && JsonNode.DeepEquals(original[id], fixture.Store.OutboxMessage(fixture.Peer.Id, id))),
            "Passing a held actor page sent, consumed or changed its sealed wire envelope.");
    }

    private static async Task ControlPriorityAsync()
    {
        using var fixture = new Fixture(); fixture.Held(64); var ordinary = fixture.Status();
        await fixture.Connection.PumpOutboxNowAsync();
        var control = fixture.Store.Enqueue(fixture.Peer.Id, "grants.update", new JsonObject {
            ["revision"] = 1, ["grants"] = TelefonProtocolContract.DesktopGrants() }, 60000, fixture.Now);
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Attempts(control) == 1 && fixture.Attempts(ordinary) == 0, "A data cursor hid a newly queued priority control.");
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Attempts(ordinary) == 1, "A priority control prevented actor-page progress.");
    }

    private static async Task WaitingProducerRawPageAsync()
    {
        using var fixture = new Fixture(); var pending = new List<string>();
        // Synthetic store metadata exercises the real waiting selector with
        // four eight-frame ledgers. The context payload is deliberately not a
        // protected native owner and is never used as a send grant here.
        using (var db = fixture.Store.OpenDatabase())
        {
            db.Open(); using var create = db.CreateCommand();
            create.CommandText = "CREATE TABLE personal_actor_context(actor_id TEXT PRIMARY KEY,expires_ms INTEGER NOT NULL,payload BLOB NOT NULL)"; create.ExecuteNonQuery();
        }
        for (var owner = 0; owner < 4; owner++)
        {
            var run = Guid.NewGuid().ToString("D"); var frames = new JsonArray();
            for (var sequence = 0; sequence < 8; sequence++)
            {
                var body = new JsonObject { ["format"] = 1, ["run_id"] = run, ["proposal_batch_id"] = Guid.NewGuid().ToString("D"),
                    ["sequence"] = sequence, ["last"] = sequence == 7, ["proposals"] = new JsonArray() };
                var id = fixture.Store.Enqueue(fixture.Peer.Id, "personal_sync.deletion_proposals", body, 60000, fixture.Now, actorRunId: run);
                pending.Add(id); frames.Add(fixture.Store.OutboxMessage(fixture.Peer.Id, id)!.DeepClone());
            }
            var key = $"personal_actor_producer:{PersonalSyncActorContract.StoragePeer(run)}:{run}";
            var ledger = new JsonObject { ["expires_ms"] = fixture.Now + 60000, ["frames"] = frames };
            using var db = fixture.Store.OpenDatabase(); db.Open(); using var insert = db.CreateCommand();
            insert.CommandText = "INSERT INTO personal_actor_context VALUES($run,$expiry,$context); INSERT INTO meta(key,value) VALUES($key,$ledger)";
            insert.Parameters.AddWithValue("$run", run); insert.Parameters.AddWithValue("$expiry", fixture.Now + 60000);
            insert.Parameters.AddWithValue("$context", new byte[] { 0 }); insert.Parameters.AddWithValue("$key", key);
            insert.Parameters.AddWithValue("$ledger", fixture.Store.Seal("personal_actor_producer", key, TelefonCrypto.Canonical(ledger)));
            insert.ExecuteNonQuery();
        }
        var ordinary = fixture.Status();
        await fixture.Connection.PumpOutboxNowAsync(); await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Attempts(ordinary) == 1 && pending.All(id => fixture.Attempts(id) == 0 && fixture.Store.OutboxMessage(fixture.Peer.Id, id) is not null),
            "Waiting producers either starved ordinary traffic or lost their retained frames.");
    }

    private static async Task RemovedRowsAsync(bool corrupt)
    {
        using var fixture = new Fixture(); fixture.Held(31);
        var run = Guid.NewGuid().ToString("D");
        var invalid = fixture.Store.Enqueue(fixture.Peer.Id, "personal_sync.request", new JsonObject {
            ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") }, 60000, fixture.Now);
        if (corrupt)
        {
            using var db = fixture.Store.OpenDatabase(); db.Open(); using var update = db.CreateCommand();
            update.CommandText = "UPDATE outbox SET payload=$bad WHERE message_id=$id";
            update.Parameters.AddWithValue("$bad", new byte[] { 1, 2, 3 }); update.Parameters.AddWithValue("$id", invalid); update.ExecuteNonQuery();
        }
        var ordinary = fixture.Status();
        await fixture.Connection.PumpOutboxNowAsync(); await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Store.OutboxMessage(fixture.Peer.Id, invalid) is null && fixture.Attempts(ordinary) == 1,
            "A deleted invalid row pinned the actor window or escaped existing cleanup.");
    }

    private static async Task NewSessionAndWrapAsync()
    {
        using var fixture = new Fixture(); var held = fixture.Held(32); var ordinary = fixture.Status();
        await fixture.Connection.PumpOutboxNowAsync();
        using var stream = new MemoryStream(); using var second = fixture.NewConnection(stream);
        await second.PumpOutboxNowAsync();
        TestAssert.That(stream.Length == 0, "A fresh connection inherited another session's cursor.");
        foreach (var id in held.Append(ordinary)) fixture.Store.CompleteOutbox(fixture.Peer.Id, id);
        var replacement = fixture.Status(created: fixture.Now - 1000);
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Attempts(replacement) == 0, "The end-wrap fixture did not exercise an exhausted cursor.");
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Attempts(replacement) == 1, "A deleted page or earlier timestamp stranded the connection cursor.");
    }

    private static async Task OrdinaryWaitAsync(string kind)
    {
        using var fixture = new Fixture();
        for (var index = 0; index < 32; index++)
        {
            var body = kind == SharedSyncSettings.StartKind
                ? new JsonObject { ["format"] = 9, ["request_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual" }
                : new JsonObject { ["format"] = 7, ["sender_epoch"] = Guid.NewGuid().ToString("D"), ["receiver_epoch"] = Guid.NewGuid().ToString("D"),
                    ["sender_revision"] = 1, ["receiver_revision"] = 1, ["trigger"] = "manual" };
            fixture.Store.Enqueue(fixture.Peer.Id, kind, body, 60000, fixture.Now);
        }
        var ordinary = fixture.Status();
        for (var round = 0; round < 3; round++) await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(fixture.Stream.Length == 0 && fixture.Attempts(ordinary) == 0,
            "The actor-only window silently widened an ordinary shared/time policy wait.");
    }

    private static async Task OrdinaryOrderAndTransportAsync()
    {
        using var fixture = new Fixture("bluetooth");
        var wifi = fixture.Status("wifi_only"); var ordinary = Enumerable.Range(0, 40).Select(_ => fixture.Status()).ToList();
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(ordinary.Take(32).All(id => fixture.Attempts(id) == 1) && ordinary.Skip(32).All(id => fixture.Attempts(id) == 0),
            "The bounded sender changed ordinary same-timestamp FIFO or exceeded 32 attempts.");
        await fixture.Connection.PumpOutboxNowAsync();
        TestAssert.That(ordinary.All(id => fixture.Attempts(id) == 1) && fixture.Attempts(wifi) == 0,
            "The sender changed ordinary progress or persistent wifi_only protection.");
    }
}
