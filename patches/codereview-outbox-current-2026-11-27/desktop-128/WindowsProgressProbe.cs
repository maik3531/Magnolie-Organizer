using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

var temporary = Path.Combine(Path.GetTempPath(), "magnolie-pending-fairness-" + Guid.NewGuid().ToString("N"));
try
{
    var paths = new WindowsPaths(temporary);
    var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)30, 32).ToArray());
    store.Enabled = true;
    var grants = TelefonProtocolContract.DesktopGrants();
    grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
    var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned transport fixture", TelefonCrypto.GenerateX25519().Public,
        CapabilityRevision: 1, StoredCapabilities: TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject(),
        GrantRevision: 1, StoredGrants: grants);
    store.SavePeers([peer]);
    store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
    store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
    var run = Guid.NewGuid().ToString("D");
    var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    var request = new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
    new PersonalSyncStore(store).RememberRun(PersonalSyncActorContract.StoragePeer(run), request, now);
    var held = new List<string>();
    for (var sequence = 0; sequence < 65; sequence++)
    {
        var body = new JsonObject { ["format"] = 3, ["run_id"] = run, ["batch_id"] = Guid.NewGuid().ToString("D"),
            ["sequence"] = sequence, ["last"] = sequence == 64, ["reply"] = false,
            ["records_hash"] = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945", ["records"] = new JsonArray() };
        held.Add(store.Enqueue(peer.Id, "personal_sync.batch", body, 60000, now, actorRunId: run));
    }
    var ordinary = store.Enqueue(peer.Id, "device_status.request", new JsonObject { ["request_id"] = Guid.NewGuid().ToString("D") }, 60000, now + 1);
    using var stream = new MemoryStream();
    using var lifetime = new CancellationTokenSource(TimeSpan.FromSeconds(15));
    using var connection = new TelefonConnection(peer, stream, new byte[16], new byte[72], store,
        (_, _) => Task.FromResult<TelefonAck?>(null), lifetime.Token, "wifi");
    var observations = new JsonArray();
    for (var cycle = 0; cycle < 3; cycle++)
    {
        var selected = store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        var before = stream.Length;
        await connection.PumpOutboxNowAsync();
        observations.Add(new JsonObject { ["cycle"] = cycle, ["selected"] = selected.Count,
            ["later_ordinary_selected"] = selected.Any(item => item.Id == ordinary), ["written_bytes"] = stream.Length - before });
    }
    var progressed = observations.Any(value => value!["written_bytes"]!.GetValue<long>() > 0);
    var actorsRetained = held.All(id => store.OutboxMessage(peer.Id, id) is not null);
    using var db = store.OpenDatabase(); db.Open(); using var attempts = db.CreateCommand();
    attempts.CommandText = "SELECT COALESCE(SUM(attempts),0) FROM outbox WHERE kind='personal_sync.batch'";
    var actorAttempts = Convert.ToInt32(attempts.ExecuteScalar());
    var result = new JsonObject { ["basis"] = "9de81cc10d72ca7b176b5c501ff20689cdd53c31", ["runtime"] = ".NET 8 source host on Linux",
        ["observations"] = observations, ["progress_within_three_pumps"] = progressed,
        ["actor_attempts"] = actorAttempts, ["actors_retained"] = actorsRetained,
        ["ordinary_still_retained_for_ack"] = store.OutboxMessage(peer.Id, ordinary) is not null };
    Console.WriteLine(result.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    return progressed && actorsRetained && actorAttempts == 0 ? 0 : 1;
}
finally
{
    SqliteConnection.ClearAllPools();
    if (Directory.Exists(temporary)) Directory.Delete(temporary, true);
}
