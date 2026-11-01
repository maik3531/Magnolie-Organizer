using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorOutgoingProducerTests
{
    private const string Peer = "22222222-2222-4222-8222-222222222222", Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static JsonObject Tombstone(string kind, string id, string parent = "", int counter = 1)
    {
        var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = counter });
        return new() { ["state"] = "deleted", ["status"] = "local_pending", ["peer_device_id"] = Peer, ["parent_id"] = parent,
            ["hash"] = "", ["prior_hash"] = new string('a', 64), ["clock"] = clock, ["deleted_ms"] = 2, ["label"] = "Synthetic native target",
            ["proposal_id"] = PersonalSyncContract.DeletionProposalId(Peer, kind, id, parent, clock, new string('a', 64)) };
    }
    private static (JsonObject Book, JsonObject Scope) Fixture(int count = 33)
    {
        var entities = new JsonObject();
        for (var i = 0; i < count; i++) entities["attachment\0canonical-parent\0file-" + i.ToString("D3")] = Tombstone("attachment", "file-" + i.ToString("D3"), "canonical-parent", i + 1);
        return (new JsonObject { ["notizen"] = new JsonArray(new JsonObject { ["id"] = "local-parent", ["text"] = "Synthetic Grüße 🌸", ["anhaenge"] = new JsonArray() }),
            ["aufgaben"] = new JsonArray(), ["personalSync"] = new JsonObject { ["actor_id"] = Actor, ["peer_device_id"] = Peer, ["counter"] = count,
                ["note_ids"] = new JsonObject { ["local-parent"] = "wire-parent" }, ["note_aliases"] = new JsonObject { ["wire-parent"] = "canonical-parent" },
                ["entities"] = entities } }, PhoneContentScope.Create(["canonical-parent"], ["selected-task"]));
    }
    private static (NativeBookOwnerScope Owner, NativeActorBookSnapshot Snapshot) Capture(JsonObject book)
    {
        var owner = new NativeBookOwnerScope(); owner.SetReady(true); var text = book.ToJsonString();
        owner.RecordSaved("native-producer-fixture", true, Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant());
        return (owner, NativeActorBookSnapshot.Capture(() => owner.SaveState("native-producer-fixture", true), () => text)!);
    }
    private static IReadOnlyList<JsonObject> Prepare(JsonObject book, JsonObject scope)
    {
        var (owner, snapshot) = Capture(book); var before = book.ToJsonString();
        var result = PersonalActorOutgoingProducer.Prepare(snapshot, scope, Peer, Run, () => owner.SaveState("native-producer-fixture", true), () => new string('a', 64));
        TestAssert.That(book.ToJsonString() == before && snapshot.Text == before, "Native proposal preparation mutated its book.");
        return result;
    }
    private static JsonObject FirstMeta(JsonObject book) => book["personalSync"]!["entities"]!.AsObject().First().Value!.AsObject();
    private static JsonObject[] Proposals(IReadOnlyList<JsonObject> bodies) => bodies.SelectMany(body => body["proposals"]!.AsArray().OfType<JsonObject>()).ToArray();

    internal static Task RunAsync()
    {
        var (book, scope) = Fixture(); var bodies = Prepare(book, scope); var proposals = Proposals(bodies);
        TestAssert.That(bodies.Count == 2 && bodies[0]["proposals"]!.AsArray().Count == 32 && bodies[1]["proposals"]!.AsArray().Count == 1 &&
            bodies[0]["sequence"]!.GetValue<int>() == 0 && bodies[1]["sequence"]!.GetValue<int>() == 1 && !bodies[0]["last"]!.GetValue<bool>() && bodies[1]["last"]!.GetValue<bool>() &&
            bodies[0]["proposal_batch_id"]!.GetValue<string>() == bodies[1]["proposal_batch_id"]!.GetValue<string>(), "Native proposals lost complete 32+1 batch identity/order.");
        TestAssert.That(proposals.All(p => p["parent_id"]!.GetValue<string>() == "canonical-parent") &&
            proposals.Select(p => p["id"]!.GetValue<string>()).ToHashSet().SetEquals(Enumerable.Range(0, 33).Select(i => "file-" + i.ToString("D3"))), "Native alias/target projection changed identities.");
        TestAssert.That(proposals.Select(p => p["proposal_id"]!.GetValue<string>()).SequenceEqual(proposals.Select(p => p["proposal_id"]!.GetValue<string>()).OrderBy(id => id, StringComparer.Ordinal)), "Native proposal ordering is not canonical.");
        (book, scope) = Fixture(0);
        book["personalSync"]!["entities"] = new JsonObject { ["note\0historical-note"] = Tombstone("note", "historical-note"),
            ["task\0historical-task"] = Tombstone("task", "historical-task"), ["note\0selected-absent"] = Tombstone("note", "selected-absent"),
            ["task\0selected-task"] = Tombstone("task", "selected-task") };
        book["personalSync"]!["entities"]!["note\0historical-note"]!["acknowledged_by_peer"] = true;
        var selected = Proposals(Prepare(book, PhoneContentScope.Create(["canonical-parent", "selected-absent"], ["selected-task"])));
        TestAssert.That(selected.Length == 2 && selected.Select(p => p["id"]!.GetValue<string>()).ToHashSet().SetEquals(["selected-absent", "selected-task"]), "Historical ACK-only targets acquired native proposal rights.");
        (book, scope) = Fixture();
        book["notizen"]![0]!["anhaenge"] = new JsonArray(new JsonObject { ["id"] = "local-file" });
        book["personalSync"]!["attachment_aliases"] = new JsonObject { ["wire-parent\0local-file"] = "file-000" };
        TestAssert.That(Proposals(Prepare(book, scope)).Length == 32, "A live aliased attachment was proposed as removed.");
        foreach (var gate in new[] { "parent-absent", "parent-unselected", "tree-parent", "other-peer", "other-state-peer", "resolved", "live-note", "live-task" })
        {
            (book, scope) = Fixture(1);
            if (gate == "parent-absent") book["notizen"] = new JsonArray();
            if (gate == "parent-unselected") scope = PhoneContentScope.Create([], ["selected-task"]);
            if (gate == "tree-parent") book["notizen"]![0]!["baumQuelle"] = "unlinked-tree-source";
            if (gate == "other-peer") FirstMeta(book)["peer_device_id"] = Run;
            if (gate == "other-state-peer") book["personalSync"]!["peer_device_id"] = Run;
            if (gate == "resolved") FirstMeta(book)["status"] = "resolved";
            if (gate == "live-note") book["personalSync"]!["entities"] = new JsonObject { ["note\0canonical-parent"] = Tombstone("note", "canonical-parent") };
            if (gate == "live-task") { book["aufgaben"] = new JsonArray(new JsonObject { ["id"] = "selected-task" }); book["personalSync"]!["entities"] = new JsonObject { ["task\0selected-task"] = Tombstone("task", "selected-task") }; }
            TestAssert.That(Prepare(book, scope).Count == 0, "Unauthorized/not removed target was prepared: " + gate);
        }
        foreach (var field in new[] { "parent_id", "prior_hash", "proposal_id", "clock", "conflict", "hash" })
        {
            (book, scope) = Fixture(2); var meta = FirstMeta(book);
            meta[field] = field switch { "conflict" => JsonValue.Create(true), "clock" => new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 99 }),
                "parent_id" => JsonValue.Create("another-parent"), "proposal_id" => JsonValue.Create(Run), _ => JsonValue.Create(new string('b', 64)) };
            TestAssert.Throws<InvalidDataException>(() => Prepare(book, scope), "Tampered native tombstone was prepared: " + field);
        }
        foreach (var gate in new[] { "stale-save", "new-save-during-prepare", "source-changed", "missing-source", "alias-cycle", "over-capacity" })
        {
            (book, scope) = Fixture(gate == "over-capacity" ? 257 : 1);
            if (gate == "alias-cycle") book["personalSync"]!["note_aliases"]!["canonical-parent"] = "wire-parent";
            var (owner, snapshot) = Capture(book); var calls = 0;
            if (gate == "stale-save") owner.RecordSaved("native-producer-fixture", true, snapshot.SavedBook.Sha256);
            string? Source()
            {
                calls++;
                if (gate == "new-save-during-prepare" && calls == 2) owner.RecordSaved("native-producer-fixture", true, snapshot.SavedBook.Sha256);
                return gate == "missing-source" ? null : new string(gate == "source-changed" && calls == 2 ? 'b' : 'a', 64);
            }
            var denied = false;
            try { PersonalActorOutgoingProducer.Prepare(snapshot, scope, Peer, Run, () => owner.SaveState("native-producer-fixture", true), Source); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { denied = true; }
            TestAssert.That(denied, "Native preparation crossed writer/source/identity/capacity fence: " + gate);
        }
        AtomicPreparedGroups();
        SuccessfulGroupReplay();
        return Task.CompletedTask;
    }

    private static void AtomicPreparedGroups()
    {
        var root = Path.Combine(Path.GetTempPath(), "actor-native-group-" + Guid.NewGuid().ToString("N"));
        try
        {
            foreach (var fault in new[] { "none", "second-frame", "last-target", "ledger", "source-before", "source-after", "saved-before", "saved-after", "missing-last", "changed-batch", "duplicate-target", "incomplete-first" })
            {
                var key = Enumerable.Repeat((byte)37, 32).ToArray(); var path = new WindowsPaths(Path.Combine(root, fault));
                var store = new TelefonStore(path, key); var (book, scope) = Fixture(); var (owner, snapshot) = Capture(book);
                var bodies = PersonalActorOutgoingProducer.Prepare(snapshot, scope, Peer, Run,
                    () => owner.SaveState("native-producer-fixture", true), () => new string('a', 64)).ToArray();
                var privatePeer = PersonalSyncActorContract.StoragePeer(Run);
                if (fault == "missing-last") bodies[^1]["last"] = false;
                if (fault == "changed-batch") bodies[^1]["proposal_batch_id"] = Peer;
                if (fault == "duplicate-target") bodies[^1]["proposals"]![0]!["id"] = bodies[0]["proposals"]![0]!["id"]!.DeepClone();
                if (fault == "incomplete-first") bodies[0]["proposals"]!.AsArray().RemoveAt(0);
                if (fault is "second-frame" or "last-target" or "ledger")
                {
                    using var db = store.OpenDatabase(); db.Open(); using var sql = db.CreateCommand();
                    var trigger = fault == "second-frame" ? "BEFORE INSERT ON outbox WHEN (SELECT COUNT(*) FROM outbox)>=1" :
                        fault == "ledger" ? "BEFORE INSERT ON meta WHEN NEW.key LIKE 'personal_actor_producer:%'" :
                        "BEFORE INSERT ON meta WHEN NEW.key='personal_proposal_kind:" + privatePeer + ":out:" + bodies[^1]["proposals"]![0]!["proposal_id"]!.GetValue<string>() + "'";
                    sql.CommandText = "CREATE TRIGGER group_atomic_failure " + trigger + " BEGIN SELECT RAISE(ABORT,'synthetic group transaction failure'); END"; sql.ExecuteNonQuery();
                }
                var sources = 0; var savedReads = 0;
                string Source() { sources++; return new string(fault == "source-before" || fault == "source-after" && sources == 2 ? 'b' : 'a', 64); }
                NativeBookSaveState? Saved()
                {
                    savedReads++;
                    if (fault == "saved-after" && savedReads == 2) owner.RecordSaved("native-producer-fixture", true, snapshot.SavedBook.Sha256);
                    return owner.SaveState("native-producer-fixture", true);
                }
                if (fault == "saved-before") owner.RecordSaved("native-producer-fixture", true, snapshot.SavedBook.Sha256);
                IReadOnlyList<JsonObject> Commit() => store.QueueActorDeletionProposals(Peer, Run, bodies, new string('a', 64), snapshot.SavedBook, Source, Saved);
                if (fault != "none")
                {
                    var denied = false;
                    try { Commit(); } catch (Exception error) when (error is InvalidDataException or InvalidOperationException or SqliteException) { denied = true; }
                    using var db = store.OpenDatabase(); db.Open(); using var count = db.CreateCommand();
                    count.CommandText = "SELECT (SELECT COUNT(*) FROM outbox)+(SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_proposal_kind:%' OR key LIKE 'personal_actor_producer:%')";
                    TestAssert.That(denied && Convert.ToInt64(count.ExecuteScalar()) == 0, "Native group fault retained partial frames/targets: " + fault);
                    continue;
                }
                var wire = Commit(); var reopened = new TelefonStore(path, key);
                TestAssert.That(wire.Count == 2, "Native prepared group lost a frame.");
                foreach (var frame in wire)
                {
                    TestAssert.That(frame["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                        JsonNode.DeepEquals(frame, reopened.OutboxMessage(Peer, frame["message_id"]!.GetValue<string>())), "Actual native group envelope did not survive reopen.");
                    var body = PersonalSyncActorContract.Unwrap(frame["body"]!.AsObject()).Body;
                    TestAssert.That(JsonNode.DeepEquals(body, bodies[body["sequence"]!.GetValue<int>()]), "Native group changed prepared proposal bytes.");
                    var decision = new JsonObject { ["format"] = 1, ["run_id"] = Run, ["decision_id"] = Run,
                        ["decisions"] = new JsonArray(body["proposals"]!.AsArray().OfType<JsonObject>().Select(p => (JsonNode)new JsonObject {
                            ["proposal_id"] = p["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = p["clock"]!.DeepClone() }).ToArray()) };
                    TestAssert.That(reopened.PersonalDecisionTargets(privatePeer, decision, false)?.Count == body["proposals"]!.AsArray().Count &&
                        reopened.PersonalDecisionTargets(Peer, decision, false) is null, "Native group proof escaped its private run or lost target coverage.");
                }
                TestAssert.That(owner.SaveState("native-producer-fixture", true) == snapshot.SavedBook && book.ToJsonString() == snapshot.Text, "Native group commit mutated its source book.");
            }
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static void SuccessfulGroupReplay()
    {
        var root = Path.Combine(Path.GetTempPath(), "actor-native-replay-" + Guid.NewGuid().ToString("N"));
        static string[] Rows(TelefonStore store)
        {
            using var db = store.OpenDatabase(); db.Open(); var result = new List<string>();
            foreach (var query in new[] { "SELECT message_id,peer_id,kind,created_ms,expires_ms,hex(payload),attempts,next_attempt_ms,last_error,transport_policy FROM outbox ORDER BY message_id",
                "SELECT key,hex(value) FROM meta WHERE key LIKE 'personal_proposal_kind:%' OR key LIKE 'personal_actor_producer:%' ORDER BY key" })
            {
                using var command = db.CreateCommand(); command.CommandText = query; using var reader = command.ExecuteReader();
                while (reader.Read()) result.Add(string.Join("|", Enumerable.Range(0, reader.FieldCount).Select(index => reader.GetValue(index).ToString())));
            }
            return result.ToArray();
        }
        try
        {
            foreach (var scenario in new[] { "same", "changed-body", "new-batch", "source", "new-save", "expired", "after-ack", "retired-owner" })
            {
                var key = Enumerable.Repeat((byte)37, 32).ToArray(); var path = new WindowsPaths(Path.Combine(root, scenario));
                var store = new TelefonStore(path, key); var (book, scope) = Fixture(); var (owner, snapshot) = Capture(book);
                var bodies = PersonalActorOutgoingProducer.Prepare(snapshot, scope, Peer, Run,
                    () => owner.SaveState("native-producer-fixture", true), () => new string('a', 64)).ToArray();
                string? source = new string('a', 64);
                IReadOnlyList<JsonObject> Commit(TelefonStore target) => target.QueueActorDeletionProposals(Peer, Run, bodies, new string('a', 64), snapshot.SavedBook,
                    () => source, () => owner.SaveState("native-producer-fixture", true));
                var original = Commit(store); var privatePeer = PersonalSyncActorContract.StoragePeer(Run);
                if (scenario == "changed-body") bodies[0]["proposals"]![0]!["label"] = "Changed retry content";
                if (scenario == "new-batch") foreach (var body in bodies) body["proposal_batch_id"] = Peer;
                if (scenario == "source") source = new string('b', 64);
                if (scenario == "new-save") owner.RecordSaved("native-producer-fixture", true, snapshot.SavedBook.Sha256);
                if (scenario == "expired")
                {
                    var ledgerKey = $"personal_actor_producer:{privatePeer}:{Run}";
                    using var db = store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
                    read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", ledgerKey);
                    var clear = store.Open("personal_actor_producer", ledgerKey, (byte[])read.ExecuteScalar()!);
                    try
                    {
                        var record = JsonNode.Parse(clear)!.AsObject(); record["expires_ms"] = 0;
                        using var write = db.CreateCommand(); write.CommandText = "UPDATE meta SET value=$value WHERE key=$key";
                        write.Parameters.AddWithValue("$key", ledgerKey); write.Parameters.AddWithValue("$value", store.Seal("personal_actor_producer", ledgerKey, TelefonCrypto.Canonical(record))); write.ExecuteNonQuery();
                    }
                    finally { CryptographicOperations.ZeroMemory(clear); }
                }
                if (scenario is "after-ack" or "retired-owner") foreach (var wire in original) store.CompleteOutbox(Peer, wire["message_id"]!.GetValue<string>());
                if (scenario == "retired-owner")
                {
                    source = null; new PersonalSyncStore(store).PurgeProtocol(privatePeer);
                    TestAssert.That(Rows(store).Length == 0, "Private owner cleanup left native producer ledger/proofs.");
                }
                var reopened = new TelefonStore(path, key); var before = Rows(reopened);
                if (scenario is not ("same" or "after-ack"))
                    TestAssert.Throws<InvalidOperationException>(() => Commit(reopened), "Native replay accepted a changed/expired/retired operation: " + scenario);
                else
                {
                    TestAssert.That(JsonNode.DeepEquals(new JsonArray(Commit(reopened).Select(wire => (JsonNode)wire.DeepClone()).ToArray()),
                        new JsonArray(original.Select(wire => (JsonNode)wire.DeepClone()).ToArray())), "Success replay changed original native frame identities.");
                    var returned = Commit(reopened); returned[0]["message_id"] = Run;
                    TestAssert.That(Commit(reopened)[0]["message_id"]!.GetValue<string>() == original[0]["message_id"]!.GetValue<string>(), "Caller edits changed persisted replay frames.");
                    TestAssert.That(original.All(wire => (reopened.OutboxMessage(Peer, wire["message_id"]!.GetValue<string>()) is null) == (scenario == "after-ack")), "Success replay requeued acknowledged frames.");
                }
                TestAssert.That(Rows(reopened).SequenceEqual(before), "Native success replay or rejected claim rewrote protected rows: " + scenario);
            }
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
