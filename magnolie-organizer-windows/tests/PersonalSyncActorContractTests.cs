using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorContractTests
{
    internal static Task RunAsync()
    {
        var root = TestSource.Root("magnolie-notes/app/src/test/resources/notes-actor-start.json");
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "magnolie-notes/app/src/test/resources/notes-actor-start.json")))!["cases"]!.AsArray();
        foreach (var item in vectors.OfType<JsonObject>())
        {
            var accepted = false;
            try { PersonalSyncActorContract.ValidateStart(item["body"]!.AsObject()); accepted = true; } catch (Exception) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor-start contract drift: " + item["name"]);
        }
        var values = new JsonObject();
        foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" })
            values[name] = new JsonObject { ["available"] = true, ["versions"] = new JsonArray(9, 12) };
        TestAssert.That(PersonalSyncActorContract.Supported(values, values), "Actor/shared markers were not recognized.");
        foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) foreach (var version in new[] { 9, 12 })
        {
            var missing = values.DeepClone().AsObject(); missing[name]!["versions"] = new JsonArray(version);
            TestAssert.That(!PersonalSyncActorContract.Supported(values, missing) && !PersonalSyncActorContract.Supported(missing, values), "A one-sided/incomplete actor contract was accepted.");
        }
        return Task.CompletedTask;
    }
}
