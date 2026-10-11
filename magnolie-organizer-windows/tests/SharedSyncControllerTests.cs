using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SharedSyncControllerTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "shared-controller-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)31, 32).ToArray());
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)23, 32).ToArray());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true);
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            store.UpdatePeerProtocol(peer.Id, 1, capabilities, 0, null);
            using var controller = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store, localOnly: true)
                { SharedLocalCapabilities = () => capabilities.DeepClone().AsObject() };
            var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            var beforeGrants = store.LocalGrants().DeepClone(); var beforeMode = store.PersonalSettings(peer.Id);
            var preview = controller.SharedPreferences(peer.Id);
            TestAssert.That(preview["supported"]!.GetValue<bool>() && !preview["initialized"]!.GetValue<bool>() &&
                preview["values"] is null && store.SharedSettings(peer.Id, peer.PublicKey) is null, "Preview initialized preferences.");
            var initial = new JsonObject { ["content_mode"] = "phone_import", ["auto_mode"] = "wifi", ["skip_deletions"] = true,
                ["custom_enabled"] = false, ["time_enabled"] = true, ["time_mode"] = "phone_import" };
            await controller.SetCommonPreferencesAsync(peer.Id, fingerprint, initial);
            TestAssert.That(JsonNode.DeepEquals(initial, controller.SharedPreferences(peer.Id)["values"]), "Controller lost initial choices.");
            await controller.SetCommonPreferencesAsync(peer.Id, fingerprint, initial, "content_mode", JsonValue.Create("phone_scope"));
            await controller.SetCommonPreferencesAsync(peer.Id, fingerprint, initial);
            var chosen = store.SharedSettings(peer.Id, peer.PublicKey);
            TestAssert.That(controller.SharedPreferences(peer.Id)["values"]!["content_mode"]!.GetValue<string>() == "phone_scope", "Repeated initializer overwrote an edit.");
            foreach (var action in new Func<Task>[] {
                () => controller.SetCommonPreferencesAsync(peer.Id, "old-key", initial, "auto_mode", JsonValue.Create("manual")),
                () => controller.SetCommonPreferencesAsync(peer.Id, fingerprint, new JsonObject()),
                () => controller.SetCommonPreferencesAsync(peer.Id, fingerprint, initial, "time_enabled", JsonValue.Create("true")) })
            {
                var rejected = false;
                try { await action(); } catch (Exception error) when (error is InvalidOperationException or InvalidDataException) { rejected = true; }
                TestAssert.That(rejected, "Invalid controller edit was accepted.");
            }
            controller.SharedLocalCapabilities = () => {
                var legacy = TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject();
                foreach (var item in legacy) item.Value!["versions"] = new JsonArray(item.Value!["versions"]!.AsArray()
                    .Where(value => value!.GetValue<int>() < 9).Select(value => value!.DeepClone()).ToArray());
                return legacy;
            };
            var unsupported = false;
            try { await controller.SetCommonPreferencesAsync(peer.Id, fingerprint, initial); } catch (InvalidOperationException) { unsupported = true; }
            TestAssert.That(unsupported && JsonNode.DeepEquals(chosen, store.SharedSettings(peer.Id, peer.PublicKey)) &&
                JsonNode.DeepEquals(beforeGrants, store.LocalGrants()) &&
                store.PersonalSettings(peer.Id) == (beforeMode.OwnDevice, beforeMode.RemoteOwnDevice, true) &&
                store.TimeSettings(peer.Id)["local"]?["enabled"]?.GetValue<bool>() == true,
                "Controller bypassed capabilities or rewrote unrelated grants/policies.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
