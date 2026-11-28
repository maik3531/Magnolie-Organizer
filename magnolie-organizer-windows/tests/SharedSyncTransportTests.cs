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

    internal static Task NativeMediaSupportAsync() => NativeMediaSupportAsync(firstReceive: null);
    internal static Task NativeFirstReceiveEntryAsync() => NativeMediaSupportAsync(firstReceive: "images");
    internal static Task NativeFirstVideoReceiveEntryAsync() => NativeMediaSupportAsync(firstReceive: "video");
    internal static Task NativeFirstMixedReceiveEntryAsync() => NativeMediaSupportAsync(firstReceive: "mixed");
    internal static Task NativeFirstMixedReceiveContentAsync() => NativeMediaSupportAsync(firstReceive: "mixed", transfer: true);
    internal static Task NativeFirstMixedDefaultContentAsync() => NativeMediaSupportAsync(firstReceive: "mixed", transfer: true, useDefaults: true);
    internal static Task NativeOriginalAutomaticSetupAsync() => NativeMediaSupportAsync(firstReceive: "mixed", automatic: "missing_read");
    internal static Task NativeOriginalAutomaticContentAsync() => NativeMediaSupportAsync(firstReceive: "mixed", transfer: true, automatic: "content");
    internal static Task NativeOriginalAutomaticReconnectAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "mixed", transfer: true, automatic: "reconnect")
            : Task.CompletedTask;
    internal static Task NativeOriginalAutomaticStopAsync() => NativeMediaSupportAsync(firstReceive: "mixed", automatic: "stop");
    internal static Task NativeOriginalSettingsEditAsync() => NativeMediaSupportAsync(firstReceive: "settings");
    internal static Task NativeOriginalPcImageHelloAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_image_hello")
            : Task.CompletedTask;
    internal static Task NativeOriginalPcImageManualAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_image_manual", transfer: true, composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalPcImageAutomaticAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_image_automatic", transfer: true, composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalPcVideoManualEntryAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_video_manual_entry", transfer: true, composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalPcVideoAutomaticEntryAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_video_automatic_entry", transfer: true, composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalPcVideoAutomaticStopAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_video_automatic_stop", composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalPcVideoAutomaticOffAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: "pc_video_automatic_off", composed: true)
            : Task.CompletedTask;
    internal static Task NativeOriginalCompositionAsync() =>
        DesktopPhoneBuild.PrivateMediaSettings && OperatingSystem.IsWindows()
            ? NativeMediaSupportAsync(firstReceive: null, composed: true)
            : Task.CompletedTask;

    private static async Task NativeMediaSupportAsync(string? firstReceive, bool transfer = false, bool composed = false,
        bool useDefaults = false, string? automatic = null)
    {
        Func<Task>? beforeMetadataAck = null;
        async Task<TelefonAck?> PublishMetadata(TelefonStore store, TelefonPeer peer, JsonObject message)
        {
            var body = message["body"]!.AsObject();
            switch (message["kind"]!.GetValue<string>())
            {
                case "capabilities.update": store.UpdatePeerProtocol(peer.Id, TelefonProtocolContract.Integer(body["revision"]), body["items"]!.AsObject(), 0, null); break;
                case "grants.update": store.UpdatePeerProtocol(peer.Id, 0, null, TelefonProtocolContract.Integer(body["revision"]), body["grants"]!.AsObject()); break;
                case "personal_sync.settings": store.SetPersonalSettings(peer.Id, remoteOwnDevice: body["own_device"]!.GetValue<bool>()); break;
                default: throw new InvalidOperationException("Unexpected ordinary dispatch");
            }
            if (beforeMetadataAck is not null) await beforeMetadataAck();
            return null;
        }
        using var fixture = new PhoneCameraParentTests.Fixture(filePairingEpoch: new string('a', 64), receive: PublishMetadata,
              lifetime: transfer ? TimeSpan.FromSeconds(firstReceive is "pc_image_manual" or "pc_image_automatic" or
                  "pc_video_manual_entry" or "pc_video_automatic_entry" ? 240 : 50) : null,
            peerName: useDefaults ? "Magnolie Test " + Guid.NewGuid().ToString("N") : "Controlled original parent");
        var connection = fixture.Connection;
        fixture.Store.SavePeers([fixture.Peer]);
        fixture.Store.Enabled = true;
        fixture.Store.SetPersonalSettings(fixture.Peer.Id, ownDevice: true, remoteOwnDevice: true);
        using var composition = composed ? new TelefonCoordinator(fixture.Paths, (_, _) => Task.CompletedTask, dataStore: fixture.Store, localOnly: true) : null;
        if (composition is not null)
        {
            typeof(TelefonCoordinator).GetMethod("ConfigureNativeMediaConnection", System.Reflection.BindingFlags.Instance |
                System.Reflection.BindingFlags.NonPublic)!.Invoke(composition, [fixture.Peer, connection]);
            var versions = TelefonProtocolContract.DesktopCapabilities()["items"]!["device_status"]!["versions"]!.AsArray()
                .Select(TelefonProtocolContract.Integer).ToArray();
            TestAssert.That(connection.NativeMediaSupportChecked && versions.Contains((long)DeviceFileControl.DiscoveryVersion) &&
                versions.Contains((long)DeviceFileControl.VideoDiscoveryVersion) && !versions.Contains((long)MediaSyncSettings.DiscoveryVersion),
                "The actual connection composition did not advertise only the ordinary native media handlers.");
        }
        else connection.NativeMediaSupportChecked = true;
        long sent = 0, received = 0;
        static JsonObject PhoneCapabilities()
        {
            var caps = TelefonProtocolContract.DesktopCapabilities();
            caps["items"]!["device_status"]!["versions"] = new JsonArray(1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 17, 18, 19, 20, 21, 22);
            return caps;
        }
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
        async Task Reconnect(TelefonCoordinator coordinator, Dictionary<string, TelefonConnection> online,
            Func<Func<Task<JsonObject>>, Func<JsonObject, Task>, TelefonConnection, Task> transferOriginals)
        {
            var peer = fixture.Peer;
            var saved = fixture.Store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
            var retired = connection.CapturePrivateMediaPhoneImport(saved!);
            TestAssert.That(retired?.Invoke() == true && online.Remove(peer.Id), "Setup did not retain its original reader.");
            await fixture.Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" }, sent++);
            await run;
            connection.Dispose();
            TestAssert.That(retired?.Invoke() != true, "The disconnected reader still authorizes media.");

            using var fresh = new PhoneCameraParentTests.Fixture(receive: PublishMetadata, previous: fixture,
                lifetime: TimeSpan.FromSeconds(50));
            typeof(TelefonCoordinator).GetMethod("ConfigureNativeMediaConnection", System.Reflection.BindingFlags.Instance |
                System.Reflection.BindingFlags.NonPublic)!.Invoke(coordinator, [peer, fresh.Connection]);
            online.Add(peer.Id, fresh.Connection);
            var reader = fresh.Connection.RunAsync();
            long incoming = 0, outgoing = 0;
            Task<JsonObject> Read() => fresh.Read(incoming++);
            Task Send(JsonObject frame) => fresh.Send(frame, outgoing++);
            async Task Metadata(string kind, JsonObject body)
            {
                var packet = Message(kind, body);
                await Send(packet);
                var response = await Read();
                while (response["kind"]?.GetValue<string>() is SharedSyncSettings.Kind or PersonalSyncContract.DesktopFeaturesKind or TimeSyncContract.Settings)
                {
                    await Send(Ack(response));
                    response = await Read();
                }
                TestAssert.That(JsonNode.DeepEquals(Ack(packet), response), $"Wrong fresh reader receipt for {kind}: {response}");
            }
            async Task Barrier()
            {
                var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"),
                    ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
                await Send(ping);
                ping["type"] = "pong";
                TestAssert.That(JsonNode.DeepEquals(ping, await Read()), "The fresh reader did not complete the receipt barrier.");
            }
            async Task AwaitingAgreement()
            {
                await Barrier();
                await coordinator.RunNativeMediaAutomaticOnceAsync(peer.Id, CancellationToken.None);
                TestAssert.That(!fresh.HasUnexpectedFrame && !fresh.Connection.PrivateMediaSettingsMatched &&
                    fixture.Store.NativeMediaReceiveHistory(peer.Id).Count == 0,
                    "A new reader inherited authority before fresh settings receipts.");
            }
            try
            {
                await AwaitingAgreement();
                var current = fixture.Store.LoadPeers().Single(value => value.Id == peer.Id);
                var caps = PhoneCapabilities();
                caps["revision"] = current.CapabilityRevision + 1;
                await Metadata("capabilities.update", caps);
                await Metadata("grants.update", new JsonObject { ["revision"] = current.GrantRevision + 1, ["grants"] = TelefonProtocolContract.DesktopGrants() });
                await Metadata("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
                var probe = Hello();
                await Send(probe);
                var reply = await Read();
                TestAssert.That(reply["kind"]?.GetValue<string>() == "media_support.hello" &&
                    JsonNode.DeepEquals(Ack(probe), await Read()), "The new reader did not negotiate original support.");
                await Send(Ack(reply));
                var restored = await Read();
                TestAssert.That(restored["kind"]?.GetValue<string>() == MediaSyncSettings.Kind &&
                    JsonNode.DeepEquals(saved, restored["body"]), "The new reader did not propose the persisted WLAN settings.");
                await Send(Ack(restored));
                await AwaitingAgreement();
                await Metadata(MediaSyncSettings.Kind, saved!);
                await Barrier();
                TestAssert.That(fresh.Connection.PrivateMediaSettingsMatched && retired?.Invoke() != true,
                    "Fresh receipts failed to bind the new reader exclusively.");
                await transferOriginals(Read, Send, fresh.Connection);
                await Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" });
                await reader;
            }
            finally
            {
                online.Remove(peer.Id);
                fresh.Connection.Dispose();
                try { await reader; } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
            }
        }
        try
        {
            await fixture.Send(Hello(), sent++);
            await Ping(); // A saved paired peer does not by itself authorize discovery.
            var caps = PhoneCapabilities();
            await Control("capabilities.update", caps);
            await Control("grants.update", new JsonObject { ["revision"] = 1, ["grants"] = TelefonProtocolContract.DesktopGrants() });
            var probe = Hello();
            var malformed = Hello(); malformed["body"]!["feature"] = "image_batch";
            if (composed)
            {
                probe["created_ms"] = TelefonProtocolContract.Integer(probe["created_ms"]) + 150;
                probe["expires_ms"] = TelefonProtocolContract.Integer(probe["created_ms"]) + 10_000;
                await fixture.Send(probe, sent++);
                await Ping(); // No hello reply before the final current native receipt.
            }
            await Control("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = true });
            if (!composed)
            {
                await fixture.Send(malformed, sent++);
                await Ping();
                await fixture.Send(probe, sent++);
            }
            var reply = await fixture.Read(received++);
            TestAssert.That(reply["kind"]!.GetValue<string>() == "media_support.hello" && !connection.NativeMediaSupportEstablished &&
                TelefonProtocolContract.Integer(reply["expires_ms"]) <= TelefonProtocolContract.Integer(probe["expires_ms"]),
                "A one-sided probe already authorized settings.");
            TestAssert.That(JsonNode.DeepEquals(Ack(probe), await fixture.Read(received++)), "Remote probe did not get its exact ACK.");
            var local = fixture.Store.LoadOrCreateIdentity();
            CryptographicOperations.ZeroMemory(local.PrivateKey);
            var remote = fixture.Peer.Id;
            var selected = MediaSyncSettings.Change(MediaSyncSettings.Create(remote), remote, local.Id, "enabled", JsonValue.Create(true)!);
            var pcImages = firstReceive is "pc_image_hello" or "pc_image_manual" or "pc_image_automatic";
            var pcVideo = firstReceive is "pc_video_manual_entry" or "pc_video_automatic_entry" or "pc_video_automatic_stop" or "pc_video_automatic_off";
            selected = MediaSyncSettings.Change(selected, remote, local.Id, "direction", JsonValue.Create(pcImages || pcVideo ? "pc_to_phone" : "phone_to_pc")!);
            if (pcImages || pcVideo)
                selected = MediaSyncSettings.Change(selected, remote, local.Id, "collection_mode", JsonValue.Create("entire_collection")!);
            if (firstReceive == "video" || pcVideo)
                selected = MediaSyncSettings.Change(selected, remote, local.Id, "photos_enabled", JsonValue.Create(false)!);
            if (firstReceive is "video" or "mixed" || pcVideo)
                selected = MediaSyncSettings.Change(selected, remote, local.Id, "videos_enabled", JsonValue.Create(true)!);
            if (automatic is not null)
                selected = MediaSyncSettings.Change(selected, remote, local.Id, "auto_mode", JsonValue.Create("wifi")!);
            if (composed && OperatingSystem.IsWindows())
            {
                File.WriteAllText(fixture.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
                    new byte[32], "magnolie-phone-storage-v1"u8.ToArray(), DataProtectionScope.CurrentUser)));
                fixture.Store.MergeNativeMediaSharedSettings(remote, fixture.Peer.PublicKey, selected);
            }
            await fixture.Send(Ack(reply), sent++);
            var privateFrames = new List<JsonObject> { malformed, probe, reply };
            JsonObject? restored = null;
            if (composed)
            {
                restored = await fixture.Read(received++);
                TestAssert.That(restored["kind"]?.GetValue<string>() == MediaSyncSettings.Kind &&
                    JsonNode.DeepEquals(restored["body"], fixture.Store.ReadNativeMediaSharedSettings(remote, fixture.Peer.PublicKey)) &&
                    !connection.PrivateMediaSettingsMatched, "A fresh original WLAN reader did not propose the saved setting, or inherited authority without receipts.");
            }
            await Ping();
            TestAssert.That(connection.NativeMediaSupportEstablished && !connection.MediaSharedControlsReady, "Support was missing or granted the media runtime.");
            Func<bool>? originalImport = null;
            if (OperatingSystem.IsWindows())
            {
                if (!composed)
                {
                    File.WriteAllText(fixture.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
                        new byte[32], "magnolie-phone-storage-v1"u8.ToArray(), DataProtectionScope.CurrentUser)));
                    await Control(MediaSyncSettings.Kind, selected);
                }
                var echo = restored ?? await fixture.Read(received++);
                privateFrames.Add(echo);
                TestAssert.That(echo["kind"]!.GetValue<string>() == MediaSyncSettings.Kind, "Missing protected shared settings echo.");
                await fixture.Send(Ack(echo), sent++);
                await Ping();
                TestAssert.That(!connection.PrivateMediaSettingsMatched, "Settings ACK without identical echo meant agreement.");
                await Control(MediaSyncSettings.Kind, echo["body"]!.AsObject());
                await Ping();
                TestAssert.That(connection.PrivateMediaSettingsMatched && !connection.MediaSharedSettingsReady,
                    "Private settings failed to converge or created a legacy file intent.");
                var body = echo["body"]!.AsObject();
                if (pcImages)
                {
                    await VerifyPcImageHello(fixture, body, () => fixture.Read(received++), frame => fixture.Send(frame, sent++),
                        manual: firstReceive == "pc_image_manual",
                        automatic: firstReceive == "pc_image_automatic" ? composition : null, Control, Ping);
                    return;
                }
                if (pcVideo)
                {
                    await VerifyPcVideoEntry(fixture, composition!, () => fixture.Read(received++),
                        frame => fixture.Send(frame, sent++), Control, Ping, firstReceive!);
                    return;
                }
                originalImport = connection.CapturePrivateMediaPhoneImport(body);
                var foreign = MediaSyncSettings.Change(body, remote, local.Id, "direction", JsonValue.Create("two_way")!);
                TestAssert.That(originalImport?.Invoke() == true && connection.CapturePrivateMediaPhoneImport(foreign) is null,
                    "Original read witness was absent or admitted a different direction.");
                if (composed)
                {
                    async Task ObserveRefresh(string kind, JsonObject metadata, bool staysCurrent)
                    {
                        var applied = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                        beforeMetadataAck = async () =>
                        {
                            applied.TrySetResult();
                            await release.Task.WaitAsync(TimeSpan.FromSeconds(3));
                        };
                        var exchanging = Control(kind, metadata);
                        try
                        {
                            await applied.Task.WaitAsync(TimeSpan.FromSeconds(3));
                            TestAssert.That(connection.PrivateMediaSettingsMatched == staysCurrent && (originalImport?.Invoke() == true) == staysCurrent,
                                "The original Windows WLAN agreement changed incorrectly before metadata ACK.");
                        }
                        finally { beforeMetadataAck = null; release.TrySetResult(); }
                        await exchanging;
                    }
                    caps["revision"] = 2;
                    await ObserveRefresh("capabilities.update", caps, staysCurrent: true);
                    await ObserveRefresh("grants.update", new JsonObject { ["revision"] = 2, ["grants"] = TelefonProtocolContract.DesktopGrants() }, staysCurrent: true);
                    await Ping();
                    TestAssert.That(connection.PrivateMediaSettingsMatched && originalImport?.Invoke() == true,
                        "An equivalent metadata refresh retired the same original Windows WLAN agreement.");
                    var withdrawn = TelefonProtocolContract.DesktopGrants(); withdrawn["device_status"] = false;
                    await ObserveRefresh("grants.update", new JsonObject { ["revision"] = 3, ["grants"] = withdrawn }, staysCurrent: false);
                }
                if (firstReceive is not null) await VerifyFirstReceiveEntry(fixture, connection, remote, firstReceive, transfer, useDefaults, automatic,
                    () => fixture.Read(received++), frame => fixture.Send(frame, sent++),
                    automatic == "reconnect" ? Reconnect : null);
                if (automatic == "reconnect") return;
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
            TestAssert.That(!connection.NativeMediaSupportEstablished && fixture.LegacyReceives == (composed ? 8 : 5),
                "Withdrawal was reversed or discovery entered the ordinary dispatcher.");
            TestAssert.That(!connection.PrivateMediaSettingsMatched &&
                (OperatingSystem.IsWindows() == fixture.Store.HasNativeMediaSharedSettings(remote)),
                "Withdrawal erased saved choices, stored choices without DPAPI or kept the old agreement current.");
            TestAssert.That(originalImport?.Invoke() != true, "A captured reader witness revived after withdrawal.");
            foreach (var frame in privateFrames)
            {
                var id = frame["message_id"]!.GetValue<string>();
                TestAssert.That(fixture.Store.OutboxMessage(fixture.Peer.Id, id) is null && !fixture.Store.ReceivedMatches(fixture.Peer.Id, frame),
                    "A private probe entered durable phone storage.");
            }
            await fixture.Send(new JsonObject { ["type"] = "close", ["reason"] = "normal" }, sent++);
            await run;
        }
        catch when (firstReceive == "pc_image_automatic")
        {
            Console.WriteLine($"Original WLAN reader at failure: {run.Status}; {run.Exception?.GetBaseException().Message}");
            throw;
        }
        finally
        {
            connection.Dispose();
            try { await run; } catch (Exception error) when (error is IOException or OperationCanceledException or ObjectDisposedException) { }
        }
    }

    private static async Task VerifyPcVideoEntry(PhoneCameraParentTests.Fixture fixture, TelefonCoordinator coordinator,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send, Func<string, JsonObject, Task> control,
        Func<Task> heartbeat, string scenario)
    {
        var peer = fixture.Peer.Id;
        var book = new PersonalActorNativeSaveHost(Path.Combine(fixture.Paths.Root, "pc-video-book"),
            "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = book.Snapshot;
        coordinator.NativeSavedBook = book.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(peer, fixture.Connection);
        try
        {
            var view = coordinator.NativeMediaUiStatus(peer);
            TestAssert.That(view["send_choice_kinds"] is JsonArray kinds && kinds.Count == 1 &&
                kinds[0]?.GetValue<string>() == "video" && view["send_consent"] is not null,
                "The matched WLAN video-only settings did not expose independent video SEND.");
            TestAssert.That(view["shared_start_version"] is null && !fixture.HasUnexpectedFrame &&
                !fixture.Store.ReadNativeMediaSendConsent(peer).Explicit &&
                fixture.Store.NativeMediaCollectionRoots(peer).Count == 0,
                "Viewing the video choice granted SEND, picked a root, or started work.");
            if (scenario == "pc_video_manual_entry")
            {
                await DeviceFileOriginalImagesTests.VerifyManualAsync(fixture, coordinator, read, send, video: true);
                return;
            }
            var stop = scenario == "pc_video_automatic_stop";
            var off = scenario == "pc_video_automatic_off";
            var pcReceive = fixture.Store.ReadNativeMediaReceiveConsent(peer);
            pcReceive = fixture.Store.ChangeNativeMediaReceiveConsent(peer, pcReceive.Version, granted: false);
            async Task Agree(JsonObject proposal)
            {
                await send(new JsonObject { ["type"] = "ack", ["message_id"] = proposal["message_id"]!.DeepClone(),
                    ["status"] = "accepted", ["error"] = "none" });
                await control(MediaSyncSettings.Kind, proposal["body"]!.AsObject());
                await heartbeat();
            }
            var sendVersion = view["send_consent"]!["version"]!.GetValue<string>();
            var allowed = coordinator.ConfirmNativeMediaUiSendConsent(peer, sendVersion, false, true, () => true);
            var root = Path.Combine(fixture.Paths.Root, "deliberate-wlan-video-source");
            Directory.CreateDirectory(root);
            var originals = new Dictionary<string, byte[]> { ["original.mp4"] = DeviceFileOriginalImagesTests.OriginalMp4() };
            File.WriteAllBytes(Path.Combine(root, "original.mp4"), originals["original.mp4"]);
            var selected = coordinator.ChooseNativeMediaCollectionFolder(peer, "video", allowed["collection_sources_version"]!.GetValue<string>(),
                current => { current(); return DeviceFileNativeDirectory.OpenExisting(root); });
            await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
            TestAssert.That(!fixture.HasUnexpectedFrame && fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
                "A selected folder and manual settings started a background pass.");
            var timingVersion = selected["shared_settings"]!["versions"]!["auto_mode"]!.GetValue<string>();
            await coordinator.ChangeNativeMediaUiSharedSettingAsync(peer, "auto_mode", JsonValue.Create("wifi")!, timingVersion);
            var proposal = await read();
            TestAssert.That(proposal["kind"]?.GetValue<string>() == MediaSyncSettings.Kind, "Missing WLAN settings proposal.");
            await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
            TestAssert.That(!fixture.HasUnexpectedFrame, "Unacknowledged WLAN choice started a pass.");
            await send(new JsonObject { ["type"] = "ack", ["message_id"] = proposal["message_id"]!.DeepClone(),
                ["status"] = "accepted", ["error"] = "none" });
            await heartbeat();
            await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
            TestAssert.That(!fixture.HasUnexpectedFrame, "WLAN choice without the matching echo started a pass.");
            await control(MediaSyncSettings.Kind, proposal["body"]!.AsObject());
            await heartbeat();
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(230));
            var scheduled = coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token);
            try
            {
                var next = read();
                if (await Task.WhenAny(next, scheduled).WaitAsync(deadline.Token) == scheduled) await scheduled;
                var packet = DeviceFileControlEnvelope.Validate(await next.WaitAsync(deadline.Token), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                TestAssert.That(packet.Grants.SendFiles && !packet.Grants.ReceiveFiles &&
                    fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
                    "The background setup did not wait for separate phone RECEIVE before creating a source.");
                await scheduled;
                await coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token);
                TestAssert.That(!fixture.HasUnexpectedFrame && fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
                    "A repeated background tick without phone RECEIVE started work.");
                var identity = fixture.Store.ReadFileIdentity();
                var phone = new NativeFileControlIdentity(peer, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
                var desktop = new NativeFileControlPeer(identity.DeviceId, identity.IdentitySha256, new object(),
                    true, true, true, true, true, fixture.Peer.FilePairingEpoch);
                var phoneGrant = new NativeLocalFileGrant(new(1, new string('a', 64), false, true), new object(), true);
                using var controls = new NativeFileControlSession(phone, () => desktop, () => phoneGrant);
                controls.ObserveRemote(packet, desktop);
                var waiting = coordinator.NativeMediaUiStatus(peer);
                TestAssert.That(waiting["automatic_phase"]?.GetValue<string>() == "waiting_for_phone" &&
                    waiting["automatic_busy"]?.GetValue<bool>() == false && waiting["automatic"]?.GetValue<bool>() == true &&
                    fixture.Store.ReadNativeMediaReceiveConsent(peer) == pcReceive,
                    "Waiting for phone RECEIVE did not release the worker or depended on PC RECEIVE.");
                if (stop) TestAssert.That(coordinator.StopNativeMediaAutomatic(peer), "The waiting SEND could not be stopped.");
                if (off)
                {
                    var enabledVersion = waiting["shared_settings"]!["versions"]!["enabled"]!.GetValue<string>();
                    var disabled = await coordinator.ChangeNativeMediaUiSharedSettingAsync(peer, "enabled", JsonValue.Create(false)!, enabledVersion);
                    TestAssert.That(disabled["automatic_phase"]?.GetValue<string>() != "waiting_for_phone" &&
                        disabled["automatic"]?.GetValue<bool>() == false,
                        "Switching OFF retained the waiting video setup.");
                    await Agree(await read().WaitAsync(deadline.Token));
                }
                var echoed = controls.Packet();
                controls.MarkSent(echoed);
                await send(DeviceFileControlEnvelope.Create(echoed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
                var answer = DeviceFileControlEnvelope.Validate(await read().WaitAsync(deadline.Token), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                controls.ObserveRemote(answer, desktop);
                await heartbeat();
                scheduled = coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token);
                if (stop || off)
                {
                    await scheduled;
                    TestAssert.That(!answer.Grants.SendFiles && !fixture.HasUnexpectedFrame &&
                        fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
                        "A delayed RECEIVE echo revived the stopped video pass.");
                    if (stop)
                    {
                        foreach (var mode in new[] { "manual", "wifi" })
                        {
                            var timing = coordinator.NativeMediaUiStatus(peer)["shared_settings"]!["versions"]!["auto_mode"]!.GetValue<string>();
                            await coordinator.ChangeNativeMediaUiSharedSettingAsync(peer, "auto_mode", JsonValue.Create(mode)!, timing);
                            await Agree(await read().WaitAsync(deadline.Token));
                        }
                        TestAssert.That(coordinator.NativeMediaUiStatus(peer)["automatic"]?.GetValue<bool>() == true &&
                            !fixture.HasUnexpectedFrame && fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
                            "A deliberate fresh WLAN choice did not resume the paused scheduler or started outside its tick.");
                    }
                    return;
                }
                var competingTick = coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token);
                await DeviceFileOriginalImagesTests.VerifyTransferAsync(fixture, read, send, true, originals, root,
                    scheduled, deadline, controls);
                await competingTick;
                var retained = fixture.Store.NativeMediaSourceHistory(peer).Single();
                await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
                TestAssert.That(fixture.Store.NativeMediaSourceHistory(peer).Single() == retained && !fixture.HasUnexpectedFrame,
                    "The same confirmed WLAN settings started a second transfer after local END.");
            }
            finally
            {
                deadline.Cancel();
                try { await scheduled; } catch (OperationCanceledException) { }
            }
        }
        finally { online.Remove(peer); }
    }

    private static async Task VerifyPcImageHello(PhoneCameraParentTests.Fixture fixture, JsonObject settings,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send, bool manual, TelefonCoordinator? automatic,
        Func<string, JsonObject, Task> control, Func<Task> heartbeat)
    {
        var remote = fixture.Peer.Id;
        using var ownedCoordinator = automatic is null
            ? new TelefonCoordinator(fixture.Paths, (_, _) => Task.CompletedTask, dataStore: fixture.Store, localOnly: true) : null;
        var coordinator = automatic ?? ownedCoordinator!;
        var book = new PersonalActorNativeSaveHost(Path.Combine(fixture.Paths.Root, "pc-image-book"),
            "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = book.Snapshot;
        coordinator.NativeSavedBook = book.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(remote, fixture.Connection);
        try
        {
            var initial = coordinator.NativeMediaUiStatus(remote);
            TestAssert.That(initial["shared_matched"]?.GetValue<bool>() == true &&
                initial["send_consent"] is null && initial["shared_start_version"] is null &&
                fixture.Connection.CapturePrivateMediaPhoneImport(settings) is null,
                "Settings agreement alone projected a transfer or local SEND.");
            var probe = Message("media_support.hello", new JsonObject { ["format"] = 1, ["feature"] = "pc_image_batch_v3" });
            probe["expires_ms"] = TelefonProtocolContract.Integer(probe["created_ms"]) + 10_000;
            var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"),
                ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
            async Task AssertIgnored(JsonObject frame)
            {
                var pong = ping.DeepClone().AsObject();
                pong["type"] = "pong";
                await send(frame);
                await send(ping);
                TestAssert.That(JsonNode.DeepEquals(pong, await read()) && fixture.Connection.CapturePrivatePcImageDiscovery() is null,
                    "An unavailable or invalid image probe altered the reader.");
            }
            if (!manual && automatic is null)
            {
                await AssertIgnored(probe);
                fixture.Connection.NativePcImageBatchChecked = true;
            }
            var expired = probe.DeepClone().AsObject();
            expired["created_ms"] = TelefonProtocolContract.Integer(probe["created_ms"]) - 11_000;
            expired["expires_ms"] = TelefonProtocolContract.Integer(probe["created_ms"]) - 1_000;
            await AssertIgnored(expired);
            await send(probe);
            await send(ping);
            var reply = await read();
            TestAssert.That(reply["kind"]?.GetValue<string>() == "media_support.hello" &&
                reply["body"]?["feature"]?.GetValue<string>() == "pc_image_batch_v3" &&
                TelefonProtocolContract.Integer(reply["expires_ms"]) <= TelefonProtocolContract.Integer(probe["expires_ms"]),
                $"The original Windows reader did not negotiate Format 3 photo output; first reply: {reply["type"]}.");
            var ack = await read();
            TestAssert.That(JsonNode.DeepEquals(ack["message_id"], probe["message_id"]) &&
                ack["status"]?.GetValue<string>() == "accepted", "The image probe did not receive its own ACK.");
            ping["type"] = "pong";
            TestAssert.That(JsonNode.DeepEquals(ping, await read()) &&
                fixture.Connection.CapturePrivatePcImageDiscovery() is null &&
                coordinator.NativeMediaUiStatus(remote)["send_consent"] is null,
                "The image lane projected SEND before both support receipts.");
            await send(new JsonObject { ["type"] = "ack", ["message_id"] = reply["message_id"]!.DeepClone(),
                ["status"] = "accepted", ["error"] = "none" });
            ping["type"] = "ping";
            await send(ping);
            ping["type"] = "pong";
            TestAssert.That(JsonNode.DeepEquals(ping, await read()), "The image lane did not remain on the original reader.");
            var witness = fixture.Connection.CapturePrivatePcImageDiscovery();
            TestAssert.That(witness?.Invoke() == true && fixture.Connection.PrivateMediaSettingsMatched &&
                !fixture.Store.ReadNativeMediaSendConsent(remote).Explicit,
                "The distinct image ACK was not scoped to discovery on this original session.");
            ping["type"] = "ping";
            await send(probe);
            await send(ping);
            ping["type"] = "pong";
            TestAssert.That(JsonNode.DeepEquals(ping, await read()) && witness?.Invoke() == true,
                "A repeated image probe renewed or retired the original witness.");
            TestAssert.That(fixture.Store.OutboxMessage(remote, reply["message_id"]!.GetValue<string>()) is null &&
                !fixture.Store.ReceivedMatches(remote, probe), "An image support handshake entered durable storage.");
            if (manual) await DeviceFileOriginalImagesTests.VerifyManualAsync(fixture, coordinator, read, send);
            if (automatic is not null) await VerifyPcImageAutomaticExport(fixture, automatic, read, send, control, heartbeat);
            fixture.Connection.Dispose();
            TestAssert.That(witness?.Invoke() != true, "A disconnected reader retained image discovery.");
        }
        finally { online.Remove(remote); }
    }

    private static async Task VerifyPcImageAutomaticExport(PhoneCameraParentTests.Fixture fixture, TelefonCoordinator coordinator,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send, Func<string, JsonObject, Task> control, Func<Task> heartbeat)
    {
        var peer = fixture.Peer.Id;
        var pcReceive = fixture.Store.ChangeNativeMediaReceiveConsent(peer,
            fixture.Store.ReadNativeMediaReceiveConsent(peer).Version, granted: false);
        var view = coordinator.NativeMediaUiStatus(peer);
        var sendVersion = view["send_consent"]!["version"]!.GetValue<string>();
        var allowed = coordinator.ConfirmNativeMediaUiSendConsent(peer, sendVersion, true, false, () => true);
        var root = Path.Combine(fixture.Paths.Root, "deliberate-wlan-image-source");
        Directory.CreateDirectory(root);
        var originals = new Dictionary<string, byte[]> {
            ["first.png"] = DeviceFileSourceSendTests.PaddedPng(length: 128),
            ["second.png"] = DeviceFileSourceSendTests.PaddedPng(length: 256)
        };
        foreach (var (name, bytes) in originals) File.WriteAllBytes(Path.Combine(root, name), bytes);
        var selected = coordinator.ChooseNativeMediaCollectionFolder(peer, "images",
            allowed["collection_sources_version"]!.GetValue<string>(),
            current => { current(); return DeviceFileNativeDirectory.OpenExisting(root); });
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
        TestAssert.That(!fixture.HasUnexpectedFrame, "Manual photo settings or selecting a folder triggered a background run.");
        var timing = selected["shared_settings"]!["versions"]!["auto_mode"]!.GetValue<string>();
        await coordinator.ChangeNativeMediaUiSharedSettingAsync(peer, "auto_mode", JsonValue.Create("wifi")!, timing);
        var proposal = await read();
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
        TestAssert.That(!fixture.HasUnexpectedFrame, "An unacknowledged photo WLAN choice started a pass.");
        await send(new JsonObject { ["type"] = "ack", ["message_id"] = proposal["message_id"]!.DeepClone(),
            ["status"] = "accepted", ["error"] = "none" });
        await heartbeat();
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
        TestAssert.That(!fixture.HasUnexpectedFrame, "A photo WLAN ACK without the matching echo started a pass.");
        await control(MediaSyncSettings.Kind, proposal["body"]!.AsObject());
        await heartbeat();
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
        TestAssert.That(fixture.HasUnexpectedFrame, "Confirmed WLAN photo settings did not prepare SEND with settings closed.");
        var packet = DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(packet.Grants.SendFiles && !packet.Grants.ReceiveFiles && fixture.Store.NativeMediaSourceHistory(peer).Count == 0,
            "The photo background setup did not wait for independent phone RECEIVE.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(230));
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token);
        var waiting = coordinator.NativeMediaUiStatus(peer);
        TestAssert.That(!fixture.HasUnexpectedFrame && waiting["automatic_phase"]?.GetValue<string>() == "waiting_for_phone" &&
            waiting["automatic_busy"]?.GetValue<bool>() == false && waiting["automatic"]?.GetValue<bool>() == true &&
            fixture.Store.NativeMediaSourceHistory(peer).Count == 0 &&
            fixture.Store.ReadNativeMediaReceiveConsent(peer) == pcReceive,
            "Waiting for photo RECEIVE created a source or depended on PC RECEIVE.");
        var identity = fixture.Store.ReadFileIdentity();
        var phone = new NativeFileControlIdentity(peer, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
        var desktop = new NativeFileControlPeer(identity.DeviceId, identity.IdentitySha256, new object(),
            true, true, true, true, true, fixture.Peer.FilePairingEpoch);
        var phoneGrant = new NativeLocalFileGrant(new(1, new string('a', 64), false, true), new object(), true);
        using var controls = new NativeFileControlSession(phone, () => desktop, () => phoneGrant);
        controls.ObserveRemote(packet, desktop);
        var echoed = controls.Packet();
        controls.MarkSent(echoed);
        await send(DeviceFileControlEnvelope.Create(echoed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        controls.ObserveRemote(DeviceFileControlEnvelope.Validate(await read().WaitAsync(deadline.Token),
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), desktop);
        await heartbeat();
        // Native preparation also does synchronous file I/O. Keep the
        // encrypted phone reader servicing heartbeats while it runs.
        var pass = Task.Run(() => coordinator.RunNativeMediaAutomaticOnceAsync(peer, deadline.Token), deadline.Token);
        await DeviceFileOriginalImagesTests.VerifyTransferAsync(fixture, read, send, false, originals, root, pass, deadline, controls);
        var retained = fixture.Store.NativeMediaSourceHistory(peer).Single();
        await coordinator.RunNativeMediaAutomaticOnceAsync(peer, CancellationToken.None);
        TestAssert.That(fixture.Store.NativeMediaSourceHistory(peer).Single() == retained && !fixture.HasUnexpectedFrame &&
            fixture.Store.ReadNativeMediaReceiveConsent(peer) == pcReceive,
            "The same WLAN photo setting exported twice or changed PC RECEIVE.");
    }

    private static async Task VerifyFirstReceiveEntry(PhoneCameraParentTests.Fixture fixture, TelefonConnection connection,
        string remote, string mediaType, bool transfer, bool useDefaults, string? automaticScenario, Func<Task<JsonObject>> read, Func<JsonObject, Task> send,
        Func<TelefonCoordinator, Dictionary<string, TelefonConnection>,
            Func<Func<Task<JsonObject>>, Func<JsonObject, Task>, TelefonConnection, Task>, Task>? reconnect)
    {
        var automatic = automaticScenario is not null;
        using var coordinator = new TelefonCoordinator(fixture.Paths, (_, _) => Task.CompletedTask, dataStore: fixture.Store, localOnly: true);
        var book = new PersonalActorNativeSaveHost(Path.Combine(fixture.Paths.Root, "first-receive-book"),
            "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = book.Snapshot;
        coordinator.NativeSavedBook = book.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(remote, connection);
        var generated = new Dictionary<string, NativeMediaDestination>();
        try
        {
            var videoOnly = mediaType == "video";
            var mixed = mediaType == "mixed";
            var readType = mixed ? "video" : mediaType;
            var before = fixture.Store.ReadNativeMediaReceiveConsent(remote);
            var state = coordinator.NativeMediaUiStatus(remote);
            TestAssert.That(state[automatic ? "automatic_receive_setup" : "manual_receive_setup"]?.GetValue<bool>() == true &&
                state["shared_start_version"] is not null,
                $"The original encrypted WLAN reader agreed but did not expose a first-receive UI action for {mediaType}.");
            TestAssert.That(!before.Granted && fixture.Store.ReadNativeMediaReceiveConsent(remote) == before &&
                fixture.Store.ReadNativeMediaPreferences(remote).Version is null &&
                fixture.Store.ReadNativeMediaDestination(remote, "images") is null &&
                fixture.Store.ReadNativeMediaDestination(remote, "video") is null,
                "Viewing agreed settings granted RECEIVE or opened a destination.");
            if (automatic)
            {
                await coordinator.RunNativeMediaAutomaticOnceAsync(remote, CancellationToken.None);
                TestAssert.That(!fixture.HasUnexpectedFrame && fixture.Store.ReadNativeMediaReceiveConsent(remote) == before &&
                    fixture.Store.ReadNativeMediaPreferences(remote).Version is null, "A shared Wi-Fi choice started background work before explicit setup.");
            }
            if (mediaType == "settings")
            {
                var version = state["shared_settings"]!["versions"]!["enabled"]!.GetValue<string>();
                TestAssert.That(state["original_settings_editable"]?.GetValue<bool>() == true, "Original shared settings are read-only.");
                var changed = await coordinator.ChangeNativeMediaUiSharedSettingAsync(remote, "enabled", JsonValue.Create(false)!, version);
                var frame = await read();
                TestAssert.That(frame["kind"]?.GetValue<string>() == MediaSyncSettings.Kind &&
                    !MediaSyncSettings.Configured(frame["body"]!.AsObject())["enabled"]!.GetValue<bool>() &&
                    changed["shared_start_version"] is null && !connection.PrivateMediaSettingsMatched,
                    "Switching OFF did not send only the shared choice or left the previous agreement usable.");
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(
                    coordinator.ChangeNativeMediaUiSharedSettingAsync(remote, "enabled", JsonValue.Create(true)!, version),
                    "A stale field version overwrote the OFF decision.");
                await send(new JsonObject { ["type"] = "ack", ["message_id"] = frame["message_id"]!.DeepClone(),
                    ["status"] = "accepted", ["error"] = "none" });
                var echo = Message(MediaSyncSettings.Kind, frame["body"]!.AsObject());
                await send(echo);
                var reply = await read();
                TestAssert.That(JsonNode.DeepEquals(reply["message_id"], echo["message_id"]) && reply["status"]?.GetValue<string>() == "accepted",
                    "The original reader did not acknowledge the matching echo.");
                var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
                await send(ping);
                TestAssert.That((await read())["type"]?.GetValue<string>() == "pong" &&
                    connection.PrivateMediaSettingsMatched && coordinator.NativeMediaUiStatus(remote)["shared_start_version"] is null &&
                    fixture.Store.ReadNativeMediaReceiveConsent(remote) == before && fixture.Store.OutboxMessage(remote, frame["message_id"]!.GetValue<string>()) is null &&
                    fixture.Store.NativeMediaReceiveHistory(remote).Count == 0,
                    "Converged OFF changed local RECEIVE, queued legacy traffic or started a native worker.");
                return;
            }
            var targets = new Dictionary<string, NativeMediaDestination>();
            var expectedPaths = new Dictionary<string, string>();
            foreach (var kind in mixed ? new[] { "images", "video" } : new[] { mediaType })
            {
                if (useDefaults)
                {
                    var parent = Environment.GetFolderPath(kind == "images" ? Environment.SpecialFolder.MyPictures : Environment.SpecialFolder.MyVideos);
                    var expected = Path.Combine(parent, fixture.Peer.Name + (kind == "images" ? "-Fotos" : "-Videos"));
                    var shown = state[kind == "images" ? "pictures" : "video_destination"];
                    TestAssert.That(Path.IsPathFullyQualified(parent) && Directory.Exists(parent) &&
                        shown?["display_path"]?.GetValue<string>() == expected && shown?["default"]?.GetValue<bool>() == true &&
                        !Directory.Exists(expected), "Viewing settings created or misreported the native reserved test default.");
                    expectedPaths.Add(kind, expected);
                    continue;
                }
                var target = Path.Combine(fixture.Paths.Root, "native-first-" + kind);
                Directory.CreateDirectory(target);
                using var root = DeviceFileNativeDirectory.OpenExistingForReceive(target);
                targets.Add(kind, fixture.Store.SetNativeMediaDestination(remote, kind, null, root));
            }
            var request = new JsonObject { ["cmd"] = "telefon_medien", ["device_id"] = remote,
                ["requestId"] = Guid.NewGuid().ToString("D"), ["action"] = "sync_shared", ["version"] = state["shared_start_version"]!.DeepClone() };
            var unbound = request.DeepClone().AsObject(); unbound["version"] = new string('0', 64);
            TestAssert.Throws<InvalidDataException>(() => coordinator.RunNativeMediaUiSharedAsync(
                NativeMediaUiRequest.Parse(unbound), CancellationToken.None), "A forged start version wrote an initial RECEIVE grant.");
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(transfer ? 45 : 8));
            var pass = coordinator.RunNativeMediaUiSharedAsync(NativeMediaUiRequest.Parse(request), stop.Token);
            var localIdentity = fixture.Store.ReadFileIdentity();
            var phoneIdentity = new NativeFileControlIdentity(remote, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
            var desktop = new NativeFileControlPeer(localIdentity.DeviceId, localIdentity.IdentitySha256, new object(),
                true, true, true, true, true, fixture.Peer.FilePairingEpoch);
            var phoneGrant = new NativeLocalFileGrant(new(1, new string('a', 64), false, false), new object(), true);
            using var phoneControls = new NativeFileControlSession(phoneIdentity, () => desktop, () => phoneGrant);
            var first = DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            TestAssert.That(first.Grants.ReceiveFiles && !first.Grants.SendFiles && !pass.IsCompleted,
                "First local action did not send the positive RECEIVE choice and wait for the reader.");
            foreach (var (kind, path) in expectedPaths)
            {
                var actual = fixture.Store.ReadNativeMediaDestination(remote, kind);
                TestAssert.That(actual is not null && string.Equals(actual.NativePath, path, StringComparison.OrdinalIgnoreCase),
                    "The first native action did not bind the displayed OS default directory.");
                targets.Add(kind, actual!);
                generated.Add(kind, actual!);
            }
            phoneControls.ObserveRemote(first, desktop);
            async Task Echo(bool expectReply = true)
            {
                var packet = phoneControls.Packet(); phoneControls.MarkSent(packet);
                await send(DeviceFileControlEnvelope.Create(packet, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
                if (expectReply)
                    phoneControls.ObserveRemote(DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), desktop);
            }
            await Echo();
            var status = await read();
            TestAssert.That(status["body"]?["operation"]?.GetValue<string>() == "status", "First start did not check the real phone policy.");
            await send(Message(DeviceFileSources.ResultKind, new JsonObject { ["format"] = 1,
                ["request_id"] = status["message_id"]!.DeepClone(), ["operation"] = "status", ["version"] = new string('c', 64),
                ["revision"] = 0, ["enabled"] = false, ["associated"] = false, ["repair_pending"] = false,
                ["kinds"] = new JsonArray(), ["videos"] = new JsonObject { ["enabled"] = false, ["revision"] = 0 } }));
            var configure = await read();
            TestAssert.That(configure["body"]?["operation"]?.GetValue<string>() == (videoOnly ? "configure_videos" : "configure"),
                "Absent phone policy did not yield the explicitly selected SEND.");
            var configured = DeviceFileConnectionCommandsTests.Configuration(configure, videoOnly);
            if (videoOnly) configured["body"]!["enabled"] = false;
            await send(configured);
            phoneGrant = new(new(2, new string('b', 64), true, false), phoneGrant.Owner, true);
            await Echo();
            if (videoOnly || mixed)
            {
                var rearm = await read();
                TestAssert.That(rearm["body"]?["operation"]?.GetValue<string>() == "configure_videos" &&
                    rearm["body"]?["expected_version"]?.GetValue<string>() == configured["body"]!["version"]!.GetValue<string>(),
                    "A newly echoed video grant did not rearm the original phone owner.");
                var confirmation = DeviceFileConnectionCommandsTests.Configuration(rearm, video: true);
                if (videoOnly) confirmation["body"]!["enabled"] = false;
                else
                {
                    confirmation["body"]!["version"] = new string('e', 64);
                    confirmation["body"]!["revision"] = 3;
                }
                await send(confirmation);
                configured = confirmation;
            }
            var sourceVersion = configured["body"]!["version"]!.GetValue<string>();
            async Task<JsonObject> Discover(string kind, bool canRead)
            {
                var discover = await read();
                TestAssert.That(discover["body"]?["operation"]?.GetValue<string>() == "discover" &&
                    (discover["body"]?["media_type"]?.GetValue<string>() ?? "images") == kind,
                    "A transfer or wrong discovery came before the next typed READ check: " + discover);
                var catalog = DeviceFileConnectionCommandsTests.Catalog(discover, kind == "video");
                var page = catalog["body"]!["page"]!.AsObject();
                catalog["body"]!["version"] = sourceVersion;
                if (!canRead) { page["coverage"] = "none"; page["albums"] = new JsonArray(); }
                await send(catalog);
                return page;
            }
            async Task RecheckExistingSources()
            {
                var freshStatus = await read();
                TestAssert.That(freshStatus["body"]?["operation"]?.GetValue<string>() == "status", "A new pass did not recheck SEND.");
                var reported = configured.DeepClone().AsObject();
                reported["message_id"] = Guid.NewGuid().ToString("D");
                reported["body"]!["request_id"] = freshStatus["message_id"]!.DeepClone();
                reported["body"]!["operation"] = "status";
                await send(reported);
                var rearm = await read();
                TestAssert.That(rearm["body"]?["operation"]?.GetValue<string>() == "configure_videos" &&
                    rearm["body"]?["expected_version"]?.GetValue<string>() == sourceVersion,
                    "A new pass did not rearm the already-positive video grant.");
                var confirmed = configured.DeepClone().AsObject();
                confirmed["message_id"] = Guid.NewGuid().ToString("D");
                confirmed["body"]!["request_id"] = rearm["message_id"]!.DeepClone();
                await send(confirmed);
            }
            async Task TransferMixed(JsonObject images)
            {
                await TransferFirstOriginal(images, "images", "first.png", DeviceFileSourceSendTests.PaddedPng(),
                    targets["images"], remote, localIdentity.DeviceId, sourceVersion, read, send);
                var video = await Discover("video", canRead: true);
                await TransferFirstOriginal(video, "video", "first.mp4", DeviceFileVideoPreviewTests.Fixture(),
                    targets["video"], remote, localIdentity.DeviceId, sourceVersion, read, send);
            }
            bool BothOriginalsFinished(TelefonConnection active) =>
                fixture.Store.NativeMediaReceiveHistory(remote).Count == 2 &&
                fixture.Store.NativeMediaReceiveBudget(remote) == (2, 0, 0L) && active.CurrentNativeMediaSourceRun is null;
            var photoCatalog = mixed ? await Discover("images", canRead: true) : null;
            await Discover(readType, canRead: transfer);
            if (transfer)
            {
                Task completion = pass;
                if (automatic)
                {
                    TestAssert.That(await pass == "waiting" && !fixture.HasUnexpectedFrame &&
                        fixture.Store.ReadNativeMediaPreferences(remote) is { AutomaticWifi: true, OriginalAutomaticKey: not null } &&
                        fixture.Store.NativeMediaReceiveHistory(remote).Count == 0 &&
                        coordinator.NativeMediaUiStatus(remote)["shared_start_version"] is null,
                        "Wi-Fi setup started a content run before arming or failed to store the completed native choice.");
                    if (reconnect is not null)
                    {
                        await reconnect(coordinator, online, async (freshRead, freshSend, freshConnection) =>
                        {
                            read = freshRead;
                            send = freshSend;
                            var freshDesktop = desktop with { Owner = new object() };
                            var freshGrant = new NativeLocalFileGrant(phoneGrant.Grants, new object(), true);
                            using var freshControls = new NativeFileControlSession(phoneIdentity, () => freshDesktop, () => freshGrant);
                            using var freshDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(45));
                            var background = coordinator.RunNativeMediaAutomaticOnceAsync(remote, freshDeadline.Token);
                            try
                            {
                                var firstFresh = DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                                TestAssert.That(firstFresh.Grants.ReceiveFiles, "The new reader did not publish its current protected RECEIVE choice.");
                                freshControls.ObserveRemote(firstFresh, freshDesktop);
                                var packet = freshControls.Packet(); freshControls.MarkSent(packet);
                                await send(DeviceFileControlEnvelope.Create(packet, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
                                freshControls.ObserveRemote(DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), freshDesktop);
                                await RecheckExistingSources();
                                var images = await Discover("images", canRead: true);
                                await Discover("video", canRead: true);
                                await TransferMixed(images);
                                await background;
                                TestAssert.That(BothOriginalsFinished(freshConnection),
                                    "The reconnected background pass did not finish both original transfers.");
                            }
                            finally
                            {
                                freshDeadline.Cancel();
                                try { await background; } catch (OperationCanceledException) { }
                            }
                        });
                        return;
                    }
                    completion = coordinator.RunNativeMediaAutomaticOnceAsync(remote, stop.Token);
                    var freshControl = DeviceFileControlEnvelope.Validate(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    phoneControls.ObserveRemote(freshControl, desktop);
                    await Echo(expectReply: false); // Phone SEND was already echoed; only desktop RECEIVE changed.
                    await RecheckExistingSources();
                    photoCatalog = await Discover("images", canRead: true);
                    await Discover("video", canRead: true);
                }
                await TransferMixed(photoCatalog!);
                await completion;
                TestAssert.That((automatic || await pass == "content_pass") && BothOriginalsFinished(connection),
                    "Mixed first receive did not close both source runs and finalize the original receipts.");
                return;
            }
            var readRequest = await read();
            TestAssert.That(readRequest["body"]?["operation"]?.GetValue<string>() == "request_read" &&
                (readRequest["body"]?["media_type"]?.GetValue<string>() ?? "images") == readType,
                "Missing OS READ was not surfaced for the selected type.");
            var permission = new JsonObject { ["format"] = 1,
                ["request_id"] = readRequest["message_id"]!.DeepClone(), ["operation"] = "request_read",
                ["version"] = configured["body"]!["version"]!.DeepClone(), ["state"] = "notification_posted" };
            if (readType == "video") permission["media_type"] = "video";
            var stopped = automaticScenario == "stop";
            if (stopped)
            {
                TestAssert.That(coordinator.StopNativeMediaAutomatic(remote), "Stop did not address the original Wi-Fi setup owner.");
                await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(pass, "Stopped Wi-Fi setup returned success.");
            }
            var permissionFrame = Message(DeviceFileSources.PermissionResultKind, permission);
            permissionFrame["expires_ms"] = readRequest["expires_ms"]!.DeepClone();
            await send(permissionFrame);
            TestAssert.That((stopped || await pass == "review") &&
                new[] { "images", "video" }.All(kind => fixture.Store.ReadNativeMediaDestination(remote, kind) == targets.GetValueOrDefault(kind)) &&
                fixture.Store.NativeMediaReceiveHistory(remote).Count == 0 &&
                targets.Keys.All(kind => !Directory.EnumerateFileSystemEntries(Path.Combine(fixture.Paths.Root, "native-first-" + kind)).Any()),
                "A missing READ decision yielded data I/O or altered a protected destination.");
            if (automatic)
            {
                await coordinator.RunNativeMediaAutomaticOnceAsync(remote, CancellationToken.None);
                TestAssert.That(!fixture.HasUnexpectedFrame &&
                    fixture.Store.ReadNativeMediaPreferences(remote) is { AutomaticWifi: false, OriginalAutomaticKey: null } &&
                    coordinator.NativeMediaUiStatus(remote)["automatic_receive_setup"]?.GetValue<bool>() == true,
                    "A missing typed READ permission armed a subsequent background run.");
            }
            if (stopped)
            {
                var ping = new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"),
                    ["sent_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
                await send(ping);
                TestAssert.That((await read())["type"]?.GetValue<string>() == "pong", "A stopped READ reply closed or reused the original reader.");
                var retry = request.DeepClone().AsObject();
                retry["requestId"] = Guid.NewGuid().ToString("D");
                retry["version"] = coordinator.NativeMediaUiStatus(remote)["shared_start_version"]!.DeepClone();
                var retryPass = coordinator.RunNativeMediaUiSharedAsync(NativeMediaUiRequest.Parse(retry), stop.Token);
                await RecheckExistingSources();
                await Discover("images", canRead: true);
                await Discover("video", canRead: true);
                TestAssert.That(await retryPass == "waiting" && fixture.Store.NativeMediaReceiveHistory(remote).Count == 0,
                    "Retry did not independently recheck both OS scopes before arming.");
            }
            var accepted = fixture.Store.ReadNativeMediaReceiveConsent(remote);
            coordinator.ChangeNativeMediaUiReceiveConsent(remote, accepted.Version, false);
            TestAssert.That(coordinator.NativeMediaUiStatus(remote)["shared_start_version"] is null &&
                !fixture.Store.ReadNativeMediaReceiveConsent(remote).Granted, "Local revocation left an enabled first-start path.");
        }
        finally
        {
            online.Remove(remote);
            foreach (var target in generated.Values)
            {
                using (var root = target.OpenNative()) _ = root.CurrentIdentity();
                Directory.Delete(target.NativePath, recursive: true);
            }
        }
    }

    private static async Task TransferFirstOriginal(JsonObject catalog, string kind, string name, byte[] data, NativeMediaDestination destination,
        string sender, string receiver, string version, Func<Task<JsonObject>> read, Func<JsonObject, Task> send)
    {
        async Task<JsonObject> Request(string operation)
        {
            var request = await read();
            TestAssert.That(request["body"]?["operation"]?.GetValue<string>() == operation &&
                (request["body"]?["media_type"]?.GetValue<string>() ?? "images") == kind,
                $"Expected {kind} {operation} but got {request}.");
            return request;
        }
        var run = Guid.NewGuid().ToString("D");
        JsonObject Reply(JsonObject request, string phase)
        {
            var reply = DeviceFileConnectionRunsTests.Reply(request, run, phase, batchEnd: true);
            reply["body"]!["version"] = version;
            return reply;
        }
        var batch = await Request("batch_run");
        var album = catalog["albums"]![0]!;
        TestAssert.That(JsonNode.DeepEquals(batch["body"]!["catalog_id"], catalog["catalog_id"]) &&
            JsonNode.DeepEquals(batch["body"]!["album_id"], album["album_id"]), "The source used a stale or wrong-kind catalog.");
        await send(Reply(batch, "snapshot_ready"));
        var hash = Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();
        var file = new DeviceManifestFile(new string('1', 32), name, data.Length, hash);
        var manifest = new DeviceFileManifest(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), sender, receiver, [file], data.Length);
        var epoch = new string(kind == "video" ? 'c' : 'b', 64);
        var page = DeviceFileConnectionRunsTests.Media(await Request("media_page"), run, epoch: epoch);
        page["body"]!["version"] = version;
        page["body"]!["page"]!["total_files"] = 1;
        page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
        page["body"]!["page"]!["entries"]![0]!["file_id"] = file.Id;
        await send(page);
        var offerRequest = await Request("offer_run");
        var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        offer["expires_ms"] = offerRequest["expires_ms"]!.DeepClone();
        await send(offer);
        var offered = Reply(offerRequest, "snapshot_ready");
        offered["body"]!["offer_id"] = offer["message_id"]!.DeepClone();
        offered["body"]!["manifest_sha256"] = manifest.Fingerprint;
        await send(offered);
        var acceptance = DeviceFileAcceptanceEnvelope.Parse(await read(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(acceptance.DestinationToken == destination.DestinationToken &&
            acceptance.ManifestSha256 == manifest.Fingerprint, "Acceptance did not bind the selected kind's protected root and original manifest.");
        for (var offset = 0; offset < data.Length; offset += DeviceFileManifest.ChunkBytes)
        {
            var chunk = await read();
            var parsed = DeviceFileChunkEnvelope.ParseRequest(chunk, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            TestAssert.That(parsed.FileId == file.Id && parsed.ChunkIndex == offset / DeviceFileManifest.ChunkBytes, "Unexpected original chunk request.");
            await send(DeviceFileConnectionReceiveTests.Chunk(chunk, data.AsSpan(offset, Math.Min(data.Length - offset, DeviceFileManifest.ChunkBytes)).ToArray()));
        }
        var saved = await read();
        TestAssert.That(saved["kind"]?.GetValue<string>() == DeviceFileSavedEnvelope.Kind, $"Expected {kind} Saved but got {saved}.");
        _ = DeviceFileSavedEnvelope.Parse(saved, manifest, acceptance, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        foreach (var operation in new[] { "cancel_run", "end_run", "end_album" })
            await send(Reply(await Request(operation), "canceled_held"));
        var folder = new NativeMediaAlbumContext(epoch, album["display_name"]!.GetValue<string>()).Folder;
        TestAssert.That(File.ReadAllBytes(Path.Combine(destination.NativePath, folder, name)).SequenceEqual(data),
            $"Published {kind} bytes differed from the original.");
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
            TelefonConnection Connect(bool supported = true, MemoryStream? wire = null, string transport = "wifi") =>
                new TelefonConnection(peer, wire ?? new MemoryStream(), new byte[16], new byte[72], store, Receive, CancellationToken.None, transport)
                { SharedLocalCapabilities = () => (supported ? negotiated : legacyCapabilities)["items"]!.DeepClone().AsObject() };
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

                using var bluetoothWire = new MemoryStream();
                using (var bluetooth = Connect(wire: bluetoothWire, transport: "bluetooth"))
                {
                    await bluetooth.HandlePlainAsync(caps); await bluetooth.HandlePlainAsync(grants); await bluetooth.HandlePlainAsync(own);
                    await bluetooth.HandlePlainAsync(Message(SharedSyncSettings.Kind, echoed));
                    foreach (var part in nextParts) await bluetooth.HandlePlainAsync(Message(PhoneContentScope.Kind, part));
                    TestAssert.That(JsonNode.DeepEquals(next, bluetooth.CurrentContentScope(PhoneContentScope.Reference(next))),
                        "Bluetooth fixture did not establish fresh controls and membership.");
                    var automatic = request.DeepClone().AsObject();
                    var autoRunId = Guid.NewGuid().ToString("D");
                    automatic["run_id"] = autoRunId;
                    automatic["trigger"] = "auto_wifi";
                    var automaticBody = PhoneContentScope.Wrap("personal_sync.request", automatic, next);
                    var bluetoothRequest = Message(PhoneContentScope.DataKind, automaticBody);
                    await bluetooth.HandlePlainAsync(bluetoothRequest);
                    var bluetoothAck = (await DrainAsync(bluetoothWire)).Single(value =>
                        JsonNode.DeepEquals(value["message_id"], bluetoothRequest["message_id"]));
                    TestAssert.That(bluetoothAck["status"]?.GetValue<string>() == "rejected" &&
                        bluetoothAck["error"]?.GetValue<string>() == "not_granted", "Bluetooth accepted a WLAN-only request.");
                    var checkedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    TestAssert.That(runs.LoadRun(peer.Id, autoRunId, checkedAt) is null &&
                        runs.ScopedRunReference(peer.Id, peer.PublicKey, autoRunId, checkedAt) is null,
                        "Rejected Bluetooth WLAN-only request left a durable scoped run.");

                    var wifiRequest = Message(PhoneContentScope.DataKind, automaticBody);
                    await scoped.HandlePlainAsync(wifiRequest);
                    var wifiAck = (await DrainAsync(scopeWire)).Single(value => JsonNode.DeepEquals(value["message_id"], wifiRequest["message_id"]));
                    TestAssert.That(wifiAck["status"]?.GetValue<string>() == "accepted" &&
                        runs.LoadRun(peer.Id, autoRunId, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())?.Policy == "wifi_only",
                        "The same request could not start on WLAN with its WLAN-only policy.");
                }

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
