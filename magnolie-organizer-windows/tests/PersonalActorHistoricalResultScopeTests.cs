using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

// Metadata correlation only, not native save/origin/mutation acceptance.
internal static class PersonalActorHistoricalResultScopeTests
{
    private const string Run = "44444444-4444-4444-8444-444444444444", Actor = "11111111-1111-4111-8111-111111111111";
    private static JsonObject Target(string kind = "note", string id = "historical-target", string parent = "") => new() {
        ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["id"] = id, ["parent_id"] = parent,
        ["prior_hash"] = new string('a', 64), ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Actor, ["counter"] = 1 }) };
    private static JsonObject Choice(JsonObject target, string decision) => new() {
        ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = decision, ["expected_clock"] = target["clock"]!.DeepClone() };
    private static JsonArray Array(params JsonObject[] values) => new(values.Select(value => (JsonNode)value.DeepClone()).ToArray());
    private static JsonObject Frame(string kind, JsonObject body) => new() { ["type"] = "message", ["v"] = 1,
        ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["created_ms"] = 100, ["expires_ms"] = 1000, ["body"] = body.DeepClone() };

    internal static Task RunAsync()
    {
        foreach (var kind in new[] { "note", "task", "attachment" }) foreach (var decision in new[] { "delete", "restore" })
        {
            var before = PhoneContentScope.Create(["data-note"], ["data-task"]);
            var target = Target(kind, parent: kind == "attachment" ? "historical-parent" : "");
            var members = PersonalSyncActorContract.HistoricalCompletionMembers(Run, before, Array(target), Array(Choice(target, decision)), Array(target));
            TestAssert.That(JsonNode.DeepEquals(members, before["members"]), "Historical action widened/reduced original data membership.");
            PersonalSyncActorContract.RequireHistoricalCompletionScope(Run, before, Array(target), Array(Choice(target, decision)), Array(target), before);
            var advanced = PhoneContentScope.Advance(before, ["data-note", kind == "attachment" ? "historical-parent" : "historical-target"], ["data-task"]);
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.RequireHistoricalCompletionScope(Run, before,
                Array(target), Array(Choice(target, decision)), Array(target), advanced), "Historical result inherited new data membership.");
        }
        foreach (var fault in new[] { "data-target", "changed-proof", "foreign-proof", "duplicate-proof", "missing-decision", "changed-clock", "duplicate-target" })
        {
            var before = PhoneContentScope.Create(["data-note"], ["data-task"]); var target = Target();
            if (fault == "data-target") target["id"] = "data-note";
            var targets = Array(target); var historical = Array(target); var choices = Array(Choice(target, "restore"));
            if (fault == "changed-proof") historical[0]!["prior_hash"] = new string('b', 64);
            if (fault == "foreign-proof") historical = Array(Target());
            if (fault == "duplicate-proof") historical.Add(target.DeepClone());
            if (fault == "missing-decision") choices.Clear();
            if (fault == "changed-clock") choices[0]!["expected_clock"]![0]!["counter"] = 2;
            if (fault == "duplicate-target") { var duplicate = target.DeepClone().AsObject(); duplicate["proposal_id"] = Guid.NewGuid().ToString("D"); targets.Add(duplicate); choices.Add(Choice(duplicate, "restore")); }
            TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.HistoricalCompletionMembers(Run, before, targets, choices, historical), "Unproved historical classification survived: " + fault);
        }
        var parent = Target(id: "historical-parent"); var child = Target("attachment", "historical-child", "historical-parent");
        TestAssert.Throws<InvalidDataException>(() => PersonalSyncActorContract.HistoricalCompletionMembers(Run, PhoneContentScope.Create(["data-note"], []),
            Array(parent, child), Array(Choice(parent, "delete"), Choice(child, "restore")), Array(parent, child)), "Historical child survived deleted parent.");
        MixedReceiptUnion();
        return Task.CompletedTask;
    }

    private static void MixedReceiptUnion()
    {
        var before = PhoneContentScope.Create(["data-note"], ["data-task"]); var data = Target(id: "data-note"); var historical = Target("task");
        var targets = Array(data, historical); var decisions = new[] { Choice(data, "delete"), Choice(historical, "restore") };
        var members = PersonalSyncActorContract.HistoricalCompletionMembers(Run, before, targets, Array(decisions), Array(historical));
        var after = PhoneContentScope.Advance(before, [], ["data-task"]);
        TestAssert.That(JsonNode.DeepEquals(members, after["members"]), "Mixed result did not keep historical rights separate.");
        var wires = decisions.Select(choice => PersonalSyncActorContract.WireMessage(Frame("personal_sync.deletion_decision", new JsonObject {
            ["format"] = 1, ["run_id"] = Run, ["decision_id"] = Guid.NewGuid().ToString("D"), ["decisions"] = Array(choice) }), Run)).ToArray();
        var acks = wires.Select(wire => Frame(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(Run, wire["message_id"]!.GetValue<string>()))).ToArray();
        var retained = new JsonArray(); var saved = new NativeBookSaveState(new string('b', 64), 2, new string('c', 64));
        var completion = new PersonalActorDecisionCompletion(Run, targets, wires, () => new string('d', 64), () => after, () => saved,
            () => retained.DeepClone().AsArray(), nativeSentAcknowledgments: [acks[1]], beforeScope: before, nativeHistoricalTargets: Array(historical));
        TestAssert.That(completion.Validator("begin", null) == true, "Mixed completion could not correlate its separate membership.");
        retained.Add(acks[0].DeepClone()); completion.RecordPersisted(acks[0]);
        TestAssert.That(completion.Summary()["saved"]!.GetValue<int>() == 1 && completion.Validator("finish", null) != true, "A data ACK completed the historical target too.");
        retained.Add(acks[1].DeepClone());
        TestAssert.Throws<InvalidOperationException>(() => completion.RecordPersisted(acks[1]), "Unsent native historical ACK counted as persisted.");
        TestAssert.That(completion.Validator("finish", null) != true, "Stored but unsent historical ACK completed its target.");
        completion.RecordSuccessfulAcknowledgmentSend(acks[1]); completion.RecordPersisted(acks[1]);
        TestAssert.That(completion.Validator("finish", null) == true && completion.Summary()["saved"]!.GetValue<int>() == 2, "Exact separate receipt union did not finish.");
    }
}
