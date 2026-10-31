using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SyncCommitProjectionTests
{
    internal static Task RunAsync()
    {
        var id = new string('a', 64);
        var baseline = new JsonObject { ["termine"] = new JsonArray(new JsonObject { ["uid"] = "synthetic-event", ["titel"] = "Synthetic" }),
            ["aufgaben"] = new JsonArray(), ["kontakte"] = new JsonArray(new JsonObject { ["id"] = "synthetic-contact", ["vorname"] = "Synthetic",
                ["syncQuellen"] = new JsonObject { ["source"] = new JsonObject { ["id"] = "bound-resource", ["etag"] = "v1" } } }),
            ["jahrestage"] = new JsonArray(), ["geloescht"] = new JsonObject { ["termine"] = new JsonArray(), ["aufgaben"] = new JsonArray(), ["kontakte"] = new JsonArray() },
            ["syncEpoch"] = "existing-book-epoch", ["letzterSync"] = 100L, ["letzteSyncs"] = new JsonObject(), ["syncMetadaten"] = new JsonObject() };
        var result = baseline.DeepClone().AsObject(); result["transactionId"] = id; result["syncAbgleichBasis"] = baseline.DeepClone();
        result["syncMetadaten"]!["nextcloud"] = new JsonObject { ["ausstehendeTransaktion"] = id };
        var saved = result.DeepClone().AsObject();
        saved["syncMetadaten"]!["nextcloud"]!.AsObject().Remove("ausstehendeTransaktion");
        var proof = baseline.DeepClone().AsObject(); proof["transactionId"] = id; saved["syncAbgleichNachweis"] = proof;
        TestAssert.That(SyncBaseline.ContainsSavedResult(result, saved), "A matching saved result was rejected solely because the frontend retired its own transient progress marker.");
        TestAssert.That(result["syncMetadaten"]!["nextcloud"]!["ausstehendeTransaktion"]!.GetValue<string>() == id, "Verification mutated the pending recovery journal payload.");
        foreach (var change in new[] { "epoch", "proof", "transaction", "source", "content", "sync-metadata", "durable-marker" })
        {
            var expected = result.DeepClone().AsObject(); var actual = saved.DeepClone().AsObject();
            if (change == "epoch") actual["syncEpoch"] = "other-restore-epoch";
            else if (change == "proof") actual.Remove("syncAbgleichNachweis");
            else if (change == "transaction") actual["syncAbgleichNachweis"]!["transactionId"] = new string('b', 64);
            else if (change == "source") actual["kontakte"]![0]!["syncQuellen"]!["source"]!["etag"] = "foreign";
            else if (change == "content") actual["termine"]![0]!["titel"] = "discarded provider content";
            else if (change == "sync-metadata") expected["syncMetadaten"]!["nextcloud"]!["ausstehendeTransaktion"] = new string('b', 64);
            else expected["syncMetadaten"]!["nextcloud"]!["pendingCommitId"] = id;
            TestAssert.That(!SyncBaseline.ContainsSavedResult(expected, actual), "Retiring one transient marker weakened the saved result proof: " + change);
        }
        return Task.CompletedTask;
    }
}
