using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SharedSyncStorageTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "shared-sync-store-" + Guid.NewGuid().ToString("N"));
        var key = Enumerable.Repeat((byte)29, 32).ToArray();
        try
        {
            var paths = new WindowsPaths(root); var store = new TelefonStore(paths, key);
            var local = store.LoadOrCreateIdentity(); var actor = local.Id;
            System.Security.Cryptography.CryptographicOperations.ZeroMemory(local.PrivateKey);
            var publicKey = Enumerable.Repeat((byte)31, 32).ToArray();
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", publicKey);
            store.SavePeers([peer]); var beforeGrants = store.LocalGrants().DeepClone(); var beforeMode = store.PersonalSettings(peer.Id);
            TestAssert.That(store.SharedSettings(peer.Id, publicKey) is null, "Preview initialized common preference metadata.");
            var initial = new JsonObject { ["content_mode"] = "phone_import", ["auto_mode"] = "wifi", ["skip_deletions"] = true,
                ["custom_enabled"] = false, ["time_enabled"] = true, ["time_mode"] = "phone_import" };
            var seeded = store.InitializeSharedSettings(peer.Id, publicKey, initial);
            TestAssert.That(JsonNode.DeepEquals(SharedSyncSettings.Effective(seeded), initial) &&
                seeded["settings"]!.AsObject().All(field => field.Value!.AsObject().All(edit => TelefonProtocolContract.Integer(edit.Value!["counter"]) == 0)),
                "Initialization changed a legacy choice or turned migration into an explicit edit.");
            var body = store.ChangeSharedSetting(peer.Id, publicKey, "content_mode", JsonValue.Create("two_way")!);
            TestAssert.That(JsonNode.DeepEquals(body, store.InitializeSharedSettings(peer.Id, publicKey, initial)), "A repeated initializer overwrote the user's newer choice.");
            var reopened = new TelefonStore(paths, key);
            TestAssert.That(JsonNode.DeepEquals(body, reopened.SharedSettings(peer.Id, publicKey)) &&
                store.PersonalSettings(peer.Id) == beforeMode && JsonNode.DeepEquals(beforeGrants, store.LocalGrants()) &&
                store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Count == 0,
                "Saved preference was lost or created authorization/outbox side effects.");
            using (var db = store.OpenDatabase())
            {
                db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT value FROM meta WHERE key LIKE 'personal_shared_settings:%'";
                var sealedValue = (byte[])query.ExecuteScalar()!;
                TestAssert.That(!Encoding.UTF8.GetString(sealedValue).Contains("content_mode"), "Common preference metadata was stored in clear text.");
            }
            var remote = SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), body, peer.Id, actor);
            remote = SharedSyncSettings.Change(remote, peer.Id, actor, "content_mode", JsonValue.Create("phone_scope")!);
            var accepted = store.MergeSharedSettings(peer.Id, publicKey, remote);
            TestAssert.That(SharedSyncSettings.Effective(accepted)["content_mode"]!.GetValue<string>() == "phone_scope" &&
                JsonNode.DeepEquals(accepted, store.MergeSharedSettings(peer.Id, publicKey, remote)), "Remote preference or idempotent echo did not persist.");
            var forged = remote.DeepClone().AsObject(); forged["settings"]!["content_mode"]![actor] = new JsonObject { ["counter"] = 100, ["value"] = "two_way" };
            TestAssert.Throws<InvalidDataException>(() => store.MergeSharedSettings(peer.Id, publicKey, forged), "Forged local preference echo was persisted.");
            TestAssert.That(JsonNode.DeepEquals(accepted, store.SharedSettings(peer.Id, publicKey)), "Rejected merge modified persisted state.");
            TestAssert.Throws<InvalidOperationException>(() => store.SharedSettings(peer.Id, Enumerable.Repeat((byte)41, 32).ToArray()), "Changed peer key reused old preferences.");
            var token = Guid.NewGuid().ToString("D"); store.BeginRestore(token);
            TestAssert.Throws<InvalidOperationException>(() => store.ChangeSharedSetting(peer.Id, publicKey, "auto_mode", JsonValue.Create("connection")!), "Restore fence allowed a new shared setting write.");
            store.AbortRestore(token);
            TestAssert.That(JsonNode.DeepEquals(accepted, store.SharedSettings(peer.Id, publicKey)), "Abort restore rolled back shared preference high-water marks.");
            token = Guid.NewGuid().ToString("D"); store.BeginRestore(token); store.CompleteRestore(Guid.NewGuid().ToString("D"), token);
            TestAssert.That(JsonNode.DeepEquals(accepted, store.SharedSettings(peer.Id, publicKey)), "Completed restore reset the common choice.");
            store.RemovePeer(peer.Id);
            using (var db = store.OpenDatabase())
            {
                db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT COUNT(*) FROM meta WHERE key LIKE 'personal_shared_settings:%'";
                TestAssert.That((long)query.ExecuteScalar()! == 0, "Unpair kept common preferences for an unrelated future pairing.");
            }
            // Re-pair with the same key, but newly selected bootstrap values.
            store.SavePeers([peer]);
            var oldBootstrap = SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), SharedSyncSettings.Create(actor), peer.Id, actor);
            oldBootstrap = SharedSyncSettings.Change(oldBootstrap, peer.Id, actor, "auto_mode", JsonValue.Create("wifi")!);
            oldBootstrap = SharedSyncSettings.Change(oldBootstrap, peer.Id, actor, "auto_mode", JsonValue.Create("wifi")!);
            var newInitial = SharedSyncSettings.Effective(SharedSyncSettings.Create(actor)); newInitial["auto_mode"] = "wifi";
            var reset = store.InitializeSharedSettings(peer.Id, publicKey, newInitial);
            TestAssert.Throws<InvalidDataException>(() => SharedSyncSettings.Merge(reset, oldBootstrap, actor, peer.Id), "The fixture did not reproduce the stale bootstrap echo.");
            var repaired = store.MergeSharedSettings(peer.Id, publicKey, oldBootstrap);
            TestAssert.That(repaired["settings"]!["auto_mode"]![actor]!["counter"]!.GetValue<long>() == 1 &&
                repaired["settings"]!["auto_mode"]![actor]!["value"]!.GetValue<string>() == "wifi", "Re-pair adopted the obsolete local bootstrap.");
            var echoed = SharedSyncSettings.Merge(oldBootstrap, repaired, peer.Id, actor);
            TestAssert.That(JsonNode.DeepEquals(repaired, store.MergeSharedSettings(peer.Id, publicKey, echoed)) &&
                JsonNode.DeepEquals(repaired, new TelefonStore(paths, key).SharedSettings(peer.Id, publicKey)), "Re-pair failed to converge durably.");
            TestAssert.That(JsonNode.DeepEquals(repaired, store.MergeSharedSettings(peer.Id, publicKey, oldBootstrap)), "Stale replay advanced the local clock again.");
            var bad = oldBootstrap.DeepClone().AsObject(); bad["settings"]!["custom_enabled"]![actor]!["counter"] = 100;
            TestAssert.Throws<InvalidDataException>(() => store.MergeSharedSettings(peer.Id, publicKey, bad), "Bootstrap recovery accepted a forged positive local clock.");
            TestAssert.That(JsonNode.DeepEquals(repaired, store.SharedSettings(peer.Id, publicKey)), "Rejected recovery partially persisted.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
