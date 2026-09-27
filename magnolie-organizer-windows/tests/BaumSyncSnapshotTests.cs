using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class BaumSyncSnapshotTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "baum-run-" + Guid.NewGuid().ToString("N"));
        var now = DateTimeOffset.UtcNow;
        var run = Guid.NewGuid().ToString("D");
        var lease = new BaumSyncSnapshot(() => now);
        var journal = new RecoveryJournal(Path.Combine(root, "points"), Path.Combine(root, "settings.json"));
        var current = "{\"notizen\":[],\"aufgaben\":[]}";
        var ack = "";
        JsonObject Proof(string peer = "a") => new() { ["run"] = run, ["peer"] = peer, ["before"] = ack };
        void Save(string next, JsonObject? proof)
        {
            var old = JsonNode.Parse(current)!.AsObject();
            var changed = RecoveryJournal.HasRecoverableChanges(old, JsonNode.Parse(next)!.AsObject());
            var covered = lease.Covers(current, proof);
            if (changed && !covered) journal.Create(old, SnapshotReason.PreChange, "2.0.24");
            lease.Saved(current, next, proof, changed, covered);
            current = next; ack = BaumSyncSnapshot.Hash(next);
        }
        try
        {
            for (var i = 1; i <= 10; i++) Save(new JsonObject {
                ["notizen"] = new JsonArray(Enumerable.Range(1, i).Select(n => (JsonNode)new JsonObject {
                    ["id"] = n.ToString(), ["text"] = "Incoming " + n }).ToArray()), ["aufgaben"] = new JsonArray()
            }.ToJsonString(), Proof());
            var task = JsonNode.Parse(current)!.AsObject(); task["aufgaben"]!.AsArray().Add(new JsonObject { ["id"] = "task" });
            Save(task.ToJsonString(), Proof());
            TestAssert.That(journal.List().Count == 1, "Mixed incoming packets did not share their initial recovery point.");
            var local = JsonNode.Parse(current)!.AsObject(); local["notizen"]![0]!["text"] = "Local edit";
            Save(local.ToJsonString(), null);
            TestAssert.That(!lease.Covers(current, Proof()), "A local edit was hidden inside a peer's snapshot scope.");
            var next = JsonNode.Parse(current)!.AsObject(); next["notizen"]![1]!["text"] = "Next remote edit";
            Save(next.ToJsonString(), Proof());
            TestAssert.That(journal.List().Count == 3, "The local edit and next synchronization lost their separate recovery boundaries.");
            TestAssert.That(!lease.Covers(current, Proof("b")), "Different peers shared a snapshot lease.");
            TestAssert.That(!lease.Covers(current + " ", Proof()), "An unacknowledged stored state reused a snapshot.");
            now = now.AddMinutes(11);
            TestAssert.That(!lease.Covers(current, Proof()), "An expired run suppressed a snapshot.");
            TestAssert.That(!new BaumSyncSnapshot().Covers(current, Proof()), "A restarted application inherited an in-memory lease.");
            TestAssert.That(!lease.Covers(current, new JsonObject { ["run"] = "invalid", ["peer"] = "a" }), "Malformed run proof accepted.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
