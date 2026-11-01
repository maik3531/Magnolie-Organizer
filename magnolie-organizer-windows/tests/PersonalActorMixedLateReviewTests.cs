using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

// Native primitive fixtures only. Actual mixed controllers remain blocked.
internal static class PersonalActorMixedLateReviewTests
{
    private const string Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static JsonObject Frame(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["kind"] = kind, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["created_ms"] = now, ["expires_ms"] = now + (kind == PersonalSyncActorContract.AckKind ? 60000 : 86400000), ["body"] = body };
    }
    private static JsonObject Target(string kind, string id) => new() { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["id"] = id,
        ["parent_id"] = "", ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 }), ["prior_hash"] = new string('a', 64) };
    private static JsonObject DecisionFrame(JsonObject target, string choice) => PersonalSyncActorContract.WireMessage(Frame("personal_sync.deletion_decision", new JsonObject {
        ["format"] = 1, ["run_id"] = Run, ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = new JsonArray(new JsonObject {
            ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = choice, ["expected_clock"] = target["clock"]!.DeepClone() }) }), Run);
    internal static Task RunAsync()
    {
        foreach (var late in new[] { "delete", "restore" }) foreach (var initial in new[] { "delete", "restore" }) Exercise(late, initial, "complete");
        foreach (var late in new[] { "delete", "restore" }) Exercise(late, "delete", "parent-direction");
        foreach (var fault in new[] { "missing-frame", "missing-target", "foreign-frame", "clock", "duplicate-frame", "duplicate-proposal", "duplicate-entity", "wrong-run", "direction-collision",
            "only-late", "only-fixed", "unrelated", "pinning" }) Exercise("delete", "delete", fault);
        foreach (var scenario in new[] { "complete", "missing-frame", "missing-target", "duplicate-frame", "foreign-clock", "report-collision", "late-target-collision" })
            ExerciseReportOwner(scenario);
        return Task.CompletedTask;
    }
    private static JsonObject ReportFrame()
    {
        var zero = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0 };
        return PersonalSyncActorContract.WireMessage(Frame("personal_sync.report", new JsonObject { ["format"] = 3, ["run_id"] = Run, ["state"] = "complete",
            ["trigger"] = "manual", ["transport"] = "wifi", ["sent"] = zero.DeepClone(), ["received"] = zero.DeepClone(), ["conflicts"] = 0,
            ["attachments_omitted"] = 0, ["oversized_skipped"] = 0, ["started_ms"] = 1, ["finished_ms"] = 2, ["error"] = "none",
            ["attachments"] = new JsonObject { ["declared"] = 0, ["requested"] = 0, ["sent"] = 0, ["received"] = 0, ["reused"] = 0, ["preserved"] = 0, ["failed"] = 0, ["bytes"] = 0 },
            ["deletions"] = new JsonObject { ["pending"] = 0, ["deleted"] = 0, ["restored"] = 0, ["conflicts"] = 0, ["blocked"] = 0,
                ["trash"] = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0, ["attachments"] = 0 } } }), Run);
    }
    private static void ExerciseReportOwner(string scenario)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-mixed-report-owner-" + Guid.NewGuid().ToString("N"));
        try
        {
            var late = Target("note", "canonical-parent"); var initial = Target("task", "selected-task");
            var outgoing = DecisionFrame(initial, "delete"); var targets = new JsonArray(initial.DeepClone()); var frames = new List<JsonObject> { outgoing.DeepClone().AsObject() };
            var report = ReportFrame(); var before = PhoneContentScope.Create(["canonical-parent"], ["selected-task"]);
            var actual = PhoneContentScope.Create(["canonical-parent"], [], revision: 2, epoch: Guid.NewGuid().ToString("D"));
            var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.RecordSaved("mixed-report-owner", true, new string('a', 64));
            NativeBookSaveState? Saved() => owner.SaveState("mixed-report-owner", true);
            var store = new TelefonStore(new WindowsPaths(root), testStorageKey: Enumerable.Repeat((byte)37, 32).ToArray());
            var registry = new PersonalSyncActorStore(store, (_, _) => new string('a', 64));
            var handle = registry.Create(Actor, "ABCD-1234-5678-90EF", new string('a', 64), Run);
            if (scenario == "missing-frame") frames.Clear();
            if (scenario == "missing-target") targets.Clear();
            if (scenario == "duplicate-frame") frames.Add(frames[0].DeepClone().AsObject());
            if (scenario == "foreign-clock") frames[0]["body"]!["body"]!["decisions"]![0]!["expected_clock"]![0]!["counter"] = 9;
            if (scenario == "report-collision") frames[0]["message_id"] = report["message_id"]!.DeepClone();
            if (scenario == "late-target-collision") targets[0]!["proposal_id"] = late["proposal_id"]!.DeepClone();
            PersonalActorReportOwner Create() => new(Run, new JsonArray(late.DeepClone()), before, report, Saved()!, () => new string('b', 64),
                () => registry.ReadCompletionControls(handle), nativeFixedTargets: targets, fixedDecisionFrames: frames);
            if (scenario != "complete")
            { TestAssert.Throws<InvalidDataException>(() => Create(), "Mixed pre-report owner admitted unbound fixed evidence: " + scenario); return; }
            var waiting = Create(); var savedBefore = Saved();
            registry.BeginDecisionReview(handle, waiting.Validator);
            registry.CheckDecisionControlSend(handle, outgoing);
            TestAssert.Throws<InvalidOperationException>(() => registry.CheckDecisionReportSend(handle, report), "Report bypassed the original fixed decision send order.");
            var fixedAck = Frame(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Run, outgoing["message_id"]!.GetValue<string>()));
            registry.PutCompletionControl(handle, fixedAck);
            TestAssert.Throws<InvalidOperationException>(() => registry.CheckDecisionReportSend(handle, report), "A peer ACK manufactured the native fixed-decision send marker.");
            waiting.RecordSuccessfulFixedDecisionSend(outgoing); // Native send-marker fixture, not actual wire acceptance.
            registry.CheckDecisionReportSend(handle, report);
            TestAssert.Throws<InvalidDataException>(() => registry.CheckDecisionControlSend(handle, report), "Mixed fixed-control capability sent general report data.");
            TestAssert.Throws<InvalidDataException>(() => registry.CheckDecisionReportSend(handle, outgoing), "Report capability admitted fixed decisions through a general data lane.");
            var changed = outgoing.DeepClone().AsObject(); changed["body"]!["body"]!["decisions"]![0]!["decision"] = "restore";
            TestAssert.Throws<InvalidDataException>(() => registry.CheckDecisionControlSend(handle, changed), "Mixed owner sent a different original choice.");
            TestAssert.Throws<InvalidDataException>(() => waiting.RecordSuccessfulFixedDecisionSend(changed), "Native fixed-send marker accepted altered original bytes.");
            changed = outgoing.DeepClone().AsObject(); changed["message_id"] = Guid.NewGuid().ToString("D");
            TestAssert.Throws<InvalidDataException>(() => registry.CheckDecisionControlSend(handle, changed), "Mixed owner sent a different frame identity.");
            TestAssert.Throws<InvalidDataException>(() => waiting.RecordSuccessfulFixedDecisionSend(changed), "Native fixed-send marker accepted another frame identity.");
            TestAssert.That(Saved() == savedBefore && waiting.Validator("handoff", null) is null, "Fixed metadata send created a save or claimed terminal success.");
            TestAssert.Throws<InvalidOperationException>(() => registry.RequireCurrent(handle), "Mixed report owner reactivated original data rights.");
            TestAssert.That(!registry.PutCompletionControl(handle, fixedAck), "Fixed ACK replay was persisted twice.");
            TestAssert.Throws<InvalidOperationException>(() => waiting.BeginReview(() => actual, Saved), "Fixed decision ACK substituted for the ordinary report ACK.");
            registry.PutCompletionControl(handle, Frame(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Run, report["message_id"]!.GetValue<string>())));
            registry.PutCompletionControl(handle, DecisionFrame(late, "restore"));
            var review = waiting.BeginReview(() => actual, Saved); var view = review.Review();
            TestAssert.That(view["decisions"]!.AsArray().Count == 1 && view["fixed_decisions"]!.AsArray().Count == 1,
                "Mixed pre-report owner repeated fixed ordinary decisions as late mutations.");
            var claim = review.PrepareSave(view["revision"]!.GetValue<string>(), new string('c', 64));
            owner.RecordSaved("mixed-report-owner", true, new string('c', 64)); review.ConfirmSaved(claim["claim_token"]!.GetValue<string>());
            TestAssert.That(waiting.Validator("handoff", null) == true && registry.ReadCompletionControls(handle).OfType<JsonObject>().Any(value => JsonNode.DeepEquals(value, fixedAck)),
                "Mixed saved handoff lost the original fixed ACK direction or its separate SaveACK.");
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
    private static void Exercise(string late, string initial, string scenario)
    {
        var lateTarget = Target("note", "canonical-parent"); var fixedTarget = Target("task", "selected-task");
        if (scenario == "parent-direction")
        {
            lateTarget = Target("attachment", "gone"); lateTarget["parent_id"] = "canonical-parent";
            fixedTarget = Target("note", "canonical-parent");
        }
        var incoming = DecisionFrame(lateTarget, late); var outgoing = DecisionFrame(fixedTarget, initial);
        var targets = new JsonArray(fixedTarget.DeepClone()); var frames = new List<JsonObject> { outgoing.DeepClone().AsObject() };
        var before = PhoneContentScope.Create(["canonical-parent"], ["selected-task"]);
        var notes = late == "delete" ? Array.Empty<string>() : ["canonical-parent"];
        var tasks = initial == "delete" ? Array.Empty<string>() : ["selected-task"];
        var actual = late == "restore" && initial == "restore" ? before : PhoneContentScope.Create(notes, tasks, revision: 2, epoch: Guid.NewGuid().ToString("D"));
        if (scenario == "parent-direction") actual = PhoneContentScope.Create([], ["selected-task"], revision: 2, epoch: Guid.NewGuid().ToString("D"));
        var owner = new NativeBookOwnerScope(); owner.SetReady(true); owner.RecordSaved("mixed-native-review", true, new string('a', 64));
        NativeBookSaveState? Read() => owner.SaveState("mixed-native-review", true);
        var reportId = Guid.NewGuid().ToString("D"); var reportAck = Frame(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Run, reportId));
        PersonalActorPostDataReview Create() => new(Run, new JsonArray(lateTarget.DeepClone()), before, reportId, reportAck, () => new string('b', 64), () => actual,
            Read, () => new JsonArray(incoming.DeepClone()), nativeFixedTargets: targets, fixedDecisionFrames: frames);
        if (scenario == "missing-frame") frames.Clear();
        if (scenario == "missing-target") targets.Clear();
        if (scenario == "foreign-frame") frames[0]["body"]!["body"]!["decisions"]![0]!["proposal_id"] = Guid.NewGuid().ToString("D");
        if (scenario == "clock") frames[0]["body"]!["body"]!["decisions"]![0]!["expected_clock"]![0]!["counter"] = 9;
        if (scenario == "duplicate-frame") frames.Add(frames[0].DeepClone().AsObject());
        if (scenario == "duplicate-proposal") targets[0] = lateTarget.DeepClone();
        if (scenario == "duplicate-entity") { targets[0]!["kind"] = "note"; targets[0]!["id"] = "canonical-parent"; }
        if (scenario == "wrong-run") frames[0]["body"]!["body"]!["run_id"] = Guid.NewGuid().ToString("D");
        if (scenario == "direction-collision") frames[0]["message_id"] = incoming["message_id"]!.DeepClone();
        if (scenario == "only-late") actual = PhoneContentScope.Create([], ["selected-task"], revision: 2, epoch: Guid.NewGuid().ToString("D"));
        if (scenario == "only-fixed") actual = PhoneContentScope.Create(["canonical-parent"], [], revision: 2, epoch: Guid.NewGuid().ToString("D"));
        if (scenario == "unrelated") actual = PhoneContentScope.Create(["unrelated"], [], revision: 2, epoch: Guid.NewGuid().ToString("D"));
        if (scenario == "parent-direction" && late == "restore")
        { TestAssert.Throws<InvalidDataException>(() => Create().Review(), "Late attachment restore ignored its fixed deleted parent."); return; }
        if (scenario is not ("complete" or "pinning" or "parent-direction"))
        { TestAssert.Throws<InvalidDataException>(() => Create().Review(), "Native mixed review accepted an ambiguous/unbound fixed group: " + scenario); return; }
        var review = Create(); var observed = review.Review(); var revision = observed["revision"]!.GetValue<string>();
        TestAssert.That(observed["decisions"]!.AsArray().Count == 1 && observed["decisions"]![0]!["proposal_id"]!.GetValue<string>() == lateTarget["proposal_id"]!.GetValue<string>() &&
            observed["fixed_decisions"]![0]!["proposal_id"]!.GetValue<string>() == fixedTarget["proposal_id"]!.GetValue<string>() &&
            observed["frame_hashes"]!.AsObject().Count == 1 && observed["fixed_frame_hashes"]!.AsObject().Count == 1,
            "Native mixed scope union reintroduced initial choices as late document mutations.");
        if (scenario == "pinning")
        {
            frames[0]["body"]!["body"]!["decisions"]![0]!["decision"] = "restore"; targets[0]!["prior_hash"] = new string('f', 64);
            TestAssert.That(review.Review()["revision"]!.GetValue<string>() == revision, "Caller mutation changed pinned native fixed evidence.");
            frames[0] = outgoing.DeepClone().AsObject(); frames[0]["message_id"] = Guid.NewGuid().ToString("D"); targets[0] = fixedTarget.DeepClone();
            TestAssert.That(Create().Review()["revision"]!.GetValue<string>() != revision, "Different fixed original frame identity reused the saved review revision.");
            return;
        }
        var savedBefore = Read(); var claim = review.PrepareSave(revision, new string('c', 64));
        TestAssert.That(Read() == savedBefore && !claim["book_persisted"]!.GetValue<bool>(), "Native mixed union wrote or falsely persisted initial choices again.");
        owner.RecordSaved("mixed-native-review", true, new string('c', 64));
        var receipt = review.ConfirmSaved(claim["claim_token"]!.GetValue<string>());
        TestAssert.That(receipt["book_persisted"]!.GetValue<bool>() && !receipt["phone_persisted"]!.GetValue<bool>() && review.Validator("handoff", null) == true,
            "Mixed late save lacked its separate saved claim or falsely completed both receipt directions.");
        TestAssert.That(JsonNode.DeepEquals(receipt, review.ConfirmSaved(claim["claim_token"]!.GetValue<string>())), "Native mixed confirm retry changed its saved identity.");
    }
}
