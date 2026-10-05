using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeSyncStoreTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "time-sync-store-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var key = Enumerable.Repeat((byte)29, 32).ToArray();
            var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var local = TimeSyncContract.NewSettings(true); var remote = TimeSyncContract.NewSettings(true);
            store.SetTimeSettings(peer.Id, local); store.SetTimeSettings(peer.Id, remote, true);
            var actor = Guid.NewGuid().ToString("D");
            JsonObject Record() => new()
            {
                ["id"] = Guid.NewGuid().ToString("D"), ["startMinute"] = 1000L, ["endMinute"] = 1060L,
                ["pauseMinute"] = null, ["pauseMinutes"] = 15L, ["zone"] = "UTC", ["type"] = "Synthetic",
                ["note"] = "Confidential fixture", ["modifiedMs"] = 1000L, ["deleted"] = false,
                ["clock"] = new JsonObject { [actor] = 1L }
            };
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            JsonObject Message()
            {
                var body = TimeSyncContract.RequestBody(remote, local); body["entries"] = new JsonArray(Record());
                return new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = TimeSyncContract.Batch,
                    ["message_id"] = Guid.NewGuid().ToString("D"), ["created_ms"] = now, ["expires_ms"] = now + 60000,
                    ["body"] = body };
            }
            var message = Message(); var id = message["message_id"]!.GetValue<string>();
            store.CommitIncoming(peer.Id, message, now, (_, _) => null, deferAcceptance: true);
            var pending = store.StageTimeBatch(peer.Id, message, now); var token = pending["commit_token"]!.GetValue<string>();
            TestAssert.That(store.LoadRecent(peer.Id, TimeSyncContract.Batch, 10).Count == 0, "Staged records were accepted before document persistence.");
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(JsonNode.DeepEquals(pending, reopened.StageTimeBatch(peer.Id, message, now)), "Restart changed the pending operation identity.");
            TestAssert.That(!reopened.CommitTimeBatch(peer.Id, id, "wrong", now, _ => true), "Wrong commit token was accepted.");
            TestAssert.That(!reopened.CommitTimeBatch(peer.Id, id, token, now, _ => false), "Missing live authorization was ignored.");
            TestAssert.That(reopened.CommitTimeBatch(peer.Id, id, token, now, _ => true), "A valid durable commit failed.");
            TestAssert.That(reopened.LoadRecent(peer.Id, TimeSyncContract.Batch, 10).Count == 1, "Committed receipt is not durable.");
            TestAssert.That(!reopened.CommitTimeBatch(peer.Id, id, token, now, _ => true), "A completed token was reusable.");

            var second = Message(); var secondId = second["message_id"]!.GetValue<string>();
            reopened.CommitIncoming(peer.Id, second, now, (_, _) => null, deferAcceptance: true);
            var staged = reopened.StageTimeBatch(peer.Id, second, now);
            var altered = second.DeepClone().AsObject(); altered["body"]!["entries"]![0]!["note"] = "Changed replay";
            TestAssert.Throws<InvalidDataException>(() => reopened.StageTimeBatch(peer.Id, altered, now), "A changed body reused a staged identity.");
            reopened.SetTimeSettings(peer.Id, TimeSyncContract.NewSettings(false, 2), true);
            TestAssert.That(!reopened.HasTimeBatch(peer.Id, secondId), "Revocation kept uncommitted private records.");
            TestAssert.That(!reopened.CommitTimeBatch(peer.Id, secondId, staged["commit_token"]!.GetValue<string>(), now, _ => true), "Revocation allowed a delayed commit.");

            var records = new JsonArray();
            for (var index = 0; index < 65; index++) records.Add(Record());
            var packets = TimeSyncContract.Batches(local, remote, records);
            TestAssert.That(packets.Count == 3 && packets.Sum(packet => packet["entries"]!.AsArray().Count) == 65, "Record-count batching lost records.");
            foreach (var record in records.OfType<JsonObject>()) record["note"] = string.Concat(Enumerable.Repeat("😀", 10000));
            packets = TimeSyncContract.Batches(local, remote, records);
            TestAssert.That(packets.Count > 3 && packets.Sum(packet => packet["entries"]!.AsArray().Count) == 65, "UTF-8 batching lost records.");
            foreach (var packet in packets) TimeSyncContract.Validate(TimeSyncContract.Batch, packet, true);
            var restoreToken = Guid.NewGuid().ToString("D"); reopened.BeginRestore(restoreToken);
            TestAssert.That(reopened.TimeSettings(peer.Id)["local"]?["enabled"]?.GetValue<bool>() == false, "Restore retained time consent.");
            reopened.AbortRestore(restoreToken);
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
