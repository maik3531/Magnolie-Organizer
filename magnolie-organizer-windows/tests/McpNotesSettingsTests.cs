using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class McpNotesSettingsTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-mcp-notes-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)28, 32).ToArray());
            store.LoadOrCreateIdentity(); store.Enabled = false;
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Owned Notes phone", TelefonCrypto.GenerateX25519().Public,
                CapabilityRevision: 1, StoredCapabilities: capabilities);
            store.SavePeers([peer]);
            store.SetPersonalSettings(peer.Id, ownDevice: false, remoteOwnDevice: false, autoWifi: false);
            var events = new List<string>();
            using var service = new TelefonCoordinator(paths, (callback, _) => { events.Add(callback); return Task.CompletedTask; }, dataStore: store, localOnly: true);
            var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            JsonObject Target(string action) => new() { ["action"] = action, ["peerId"] = peer.Id, ["fingerprint"] = fingerprint };
            var first = await service.ExecuteMcpAsync(Target("notes_settings_read"), default);
            var state = first["notesSettings"]!.AsObject();
            TestAssert.That(first["ok"]!.GetValue<bool>() && !state["own_device"]!.GetValue<bool>() && state["shared"]!["supported"]!.GetValue<bool>() &&
                state["shared"]!["values"] is null && store.SharedSettings(peer.Id, peer.PublicKey) is null, "Reading Notes settings initialized consent/preferences.");
            var initial = SharedSyncSettings.Effective(SharedSyncSettings.Create(store.LoadOrCreateIdentity().Id));
            var update = Target("notes_settings_update"); update["expectedRevision"] = state["revision"]!.DeepClone();
            update["initial"] = initial; update["field"] = "auto_mode"; update["value"] = "wifi";
            var saved = await service.ExecuteMcpAsync(update, default);
            TestAssert.That(saved["ok"]!.GetValue<bool>() && saved["persisted"]!.GetValue<bool>() && !saved["deliveryConfirmed"]!.GetValue<bool>() &&
                store.PersonalSettings(peer.Id).OwnDevice && store.PersonalSettings(peer.Id).AutoWifi && !store.PersonalSettings(peer.Id).RemoteOwnDevice &&
                SharedSyncSettings.Effective(store.SharedSettings(peer.Id, peer.PublicKey)!)["auto_mode"]!.GetValue<string>() == "wifi", "Native Notes shared preference was not saved/read back through the GUI handler.");
            var stale = await service.ExecuteMcpAsync(update, default);
            TestAssert.That(stale["code"]!.GetValue<string>() == "conflict", "Stale Notes revision mutated shared preferences.");
            update["expectedRevision"] = saved["notesSettings"]!["revision"]!.DeepClone(); update["field"] = "skip_deletions"; update["value"] = false;
            var deletion = await service.ExecuteMcpAsync(update, default);
            TestAssert.That(deletion["ok"]!.GetValue<bool>() && store.StoredGrantMatches("personal_deletions_sync", true), "Shared deletion preference bypassed the existing grant handler.");
            update["expectedRevision"] = deletion["notesSettings"]!["revision"]!.DeepClone(); update["value"] = "false";
            var invalid = await service.ExecuteMcpAsync(update, default);
            TestAssert.That(invalid["code"]!.GetValue<string>() == "invalid_selection", "Wrong preference type was accepted.");
            var wrong = Target("notes_settings_read"); wrong["fingerprint"] = "0000-0000-0000-0000";
            TestAssert.That((await service.ExecuteMcpAsync(wrong, default))["code"]!.GetValue<string>() == "conflict", "Wrong Notes fingerprint read current settings.");
            var revision = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.GetValue<string>();
            update["expectedRevision"] = revision; update["field"] = "auto_mode"; update["value"] = "manual";
            await store.NotePolicyGate.WaitAsync();
            Task<JsonObject> raced;
            try
            {
                raced = service.ExecuteMcpAsync(update, default);
                TestAssert.That(!raced.IsCompleted, "Notes mutation did not await the shared note-policy gate.");
                store.SetPersonalSettings(peer.Id, remoteOwnDevice: true);
            }
            finally { store.NotePolicyGate.Release(); }
            TestAssert.That((await raced)["code"]!.GetValue<string>() == "conflict" && store.PersonalSettings(peer.Id).AutoWifi,
                "Notes mutation failed to recheck consent revision after waiting for the shared gate.");
            TestAssert.That(service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.GetValue<string>() != revision, "Remote ownership change did not invalidate settings revision.");
            var ownership = Target("notes_ownership"); ownership["enabled"] = false;
            ownership["expectedRevision"] = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.DeepClone();
            var withdrawn = await service.ExecuteMcpAsync(ownership, default);
            TestAssert.That(withdrawn["ok"]!.GetValue<bool>() && withdrawn["persisted"]!.GetValue<bool>() &&
                !store.PersonalSettings(peer.Id).OwnDevice && !store.PersonalSettings(peer.Id).AutoWifi && store.PersonalSettings(peer.Id).RemoteOwnDevice &&
                store.LoadPeers().Single().Id == peer.Id, "Withdrawal did not preserve pairing/remote consent or failed to stop local automatic synchronization.");
            ownership["enabled"] = true; ownership["expectedRevision"] = withdrawn["notesSettings"]!["revision"]!.DeepClone();
            var confirmed = await service.ExecuteMcpAsync(ownership, default);
            TestAssert.That(confirmed["ok"]!.GetValue<bool>() && store.PersonalSettings(peer.Id).OwnDevice && store.PersonalSettings(peer.Id).RemoteOwnDevice,
                "Explicit ownership confirmation failed through the existing native handler.");
            var legacy = Target("notes_legacy_mode"); legacy["expectedRevision"] = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.DeepClone();
            legacy["enabled"] = true; legacy["skipDeletions"] = false;
            TestAssert.That((await service.ExecuteMcpAsync(legacy, default))["code"]!.GetValue<string>() == "unsupported_feature", "Legacy control overrode a modern shared-settings peer.");
            var oldCapabilities = capabilities.DeepClone().AsObject();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) oldCapabilities[name]!["versions"] = new JsonArray(1, 2, 3, 4, 5, 7);
            store.SavePeers([peer with { Capabilities = oldCapabilities }]);
            legacy["expectedRevision"] = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.DeepClone();
            var legacySaved = await service.ExecuteMcpAsync(legacy, default);
            TestAssert.That(legacySaved["ok"]!.GetValue<bool>() && store.PersonalSettings(peer.Id).AutoWifi &&
                store.StoredGrantMatches("personal_notes_sync", true) && store.StoredGrantMatches("personal_tasks_sync", true) &&
                store.StoredGrantMatches("personal_deletions_sync", true), "Legacy mode did not apply/read back the existing paired grant choices.");
            foreach (var mode in new[] { "phone_import", "two_way", "phone_import" })
            {
                var direction = Target("notes_note_direction"); direction["mode"] = mode;
                direction["expectedRevision"] = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.DeepClone();
                var changed = await service.ExecuteMcpAsync(direction, default);
                TestAssert.That(changed["ok"]!.GetValue<bool>() && changed["persisted"]!.GetValue<bool>() &&
                    store.NoteSettings(peer.Id)["local"]!["mode"]!.GetValue<string>() == mode, "Explicit note direction was not durably read back.");
                TestAssert.That((await service.ExecuteMcpAsync(direction, default))["code"]!.GetValue<string>() == "conflict", "Stale note policy revision mutated the direction.");
            }
            foreach (var policy in new[] { "custom", "time" }) foreach (var enabled in new[] { true, false })
            {
                var choice = Target("notes_legacy_policy"); choice["name"] = policy; choice["enabled"] = enabled;
                choice["expectedRevision"] = service.McpNotesSettings(peer.Id, fingerprint)["revision"]!.DeepClone();
                var changed = await service.ExecuteMcpAsync(choice, default);
                TestAssert.That(changed["ok"]!.GetValue<bool>() && changed["notesSettings"]!["policies"]![policy]!["local_enabled"]!.GetValue<bool>() == enabled,
                    "Legacy custom/time policy was not saved through the shared native handler.");
                TestAssert.That((await service.ExecuteMcpAsync(choice, default))["code"]!.GetValue<string>() == "conflict", "Stale legacy policy revision was accepted.");
            }
            TestAssert.That(events.Count == 0 && !service.McpStatus()["listening"]!.GetValue<bool>(), "Notes settings emitted GUI events or started a listener.");
            var previousCustom = store.CustomSettings(peer.Id)["local"]!.AsObject();
            var guiPolicy = TelefonStore.NewCustomSettings(true, TelefonProtocolContract.Integer(previousCustom["revision"]) + 1);
            var guiQueued = await service.SendPersonalSyncAsync(peer.Id, "personal_sync.custom_settings", guiPolicy);
            TestAssert.That(guiQueued.Length > 0 && JsonNode.DeepEquals(store.CustomSettings(peer.Id)["local"], guiPolicy) && events.Count > 0,
                "The ordinary GUI custom-policy route lost its existing store/queue/status behavior after sharing the native handler.");
        }
        finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
