using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ScopedRunStorageTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "scoped-run-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)57, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)59, 32).ToArray());
            store.SavePeers([peer]); store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var request = new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            var runId = request["run_id"]!.GetValue<string>(); var reference = PhoneContentScope.Reference(PhoneContentScope.Create(["note"], ["task"]));
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var expires = now + 60000;
            var runs = new PersonalSyncStore(store); runs.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires);
            var reopened = new TelefonStore(paths, key); var loaded = new PersonalSyncStore(reopened);
            TestAssert.That(JsonNode.DeepEquals(reference, loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now)) &&
                JsonNode.DeepEquals(request, loaded.LoadRun(peer.Id, runId, now)!.Request), "Run or scope reference did not survive reopen.");
            loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires);
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, reference, now, expires + 1), "Replay extended scoped run lifetime.");
            var changed = reference.DeepClone().AsObject(); changed["scope_revision"] = 2;
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, request, changed, now, expires), "Run changed membership after persistence.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "time_mode", JsonValue.Create("two_way")!);
            TestAssert.That(JsonNode.DeepEquals(reference, loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now)), "Separate time direction invalidated note/task run.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("two_way")!);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now), "Changed content choice retained old scoped authorization.");
            reopened.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, runId, now), "Returning to scope mode revived old run.");
            var legacy = request.DeepClone().AsObject(); legacy["run_id"] = Guid.NewGuid().ToString("D"); loaded.RememberRun(peer.Id, legacy, now, expires);
            TestAssert.Throws<InvalidDataException>(() => loaded.RememberScopedRun(peer.Id, peer.PublicKey, legacy, reference, now, expires), "Legacy run identity was adopted as scoped.");
            var fresh = request.DeepClone().AsObject(); fresh["run_id"] = Guid.NewGuid().ToString("D");
            loaded.RememberScopedRun(peer.Id, peer.PublicKey, fresh, reference, now, expires);
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, Enumerable.Repeat((byte)61, 32).ToArray(), fresh["run_id"]!.GetValue<string>(), now), "Different paired key reused scoped metadata.");
            TestAssert.Throws<InvalidOperationException>(() => loaded.ScopedRunReference(peer.Id, peer.PublicKey, fresh["run_id"]!.GetValue<string>(), expires + 1), "Expired scoped run stayed valid.");
            loaded.CleanupExpiredRuns(expires + 1);
            using var db = reopened.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
            query.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_scope:%'";
            TestAssert.That((long)query.ExecuteScalar()! == 0, "Expired run cleanup left scoped bindings behind.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
