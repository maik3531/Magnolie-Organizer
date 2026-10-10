using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneContentScopeTests
{
    private static JsonObject Record(string kind, string id, string text = "", string notebook = "") => new()
    { ["kind"] = kind, ["id"] = id, ["state"] = "live", ["value"] = new JsonObject { ["text"] = text, ["notebook_id"] = notebook } };

    internal static Task RunAsync()
    {
        var golden = PhoneContentScope.Create(["mobile-note", "\ue000", "😀"], ["mobile-task"], 7, "44444444-4444-4444-8444-444444444444");
        TestAssert.That(golden["scope_hash"]!.GetValue<string>() == "589f36e8c7d673b4e24e3bebc8a020441d9e313a465f2f8f011b9cebb596fdc2",
            "Scope hash or UTF-8 identity ordering disagrees with the Python golden.");
        var manifest = PhoneContentScope.Create(["mobile-note"], ["mobile-task"]);
        var records = new[] { Record("note", "mobile-note", "Organizer addition", "shared-book"),
            Record("note", "organizer-only", "Private organizer text", "private-book"), Record("task", "mobile-task"),
            Record("task", "organizer-task"), Record("notebook", "shared-book"), Record("notebook", "private-book") };
        var selected = PhoneContentScope.FilterRecords(records, manifest);
        TestAssert.That(selected.Select(record => record["id"]!.GetValue<string>()).SequenceEqual(new[] { "mobile-note", "mobile-task", "shared-book" }) &&
            selected[0]["value"]!["text"]!.GetValue<string>() == "Organizer addition", "Existing phone content updates were lost or unrelated organizer content leaked.");
        var before = new JsonArray(records.Select(record => record.DeepClone()).ToArray());
        var removed = PhoneContentScope.Advance(manifest, [], []);
        TestAssert.That(PhoneContentScope.FilterRecords(records, removed).Count == 0 &&
            JsonNode.DeepEquals(before, new JsonArray(records.Select(record => record.DeepClone()).ToArray())),
            "Phone removal deleted organizer copies or authorized reintroduction.");
        TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.RequireCurrent(PhoneContentScope.Reference(manifest), removed), "Stale scope reply was accepted.");
        PhoneContentScope.RequireCurrent(PhoneContentScope.Reference(removed), removed);
        TestAssert.That(ReferenceEquals(manifest, PhoneContentScope.Advance(manifest, ["mobile-note"], ["mobile-task"])), "Unchanged scope rotated generation.");
        var large = PhoneContentScope.Create(Enumerable.Range(0, 1300).Select(n => $"note-{n:D5}"), Enumerable.Range(0, 700).Select(n => $"task-{n:D5}"));
        var chunks = PhoneContentScope.Chunks(large);
        TestAssert.That(chunks.Count > 1 && chunks.All(part => part["members"]!.AsArray().Count <= 256) &&
            JsonNode.DeepEquals(large, PhoneContentScope.Assemble(chunks.Reverse().Concat([chunks[0].DeepClone().AsObject()]))),
            "Large scope did not use bounded chunks or duplicate/out-of-order delivery changed it.");
        TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.Assemble(chunks.SkipLast(1)), "Incomplete scope was accepted.");
        TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.Assemble([chunks[0], PhoneContentScope.Chunks(removed)[0]]), "Mixed scope generations were accepted.");
        var changed = chunks[0].DeepClone().AsObject(); changed["members"]![0]!["id"] = "aaa-different";
        TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.Assemble(chunks.Concat([changed])), "Conflicting duplicate was accepted.");
        var wrong = PhoneContentScope.Reference(manifest); wrong["scope_revision"] = true;
        TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.RequireCurrent(wrong, manifest), "Boolean scope revision was accepted.");
        var deleted = new JsonObject { ["kind"] = "note", ["id"] = "mobile-note", ["state"] = "deleted" };
        TestAssert.That(PhoneContentScope.FilterRecords([records[0], deleted], manifest).Count == 1, "Deleted record reentered the live scope.");
        var empty = PhoneContentScope.Create([], []);
        TestAssert.That(PhoneContentScope.FilterRecords(records, empty).Count == 0 && JsonNode.DeepEquals(empty, PhoneContentScope.Assemble(PhoneContentScope.Chunks(empty))),
            "Empty scope expanded to whole-library permission.");
        var session = new PhoneContentScope.Session("peer", "key", 1);
        TestAssert.That(session.Receive("peer", "key", 1, chunks[^1]) is null, "Partial scope authorized a reply.");
        TestAssert.Throws<InvalidOperationException>(() => session.Current("peer", "key", 1, PhoneContentScope.Reference(large)), "Partial session was ready.");
        foreach (var part in chunks.SkipLast(1)) session.Receive("peer", "key", 1, part);
        TestAssert.That(JsonNode.DeepEquals(large, session.Current("peer", "key", 1, PhoneContentScope.Reference(large))), "Complete scope did not become ready.");
        TestAssert.Throws<InvalidOperationException>(() => session.Current("peer", "key", 2, PhoneContentScope.Reference(large)), "Other connection reused scope evidence.");
        TestAssert.Throws<InvalidOperationException>(() => session.Receive("other", "key", 1, chunks[0]), "Other peer supplied a scope part.");
        var next = PhoneContentScope.Advance(large, Enumerable.Range(0, 100).Select(n => $"new-{n:D3}"), []);
        var nextParts = PhoneContentScope.Chunks(next, 32);
        TestAssert.That(session.Receive("peer", "key", 1, nextParts[0]) is null, "Incomplete newer scope kept the old gate open.");
        TestAssert.Throws<InvalidOperationException>(() => session.Current("peer", "key", 1, PhoneContentScope.Reference(large)), "Old scope remained current after a new partial generation.");
        TestAssert.That(session.Receive("peer", "key", 1, chunks[0]) is null, "Old generation displaced current partial generation.");
        foreach (var part in nextParts.Skip(1)) session.Receive("peer", "key", 1, part);
        TestAssert.That(JsonNode.DeepEquals(next, session.Current("peer", "key", 1, PhoneContentScope.Reference(next))), "New scope did not complete.");
        var corrupt = nextParts[0].DeepClone().AsObject(); corrupt["scope_hash"] = new string('0', 64);
        TestAssert.Throws<InvalidDataException>(() => session.Receive("peer", "key", 1, corrupt), "Conflicting generation did not fail the session.");
        TestAssert.Throws<InvalidOperationException>(() => session.Current("peer", "key", 1, PhoneContentScope.Reference(next)), "Failed session remained ready.");
        TestAssert.Throws<InvalidDataException>(() => session.Receive("peer", "key", 1, nextParts[0]), "Failed session revived without reconnect.");
        return Task.CompletedTask;
    }
}
