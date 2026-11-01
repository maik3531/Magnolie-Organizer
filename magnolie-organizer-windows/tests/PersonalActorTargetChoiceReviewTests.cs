using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorTargetChoiceReviewTests
{
    private const string Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static void Rejected(Action action, string message)
    {
        try { action(); } catch (Exception error) when (error is InvalidDataException or InvalidOperationException or ArgumentException) { return; }
        throw new InvalidOperationException(message);
    }
    internal static Task RunAsync()
    {
        var catalog = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/notes-actor-target-choice-draft-v1-vectors.json"),
            "contracts", "notes-actor-target-choice-draft-v1-vectors.json")))!;
        foreach (var kind in new[] { "note", "task", "attachment" })
        foreach (var scenario in new[] { "delete", "restore", "missing-confirm", "false", "numeric-true", "string-true", "clock", "foreign", "unknown", "missing", "extra",
            "source", "scope", "save", "frame", "frame-race", "optimistic", "metadata", "content", "revision", "input-mutation", "pending-delete", "pending-restore" })
        {
            var parent = kind == "attachment" ? "own-note" : ""; var id = kind == "task" ? "own-task" : kind == "attachment" ? "own-file" : "own-note";
            var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 });
            var target = new JsonObject { ["proposal_id"] = "66666666-6666-4666-8666-666666666666", ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
                ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() };
            var proposal = target.DeepClone().AsObject(); proposal["deleted_ms"] = 0; proposal["label"] = "PRIVATE LABEL";
            var body = new JsonObject { ["format"] = 1, ["run_id"] = Run, ["proposal_batch_id"] = Run, ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(proposal) };
            var frame = PersonalSyncActorContract.WireMessage(new JsonObject { ["type"] = "message", ["v"] = 1,
                ["message_id"] = "55555555-5555-4555-8555-555555555555", ["kind"] = "personal_sync.deletion_proposals", ["created_ms"] = 100, ["expires_ms"] = 1000, ["body"] = body }, Run);
            var before = PhoneContentScope.Create([], [], epoch: Run); var scope = before.DeepClone().AsObject();
            var saved = new NativeBookSaveState(new string('c', 64), 1, new string('d', 64)); var originalSaved = saved;
            var source = new string('b', 64); var observations = 0;
            IReadOnlyList<JsonObject> Observe(IReadOnlyList<JsonObject> targets)
            {
                observations++;
                if (scenario == "input-mutation") targets[0]["id"] = "changed-native-input";
                var value = new JsonObject { ["target"] = targets.Single().DeepClone(), ["local_state"] = scenario.StartsWith("pending-", StringComparison.Ordinal) ? "deleted" : "live", ["local_hash"] = new string('a', 64),
                    ["local_clock"] = clock.DeepClone(), ["native_saved_book"] = new JsonObject { ["book_source"] = saved.BookSource, ["sequence"] = saved.Sequence, ["sha256"] = saved.Sha256 },
                    ["metadata_matches"] = true, ["requires_conflict_choice"] = true };
                if (scenario == "optimistic") value["requires_conflict_choice"] = false;
                if (scenario == "metadata") value["metadata_matches"] = false;
                if (scenario == "content") value["content"] = "PRIVATE";
                if (scenario == "frame-race") frame["body"]!["body"]!["proposals"]![0]!["label"] = "Changed after protected read";
                return [value];
            }
            var review = new PersonalActorIncomingTargetChoiceReview(Run, () => [frame.DeepClone().AsObject()], Observe, () => source, () => scope, () => saved);
            if (scenario is "optimistic" or "metadata" or "content" or "frame-race" or "input-mutation")
            { Rejected(() => review.Review(), "Unsafe observation/frame-race became a review: " + scenario); continue; }
            var view = review.Review();
            var choice = new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = scenario.EndsWith("restore", StringComparison.Ordinal) ? "restore" : "delete",
                ["expected_clock"] = clock.DeepClone(), ["confirm_conflict"] = true };
            switch (scenario)
            {
                case "missing-confirm": choice.Remove("confirm_conflict"); break;
                case "false": choice["confirm_conflict"] = false; break;
                case "numeric-true": choice["confirm_conflict"] = 1; break;
                case "string-true": choice["confirm_conflict"] = "true"; break;
                case "clock": choice["expected_clock"]![0]!["counter"] = 2; break;
                case "foreign": choice["proposal_id"] = Run; break;
                case "unknown": choice["decision"] = "accept"; break;
                case "extra": choice["action_authorized"] = true; break;
                case "source": source = new string('f', 64); break;
                case "scope": scope = PhoneContentScope.Create(["different"], []); break;
                case "save": saved = originalSaved with { Sequence = 2 }; break;
                case "frame": frame["body"]!["body"]!["proposals"]![0]!["label"] = "Changed protected bytes"; break;
            }
            var revision = view["revision"]!.GetValue<string>();
            if (scenario is not ("delete" or "restore" or "pending-delete" or "pending-restore"))
            { Rejected(() => review.DraftChoices(scenario == "revision" ? new string('f', 64) : revision, scenario == "missing" ? [] : [choice]), "Implicit/stale choice became a draft: " + scenario); continue; }
            var draft = review.DraftChoices(revision, [choice]); var repeat = review.DraftChoices(revision, [choice]);
            var vector = catalog[scenario.StartsWith("pending-", StringComparison.Ordinal) ? "pending_cases" : "cases"]!.AsArray().OfType<JsonObject>()
                .Single(value => value["kind"]!.GetValue<string>() == kind);
            TestAssert.That(revision == vector["review_revision"]!.GetValue<string>() &&
                draft["choice_revision"]!.GetValue<string>() == vector[choice["decision"]!.GetValue<string>() + "_choice_revision"]!.GetValue<string>(),
                "Private native choice-draft revision disagreed with the shared canonical vectors.");
            TestAssert.That(JsonNode.DeepEquals(draft, repeat) && draft["action_authorized"]!.GetValue<bool>() == false &&
                view["action_authorized"]!.GetValue<bool>() == false && draft["conflicts_explicitly_confirmed"]!.GetValue<bool>() &&
                JsonNode.DeepEquals(draft["content_scope"], before) && !draft.ToJsonString().Contains("PRIVATE") && !view.ToJsonString().Contains("PRIVATE") && observations == 3,
                "Native choice draft changed data scope, leaked content or invented action rights.");
            draft["decisions"]![0]!["decision"] = "forged";
            TestAssert.That(JsonNode.DeepEquals(repeat, review.DraftChoices(revision, [choice])), "Returned mutation changed native pinned choices.");
        }
        ParentChildChoices();
        return Task.CompletedTask;
    }

    private static void ParentChildChoices()
    {
        foreach (var parentChoice in new[] { "delete", "restore" }) foreach (var childChoice in new[] { "delete", "restore" })
        {
            var clock = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 });
            var parent = new JsonObject { ["proposal_id"] = "66666666-6666-4666-8666-666666666666", ["kind"] = "note", ["id"] = "own-note",
                ["parent_id"] = "", ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() };
            var child = parent.DeepClone().AsObject(); child["proposal_id"] = "77777777-7777-4777-8777-777777777777";
            child["kind"] = "attachment"; child["id"] = "own-file"; child["parent_id"] = "own-note";
            var proposals = new JsonArray();
            foreach (var target in new[] { parent, child }) { var proposal = target.DeepClone().AsObject(); proposal["deleted_ms"] = 0; proposal["label"] = ""; proposals.Add(proposal); }
            var body = new JsonObject { ["format"] = 1, ["run_id"] = Run, ["proposal_batch_id"] = Run, ["sequence"] = 0, ["last"] = true, ["proposals"] = proposals };
            var frame = new JsonObject { ["kind"] = PersonalSyncActorContract.DataKind, ["message_id"] = "55555555-5555-4555-8555-555555555555",
                ["body"] = PersonalSyncActorContract.Wrap(Run, "personal_sync.deletion_proposals", body) };
            var scope = PhoneContentScope.Create([], [], epoch: Run);
            var saved = new NativeBookSaveState(new string('c', 64), 1, new string('d', 64));
            IReadOnlyList<JsonObject> Observe(IReadOnlyList<JsonObject> targets) => targets.Select(target => new JsonObject {
                ["target"] = target.DeepClone(), ["local_state"] = "live", ["local_hash"] = new string('a', 64), ["local_clock"] = clock.DeepClone(),
                ["native_saved_book"] = new JsonObject { ["book_source"] = saved.BookSource, ["sequence"] = saved.Sequence, ["sha256"] = saved.Sha256 },
                ["metadata_matches"] = true, ["requires_conflict_choice"] = true }).ToArray();
            var review = new PersonalActorIncomingTargetChoiceReview(Run, () => [frame], Observe, () => new string('b', 64), () => scope, () => saved);
            var revision = review.Review()["revision"]!.GetValue<string>();
            var choices = new[] { (Target: parent, Decision: parentChoice), (Target: child, Decision: childChoice) }.Select(value => new JsonObject {
                ["proposal_id"] = value.Target["proposal_id"]!.DeepClone(), ["decision"] = value.Decision, ["expected_clock"] = clock.DeepClone(), ["confirm_conflict"] = true }).ToArray();
            if (parentChoice == "delete" && childChoice == "restore")
                Rejected(() => review.DraftChoices(revision, choices), "Child restore under a deleted parent became a confirmed draft.");
            else TestAssert.That(review.DraftChoices(revision, choices)["action_authorized"]!.GetValue<bool>() == false,
                "Compatible pair draft acquired action authority.");
        }
    }
}
