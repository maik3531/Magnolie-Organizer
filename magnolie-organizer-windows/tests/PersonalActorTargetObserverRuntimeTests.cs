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

    internal static Task RunAsync() => RunCasesAsync(null, null);
    internal static Task RunHistoricalSourceAsync(JsonObject fixture, string fault) => RunCasesAsync(fixture, fault);

    private static async Task RunCasesAsync(JsonObject? sourceFixture, string? sourceFault)
    {
        var scenarios = new[] { "note", "task", "attachment", "foreign-owner", "cancelled", "local-grant", "remote-grant",
            "skip-deletions", "channel", "missing-snapshot", "saved-mismatch", "source-mismatch", "save-during-capture", "invalid-group", "empty-group", "over-capacity",
            "origin-note", "origin-task", "origin-attachment", "origin-raw-only", "origin-foreign-key", "origin-conflict", "origin-partial",
            "origin-local-grant", "origin-remote-grant", "origin-expired", "origin-cancelled", "origin-capacity", "origin-channel", "origin-source",
            "origin-wall", "origin-mono", "origin-request-missing", "origin-pending-note", "origin-pending-task", "origin-pending-attachment",
            "pending-attachment-missing-parent", "pending-attachment-foreign-parent", "pending-attachment-duplicate-parent" }.Concat(
                from kind in new[] { "note", "task", "attachment" }
                from fault in new[] { "resolved", "old-ack", "foreign-peer", "conflict", "forged-proposal", "nonempty-hash", "present-object" }
                select $"pending-{kind}-{fault}");
        foreach (var scenario in sourceFixture is null ? scenarios : new[] { "origin-local-source-" + sourceFixture["target"]!["kind"]!.GetValue<string>() + "-" + sourceFault })
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
                if (sourceFixture is not null) peer = store.LoadPeers().Single(value => value.Id == peer.Id);
                var scope = sourceFixture is not null && sourceFault?.StartsWith("prepare-", StringComparison.Ordinal) == true
                    ? PhoneContentScope.Create(sourceFixture["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()),
                        sourceFixture["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()))
                    : PhoneContentScope.Create(["selected-note"], ["selected-task"]);
                foreach (var chunk in PhoneContentScope.Chunks(scope)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, chunk));
                var kind = scenario.Split('-').Contains("task") ? "task" : scenario.Split('-').Contains("attachment") ? "attachment" : "note";
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
                if (sourceFixture is not null)
                {
                    book = sourceFixture["book"]!.DeepClone().AsObject(); target = sourceFixture["target"]!.DeepClone().AsObject();
                    id = target["id"]!.GetValue<string>(); clock = target["clock"]!.DeepClone().AsArray();
                    var state = book["personalSync"]!.AsObject(); state["peer_device_id"] = peer.Id;
                    var meta = state["entities"]![kind + "\0" + id]!.AsObject(); meta["peer_device_id"] = peer.Id;
                    meta["proposal_id"] = PersonalSyncContract.DeletionProposalId(peer.Id, kind, id, "", clock, meta["prior_hash"]!.GetValue<string>());
                    if (sourceFault == "missing") book["papierkorb"]!.AsArray().Clear();
                    if (sourceFault == "changed") book["papierkorb"]![0]!["eintrag"]!["titel"] = "Changed source";
                    if (sourceFault == "duplicate") book["papierkorb"]!.AsArray().Add(book["papierkorb"]![0]!.DeepClone());
                }
                if (scenario.StartsWith("pending-", StringComparison.Ordinal) || scenario.StartsWith("origin-pending-", StringComparison.Ordinal))
                {
                    var meta = book["personalSync"]!["entities"]!.AsObject().Single().Value!.AsObject();
                    meta["state"] = "deleted"; meta["status"] = "local_pending"; meta["hash"] = ""; meta["prior_hash"] = new string('a', 64);
                    meta["deleted_ms"] = 2; meta["label"] = "Synthetic native pending";
                    meta["proposal_id"] = PersonalSyncContract.DeletionProposalId(peer.Id, kind, id, parent, clock, new string('a', 64));
                    if (kind == "note") book["notizen"]!.AsArray().Clear();
                    else if (kind == "task") book["aufgaben"]!.AsArray().Clear();
                    else book["notizen"]![0]!["anhaenge"]!.AsArray().Clear();
                    if (scenario.EndsWith("-resolved", StringComparison.Ordinal)) meta["status"] = "resolved";
                    if (scenario.EndsWith("-old-ack", StringComparison.Ordinal)) { meta.Clear(); meta["acknowledged_by_peer"] = true; }
                    if (scenario.EndsWith("-foreign-peer", StringComparison.Ordinal)) meta["peer_device_id"] = Guid.NewGuid().ToString("D");
                    if (scenario.EndsWith("-conflict", StringComparison.Ordinal)) meta["conflict"] = true;
                    if (scenario.EndsWith("-forged-proposal", StringComparison.Ordinal)) meta["proposal_id"] = Guid.NewGuid().ToString("D");
                    if (scenario.EndsWith("-nonempty-hash", StringComparison.Ordinal)) meta["hash"] = new string('a', 64);
                    if (scenario.EndsWith("-present-object", StringComparison.Ordinal))
                    {
                        if (kind == "note") book["notizen"]!.AsArray().Add(new JsonObject { ["id"] = id });
                        else if (kind == "task") book["aufgaben"]!.AsArray().Add(new JsonObject { ["id"] = id });
                        else book["notizen"]![0]!["anhaenge"]!.AsArray().Add(new JsonObject { ["id"] = id });
                    }
                    if (scenario.EndsWith("-missing-parent", StringComparison.Ordinal)) book["notizen"]!.AsArray().Clear();
                    if (scenario.EndsWith("-foreign-parent", StringComparison.Ordinal)) book["notizen"]![0]!["baumQuelle"] = "foreign-owner";
                    if (scenario.EndsWith("-duplicate-parent", StringComparison.Ordinal)) book["notizen"]!.AsArray().Add(book["notizen"]![0]!.DeepClone());
                }
                var owner = new NativeBookOwnerScope(); owner.SetReady(true); var text = book.ToJsonString();
                owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text));
                coordinator.NativeBookSource = () => owner.Current("target-observer", true);
                coordinator.NativeSavedBook = () => owner.SaveState("target-observer", true);
                var captured = NativeActorBookSnapshot.Capture(() => owner.SaveState("target-observer", true), () => text)!;
                var captures = 0;
                coordinator.NativeProducerBook = () => { captures++; if (scenario == "save-during-capture") owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text)); return captured; };
                PersonalActorNativeSaveHost? nativeSaveHost = null;
                if (scenario.Contains("-prepare-bridge-", StringComparison.Ordinal))
                {
                    nativeSaveHost = new PersonalActorNativeSaveHost(root, text);
                    coordinator.NativeBookSource = nativeSaveHost.Source;
                    coordinator.NativeSavedBook = nativeSaveHost.Saved;
                    coordinator.NativeProducerBook = nativeSaveHost.Snapshot;
                }
                var handle = await coordinator.CreatePersonalActorAsync(peer.Id, TelefonCrypto.Fingerprint(peer.PublicKey));
                if (scenario.StartsWith("origin-", StringComparison.Ordinal))
                {
                    await OriginAsync(scenario, coordinator, store, peer, connection, handle, target, grants, owner, captured, scope,
                        wire, () => emitted, () => captures, sourceFixture?["format"]?.GetValue<int>() ?? 3, sourceFixture, nativeSaveHost);
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

    private static async Task HistoricalBridgeSaveAsync(string scenario, TelefonCoordinator coordinator, TelefonStore store, TelefonPeer peer,
        TelefonConnection connection, PersonalActorHandle handle, JsonObject scope, string candidateText, string token, PersonalActorNativeSaveHost host, NativeHistoricalWriterInvocation invocation)
    {
        var beforeBytes = File.ReadAllBytes(host.DataPath); var before = host.Saved();
        if (scenario.EndsWith("-user-save", StringComparison.Ordinal))
        {
            var independent = JsonNode.Parse(host.Snapshot()!.Text)!.AsObject();
            var live = independent["notizen"]!.AsArray().FirstOrDefault() ?? independent["aufgaben"]!.AsArray().First();
            live!["titel"] = "Synthetic independent user edit";
            using var ordinary = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 9, ["text"] = independent.ToJsonString() }.ToJsonString());
            await host.SaveAsync(ordinary.RootElement);
            TestAssert.That(host.Responses.Last().Value["ok"]!.GetValue<bool>(), "Independent ordinary user edit was not actually saved.");
            beforeBytes = File.ReadAllBytes(host.DataPath); before = host.Saved();
        }
        var beforeSnapshots = host.Snapshots;
        var sentText = scenario.EndsWith("-payload", StringComparison.Ordinal) ? candidateText + " " : candidateText;
        host.FailAfterPrimary = scenario.EndsWith("-uncertain", StringComparison.Ordinal);
        using var message = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = sentText }.ToJsonString());
        await host.SaveAsync(message.RootElement, invocation);
        var result = host.Responses.Single(value => value.Callback == "App.gespeichert" && value.Value["id"]?.GetValue<int>() == 1).Value;
        if (scenario.EndsWith("-payload", StringComparison.Ordinal) || scenario.EndsWith("-user-save", StringComparison.Ordinal))
        {
            TestAssert.That(!result["ok"]!.GetValue<bool>() && host.Available && host.Saved() == before && host.Snapshots == beforeSnapshots &&
                beforeBytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)), "Denied payload mutated the actual SaveAsync file/book/snapshot.");
            if (scenario.EndsWith("-user-save", StringComparison.Ordinal))
            {
                TestAssert.That(new EncryptionService().Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password).Contains("Synthetic independent user edit", StringComparison.Ordinal),
                    "Historical save overwrote a newer independent user edit.");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token), "Independent ordinary user save was misattributed as a historical restore.");
                var status = await coordinator.PersonalActorStatusAsync(handle);
                TestAssert.That(status["phase"]!.GetValue<string>() == "cancelled" && !status["historical_book_persisted"]!.GetValue<bool>() && !status["phone_persisted"]!.GetValue<bool>(),
                    "Stale historical claim survived independent user persistence.");
            }
            return;
        }
        var actualBytes = File.ReadAllBytes(host.DataPath);
        TestAssert.That(new EncryptionService().Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password) == candidateText, "Actual SaveAsync lost exact encrypted candidate bytes.");
        if (scenario.EndsWith("-uncertain", StringComparison.Ordinal))
        {
            TestAssert.That(!result["ok"]!.GetValue<bool>() && !host.Available && host.Saved() is null, "Uncertain actual SaveAsync left stale memory writable.");
            host.FailAfterPrimary = false;
            using var stale = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 2, ["text"] = "{\"stale\":true}" }.ToJsonString());
            await host.SaveAsync(stale.RootElement);
            TestAssert.That(host.Responses.Last(value => value.Callback == "App.gespeichert").Value["ok"]!.GetValue<bool>() == false && actualBytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)),
                "Ordinary autosave overwrote uncertain actual saved content with stale memory.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token), "Uncertain actual bridge save fabricated its native witness.");
            return;
        }
        TestAssert.That(result["ok"]!.GetValue<bool>() && result["standSha256"]!.GetValue<string>() == BaumSyncSnapshot.Hash(candidateText) && host.Saved()?.Sequence == before!.Sequence + 1,
            "Actual bridge save did not establish its own exact native witness.");
        var confirmed = await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token);
        await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token);
        TestAssert.That(confirmed["historical_book_persisted"]!.GetValue<bool>() && !confirmed["phone_data_persisted"]!.GetValue<bool>() && actualBytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)),
            "Actual bridge confirmation changed the saved file or fabricated ordinary data persistence.");
        var queued = store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Single(item => item.Message["kind"]?.GetValue<string>() == PersonalSyncActorContract.DataKind && item.Message["body"]?["run_id"]?.GetValue<string>() == handle.ActorId);
        await coordinator.PumpPersonalActorAsync(connection);
        await coordinator.ReceivePersonalActorAsync(connection, peer, Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(handle.ActorId, queued.Id)));
        var done = await coordinator.PersonalActorStatusAsync(handle);
        TestAssert.That(done["phase"]!.GetValue<string>() == "completed" && done["phone_persisted"]!.GetValue<bool>() && !done["phone_data_persisted"]!.GetValue<bool>() &&
            JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope) && actualBytes.AsSpan().SequenceEqual(File.ReadAllBytes(host.DataPath)),
            "Actual bridge save receipt changed native file/data scope or lost exact completion.");
    }

    // Actual product AES/atomic file writer, but not WinForms/physical phone E2E.
    private static async Task HistoricalFileWriterAsync(string scenario, TelefonCoordinator coordinator, TelefonStore store, TelefonPeer peer,
        TelefonConnection connection, PersonalActorHandle handle, NativeBookOwnerScope owner, JsonObject scope, string beforeText, string candidateText, string token, MemoryStream transport)
    {
        var directory = Path.Combine(Path.GetTempPath(), "magnolie-historical-writer-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "book.json"); var atomic = new AtomicStore(); var encryption = new EncryptionService();
            const string password = "synthetic-only-historical-writer";
            atomic.WriteRecoverableJson(path, encryption.Enable(beforeText, password));
            var beforeBytes = File.ReadAllBytes(path); var saved = owner.SaveState("target-observer", true); var writes = 0;
            var wireBefore = transport.Length;
            var invocation = new NativeHistoricalWriterInvocation(coordinator, handle, token);
            Action<string> writer = text => {
                writes++;
                if (scenario.EndsWith("-failure", StringComparison.Ordinal)) throw new IOException("Synthetic pre-write failure");
                atomic.WriteRecoverableJson(path, encryption.EncryptData(text));
                if (scenario.EndsWith("-after-write", StringComparison.Ordinal)) throw new IOException("Synthetic failure after atomic file replacement");
                owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(text));
                coordinator.NativeProducerBook = () => NativeActorBookSnapshot.Capture(() => owner.SaveState("target-observer", true), () => text);
            };
            if (scenario.EndsWith("-after-write", StringComparison.Ordinal))
            {
                await TestAssert.ThrowsAsync<IOException>(() => invocation.WriteAsync(candidateText, writer), "Uncertain post-write outcome minted persistence.");
                var actualBytes = File.ReadAllBytes(path);
                TestAssert.That(new EncryptionService().Unlock(File.ReadAllText(path), password) == candidateText, "Uncertain writer rolled back the actual saved content.");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => invocation.WriteAsync(candidateText, writer), "Uncertain write was replayed.");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token), "Missing native SaveACK became a receipt after I/O failure.");
                var status = await coordinator.PersonalActorStatusAsync(handle);
                TestAssert.That(writes == 1 && status["phase"]!.GetValue<string>() == "cancelled" && !status["historical_book_persisted"]!.GetValue<bool>() &&
                    actualBytes.AsSpan().SequenceEqual(File.ReadAllBytes(path)) && owner.SaveState("target-observer", true) == saved && transport.Length == wireBefore,
                    "Uncertain encrypted write fabricated a SaveACK or changed the actual file twice.");
                return;
            }
            if (scenario.EndsWith("-failure", StringComparison.Ordinal))
                await TestAssert.ThrowsAsync<IOException>(() => invocation.WriteAsync(candidateText, writer), "Writer failure was promoted to persistence.");
            else if (scenario.EndsWith("-payload", StringComparison.Ordinal))
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => invocation.WriteAsync(candidateText + " ", writer), "Changed payload reached the encrypted writer.");
            else
            {
                var awaitingConfirm = await invocation.WriteAsync(candidateText, writer);
                TestAssert.That(!awaitingConfirm["historical_book_persisted"]!.GetValue<bool>(), "Writer invocation manufactured a confirmed receipt.");
                TestAssert.That(new EncryptionService().Unlock(File.ReadAllText(path), password) == candidateText && EncryptionService.IsEncrypted(File.ReadAllText(path)), "Actual encrypted file lost the exact prepared candidate.");
                TestAssert.That(owner.SaveState("target-observer", true)?.Sequence == saved!.Sequence + 1, "Actual writer did not record exactly one save.");
                await TestAssert.ThrowsAsync<InvalidOperationException>(() => invocation.WriteAsync(candidateText, writer), "Actual encrypted writer was replayed.");
                var bytes = File.ReadAllBytes(path);
                var confirmed = await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token);
                await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token);
                TestAssert.That(confirmed["historical_book_persisted"]!.GetValue<bool>() && writes == 1 && bytes.AsSpan().SequenceEqual(File.ReadAllBytes(path)), "Confirm repeated the encrypted save.");
                var queued = store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Single(item => item.Message["kind"]?.GetValue<string>() == PersonalSyncActorContract.DataKind && item.Message["body"]?["run_id"]?.GetValue<string>() == handle.ActorId);
                await coordinator.PumpPersonalActorAsync(connection);
                await coordinator.ReceivePersonalActorAsync(connection, peer, Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(handle.ActorId, queued.Id)));
                var done = await coordinator.PersonalActorStatusAsync(handle);
                TestAssert.That(done["phase"]!.GetValue<string>() == "completed" && done["phone_persisted"]!.GetValue<bool>() && !done["phone_data_persisted"]!.GetValue<bool>(), "Real encrypted save did not bind exact historical receipt.");
                TestAssert.That(JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope) && bytes.AsSpan().SequenceEqual(File.ReadAllBytes(path)), "Receipt changed original scope or encrypted bytes.");
                return;
            }
            TestAssert.That(writes == (scenario.EndsWith("-failure", StringComparison.Ordinal) ? 1 : 0) && beforeBytes.AsSpan().SequenceEqual(File.ReadAllBytes(path)) && owner.SaveState("target-observer", true) == saved && transport.Length == wireBefore,
                "Denied/failed writer changed encrypted file/save/wire.");
        }
        finally { Directory.Delete(directory, recursive: true); }
    }

    // Native writer ACK is deliberately synthetic here, not GUI/file/E2E proof.
    private static async Task HistoricalConfirmAsync(string scenario, TelefonCoordinator coordinator, TelefonStore store, TelefonPeer peer,
        TelefonConnection connection, PersonalActorHandle handle, NativeBookOwnerScope owner, JsonObject scope, string candidateText, string token, MemoryStream transport)
    {
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token), "Confirm skipped the writer invocation.");
        await coordinator.CheckPersonalActorHistoricalRestoreSaveAsync(handle, token, candidateText);
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token), "Invocation marker became a successful SaveACK.");
        if (scenario.EndsWith("-bytes", StringComparison.Ordinal))
        {
            var changed = JsonNode.Parse(candidateText)!.AsObject(); changed["einstellungen"]!["unrelated_synthetic_change"] = true;
            candidateText = changed.ToJsonString();
        }
        owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(candidateText));
        if (scenario.EndsWith("-sequence", StringComparison.Ordinal)) owner.RecordSaved("target-observer", true, BaumSyncSnapshot.Hash(candidateText));
        var captured = NativeActorBookSnapshot.Capture(() => owner.SaveState("target-observer", true), () => candidateText)!;
        coordinator.NativeProducerBook = () => captured;
        if (scenario.EndsWith("-scope", StringComparison.Ordinal))
        {
            var changed = PhoneContentScope.Create(["foreign"], []);
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
        }
        if (scenario.EndsWith("-grant", StringComparison.Ordinal)) store.SetLocalGrant("personal_deletions_sync", false);
        var beforeWire = transport.Length; var saved = owner.SaveState("target-observer", true);
        long Rows()
        {
            using var db = store.OpenDatabase(); db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT COUNT(*) FROM outbox";
            return Convert.ToInt64(query.ExecuteScalar());
        }
        var rows = Rows();
        var positive = scenario.EndsWith("-none", StringComparison.Ordinal) || scenario.EndsWith("-later-save", StringComparison.Ordinal);
        if (!positive)
        {
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle,
                scenario.EndsWith("-token", StringComparison.Ordinal) ? new string('f', 64) : token), "Mismatched native SaveACK minted a terminal receipt.");
            var status = await coordinator.PersonalActorStatusAsync(handle);
            TestAssert.That(!status["historical_book_persisted"]!.GetValue<bool>() && !status["phone_persisted"]!.GetValue<bool>() && Rows() == rows && transport.Length == beforeWire,
                "Rejected confirmation changed queue/wire/persistence claims.");
        }
        else
        {
            var status = await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token);
            TestAssert.That(status["historical_book_persisted"]!.GetValue<bool>() && !status["book_persisted"]!.GetValue<bool>() && !status["phone_data_persisted"]!.GetValue<bool>() &&
                !status["phone_persisted"]!.GetValue<bool>() && status["phase"]!.GetValue<string>() == "completion", "Historical confirmation fabricated an ordinary data receipt.");
            TestAssert.That(JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope), "Confirm changed original data membership.");
            rows = Rows();
            TestAssert.That(JsonNode.DeepEquals(status, await coordinator.ConfirmPersonalActorHistoricalRestoreSaveAsync(handle, token)) && Rows() == rows && owner.SaveState("target-observer", true) == saved,
                "Confirm retry wrote twice or duplicated the decision queue.");
            var queued = store.Due(peer.Id, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Where(item => item.Message["kind"]?.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                item.Message["body"]?["run_id"]?.GetValue<string>() == handle.ActorId).ToArray();
            TestAssert.That(queued.Length == 1 && PersonalSyncActorContract.Unwrap(queued[0].Message["body"]!.AsObject()).Kind == "personal_sync.deletion_decision", "Historical receipt union included unrelated frames.");
            await coordinator.PumpPersonalActorAsync(connection);
            TestAssert.That(transport.Length > beforeWire, "Historical terminal decision was never dispatched.");
            if (scenario.EndsWith("-later-save", StringComparison.Ordinal)) owner.RecordSaved("target-observer", true, saved!.Sha256);
            var afterWire = transport.Length;
            await coordinator.ReceivePersonalActorAsync(connection, peer, Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(handle.ActorId, queued[0].Id)));
            var done = await coordinator.PersonalActorStatusAsync(handle);
            var lost = scenario.EndsWith("-later-save", StringComparison.Ordinal);
            TestAssert.That(done["phase"]!.GetValue<string>() == (lost ? "cancelled" : "completed") && done["phone_persisted"]!.GetValue<bool>() == !lost &&
                !done["phone_data_persisted"]!.GetValue<bool>() && transport.Length == afterWire, "Exact historical receipt lost saved-book or data-closed boundary.");
        }
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.WithPersonalActorStoreAsync(registry => { registry.RequireCurrent(handle); return true; }), "Confirm reopened ordinary data.");
        TestAssert.That(captured.Text == candidateText && owner.SaveState("target-observer", true)?.Sha256 == BaumSyncSnapshot.Hash(candidateText), "Confirmation rolled back saved local content.");
    }

    private static async Task OriginAsync(string scenario, TelefonCoordinator coordinator, TelefonStore store, TelefonPeer peer,
        TelefonConnection connection, PersonalActorHandle handle, JsonObject target, JsonObject grants, NativeBookOwnerScope owner,
        NativeActorBookSnapshot snapshot, JsonObject scope, MemoryStream transport, Func<int> emitted, Func<int> captures, int wireFormat = 3, JsonObject? sourceFixture = null,
        PersonalActorNativeSaveHost? nativeSaveHost = null)
    {
        await coordinator.StartPersonalActorAsync(handle);
        var request = new JsonObject { ["format"] = wireFormat, ["run_id"] = handle.ActorId, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
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
        if (scenario.StartsWith("origin-local-source-", StringComparison.Ordinal))
        {
            await coordinator.ReceivePersonalActorAsync(connection, peer, message);
            var script = scenario.Contains("-script-", StringComparison.Ordinal);
            JsonObject Request(string action) => new() { ["action"] = action, ["actorId"] = handle.ActorId, ["ownerToken"] = handle.OwnerToken };
            var view = script ? (await coordinator.ExecuteMcpAsync(Request("notes_actor_historical_review"), CancellationToken.None))["actor"]!.AsObject()
                : await coordinator.ReviewPersonalActorIncomingTargetsAsync(handle);
            var choice = new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "restore",
                ["expected_clock"] = target["clock"]!.DeepClone(), ["confirm_conflict"] = true };
            if (scenario.Contains("-prepare-", StringComparison.Ordinal))
            {
                var proposed = JsonNode.Parse(sourceFixture!["candidate_text"]!.GetValue<string>())!.AsObject();
                proposed["personalSync"]!["peer_device_id"] = peer.Id;
                proposed["personalSync"]!["entities"]![target["kind"]!.GetValue<string>() + "\0" + target["id"]!.GetValue<string>()]!["peer_device_id"] = peer.Id;
                if (scenario.EndsWith("-candidate", StringComparison.Ordinal))
                {
                    proposed["einstellungen"]!["unrelated_synthetic_change"] = true;
                    await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.PreparePersonalActorHistoricalRestoreSaveAsync(handle,
                        view["revision"]!.GetValue<string>(), [choice], proposed.ToJsonString()), "Unrelated candidate mutation minted a historical writer claim.");
                    await coordinator.WithPersonalActorStoreAsync(registry => { registry.RequireCurrent(handle); return true; });
                    TestAssert.That(JsonNode.DeepEquals(beforeStatus, await coordinator.PersonalActorStatusAsync(handle)), "Rejected candidate retired the original native data owner.");
                }
                else
                {
                    var candidateText = proposed.ToJsonString();
                    NativeHistoricalWriterInvocation? bridgeInvocation = null;
                    JsonObject claim;
                    if (nativeSaveHost is not null)
                    {
                        var issued = await nativeSaveHost.PreparePersonalActorHistoricalSaveAsync(coordinator, handle, view["revision"]!.GetValue<string>(), [choice], candidateText);
                        claim = issued.Claim; bridgeInvocation = issued.Invocation;
                    }
                    else claim = await coordinator.PreparePersonalActorHistoricalRestoreSaveAsync(handle, view["revision"]!.GetValue<string>(), [choice], candidateText);
                    TestAssert.That(claim["data_closed"]!.GetValue<bool>() && !claim["book_persisted"]!.GetValue<bool>() && !claim["phone_persisted"]!.GetValue<bool>(), "Prepare manufactured a saved/peer receipt.");
                    await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.WithPersonalActorStoreAsync(registry => { registry.RequireCurrent(handle); return true; }), "Prepared owner retained data access.");
                    var token = claim["claim_token"]!.GetValue<string>();
                    if (nativeSaveHost is not null)
                    {
                        await HistoricalBridgeSaveAsync(scenario, coordinator, store, peer, connection, handle, scope, candidateText, token, nativeSaveHost, bridgeInvocation!);
                        return;
                    }
                    if (scenario.Contains("-prepare-file-", StringComparison.Ordinal))
                    {
                        await HistoricalFileWriterAsync(scenario, coordinator, store, peer, connection, handle, owner, scope, snapshot.Text, candidateText, token, transport);
                        return;
                    }
                    if (scenario.Contains("-prepare-confirm-", StringComparison.Ordinal))
                    {
                        await HistoricalConfirmAsync(scenario, coordinator, store, peer, connection, handle, owner, scope, candidateText, token, transport);
                        return;
                    }
                    if (scenario.EndsWith("-token", StringComparison.Ordinal)) token = new string('f', 64);
                    if (scenario.EndsWith("-payload", StringComparison.Ordinal)) candidateText += " ";
                    if (scenario.EndsWith("-save", StringComparison.Ordinal)) owner.RecordSaved("target-observer", true, snapshot.SavedBook.Sha256);
                    if (scenario.EndsWith("-frame", StringComparison.Ordinal))
                    {
                        var admissions = (System.Collections.IDictionary)typeof(TelefonCoordinator).GetField("actorAdmissions", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
                        var admitted = admissions[handle.ActorId]!;
                        var origin = admitted.GetType().GetProperty("IncomingTargetOrigin", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(admitted)!;
                        var frames = (Dictionary<string, byte[]>)origin.GetType().GetField("Frames", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(origin)!;
                        var id = frames.Keys.Single(); var changed = JsonNode.Parse(frames[id])!.AsObject();
                        changed["expires_ms"] = changed["expires_ms"]!.GetValue<long>() - 1; frames[id] = TelefonCrypto.Canonical(changed);
                    }
                    if (scenario.EndsWith("-grant", StringComparison.Ordinal)) store.SetLocalGrant("personal_deletions_sync", false);
                    if (scenario.EndsWith("-cancel", StringComparison.Ordinal)) await coordinator.WithPersonalActorStoreAsync(registry => registry.Cancel(handle));
                    if (scenario.EndsWith("-receive", StringComparison.Ordinal))
                    {
                        var status = await coordinator.PersonalActorStatusAsync(handle);
                        await coordinator.ReceivePersonalActorAsync(connection, peer, Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(handle.ActorId, Guid.NewGuid().ToString("D"))));
                        var records = new JsonArray(sourceFixture["live_records"]![0]!.DeepClone());
                        var data = new JsonObject { ["format"] = wireFormat, ["run_id"] = handle.ActorId, ["batch_id"] = Guid.NewGuid().ToString("D"),
                            ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records_hash"] = PersonalSyncContract.RecordsHash(records), ["records"] = records };
                        await coordinator.ReceivePersonalActorAsync(connection, peer, PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", data), handle.ActorId));
                        await coordinator.PumpPersonalActorAsync(connection);
                        TestAssert.That(JsonNode.DeepEquals(status, await coordinator.PersonalActorStatusAsync(handle)), "Prepared network controls admitted data or cancelled the native writer.");
                    }
                    var expectedSaved = owner.SaveState("target-observer", true);
                    if (scenario.EndsWith("-none", StringComparison.Ordinal) || scenario.EndsWith("-receive", StringComparison.Ordinal))
                    {
                        await coordinator.CheckPersonalActorHistoricalRestoreSaveAsync(handle, token, candidateText);
                        await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.CheckPersonalActorHistoricalRestoreSaveAsync(handle, token, candidateText), "Historical writer invocation was replayed.");
                    }
                    else await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.CheckPersonalActorHistoricalRestoreSaveAsync(handle, token, candidateText), "Changed native writer claim was accepted.");
                    TestAssert.That(expectedSaved == owner.SaveState("target-observer", true), "Native writer gate changed/reverted saved state.");
                }
                TestAssert.That(transport.Length == beforeWire && emitted() == beforeEmitted && Rows() == beforeRows, "Historical writer preparation changed wire/callbacks/outbox.");
                return;
            }
            if (scenario.EndsWith("-none", StringComparison.Ordinal))
            {
                JsonObject result;
                if (script)
                {
                    var requestReview = Request("notes_actor_historical_source_review");
                    requestReview["reviewRevision"] = view["revision"]!.DeepClone(); requestReview["choices"] = new JsonArray(choice.DeepClone());
                    result = (await coordinator.ExecuteMcpAsync(requestReview, CancellationToken.None))["actor"]!.AsObject();
                    TestAssert.That((await coordinator.ExecuteMcpAsync(Request("notes_actor_historical_save"), CancellationToken.None))["ok"]?.GetValue<bool>() == false,
                        "Metadata script route exposed an unreviewed historical save action.");
                }
                else result = await coordinator.ReviewPersonalActorHistoricalRestoreAsync(handle, view["revision"]!.GetValue<string>(), [choice]);
                TestAssert.That(!result["action_authorized"]!.GetValue<bool>() && result["restore_source_revision"]!.GetValue<string>().Length == 64 &&
                    JsonNode.DeepEquals(result["local_restore_sources"]![0]!["target"], target), "Historical source review lost original identity or no-action boundary.");
                TestAssert.That(!result.ToJsonString().Contains("Protected synthetic source", StringComparison.Ordinal) && !result.ToJsonString().Contains("data:", StringComparison.Ordinal), "Historical source review leaked source bytes.");
            }
            else await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReviewPersonalActorHistoricalRestoreAsync(handle,
                view["revision"]!.GetValue<string>(), [choice]), "Historical source review accepted an unavailable/changed source.");
            TestAssert.That(JsonNode.DeepEquals(beforeStatus, await coordinator.PersonalActorStatusAsync(handle)) && beforeSaved == owner.SaveState("target-observer", true),
                "Historical source review mutated registry or native saved book.");
            TestAssert.That(transport.Length == beforeWire && emitted() == beforeEmitted && Rows() == beforeRows, "Historical source review changed queue, callbacks or wire.");
            return;
        }
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
        var positive = scenario is "origin-note" or "origin-task" or "origin-attachment" or "origin-pending-note" or "origin-pending-task" or "origin-pending-attachment";
        if (positive)
        {
            var view = await coordinator.ReviewPersonalActorIncomingTargetsAsync(handle);
            TestAssert.That(view["action_authorized"]!.GetValue<bool>() == false && JsonNode.DeepEquals(view["targets"]![0], target), "Origin review lost target/no-action boundary.");
            TestAssert.That(view["observations"]![0]!["local_state"]!.GetValue<string>() == (scenario.Contains("pending", StringComparison.Ordinal) ? "deleted" : "live"), "Native review lost local pending/live classification.");
            var choice = new JsonObject { ["proposal_id"] = target["proposal_id"]!.DeepClone(), ["decision"] = "delete", ["expected_clock"] = target["clock"]!.DeepClone(), ["confirm_conflict"] = true };
            var draft = await coordinator.ReviewPersonalActorIncomingTargetsAsync(handle, view["revision"]!.GetValue<string>(), [choice]);
            TestAssert.That(!draft["action_authorized"]!.GetValue<bool>() && draft["conflicts_explicitly_confirmed"]!.GetValue<bool>() && captures() == 2,
                "Origin choice reused a capture or acquired action rights.");
            owner.RecordSaved("target-observer", true, snapshot.SavedBook.Sha256);
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReviewPersonalActorIncomingTargetsAsync(handle, view["revision"]!.GetValue<string>(), [choice]), "Old review survived actual new save.");
        }
        else if (scenario != "origin-partial")
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => coordinator.ReadPersonalActorIncomingTargetFramesAsync(handle), "Invalid origin remained readable: " + scenario);
        if (positive || scenario is "origin-conflict" or "origin-partial" or "origin-capacity" or "origin-expired" or "origin-foreign-key")
            TestAssert.That(JsonNode.DeepEquals(await coordinator.PersonalActorStatusAsync(handle), beforeStatus), "Origin mutated raw registry/data status.");
        TestAssert.That(transport.Length == beforeWire && emitted() == beforeEmitted && Rows() == beforeRows, "Origin changed wire, callbacks or outgoing queue: " + scenario);
        if (!positive && scenario is not ("origin-cancelled" or "origin-channel" or "origin-source" or "origin-local-grant" or "origin-remote-grant"))
            TestAssert.That(owner.SaveState("target-observer", true) == beforeSaved, "Origin mutated native saved book.");
        if (positive)
            TestAssert.That(JsonNode.DeepEquals(connection.CurrentContentScope(PhoneContentScope.Reference(scope)), scope), "Origin widened data scope.");
    }
}
