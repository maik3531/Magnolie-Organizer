using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorRegistryTests
{
    private const string Peer = "11111111-1111-4111-8111-111111111111", Run = "22222222-2222-4222-8222-222222222222", Message = "33333333-3333-4333-8333-333333333333";
    private const string Fingerprint = "ABCD-1234-5678-90EF";

    internal static Task RunAsync()
    {
        foreach (var scenario in new[] { "reopen", "wrong_owner", "epoch", "revoke", "cancel", "expiry", "conflict", "put_race", "read_race", "lease_tamper", "capacity", "wall_rollback", "cross_context", "ttl",
            "reap_wall", "reap_monotonic", "reap_epoch", "reap_source", "reap_failure", "reap_restore" })
            Exercise(scenario);
        return Task.CompletedTask;
    }

    private static void Exercise(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-actor-registry-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)33, 32).ToArray());
            var revision = new string('a', 64); var calls = 0; int? failAt = null; long wall = 1700000000000, monotonic = 1000000;
            string? Current(string peer, string fingerprint)
            {
                calls++; if (failAt is not null && calls >= failAt) return null;
                return peer == Peer && fingerprint == Fingerprint ? revision : null;
            }
            var registry = new PersonalSyncActorStore(store, Current, clock: () => wall, monotonicClock: () => monotonic);
            var handle = registry.Create(Peer, Fingerprint, revision, Run);
            TestAssert.That(!handle.ToString().Contains(handle.OwnerToken, StringComparison.Ordinal), "Owner token leaked through handle formatting.");
            var original = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Message, ["kind"] = "personal_sync.request", ["created_ms"] = wall,
                ["expires_ms"] = wall + 60000, ["body"] = new JsonObject { ["format"] = 3, ["run_id"] = Run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") } };
            var wire = PersonalSyncActorContract.WireMessage(original, Run);
            if (scenario == "put_race")
            {
                failAt = calls + 2; Expect("actor_source_changed", () => registry.Put(handle, wire));
                TestAssert.That(registry.Status(handle)["packets"]!.GetValue<int>() == 0 && registry.Status(handle)["phase"]!.GetValue<string>() == "registered", "Revoked source left a partial raw packet/binding update.");
                return;
            }
            if (scenario == "ttl")
            {
                wire["expires_ms"] = wall + 3600001;
                TestAssert.Throws<InvalidDataException>(() => registry.Put(handle, wire), "Raw storage extended the existing request lifetime.");
                var ack = original.DeepClone().AsObject(); ack["kind"] = PersonalSyncActorContract.AckKind; ack["body"] = PersonalSyncActorContract.Ack(Run, Message); ack["expires_ms"] = wall + 60001;
                TestAssert.Throws<InvalidDataException>(() => registry.Put(handle, ack), "Raw storage extended an actor acknowledgement lifetime."); return;
            }
            var before = registry.Status(handle)["revision"]!.GetValue<string>();
            TestAssert.That(registry.Put(handle, wire) && !registry.Put(handle, wire) && registry.Status(handle)["revision"]!.GetValue<string>() != before,
                "Raw storage lost its actual insert/duplicate/state receipts.");
            switch (scenario)
            {
                case "reap_wall": case "reap_monotonic": case "reap_epoch": case "reap_source": case "reap_failure": case "reap_restore":
                {
                    var privatePeer = PersonalSyncActorContract.StoragePeer(Run);
                    new PersonalSyncStore(store).RememberRun(privatePeer, original["body"]!.AsObject(), wall);
                    var outbound = store.Enqueue(Peer, "personal_sync.request", original["body"]!.AsObject(), 60000, wall, actorRunId: Run);
                    var gui = store.Enqueue(Peer, "personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000, wall);
                    byte[]? oldContext = null, oldRun = null;
                    var runKey = $"personal_run:{privatePeer}:{Run}";
                    if (scenario == "reap_restore")
                    {
                        using var snapshotDb = store.OpenDatabase(); snapshotDb.Open(); using var read = snapshotDb.CreateCommand();
                        read.CommandText = "SELECT payload FROM personal_actor_context WHERE actor_id=$id"; read.Parameters.AddWithValue("$id", Run);
                        oldContext = (byte[])read.ExecuteScalar()!;
                        read.Parameters.Clear(); read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", runKey);
                        oldRun = (byte[])read.ExecuteScalar()!;
                    }
                    if (scenario == "reap_wall") wall += PersonalSyncActorStore.LifetimeMs + 1;
                    if (scenario == "reap_monotonic") monotonic += PersonalSyncActorStore.LifetimeMs + 1;
                    if (scenario is "reap_source" or "reap_failure" or "reap_restore") revision = new string('b', 64);
                    var reaper = scenario == "reap_epoch" ? new PersonalSyncActorStore(store, Current, clock: () => wall, monotonicClock: () => monotonic) : registry;
                    if (scenario == "reap_failure")
                    {
                        using (var db = store.OpenDatabase())
                        {
                            db.Open(); using var trigger = db.CreateCommand();
                            trigger.CommandText = "CREATE TRIGGER actor_cleanup_failure BEFORE DELETE ON meta WHEN OLD.key LIKE 'personal_run:@mcp-actor-%' BEGIN SELECT RAISE(FAIL,'owned cleanup failure'); END";
                            trigger.ExecuteNonQuery();
                        }
                        TestAssert.Throws<SqliteException>(() => reaper.Reap(), "Forced native cleanup failure was hidden.");
                        revision = new string('a', 64);
                        TestAssert.That(registry.Status(handle)["phase"]!.GetValue<string>() == "cancelled", "Cleanup failure resumed its retired actor.");
                        Expect("actor_inactive", () => registry.Read(handle, Message));
                        using var dropDb = store.OpenDatabase(); dropDb.Open(); using var drop = dropDb.CreateCommand();
                        drop.CommandText = "DROP TRIGGER actor_cleanup_failure"; drop.ExecuteNonQuery();
                    }
                    TestAssert.That(reaper.Reap() == 1 && store.OutboxMessage(Peer, outbound) is null && store.OutboxMessage(Peer, gui) is not null,
                        "Actor reaper left owned outgoing work or removed unrelated GUI controls.");
                    TestAssert.That(new PersonalSyncStore(store).LoadRun(privatePeer, Run, wall) is null, "Actor reaper left private native staging.");
                    TestAssert.That(reaper.Reap() == 0, "Actor reaper repeated completed cleanup work.");
                    if (scenario == "reap_restore")
                    {
                        using var restoreDb = store.OpenDatabase(); restoreDb.Open(); using var restore = restoreDb.CreateCommand();
                        restore.CommandText = "INSERT OR REPLACE INTO personal_actor_context VALUES($id,$expires,$payload); INSERT OR REPLACE INTO meta VALUES($key,$run)";
                        restore.Parameters.AddWithValue("$id", Run); restore.Parameters.AddWithValue("$expires", wall + PersonalSyncActorStore.LifetimeMs);
                        restore.Parameters.AddWithValue("$payload", oldContext!); restore.Parameters.AddWithValue("$key", runKey); restore.Parameters.AddWithValue("$run", oldRun!);
                        restore.ExecuteNonQuery();
                        TestAssert.That(reaper.Reap() == 1 && new PersonalSyncStore(store).LoadRun(privatePeer, Run, wall) is null,
                            "Restored staging inherited a volatile cleanup receipt.");
                    }
                    if (scenario is "reap_source" or "reap_failure" or "reap_restore")
                        TestAssert.That(registry.Status(handle)["phase"]!.GetValue<string>() == "cancelled", "Source retirement did not retain its terminal owner status.");
                    else Expect("actor_not_found", () => registry.Status(handle));
                    break;
                }
                case "reopen":
                {
                    var reopened = new PersonalSyncActorStore(store, Current, registry.Epoch, () => wall, () => monotonic);
                    TestAssert.That(JsonNode.DeepEquals(reopened.Read(handle, Message), wire), "Protected actor wire was not retained after reopening.");
                    using var db = store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
                    read.CommandText = "SELECT payload FROM personal_actor_wire WHERE actor_id=$actor AND message_id=$message";
                    read.Parameters.AddWithValue("$actor", Run); read.Parameters.AddWithValue("$message", Message);
                    TestAssert.That(JsonNode.DeepEquals(JsonNode.Parse(store.Open("personal_actor_wire", Run + ":" + Message, (byte[])read.ExecuteScalar()!)), wire), "Raw actor marker was not in the actual encrypted stored bytes.");
                    break;
                }
                case "wrong_owner":
                {
                    var other = handle with { OwnerToken = new string('0', 64) };
                    Expect("actor_not_found", () => registry.Read(other, Message)); Expect("actor_not_found", () => registry.Cancel(other)); Expect("actor_not_found", () => registry.Status(other)); break;
                }
                case "epoch":
                    Expect("actor_not_found", () => new PersonalSyncActorStore(store, Current, clock: () => wall, monotonicClock: () => monotonic).Read(handle, Message)); break;
                case "revoke":
                    revision = new string('b', 64); Expect("actor_source_changed", () => registry.Read(handle, Message));
                    TestAssert.That(registry.Cancel(handle)["phase"]!.GetValue<string>() == "cancelled", "Owner could not retire a revoked source."); break;
                case "cancel":
                    registry.Cancel(handle); Expect("actor_inactive", () => registry.Read(handle, Message)); break;
                case "expiry":
                    wall += PersonalSyncActorStore.LifetimeMs + 1; Expect("actor_inactive", () => registry.Read(handle, Message)); registry.Cancel(handle); break;
                case "conflict":
                {
                    var changed = wire.DeepClone().AsObject(); changed["body"]!["body"]!["modules"] = new JsonArray("notes");
                    TestAssert.Throws<InvalidDataException>(() => registry.Put(handle, changed), "Conflicting duplicate actor data replaced a packet.");
                    TestAssert.That(JsonNode.DeepEquals(registry.Read(handle, Message), wire), "Conflict changed the protected original packet."); break;
                }
                case "read_race":
                    failAt = calls + 2; Expect("actor_source_changed", () => registry.Read(handle, Message)); break;
                case "lease_tamper":
                {
                    using var db = store.OpenDatabase(); db.Open(); using var update = db.CreateCommand();
                    update.CommandText = "UPDATE personal_actor_context SET expires_ms=expires_ms+60000 WHERE actor_id=$actor"; update.Parameters.AddWithValue("$actor", Run); update.ExecuteNonQuery();
                    TestAssert.Throws<InvalidDataException>(() => registry.Status(handle), "Plaintext metadata extended a protected owner lease."); break;
                }
                case "capacity":
                    for (var index = 1; index < 4; index++) registry.Create(Peer, Fingerprint, revision);
                    Expect("actor_capacity", () => registry.Create(Peer, Fingerprint, revision));
                    TestAssert.That(JsonNode.DeepEquals(registry.Read(handle, Message), wire), "Live actor data was evicted to make capacity."); break;
                case "wall_rollback":
                    wall -= 86400000; monotonic += PersonalSyncActorStore.LifetimeMs + 1; Expect("actor_inactive", () => registry.Read(handle, Message)); break;
                case "cross_context":
                {
                    var other = registry.Create(Peer, Fingerprint, revision);
                    TestAssert.Throws<KeyNotFoundException>(() => registry.Read(other, Message), "Another valid owner context read a foreign packet."); break;
                }
            }
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static void Expect(string code, Action action)
    {
        try { action(); }
        catch (InvalidOperationException error) when (error.Message == code) { return; }
        throw new InvalidOperationException("Expected native actor failure: " + code);
    }
}
