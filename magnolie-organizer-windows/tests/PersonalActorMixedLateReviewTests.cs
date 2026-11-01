using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

// Native primitive fixtures only. Actual mixed controllers remain blocked.
internal static class PersonalActorMixedLateReviewTests
{
    private const string Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static JsonObject Frame(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1, ["kind"] = kind,
        ["message_id"] = Guid.NewGuid().ToString("D"), ["created_ms"] = 1, ["expires_ms"] = 86400001, ["body"] = body };
    private static JsonObject Target(string kind, string id) => new() { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["id"] = id,
        ["parent_id"] = "", ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 }), ["prior_hash"] = new string('a', 64) };
    private static JsonObject DecisionFrame(JsonObject target, string choice) => PersonalSyncActorContract.WireMessage(Frame("personal_sync.deletion_decision", new JsonObject {
        ["format"] = 1, ["run_id"] = Run, ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = new JsonArray(new JsonObject {
            ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = choice, ["expected_clock"] = target["clock"]!.DeepClone() }) }), Run);
    internal static Task RunAsync()
    {
        foreach (var late in new[] { "delete", "restore" }) foreach (var initial in new[] { "delete", "restore" }) Exercise(late, initial, "complete");
        foreach (var fault in new[] { "missing-frame", "missing-target", "foreign-frame", "clock", "duplicate-frame", "duplicate-proposal", "duplicate-entity", "wrong-run", "direction-collision",
            "only-late", "only-fixed", "unrelated", "pinning" }) Exercise("delete", "delete", fault);
        return Task.CompletedTask;
    }
    private static void Exercise(string late, string initial, string scenario)
    {
        var lateTarget = Target("note", "canonical-parent"); var fixedTarget = Target("task", "selected-task");
        var incoming = DecisionFrame(lateTarget, late); var outgoing = DecisionFrame(fixedTarget, initial);
        var targets = new JsonArray(fixedTarget.DeepClone()); var frames = new List<JsonObject> { outgoing.DeepClone().AsObject() };
        var before = PhoneContentScope.Create(["canonical-parent"], ["selected-task"]);
        var notes = late == "delete" ? Array.Empty<string>() : ["canonical-parent"];
        var tasks = initial == "delete" ? Array.Empty<string>() : ["selected-task"];
        var actual = late == "restore" && initial == "restore" ? before : PhoneContentScope.Create(notes, tasks, revision: 2, epoch: Guid.NewGuid().ToString("D"));
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
        if (scenario is not ("complete" or "pinning"))
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
