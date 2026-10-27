using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorCommitTests
{
    private const string Run = "11111111-1111-4111-8111-111111111111";
    private static readonly long Now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private static readonly string[] IntentIds = ["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"];

    internal static Task RunAsync()
    {
        ReviewVectors();
        var root = Path.Combine(Path.GetTempPath(), "magnolie-actor-atomic-" + Guid.NewGuid().ToString("N"));
        try
        {
            CheckDecisionTargets(Path.Combine(root, "targets"));
            foreach (var mode in new[] { "missing", "partial", "foreign_token", "extra", "duplicate", "expired", "foreign_run", "atomic" })
                Check(Path.Combine(root, mode), mode);
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    private static void CheckDecisionTargets(string path)
    {
        var keyBytes = Enumerable.Range(1, 32).Select(value => (byte)value).ToArray();
        var store = new TelefonStore(new WindowsPaths(path), keyBytes); var peer = PersonalSyncActorContract.StoragePeer(Run);
        var proposalId = "33333333-3333-4333-8333-333333333333";
        var clock = new JsonArray(new JsonObject { ["actor_id"] = Run, ["counter"] = 2 });
        var proposal = new JsonObject { ["proposal_id"] = proposalId, ["kind"] = "attachment", ["id"] = "scope-target",
            ["parent_id"] = "scope-parent", ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone(),
            ["deleted_ms"] = 0, ["label"] = "Not retained in target proof" };
        var body = new JsonObject { ["format"] = 1, ["run_id"] = Run, ["proposal_batch_id"] = Run, ["sequence"] = 0,
            ["last"] = true, ["proposals"] = new JsonArray(proposal) };
        var decision = new JsonObject { ["format"] = 1, ["run_id"] = Run, ["decision_id"] = "44444444-4444-4444-8444-444444444444",
            ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = proposalId, ["decision"] = "restore", ["expected_clock"] = clock.DeepClone() }) };
        TestAssert.That(store.PersonalDecisionTargets(peer, decision, false) is null, "Absent target proof was guessed.");
        store.RememberPersonalProposalKinds(peer, body, true);
        var expected = new JsonArray(new JsonObject { ["proposal_id"] = proposalId, ["kind"] = "attachment", ["id"] = "scope-target",
            ["parent_id"] = "scope-parent", ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() });
        TestAssert.That(JsonNode.DeepEquals(expected, store.PersonalDecisionTargets(peer, decision, false)), "Native full target identity was not retained.");
        var edited = store.PersonalDecisionTargets(peer, decision, false)!; edited[0]!["id"] = "caller-edit";
        foreach (var (field, value) in new[] { ("id", "foreign-target"), ("parent_id", "foreign-parent"), ("prior_hash", new string('b', 64)) })
        {
            var changed = body.DeepClone().AsObject(); changed["proposals"]![0]![field] = value;
            TestAssert.Throws<InvalidDataException>(() => store.RememberPersonalProposalKinds(peer, changed, true), "Changed target identity retained the old proposal ID.");
        }
        var key = "personal_proposal_kind:" + peer + ":out:" + proposalId;
        JsonObject saved;
        using (var connection = store.OpenDatabase())
        {
            connection.Open(); using var read = connection.CreateCommand(); read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key);
            saved = JsonNode.Parse(store.Open("personal_proposal_kind", key, (byte[])read.ExecuteScalar()!))!.AsObject();
        }
        void WriteMeta(JsonObject value)
        {
            using var connection = store.OpenDatabase(); connection.Open(); using var write = connection.CreateCommand();
            write.CommandText = "UPDATE meta SET value=$data WHERE key=$key"; write.Parameters.AddWithValue("$key", key);
            write.Parameters.AddWithValue("$data", store.Seal("personal_proposal_kind", key, TelefonCrypto.Canonical(value))); write.ExecuteNonQuery();
        }
        var legacy = saved.DeepClone().AsObject(); legacy.Remove("target"); WriteMeta(legacy);
        TestAssert.That(store.PersonalDecisionKinds(peer, decision, false)?.Single() == "attachment" && store.PersonalDecisionTargets(peer, decision, false) is null,
            "Legacy kind-only proof was rejected or became a full target authority.");
        store.RememberPersonalProposalKinds(peer, body, true);
        var reopened = new TelefonStore(new WindowsPaths(path), keyBytes);
        TestAssert.That(JsonNode.DeepEquals(expected, reopened.PersonalDecisionTargets(peer, decision, false)), "Full target proof did not survive reopen or was aliased.");
        var stale = decision.DeepClone().AsObject(); stale["decisions"]![0]!["expected_clock"]![0]!["counter"] = 3;
        TestAssert.That(reopened.PersonalDecisionTargets(peer, stale, false) is null &&
            reopened.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer("22222222-2222-4222-8222-222222222222"), decision, false) is null,
            "Stale or cross-run target proof was reused.");
        saved["expires_ms"] = 0; WriteMeta(saved);
        TestAssert.That(reopened.PersonalDecisionTargets(peer, decision, false) is null, "Expired native target proof authorized a transition.");
    }

    private static void ReviewVectors()
    {
        var cases = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/notes-actor-deletion-review.json"), "contracts", "notes-actor-deletion-review.json")))!["cases"]!.AsArray();
        TestAssert.That(cases.Count == 28, "Independent native review vectors missing.");
        foreach (var raw in cases)
        {
            var item = raw!.AsObject(); var before = TelefonCrypto.Canonical(item); var name = item["name"]!.GetValue<string>();
            var plan = item["plan"] as JsonObject; var native = item["native_intents"]!.AsArray(); var run = item["run_id"]!.GetValue<string>();
            if (item["valid"]!.GetValue<bool>())
            {
                var value = PersonalSyncActorContract.DeletionReview(run, plan, native);
                TestAssert.That(JsonNode.DeepEquals(value, PersonalSyncActorContract.DeletionReview(run, value, native)), "Native review is not stable: " + name);
                value["choices"]!.AsArray().Clear(); value["intents"]!.AsArray().Clear();
            }
            else TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.DeletionReview(run, plan, native), "Invalid native review accepted: " + name);
            TestAssert.That(before.SequenceEqual(TelefonCrypto.Canonical(item)), "Native review mutated its caller: " + name);
        }
    }

    private static void Check(string path, string mode)
    {
        var store = new TelefonStore(new WindowsPaths(path), Enumerable.Range(1, 32).Select(value => (byte)value).ToArray());
        var personal = new PersonalSyncStore(store); var peer = PersonalSyncActorContract.StoragePeer(Run);
        personal.RememberRun(peer, new JsonObject { ["format"] = 3, ["run_id"] = Run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") }, Now);
        JsonObject Message(string id, string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1, ["message_id"] = id,
            ["kind"] = kind, ["created_ms"] = Now, ["expires_ms"] = Now + 60000, ["body"] = body };
        var batchMessage = Message("77777777-7777-4777-8777-777777777777", "personal_sync.batch", new JsonObject {
            ["format"] = 3, ["run_id"] = Run, ["batch_id"] = "88888888-8888-4888-8888-888888888888", ["sequence"] = 0,
            ["last"] = true, ["reply"] = false, ["records_hash"] = PersonalSyncContract.RecordsHash(new JsonArray()), ["records"] = new JsonArray() });
        store.CommitIncoming(peer, batchMessage, Now, (_, _) => null, deferAcceptance: true);
        var batch = personal.StageBatch(peer, batchMessage, "wifi", Now)!;
        var references = new List<(string MessageId, string Token)>();
        foreach (var id in IntentIds)
        {
            var message = Message(id, "personal_sync.deletion_proposals", new JsonObject { ["format"] = 1, ["run_id"] = Run,
                ["proposal_batch_id"] = id, ["sequence"] = references.Count, ["last"] = references.Count == 1, ["proposals"] = new JsonArray() });
            store.CommitIncoming(peer, message, Now, (_, _) => null, deferAcceptance: true);
            var intent = personal.StageDecisionIntent(peer, message, "wifi", Now);
            references.Add((id, intent.CommitToken));
        }
        void Execute(string sql)
        {
            using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = sql; command.ExecuteNonQuery();
        }
        long Count(string sql)
        {
            using var connection = store.OpenDatabase(); connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = sql; return Convert.ToInt64(command.ExecuteScalar());
        }
        var selected = references.ToList();
        switch (mode)
        {
            case "partial": selected.RemoveAt(1); break;
            case "foreign_token": selected[1] = (selected[1].MessageId, "foreign"); break;
            case "extra": selected.Add((Run, "foreign")); break;
            case "duplicate": selected.Add(selected[0]); break;
            case "expired": Execute($"UPDATE personal_domain SET expires_ms=0 WHERE message_id='{IntentIds[1]}'"); break;
            case "foreign_run":
                using (var connection = store.OpenDatabase())
                {
                    connection.Open(); using var read = connection.CreateCommand(); read.CommandText = $"SELECT payload FROM personal_domain WHERE message_id='{IntentIds[1]}'";
                    var body = JsonNode.Parse(store.Open("personal_domain", IntentIds[1], (byte[])read.ExecuteScalar()!))!.AsObject();
                    body["body"]!["run_id"] = "22222222-2222-4222-8222-222222222222";
                    using var write = connection.CreateCommand(); write.CommandText = "UPDATE personal_domain SET payload=$data WHERE message_id=$id";
                    write.Parameters.AddWithValue("$id", IntentIds[1]); write.Parameters.AddWithValue("$data", store.Seal("personal_domain", IntentIds[1], TelefonCrypto.Canonical(body))); write.ExecuteNonQuery();
                }
                break;
            case "atomic": Execute($"CREATE TRIGGER actor_commit_failure BEFORE DELETE ON personal_domain WHEN OLD.message_id='{IntentIds[1]}' BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END"); break;
        }
        bool Commit(IReadOnlyList<(string MessageId, string Token)>? choices) => personal.CommitBatch(peer, batch.PendingMessageId, batch.CommitToken, Now, out _, choices);
        if (mode == "duplicate") TestAssert.Throws<InvalidDataException>(() => Commit(selected), "Duplicate native intent reference accepted.");
        else if (mode == "atomic") TestAssert.Throws<SqliteException>(() => Commit(selected), "Injected native failure did not abort the combined commit.");
        else TestAssert.That(!Commit(mode == "missing" ? null : selected), "Unreviewed/changed intent accepted: " + mode);
        TestAssert.That(Count("SELECT COUNT(*) FROM personal_batch") == 1 && Count("SELECT COUNT(*) FROM personal_domain") == 2 &&
            Count("SELECT COUNT(*) FROM dedupe WHERE result='accepted'") == 0 && Count("SELECT COUNT(*) FROM inbox WHERE state='processed'") == 0,
            "Partial batch/intent receipt survived failed native commit: " + mode);
        if (mode != "atomic") return;
        Execute("DROP TRIGGER actor_commit_failure"); selected.Reverse(); TestAssert.That(Commit(selected), "Exact native intents did not commit together.");
        var reopened = new TelefonStore(new WindowsPaths(path), Enumerable.Range(1, 32).Select(value => (byte)value).ToArray());
        var reopenedPersonal = new PersonalSyncStore(reopened);
        var remainingBatches = reopenedPersonal.ReadyBatches(Now).Count; var remainingIntents = reopenedPersonal.DecisionIntents(Now).Count;
        var accepted = Count("SELECT COUNT(*) FROM dedupe WHERE result='accepted'"); var processed = Count("SELECT COUNT(*) FROM inbox WHERE state='processed'");
        TestAssert.That(remainingBatches == 0 && remainingIntents == 0 && accepted == 3 && processed == 3 && !Commit(selected),
            $"Atomic native receipt counts changed: batches={remainingBatches}, intents={remainingIntents}, accepted={accepted}, processed={processed}.");
    }
}
