using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorPostDataReviewTests
{
    private const string Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static JsonObject Frame(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1, ["kind"] = kind,
        ["message_id"] = Guid.NewGuid().ToString("D"), ["created_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        ["expires_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 60000, ["body"] = body };
    internal static Task RunAsync()
    {
        foreach (var scenario in new[] { "complete", "missing", "duplicate", "foreign", "clock", "frame-conflict", "ordinary-data", "scope", "authority", "writer",
            "token", "revision", "claim-hash", "wrong-save", "newer-writer", "source-change", "note-scope", "wrong-report", "wrong-run", "rejected", "registry", "source-race", "writer-race" })
            Exercise(scenario);
        return Task.CompletedTask;
    }

    private static void Exercise(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-post-data-review-" + Guid.NewGuid().ToString("N"));
        try
        {
            var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.RecordSaved("post-data-review-fixture", true, new string('a', 64));
            NativeBookSaveState? Read() => owner.SaveState("post-data-review-fixture", true);
            Func<NativeBookSaveState?> savedProvider = Read;
            var beforeSaved = Read(); var authority = new string('a', 64); var manifest = PhoneContentScope.Create(["parent"], []);
            var actualScope = manifest.DeepClone().AsObject(); var controls = new JsonArray(); var targets = new JsonArray();
            var choices = new List<JsonObject>();
            for (var i = 0; i < (scenario == "note-scope" ? 1 : 33); i++)
            {
                var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = i + 1 });
                var kind = scenario == "note-scope" ? "note" : "attachment";
                var id = scenario == "note-scope" ? "parent" : "file-" + i;
                var parent = scenario == "note-scope" ? "" : "parent";
                var proposalId = PersonalSyncContract.DeletionProposalId(Actor, kind, id, parent, clock, new string('a', 64));
                targets.Add(new JsonObject { ["proposal_id"] = proposalId, ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
                    ["prior_hash"] = new string('a', 64), ["clock"] = clock });
                choices.Add(new JsonObject { ["proposal_id"] = proposalId, ["decision"] = "delete", ["expected_clock"] = clock.DeepClone() });
            }
            foreach (var chunk in choices.OrderBy(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal).Chunk(32))
                controls.Add(PersonalSyncActorContract.WireMessage(Frame("personal_sync.deletion_decision", new JsonObject { ["format"] = 1,
                    ["run_id"] = Run, ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = new JsonArray(chunk.Cast<JsonNode>().ToArray()) }), Run));
            var reportId = Guid.NewGuid().ToString("D"); var ack = Frame(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Run, reportId));
            if (scenario == "wrong-report") ack["body"]!["message_id"] = Guid.NewGuid().ToString("D");
            if (scenario == "wrong-run") ack["body"]!["run_id"] = Guid.NewGuid().ToString("D");
            if (scenario == "rejected") { ack["body"]!["status"] = "rejected"; ack["body"]!["error"] = "temporary_failure"; }
            Func<JsonArray> persisted = () => controls.DeepClone().AsArray();
            PersonalActorPostDataReview Create() => new(Run, targets, manifest, reportId, ack, () => authority, () => actualScope, () => savedProvider(), () => persisted());
            if (scenario is "wrong-report" or "wrong-run" or "rejected")
            { TestAssert.Throws<InvalidOperationException>(() => Create(), "Post-data review accepted the wrong ordinary receipt: " + scenario); return; }
            var review = Create();
            if (scenario == "missing") controls.RemoveAt(1);
            if (scenario is "duplicate" or "frame-conflict")
            {
                var copy = controls[0]!.DeepClone();
                if (scenario == "duplicate") copy["message_id"] = Guid.NewGuid().ToString("D");
                else copy["body"]!["body"]!["decisions"]![0]!["decision"] = "restore";
                controls.Add(copy);
            }
            if (scenario == "foreign") controls[0]!["body"]!["body"]!["decisions"]![0]!["proposal_id"] = Guid.NewGuid().ToString("D");
            if (scenario == "clock") controls[0]!["body"]!["body"]!["decisions"]![0]!["expected_clock"]![0]!["counter"] = 9999;
            if (scenario == "ordinary-data") controls = new JsonArray(PersonalSyncActorContract.WireMessage(Frame("personal_sync.request", new JsonObject {
                ["format"] = 3, ["run_id"] = Run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") }), Run));
            if (scenario == "scope") actualScope = PhoneContentScope.Create(["unrelated"], []);
            if (scenario == "authority") authority = new string('c', 64);
            if (scenario == "writer") owner.RecordSaved("post-data-review-fixture", true, new string('a', 64));
            if (scenario is "missing" or "duplicate" or "foreign" or "clock" or "frame-conflict" or "ordinary-data" or "scope" or "authority" or "writer")
            {
                var denied = false;
                try { review.Review(); } catch (Exception error) when (error is InvalidOperationException or InvalidDataException) { denied = true; }
                TestAssert.That(denied, "Post-data review accepted changed/incomplete native evidence: " + scenario); return;
            }
            if (scenario == "source-race")
            {
                persisted = () => { authority = new string('c', 64); return controls.DeepClone().AsArray(); };
                TestAssert.Throws<InvalidOperationException>(() => review.Review(), "Source changed during protected metadata read."); return;
            }
            if (scenario == "note-scope")
            {
                TestAssert.Throws<InvalidDataException>(() => review.Review(), "Note-delete review accepted unadvanced original scope.");
                actualScope = PhoneContentScope.Create([], [], epoch: Guid.NewGuid().ToString("D"), revision: 2);
            }
            PersonalSyncActorStore? registry = null; PersonalActorHandle? handle = null;
            if (scenario == "registry")
            {
                var store = new TelefonStore(new WindowsPaths(root), testStorageKey: Enumerable.Repeat((byte)35, 32).ToArray());
                registry = new PersonalSyncActorStore(store, (_, _) => new string('a', 64));
                handle = registry.Create(Actor, "ABCD-1234-5678-90EF", new string('a', 64), Run);
                registry.BeginDecisionReview(handle, review.Validator);
                persisted = () => registry.ReadCompletionControls(handle);
                foreach (var control in controls.OfType<JsonObject>()) registry.PutCompletionControl(handle, control);
            }
            var view = review.Review(); var revision = view["revision"]!.GetValue<string>();
            var claim = review.PrepareSave(revision, new string('b', 64)); var token = claim["claim_token"]!.GetValue<string>();
            TestAssert.That(Read() == beforeSaved && !claim["book_persisted"]!.GetValue<bool>() && review.Validator("handoff", null) is null,
                "Separate review claim silently wrote data or completed without SaveACK.");
            if (scenario is "revision" or "claim-hash")
            { TestAssert.Throws<InvalidOperationException>(() => review.PrepareSave(scenario == "revision" ? new string('f', 64) : revision,
                scenario == "claim-hash" ? new string('c', 64) : new string('b', 64)), "Review claim rebound a different candidate."); return; }
            TestAssert.Throws<InvalidOperationException>(() => review.ConfirmSaved(token), "Review claim accepted the old ordinary data SaveACK.");
            owner.RecordSaved("post-data-review-fixture", true, new string(scenario == "wrong-save" ? 'c' : 'b', 64));
            if (scenario == "source-change") authority = new string('c', 64);
            if (scenario == "writer-race")
            {
                var calls = 0;
                savedProvider = () => {
                    if (++calls == 2) owner.RecordSaved("post-data-review-fixture", true, new string('b', 64));
                    return Read();
                };
                TestAssert.Throws<InvalidOperationException>(() => review.ConfirmSaved(token), "Writer changed during native SaveACK confirmation."); return;
            }
            if (scenario is "token" or "wrong-save" or "source-change")
            { TestAssert.Throws<InvalidOperationException>(() => review.ConfirmSaved(scenario == "token" ? new string('f', 64) : token), "Review save accepted an unbound receipt."); return; }
            TestAssert.That(review.Validator("maintain", null) is null, "In-flight SaveACK prematurely completed or retired review.");
            registry?.Reap();
            var receipt = review.ConfirmSaved(token);
            TestAssert.That(receipt["book_persisted"]!.GetValue<bool>() && !receipt["phone_persisted"]!.GetValue<bool>() && review.Validator("handoff", null) == true,
                "Explicit review SaveACK receipt was missing or falsely confirmed both endpoints.");
            TestAssert.That(JsonNode.DeepEquals(receipt, review.ConfirmSaved(token)), "Save confirmation retry changed its native claim.");
            if (scenario == "newer-writer")
            {
                owner.RecordSaved("post-data-review-fixture", true, new string('b', 64));
                TestAssert.Throws<InvalidOperationException>(() => review.ConfirmSaved(token), "New same-byte writer rebound saved review."); return;
            }
            if (registry is not null && handle is not null)
            {
                bool? Completion(string operation, JsonObject? wire) => true; // Registry boundary, not receipt proof.
                registry.PromoteDecisionReview(handle, review.Validator, Completion);
                registry.PromoteDecisionReview(handle, review.Validator, Completion);
                TestAssert.Throws<InvalidOperationException>(() => registry.RequireCurrent(handle), "Review save reopened original data owner.");
            }
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
