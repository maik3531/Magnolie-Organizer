using System.Text.Json.Nodes;
using System.Buffers.Binary;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class SharedSyncTransportTests
{
    internal static async Task<IReadOnlyList<JsonObject>> DrainAsync(MemoryStream wire)
    {
        using var input = new MemoryStream(wire.ToArray()); wire.SetLength(0); wire.Position = 0;
        var result = new List<JsonObject>();
        while (input.Position < input.Length)
        {
            var envelope = await TelefonCoordinator.ReadFrameAsync(input, 1_048_576, CancellationToken.None);
            var cipher = Convert.FromBase64String(envelope["ciphertext"]!.GetValue<string>());
            envelope.Remove("ciphertext");
            var nonce = new byte[12]; BinaryPrimitives.WriteUInt64BigEndian(nonce.AsSpan(4), (ulong)TelefonProtocolContract.Integer(envelope["seq"]));
            var clear = new byte[cipher.Length - 16];
            using var aes = new AesGcm(new byte[32], 16);
            aes.Decrypt(nonce, cipher.AsSpan(0, clear.Length), cipher.AsSpan(clear.Length), clear, TelefonCrypto.Canonical(envelope));
            result.Add(JsonNode.Parse(clear)!.AsObject());
        }
        return result;
    }

    private static JsonObject Message(string kind, JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }

    internal static async Task LegacyMediaSupportAsync()
    {
        using var fixture = new PhoneCameraParentTests.Fixture();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        var store = fixture.Store;
        var peer = fixture.Peer;
        store.SavePeers([peer]);
        store.SetPersonalSettings(peer.Id, ownDevice: true, remoteOwnDevice: true);
        var caps = TelefonProtocolContract.DesktopCapabilities();
        caps["items"]!["device_status"]!["versions"] = new JsonArray(1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22);
        var revision = TelefonProtocolContract.ValidateCapabilities(caps);
        store.UpdatePeerProtocol(peer.Id, revision, caps["items"]!.AsObject(), 0, null);
        var before = store.LoadPeers().Single();
        var optIns = store.PersonalSettings(peer.Id);
        var grants = store.LocalGrants().DeepClone();
        var hello = Message("media_support.hello", new JsonObject { ["format"] = 1, ["feature"] = "shared_settings" });
        hello["expires_ms"] = TelefonProtocolContract.Integer(hello["created_ms"]) + 10_000;
        var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };

        var run = fixture.Connection.RunAsync();
        try
        {
            await fixture.Send(hello, 0);
            var ack = await fixture.Read(0);
            // The Windows legacy kind allowlist rejects before authorization.
            TestAssert.That(JsonNode.DeepEquals(ack, new JsonObject { ["type"] = "ack", ["message_id"] = hello["message_id"]!.DeepClone(),
                ["status"] = "rejected", ["error"] = "invalid_schema" }), $"Unexpected legacy response to the synthetic probe: {ack}");
            await fixture.Send(ping, 1);
            ping["type"] = "pong";
            TestAssert.That(JsonNode.DeepEquals(await fixture.Read(1), ping), "Heartbeat did not continue on the original encrypted parent.");
            var after = store.LoadPeers().Single();
            TestAssert.That(after.Id == before.Id && after.State == before.State && after.PublicKey.SequenceEqual(before.PublicKey) &&
                after.FilePairingEpoch == before.FilePairingEpoch && after.CapabilityRevision == before.CapabilityRevision &&
                JsonNode.DeepEquals(after.Capabilities, before.Capabilities) && JsonNode.DeepEquals(after.Grants, before.Grants) &&
                store.PersonalSettings(peer.Id) == optIns && JsonNode.DeepEquals(grants, store.LocalGrants()) &&
                fixture.LegacyReceives == 0 && !fixture.Connection.SharedSettingsReady,
                "Unknown media probe altered pairing, capabilities, grants or ordinary preference processing.");
            await fixture.Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" }, 2);
            await run.WaitAsync(timeout.Token);
        }
        finally
        {
            fixture.Connection.Dispose();
            try { await run.WaitAsync(timeout.Token); } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
        }
    }

    internal static async Task NativeMediaSupportAsync()
    {
        using var fixture = new PhoneCameraParentTests.Fixture(filePairingEpoch: new string('a', 64), receive: (store, peer, message) =>
        {
            var body = message["body"]!.AsObject();
            switch (message["kind"]!.GetValue<string>())
            {
                case "capabilities.update": store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null); break;
                case "grants.update": store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject()); break;
                case "personal_sync.settings": store.SetPersonalSettings(peer.Id, remoteOwnDevice: body["own_device"]!.GetValue<bool>()); break;
                default: throw new InvalidOperationException("Unexpected ordinary dispatch");
            }
            return Task.FromResult<TelefonAck?>(null);
        });
        var connection = fixture.Connection;
        fixture.Store.SavePeers([fixture.Peer]);
        fixture.Store.Enabled = true;
        fixture.Store.SetPersonalSettings(fixture.Peer.Id, ownDevice: true, remoteOwnDevice: true);
        connection.NativeMediaSupportChecked = true;
        long sent = 0, received = 0;
        JsonObject Hello()
        {
            var hello = Message("media_support.hello", new JsonObject { ["format"] = 1, ["feature"] = "shared_settings" });
            hello["expires_ms"] = TelefonProtocolContract.Integer(hello["created_ms"]) + 10_000;
            return hello;
        }
        static JsonObject Ack(JsonObject frame) => new() { ["type"] = "ack", ["message_id"] = frame["message_id"]!.DeepClone(), ["status"] = "accepted", ["error"] = "none" };
        async Task Ping()
        {
            var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
            await fixture.Send(ping, sent++); ping["type"] = "pong";
            TestAssert.That(JsonNode.DeepEquals(ping, await fixture.Read(received++)), "Original parent did not answer heartbeat.");
        }
        async Task Control(string kind, JsonObject body)
        {
            var packet = Message(kind, body);
            await fixture.Send(packet, sent++);
            var response = await fixture.Read(received++);
            while (response["kind"]?.GetValue<string>() is SharedSyncSettings.Kind or PersonalSyncContract.DesktopFeaturesKind or TimeSyncContract.Settings)
            {
                await fixture.Send(Ack(response), sent++);
                response = await fixture.Read(received++);
            }
            TestAssert.That(JsonNode.DeepEquals(Ack(packet), response), $"Expected {kind} acknowledgement before discovery, got {response}.");
        }
        var run = connection.RunAsync();
        try
        {
            await fixture.Send(Hello(), sent++);
            await Ping(); // A saved paired peer does not by itself authorize discovery.
            var caps = TelefonProtocolContract.DesktopCapabilities();
            caps["items"]!["device_status"]!["versions"] = new JsonArray(1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22);
            await Control("capabilities.update", caps);
            await Control("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = TelefonProtocolContract.DesktopGrants() });
            await Control("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
            var malformed = Hello(); malformed["body"]!["feature"] = "image_batch";
            await fixture.Send(malformed, sent++);
            await Ping();
            var probe = Hello();
            await fixture.Send(probe, sent++);
            var reply = await fixture.Read(received++);
            TestAssert.That(reply["kind"]!.GetValue<string>() == "media_support.hello" && !connection.NativeMediaSupportEstablished,
                "A one-sided probe already authorized settings.");
            TestAssert.That(JsonNode.DeepEquals(Ack(probe), await fixture.Read(received++)), "Remote probe did not get its exact ACK.");
            await fixture.Send(Ack(reply), sent++);
            await Ping();
            TestAssert.That(connection.NativeMediaSupportEstablished && !connection.MediaSharedControlsReady, "Support was missing or granted the media runtime.");
            var local = fixture.Store.LoadOrCreateIdentity();
            CryptographicOperations.ZeroMemory(local.PrivateKey);
            var remote = fixture.Peer.Id;
            var selected = MediaSyncSettings.Change(MediaSyncSettings.Create(remote), remote, local.Id, "enabled", JsonValue.Create(true)!);
            var privateFrames = new List<JsonObject> { malformed, probe, reply };
            if (OperatingSystem.IsWindows())
            {
                File.WriteAllText(fixture.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
                    new byte[32], "magnolie-phone-storage-v1"u8.ToArray(), DataProtectionScope.CurrentUser)));
                await Control(MediaSyncSettings.Kind, selected);
                var echo = await fixture.Read(received++);
                privateFrames.Add(echo);
                TestAssert.That(echo["kind"]!.GetValue<string>() == MediaSyncSettings.Kind, "Missing protected shared settings echo.");
                await fixture.Send(Ack(echo), sent++);
                await Ping();
                TestAssert.That(!connection.PrivateMediaSettingsMatched, "Settings ACK without identical echo meant agreement.");
                await Control(MediaSyncSettings.Kind, echo["body"]!.AsObject());
                await Ping();
                TestAssert.That(connection.PrivateMediaSettingsMatched && !connection.MediaSharedSettingsReady,
                    "Private settings failed to converge or created a legacy file intent.");
            }
            else
            {
                var proposal = Message(MediaSyncSettings.Kind, selected);
                privateFrames.Add(proposal);
                await fixture.Send(proposal, sent++);
                var rejection = Ack(proposal); rejection["status"] = "rejected"; rejection["error"] = "not_granted";
                TestAssert.That(JsonNode.DeepEquals(rejection, await fixture.Read(received++)), "Missing native DPAPI was not held.");
                await Ping();
                TestAssert.That(!connection.PrivateMediaSettingsMatched, "Linux stand-in granted protected Windows settings.");
            }
            await Control("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = false });
            await Control("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
            await fixture.Send(Ack(reply), sent++);
            await fixture.Send(Hello(), sent++);
            await Ping();
            TestAssert.That(!connection.NativeMediaSupportEstablished && fixture.LegacyReceives == 5, "Withdrawal was reversed or discovery entered the ordinary dispatcher.");
            TestAssert.That(!connection.PrivateMediaSettingsMatched &&
                (OperatingSystem.IsWindows() == fixture.Store.HasNativeMediaSharedSettings(remote)),
                "Withdrawal erased saved choices, stored choices without DPAPI or kept the old agreement current.");
            foreach (var frame in privateFrames)
            {
                var id = frame["message_id"]!.GetValue<string>();
                TestAssert.That(fixture.Store.OutboxMessage(fixture.Peer.Id, id) is null && !fixture.Store.ReceivedMatches(fixture.Peer.Id, frame),
                    "A private probe entered durable phone storage.");
            }
            await fixture.Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" }, sent++);
            await run;
        }
        finally
        {
            connection.Dispose();
            try { await run; } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
        }
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
            var negotiated = TelefonProtocolContract.DesktopCapabilities();
            TestAssert.That(SharedSyncSettings.Supported(negotiated["items"]!.AsObject(), negotiated["items"]!.AsObject()),
                "Shared-preference support was not advertised.");
            var legacyCapabilities = negotiated.DeepClone().AsObject();
            foreach (var name in new[] { "personal_notes_sync", "personal_tasks_sync" })
            {
                legacyCapabilities["items"]![name]!["versions"] = new JsonArray(legacyCapabilities["items"]![name]!["versions"]!.AsArray()
                    .Where(value => value!.GetValue<int>() < 9).Select(value => value!.DeepClone()).ToArray());
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
            TelefonConnection Connect(bool supported = true, MemoryStream? wire = null) => new TelefonConnection(peer, wire ?? new MemoryStream(), new byte[16], new byte[72],
                store, Receive, CancellationToken.None, "wifi") { SharedLocalCapabilities = () => (supported ? negotiated : legacyCapabilities)["items"]!.DeepClone().AsObject() };
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
            using (var bootstrap = Connect())
            {
                await bootstrap.HandlePlainAsync(caps); await bootstrap.HandlePlainAsync(grants); await bootstrap.HandlePlainAsync(own);
                var staleBootstrap = remote.DeepClone().AsObject();
                staleBootstrap["settings"]!["auto_mode"]![actor]!["value"] = "wifi";
                var beforeGrants = store.LocalGrants().DeepClone();
                await bootstrap.HandlePlainAsync(Message(SharedSyncSettings.Kind, staleBootstrap));
                var reasserted = store.SharedSettings(peer.Id, peer.PublicKey)!;
                TestAssert.That(reasserted["settings"]!["auto_mode"]![actor]!["counter"]!.GetValue<long>() == 1 &&
                    reasserted["settings"]!["auto_mode"]![actor]!["value"]!.GetValue<string>() == "manual" &&
                    !bootstrap.SharedSettingsReady, "Stale bootstrap either blocked recovery or prematurely established agreement.");
                var echo = SharedSyncSettings.Merge(staleBootstrap, reasserted, peer.Id, actor);
                await bootstrap.HandlePlainAsync(Message(SharedSyncSettings.Kind, echo));
                TestAssert.That(bootstrap.SharedSettingsReady && JsonNode.DeepEquals(beforeGrants, store.LocalGrants()),
                    "Current bootstrap echo did not establish agreement without changing grants.");
                remote = echo; update = Message(SharedSyncSettings.Kind, remote);
            }
            using var scopeWire = new MemoryStream();
            using (var scoped = Connect(wire: scopeWire))
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
                var single = new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"),
                    ["trigger"] = "manual", ["modules"] = new JsonArray("notes"),
                    ["send_item"] = new JsonObject { ["kind"] = "note", ["id"] = "organizer-only" } };
                var singleNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                new PersonalSyncStore(store).RememberRun(peer.Id, single, singleNow, singleNow + 60000);
                var singleId = store.Enqueue(peer.Id, "personal_sync.request", single, 60000, singleNow);
                await scoped.PumpOutboxNowAsync();
                TestAssert.That((await DrainAsync(scopeWire)).Any(value => value["message_id"]?.GetValue<string>() == singleId &&
                    value["kind"]?.GetValue<string>() == "personal_sync.request" && JsonNode.DeepEquals(value["body"], single)),
                    "A manually selected Organizer-only note did not use the existing transfer.");
                store.CompleteOutbox(peer.Id, singleId);
                var next = PhoneContentScope.Advance(manifest, Enumerable.Range(0, 100).Select(n => $"updated-{n:D3}"), []);
                var nextParts = PhoneContentScope.Chunks(next, 32);
                await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, nextParts[0]));
                TestAssert.Throws<InvalidOperationException>(() => scoped.CurrentContentScope(PhoneContentScope.Reference(manifest)), "New incomplete scope kept old membership authorized.");
                foreach (var part in nextParts.Skip(1)) await scoped.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                TestAssert.That(JsonNode.DeepEquals(next, scoped.CurrentContentScope(PhoneContentScope.Reference(next))), "Updated wire membership did not become current.");
                var changedTime = store.ChangeSharedSetting(peer.Id, peer.PublicKey, "time_enabled", JsonValue.Create(true)!);
                TestAssert.That(!scoped.SharedSettingsReady, "Time change did not require a fresh settings echo.");
                await DrainAsync(scopeWire);
                var retryPart = Message(PhoneContentScope.Kind, nextParts[0]);
                var pendingRequest = new JsonObject { ["format"] = 3, ["run_id"] = Guid.NewGuid().ToString("D"),
                    ["trigger"] = "manual", ["modules"] = new JsonArray("notes", "tasks") };
                var retryRequest = Message(PhoneContentScope.DataKind, PhoneContentScope.Wrap("personal_sync.request", pendingRequest, next));
                foreach (var packet in new[] { retryPart, retryRequest })
                {
                    await scoped.HandlePlainAsync(packet);
                    var ack = (await DrainAsync(scopeWire)).Last(value => value["type"]?.GetValue<string>() == "ack");
                    TestAssert.That(ack["status"]?.GetValue<string>() == "rejected" && ack["error"]?.GetValue<string>() == "temporary_failure", "Settings gap became a terminal scope failure.");
                }
                var pendingRuns = new PersonalSyncStore(store);
                var raw = pendingRequest.DeepClone().AsObject(); raw["run_id"] = Guid.NewGuid().ToString("D");
                await scoped.HandlePlainAsync(Message("personal_sync.request", raw));
                TestAssert.That((await DrainAsync(scopeWire)).Last()["error"]?.GetValue<string>() == "not_granted" &&
                    pendingRuns.LoadRun(peer.Id, raw["run_id"]!.GetValue<string>(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()) is null,
                    "A settings gap admitted raw legacy data.");
                var legacy = raw.DeepClone().AsObject(); legacy["run_id"] = Guid.NewGuid().ToString("D");
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                pendingRuns.RememberRun(peer.Id, legacy, now, now + 60000);
                store.Enqueue(peer.Id, "personal_sync.request", legacy, 60000, now);
                await scoped.PumpOutboxNowAsync();
                TestAssert.That(!(await DrainAsync(scopeWire)).Any(value => value["kind"]?.GetValue<string>() == "personal_sync.request"), "A settings gap sent unscoped content.");
                var echoed = SharedSyncSettings.Merge(choice, changedTime, peer.Id, actor);
                await scoped.HandlePlainAsync(Message(SharedSyncSettings.Kind, echoed));
                TestAssert.That(scoped.SharedSettingsReady, "Settings echo did not restore content readiness.");
                foreach (var packet in new[] { retryPart, retryRequest })
                {
                    await scoped.HandlePlainAsync(packet);
                    var ack = (await DrainAsync(scopeWire)).Last(value => value["type"]?.GetValue<string>() == "ack");
                    TestAssert.That(ack["status"]?.GetValue<string>() is "accepted" or "duplicate", "Temporary scope failure poisoned the original message ID.");
                }
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
                using var downgradedWire = new MemoryStream();
                using var downgraded = Connect(false, downgradedWire);
                await downgraded.HandlePlainAsync(caps); await downgraded.HandlePlainAsync(grants); await downgraded.HandlePlainAsync(own);
                await DrainAsync(downgradedWire);
                var downgradedRequest = request.DeepClone().AsObject(); downgradedRequest["run_id"] = Guid.NewGuid().ToString("D");
                await downgraded.HandlePlainAsync(Message("personal_sync.request", downgradedRequest));
                TestAssert.That((await DrainAsync(downgradedWire)).Last()["error"]?.GetValue<string>() == "not_granted" &&
                    runs.LoadRun(peer.Id, downgradedRequest["run_id"]!.GetValue<string>(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()) is null,
                    "Capability downgrade bypassed the persisted scope choice.");
            }
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
