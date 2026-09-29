using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RecoveryComparisonAllocationTests
{
    internal static Task RunAsync()
    {
        var photo = "data:image/png;base64," + Convert.ToBase64String(new byte[24 * 1024]);
        var contacts = new JsonArray();
        for (var index = 0; index < 128; index++)
            contacts.Add(new JsonObject { ["id"] = "fixture-" + index, ["uid"] = "uid-" + index,
                ["vorname"] = "Fixture", ["nachname"] = index.ToString(), ["foto"] = photo });
        var text = new JsonObject { ["kontakte"] = contacts, ["einstellungen"] = new JsonObject() }.ToJsonString();
        var before = JsonNode.Parse(text)!.AsObject();
        var after = JsonNode.Parse(text)!.AsObject();
        after["einstellungen"]!["changed"] = true;
        _ = RecoveryJournal.HasRecoverableChanges(new JsonObject(), new JsonObject());
        var start = GC.GetAllocatedBytesForCurrentThread();
        var changed = RecoveryJournal.HasRecoverableChanges(before, after);
        var allocated = GC.GetAllocatedBytesForCurrentThread() - start;
        Console.WriteLine($"Recovery comparison: payload={text.Length}, allocated={allocated}");
        TestAssert.That(!changed, "Settings-only changes created a content snapshot.");
        TestAssert.That(allocated <= 8L * text.Length,
            "Unchanged photo contacts were repeatedly materialized during a settings-only comparison.");
        after["kontakte"]![0]!["uid"] = "another-source-id";
        TestAssert.That(!RecoveryJournal.HasRecoverableChanges(before, after), "Source identity changes became content changes.");
        after["kontakte"]![0]!["foto"] = "data:image/png;base64,AQID";
        TestAssert.That(RecoveryJournal.HasRecoverableChanges(before, after), "A real photo change was lost by the fast path.");
        return Task.CompletedTask;
    }
}
