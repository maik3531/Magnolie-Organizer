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
        public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellation = default)
        { if (AssertActorWrite is not null) { AssertActorWrite(); GuardChecks++; } return base.WriteAsync(buffer, cancellation); }
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
            var settings = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            var capabilities = TelefonProtocolContract.DesktopCapabilities();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" }) capabilities["items"]![name]!["versions"]!.AsArray().Add(12);
            var grants = TelefonProtocolContract.DesktopGrants(); grants["personal_notes_sync"] = true; grants["personal_tasks_sync"] = true;
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
            TestAssert.That(Read() is null, "Missing fresh native controls admitted an actor source.");
            await connection.HandlePlainAsync(Message("capabilities.update", capabilities));
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = grants }));
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), settings, peer.Id, identity.Id)));
            TestAssert.That(Read() is null, "A persisted preference agreement replaced fresh membership.");
            var manifest = PhoneContentScope.Create(["note-one"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(manifest)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var revision = Read(); var beforeWire = wire.Length; var beforeEmitted = emitted;
            TestAssert.That(revision is { Length: 64 } && Read() == revision, "Actual native source was unavailable or unstable.");
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
            await connection.HandlePlainAsync(batchWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind && emitted == beforeEmitted,
                "Private actor batch reached ordinary GUI handling or lacked its marked receipt.");
            var staged = new PersonalSyncStore(store).ReadyBatches(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())
                .Single(value => value.PeerId == PersonalSyncActorContract.StoragePeer(transportHandle.ActorId));
            TestAssert.That(JsonNode.DeepEquals(staged.Records.Single(), record), "Existing private stager changed actor records.");
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
            await connection.HandlePlainAsync(chunkWire);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Count == 1, "Exact actor attachment replay failed native dedupe.");
            await coordinator.PumpPersonalActorAsync(connection);
            var resultWire = (await SharedSyncTransportTests.DrainAsync(wire)).Single();
            var resultBody = PersonalSyncActorContract.Unwrap(resultWire["body"]!.AsObject());
            TestAssert.That(resultBody.Kind == "personal_sync.attachment_result" && resultBody.Body["state"]!.GetValue<string>() == "complete",
                "Native integrity verification did not enqueue the marked transfer result.");
            await coordinator.CancelPersonalActorAsync(transportHandle);
            TestAssert.That((await SharedSyncTransportTests.DrainAsync(wire)).Single()["kind"]!.GetValue<string>() == PersonalSyncActorContract.CancelKind,
                "Native actor cancellation lost its explicit wire marker.");
            TestAssert.That(store.OutboxMessage(peer.Id, resultWire["message_id"]!.GetValue<string>()) is null,
                "Cancellation left its own outbound actor result pending.");
            TestAssert.That(wire.GuardChecks > 0, "Encrypted actor writes bypassed the source-guard observation.");
            wire.AssertActorWrite = null;
            TestAssert.That(Read(() => new string('b', 64)) != revision && Read(() => null) is null && Read(() => "client-digest") is null,
                "Native book ownership was ignored or an invalid book source was accepted.");
            var checks = 0;
            TestAssert.That(Read(() => ++checks == 1 ? new string('a', 64) : new string('b', 64)) is null, "Book-owner race produced a source revision.");
            TestAssert.That(coordinator.CurrentActorSource(peer.Id, "AAAA-BBBB-CCCC-DDDD", () => new string('a', 64)) is null, "Another peer key was accepted.");
            store.SetLocalGrant("personal_tasks_sync", false);
            TestAssert.That(Read() is null, "Grant revocation reused an actor source.");
            store.SetLocalGrant("personal_tasks_sync", true); store.NextOwnRevision("grants");
            var granted = Read();
            TestAssert.That(granted is { Length: 64 } && granted != revision, "Native grant revision was not source-bound.");
            var changed = PhoneContentScope.Advance(manifest, ["note-two"], ["task-one"]);
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var current = Read();
            TestAssert.That(current is not null && current != granted, "Scope replacement retained source identity.");
            beforeWire = wire.Length; beforeEmitted = emitted;
            TestAssert.That(Read() == current && wire.Length == beforeWire && emitted == beforeEmitted, "Source inspection emitted transport or GUI work.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = grants.DeepClone() }));
            var remoteRevision = Read();
            TestAssert.That(remoteRevision is not null && remoteRevision != current, "Fresh remote grant revision was not source-bound.");
            store.UpdatePeerProtocol(peer.Id, 0, null, 3, grants);
            TestAssert.That(Read() is null, "Cached fresh flags authorized a control revision unseen on this connection.");
            await connection.HandlePlainAsync(Message("grants.update", new JsonObject { ["revision"] = 4, ["grants"] = grants.DeepClone() }));
            current = Read();
            TestAssert.That(current is not null, "Actual current grant control did not refresh source authority.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = false }));
            TestAssert.That(Read() is null, "Remote ownership revocation stayed authorized.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            var renewed = store.SharedSettings(peer.Id, peer.PublicKey) ?? store.ChangeSharedSetting(peer.Id, peer.PublicKey, "content_mode", JsonValue.Create("phone_scope")!);
            await connection.HandlePlainAsync(Message(SharedSyncSettings.Kind, SharedSyncSettings.Merge(SharedSyncSettings.Create(peer.Id), renewed, peer.Id, identity.Id)));
            foreach (var part in PhoneContentScope.Chunks(changed)) await connection.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
            var reowned = Read();
            TestAssert.That(reowned is not null && reowned != current, "Remote revoke/regrant inherited an old actor source.");
            await connection.HandlePlainAsync(Message("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true }));
            TestAssert.That(Read() == reowned, "Unchanged ownership replay rotated actor authority.");
            online.Clear(); TestAssert.That(Read() is null, "A disconnected native source stayed authorized.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
