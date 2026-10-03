using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncModeTests
{
    internal static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "personal-mode-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)27, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)11, 32).ToArray());
            store.SavePeers([peer]);
            store.SetPersonalSyncMode(peer.Id, true, false);
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(reopened.PersonalSettings(peer.Id) == (true, false, true), "Unified mode invented remote consent or lost local settings.");
            var grants = reopened.LocalGrants();
            TestAssert.That(new[] { "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync" }
                .All(name => grants[name]!.GetValue<bool>()), "Initial mode did not enable notes, tasks and deletion review.");
            reopened.SetLocalGrant("selected_notifications_readonly", false);
            reopened.SetLocalGrant("incoming_call_state", true);
            var direction = PersonalSyncContract.NoteSettings("phone_import");
            reopened.SetNoteSettings(peer.Id, direction, false);
            reopened.SetPersonalSyncMode(peer.Id, false, true);
            grants = reopened.LocalGrants();
            TestAssert.That(reopened.PersonalSettings(peer.Id) == (true, false, false) &&
                grants["personal_notes_sync"]!.GetValue<bool>() && grants["personal_tasks_sync"]!.GetValue<bool>() &&
                !grants["personal_deletions_sync"]!.GetValue<bool>(), "Manual mode or deletion exception did not persist.");
            TestAssert.That(grants["incoming_call_state"]!.GetValue<bool>() && !grants["selected_notifications_readonly"]!.GetValue<bool>() &&
                JsonNode.DeepEquals(reopened.NoteSettings(peer.Id)["local"], direction), "Unified mode changed unrelated permissions or direction.");
            TestAssert.Throws<InvalidOperationException>(() => reopened.SetPersonalSyncMode(Guid.NewGuid().ToString("D"), true, false),
                "Unified mode accepted an unpaired computer.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
