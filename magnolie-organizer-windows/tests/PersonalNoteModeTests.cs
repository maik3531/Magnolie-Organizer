using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalNoteModeTests
{
    internal static async Task RunAsync()
    {
        var temporary = Path.Combine(Path.GetTempPath(), "personal-note-mode-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new TelefonStore(new WindowsPaths(temporary), Enumerable.Repeat((byte)19, 32).ToArray());
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic phone", Enumerable.Repeat((byte)112, 32).ToArray());
            store.SavePeers([peer]);
            var rejectOwn = false;
            var callbacks = 0;
            Task<TelefonAck?> Receive(TelefonPeer _, JsonObject message)
            {
                callbacks++;
                var body = message["body"]!.AsObject();
                switch (message["kind"]!.GetValue<string>())
                {
                    case "capabilities.update":
                        store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null);
                        break;
                    case "grants.update":
                        store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject());
                        break;
                    case "personal_sync.settings":
                        if (rejectOwn) return Task.FromResult<TelefonAck?>(new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", "temporary_failure"));
                        store.SetPersonalSettings(peer.Id, remoteOwnDevice: body["own_device"]!.GetValue<bool>());
                        break;
                }
                return Task.FromResult<TelefonAck?>(null);
            }
            TelefonConnection Connect() => new(peer, new MemoryStream(), new byte[16], new byte[72], store,
                Receive, CancellationToken.None, "wifi");
            JsonObject Message(string kind, JsonObject body)
            {
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                    ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body };
            }
            var legacyCapabilities = TelefonProtocolContract.DesktopCapabilities();
            legacyCapabilities["items"]!["personal_notes_sync"]!["versions"] = new JsonArray(1, 2, 3);
            var capability = Message("capabilities.update", legacyCapabilities);
            var grants = Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = TelefonProtocolContract.DesktopGrants() });
            var own = Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
            using (var first = Connect())
            {
                await first.HandlePlainAsync(capability); await first.HandlePlainAsync(grants); await first.HandlePlainAsync(own);
                TestAssert.That(first.NotePolicyReady, "Fresh legacy controls did not permit the existing two-way protocol.");
            }
            var count = callbacks;
            using (var reconnect = Connect())
            {
                TestAssert.That(!reconnect.NotePolicyReady, "Persisted controls opened a new connection.");
                await reconnect.HandlePlainAsync(capability); await reconnect.HandlePlainAsync(grants);
                TestAssert.That(!reconnect.NotePolicyReady, "Missing current own-device control was ignored.");
                await reconnect.HandlePlainAsync(own);
                TestAssert.That(reconnect.NotePolicyReady && callbacks == count, "ACK-loss replay did not refresh controls without repeating their effects.");
            }
            using (var rejected = Connect())
            {
                await rejected.HandlePlainAsync(capability); await rejected.HandlePlainAsync(grants);
                rejectOwn = true;
                await rejected.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
                TestAssert.That(!rejected.NotePolicyReady, "A rejected settings callback opened the note gate.");
            }
            var newer = TelefonProtocolContract.DesktopCapabilities(); newer["revision"] = 2;
            store.UpdatePeerProtocol(peer.Id, 2, newer["items"]!.AsObject(), 0, null);
            using (var stale = Connect())
            {
                await stale.HandlePlainAsync(capability); await stale.HandlePlainAsync(grants); await stale.HandlePlainAsync(own);
                TestAssert.That(!stale.NotePolicyReady, "A superseded capability replay opened the note gate.");
            }
            rejectOwn = false;
            using (var modern = Connect())
            {
                await modern.SendNoteSettingsAsync(true);
                TestAssert.That(store.NoteSettings(peer.Id).Count == 0,
                    "Cached V5 capability sent note settings before fresh capabilities (breaking downgraded peers).");
                var capabilities = TelefonProtocolContract.DesktopCapabilities(); capabilities["revision"] = 3;
                await modern.HandlePlainAsync(Message("capabilities.update", capabilities));
                await modern.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 3, ["grants"] = TelefonProtocolContract.DesktopGrants() }));
                await modern.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
                await modern.SendNoteSettingsAsync(true);
                TestAssert.That(!modern.NotePolicyReady, "V5 controls without remote policy opened the note gate.");
                var local = store.NoteSettings(peer.Id)["local"]!.AsObject();
                var remote = PersonalSyncContract.NoteSettings("phone_import", peerEpoch: local["epoch"]!.GetValue<string>());
                var settingsMessage = Message(PersonalSyncContract.NoteModeKind, remote);
                await modern.HandlePlainAsync(settingsMessage);
                TestAssert.That(modern.NotePolicyReady && store.NoteImportMode(peer.Id), "Fresh V5 mutual echoes did not establish import mode.");
                var altered = settingsMessage.DeepClone().AsObject(); altered["body"]!["peer_epoch"] = "";
                await modern.HandlePlainAsync(altered);
                TestAssert.That(modern.NotePolicyReady && JsonNode.DeepEquals(store.NoteSettings(peer.Id)["remote"], remote),
                    "An altered replay replaced the authenticated direction echo.");
            }
            var import = PersonalSyncContract.NoteSettings("phone_import", 2);
            store.SetNoteSettings(peer.Id, import, false);
            var token = Guid.NewGuid().ToString("D");
            store.BeginRestore(token); store.AbortRestore(token);
            TestAssert.That(JsonNode.DeepEquals(store.NoteSettings(peer.Id)["local"], import), "Aborting restore reset note direction consent.");
            token = Guid.NewGuid().ToString("D");
            store.BeginRestore(token); store.CompleteRestore(Guid.NewGuid().ToString("D"), token);
            TestAssert.That(JsonNode.DeepEquals(store.NoteSettings(peer.Id)["local"], import), "Completing restore reset note direction consent.");
            var remotePolicy = store.NoteSettings(peer.Id)["remote"]!.AsObject();
            store.SetNoteSettings(peer.Id, PersonalSyncContract.NoteSettingsEcho(import, remotePolicy), false);
            store.SetNoteSettings(peer.Id, PersonalSyncContract.NoteSettingsEcho(remotePolicy, import), true);
            store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            store.SetLocalGrant("personal_notes_sync", true);
            var remoteGrants = TelefonProtocolContract.DesktopGrants(); remoteGrants["personal_notes_sync"] = true;
            store.UpdatePeerProtocol(peer.Id, 0, null, 4, remoteGrants);
            var personal = new PersonalSyncStore(store); var run = Guid.NewGuid().ToString("D");
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            personal.RememberRun(peer.Id, new JsonObject { ["format"] = 1, ["run_id"] = run,
                ["trigger"] = "manual", ["modules"] = new JsonArray("notes") }, now);
            var value = new JsonObject { ["title"] = "Incoming", ["text"] = "Phone text", ["html"] = "",
                ["notebook_id"] = "book", ["symbol"] = "note", ["created_ms"] = 1, ["modified_ms"] = 1 };
            var records = new JsonArray(new JsonObject { ["kind"] = "note", ["id"] = "phone-note", ["state"] = "live",
                ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = Guid.NewGuid().ToString("D"), ["counter"] = 1 }),
                ["hash"] = PersonalSyncContract.ProjectionHash(value), ["modified_ms"] = 1, ["value"] = value });
            var batch = Message("personal_sync.batch", new JsonObject { ["format"] = 1, ["run_id"] = run,
                ["batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = 0, ["last"] = true, ["reply"] = true, ["records"] = records });
            store.CommitIncoming(peer.Id, batch, now, (_, _) => null, deferAcceptance: true);
            var staged = personal.StageBatch(peer.Id, batch, "wifi", now)!;
            var delivered = 0;
            using (var offline = new TelefonCoordinator(new WindowsPaths(temporary), (name, _) => {
                if (name == "App.telefonPersonalSync") delivered++;
                return Task.CompletedTask;
            }, dataStore: store))
            {
                await offline.ReplayPersonalSyncAsync();
                TestAssert.That(delivered == 0 && !offline.CommitPersonalSync(peer.Id, staged.PendingMessageId, staged.CommitToken, "applied"),
                    "Persisted V5 mutual echoes authorized replay or commit without a fresh connection.");
            }
            var proposalId = Guid.NewGuid().ToString("D");
            var clock = new JsonArray(new JsonObject { ["actor_id"] = Guid.NewGuid().ToString("D"), ["counter"] = 1 });
            var proposals = new JsonObject { ["format"] = 1, ["run_id"] = run, ["proposal_batch_id"] = Guid.NewGuid().ToString("D"),
                ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(new JsonObject { ["proposal_id"] = proposalId,
                    ["kind"] = "task", ["id"] = "task", ["parent_id"] = "", ["clock"] = clock.DeepClone(),
                    ["prior_hash"] = new string('a', 64), ["deleted_ms"] = 1, ["label"] = "Task" }) };
            var decision = new JsonObject { ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = proposalId,
                ["decision"] = "delete", ["expected_clock"] = clock.DeepClone() }) };
            store.RememberPersonalProposalKinds(peer.Id, proposals, true, now);
            TestAssert.That(store.PersonalDecisionKinds(peer.Id, decision, false)?.Single() == "task" &&
                store.PersonalDecisionKinds(peer.Id, decision, true) is null &&
                store.PersonalDecisionKinds(Guid.NewGuid().ToString("D"), decision, false) is null,
                "Task decision proof escaped its peer or direction.");
            var wrongClock = decision.DeepClone().AsObject(); wrongClock["decisions"]![0]!["expected_clock"]![0]!["counter"] = 2;
            TestAssert.That(store.PersonalDecisionKinds(peer.Id, wrongClock, false) is null, "Task proof accepted a different vector clock.");
            store.RememberPersonalProposalKinds(peer.Id, proposals, true, now + 86_400_000);
            store.Cleanup(now + TelefonStore.MaximumMessageTtlMs + 1);
            TestAssert.That(store.PersonalDecisionKinds(peer.Id, decision, false) is null && store.NoteImportMode(peer.Id),
                "Proof retention did not expire or erased the paired direction policy.");
            store.RemovePeer(peer.Id);
            TestAssert.That(store.NoteSettings(peer.Id).Count == 0, "Unpair retained note direction consent.");
        }
        finally { if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }
}
