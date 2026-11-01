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

    private static void OutgoingTargetEvidence()
    {
        // Evidence-only primitive. No controller, queue, data or wire grant.
        foreach (var scenario in new[] { "success", "owner", "source", "scope", "book", "missing-book", "old-ack", "live", "resolved", "other-peer", "missing-parent", "tree-parent", "live-alias", "current-content" })
        {
            var (book, _) = Fixture(1); var entities = book["personalSync"]!["entities"]!.AsObject();
            entities["note\0removed-note"] = Tombstone("note", "removed-note"); entities["task\0removed-task"] = Tombstone("task", "removed-task");
            if (scenario == "old-ack") book["personalSync"]!["entities"] = new JsonObject { ["note\0old"] = new JsonObject { ["acknowledged_by_peer"] = true } };
            if (scenario is "live" or "resolved") foreach (var meta in entities.Select(value => value.Value!.AsObject()))
                meta[scenario == "live" ? "state" : "status"] = scenario == "live" ? "live" : "resolved";
            if (scenario == "other-peer") book["personalSync"]!["peer_device_id"] = Guid.NewGuid().ToString("D");
            if (scenario == "missing-parent") book["notizen"] = new JsonArray();
            if (scenario == "tree-parent") book["notizen"]![0]!["baumQuelle"] = "unowned";
            if (scenario == "live-alias")
            {
                book["notizen"]![0]!["anhaenge"] = new JsonArray(new JsonObject { ["id"] = "local-alias" });
                book["personalSync"]!["attachment_aliases"] = new JsonObject { ["canonical-parent\0local-alias"] = "file-000" };
            }
            var (owner, captured) = Capture(book); NativeActorBookSnapshot? snapshot = captured;
            var allowed = true; string? source = new string('b', 64);
            var scope = scenario == "current-content" ? PhoneContentScope.Create(["canonical-parent", "removed-note"], ["removed-task"]) : PhoneContentScope.Create([], []);
            var originalText = book.ToJsonString(); var originalSaved = owner.SaveState("native-producer-fixture", true); var originalScope = scope.DeepClone();
            var proof = new PersonalActorOutgoingTargetEvidence(Peer, Run, () => allowed, () => source, () => snapshot, () => scope);
            var targets = proof.Targets();
            TestAssert.That(book.ToJsonString() == originalText && owner.SaveState("native-producer-fixture", true) == originalSaved && JsonNode.DeepEquals(scope, originalScope),
                "Native target evidence modified its book/selection/save state.");
            if (scenario is "old-ack" or "live" or "resolved" or "other-peer" or "current-content")
            { TestAssert.That(targets.Count == 0, "Old ACK/nonpending/content target acquired independent offscope evidence: " + scenario); continue; }
            if (scenario is "missing-parent" or "tree-parent" or "live-alias")
            { TestAssert.That(targets.OfType<JsonObject>().All(value => value["kind"]!.GetValue<string>() != "attachment"), "Unavailable/unowned/live child became removal evidence."); continue; }
            TestAssert.That(targets.Count == 3, "Exact offscope note/task/child pending proofs were not derived.");
            var target = targets[0]!.AsObject();
            if (scenario == "success")
            {
                TestAssert.That(PersonalActorOutgoingProducer.Prepare(captured, scope, Peer, Run, () => owner.SaveState("native-producer-fixture", true), () => source).Count == 0,
                    "Private target evidence widened the ordinary accepted-scope producer.");
                TestAssert.That(proof.RequireExact(Run, target), "Exact outgoing target proof was refused.");
                target["prior_hash"] = new string('f', 64);
                TestAssert.Throws<InvalidOperationException>(() => proof.RequireExact(Run, target), "Changed target hash acquired evidence.");
                TestAssert.That(proof.Targets()[0]!["prior_hash"]!.GetValue<string>() == new string('a', 64), "Returned target mutation changed pinned evidence.");
                TestAssert.Throws<InvalidOperationException>(() => proof.RequireExact(Guid.NewGuid().ToString("D"), proof.Targets()[0]!.AsObject()), "Another run reused target evidence.");
                continue;
            }
            if (scenario == "owner") allowed = false;
            if (scenario == "source") source = new string('c', 64);
            if (scenario == "scope") scope = PhoneContentScope.Create(["different"], []);
            if (scenario == "book") { book["notizen"]![0]!["text"] = "New actual book"; snapshot = Capture(book).Snapshot; }
            if (scenario == "missing-book") snapshot = null;
            TestAssert.Throws<InvalidOperationException>(() => proof.Targets(), "Changed native observation retained offscope evidence: " + scenario);
            TestAssert.Throws<InvalidOperationException>(() => proof.RequireExact(Run, target), "Changed native observation retained exact target permission: " + scenario);
        }
    }

    private static void ChangedTargetEvidence()
    {
        foreach (var field in new[] { "proposal_id", "prior_hash", "hash", "parent_id", "clock", "conflict" })
        {
            var (book, _) = Fixture(1); var meta = FirstMeta(book);
            meta[field] = field switch { "conflict" => JsonValue.Create(true),
                "clock" => new JsonArray(new JsonObject { ["actor_id"] = Peer, ["counter"] = 99 }),
                "parent_id" => JsonValue.Create("different"), "proposal_id" => JsonValue.Create(Run), _ => JsonValue.Create(new string('f', 64)) };
            var (owner, snapshot) = Capture(book);
            TestAssert.Throws<InvalidDataException>(() => new PersonalActorOutgoingTargetEvidence(Peer, Run, () => true, () => new string('b', 64),
                () => snapshot, () => PhoneContentScope.Create([], [], epoch: Run)), "Changed current native tombstone acquired evidence: " + field);
        }
    }

    private static void IncomingLiveObservations()
    {
        foreach (var kind in new[] { "note", "task", "attachment" })
        foreach (var scenario in new[] { "success", "old-ack", "other-peer", "missing-live", "duplicate-live", "unowned", "stale-meta", "owner", "source", "scope", "book", "run", "target-change", "content-target", "changed-content-matching-meta" })
        {
            var (book, _) = Fixture(0);
            book["notizen"]![0]!["text"] = "PRIVATE CONTENT MUST NOT BE RETURNED";
            book["notizen"]![0]!["anhaenge"] = new JsonArray(new JsonObject { ["id"] = "file-000", ["daten"] = "PRIVATE BLOB" });
            book["aufgaben"] = new JsonArray(new JsonObject { ["id"] = "selected-task", ["titel"] = "PRIVATE TASK" });
            var id = kind == "note" ? "canonical-parent" : kind == "task" ? "selected-task" : "file-000";
            var parent = kind == "attachment" ? "canonical-parent" : "";
            var key = kind + "\0" + (kind == "attachment" ? parent + "\0" : "") + id;
            var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 });
            var meta = new JsonObject { ["state"] = "live", ["peer_device_id"] = Peer, ["hash"] = new string('a', 64), ["clock"] = clock.DeepClone(), ["parent_id"] = parent };
            book["personalSync"]!["entities"]![key] = meta;
            if (scenario == "old-ack") book["personalSync"]!["entities"]![key] = new JsonObject { ["acknowledged_by_peer"] = true };
            if (scenario == "other-peer") meta["peer_device_id"] = Guid.NewGuid().ToString("D");
            if (scenario == "stale-meta") meta["state"] = "deleted";
            if (scenario == "unowned") { if (kind == "task") book["aufgaben"]![0]!["delegiertAn"] = "someone-else"; else book["notizen"]![0]!["baumQuelle"] = "unowned"; }
            if (scenario == "missing-live") { if (kind == "task") book["aufgaben"] = new JsonArray(); else if (kind == "note") book["notizen"] = new JsonArray(); else book["notizen"]![0]!["anhaenge"] = new JsonArray(); }
            if (scenario == "duplicate-live")
            {
                var values = kind == "task" ? book["aufgaben"]!.AsArray() : kind == "note" ? book["notizen"]!.AsArray() : book["notizen"]![0]!["anhaenge"]!.AsArray();
                values.Add(values[0]!.DeepClone());
            }
            if (scenario == "changed-content-matching-meta")
            {
                if (kind == "note") book["notizen"]![0]!["text"] = "CURRENT CHANGED PRIVATE NOTE";
                else if (kind == "task") book["aufgaben"]![0]!["titel"] = "CURRENT CHANGED PRIVATE TASK";
                else book["notizen"]![0]!["anhaenge"]![0]!["daten"] = "CURRENT CHANGED PRIVATE BLOB";
            }
            var (owner, captured) = Capture(book); NativeActorBookSnapshot? snapshot = captured;
            var before = book.ToJsonString(); var beforeSaved = owner.SaveState("native-producer-fixture", true);
            var allowed = true; string? source = new string('b', 64);
            var scope = scenario == "content-target" ? PhoneContentScope.Create(kind == "task" ? [] : ["canonical-parent"], kind == "task" ? ["selected-task"] : []) : PhoneContentScope.Create([], []);
            PersonalActorIncomingLiveTargetObservation Create() => new(Peer, Run, () => allowed, () => source, () => snapshot, () => scope);
            var proof = Create();
            var target = new JsonObject { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
                ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() };
            if (scenario is "old-ack" or "other-peer" or "missing-live" or "duplicate-live" or "unowned" or "stale-meta" or "content-target")
            { TestAssert.Throws<InvalidOperationException>(() => proof.Observe(Run, target), "Invalid live native target was observed: " + kind + "/" + scenario); continue; }
            var result = proof.Observe(Run, target);
            TestAssert.That(result["requires_conflict_choice"]!.GetValue<bool>() && result["metadata_matches"]!.GetValue<bool>() && !result.ToJsonString().Contains("PRIVATE", StringComparison.Ordinal) &&
                owner.SaveState("native-producer-fixture", true) == beforeSaved && book.ToJsonString() == before,
                "Incoming local identity observation exported content, mislabeled identity or changed its book.");
            if (scenario is "success" or "changed-content-matching-meta")
            {
                result["target"]!["prior_hash"] = new string('f', 64);
                TestAssert.That(JsonNode.DeepEquals(proof.Observe(Run, target)["target"], target), "Returned observation changed pinned target proof.");
                var conflicting = target.DeepClone().AsObject(); conflicting["proposal_id"] = Guid.NewGuid().ToString("D"); conflicting["prior_hash"] = new string('f', 64);
                TestAssert.Throws<InvalidOperationException>(() => proof.Observe(Run, conflicting), "Second proposal replaced the observed entity identity.");
                var mismatch = Create().Observe(Run, conflicting);
                TestAssert.That(mismatch["requires_conflict_choice"]!.GetValue<bool>() && !mismatch["metadata_matches"]!.GetValue<bool>(), "Different remote value was falsely observed as equal to current local metadata.");
                continue;
            }
            var expectedRun = Run;
            if (scenario == "owner") allowed = false;
            if (scenario == "source") source = new string('c', 64);
            if (scenario == "scope") scope = PhoneContentScope.Create(["different"], []);
            if (scenario == "book") { book["notizen"]![0]!["text"] = "CHANGED"; snapshot = Capture(book).Snapshot; }
            if (scenario == "run") expectedRun = Guid.NewGuid().ToString("D");
            if (scenario == "target-change") target["clock"]![0]!["counter"] = 9;
            TestAssert.Throws<InvalidOperationException>(() => proof.Observe(expectedRun, target), "Changed native boundary retained incoming observation: " + kind + "/" + scenario);
        }
    }

    private static void IncomingObservationCapacity()
    {
        var (book, _) = Fixture(0); var entities = book["personalSync"]!["entities"]!.AsObject(); var tasks = book["aufgaben"]!.AsArray();
        var targets = new List<JsonObject>();
        for (var index = 0; index < 257; index++)
        {
            var id = $"capacity-task-{index:D3}"; var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 });
            tasks.Add(new JsonObject { ["id"] = id, ["titel"] = "PRIVATE CAPACITY CONTENT" });
            entities["task\0" + id] = new JsonObject { ["state"] = "live", ["peer_device_id"] = Peer, ["hash"] = new string('a', 64), ["clock"] = clock.DeepClone(), ["parent_id"] = "" };
            targets.Add(new JsonObject { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = "task", ["id"] = id, ["parent_id"] = "", ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() });
        }
        var (owner, snapshot) = Capture(book); var scope = PhoneContentScope.Create([], []); var before = book.ToJsonString();
        var proof = new PersonalActorIncomingLiveTargetObservation(Peer, Run, () => true, () => new string('b', 64), () => snapshot, () => scope);
        foreach (var target in targets.Take(256)) TestAssert.That(proof.Observe(Run, target)["requires_conflict_choice"]!.GetValue<bool>(), "Maximum observation bypassed its explicit conflict-choice boundary.");
        TestAssert.Throws<InvalidDataException>(() => proof.Observe(Run, targets[256]), "More than256 independent target observations were cached.");
        TestAssert.That(book.ToJsonString() == before && scope["members"]!["notes"]!.AsArray().Count == 0 && scope["members"]!["tasks"]!.AsArray().Count == 0,
            "Observation capacity changed book data or content membership.");
    }

    internal static Task RunAsync()
    {
        var (book, scope) = Fixture(); var bodies = Prepare(book, scope); var proposals = Proposals(bodies);
        TestAssert.That(bodies.Count == 2 && bodies[0]["proposals"]!.AsArray().Count == 32 && bodies[1]["proposals"]!.AsArray().Count == 1 &&
            bodies[0]["sequence"]!.GetValue<int>() == 0 && bodies[1]["sequence"]!.GetValue<int>() == 1 && !bodies[0]["last"]!.GetValue<bool>() && bodies[1]["last"]!.GetValue<bool>() &&
            bodies[0]["proposal_batch_id"]!.GetValue<string>() == bodies[1]["proposal_batch_id"]!.GetValue<string>(), "Native proposals lost complete 32+1 batch identity/order.");
        TestAssert.That(proposals.All(p => p["parent_id"]!.GetValue<string>() == "canonical-parent") &&
            proposals.Select(p => p["id"]!.GetValue<string>()).ToHashSet().SetEquals(Enumerable.Range(0, 33).Select(i => "file-" + i.ToString("D3"))), "Native alias/target projection changed identities.");
        TestAssert.That(proposals.Select(p => p["proposal_id"]!.GetValue<string>()).SequenceEqual(proposals.Select(p => p["proposal_id"]!.GetValue<string>()).OrderBy(id => id, StringComparer.Ordinal)), "Native proposal ordering is not canonical.");
        foreach (var decisionCase in new[] { "complete", "missing", "duplicate", "foreign", "clock" })
        {
            var decisions = proposals.Select(value => new JsonObject { ["proposal_id"] = value["proposal_id"]!.DeepClone(),
                ["decision"] = "restore", ["expected_clock"] = value["clock"]!.DeepClone() }).ToList();
            if (decisionCase == "missing") decisions.RemoveAt(decisions.Count - 1);
            if (decisionCase == "duplicate") decisions[^1] = decisions[0].DeepClone().AsObject();
            if (decisionCase == "foreign") decisions[^1]["proposal_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff";
            if (decisionCase == "clock") decisions[^1]["expected_clock"]![0]!["counter"] = 9999;
            var incoming = decisions.Chunk(32).Select(chunk => new JsonObject { ["format"] = 1, ["run_id"] = Run,
                ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = new JsonArray(chunk.Cast<JsonNode>().ToArray()) }).ToArray();
            if (decisionCase == "complete") TelefonCoordinator.RequireActorProducerDecisionSet(bodies, incoming);
            else TestAssert.Throws<InvalidOperationException>(() => TelefonCoordinator.RequireActorProducerDecisionSet(bodies, incoming),
                "Producer completion accepted an incomplete/changed native decision set: " + decisionCase);
        }
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
        OutgoingTargetEvidence();
        ChangedTargetEvidence();
        IncomingLiveObservations();
        IncomingObservationCapacity();
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
