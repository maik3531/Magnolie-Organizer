using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorStoreTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-actor-outbox-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var key = Enumerable.Repeat((byte)29, 32).ToArray();
            var store = new TelefonStore(paths, testStorageKey: key);
            var peer = "22222222-2222-4222-8222-222222222222";
            var run = "11111111-1111-4111-8111-111111111111"; var legacyRun = "33333333-3333-4333-8333-333333333333";
            var request = new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            var legacy = request.DeepClone().AsObject(); legacy["run_id"] = legacyRun;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var personal = new PersonalSyncStore(store);
            personal.RememberRun(PersonalSyncActorContract.StoragePeer(run), request, now); personal.RememberRun(peer, legacy, now);
            var actorId = store.Enqueue(peer, "personal_sync.request", request, 60000, now, actorRunId: run);
            var ordinaryId = store.Enqueue(peer, "personal_sync.request", legacy, 60000, now);
            var reopened = new TelefonStore(paths, testStorageKey: key);
            var pending = reopened.Due(peer, now + 1).ToDictionary(item => item.Id);
            var wire = pending[actorId].Message;
            TestAssert.That(wire["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind && wire["message_id"]!.GetValue<string>() == actorId &&
                wire["created_ms"]!.GetValue<long>() == now && wire["expires_ms"]!.GetValue<long>() == now + 60000 &&
                JsonNode.DeepEquals(PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject()).Body, request), "Encrypted actor wire identity/lifetime did not survive queue restart.");
            TestAssert.That(pending[ordinaryId].Message["kind"]!.GetValue<string>() == "personal_sync.request" &&
                JsonNode.DeepEquals(pending[ordinaryId].Message["body"], legacy), "An ordinary GUI queue was converted into actor traffic.");
            using var db = reopened.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT kind,payload FROM outbox WHERE message_id=$id"; read.Parameters.AddWithValue("$id", actorId);
            using var row = read.ExecuteReader(); TestAssert.That(row.Read(), "Actor queue row disappeared.");
            TestAssert.That(row.GetString(0) == "personal_sync.request" && JsonNode.DeepEquals(JsonNode.Parse(reopened.Open("outbox", actorId, (byte[])row[1])), wire),
                "Stored actor marker was only volatile or semantic queue ordering was lost.");
            row.Close(); db.Close();
            TestAssert.Throws<InvalidDataException>(() => reopened.Enqueue(peer, "personal_sync.request", request, 60000, now, actorRunId: legacyRun), "A foreign actor run identity was queued.");
            TestAssert.Throws<InvalidDataException>(() => reopened.Enqueue(peer, "personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000, now, actorRunId: run), "Actor transport admitted control injection.");
            TestAssert.That(reopened.AcknowledgePersonalOutbox(peer, actorId, "rejected", "temporary_failure", now + 2) &&
                JsonNode.DeepEquals(reopened.OutboxMessage(peer, actorId), wire), "A temporary receipt discarded the retained actor marker.");
            TestAssert.That(reopened.AcknowledgePersonalOutbox(peer, actorId, "accepted", "none", now + 3) && reopened.OutboxMessage(peer, actorId) is null &&
                reopened.OutboxMessage(peer, ordinaryId) is not null, "Actor ACK identity changed or removed unrelated GUI traffic.");
            await NoLegacyTransportFallbackAsync(Path.Combine(root, "transport"));
            await PrivateStagingNamespaceAsync(Path.Combine(root, "staging"));
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task NoLegacyTransportFallbackAsync(string root)
    {
        var paths = new WindowsPaths(root); var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)30, 32).ToArray());
        store.Enabled = true;
        var grants = TelefonProtocolContract.DesktopGrants(); grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
        var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned transport fixture", TelefonCrypto.GenerateX25519().Public,
            CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
            GrantRevision: 1, StoredGrants: grants);
        store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
        store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
        var run = Guid.NewGuid().ToString("D"); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var request = new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
        new PersonalSyncStore(store).RememberRun(PersonalSyncActorContract.StoragePeer(run), request, now);
        var id = store.Enqueue(peer.Id, "personal_sync.request", request, 60000, now, actorRunId: run);
        using var stream = new MemoryStream(); using var lifetime = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var legacyReceives = 0;
        using var connection = new TelefonConnection(peer, stream, new byte[16], new byte[72], store,
            (_, _) => { legacyReceives++; return Task.FromResult<TelefonAck?>(null); }, lifetime.Token, "wifi");
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        foreach (var field in new[] { "freshCapabilities", "freshGrants", "freshOwnSettings" })
            typeof(TelefonConnection).GetField(field, flags)!.SetValue(connection, true);
        await connection.PumpOutboxNowAsync();
        TestAssert.That(stream.Length == 0 && store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(item => item.Id == id && item.Attempts == 0),
            "A reserved actor frame fell through the ordinary transport or was consumed before an authorized actor route existed.");
        var wire = store.OutboxMessage(peer.Id, id)!.DeepClone().AsObject(); wire["message_id"] = Guid.NewGuid().ToString("D");
        var start = wire.DeepClone().AsObject(); start["message_id"] = run; start["kind"] = PersonalSyncActorContract.StartKind; start["body"] = PersonalSyncActorContract.Start(run);
        var malformed = wire.DeepClone().AsObject(); malformed["body"] = new JsonObject { ["owned_unclaimed"] = "Must not reach GUI/storage" };
        var markedAck = wire.DeepClone().AsObject(); markedAck["message_id"] = Guid.NewGuid().ToString("D"); markedAck["kind"] = PersonalSyncActorContract.AckKind; markedAck["body"] = PersonalSyncActorContract.Ack(run, id);
        var cancel = wire.DeepClone().AsObject(); cancel["kind"] = PersonalSyncActorContract.CancelKind; cancel["body"] = PersonalSyncActorContract.Cancel(run);
        foreach (var frame in new[] { start, wire, malformed, markedAck, cancel }) await connection.HandlePlainAsync(frame);
        await connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = id, ["status"] = "accepted", ["error"] = "none" });
        TestAssert.That(stream.Length == 0 && legacyReceives == 0, "An unadmitted actor reached legacy receive/callbacks or emitted protocol traffic.");
        TestAssert.That(store.OutboxMessage(peer.Id, id) is not null, "A generic late ACK consumed an unadmitted actor.");
        using (var db = store.OpenDatabase())
        {
            db.Open();
            foreach (var table in new[] { "inbox", "dedupe", "personal_batch", "personal_domain", "personal_attachment_chunk", "personal_attachment_transfer" })
            {
                using var count = db.CreateCommand(); count.CommandText = "SELECT COUNT(*) FROM " + table;
                TestAssert.That(Convert.ToInt64(count.ExecuteScalar()) == 0, "An unadmitted actor entered ordinary staging: " + table);
            }
        }
        await connection.HandlePlainAsync(new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = now });
        TestAssert.That(stream.Length > 0 && legacyReceives == 0, "The actor boundary disabled ordinary heartbeat traffic.");
    }

    private static async Task PrivateStagingNamespaceAsync(string root)
    {
        var paths = new WindowsPaths(root); var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)31, 32).ToArray());
        store.Enabled = false;
        var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned staged source", TelefonCrypto.GenerateX25519().Public); store.SavePeers([peer]);
        var callbacks = new List<string>();
        using var coordinator = new TelefonCoordinator(paths, (name, _) => { callbacks.Add(name); return Task.CompletedTask; }, dataStore: store, localOnly: true);
        var run = Guid.NewGuid().ToString("D"); var storagePeer = PersonalSyncActorContract.StoragePeer(run);
        TestAssert.That(PersonalSyncActorContract.IsStoragePeer(storagePeer) && !TelefonProtocolContract.IsUuidV4(storagePeer) && !PersonalSyncActorContract.IsStoragePeer(peer.Id), "Private actor storage could collide with a paired peer identity.");
        var personal = new PersonalSyncStore(store); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        personal.RememberRun(storagePeer, new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") }, now);
        var body = new JsonObject { ["format"] = 3, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = 0,
            ["last"] = true, ["reply"] = false, ["records_hash"] = PersonalSyncContract.RecordsHash(new JsonArray()), ["records"] = new JsonArray() };
        JsonObject Message(string kind, JsonObject value) => new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = value };
        TestAssert.That(personal.StageBatch(storagePeer, Message("personal_sync.batch", body), "wifi", now) is not null, "Existing batch engine did not stage in the private actor namespace.");
        personal.StageDecisionIntent(storagePeer, Message("personal_sync.deletion_proposals", new JsonObject { ["format"] = 1, ["run_id"] = run,
            ["proposal_batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray() }), "wifi", now);
        await coordinator.ReplayPersonalSyncAsync();
        var reopened = new PersonalSyncStore(new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)31, 32).ToArray()));
        TestAssert.That(callbacks.Count == 0 && !coordinator.McpStatus()["listening"]!.GetValue<bool>() && store.LoadPeers().Single().Id == peer.Id &&
            reopened.ReadyBatches(now + 1).Any(value => value.PeerId == storagePeer) && reopened.DecisionIntents(now + 1).Any(value => value.PeerId == storagePeer),
            "Private actor staging was lost, exposed as a paired peer or replayed through the ordinary GUI.");
    }
}
