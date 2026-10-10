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
            store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
            var body = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var publicCapabilities = TelefonProtocolContract.DesktopCapabilities();
            TestAssert.That(!SharedSyncSettings.Supported(publicCapabilities["items"]!.AsObject(), publicCapabilities["items"]!.AsObject()),
                "Incomplete shared-preference activation was advertised.");
            var negotiated = publicCapabilities.DeepClone().AsObject();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" })
            {
                negotiated["items"]![name]!["versions"]!.AsArray().Add(SharedSyncSettings.Version);
                negotiated["items"]![name]!["versions"]!.AsArray().Add(PhoneContentScope.Version);
            }
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
            var allowed = TelefonProtocolContract.DesktopGrants(); allowed["personal_notes_sync"] = true; allowed["personal_tasks_sync"] = true;
            var grants = Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = allowed });
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
            using (var scoped = Connect())
            {
                await scoped.HandlePlainAsync(caps); await scoped.HandlePlainAsync(grants); await scoped.HandlePlainAsync(own);
                await scoped.HandlePlainAsync(update);
                var manifest = PhoneContentScope.Create(Enumerable.Range(0, 100).Select(n => $"note-{n:D3}"), ["task"]);
                var pieces = PhoneContentScope.Chunks(manifest, 32);
                await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, pieces[0]));
                TestAssert.Throws<InvalidOperationException>(() => scoped.CurrentContentScope(PhoneContentScope.Reference(manifest)),
                    "Scope was accepted while full-collection mode was selected.");
                var choice = SharedSyncSettings.Change(remote, peer.Id, actor, "content_mode", JsonValue.Create("phone_scope")!);
                await scoped.HandlePlainAsync(Message(SharedSyncSettings.Kind, choice));
                TestAssert.That(scoped.SharedSettingsReady, "Scoped preference did not become current.");
                await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, pieces[^1]));
                TestAssert.Throws<InvalidOperationException>(() => scoped.CurrentContentScope(PhoneContentScope.Reference(manifest)), "Incomplete wire scope authorized reply.");
                foreach (var part in pieces.SkipLast(1)) await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                TestAssert.That(JsonNode.DeepEquals(manifest, scoped.CurrentContentScope(PhoneContentScope.Reference(manifest))), "Complete authenticated wire scope did not become current.");
                var next = PhoneContentScope.Advance(manifest, Enumerable.Range(0, 100).Select(n => $"updated-{n:D3}"), []);
                var nextParts = PhoneContentScope.Chunks(next, 32);
                await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, nextParts[0]));
                TestAssert.Throws<InvalidOperationException>(() => scoped.CurrentContentScope(PhoneContentScope.Reference(manifest)), "New incomplete scope kept old membership authorized.");
                foreach (var part in nextParts.Skip(1)) await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                TestAssert.That(JsonNode.DeepEquals(next, scoped.CurrentContentScope(PhoneContentScope.Reference(next))), "Updated wire membership did not become current.");
                var request = new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"),
                    ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
                var wrappedRequest = Message(PhoneContentScope.DataKind, PhoneContentScope.Wrap("personal_sync.request", request, next));
                await scoped.HandlePlainAsync(wrappedRequest);
                var runs = new PersonalSyncStore(store); var runId = request["run_id"]!.GetValue<string>();
                TestAssert.That(JsonNode.DeepEquals(PhoneContentScope.Reference(next), runs.ScopedRunReference(peer.Id, peer.PublicKey, runId,
                    DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())), "Scoped data dispatcher did not bind its request.");
                var rawRequest = Message("personal_sync.request", request);
                await scoped.HandlePlainAsync(rawRequest);
                using (var db = store.OpenDatabase())
                {
                    db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT result FROM dedupe WHERE peer_id=$peer AND message_id=$id";
                    query.Parameters.AddWithValue("$peer", peer.Id); query.Parameters.AddWithValue("$id", rawRequest["message_id"]!.GetValue<string>());
                    TestAssert.That((string?)query.ExecuteScalar() == "rejected", "Raw request reused a scoped run without its wrapper.");
                }
                var alteredData = wrappedRequest.DeepClone().AsObject();
                alteredData["body"]!["body"]!["run_id"] = Guid.NewGuid().ToString("D");
                await scoped.HandlePlainAsync(alteredData);
                TestAssert.That(runs.LoadRun(peer.Id, alteredData["body"]!["body"]!["run_id"]!.GetValue<string>(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()) is null,
                    "Altered message identity created another scoped run before rejection.");
                var records = new JsonArray();
                var emptyBatch = new JsonObject { ["format"] = 3, ["run_id"] = runId, ["batch_id"] = Guid.NewGuid().ToString("D"),
                    ["sequence"] = 0, ["last"] = true, ["reply"] = true, ["records"] = records,
                    ["records_hash"] = PersonalSyncContract.RecordsHash(records) };
                var queued = store.Enqueue(peer.Id, "personal_sync.batch", emptyBatch, 60000, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                await scoped.PumpOutboxNowAsync();
                var removed = PhoneContentScope.Advance(next, [], []);
                await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, PhoneContentScope.Chunks(removed).Single()));
                var rejectedAck = false;
                try { await scoped.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = queued, ["status"] = "accepted", ["error"] = "none" }); }
                catch (Exception error) when (error is InvalidOperationException or InvalidDataException) { rejectedAck = true; }
                TestAssert.That(rejectedAck && store.OutboxMessage(peer.Id, queued) is not null, "Stale scope ACK removed queued content.");
                using var otherConnection = Connect();
                TestAssert.Throws<InvalidOperationException>(() => otherConnection.CurrentContentScope(PhoneContentScope.Reference(next)), "Other connection inherited current membership.");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
