using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorStoreTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-actor-outbox-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var key = Enumerable.Repeat((byte)29, 32).ToArray();
            var store = new TelefonStore(paths, testStorageKey: key);
            var peer = "22222222-2222-4222-8222-222222222222";
            var run = "11111111-1111-4111-8111-111111111111"; var legacyRun = "33333333-3333-4333-8333-333333333333";
            var request = new JsonObject { ["format"] = 3, ["run_id"] = run, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            var legacy = request.DeepClone().AsObject(); legacy["run_id"] = legacyRun;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var personal = new PersonalSyncStore(store);
            personal.RememberRun(peer, request, now); personal.RememberRun(peer, legacy, now);
            var actorId = store.Enqueue(peer, "personal_sync.request", request, 60000, now, actorRunId: run);
            var ordinaryId = store.Enqueue(peer, "personal_sync.request", legacy, 60000, now);
            var reopened = new TelefonStore(paths, testStorageKey: key);
            var pending = reopened.Due(peer, now + 1).ToDictionary(item => item.Id);
            var wire = pending[actorId].Message;
            TestAssert.That(wire["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind && wire["message_id"]!.GetValue<string>() == actorId &&
                wire["created_ms"]!.GetValue<long>() == now && wire["expires_ms"]!.GetValue<long>() == now + 60000 &&
                JsonNode.DeepEquals(PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject()).Body, request), "Encrypted actor wire identity/lifetime did not survive queue restart.");
            TestAssert.That(pending[ordinaryId].Message["kind"]!.GetValue<string>() == "personal_sync.request" &&
                JsonNode.DeepEquals(pending[ordinaryId].Message["body"], legacy), "An ordinary GUI queue was converted into actor traffic.");
            using var db = reopened.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT kind,payload FROM outbox WHERE message_id=$id"; read.Parameters.AddWithValue("$id", actorId);
            using var row = read.ExecuteReader(); TestAssert.That(row.Read(), "Actor queue row disappeared.");
            TestAssert.That(row.GetString(0) == "personal_sync.request" && JsonNode.DeepEquals(JsonNode.Parse(reopened.Open("outbox", actorId, (byte[])row[1])), wire),
                "Stored actor marker was only volatile or semantic queue ordering was lost.");
            row.Close(); db.Close();
            TestAssert.Throws<InvalidDataException>(() => reopened.Enqueue(peer, "personal_sync.request", request, 60000, now, actorRunId: legacyRun), "A foreign actor run identity was queued.");
            TestAssert.Throws<InvalidDataException>(() => reopened.Enqueue(peer, "personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }, 60000, now, actorRunId: run), "Actor transport admitted control injection.");
            TestAssert.That(reopened.AcknowledgePersonalOutbox(peer, actorId, "rejected", "temporary_failure", now + 2) &&
                JsonNode.DeepEquals(reopened.OutboxMessage(peer, actorId), wire), "A temporary receipt discarded the retained actor marker.");
            TestAssert.That(reopened.AcknowledgePersonalOutbox(peer, actorId, "accepted", "none", now + 3) && reopened.OutboxMessage(peer, actorId) is null &&
                reopened.OutboxMessage(peer, ordinaryId) is not null, "Actor ACK identity changed or removed unrelated GUI traffic.");
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
