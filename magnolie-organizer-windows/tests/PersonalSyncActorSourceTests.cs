using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PersonalSyncActorSourceTests
{
    private sealed class ActorWireStream : MemoryStream
    {
        internal Action? AssertActorWrite;
        internal int GuardChecks;
        internal bool FailNextWrite, WasDisposed;
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellation = default)
        {
            if (AssertActorWrite is not null) { AssertActorWrite(); GuardChecks++; }
            if (FailNextWrite) { FailNextWrite = false; throw new IOException("Synthetic native encrypted ACK channel failure"); }
            return base.WriteAsync(buffer, cancellation);
        }
        protected override void Dispose(bool disposing) { WasDisposed = true; base.Dispose(disposing); }
    }
    private static JsonObject Message(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }

    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "actor-native-source-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, Enumerable.Repeat((byte)37, 32).ToArray());
            var identity = store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
            var peer = new TelefonPeer(Guid.NewGuid().ToString("D"), "Synthetic", Enumerable.Repeat((byte)23, 32).ToArray());
            store.SavePeers([peer]); store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
            store.SetLocalGrant("personal_notes_sync", true); store.SetLocalGrant("personal_tasks_sync", true);
            store.SetLocalGrant("personal_deletions_sync", true);
            var settings = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            settings = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "skip_deletions", JsonValue.Create(false)!);
            var capabilities = TelefonProtocolContract.DesktopCapabilities();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) capabilities["items"]![name]!["versions"]!.AsArray().Add(12);
            var grants = TelefonProtocolContract.DesktopGrants(); grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
            grants["personal_deletions_sync"] = true;
            Task<TelefonAck?> Receive(TelefonPeer _, JsonObject message)
            {
                var body = message["body"]!.AsObject();
                if (message["kind"]!.GetValue<string>() == "capabilities.update")
                    store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null);
                else if (message["kind"]!.GetValue<string>() == "grants.update")
                    store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject());
                else if (message["kind"]!.GetValue<string>() == "personal_sync.settings")
                    store.SetPersonalSettings(peer.Id, remoteOwnDevice: body["own_device"]!.GetValue<bool>());
                return Task.FromResult<TelefonAck?>(null);
            }
            var emitted = 0;
            using var coordinator = new TelefonCoordinator(paths, (_, _) => { emitted++; return Task.CompletedTask; }, dataStore: store,
                foregroundEnabled: true, localOnly: true) { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
            using var wire = new ActorWireStream();
            using var connection = new TelefonConnection(peer, wire, new byte[16], new byte[72], store, Receive, CancellationToken.None, "wifi")
                { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
            online[peer.Id] = connection;
            var fingerprint = TelefonCrypto.Fingerprint(peer.PublicKey);
            string? Read(Func<string?>? book = null) => coordinator.CurrentActorSource(peer.Id, fingerprint, book ?? (() => new string('a', 64)));
            string? CompletionAuthority() => coordinator.CurrentActorCompletionAuthority(peer.Id, fingerprint, () => new string('a', 64));
            TestAssert.That(Read() is null, "Missing fresh native controls admitted an actor source.");
            TestAssert.That(CompletionAuthority() is null, "Missing controls admitted terminal receipt authority.");
            await connection.HandlePlainAsync(Message("capabilities.update", capabilities));
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = grants }));
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), settings, peer.Id, identity.Id)));
            TestAssert.That(Read() is null, "A persisted preference agreement replaced fresh membership.");
            var manifest = PhoneContentScope.Create(["note-one"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(manifest)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var revision = Read(); var beforeWire = wire.Length; var beforeEmitted = emitted;
            TestAssert.That(revision is { Length: 64 } && Read() == revision, "Actual native source was unavailable or unstable.");
            foreach (var singleKind in new[] { "note", "task" })
            {
                var singleRequest = new JsonObject { ["format"] = 14, ["run_id"] = Guid.NewGuid().ToString("D"), ["trigger"] = "manual",
                    ["modules"] = new JsonArray(singleKind == "note" ? "notes" : "tasks"),
                    ["send_item"] = new JsonObject { ["kind"] = singleKind, ["id"] = singleKind + "-one" } };
                TestAssert.That(!coordinator.NoteDirectionAllowed(peer.Id, "personal_sync.request", singleRequest, false), "Unscoped reverse single-entry request was authorized.");
                var singleNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                new PersonalSyncStore(store).RememberScopedRun(peer.Id, peer.PublicKey, singleRequest, PhoneContentScope.Reference(manifest), singleNow, singleNow + 60000);
                TestAssert.That(coordinator.NoteDirectionAllowed(peer.Id, "personal_sync.request", singleRequest, false), "Current phone member could not start a scoped single-entry request.");
                var outsideSingle = singleRequest.DeepClone().AsObject(); outsideSingle["send_item"]!["id"] = "not-a-phone-member";
                TestAssert.That(!coordinator.NoteDirectionAllowed(peer.Id, "personal_sync.request", outsideSingle, false), "Reverse single-entry request widened physical phone membership.");
                var oldSingle = singleRequest.DeepClone().AsObject(); oldSingle["format"] = 3;
                TestAssert.That(!coordinator.NoteDirectionAllowed(peer.Id, "personal_sync.request", oldSingle, false), "Legacy admission was reinterpreted as reverse single-entry sync.");
            }
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, fingerprint) is null, "Unconfigured host book source was authorized.");
            var hostBook = new NativeBookOwnerScope(); hostBook.SetReady(true);
            coordinator.NativeBookSource = () => hostBook.Current("actual-host-profile", true);
            var hostSource = coordinator.CurrentActorSource(peer.Id, fingerprint);
            TestAssert.That(hostSource is not null, "Configured native host book was not source-bound.");
            hostBook.SetReady(false);
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, fingerprint) is null, "Native host lock remained source-authorized.");
            hostBook.SetReady(true);
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, fingerprint) is string reopened && reopened != hostSource,
                "Host lock/unlock inherited a previous actor source.");
            var actorSource = coordinator.CurrentActorSource(peer.Id, fingerprint)!;
            var actorHandle = await coordinator.WithPersonalActorStoreAsync(registry => {
                TestAssert.That(store.NotePolicyGate.CurrentCount == 0 && Monitor.IsEntered(
                    typeof(TelefonCoordinator).GetField("gate", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!),
                    "Native source/policy guards were not acquired before actor storage.");
                return registry.Create(peer.Id, fingerprint, actorSource);
            });
            var actorWire = Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(actorHandle.ActorId, Guid.NewGuid().ToString("D")));
            TestAssert.That(await coordinator.WithPersonalActorStoreAsync(registry => registry.Put(actorHandle, actorWire)), "Native factory did not persist a source-bound raw frame.");
            TestAssert.That(JsonNode.DeepEquals(actorWire, await coordinator.WithPersonalActorStoreAsync(registry => registry.Read(actorHandle, actorWire["message_id"]!.GetValue<string>()))),
                "Native factory changed raw actor wire data.");
            hostBook.SetReady(false);
            try
            {
                await coordinator.WithPersonalActorStoreAsync(registry => registry.Read(actorHandle, actorWire["message_id"]!.GetValue<string>()));
                throw new Exception("Native registry read survived loss of its actual host book.");
            }
            catch (InvalidOperationException) { }
            await coordinator.WithPersonalActorStoreAsync(registry => registry.Cancel(actorHandle));
            hostBook.SetReady(true);
            connection.ActorMessageReceived = (source, message) => coordinator.ReceivePersonalActorAsync(source, peer, message);
            await SharedSyncTransportTests.DrainAsync(wire);
            wire.AssertActorWrite = () => TestAssert.That(store.NotePolicyGate.CurrentCount == 1 && !Monitor.IsEntered(
                typeof(TelefonCoordinator).GetField("gate", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!),
                "Actor network I/O held native policy/source guards.");
            foreach (var ownScenario in new[] { "before-send", "after-marker", "metadata-failure", "post-send-book" })
            {
                var afterNativeSend = ownScenario == "after-marker";
                var ownHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
                await coordinator.StartPersonalActorAsync(ownHandle);
                await SharedSyncTransportTests.DrainAsync(wire);
                var ownProposal = Guid.NewGuid().ToString("D");
                var clock = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 2 });
                var target = new JsonObject { ["proposal_id"] = ownProposal, ["kind"] = "note", ["id"] = "note-one", ["parent_id"] = "",
                    ["prior_hash"] = new string('a', 64), ["clock"] = clock.DeepClone() };
                var decision = PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_decision", new JsonObject {
                    ["format"] = 1, ["run_id"] = ownHandle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = ownProposal, ["decision"] = "restore", ["expected_clock"] = clock.DeepClone() }) }), ownHandle.ActorId);
                var ownAck = Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(ownHandle.ActorId, decision["message_id"]!.GetValue<string>()));
                hostBook.RecordSaved("actual-host-profile", true, new string('a', 64));
                // Native guard injection exercises the real admitted receive
                // lane, not a yet-unimplemented incoming-decision controller.
                var ownCompletion = await coordinator.WithPersonalActorStoreAsync(registry => {
                    var guard = new PersonalActorDecisionCompletion(ownHandle.ActorId, new JsonArray(target), [decision],
                        () => coordinator.CurrentActorCompletionAuthority(peer.Id, fingerprint),
                        () => connection.CurrentContentScope(PhoneContentScope.Reference(manifest)),
                        () => hostBook.SaveState("actual-host-profile", true), () => registry.ReadCompletionControls(ownHandle),
                        nativeSentAcknowledgments: [ownAck]);
                    registry.BeginCompletion(ownHandle, guard.Validator); return guard;
                });
                var admissions = (System.Collections.IDictionary)typeof(TelefonCoordinator).GetField("actorAdmissions", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
                var admitted = admissions[ownHandle.ActorId]!;
                admitted.GetType().GetProperty("Completion", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(admitted, ownCompletion);
                if (afterNativeSend) await coordinator.WithPersonalActorStoreAsync(_ => { ownCompletion.RecordSuccessfulAcknowledgmentSend(ownAck); return true; });
                var ownEmitted = emitted;
                foreach (var status in new[] { "accepted", "duplicate", "rejected" })
                {
                    await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind,
                        PersonalSyncActorContract.Ack(ownHandle.ActorId, decision["message_id"]!.GetValue<string>(), status,
                            status == "rejected" ? "temporary_failure" : "none")));
                    await coordinator.WithPersonalActorStoreAsync(registry => {
                        TestAssert.That(ownCompletion.Summary()["saved"]!.GetValue<int>() == 0 && registry.ReadCompletionControls(ownHandle).Count == 0 &&
                            registry.Status(ownHandle)["phase"]!.GetValue<string>() == "completion", "Peer claim counted or retired this endpoint's native ACK.");
                        return true;
                    });
                    TestAssert.That(wire.Length == 0 && emitted == ownEmitted, "Peer claim emitted wire/GUI side effects.");
                }
                var nativeAcks = (Dictionary<string, JsonObject>)admitted.GetType().GetProperty("NativeAcknowledgments", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(admitted)!;
                nativeAcks.Add(ownAck["message_id"]!.GetValue<string>(), ownAck.DeepClone().AsObject());
                var savedOwnBook = hostBook.SaveState("actual-host-profile", true);
                admitted.GetType().GetProperty("SaveReceipt", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(admitted, savedOwnBook);
                admitted.GetType().GetProperty("PhoneDataPersisted", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(admitted, true);
                coordinator.NativeSavedBook = () => hostBook.SaveState("actual-host-profile", true);
                if (ownScenario == "metadata-failure")
                {
                    using (var db = store.OpenDatabase())
                    {
                        db.Open(); using var sql = db.CreateCommand();
                        sql.CommandText = "CREATE TRIGGER native_ack_metadata_failure BEFORE INSERT ON personal_actor_completion_wire BEGIN SELECT RAISE(ABORT,'synthetic native ACK metadata failure'); END"; sql.ExecuteNonQuery();
                    }
                    var failed = false;
                    try { await coordinator.PumpPersonalActorAsync(connection); }
                    catch (Microsoft.Data.Sqlite.SqliteException) { failed = true; }
                    TestAssert.That(failed && ownCompletion.Summary()["saved"]!.GetValue<int>() == 0 && nativeAcks.Count == 1,
                        "Successful socket write substituted for failed protected ACK persistence.");
                    TestAssert.That(JsonNode.DeepEquals((await SharedSyncTransportTests.DrainAsync(wire)).Single(), ownAck), "Metadata fault lost the actual sent ACK identity.");
                    await coordinator.WithPersonalActorStoreAsync(registry => {
                        TestAssert.That(registry.ReadCompletionControls(ownHandle).Count == 0 && registry.Status(ownHandle)["phase"]!.GetValue<string>() == "completion",
                            "Failed ACK metadata write finished native completion."); return true;
                    });
                    using (var db = store.OpenDatabase())
                    { db.Open(); using var sql = db.CreateCommand(); sql.CommandText = "DROP TRIGGER native_ack_metadata_failure"; sql.ExecuteNonQuery(); }
                    await coordinator.PumpPersonalActorAsync(connection);
                    TestAssert.That(wire.Length == 0, "Immediate native ACK retry bypassed backoff.");
                    admitted.GetType().GetProperty("NativeAckNextAttempt", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(admitted, 0L);
                }
                if (ownScenario == "post-send-book")
                {
                    var previousCheck = wire.AssertActorWrite; var changedBook = false; var denied = false;
                    wire.AssertActorWrite = () => {
                        previousCheck?.Invoke();
                        if (!changedBook) { changedBook = true; hostBook.RecordSaved("actual-host-profile", true, new string('b', 64)); }
                    };
                    try { await coordinator.PumpPersonalActorAsync(connection); }
                    catch (InvalidOperationException) { denied = true; }
                    finally { wire.AssertActorWrite = previousCheck; }
                    TestAssert.That(denied && JsonNode.DeepEquals((await SharedSyncTransportTests.DrainAsync(wire)).Single(), ownAck) &&
                        ownCompletion.Summary()["saved"]!.GetValue<int>() == 0 && emitted == ownEmitted,
                        "Post-send book change was counted as native ACK completion.");
                    await coordinator.WithPersonalActorStoreAsync(registry => {
                        TestAssert.That(registry.Status(ownHandle)["phase"]!.GetValue<string>() == "cancelled", "Post-send source change retained an active native owner."); return true;
                    });
                    continue;
                }
                await coordinator.PumpPersonalActorAsync(connection);
                var sentOwnAck = (await SharedSyncTransportTests.DrainAsync(wire)).Single();
                TestAssert.That(JsonNode.DeepEquals(sentOwnAck, ownAck) && nativeAcks.Count == 0 &&
                    hostBook.SaveState("actual-host-profile", true) == savedOwnBook && emitted == ownEmitted,
                    "Native ACK dispatch changed data, emitted GUI events or lost its exact identity.");
                await coordinator.WithPersonalActorStoreAsync(registry => {
                    TestAssert.That(registry.Status(ownHandle)["phase"]!.GetValue<string>() == "completed" &&
                        ownCompletion.Summary()["saved"]!.GetValue<int>() == 1 && registry.ReadCompletionControls(ownHandle).Count == 1,
                        "Actual encrypted native ACK send did not persist before completion."); return true;
                });
            }
            coordinator.NativeSavedBook = () => null;
            var transportHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
            var started = await coordinator.StartPersonalActorAsync(transportHandle);
            var startFrame = (await SharedSyncTransportTests.DrainAsync(wire)).Single();
            TestAssert.That(startFrame["kind"]!.GetValue<string>() == PersonalSyncActorContract.StartKind &&
                started["dispatch_started"]!.GetValue<bool>() && !started["persisted"]!.GetValue<bool>(), "Native actor start did not use its dedicated encrypted route.");
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind,
                PersonalSyncActorContract.Ack(transportHandle.ActorId, startFrame["message_id"]!.GetValue<string>())));
            TestAssert.That(wire.Length == 0, "Actor ACK was itself acknowledged.");
            var actorRequest = new JsonObject { ["format"] = 3, ["run_id"] = transportHandle.ActorId, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.request", actorRequest), transportHandle.ActorId));
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind, "Actor request did not reach private native staging.");
            var privatePeer = PersonalSyncActorContract.StoragePeer(transportHandle.ActorId);
            var proposalId = Guid.NewGuid().ToString("D");
            var deletionClock = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 2 });
            var proposals = new JsonObject { ["format"] = 1, ["run_id"] = transportHandle.ActorId,
                ["proposal_batch_id"] = Guid.NewGuid().ToString("D"), ["sequence"] = 0, ["last"] = true,
                ["proposals"] = new JsonArray(new JsonObject { ["proposal_id"] = proposalId, ["kind"] = "note", ["id"] = "note-one", ["parent_id"] = "",
                    ["clock"] = deletionClock.DeepClone(), ["prior_hash"] = new string('a', 64), ["deleted_ms"] = 2, ["label"] = "Owned proposal" }) };
            var proposalWire = PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_proposals", proposals), transportHandle.ActorId);
            var deletionEmitted = emitted;
            await connection.HandlePlainAsync(proposalWire);
            var intent = new PersonalSyncStore(store).DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Single();
            TestAssert.That(intent.PeerId == privatePeer && wire.Length == 0 && emitted == deletionEmitted,
                "Actor deletion intent reached ordinary storage, GUI adoption or a premature save receipt.");
            await connection.HandlePlainAsync(proposalWire);
            TestAssert.That(new PersonalSyncStore(store).DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Single().CommitToken == intent.CommitToken,
                "Actor deletion replay changed its native pending commit token.");
            var deletionPackets = await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>());
            var unrelatedProposal = proposals.DeepClone().AsObject(); unrelatedProposal["proposals"]![0]!["id"] = "outside-phone-scope";
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_proposals", unrelatedProposal), transportHandle.ActorId));
            var decisions = new JsonObject { ["format"] = 1, ["run_id"] = transportHandle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = proposalId, ["decision"] = "delete", ["expected_clock"] = deletionClock.DeepClone() }) };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_decision", decisions), transportHandle.ActorId));
            TestAssert.That(wire.Length == 0 && deletionPackets == await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>()),
                "Out-of-scope or unknown-prior deletion intent reached the raw inbox.");
            store.RememberPersonalProposalKinds(privatePeer, proposals, true);
            var staleDecision = decisions.DeepClone().AsObject(); staleDecision["decisions"]![0]!["expected_clock"]![0]!["counter"] = 3;
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_decision", staleDecision), transportHandle.ActorId));
            TestAssert.That(deletionPackets == await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>()),
                "Actor decision with a forged expected clock entered raw storage.");
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_decision", decisions), transportHandle.ActorId));
            TestAssert.That(new PersonalSyncStore(store).DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Count == 2 && wire.Length == 0,
                "Prior-bound actor decision was not privately staged or received a save ACK before book commit.");
            byte[] attachment = [137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3];
            var attachmentHash = Convert.ToHexString(SHA256.HashData(attachment)).ToLowerInvariant();
            var noteValue = new JsonObject { ["title"] = "Owned phone snapshot", ["text"] = "Only staged", ["html"] = "", ["notebook_id"] = "", ["symbol"] = "note",
                ["created_ms"] = 1, ["modified_ms"] = 2, ["attachments"] = new JsonArray(new JsonObject {
                    ["attachment_id"] = "actor-image", ["name"] = "owned.png", ["kind"] = "image", ["mime"] = "image/png",
                    ["size"] = attachment.Length, ["sha256"] = attachmentHash }) };
            var record = new JsonObject { ["kind"] = "note", ["id"] = "note-one", ["state"] = "live", ["modified_ms"] = 2,
                ["clock"] = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 1 }), ["hash"] = PersonalSyncContract.ProjectionHash(noteValue), ["value"] = noteValue };
            var records = new JsonArray(record);
            var batchBody = new JsonObject { ["format"] = 3, ["run_id"] = transportHandle.ActorId, ["batch_id"] = Guid.NewGuid().ToString("D"),
                ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records_hash"] = PersonalSyncContract.RecordsHash(records), ["records"] = records };
            var batchWire = PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", batchBody), transportHandle.ActorId);
            beforeEmitted = emitted;
            var waitingStaging = await coordinator.ReadPersonalActorStagingAsync(transportHandle);
            TestAssert.That(!waitingStaging["batch_ready"]!.GetValue<bool>(), "Native actor staging reader invented a complete batch.");
            var bridgeSource = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "notes_actor_source", ["peerId"] = peer.Id,
                ["fingerprint"] = fingerprint }, default);
            TestAssert.That(bridgeSource["ok"]!.GetValue<bool>() && bridgeSource["sourceRevision"]!.GetValue<string>() == coordinator.CurrentActorSource(peer.Id, fingerprint),
                "Private bridge source was not derived from the actual native owner.");
            var staleBridgeCreate = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "notes_actor_create", ["peerId"] = peer.Id,
                ["fingerprint"] = fingerprint, ["sourceRevision"] = new string('f', 64) }, default);
            TestAssert.That(!staleBridgeCreate["ok"]!.GetValue<bool>(), "Private actor bridge created a context from a client source revision.");
            await connection.HandlePlainAsync(batchWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind && emitted == beforeEmitted,
                "Private actor batch reached ordinary GUI handling or lacked its marked receipt.");
            var staged = new PersonalSyncStore(store).ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())
                .Single(value => value.PeerId == PersonalSyncActorContract.StoragePeer(transportHandle.ActorId));
            TestAssert.That(JsonNode.DeepEquals(staged.Records.Single(), record), "Existing private stager changed actor records.");
            var firstStaging = await coordinator.ReadPersonalActorStagingAsync(transportHandle, limit: 17);
            var bridgeRead = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "notes_actor_read", ["actorId"] = transportHandle.ActorId,
                ["ownerToken"] = transportHandle.OwnerToken, ["limit"] = 17 }, default);
            TestAssert.That(bridgeRead["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(bridgeRead["actor"], firstStaging),
                "Private bridge changed bounded native staging results.");
            var foreignBridgeRead = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "notes_actor_read", ["actorId"] = transportHandle.ActorId,
                ["ownerToken"] = new string('f', 64) }, default);
            TestAssert.That(!foreignBridgeRead["ok"]!.GetValue<bool>() && foreignBridgeRead["actor"] is null,
                "Private actor bridge accepted a foreign owner token.");
            using var stagingBytes = new MemoryStream(); stagingBytes.Write(Convert.FromBase64String(firstStaging["data_base64"]!.GetValue<string>()));
            var stagingOffset = firstStaging["next_offset"]?.GetValue<long>();
            while (stagingOffset is not null)
            {
                var page = await coordinator.ReadPersonalActorStagingAsync(transportHandle, (int)stagingOffset.Value, 17, firstStaging["revision"]!.GetValue<string>());
                var bytes = Convert.FromBase64String(page["data_base64"]!.GetValue<string>());
                TestAssert.That(bytes.Length <= 17, "Actor staging reader exceeded its byte limit.");
                stagingBytes.Write(bytes); stagingOffset = page["next_offset"]?.GetValue<long>();
            }
            var stagedValue = JsonNode.Parse(stagingBytes.ToArray())!.AsObject();
            TestAssert.That(JsonNode.DeepEquals(stagedValue["batch"]!["records"], staged.Records) &&
                JsonNode.DeepEquals(stagedValue["content_scope"], manifest) &&
                stagedValue["batch"]!["commit_token"]!.GetValue<string>() == staged.CommitToken && stagedValue["intents"]!.AsArray().Count == 2 &&
                Convert.ToHexString(SHA256.HashData(stagingBytes.ToArray())).ToLowerInvariant() == firstStaging["revision"]!.GetValue<string>(),
                "Private actor review bytes lost native records, commit tokens, intents or revision binding.");
            foreach (var rejectedRead in new Func<Task<JsonObject>>[] {
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, expectedRevision: waitingStaging["revision"]!.GetValue<string>()),
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, offset: 17),
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, limit: 65537),
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, attachmentSha256: attachmentHash),
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, expectedRevision: firstStaging["revision"]!.GetValue<string>(), attachmentSha256: new string('b', 64)),
                () => coordinator.ReadPersonalActorStagingAsync(transportHandle, expectedRevision: firstStaging["revision"]!.GetValue<string>(), attachmentSha256: attachmentHash) })
            {
                var rejectedReadback = false;
                try { await rejectedRead(); } catch (Exception error) when (error is InvalidOperationException or InvalidDataException) { rejectedReadback = true; }
                TestAssert.That(rejectedReadback, "Actor staging reader accepted stale revision or unbounded continuation.");
            }
            await coordinator.PumpPersonalActorAsync(connection);
            var attachmentRequest = (await SharedSyncTransportTests.DrainAsync(wire)).Single();
            TestAssert.That(PersonalSyncActorContract.Unwrap(attachmentRequest["body"]!.AsObject()).Kind == "personal_sync.attachment_request",
                "Native actor attachment request was not dispatched through the existing outbox.");
            var requestId = attachmentRequest["message_id"]!.GetValue<string>();
            await connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = requestId, ["status"] = "accepted", ["error"] = "none" });
            TestAssert.That(store.OutboxMessage(peer.Id, requestId) is not null, "Plain receipt consumed an actor request.");
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(transportHandle.ActorId, requestId)));
            TestAssert.That(store.OutboxMessage(peer.Id, requestId) is null, "Exact marked receipt left its actor request pending.");
            var packets = await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>());
            var outside = batchBody.DeepClone().AsObject(); outside["batch_id"] = Guid.NewGuid().ToString("D");
            outside["records"]![0]!["id"] = "private-outside-scope"; outside["records_hash"] = PersonalSyncContract.RecordsHash(outside["records"]!.AsArray());
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", outside), transportHandle.ActorId));
            TestAssert.That(wire.Length == 0 && packets == await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>()),
                "Out-of-scope actor data was persisted before membership authorization.");
            var chunkBody = new JsonObject { ["format"] = 2, ["run_id"] = transportHandle.ActorId, ["reply"] = true,
                ["records_hash"] = staged.RecordsHash, ["sha256"] = attachmentHash, ["index"] = 0, ["data"] = Convert.ToBase64String(attachment) };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_chunk", chunkBody), transportHandle.ActorId));
            TestAssert.That(wire.Length == 0 && packets == await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>()),
                "Actor attachment without its matching aggregate entered raw storage.");
            chunkBody["reply"] = false;
            var chunkWire = PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_chunk", chunkBody), transportHandle.ActorId);
            await connection.HandlePlainAsync(chunkWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["body"]!["message_id"]!.GetValue<string>() == chunkWire["message_id"]!.GetValue<string>(),
                "Private actor attachment lost its marked receipt.");
            var verified = new PersonalSyncStore(store).ReadVerifiedAttachment(PersonalSyncActorContract.StoragePeer(transportHandle.ActorId),
                transportHandle.ActorId, false, staged.RecordsHash, attachmentHash, "incoming", "wifi", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            TestAssert.That(verified.SequenceEqual(attachment) && emitted == beforeEmitted, "Native attachment integrity or GUI isolation failed.");
            var fileFirst = await coordinator.ReadPersonalActorStagingAsync(transportHandle, limit: 7,
                expectedRevision: firstStaging["revision"]!.GetValue<string>(), attachmentSha256: attachmentHash);
            var fileLast = await coordinator.ReadPersonalActorStagingAsync(transportHandle, offset: 7, limit: 7,
                expectedRevision: firstStaging["revision"]!.GetValue<string>(), attachmentSha256: attachmentHash);
            TestAssert.That(Convert.FromBase64String(fileFirst["data_base64"]!.GetValue<string>()).Concat(Convert.FromBase64String(fileLast["data_base64"]!.GetValue<string>())).SequenceEqual(attachment) &&
                fileFirst["attachment_sha256"]!.GetValue<string>() == attachmentHash && fileFirst["mime"]!.GetValue<string>() == "image/png" &&
                fileFirst["total_bytes"]!.GetValue<int>() == attachment.Length && fileLast["next_offset"] is null,
                "Native actor attachment readback lost verified bytes, type, size or bounded continuation.");
            await connection.HandlePlainAsync(chunkWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Count == 1, "Exact actor attachment replay failed native dedupe.");
            await coordinator.PumpPersonalActorAsync(connection);
            var resultWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single();
            var resultBody = PersonalSyncActorContract.Unwrap(resultWire["body"]!.AsObject());
            TestAssert.That(resultBody.Kind == "personal_sync.attachment_result" && resultBody.Body["state"]!.GetValue<string>() == "complete",
                "Native integrity verification did not enqueue the marked transfer result.");
            var replyBatch = batchBody.DeepClone().AsObject(); replyBatch["reply"] = true; replyBatch["batch_id"] = Guid.NewGuid().ToString("D");
            var privateStore = new PersonalSyncStore(store);
            privateStore.StageBatch(privatePeer, Message("personal_sync.batch", replyBatch), "wifi", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            privateStore.StageAttachment(privatePeer, transportHandle.ActorId, true, staged.RecordsHash,
                noteValue["attachments"]![0]!.AsObject(), "outgoing", "any", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 60000, [(0, attachment)]);
            var wants = new JsonObject { ["format"] = 2, ["run_id"] = transportHandle.ActorId, ["reply"] = true,
                ["records_hash"] = staged.RecordsHash, ["wants"] = new JsonArray(new JsonObject { ["sha256"] = attachmentHash,
                    ["ranges"] = new JsonArray(new JsonArray(0, 1)) }) };
            var beforeRequests = await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>());
            var wrongWant = wants.DeepClone().AsObject(); wrongWant["wants"]![0]!["sha256"] = new string('b', 64);
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_request", wrongWant), transportHandle.ActorId));
            wrongWant = wants.DeepClone().AsObject(); wrongWant["reply"] = false;
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_request", wrongWant), transportHandle.ActorId));
            wrongWant = wants.DeepClone().AsObject(); wrongWant["wants"]![0]!["ranges"]![0]![1] = 2;
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_request", wrongWant), transportHandle.ActorId));
            TestAssert.That(wire.Length == 0 && beforeRequests == await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["packets"]!.GetValue<int>()),
                "Undeclared, wrong-direction or out-of-file actor request reached raw persistence.");
            var wantWire = PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_request", wants), transportHandle.ActorId);
            await connection.HandlePlainAsync(wantWire); await connection.HandlePlainAsync(wantWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Count == 2, "Native reply attachment request replay lost its marked receipts.");
            await coordinator.PumpPersonalActorAsync(connection);
            var replyChunk = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                PersonalSyncActorContract.Unwrap(value["body"]!.AsObject()).Kind == "personal_sync.attachment_chunk");
            var replyChunkBody = PersonalSyncActorContract.Unwrap(replyChunk["body"]!.AsObject()).Body;
            TestAssert.That(replyChunkBody["reply"]!.GetValue<bool>() && Convert.FromBase64String(replyChunkBody["data"]!.GetValue<string>()).SequenceEqual(attachment),
                "Private reply attachment bytes or marked queue deduplication failed.");
            var complete = resultBody.Body.DeepClone().AsObject(); complete["reply"] = true;
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_result", complete), transportHandle.ActorId));
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind && emitted == beforeEmitted,
                "Native reply transfer result reached GUI adoption or lost its marked receipt.");
            var commitHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
            await coordinator.StartPersonalActorAsync(commitHandle); await SharedSyncTransportTests.DrainAsync(wire);
            var commitRequest = new JsonObject { ["format"] = 3, ["run_id"] = commitHandle.ActorId, ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.request", commitRequest), commitHandle.ActorId));
            var emptyRecords = new JsonArray();
            var commitBatch = new JsonObject { ["format"] = 3, ["run_id"] = commitHandle.ActorId, ["batch_id"] = Guid.NewGuid().ToString("D"),
                ["sequence"] = 0, ["last"] = true, ["reply"] = false, ["records"] = emptyRecords, ["records_hash"] = PersonalSyncContract.RecordsHash(emptyRecords) };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", commitBatch), commitHandle.ActorId));
            await SharedSyncTransportTests.DrainAsync(wire);
            var commitView = await coordinator.ReadPersonalActorStagingAsync(commitHandle);
            var unobserved = await coordinator.ExecuteMcpAsync(new JsonObject { ["action"] = "notes_actor_prepare_commit", ["actorId"] = commitHandle.ActorId,
                ["ownerToken"] = commitHandle.OwnerToken, ["expectedRevision"] = commitView["revision"]!.GetValue<string>(), ["bookSha256"] = new string('b', 64), ["saved"] = true }, default);
            TestAssert.That(!unobserved["ok"]!.GetValue<bool>(), "A client saved boolean substituted for an actual native writer observation.");
            NativeBookSaveState? nativeSaved = hostBook.RecordSaved("actual-host-profile", true, new string('a', 64));
            coordinator.NativeSavedBook = () => nativeSaved;
            var deletionGate = false;
            try { await coordinator.PreparePersonalActorCommitAsync(transportHandle, firstStaging["revision"]!.GetValue<string>(), new string('b', 64)); }
            catch (InvalidOperationException) { deletionGate = true; }
            TestAssert.That(deletionGate, "Unapplied native deletion intents bypassed typed review before commit.");
            var claim = await coordinator.PreparePersonalActorCommitAsync(commitHandle, commitView["revision"]!.GetValue<string>(), new string('b', 64));
            var claimToken = claim["claim_token"]!.GetValue<string>();
            var prematureReply = false;
            try { await coordinator.QueuePersonalActorReplyAsync(commitHandle, claimToken, new JsonArray(), new JsonArray()); }
            catch (InvalidOperationException) { prematureReply = true; }
            TestAssert.That(prematureReply, "An uncommitted actor queued its book reply.");
            foreach (var observation in new[] { nativeSaved, hostBook.RecordSaved("actual-host-profile", true, new string('c', 64)) })
            {
                nativeSaved = observation; var denied = false;
                try { await coordinator.CommitPersonalActorAsync(commitHandle, claimToken); } catch (InvalidOperationException) { denied = true; }
                TestAssert.That(denied, "Unchanged save sequence or wrong actual-book hash authorized core commit.");
            }
            nativeSaved = hostBook.RecordSaved("actual-host-profile", true, new string('b', 64));
            var foreignClaim = false;
            try { await coordinator.CommitPersonalActorAsync(commitHandle, new string('f', 64)); } catch (InvalidOperationException) { foreignClaim = true; }
            TestAssert.That(foreignClaim, "A foreign native review claim authorized core commit.");
            var committed = await coordinator.CommitPersonalActorAsync(commitHandle, claimToken);
            TestAssert.That(committed["book_persisted"]!.GetValue<bool>() && committed["core_committed"]!.GetValue<bool>() && !committed["phone_persisted"]!.GetValue<bool>() &&
                JsonNode.DeepEquals(committed, await coordinator.CommitPersonalActorAsync(commitHandle, claimToken)) &&
                !privateStore.ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(value => value.PeerId == PersonalSyncActorContract.StoragePeer(commitHandle.ActorId)) && wire.Length == 0,
                "Actual native save proof failed private core commit/idempotency or emitted a premature book receipt.");
            var nativeReply = batchBody.DeepClone().AsObject(); nativeReply["run_id"] = commitHandle.ActorId; nativeReply["reply"] = true;
            nativeReply["batch_id"] = Guid.NewGuid().ToString("D");
            var nativeReplies = new JsonArray(nativeReply);
            var nativeSources = new JsonArray(new JsonObject { ["sha256"] = attachmentHash, ["data"] = "data:image/png;base64," + Convert.ToBase64String(attachment) });
            var queuedReply = await coordinator.QueuePersonalActorReplyAsync(commitHandle, claimToken, nativeReplies, nativeSources);
            TestAssert.That(queuedReply["reply_queued"]!.GetValue<bool>() && !queuedReply["delivery_confirmed"]!.GetValue<bool>() && !queuedReply["phone_persisted"]!.GetValue<bool>() &&
                JsonNode.DeepEquals(queuedReply, await coordinator.QueuePersonalActorReplyAsync(commitHandle, claimToken, nativeReplies, nativeSources)),
                "Native persisted reply was not queued idempotently or asserted remote persistence.");
            var changedReply = nativeReplies.DeepClone().AsArray(); changedReply[0]!["batch_id"] = Guid.NewGuid().ToString("D");
            var changedDenied = false;
            try { await coordinator.QueuePersonalActorReplyAsync(commitHandle, claimToken, changedReply, nativeSources); } catch (InvalidOperationException) { changedDenied = true; }
            TestAssert.That(changedDenied, "A changed reply replaced an already queued actor output.");
            await coordinator.PumpPersonalActorAsync(connection);
            var savedReplyWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                value["body"]!["run_id"]!.GetValue<string>() == commitHandle.ActorId);
            TestAssert.That(PersonalSyncActorContract.Unwrap(savedReplyWire["body"]!.AsObject()).Kind == "personal_sync.batch" &&
                privateStore.ReadVerifiedAttachment(PersonalSyncActorContract.StoragePeer(commitHandle.ActorId), commitHandle.ActorId, true, staged.RecordsHash,
                    attachmentHash, "outgoing", "wifi", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).SequenceEqual(attachment),
                "Native actor reply wire or existing private outgoing file store changed its persisted source.");
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(commitHandle.ActorId, savedReplyWire["message_id"]!.GetValue<string>())));
            await coordinator.PumpPersonalActorAsync(connection); await SharedSyncTransportTests.DrainAsync(wire);
            var beforeRemoteSave = await coordinator.PersonalActorStatusAsync(commitHandle);
            TestAssert.That(!beforeRemoteSave["phone_persisted"]!.GetValue<bool>() && !beforeRemoteSave["completion_report_queued"]!.GetValue<bool>(),
                "Reply batch ACK bypassed pending native attachment completion.");
            var replyFileResult = complete.DeepClone().AsObject(); replyFileResult["run_id"] = commitHandle.ActorId;
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.attachment_result", replyFileResult), commitHandle.ActorId));
            await SharedSyncTransportTests.DrainAsync(wire); await coordinator.PumpPersonalActorAsync(connection);
            var reportWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                value["body"]!["run_id"]!.GetValue<string>() == commitHandle.ActorId);
            TestAssert.That(PersonalSyncActorContract.Unwrap(reportWire["body"]!.AsObject()).Kind == "personal_sync.report" &&
                !(await coordinator.PersonalActorStatusAsync(commitHandle))["phone_persisted"]!.GetValue<bool>(), "File result claimed phone book persistence before report SaveACK.");
            await connection.HandlePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = reportWire["message_id"]!.DeepClone(), ["status"] = "accepted", ["error"] = "none" });
            TestAssert.That(!(await coordinator.PersonalActorStatusAsync(commitHandle))["phone_persisted"]!.GetValue<bool>(), "Ordinary ACK forged remote actor book persistence.");
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(commitHandle.ActorId, reportWire["message_id"]!.GetValue<string>())));
            TestAssert.That((await coordinator.PersonalActorStatusAsync(commitHandle))["phone_persisted"]!.GetValue<bool>(), "Exact marked completion report receipt did not confirm remote book commit.");
            await coordinator.CancelPersonalActorAsync(commitHandle); await SharedSyncTransportTests.DrainAsync(wire);
            // Native typed review/save-report/terminal controller with a native
            // writer-state fixture, not the GUI book writer or public activation.
            foreach (var terminalChoice in new[] { "restore", "delete" })
            {
            var reviewHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
            await coordinator.StartPersonalActorAsync(reviewHandle); await SharedSyncTransportTests.DrainAsync(wire);
            var reviewRequest = commitRequest.DeepClone().AsObject(); reviewRequest["run_id"] = reviewHandle.ActorId;
            var reviewBatch = commitBatch.DeepClone().AsObject(); reviewBatch["run_id"] = reviewHandle.ActorId; reviewBatch["batch_id"] = Guid.NewGuid().ToString("D");
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.request", reviewRequest), reviewHandle.ActorId));
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", reviewBatch), reviewHandle.ActorId));
            await SharedSyncTransportTests.DrainAsync(wire);
            var reviewProposalId = Guid.NewGuid().ToString("D");
            var reviewClock = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 2 });
            var reviewProposal = new JsonObject { ["format"] = 1, ["run_id"] = reviewHandle.ActorId, ["proposal_batch_id"] = Guid.NewGuid().ToString("D"),
                ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(new JsonObject { ["proposal_id"] = reviewProposalId,
                    ["kind"] = "note", ["id"] = "note-one", ["parent_id"] = "", ["clock"] = reviewClock.DeepClone(),
                    ["prior_hash"] = new string('a', 64), ["deleted_ms"] = 2, ["label"] = "Synthetic native review" }) };
            await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_proposals", reviewProposal), reviewHandle.ActorId));
            TestAssert.That(wire.Length == 0, "Intent review caused a premature deletion receipt.");
            var reviewView = await coordinator.ReadPersonalActorStagingAsync(reviewHandle);
            var reviewPayload = JsonNode.Parse(Convert.FromBase64String(reviewView["data_base64"]!.GetValue<string>()))!.AsObject();
            var reviewIntent = reviewPayload["intents"]!.AsArray().OfType<JsonObject>().Single();
            var typedPlan = new JsonObject { ["choices"] = new JsonArray(new JsonObject { ["proposal_id"] = reviewProposalId,
                ["decision"] = terminalChoice, ["expected_clock"] = reviewClock.DeepClone(), ["allow_conflict"] = false }),
                ["intents"] = new JsonArray(new JsonObject { ["kind"] = reviewIntent["kind"]!.DeepClone(),
                    ["message_id"] = reviewIntent["pending_message_id"]!.DeepClone(), ["commit_token"] = reviewIntent["commit_token"]!.DeepClone() }) };
            var badPlan = typedPlan.DeepClone().AsObject(); badPlan["intents"]![0]!["commit_token"] = "foreign";
            var deniedReview = false;
            try { await coordinator.PreparePersonalActorCommitAsync(reviewHandle, reviewView["revision"]!.GetValue<string>(), new string('d', 64), deletionPlan: badPlan); }
            catch (InvalidDataException) { deniedReview = true; }
            TestAssert.That(deniedReview, "Foreign native intent token authorized a commit plan.");
            var reviewedClaim = await coordinator.PreparePersonalActorCommitAsync(reviewHandle, reviewView["revision"]!.GetValue<string>(), new string('d', 64), deletionPlan: typedPlan);
            badPlan = typedPlan.DeepClone().AsObject(); badPlan["choices"]![0]!["decision"] = terminalChoice == "restore" ? "delete" : "restore"; deniedReview = false;
            try { await coordinator.PreparePersonalActorCommitAsync(reviewHandle, reviewView["revision"]!.GetValue<string>(), new string('d', 64), deletionPlan: badPlan); }
            catch (InvalidOperationException) { deniedReview = true; }
            TestAssert.That(deniedReview, "Bound native review silently changed its decision.");
            deniedReview = false;
            try { await coordinator.CommitPersonalActorAsync(reviewHandle, reviewedClaim["claim_token"]!.GetValue<string>()); }
            catch (InvalidOperationException) { deniedReview = true; }
            TestAssert.That(deniedReview, "Typed review substituted for an actual fresh native save.");
            nativeSaved = hostBook.RecordSaved("actual-host-profile", true, new string('d', 64));
            var reviewReceipt = await coordinator.CommitPersonalActorAsync(reviewHandle, reviewedClaim["claim_token"]!.GetValue<string>());
            var reviewedPeer = PersonalSyncActorContract.StoragePeer(reviewHandle.ActorId);
            TestAssert.That(reviewReceipt["core_committed"]!.GetValue<bool>() && reviewReceipt["book_persisted"]!.GetValue<bool>() && !reviewReceipt["phone_persisted"]!.GetValue<bool>() &&
                JsonNode.DeepEquals(reviewReceipt, await coordinator.CommitPersonalActorAsync(reviewHandle, reviewedClaim["claim_token"]!.GetValue<string>())) &&
                !privateStore.DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(value => value.PeerId == reviewedPeer) &&
                !privateStore.ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(value => value.PeerId == reviewedPeer) && wire.Length == 0,
                "Reviewed native batch/intent commit was partial or claimed remote persistence.");
            var replyReviewBatch = reviewBatch.DeepClone().AsObject(); replyReviewBatch["reply"] = true; replyReviewBatch["batch_id"] = Guid.NewGuid().ToString("D");
            await coordinator.QueuePersonalActorReplyAsync(reviewHandle, reviewedClaim["claim_token"]!.GetValue<string>(), new JsonArray(replyReviewBatch), new JsonArray());
            deniedReview = false;
            try { await coordinator.BeginPersonalActorCompletionAsync(reviewHandle, reviewedClaim["claim_token"]!.GetValue<string>()); }
            catch (InvalidOperationException) { deniedReview = true; }
            TestAssert.That(deniedReview, "A native saved claim skipped the phone DataSaveACK prerequisite.");
            await coordinator.PumpPersonalActorAsync(connection);
            var reviewReplyWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                value["body"]!["run_id"]!.GetValue<string>() == reviewHandle.ActorId);
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(reviewHandle.ActorId, reviewReplyWire["message_id"]!.GetValue<string>())));
            await coordinator.PumpPersonalActorAsync(connection);
            var reviewReportWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                value["body"]!["run_id"]!.GetValue<string>() == reviewHandle.ActorId);
            TestAssert.That(PersonalSyncActorContract.Unwrap(reviewReportWire["body"]!.AsObject()).Kind == "personal_sync.report", "Terminal start lacked the actual queued data completion report.");
            await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(reviewHandle.ActorId, reviewReportWire["message_id"]!.GetValue<string>())));
            var dataOnly = await coordinator.PersonalActorStatusAsync(reviewHandle);
            TestAssert.That(dataOnly["phone_data_persisted"]!.GetValue<bool>() && !dataOnly["phone_persisted"]!.GetValue<bool>(), "Data SaveACK incorrectly completed reviewed deletions.");
            await coordinator.PumpPersonalActorAsync(connection); // Actual controller starts the terminal owner.
            var decisionWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                value["body"]!["run_id"]!.GetValue<string>() == reviewHandle.ActorId);
            TestAssert.That(PersonalSyncActorContract.Unwrap(decisionWire["body"]!.AsObject()).Kind == "personal_sync.deletion_decision" &&
                PersonalSyncActorContract.Unwrap(decisionWire["body"]!.AsObject()).Body["decisions"]![0]!["decision"]!.GetValue<string>() == terminalChoice,
                "Native terminal sender changed its exact reviewed choice.");
            deniedReview = false;
            try { await coordinator.ReadPersonalActorStagingAsync(reviewHandle); } catch (InvalidOperationException) { deniedReview = true; }
            TestAssert.That(deniedReview, "Terminal owner reopened native content staging.");
            var finalAck = Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(reviewHandle.ActorId, decisionWire["message_id"]!.GetValue<string>()));
            var terminalScope = manifest;
            if (terminalChoice == "delete")
            {
                await connection.HandlePlainAsync(finalAck.DeepClone().AsObject());
                TestAssert.That(!(await coordinator.PersonalActorStatusAsync(reviewHandle))["phone_persisted"]!.GetValue<bool>(), "Positive deletion ACK before fresh resulting membership counted as saved.");
                terminalScope = PhoneContentScope.Advance(manifest, [], ["task-one"]);
                foreach (var part in PhoneContentScope.Chunks(terminalScope)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                await SharedSyncTransportTests.DrainAsync(wire);
            }
            await connection.HandlePlainAsync(finalAck);
            var terminalStatus = await coordinator.PersonalActorStatusAsync(reviewHandle);
            TestAssert.That(terminalStatus["phase"]!.GetValue<string>() == "completed" && terminalStatus["phone_persisted"]!.GetValue<bool>() &&
                terminalStatus["deletion_completion"]!["saved"]!.GetValue<int>() == 1, "Native terminal controller did not finish exact persisted ACK: " + terminalChoice);
            await connection.HandlePlainAsync(finalAck.DeepClone().AsObject());
            TestAssert.That((await coordinator.PersonalActorStatusAsync(reviewHandle))["phase"]!.GetValue<string>() == "completed", "Exact terminal ACK replay changed completed state.");
            if (terminalChoice == "delete")
            {
                manifest = PhoneContentScope.Advance(terminalScope, ["note-one"], ["task-one"]);
                foreach (var part in PhoneContentScope.Chunks(manifest)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                await SharedSyncTransportTests.DrainAsync(wire);
            }
            await coordinator.CancelPersonalActorAsync(reviewHandle); await SharedSyncTransportTests.DrainAsync(wire);
            }
            // Actual native review/core/data-report/terminal flow. The outgoing
            // full target proof is seeded through the protected store here;
            // this does not stand in for the unfinished desktop producer/GUI.
            foreach (var incomingScenario in new[] { "incoming", "mixed", "outside", "overlap" })
            {
                var mixedIncoming = incomingScenario is "mixed" or "overlap";
                var incomingHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
                await coordinator.StartPersonalActorAsync(incomingHandle); await SharedSyncTransportTests.DrainAsync(wire);
                var incomingPrivate = PersonalSyncActorContract.StoragePeer(incomingHandle.ActorId);
                var incomingRequest = commitRequest.DeepClone().AsObject(); incomingRequest["run_id"] = incomingHandle.ActorId;
                var incomingBatch = commitBatch.DeepClone().AsObject(); incomingBatch["run_id"] = incomingHandle.ActorId; incomingBatch["batch_id"] = Guid.NewGuid().ToString("D");
                await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.request", incomingRequest), incomingHandle.ActorId));
                await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.batch", incomingBatch), incomingHandle.ActorId));
                await SharedSyncTransportTests.DrainAsync(wire);
                var outgoingProposalId = Guid.NewGuid().ToString("D"); var localProposalId = Guid.NewGuid().ToString("D");
                var incomingClock = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 2 });
                var incomingDecision = new JsonObject { ["format"] = 1, ["run_id"] = incomingHandle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = outgoingProposalId, ["decision"] = "restore", ["expected_clock"] = incomingClock.DeepClone() }) };
                var semanticDecision = Message("personal_sync.deletion_decision", incomingDecision);
                if (mixedIncoming)
                {
                    TestAssert.Throws<InvalidDataException>(() => PhoneContentScope.Wrap("personal_sync.deletion_decision", incomingDecision, manifest),
                        "Terminal decisions unexpectedly acquired a scoped-data wire format.");
                }
                var incomingWire = PersonalSyncActorContract.WireMessage(semanticDecision, incomingHandle.ActorId);
                await connection.HandlePlainAsync(incomingWire.DeepClone().AsObject());
                TestAssert.That(wire.Length == 0 && !privateStore.DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(value => value.PeerId == incomingPrivate),
                    "Unknown outgoing proposal acquired an incoming decision intent.");
                var nativeOutgoing = new JsonObject { ["format"] = 1, ["run_id"] = incomingHandle.ActorId, ["proposal_batch_id"] = Guid.NewGuid().ToString("D"),
                    ["sequence"] = 0, ["last"] = true, ["proposals"] = new JsonArray(new JsonObject { ["proposal_id"] = outgoingProposalId,
                        ["kind"] = "attachment", ["id"] = "native-outgoing-file", ["parent_id"] = "note-one", ["clock"] = incomingClock.DeepClone(),
                        ["prior_hash"] = new string('a', 64), ["deleted_ms"] = 2, ["label"] = "Synthetic native outgoing target" }) };
                if (incomingScenario is "outside" or "overlap")
                {
                    nativeOutgoing["proposals"]![0]!["kind"] = incomingScenario == "outside" ? "note" : "task";
                    nativeOutgoing["proposals"]![0]!["id"] = incomingScenario == "outside" ? "unselected-note" : "task-one";
                    nativeOutgoing["proposals"]![0]!["parent_id"] = "";
                }
                store.RememberPersonalProposalKinds(incomingPrivate, nativeOutgoing, true);
                await connection.HandlePlainAsync(incomingWire.DeepClone().AsObject());
                if (mixedIncoming)
                {
                    var localProposal = nativeOutgoing.DeepClone().AsObject();
                    localProposal["proposal_batch_id"] = Guid.NewGuid().ToString("D");
                    localProposal["proposals"]![0]!["proposal_id"] = localProposalId;
                    localProposal["proposals"]![0]!["kind"] = "task"; localProposal["proposals"]![0]!["id"] = "task-one"; localProposal["proposals"]![0]!["parent_id"] = "";
                    await connection.HandlePlainAsync(PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_proposals", localProposal), incomingHandle.ActorId));
                }
                TestAssert.That(wire.Length == 0, "Incoming decisions received success before native commit.");
                var incomingView = await coordinator.ReadPersonalActorStagingAsync(incomingHandle);
                var incomingPayload = JsonNode.Parse(Convert.FromBase64String(incomingView["data_base64"]!.GetValue<string>()))!.AsObject();
                var incomingPlan = new JsonObject { ["choices"] = mixedIncoming ? new JsonArray(new JsonObject {
                    ["proposal_id"] = localProposalId, ["decision"] = "restore", ["expected_clock"] = incomingClock.DeepClone(), ["allow_conflict"] = false }) : new JsonArray(),
                    ["intents"] = new JsonArray(incomingPayload["intents"]!.AsArray().OfType<JsonObject>().Select(value => (JsonNode)new JsonObject {
                        ["kind"] = value["kind"]!.DeepClone(), ["message_id"] = value["pending_message_id"]!.DeepClone(), ["commit_token"] = value["commit_token"]!.DeepClone() }).ToArray()) };
                if (incomingScenario is "outside" or "overlap")
                {
                    var beforeDeniedPlan = nativeSaved; var deniedPlan = false;
                    try { await coordinator.PreparePersonalActorCommitAsync(incomingHandle, incomingView["revision"]!.GetValue<string>(), new string('e', 64), deletionPlan: incomingPlan); }
                    catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { deniedPlan = true; }
                    TestAssert.That(deniedPlan && nativeSaved == beforeDeniedPlan && wire.Length == 0 &&
                        privateStore.DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Count(value => value.PeerId == incomingPrivate) == (mixedIncoming ? 2 : 1),
                        "Outside/overlapping target group reached a save claim or consumed native intents.");
                    await coordinator.CancelPersonalActorAsync(incomingHandle); await SharedSyncTransportTests.DrainAsync(wire);
                    continue;
                }
                var incomingClaim = await coordinator.PreparePersonalActorCommitAsync(incomingHandle, incomingView["revision"]!.GetValue<string>(), new string('e', 64), deletionPlan: incomingPlan);
                var incomingToken = incomingClaim["claim_token"]!.GetValue<string>();
                nativeSaved = hostBook.RecordSaved("actual-host-profile", true, new string('e', 64));
                await coordinator.CommitPersonalActorAsync(incomingHandle, incomingToken);
                TestAssert.That(!privateStore.DecisionIntents(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()).Any(value => value.PeerId == incomingPrivate),
                    "Native incoming/mixed intent group did not commit atomically with the data batch.");
                var incomingReply = incomingBatch.DeepClone().AsObject(); incomingReply["reply"] = true; incomingReply["batch_id"] = Guid.NewGuid().ToString("D");
                await coordinator.QueuePersonalActorReplyAsync(incomingHandle, incomingToken, new JsonArray(incomingReply), new JsonArray());
                await coordinator.PumpPersonalActorAsync(connection);
                var incomingReplyWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                    value["body"]!["run_id"]!.GetValue<string>() == incomingHandle.ActorId);
                await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(incomingHandle.ActorId, incomingReplyWire["message_id"]!.GetValue<string>())));
                await coordinator.PumpPersonalActorAsync(connection);
                var incomingReport = (await SharedSyncTransportTests.DrainAsync(wire)).Single(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind &&
                    value["body"]!["run_id"]!.GetValue<string>() == incomingHandle.ActorId);
                TestAssert.That(PersonalSyncActorContract.Unwrap(incomingReport["body"]!.AsObject()).Kind == "personal_sync.report", "Incoming completion lacked the data report.");
                await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(incomingHandle.ActorId, incomingReport["message_id"]!.GetValue<string>())));
                TestAssert.That(!(await coordinator.PersonalActorStatusAsync(incomingHandle))["phone_persisted"]!.GetValue<bool>(), "Data report ACK skipped incoming terminal decisions.");
                var terminalWitness = nativeSaved;
                var beganIncoming = await coordinator.ExecuteMcpActorAsync(new JsonObject { ["action"] = "notes_actor_begin_completion",
                    ["actorId"] = incomingHandle.ActorId, ["ownerToken"] = incomingHandle.OwnerToken, ["claimToken"] = incomingToken }, default);
                TestAssert.That(beganIncoming["ok"]!.GetValue<bool>() && beganIncoming["actor"]!["phase"]!.GetValue<string>() == "completion",
                    "Private GUI bridge could not begin native incoming/mixed completion.");
                var advancedIncoming = await coordinator.ExecuteMcpActorAsync(new JsonObject { ["action"] = "notes_actor_advance_completion",
                    ["actorId"] = incomingHandle.ActorId, ["ownerToken"] = incomingHandle.OwnerToken }, default);
                TestAssert.That(advancedIncoming["ok"]!.GetValue<bool>(), "Private GUI advance did not use native completion dispatch.");
                var terminalWires = (await SharedSyncTransportTests.DrainAsync(wire)).Where(value => value["body"]?["run_id"]?.GetValue<string>() == incomingHandle.ActorId).ToArray();
                TestAssert.That(terminalWires.Count(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind &&
                    value["body"]!["message_id"]!.GetValue<string>() == incomingWire["message_id"]!.GetValue<string>()) == 1,
                    "Native incoming decision did not receive its actual sent ACK.");
                var terminalDecisions = terminalWires.Where(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind).ToArray();
                TestAssert.That(terminalDecisions.Length == (mixedIncoming ? 1 : 0), "Incoming reference frame was resent as data or local decision was lost.");
                if (mixedIncoming)
                {
                    TestAssert.That(!(await coordinator.PersonalActorStatusAsync(incomingHandle))["phone_persisted"]!.GetValue<bool>(), "Own ACK substituted for mixed peer receipt.");
                    await connection.HandlePlainAsync(Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(incomingHandle.ActorId, terminalDecisions.Single()["message_id"]!.GetValue<string>())));
                }
                var incomingStatus = await coordinator.PersonalActorStatusAsync(incomingHandle);
                TestAssert.That(incomingStatus["phase"]!.GetValue<string>() == "completed" && incomingStatus["phone_persisted"]!.GetValue<bool>() &&
                    incomingStatus["deletion_completion"]!["saved"]!.GetValue<int>() == (mixedIncoming ? 2 : 1) && nativeSaved == terminalWitness,
                    "Incoming/mixed native controller lacked both exact receipt directions or repeated the writer observation.");
                await coordinator.CancelPersonalActorAsync(incomingHandle); await SharedSyncTransportTests.DrainAsync(wire);
            }
            hostBook.SetReady(false);
            await coordinator.PumpPersonalActorAsync(connection);
            TestAssert.That(wire.Length == 0 && await coordinator.WithPersonalActorStoreAsync(registry => registry.Status(transportHandle)["phase"]!.GetValue<string>()) == "cancelled",
                "Source-loss reaping dispatched data or failed to retain terminal owner status.");
            await coordinator.CancelPersonalActorAsync(transportHandle);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.CancelKind,
                "Native actor cancellation lost its explicit wire marker.");
            TestAssert.That(store.OutboxMessage(peer.Id, resultWire["message_id"]!.GetValue<string>()) is null,
                "Cancellation left its own outbound actor result pending.");
            hostBook.SetReady(true);
            var cancelledRead = false;
            try { await coordinator.ReadPersonalActorStagingAsync(transportHandle); } catch (InvalidOperationException) { cancelledRead = true; }
            TestAssert.That(cancelledRead, "Retired native actor retained private staging read authority.");
            TestAssert.That(wire.GuardChecks > 0, "Encrypted actor writes bypassed the source-guard observation.");
            wire.AssertActorWrite = null;
            TestAssert.That(Read(() => new string('b', 64)) != revision && Read(() => null) is null && Read(() => "client-digest") is null,
                "Native book ownership was ignored or an invalid book source was accepted.");
            var checks = 0;
            TestAssert.That(Read(() => ++checks == 1 ? new string('a', 64) : new string('b', 64)) is null, "Book-owner race produced a source revision.");
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, "AAAA-BBBB-CCCC-DDDD", () => new string('a', 64)) is null, "Another peer key was accepted.");
            store.SetLocalGrant("personal_tasks_sync", false);
            TestAssert.That(Read() is null, "Grant revocation reused an actor source.");
            TestAssert.That(CompletionAuthority() is null, "Grant revocation retained terminal receipt authority.");
            store.SetLocalGrant("personal_tasks_sync", true); store.NextOwnRevision("grants");
            var granted = Read();
            TestAssert.That(granted is { Length: 64 } && granted != revision, "Native grant revision was not source-bound.");
            var completionAuthority = CompletionAuthority();
            TestAssert.That(completionAuthority is { Length: 64 } && completionAuthority != granted, "Receipt authority aliased a data source.");
            var changed = PhoneContentScope.Advance(manifest, ["note-two"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var current = Read();
            TestAssert.That(current is not null && current != granted, "Scope replacement retained source identity.");
            TestAssert.That(CompletionAuthority() == completionAuthority, "A completed scope generation changed unrelated native receipt authority.");
            beforeWire = wire.Length; beforeEmitted = emitted;
            TestAssert.That(Read() == current && wire.Length == beforeWire && emitted == beforeEmitted, "Source inspection emitted transport or GUI work.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = grants.DeepClone() }));
            var remoteRevision = Read();
            TestAssert.That(remoteRevision is not null && remoteRevision != current, "Fresh remote grant revision was not source-bound.");
            TestAssert.That(CompletionAuthority() != completionAuthority, "A new grant revision inherited terminal receipt authority.");
            store.UpdatePeerProtocol(peer.Id, 0, null, 3, grants);
            TestAssert.That(Read() is null, "Cached fresh flags authorized a control revision unseen on this connection.");
            TestAssert.That(CompletionAuthority() is null, "Unseen control revision authorized terminal correlation.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 4, ["grants"] = grants.DeepClone() }));
            current = Read();
            TestAssert.That(current is not null, "Actual current grant control did not refresh source authority.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = false }));
            TestAssert.That(Read() == current, "An obsolete ownership flag changed the authenticated paired source.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            var renewed = store.SharedSettings(peer.Id, peer.PublicKey) ?? store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), renewed, peer.Id, identity.Id)));
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var reowned = Read();
            TestAssert.That(reowned is not null, "Paired source failed after a legacy ownership control.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            TestAssert.That(Read() == reowned, "Unchanged ownership replay rotated actor authority.");
            // A real SendPlainAsync I/O fault disposes its stream. Use an
            // independent authenticated connection and never pretend it can
            // recover on that disposed channel or rebind its old actor owner.
            using (var failedWire = new ActorWireStream())
            using (var failedConnection = new TelefonConnection(peer, failedWire, new byte[16], new byte[72], store, Receive, CancellationToken.None, "wifi")
                { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() })
            {
                async Task Prime(TelefonConnection fresh, ActorWireStream output)
                {
                    online[peer.Id] = fresh;
                    var previousPeer = store.LoadPeers().Single(value => value.Id == peer.Id);
                    var freshCapabilities = capabilities.DeepClone().AsObject(); freshCapabilities["revision"] = previousPeer.CapabilityRevision + 1;
                    // New identities with an already consumed revision are not
                    // fresh controls. Advance revisions for these new frames.
                    await fresh.HandlePlainAsync(Message("capabilities.update", freshCapabilities));
                    await fresh.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = previousPeer.GrantRevision + 1, ["grants"] = grants.DeepClone() }));
                    await fresh.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
                    await fresh.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), renewed, peer.Id, identity.Id)));
                    await fresh.SendSharedSettingsAsync();
                    foreach (var part in PhoneContentScope.Chunks(changed)) await fresh.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                    await SharedSyncTransportTests.DrainAsync(output);
                    var currentPeer = store.LoadPeers().Single(value => value.Id == peer.Id);
                    TestAssert.That(fresh.SharedSettingsReady, "Separate fault connection did not finish fresh shared controls.");
                    TestAssert.That(fresh.ActorSourceSnapshot() is not null,
                        $"Separate fault connection lacked source evidence (caps={currentPeer.CapabilityRevision},grants={currentPeer.GrantRevision}).");
                }
                await Prime(failedConnection, failedWire);
                hostBook.RecordSaved("actual-host-profile", true, new string('c', 64));
                coordinator.NativeSavedBook = () => hostBook.SaveState("actual-host-profile", true);
                var failedHandle = await coordinator.CreatePersonalActorAsync(peer.Id, fingerprint);
                await coordinator.StartPersonalActorAsync(failedHandle); await SharedSyncTransportTests.DrainAsync(failedWire);
                var failureClock = new JsonArray(new JsonObject { ["actor_id"] = peer.Id, ["counter"] = 3 });
                var failureProposal = Guid.NewGuid().ToString("D");
                var reference = PersonalSyncActorContract.WireMessage(Message("personal_sync.deletion_decision", new JsonObject {
                    ["format"] = 1, ["run_id"] = failedHandle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(new JsonObject { ["proposal_id"] = failureProposal, ["decision"] = "restore", ["expected_clock"] = failureClock.DeepClone() }) }), failedHandle.ActorId);
                var failureAck = Message(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(failedHandle.ActorId, reference["message_id"]!.GetValue<string>()));
                var failureGuard = await coordinator.WithPersonalActorStoreAsync(registry => {
                    var guard = new PersonalActorDecisionCompletion(failedHandle.ActorId, new JsonArray(new JsonObject {
                        ["proposal_id"] = failureProposal, ["kind"] = "task", ["id"] = "task-one", ["parent_id"] = "",
                        ["prior_hash"] = new string('a', 64), ["clock"] = failureClock.DeepClone() }), [reference],
                        () => coordinator.CurrentActorCompletionAuthority(peer.Id, fingerprint),
                        () => failedConnection.CurrentContentScope(PhoneContentScope.Reference(changed)), () => hostBook.SaveState("actual-host-profile", true),
                        () => registry.ReadCompletionControls(failedHandle), nativeSentAcknowledgments: [failureAck]);
                    registry.BeginCompletion(failedHandle, guard.Validator); return guard;
                });
                var failureAdmissions = (System.Collections.IDictionary)typeof(TelefonCoordinator).GetField("actorAdmissions", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!;
                var failureAdmission = failureAdmissions[failedHandle.ActorId]!;
                void SetFailure(string name, object value) => failureAdmission.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(failureAdmission, value);
                SetFailure("Completion", failureGuard); SetFailure("SaveReceipt", hostBook.SaveState("actual-host-profile", true)!); SetFailure("PhoneDataPersisted", true);
                var failureAcks = (Dictionary<string, JsonObject>)failureAdmission.GetType().GetProperty("NativeAcknowledgments", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(failureAdmission)!;
                failureAcks.Add(failureAck["message_id"]!.GetValue<string>(), failureAck);
                var failureWitness = hostBook.SaveState("actual-host-profile", true); var failureEvents = emitted;
                failedWire.AssertActorWrite = () => TestAssert.That(store.NotePolicyGate.CurrentCount == 1 && !Monitor.IsEntered(
                    typeof(TelefonCoordinator).GetField("gate", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(coordinator)!), "Faulting ACK send held native guards.");
                failedWire.FailNextWrite = true;
                var ioFailed = false;
                try { await coordinator.PumpPersonalActorAsync(failedConnection); } catch (IOException) { ioFailed = true; }
                TestAssert.That(ioFailed && failedWire.WasDisposed && failureAcks.Count == 1 && failureGuard.Summary()["saved"]!.GetValue<int>() == 0 &&
                    hostBook.SaveState("actual-host-profile", true) == failureWitness && emitted == failureEvents, "Failed actual ACK write counted success, mutated data, or retained a usable stream.");
                await coordinator.WithPersonalActorStoreAsync(registry => {
                    TestAssert.That(registry.ReadCompletionControls(failedHandle).Count == 0 && registry.Status(failedHandle)["phase"]!.GetValue<string>() == "completion", "I/O failure persisted a successful own ACK."); return true;
                });
                using var replacementWire = new ActorWireStream();
                using var replacement = new TelefonConnection(peer, replacementWire, new byte[16], new byte[72], store, Receive, CancellationToken.None, "wifi")
                    { SharedLocalCapabilities = () => capabilities["items"]!.DeepClone().AsObject() };
                await Prime(replacement, replacementWire);
                SetFailure("NativeAckNextAttempt", 0L);
                await coordinator.PumpPersonalActorAsync(replacement);
                TestAssert.That(replacementWire.Length == 0 && failureAcks.Count == 1 && failureGuard.Summary()["saved"]!.GetValue<int>() == 0,
                    "Replacement channel inherited the old native ACK claim.");
                await coordinator.WithPersonalActorStoreAsync(registry => {
                    TestAssert.Throws<InvalidOperationException>(() => registry.ReadCompletionControls(failedHandle), "Replacement connection retained the old completion source."); return true;
                });
            }
            online.Clear(); TestAssert.That(Read() is null && CompletionAuthority() is null, "A disconnected native source stayed authorized.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
