using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalActorTargetObserverRuntimeTests
{
    private static JsonObject Message(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }

    internal static async Task RunAsync()
    {
        foreach (var scenario in new[] { "note", "task", "attachment", "foreign-owner", "cancelled", "local-grant", "remote-grant",
            "skip-deletions", "channel", "missing-snapshot", "saved-mismatch", "source-mismatch", "save-during-capture", "invalid-group", "empty-group", "over-capacity",
            "origin-note", "origin-task", "origin-attachment", "origin-raw-only", "origin-foreign-key", "origin-conflict", "origin-partial",
            "origin-local-grant", "origin-remote-grant", "origin-expired", "origin-cancelled", "origin-capacity", "origin-channel", "origin-source",
            "origin-wall", "origin-mono", "origin-request-missing" })
        {
            var root = Path.Combine(Path.GetTempPath(), "actor-target-observer-" + Guid.NewGuid().ToString("N"));
            try
            {
                var paths = new WindowsPaths(root);
                var store = new TelefonStore(paths, Enumerable.Repeat((byte)37, 32).ToArray());
                var identity = store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
                var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)23, 32).ToArray());
                store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
                foreach (var grant in new[] { "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync" }) store.SetLocalGrant(grant, true);
                var settings = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "skip_deletions", JsonValue.Create(false)!);
                var capabilities = TelefonProtocolContract.DesktopCapabilities();
                foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) capabilities["items"]![name]!["versions"]!.AsArray().Add(12);
                var grants = TelefonProtocolContract.DesktopGrants();
                foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync" }) grants[name] = true;
                Task<TelefonAck?> Receive(TelefonPeer _, JsonObject message)
                {
                    var body = message["body"]!.AsObject();
                    if (message["kind"]!.GetValue<string>() == "capabilities.update") store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null);
                    else if (message["kind"]!.GetValue<string>() == "grants.update") store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject());
                    return Task.FromResult<TelefonAck?>(null);
                }
                var emitted = 0;
                using var coordinator = new TelefonCoordinator(paths, (_, _) => { emitted++; return Task.CompletedTask; }, dataStore: store,
                    foregroundEnabled: true, localOnly: true) { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
                using var wire = new MemoryStream();
                using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store, Receive, CancellationToken.None, "wifi")
                    { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
                var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
                online[peer.Id] = connection;
                await connection.HandlePlainAsync(Message("capabilities.update", capabilities));
                await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = grants }));
                await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
                await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), settings, peer.Id, identity.Id)));
                var scope = PhoneContentScope.Create(["selected-note"], ["selected-task"]);
                foreach (var chunk in PhoneContentScope.Chunks(scope)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, chunk));
                var kind = scenario is "task" or "origin-task" ? "task" : scenario is "attachment" or "origin-attachment" ? "attachment" : "note";
                var id = kind == "task" ? "outside-task" : kind == "attachment" ? "outside-file" : "outside-note";
                var parent = kind == "attachment" ? "outside-note" : "";
                var clock = new JsonArray(new JsonObject { ["actor_id"] = identity.Id, ["counter"] = 1 });
                var book = new JsonObject { ["notizen"] = new JsonArray(new JsonObject { ["id"] = "outside-note", ["text"] = "PRIVATE CONTENT",
                        ["anhaenge"] = new JsonArray(new JsonObject { ["id"] = "outside-file", ["daten"] = "PRIVATE BLOB" }) }),
                    ["aufgaben"] = new JsonArray(new JsonObject { ["id"] = "outside-task", ["titel"] = "PRIVATE TASK" }),
                    ["personalSync"] = new JsonObject { ["peer_device_id"] = peer.Id, ["entities"] = new JsonObject {
                        [kind + "\0" + (parent.Length > 0 ? parent + "\0" : "") + id] = new JsonObject { ["state"] = "live", ["peer_device_id"] = peer.Id,
                            ["parent_id"] = parent, ["hash"] = new string('a', 64), ["clock"] = clock.DeepClone() } } } };
                var target = new JsonObject { ["proposal_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind, ["id"] = id,
                    ["parent_id"] = parent, ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() };
                var owner = new NativeBookOwnerScope(); owner.SetReady(true); var text = book.ToJsonString();
                owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text));
                coordinator.NativeBookSource = () => owner.Current("target-observer", true);
                coordinator.NativeSavedBook = () => owner.SaveState("target-observer", true);
                var captured = NativeActorBookSnapshot.Capture(() => owner.SaveState("target-observer", true), () => text)!;
                var captures = 0;
                coordinator.NativeProducerBook = () => { captures++; if (scenario == "save-during-capture") owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text)); return captured; };
                var handle = await coordinator.CreatePersonalActorAsync(peer.Id, TelefonCrypto.Fingerprint(peer.PublicKey));
                if (scenario.StartsWith("origin-", StringComparison.Ordinal))
                {
                    await OriginAsync(scenario, coordinator, store, peer, connection, handle, target, grants, owner, captured, scope,
                        wire, () => emitted, () => captures);
                    continue;
                }
                if (scenario == "foreign-owner") handle = new PersonalActorHandle(handle.ActorId, new string('f', 64));
                if (scenario == "cancelled") await coordinator.CancelPersonalActorAsync(handle);
                if (scenario == "local-grant") store.SetLocalGrant("personal_deletions_sync", false);
                if (scenario == "remote-grant") { var changed = grants.DeepClone().AsObject(); changed["personal_deletions_sync"] = false; await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = changed })); }
                if (scenario == "skip-deletions") store.ChangeSharedSetting(peer.Id, peer.PublicKey, "skip_deletions", JsonValue.Create(true)!);
                if (scenario == "channel") online.Clear();
                if (scenario == "missing-snapshot") coordinator.NativeProducerBook = () => null;
                if (scenario == "saved-mismatch") owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text));
                if (scenario == "source-mismatch") coordinator.NativeBookSource = () => new string('c', 64);
                var beforeWire = wire.Length; var beforeEmitted = emitted; var beforeSaved = owner.SaveState("target-observer", true);
                using var db = store.OpenDatabase(); db.Open();
                long Rows() { using var query = db.CreateCommand(); query.CommandText = "SELECT COUNT(*) FROM outbox"; return Convert.ToInt64(query.ExecuteScalar()); }
                var beforeRows = Rows();
                if (scenario is "note" or "task" or "attachment")
                {
                    var result = await coordinator.ObservePersonalActorIncomingTargetsAsync(handle, [target]);
                    TestAssert.That(result.Count == 1 && JsonNode.DeepEquals(result[0]["target"], target) && result[0]["requires_conflict_choice"]!.GetValue<bool>() &&
                        !result[0].ToJsonString().Contains("PRIVATE") && captures == 1, "Native observer lost exact target/conflict/privacy/one-capture boundary.");
                    TestAssert.That(owner.SaveState("target-observer", true) == beforeSaved && book.ToJsonString() == text, "Observation changed actual native book.");
                    var decision = new JsonObject { ["format"] = 1, ["run_id"] = handle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                        ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "delete", ["expected_clock"] = clock.DeepClone() }) };
                    TestAssert.That(store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(handle.ActorId), decision, true) is null,
                        "Read-only target observation created an incoming action right.");
                    TestAssert.That(JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope), "Observation widened content membership.");
                }
                else if (scenario == "invalid-group")
                    await TestAssert.ThrowsAsync<InvalidDataException>(() => coordinator.ObservePersonalActorIncomingTargetsAsync(handle, [target, target]), "Duplicate group was accepted.");
                else if (scenario is "empty-group" or "over-capacity")
                {
                    await TestAssert.ThrowsAsync<InvalidDataException>(() => coordinator.ObservePersonalActorIncomingTargetsAsync(handle,
                        Enumerable.Repeat(target, scenario == "empty-group" ? 0 : 257).ToArray()), "Invalid capacity was accepted.");
                    TestAssert.That(captures == 0, "Invalid capacity read the whole native book before rejection.");
                }
                else await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ObservePersonalActorIncomingTargetsAsync(handle, [target]), "Stale/unconsented target observer was admitted: " + scenario);
                TestAssert.That(wire.Length == beforeWire && emitted == beforeEmitted && Rows() == beforeRows,
                    "Observation emitted data, callbacks or persisted outgoing frames: " + scenario);
            }
            finally { SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
        }
    }

    private static async Task OriginAsync(string scenario, TelefonCoordinator coordinator, TelefonStore store, TelefonPeer peer,
        TelefonConnection connection, PersonalActorHandle handle, JsonObject target, JsonObject grants, NativeBookOwnerScope owner,
        NativeActorBookSnapshot snapshot, JsonObject scope, MemoryStream transport, Func<int> emitted, Func<int> captures)
    {
        await coordinator.StartPersonalActorAsync(handle);
        var request = new JsonObject { ["format"] = 3, ["run_id"] = handle.ActorId, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
        await coordinator.ReceivePersonalActorAsync(connection, peer, PersonalSyncActorContract.WireMessage(Message("personal_sync.request", request), handle.ActorId));
        var proposal = target.DeepClone().AsObject(); proposal["deleted_ms"] = 1; proposal["label"] = "Synthetic target";
        var body = new JsonObject { ["format"] = 1, ["run_id"] = handle.ActorId, ["proposal_batch_id"] = Guid.NewGuid().ToString("D"),
            ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(proposal) };
        var message = PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_proposals", body), handle.ActorId);
        var beforeWire = transport.Length; var beforeEmitted = emitted(); var beforeSaved = owner.SaveState("target-observer", true);
        var beforeStatus = await coordinator.PersonalActorStatusAsync(handle);
        long Rows()
        {
            using var db = store.OpenDatabase(); db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT COUNT(*) FROM outbox";
            return Convert.ToInt64(query.ExecuteScalar());
        }
        var beforeRows = Rows();
        if (scenario == "origin-raw-only")
            await coordinator.WithPersonalActorStoreAsync(registry => registry.Put(handle, message));
        else if (scenario == "origin-foreign-key")
            await coordinator.ReceivePersonalActorAsync(connection, new TelefonPeer(peer.Id, "Foreign", Enumerable.Repeat((byte)9, 32).ToArray()), message);
        else if (scenario == "origin-expired")
        {
            var expired = message.DeepClone().AsObject(); var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            expired["created_ms"] = now - 60000; expired["expires_ms"] = now - 1;
            await coordinator.ReceivePersonalActorAsync(connection, peer, expired);
        }
        else if (scenario == "origin-capacity")
        {
            for (var index = 0; index < 9; index++)
            {
                var part = message.DeepClone().AsObject(); part["message_id"] = Guid.NewGuid().ToString("D");
                var content = part["body"]!["body"]!.AsObject(); content["sequence"] = index; content["last"] = index == 8;
                var proposals = Enumerable.Range(0, index < 8 ? 32 : 1).Select(offset => {
                    var item = proposal.DeepClone().AsObject(); item["proposal_id"] = Guid.NewGuid().ToString("D"); item["id"] = $"outside-{index}-{offset}"; return item;
                }).OrderBy(item => item["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal);
                content["proposals"] = new JsonArray(proposals.Select(item => (JsonNode)item).ToArray());
                await coordinator.ReceivePersonalActorAsync(connection, peer, part);
            }
        }
        else if (scenario == "origin-partial")
        {
            var first = message.DeepClone().AsObject(); first["body"]!["body"]!["last"] = false;
            await coordinator.ReceivePersonalActorAsync(connection, peer, first);
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle), "Partial origin group was readable.");
            var second = message.DeepClone().AsObject(); second["message_id"] = Guid.NewGuid().ToString("D"); second["body"]!["body"]!["sequence"] = 1;
            second["body"]!["body"]!["proposals"]![0]!["proposal_id"] = Guid.NewGuid().ToString("D");
            second["body"]!["body"]!["proposals"]![0]!["id"] = "second-outside-target";
            await coordinator.ReceivePersonalActorAsync(connection, peer, second);
            var frames = await coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle);
            TestAssert.That(frames.Count == 2 && JsonNode.DeepEquals(frames[0], first) && JsonNode.DeepEquals(frames[1], second), "Complete origin group changed its original bytes.");
        }
        else
        {
            await coordinator.ReceivePersonalActorAsync(connection, peer, message);
            var received = await coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle);
            TestAssert.That(received.Count == 1 && JsonNode.DeepEquals(received[0], message), "Authenticated incoming origin not retained.");
            received[0]["body"]!["body"]!["proposals"]![0]!["label"] = "Caller copy";
            TestAssert.That(JsonNode.DeepEquals((await coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle))[0], message), "Caller mutated protected original.");
            if (scenario == "origin-conflict")
            {
                var changed = message.DeepClone().AsObject(); changed["body"]!["body"]!["proposals"]![0]!["prior_hash"] = new string('b', 64);
                await coordinator.ReceivePersonalActorAsync(connection, peer, changed);
            }
            if (scenario == "origin-local-grant") store.SetLocalGrant("personal_deletions_sync", false);
            if (scenario == "origin-remote-grant")
            {
                var changed = grants.DeepClone().AsObject(); changed["personal_deletions_sync"] = false;
                await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = changed }));
                beforeWire = transport.Length; // The deliberate grant update has its own protocol ACK.
            }
            if (scenario == "origin-cancelled") await coordinator.WithPersonalActorStoreAsync(registry => registry.Cancel(handle));
            if (scenario == "origin-channel")
                ((Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!).Clear();
            if (scenario == "origin-source") coordinator.NativeBookSource = () => new string('c', 64);
            if (scenario is "origin-wall" or "origin-mono")
            {
                var admissions = (System.Collections.IDictionary)typeof(TelefonCoordinator).GetField("actorAdmissions", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
                var admission = admissions[handle.ActorId]!;
                var origin = admission.GetType().GetProperty("IncomingTargetOrigin", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(admission)!;
                var deadline = origin.GetType().GetField(scenario == "origin-wall" ? "WallDeadline" : "MonotonicDeadline", BindingFlags.NonPublic | BindingFlags.Instance)!;
                var originalDeadline = deadline.GetValue(origin);
                await coordinator.ReceivePersonalActorAsync(connection, peer, message);
                TestAssert.That(Equals(originalDeadline, deadline.GetValue(origin)), "Retransmission renewed origin deadline.");
                deadline.SetValue(origin, 0L);
            }
            if (scenario == "origin-request-missing")
            {
                using var db = store.OpenDatabase(); db.Open(); using var delete = db.CreateCommand(); delete.CommandText = "DELETE FROM meta WHERE key=$key";
                delete.Parameters.AddWithValue("$key", $"personal_run:{PersonalSyncActorContract.StoragePeer(handle.ActorId)}:{handle.ActorId}"); delete.ExecuteNonQuery();
            }
        }
        if (scenario is "origin-note" or "origin-task" or "origin-attachment")
        {
            var view = await coordinator.ReviewPersonalActorIncomingTargetsAsync(handle);
            TestAssert.That(view["action_authorized"]!.GetValue<bool>() == false && JsonNode.DeepEquals(view["targets"]![0], target), "Origin review lost target/no-action boundary.");
            var choice = new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "delete", ["expected_clock"] = target["clock"]!.DeepClone(), ["confirm_conflict"] = true };
            var draft = await coordinator.ReviewPersonalActorIncomingTargetsAsync(handle, view["revision"]!.GetValue<string>(), [choice]);
            TestAssert.That(!draft["action_authorized"]!.GetValue<bool>() && draft["conflicts_explicitly_confirmed"]!.GetValue<bool>() && captures() == 2,
                "Origin choice reused a capture or acquired action rights.");
            owner.RecordSaved("target-observer", true, snapshot.SavedBook.Sha256);
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReviewPersonalActorIncomingTargetsAsync(handle, view["revision"]!.GetValue<string>(), [choice]), "Old review survived actual new save.");
        }
        else if (scenario != "origin-partial")
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle), "Invalid origin remained readable: " + scenario);
        if (scenario is "origin-note" or "origin-task" or "origin-attachment" or "origin-conflict" or "origin-partial" or "origin-capacity" or "origin-expired" or "origin-foreign-key")
            TestAssert.That(JsonNode.DeepEquals(await coordinator.PersonalActorStatusAsync(handle), beforeStatus), "Origin mutated raw registry/data status.");
        TestAssert.That(transport.Length == beforeWire && emitted() == beforeEmitted && Rows() == beforeRows, "Origin changed wire, callbacks or outgoing queue: " + scenario);
        if (scenario is not ("origin-note" or "origin-task" or "origin-attachment" or "origin-cancelled" or "origin-channel" or "origin-source" or "origin-local-grant" or "origin-remote-grant"))
            TestAssert.That(owner.SaveState("target-observer", true) == beforeSaved, "Origin mutated native saved book.");
        if (scenario is "origin-note" or "origin-task" or "origin-attachment")
            TestAssert.That(JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope), "Origin widened data scope.");
    }
}
