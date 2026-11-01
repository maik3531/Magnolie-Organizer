using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

// Native atomic fixed-group primitive only; no actual mixed transport/GUI proof.
internal static class PersonalActorFixedDecisionGroupTests
{
    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "magnolie-fixed-group-" + Guid.NewGuid().ToString("N"));
        internal readonly string Peer = Guid.NewGuid().ToString("D"), Run = Guid.NewGuid().ToString("D");
        internal readonly TelefonStore Store;
        internal readonly NativeBookOwnerScope Owner = new();
        internal readonly JsonObject[] Choices;
        internal string Source = new('c', 64);
        internal string Private => PersonalSyncActorContract.StoragePeer(Run);
        internal NativeBookSaveState Claim => Owner.SaveState("native-fixed-group", true)!;
        internal Fixture(int count = 33)
        {
            Store = new TelefonStore(new WindowsPaths(Root), testStorageKey: Enumerable.Repeat((byte)38, 32).ToArray());
            Owner.SetReady(true); Owner.RecordSaved("native-fixed-group", true, new string('b', 64));
            var proposals = Enumerable.Range(0, count).Select(index => new JsonObject { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = "task", ["id"] = "native-task-" + index,
                ["parent_id"] = "", ["prior_hash"] = new string('a', 64), ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Peer, ["counter"] = 1 }),
                ["deleted_ms"] = 2, ["label"] = "Synthetic native target" }).OrderBy(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal).ToArray();
            var sequence = 0;
            foreach (var chunk in proposals.Chunk(32))
            {
                Store.RememberPersonalProposalKinds(Private, new JsonObject { ["format"] = 1, ["run_id"] = Run, ["proposal_batch_id"] = Run,
                    ["sequence"] = sequence, ["last"] = ++sequence == (count + 31) / 32, ["proposals"] = new JsonArray(chunk.Select(value => (JsonNode)value.DeepClone()).ToArray()) }, false);
            }
            Choices = proposals.Select(value => new JsonObject { ["proposal_id"] = value["proposal_id"]!.DeepClone(), ["decision"] = "delete", ["expected_clock"] = value["clock"]!.DeepClone() }).ToArray();
        }
        internal IReadOnlyList<JsonObject> Prepare(IReadOnlyList<JsonObject>? choices = null, string? expectedSource = null,
            Func<string?>? currentSource = null, Func<NativeBookSaveState?>? currentClaim = null) =>
            Store.QueueActorFixedDecisions(Peer, Run, choices ?? Choices, expectedSource ?? new string('c', 64), Claim, currentSource ?? (() => Source), currentClaim ?? (() => Claim));
        internal long LedgerCount()
        {
            using var db = Store.OpenDatabase(); db.Open(); using var count = db.CreateCommand();
            count.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_actor_fixed:%'"; return Convert.ToInt64(count.ExecuteScalar());
        }
        internal long OutboxCount()
        {
            using var db = Store.OpenDatabase(); db.Open(); using var count = db.CreateCommand(); count.CommandText = "SELECT COUNT(*) FROM outbox";
            return Convert.ToInt64(count.ExecuteScalar());
        }
        internal void MutateRecord(string category, string key, Action<JsonObject> mutate)
        {
            using var db = Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM meta WHERE key=$key"; read.Parameters.AddWithValue("$key", key);
            var clear = Store.Open(category, key, (byte[])read.ExecuteScalar()!);
            try
            {
                var value = JsonNode.Parse(clear)!.AsObject(); mutate(value);
                using var write = db.CreateCommand(); write.CommandText = "UPDATE meta SET value=$value WHERE key=$key"; write.Parameters.AddWithValue("$key", key);
                write.Parameters.AddWithValue("$value", Store.Seal(category, key, TelefonCrypto.Canonical(value))); write.ExecuteNonQuery();
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }
        public void Dispose() { SqliteConnection.ClearAllPools(); if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }

    internal static Task RunAsync()
    {
        using (var f = new Fixture())
        {
            var before = f.Claim; var frames = f.Prepare();
            TestAssert.That(frames.Count == 2 && PersonalSyncActorContract.Unwrap(frames[0]["body"]!.AsObject()).Body["decisions"]!.AsArray().Count == 32 &&
                JsonNode.DeepEquals(new JsonArray(frames.Select(value => (JsonNode)value.DeepClone()).ToArray()), new JsonArray(f.Prepare().Select(value => (JsonNode)value.DeepClone()).ToArray())),
                "Native fixed decision group was incomplete or changed on retry.");
            foreach (var wire in frames)
            {
                var id = wire["message_id"]!.GetValue<string>(); TestAssert.That(JsonNode.DeepEquals(f.Store.OutboxMessage(f.Peer, id), wire), "Fixed control outbox changed original bytes.");
                f.Store.CompleteOutbox(f.Peer, id);
            }
            TestAssert.That(f.OutboxCount() == 0 && f.Claim == before && f.Prepare().Select(value => value["message_id"]!.GetValue<string>()).SequenceEqual(frames.Select(value => value["message_id"]!.GetValue<string>())) &&
                f.OutboxCount() == 0, "Native fixed success replay requeued ACKed originals or repeated a saved claim.");
        }
        using (var f = new Fixture())
        {
            using var db = f.Store.OpenDatabase(); db.Open(); using var fault = db.CreateCommand();
            fault.CommandText = "CREATE TRIGGER fixed_group_fault BEFORE INSERT ON outbox WHEN (SELECT COUNT(*) FROM outbox WHERE kind='personal_sync.deletion_decision')>=1 BEGIN SELECT RAISE(ABORT,'synthetic partial fixed group fault'); END"; fault.ExecuteNonQuery();
            TestAssert.Throws<SqliteException>(() => f.Prepare(), "Partial fixed group SQL fault was ignored.");
            TestAssert.That(f.OutboxCount() == 0 && f.LedgerCount() == 0, "Failed fixed group left half an outbox or protected success identity.");
            using var drop = db.CreateCommand(); drop.CommandText = "DROP TRIGGER fixed_group_fault"; drop.ExecuteNonQuery();
            TestAssert.That(f.Prepare().Count == 2, "Clean SQL retry did not atomically prepare the whole group.");
        }
        foreach (var scenario in new[] { "missing", "clock", "duplicate", "unsorted", "empty", "extra-field", "foreign-source", "missing-claim", "source-race", "claim-race" })
        {
            using var f = new Fixture(); var values = f.Choices.Select(value => value.DeepClone().AsObject()).ToArray();
            if (scenario == "missing") { values[0]["proposal_id"] = Guid.NewGuid().ToString("D"); values = values.OrderBy(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal).ToArray(); }
            if (scenario == "clock") values[0]["expected_clock"]![0]!["counter"] = 9;
            if (scenario == "duplicate") { values[^1] = values[0].DeepClone().AsObject(); values = values.OrderBy(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal).ToArray(); }
            if (scenario == "unsorted") Array.Reverse(values);
            if (scenario == "empty") values = [];
            if (scenario == "extra-field") values[0]["allow_conflict"] = true;
            if (scenario == "foreign-source") f.Source = new string('d', 64);
            var calls = 0;
            string? Source()
            {
                if (++calls == 2)
                {
                    if (scenario == "source-race") f.Source = new string('d', 64);
                    if (scenario == "claim-race") f.Owner.RecordSaved("native-fixed-group", true, new string('e', 64));
                }
                return f.Source;
            }
            var denied = false;
            try { f.Prepare(values, currentSource: Source, currentClaim: scenario == "missing-claim" ? () => null : () => f.Claim); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { denied = true; }
            TestAssert.That(denied && f.OutboxCount() == 0 && f.LedgerCount() == 0, "Native fixed evidence/race created a partial group: " + scenario);
        }
        foreach (var scenario in new[] { "decision", "source", "new-claim", "kind-only", "created_ms", "type", "v" })
        {
            using var f = new Fixture(1); var original = f.Prepare(); f.Store.CompleteOutbox(f.Peer, original[0]["message_id"]!.GetValue<string>());
            var values = f.Choices.Select(value => value.DeepClone().AsObject()).ToArray(); var expected = new string('c', 64);
            if (scenario == "decision") values[0]["decision"] = "restore";
            if (scenario == "source") { f.Source = new string('d', 64); expected = f.Source; }
            if (scenario == "new-claim") f.Owner.RecordSaved("native-fixed-group", true, new string('b', 64));
            if (scenario == "kind-only") f.MutateRecord("personal_proposal_kind", $"personal_proposal_kind:{f.Private}:in:{values[0]["proposal_id"]!.GetValue<string>()}", value => value.Remove("target"));
            if (scenario is "created_ms" or "type" or "v") f.MutateRecord("personal_actor_fixed", $"personal_actor_fixed:{f.Private}:{f.Run}", value => {
                value["frames"]![0]![scenario] = scenario == "created_ms" ? JsonValue.Create(1) : scenario == "v" ? JsonValue.Create(true) : JsonValue.Create("caller-message");
            });
            var denied = false;
            try { f.Prepare(values, expectedSource: expected); } catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { denied = true; }
            TestAssert.That(denied && f.OutboxCount() == 0, "Protected fixed replay rebound changed original evidence or requeued an ACKed control: " + scenario);
        }
        using (var f = new Fixture(1))
        {
            var original = f.Prepare(); var otherRun = Guid.NewGuid().ToString("D"); var otherPrivate = PersonalSyncActorContract.StoragePeer(otherRun);
            var proof = f.Store.PersonalDecisionTargets(f.Private, new JsonObject { ["format"] = 1, ["run_id"] = f.Run, ["decision_id"] = f.Run,
                ["decisions"] = new JsonArray(f.Choices.Select(value => (JsonNode)value.DeepClone()).ToArray()) }, true)![0]!.DeepClone().AsObject();
            proof["deleted_ms"] = 2; proof["label"] = "Other private run";
            f.Store.RememberPersonalProposalKinds(otherPrivate, new JsonObject { ["format"] = 1, ["run_id"] = otherRun, ["proposal_batch_id"] = otherRun, ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(proof) }, false);
            var other = f.Store.QueueActorFixedDecisions(f.Peer, otherRun, f.Choices, new string('c', 64), f.Claim, () => f.Source, () => f.Claim);
            var unrelated = f.Store.Enqueue(f.Peer, "personal_sync.request", new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual", ["modules"] = new JsonArray("tasks") }, 60000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            new PersonalSyncStore(f.Store).PurgeProtocol(f.Private);
            TestAssert.That(original.All(value => f.Store.OutboxMessage(f.Peer, value["message_id"]!.GetValue<string>()) is null) &&
                other.All(value => JsonNode.DeepEquals(f.Store.OutboxMessage(f.Peer, value["message_id"]!.GetValue<string>()), value)) && f.Store.OutboxMessage(f.Peer, unrelated) is not null && f.LedgerCount() == 1,
                "Private fixed-group cleanup deleted another run/ordinary peer packet or left its own group orphaned.");
        }
        return Task.CompletedTask;
    }
}
