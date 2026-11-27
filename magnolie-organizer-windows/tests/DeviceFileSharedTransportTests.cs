using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSharedTransportTests
{
    private static void Identity(DeviceFileConnectionMetadataTests.Fixture f)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
    }
    private static JsonObject Message(JsonObject body)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = MediaSyncSettings.Kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body.DeepClone() };
    }
    private static JsonObject Ack(string id) => new() { ["type"] = "ack", ["message_id"] = id, ["status"] = "accepted", ["error"] = "none" };
    private static string QueuedId(DeviceFileConnectionMetadataTests.Fixture f)
    {
        using var db = f.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT message_id FROM outbox WHERE kind=$kind"; read.Parameters.AddWithValue("$kind", MediaSyncSettings.Kind);
        return (string)read.ExecuteScalar()!;
    }
    internal static async Task Seed(DeviceFileConnectionMetadataTests.Fixture f, bool supported = true)
    {
        Identity(f);
        f.Connection.SharedLocalCapabilities = () => {
            var capabilities = TelefonProtocolContract.DesktopCapabilities()["items"]!.DeepClone().AsObject();
            capabilities["device_status"]!["versions"]!.AsArray().Add(23); return capabilities;
        };
        foreach (var kind in new[] { "capabilities.update", "grants.update", "personal_sync.settings" })
        {
            var message = f.Message(kind);
            if (kind == "capabilities.update" && supported) message["body"]!["items"]!["device_status"]!["versions"]!.AsArray().Add(23);
            await f.Connection.HandlePlainAsync(message);
        }
        TestAssert.That(f.Connection.MediaSharedControlsReady == supported, "Shared controls ignored current native metadata/capability.");
    }

    internal static async Task MatchAsync(DeviceFileConnectionMetadataTests.Fixture f)
    {
        await f.Connection.SendMediaSharedSettingsAsync();
        var body = f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)!;
        await f.Connection.HandlePlainAsync(Message(body));
        await f.Connection.HandlePlainAsync(Ack(QueuedId(f)));
        TestAssert.That(f.Connection.MediaSharedSettingsReady, "Current media fixture failed actual secure matching.");
    }

    internal static async Task LegacyManualReceivePreviewAsync()
    {
        foreach (var videoOnly in new[] { false, true })
        {
            using var f = new DeviceFileConnectionMetadataTests.Fixture();
            await Seed(f);
            void Set(string field, JsonNode value) => f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey,
                field, value, f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, field));
            Set("enabled", JsonValue.Create(true)!);
            Set("direction", JsonValue.Create("phone_to_pc")!);
            if (videoOnly)
            {
                Set("photos_enabled", JsonValue.Create(false)!);
                Set("videos_enabled", JsonValue.Create(true)!);
            }
            await MatchAsync(f);
            using var coordinator = new TelefonCoordinator(f.Paths, (_, _) => Task.CompletedTask, dataStore: f.Store, localOnly: true);
            var book = new PersonalActorNativeSaveHost(Path.Combine(f.Paths.Root, "manual-first-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
            coordinator.NativeProducerBook = book.Snapshot;
            coordinator.NativeSavedBook = book.Saved;
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online.Add(f.Peer.Id, f.Connection);
            var before = f.Stream.Length;
            var status = coordinator.NativeMediaUiStatus(f.Peer.Id);
            TestAssert.That(status["shared_matched"]!.GetValue<bool>() && !f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id).Granted &&
                f.Store.ReadNativeMediaPreferences(f.Peer.Id).Version is null && f.Stream.Length == before,
                "Viewing an agreed choice changed the local RECEIVE policy or emitted data.");
            TestAssert.That(status["shared_start_version"] is null,
                "Legacy agreement exposed a first grant reserved for the original reader.");
        }
    }

    internal static async Task FirstReceiveConsentAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture();
        await Seed(f);
        var peer = f.Peer.Id;
        var absent = f.Store.ReadNativeMediaReceiveConsent(peer);
        var before = f.Store.ReadNativeMediaPreferences(peer);
        TestAssert.That(absent.CanInitializeFirstReceive(before), "A genuinely absent receive policy was not eligible.");
        var validations = 0;
        TestAssert.Throws<OperationCanceledException>(() => f.Store.InitializeNativeMediaFirstReceive(peer, absent.Version, () =>
        {
            if (++validations == 2) throw new OperationCanceledException("synthetic book change before commit");
        }), "A changed book did not abort the first receive commit.");
        TestAssert.That(f.Store.ReadNativeMediaReceiveConsent(peer) == absent, "A concurrent change left a receive grant behind.");
        validations = 0;
        var accepted = f.Store.InitializeNativeMediaFirstReceive(peer, absent.Version, () => validations++);
        TestAssert.That(accepted.Granted && accepted.Explicit && accepted.Version != absent.Version && validations == 2 &&
            f.Store.ReadNativeMediaReceiveConsent(peer) == accepted && f.Store.ReadNativeMediaPreferences(peer) == before &&
            f.Store.ReadNativeMediaDestination(peer, "images") is null && f.Store.ReadNativeMediaDestination(peer, "video") is null &&
            f.Store.NativeMediaReceiveHistory(peer).Count == 0, "The first CAS failed readback or created targets or a media job.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.InitializeNativeMediaFirstReceive(peer, absent.Version, () => { }),
            "A stale native choice was accepted.");
        var off = f.Store.ChangeNativeMediaReceiveConsent(peer, accepted.Version, false);
        TestAssert.Throws<InvalidDataException>(() => f.Store.InitializeNativeMediaFirstReceive(peer, off.Version, () => { }),
            "Explicit OFF was treated as absence.");
        TestAssert.That(f.Store.ReadNativeMediaReceiveConsent(peer) == off, "A rejected retry altered the OFF policy.");

        using var legacy = new DeviceFileConnectionMetadataTests.Fixture();
        await Seed(legacy);
        var legacyPeer = legacy.Peer.Id;
        var enabled = legacy.Store.SetNativeMediaPreferences(legacyPeer, null, true, false, false);
        var priorOff = legacy.Store.SetNativeMediaPreferences(legacyPeer, enabled.Version, false, false, false);
        var priorChoice = legacy.Store.ReadNativeMediaReceiveConsent(legacyPeer);
        TestAssert.That(!priorChoice.Explicit && !priorChoice.Granted && !priorChoice.CanInitializeFirstReceive(priorOff),
            "A persisted legacy OFF looked like an absent policy.");
        TestAssert.Throws<InvalidDataException>(() => legacy.Store.InitializeNativeMediaFirstReceive(legacyPeer, priorChoice.Version, () => { }),
            "A persisted legacy OFF re-enabled receiving.");
        TestAssert.That(legacy.Store.ReadNativeMediaReceiveConsent(legacyPeer) == priorChoice, "The legacy OFF policy changed.");
    }

    internal static async Task MatchedAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); await Seed(f);
        var beforeGrants = f.Store.LocalGrants().DeepClone(); var beforePersonal = f.Store.PersonalSettings(f.Peer.Id);
        var version = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled");
        var local = f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "enabled", JsonValue.Create(true)!, version);
        await f.Connection.SendMediaSharedSettingsAsync();
        TestAssert.That(!f.Connection.MediaSharedSettingsReady, "Sending alone claimed matched settings.");
        var actor = local["settings"]!["enabled"]!.AsObject().Single().Key;
        var remote = MediaSyncSettings.Merge(MediaSyncSettings.Create(f.Peer.Id), local, f.Peer.Id, actor);
        await f.Connection.HandlePlainAsync(Message(remote));
        var persisted = f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)!;
        await f.Connection.HandlePlainAsync(Message(persisted));
        TestAssert.That(!f.Connection.MediaSharedSettingsReady, "Peer echo without actual matching outbound ACK claimed readiness.");
        await f.Connection.HandlePlainAsync(Ack(Guid.NewGuid().ToString("D")));
        TestAssert.That(!f.Connection.MediaSharedSettingsReady, "Foreign ACK matched media settings.");
        var acceptedId = QueuedId(f);
        await f.Connection.HandlePlainAsync(Ack(acceptedId));
        TestAssert.That(f.Connection.MediaSharedSettingsReady && JsonNode.DeepEquals(beforeGrants, f.Store.LocalGrants()) &&
            beforePersonal == f.Store.PersonalSettings(f.Peer.Id) && f.Store.ReadNativeMediaPreferences(f.Peer.Id).Version is null,
            "Current bilateral matching failed or manufactured rights/personal/native policy.");
        var capabilities = f.Message("capabilities.update", revision: 2);
        capabilities["body"]!["items"]!["device_status"]!["versions"]!.AsArray().Add(23);
        await f.Connection.HandlePlainAsync(capabilities);
        await f.Connection.HandlePlainAsync(Ack(acceptedId));
        TestAssert.That(f.Connection.MediaSharedControlsReady && !f.Connection.MediaSharedSettingsReady,
            "A metadata renewal or replayed old ACK revived historical matching.");
        await f.Connection.HandlePlainAsync(Message(persisted));
        await f.Connection.HandlePlainAsync(Ack(QueuedId(f)));
        TestAssert.That(f.Connection.MediaSharedSettingsReady, "Fresh settings exchange after metadata renewal failed.");
        using var coordinator = new TelefonCoordinator(f.Paths, (_, _) => Task.CompletedTask, dataStore: f.Store, localOnly: true);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Paths.Root, "shared-media-ui-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Peer.Id, f.Connection);
        var ui = coordinator.NativeMediaUiStatus(f.Peer.Id);
        TestAssert.That(ui["shared_matched"]!.GetValue<bool>() && !ui["receive_consent"]!["granted"]!.GetValue<bool>(),
            "Native UI confused a matched remote preference with local receive permission.");
        TestAssert.Throws<InvalidDataException>(() => coordinator.RequireNativeMediaUiDestinationConsent(f.Peer.Id),
            "A browser folder action bypassed the unchecked local receive right.");
        TestAssert.Throws<InvalidDataException>(() => coordinator.EnsureNativeMediaDefaultDestination(f.Peer.Id, "images",
            Path.Combine(f.Paths.Root, "must-not-open")), "Default folder IO began before local receive consent.");
        var localRights = coordinator.ChangeNativeMediaUiReceiveConsent(f.Peer.Id, ui["receive_consent"]!["version"]!.GetValue<string>(), true);
        var projected = f.Store.ReadNativeMediaPreferences(f.Peer.Id);
        TestAssert.That(localRights["receive_consent"]!["granted"]!.GetValue<bool>() && projected.PhotosEnabled && !projected.VideosEnabled &&
            f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") is null && f.Store.ReadNativeMediaDestination(f.Peer.Id, "video") is null,
            "Matched intent plus explicit local rights failed projection or created a destination without a run.");
        TestAssert.That(!projected.GrantsReceiveAuthority && f.Store.NativeMediaReceiveHistory(f.Peer.Id).Count == 0,
            "Policy projection fabricated native transport authority or a receive job.");
        var edited = await coordinator.ChangeNativeMediaUiSharedSettingAsync(f.Peer.Id, "collection_mode", JsonValue.Create("entire_collection")!,
            ui["shared_settings"]!["versions"]!["collection_mode"]!.GetValue<string>());
        TestAssert.That(edited["shared_settings"]!["values"]!["collection_mode"]!.GetValue<string>() == "entire_collection" &&
            !edited["shared_matched"]!.GetValue<bool>() && f.Store.ReadNativeMediaPreferences(f.Peer.Id) == projected,
            "Native UI field edit failed to persist or incorrectly treated sending as a matched/started run.");
        var nextVersion = f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "videos_enabled");
        f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "videos_enabled", JsonValue.Create(true)!, nextVersion);
        TestAssert.That(!f.Connection.MediaSharedSettingsReady, "A local edit reused an old matched snapshot.");
        f.Connection.Dispose(); TestAssert.That(!f.Connection.MediaSharedSettingsReady, "Closed channel retained matched settings.");
    }

    internal static async Task GuardsAsync()
    {
        using (var old = new DeviceFileConnectionMetadataTests.Fixture())
        {
            await Seed(old, supported: false);
            await old.Connection.HandlePlainAsync(Message(MediaSyncSettings.Create(old.Peer.Id)));
            TestAssert.That(old.Store.ReadNativeMediaSharedSettings(old.Peer.Id, old.Peer.PublicKey) is null &&
                !old.Connection.MediaSharedSettingsReady, "Old discovery version admitted media intent.");
        }
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); await Seed(f);
        f.Stream.Fail = true;
        try { await f.Connection.HandlePlainAsync(Message(MediaSyncSettings.Create(f.Peer.Id))); throw new Exception("Failed secure ACK was ignored."); }
        catch (IOException) { }
        TestAssert.That(f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey) is not null &&
            !f.Connection.MediaSharedSettingsReady, "Secure output failure lost durable choices or claimed matched state.");
    }

    internal static async Task ManualGuardsAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); await Seed(f);
        f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "enabled", JsonValue.Create(true)!,
            f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "enabled"));
        JsonObject Request()
        {
            var message = Message(new JsonObject { ["format"] = 1, ["settings"] = f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)!.DeepClone() });
            message["kind"] = MediaSyncSettings.StartKind; return message;
        }
        var calls = 0;
        f.Connection.MediaManualRequested = (settings, _, _, _) => {
            TestAssert.That(JsonNode.DeepEquals(settings, f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)), "Manual callback received a different snapshot.");
            calls++;
        };
        await f.Connection.HandlePlainAsync(Request());
        TestAssert.That(calls == 0, "Unmatched settings admitted explicit manual work.");
        await MatchAsync(f);
        var requested = Request(); await f.Connection.HandlePlainAsync(requested); await f.Connection.HandlePlainAsync(requested);
        TestAssert.That(calls == 1, "Exact duplicate manual request scheduled another worker.");
        var expired = Request(); expired["created_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 61000; expired["expires_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1000;
        await f.Connection.HandlePlainAsync(expired);
        TestAssert.That(calls == 1, "Manual action used generic clock-skew tolerance to start after its deadline.");
        var duringAck = Request(); var issued = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        duringAck["created_ms"] = issued - 59000; duringAck["expires_ms"] = issued + 1000;
        f.Stream.BeforeWrite = () => { f.Stream.BeforeWrite = null; Thread.Sleep(1200); };
        await f.Connection.HandlePlainAsync(duringAck);
        TestAssert.That(calls == 1, "A manual request expired during actual secure ACK output but still scheduled native IO.");
        var held = DeviceFileConnectionTransportTests.OpenFrames(f.Stream.ToArray()).Last(frame => frame["kind"]?.GetValue<string>() == MediaSyncSettings.ResultKind);
        TestAssert.That(held["body"]!["request_id"]!.GetValue<string>() == duringAck["message_id"]!.GetValue<string>() &&
            held["body"]!["state"]!.GetValue<string>() == "held", "ACK-deadline withdrawal left the phone pending without a correlated HOLD.");
        var malformed = Request(); malformed["body"]!["path"] = "C:\\must-not-open";
        await DeviceFileConnectionSourcesTests.FailsAsync<TelefonMessageException>(f.Connection.HandlePlainAsync(malformed), "Native path entered an explicit phone request.");
        var stale = Request();
        f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, "skip_deletions", JsonValue.Create(true)!,
            f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, "skip_deletions"));
        await f.Connection.HandlePlainAsync(stale); TestAssert.That(calls == 1, "Stale manual action started after a register edit.");
        void Change(string field, string value) => f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, field,
            JsonValue.Create(value)!, f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, field));
        Change("direction", "two_way"); Change("auto_mode", "wifi");
        await MatchAsync(f);
        var retained = f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)!;
        await f.Connection.HandlePlainAsync(Request());
        TestAssert.That(calls == 1 && f.Connection.MediaSharedSettingsReady &&
            JsonNode.DeepEquals(retained, f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)),
            "A matched two-way choice started a worker or was not preserved.");
        Change("collection_mode", "import_only");
        await MatchAsync(f);
        await f.Connection.HandlePlainAsync(Request());
        TestAssert.That(calls == 2, "Explicit import-only failed with an independently stored two-way direction.");
        f.Stream.Fail = true;
        await DeviceFileConnectionSourcesTests.FailsAsync<IOException>(f.Connection.HandlePlainAsync(Request()), "Failed secure request ACK was ignored.");
        TestAssert.That(calls == 2, "Native manual work started before secure ACK output succeeded.");
    }
}
