using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SharedSyncTransportTests
{
    private static JsonObject Message(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "shared-sync-wire-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new TelefonStore(new WindowsPaths(root), Enumerable.Repeat((byte)37, 32).ToArray());
            var identity = store.LoadOrCreateIdentity(); var actor = identity.Id;
            System.Security.Cryptography.CryptographicOperations.ZeroMemory(identity.PrivateKey);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)23, 32).ToArray());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            var body = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var publicCapabilities = TelefonProtocolContract.DesktopCapabilities();
            TestAssert.That(!SharedSyncSettings.Supported(publicCapabilities["items"]!.AsObject(), publicCapabilities["items"]!.AsObject()),
                "Incomplete shared-preference activation was advertised.");
            var negotiated = publicCapabilities.DeepClone().AsObject();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) negotiated["items"]![name]!["versions"]!.AsArray().Add(SharedSyncSettings.Version);
            Task<TelefonAck?> Receive(TelefonPeer _, JsonObject message)
            {
                var content = message["body"]!.AsObject();
                switch (message["kind"]!.GetValue<string>())
                {
                    case "capabilities.update": store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(content["revision"]), content["items"]!.AsObject(), 0, null); break;
                    case "grants.update": store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(content["revision"]), content["grants"]!.AsObject()); break;
                    case "personal_sync.settings": store.SetPersonalSettings(peer.Id, remoteOwnDevice: content["own_device"]!.GetValue<bool>()); break;
                }
                return Task.FromResult<TelefonAck?>(null);
            }
            TelefonConnection Connect(bool supported = true) => new TelefonConnection(peer, new MemoryStream(), new byte[16], new byte[72],
                store, Receive, CancellationToken.None, "wifi") { SharedLocalCapabilities = () => (supported ? negotiated : publicCapabilities)["items"]!.DeepClone().AsObject() };
            var caps = Message("capabilities.update", negotiated);
            var grants = Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = TelefonProtocolContract.DesktopGrants() });
            var own = Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
            var remote = SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), body, peer.Id, actor);
            remote = SharedSyncSettings.Change(remote, peer.Id, actor, "content_mode", JsonValue.Create("two_way")!);
            var update = Message(SharedSyncSettings.Kind, remote);
            using (var connection = Connect())
            {
                await connection.HandlePlainAsync(update);
                TestAssert.That(JsonNode.DeepEquals(body, store.SharedSettings(peer.Id, peer.PublicKey)), "Missing fresh controls accepted preferences.");
                await connection.HandlePlainAsync(caps); await connection.HandlePlainAsync(grants); await connection.HandlePlainAsync(own);
                TestAssert.That(!connection.SharedSettingsReady, "Controls alone established preference agreement.");
                // A fresh message identity retries the previously unauthorized request.
                update = Message(SharedSyncSettings.Kind, remote);
                var beforeGrants = store.LocalGrants().DeepClone();
                await connection.HandlePlainAsync(update);
                var accepted = store.SharedSettings(peer.Id, peer.PublicKey)!;
                TestAssert.That(connection.SharedSettingsReady && SharedSyncSettings.Effective(accepted)["content_mode"]!.GetValue<string>() == "two_way",
                    "Authenticated common preference did not converge.");
                TestAssert.That(JsonNode.DeepEquals(beforeGrants, store.LocalGrants()), "Common preference exchange rewrote data grants.");
                await connection.HandlePlainAsync(update);
                TestAssert.That(connection.SharedSettingsReady && JsonNode.DeepEquals(accepted, store.SharedSettings(peer.Id, peer.PublicKey)), "Lost ACK replay changed preferences.");
                var altered = update.DeepClone().AsObject(); altered["body"] = SharedSyncSettings.Change(remote, peer.Id, actor, "auto_mode", JsonValue.Create("connection")!);
                await connection.HandlePlainAsync(altered);
                TestAssert.That(JsonNode.DeepEquals(accepted, store.SharedSettings(peer.Id, peer.PublicKey)), "Altered same-message replay changed preferences.");
            }
            using (var reconnect = Connect())
            {
                TestAssert.That(!reconnect.SharedSettingsReady, "Saved preferences opened a new connection.");
                await reconnect.HandlePlainAsync(caps); await reconnect.HandlePlainAsync(grants); await reconnect.HandlePlainAsync(own);
                TestAssert.That(!reconnect.SharedSettingsReady, "New controls reused old received preference evidence.");
                await reconnect.HandlePlainAsync(update);
                TestAssert.That(reconnect.SharedSettingsReady, "Identical authenticated replay did not refresh current connection evidence.");
            }
            using (var oldVersion = Connect(false))
            {
                await oldVersion.HandlePlainAsync(caps); await oldVersion.HandlePlainAsync(grants); await oldVersion.HandlePlainAsync(own);
                await oldVersion.HandlePlainAsync(Message(SharedSyncSettings.Kind, remote));
                TestAssert.That(!oldVersion.SharedSettingsReady, "One-sided capability negotiated common settings.");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
