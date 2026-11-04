using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncSuccessTests
{
    internal static async Task AcknowledgmentsAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "personal-success-ack-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, Enumerable.Repeat((byte)27, 32).ToArray());
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)11, 32).ToArray());
            store.SavePeers([peer]);
            using var owner = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store);
            using var wire = new MemoryStream();
            using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "wifi") {
                PersonalSuccessConfirmed = (source, report) => owner.RecordConfirmedPersonalSuccess(source, peer, report)
            };
            var online = (IDictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(owner)!;
            online[peer.Id] = connection;
            JsonObject Ack(string id, string status) => new() { ["type"] = "ack", ["message_id"] = id,
                ["status"] = status, ["error"] = status == "rejected" ? "invalid_schema" : "none" };
            foreach (var scenario in new[] { "rejected", "failed", "unknown_run", "stale", "accepted", "duplicate" })
            {
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var run = Guid.NewGuid().ToString("D");
                if (scenario != "unknown_run") new PersonalSyncStore(store).RememberRun(peer.Id, new JsonObject {
                    ["format"] = 1, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes") }, now);
                var report = JsonNode.Parse("""{"format":1,"state":"complete","trigger":"manual","transport":"wifi","sent":{"notes":0,"tasks":0,"notebooks":0},"received":{"notes":0,"tasks":0,"notebooks":0},"conflicts":0,"attachments_omitted":0,"oversized_skipped":0,"started_ms":1,"finished_ms":1,"error":"none","deletions":{"pending":0,"deleted":0,"restored":0,"conflicts":0,"blocked":0,"trash":{"notes":0,"tasks":0,"notebooks":0,"attachments":0}}}""")!.AsObject();
                report["run_id"] = run;
                if (scenario == "failed") { report["state"] = "failed"; report["error"] = "protocol"; }
                var before = store.PersonalSuccess(peer.Id)?.DeepClone();
                var id = store.Enqueue(peer.Id, "personal_sync.report", report, 60000, now);
                TestAssert.That(JsonNode.DeepEquals(before, store.PersonalSuccess(peer.Id)), "Queueing marked success.");
                if (scenario == "stale") online.Remove(peer.Id);
                await connection.HandlePlainAsync(Ack(id, scenario is "rejected" or "duplicate" ? scenario : "accepted"));
                online[peer.Id] = connection;
                if (scenario is "accepted" or "duplicate")
                {
                    TestAssert.That(store.PersonalSuccess(peer.Id)?["trigger"]?.GetValue<string>() == "manual" &&
                        store.PersonalSuccess(peer.Id)!["finished_ms"]!.GetValue<long>() >= now, "Real confirmed ACK did not record local completion.");
                    var saved = store.PersonalSuccess(peer.Id)!.DeepClone();
                    await connection.HandlePlainAsync(Ack(id, "duplicate"));
                    TestAssert.That(JsonNode.DeepEquals(saved, store.PersonalSuccess(peer.Id)), "Repeated ACK moved completion time.");
                }
                else TestAssert.That(JsonNode.DeepEquals(before, store.PersonalSuccess(peer.Id)), "Failed/stale/unbound ACK invented success.");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "personal-success-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)27, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)11, 32).ToArray());
            store.SavePeers([peer]); var publicKey = Convert.ToBase64String(peer.PublicKey);
            var grants = store.LocalGrants().DeepClone(); var preferences = store.PersonalSettings(peer.Id);
            TestAssert.That(store.PersonalSuccess(peer.Id) is null, "Legacy absence invented a successful sync.");
            var run = Guid.NewGuid().ToString("D");
            TestAssert.That(!store.RememberPersonalSuccess(peer.Id, "wrong-key", run, "manual", 1000), "Wrong phone key recorded success.");
            TestAssert.That(store.RememberPersonalSuccess(peer.Id, publicKey, run, "manual", 1000), "Confirmed native success not stored.");
            var saved = store.PersonalSuccess(peer.Id)!;
            TestAssert.That(saved.Count == 3 && saved["finished_ms"]!.GetValue<long>() == 1000 &&
                saved["trigger"]!.GetValue<string>() == "manual", "Success projection exposed identity or wrong metadata.");
            TestAssert.That(JsonNode.DeepEquals(grants, store.LocalGrants()) && preferences == store.PersonalSettings(peer.Id),
                "Display metadata changed native grants or synchronization mode.");
            TestAssert.That(!store.RememberPersonalSuccess(peer.Id, publicKey, run, "manual", 2000) &&
                !store.RememberPersonalSuccess(peer.Id, publicKey, Guid.NewGuid().ToString("D"), "manual", 999),
                "Replayed/older completion advanced last-success time.");
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(JsonNode.DeepEquals(saved, reopened.PersonalSuccess(peer.Id)), "Successful sync did not survive reopen.");
            reopened.SetPersonalSyncMode(peer.Id, false, true);
            TestAssert.That(JsonNode.DeepEquals(saved, reopened.PersonalSuccess(peer.Id)), "Changing mode discarded successful history.");
            foreach (var trigger in new[] { "auto_wifi", "auto_connection" })
            {
                TestAssert.That(reopened.RememberPersonalSuccess(peer.Id, publicKey, Guid.NewGuid().ToString("D"), trigger,
                    trigger == "auto_wifi" ? 2000 : 3000), "Supported automatic trigger rejected.");
                TestAssert.That(reopened.PersonalSuccess(peer.Id)!["trigger"]!.GetValue<string>() == trigger,
                    "Configured manual mode replaced the actual automatic trigger.");
            }
            TestAssert.That(!reopened.RememberPersonalSuccess(peer.Id, publicKey, "not-a-run", "manual", 4000) &&
                !reopened.RememberPersonalSuccess(peer.Id, publicKey, Guid.NewGuid().ToString("D"), "automatic", 4000),
                "Invalid run/trigger aliases became successful metadata.");
            reopened.SavePeers([peer with { PublicKey = Enumerable.Repeat((byte)12, 32).ToArray() }]);
            TestAssert.That(reopened.PersonalSuccess(peer.Id) is null, "Changed phone key inherited old completion.");
            reopened.SavePeers([peer]);
            TestAssert.That(reopened.PersonalSuccess(peer.Id) is not null, "Key comparison changed or deleted historical metadata.");
            var settings = JsonNode.Parse(File.ReadAllText(paths.TelefonSettings))!.AsObject();
            settings["personal_sync"]![peer.Id]!["last_success"]!["finished_ms"] = true;
            File.WriteAllText(paths.TelefonSettings, settings.ToJsonString()); var bytes = File.ReadAllBytes(paths.TelefonSettings);
            var unchangedGrants = reopened.LocalGrants().DeepClone();
            TestAssert.That(reopened.PersonalSuccess(peer.Id) is null && JsonNode.DeepEquals(unchangedGrants, reopened.LocalGrants()) &&
                File.ReadAllBytes(paths.TelefonSettings).SequenceEqual(bytes), "Malformed display metadata repaired settings or changed grants.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
        return Task.CompletedTask;
    }
}
