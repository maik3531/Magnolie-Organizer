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
            try { PersonalSyncActorContract.ValidateStart(item["body"]!.AsObject()); accepted = true; } catch (InvalidDataException) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor-start contract drift: " + item["name"]);
        }
        var dataVectors = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "magnolie-notes/app/src/test/resources/notes-actor-data.json")))!["cases"]!.AsArray();
        foreach (var item in dataVectors.OfType<JsonObject>())
        {
            var value = item["body"]!.AsObject(); var accepted = false;
            try { PersonalSyncActorContract.ValidateData(value); accepted = true; } catch (InvalidDataException) { }
            TestAssert.That(accepted == item["valid"]!.GetValue<bool>(), "Actor-data contract drift: " + item["name"]);
            if (!accepted) continue;
            TestAssert.That(JsonNode.DeepEquals(PersonalSyncActorContract.Wrap(value["run_id"]!.GetValue<string>(), value["kind"]!.GetValue<string>(), value["body"]!.AsObject()), value), "Actor wrap changed existing record/schema content.");
            var unwrapped = PersonalSyncActorContract.Unwrap(value);
            TestAssert.That(unwrapped.Kind == value["kind"]!.GetValue<string>() && JsonNode.DeepEquals(unwrapped.Body, value["body"]), "Actor unwrap lost original scoped/legacy body.");
            unwrapped.Body["owned_mutation"] = true;
            TestAssert.That(value["body"]!["owned_mutation"] is null, "Unwrapped data aliased the stored actor envelope.");
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
