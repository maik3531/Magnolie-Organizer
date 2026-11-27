using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RestoreSelectionIdentityTests
{
    internal static Task RunAsync()
    {
        const string marker = "contracts/restore-additive-identity-vectors.json";
        var vectors = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(marker), marker)))!["cases"]!.AsArray();
        foreach (var vector in vectors.OfType<JsonObject>())
        {
            var name = vector["collection"]!.GetValue<string>();
            var area = vector["area"]!.GetValue<string>();
            var id = vector["id"]!.GetValue<string>();
            var current = new JsonObject { [name] = vector["current"]!.DeepClone() };
            var snapshot = new JsonObject { [name] = vector["snapshot"]!.DeepClone() };
            var currentBefore = current.DeepClone();
            var snapshotBefore = snapshot.DeepClone();
            if (vector["error"]?.GetValue<string>() == "ambiguous-local-id")
            {
                TestAssert.Throws<InvalidDataException>(() => RestoreSelection.Select(snapshot, current, [area], "additive"),
                    id + ": ambiguous local identity did not hold the restoration.");
                TestAssert.That(JsonNode.DeepEquals(current, currentBefore) && JsonNode.DeepEquals(snapshot, snapshotBefore),
                    id + ": rejected restoration mutated its inputs.");
                var explicitReplacement = RestoreSelection.Select(snapshot, current, [area], "replace");
                TestAssert.That(JsonNode.DeepEquals(explicitReplacement[name], vector["snapshot"]), id + ": replacement selection changed.");
                continue;
            }
            var restored = RestoreSelection.Select(snapshot, current, [area], "additive");
            TestAssert.That(JsonNode.DeepEquals(restored[name], vector["expected"]), id + ": additive selection differs.");
            var repeated = RestoreSelection.Select(snapshot, restored, [area], "additive");
            TestAssert.That(JsonNode.DeepEquals(repeated[name], vector["expected"]), id + ": repeated restoration duplicates or changes entries.");
            var replaced = RestoreSelection.Select(snapshot, current, [area], "replace");
            TestAssert.That(JsonNode.DeepEquals(replaced[name], vector["snapshot"]), id + ": replacement selection changed.");
            TestAssert.That(JsonNode.DeepEquals(current, currentBefore) && JsonNode.DeepEquals(snapshot, snapshotBefore),
                id + ": restoration mutated its inputs.");
        }
        return Task.CompletedTask;
    }
}
