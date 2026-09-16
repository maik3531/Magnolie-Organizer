using System.Buffers.Binary;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonProtocolTests
{
    internal static async Task RunAsync()
    {
        TestAssert.That(await OutgoingDialTests.RunAsync() == 0,
            "Scoped explicit outgoing lifecycle/control regression failed.");
        var copiedControl = Path.Combine(AppContext.BaseDirectory, "resources", "telefon-control-contract.json");
        TestAssert.That(File.Exists(copiedControl), "Repository-lokaler Telefon-Control-Vertrag fehlt.");
        var capabilities = TelefonProtocolContract.DesktopCapabilities();
        TestAssert.That(TelefonProtocolContract.ValidateCapabilities(capabilities) == 1 && capabilities["items"]!.AsObject().Count == 11,
            "Granulare Telefon-Capabilities fehlen.");
        TestAssert.That(capabilities["items"]!["device_status"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3, 4 }),
            "Device status negotiation must include v4 without new capability names.");
        TestAssert.That(capabilities["items"]!["personal_tasks_sync"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3, 4 }),
            "Ordinary tasks v1-v3 and separate Custom v4 capability are missing.");
        TestAssert.That(!capabilities["items"]!["transport.bluetooth_rfcomm"]!["available"]!.GetValue<bool>() &&
            capabilities["items"]!["transport.bluetooth_rfcomm"]!["reason"]!.GetValue<string>() == "os_restricted" &&
            capabilities["items"]!["incoming_call_state"]!["versions"]!.AsArray().Single()!.GetValue<int>() == 2,
            "Windows-Bluetooth oder incoming_call_state v2 wird falsch ausgewiesen.");
        /* Ohne gemeldetes Funkgerät bleibt der Transport ausdrücklich aus; meldet
           die Windows-Anbindung einen veröffentlichten RFCOMM-Dienst, muss die
           Capability das vertragskonform mittragen. */
        try
        {
            TelefonBluetoothSupport.Report(true, "available", "");
            var withRadio = TelefonProtocolContract.DesktopCapabilities();
            TestAssert.That(TelefonProtocolContract.ValidateCapabilities(withRadio) == 1 &&
                withRadio["items"]!["transport.bluetooth_rfcomm"]!["available"]!.GetValue<bool>() &&
                withRadio["items"]!["transport.bluetooth_rfcomm"]!["reason"]!.GetValue<string>() == "available",
                "Ein veröffentlichter RFCOMM-Dienst wird nicht als Capability geführt.");
            TelefonBluetoothSupport.Report(false, "no_hardware", "");
            var withoutRadio = TelefonProtocolContract.DesktopCapabilities();
            TestAssert.That(TelefonProtocolContract.ValidateCapabilities(withoutRadio) == 1 &&
                !withoutRadio["items"]!["transport.bluetooth_rfcomm"]!["available"]!.GetValue<bool>() &&
                withoutRadio["items"]!["transport.bluetooth_rfcomm"]!["reason"]!.GetValue<string>() == "no_hardware" &&
                TelefonBluetoothSupport.Blocker.Length > 0,
                "Fehlendes Bluetooth-Funkgerät wird nicht begründet gemeldet.");
        }
        finally { TelefonBluetoothSupport.Report(false, "os_restricted", TelefonBluetoothSupport.DefaultBlocker); }
        TestAssert.That(!capabilities["items"]!.AsObject().ContainsKey("sms_send") && !capabilities["items"]!.AsObject().ContainsKey("call_control"),
            "Legacy-SMS/call_control wird noch beworben.");
        var control = JsonNode.Parse(File.ReadAllText(copiedControl))!.AsObject();
        TestAssert.That(control["desktop_capabilities"]!["device_status"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3, 4 }) &&
            control["android_capabilities"]!["device_status"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3 }),
            "Der Telefon-Control-Vertrag bewirbt nicht auf beiden Seiten Gerätestatus v3.");
        TestAssert.That(control["desktop_capabilities"]!["personal_tasks_sync"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3, 4 }) &&
            control["android_capabilities"]!["personal_tasks_sync"]!["versions"]!.AsArray()
            .Select(value => value!.GetValue<int>()).SequenceEqual(new[] { 1, 2, 3, 4 }),
            "Control vectors must advertise ordinary task versions and separate Custom support.");
        foreach (var name in new[] { "device_status_v1", "device_status_v2", "device_status_v3" })
            TelefonDeviceStatusContract.ValidateReport(control[name]!);
        var requestId = "123e4567-e89b-42d3-a456-426614174000";
        var requestV3 = TelefonCoordinator.DeviceStatusRequest(requestId, new JsonArray(1, 2, 3));
        var requestV2 = TelefonCoordinator.DeviceStatusRequest(requestId, new JsonArray(1, 2));
        var requestV1 = TelefonCoordinator.DeviceStatusRequest(requestId, new JsonArray(1));
        TestAssert.That(requestV3.Count == 2 && requestV3["version"]!.GetValue<int>() == 3 &&
            requestV2.Count == 2 && requestV2["version"]!.GetValue<int>() == 2 &&
            requestV1.Count == 1 && !requestV1.ContainsKey("version"),
            "Die Statusanfrage wählt nicht v3, dann v2 und zuletzt exakt das unversionierte v1.");
        TestAssert.Throws<InvalidDataException>(() => TelefonDeviceStatusContract.ValidateRequest(
            new JsonObject { ["request_id"] = requestId, ["version"] = 1 }),
            "Eine explizite Legacy-Statusversion 1 wurde angenommen.");
        var v2WithUnknown = control["device_status_v2"]!.DeepClone().AsObject(); v2WithUnknown["extra"] = true;
        TestAssert.Throws<InvalidDataException>(() => TelefonDeviceStatusContract.ValidateReport(v2WithUnknown),
            "Gerätestatus v2 nahm ein zusätzliches Feld an.");
        var v3MissingField = control["device_status_v3"]!.DeepClone().AsObject(); v3MissingField.Remove("network_metered");
        TestAssert.Throws<InvalidDataException>(() => TelefonDeviceStatusContract.ValidateReport(v3MissingField),
            "Gerätestatus v3 nahm einen unvollständigen Feldsatz an.");
        var v3 = control["device_status_v3"]!.DeepClone().AsObject();
        DeviceIdentifierTests.Run(v3);
        v3["app_version"] = string.Concat(Enumerable.Repeat("\U0001F600", 80));
        TelefonDeviceStatusContract.ValidateReport(v3);
        foreach (var invalidVersion in new[] { "", "1.0\u0001", string.Concat(Enumerable.Repeat("\U0001F600", 81)) })
        {
            var invalidV3 = control["device_status_v3"]!.DeepClone().AsObject(); invalidV3["app_version"] = invalidVersion;
            TestAssert.Throws<InvalidDataException>(() => TelefonDeviceStatusContract.ValidateReport(invalidV3),
                "Eine leere, kontrollzeichenhaltige oder überlange Magnolie-Notes-Version wurde angenommen.");
        }
        var grants = TelefonProtocolContract.DesktopGrants();
        TestAssert.That(grants.Count == 10 && grants["device_status"]!.GetValue<bool>() && grants["dial_request"]!.GetValue<bool>() &&
            grants.Where(item => item.Key is not ("device_status" or "dial_request")).All(item => !item.Value!.GetValue<bool>()),
            "Desktop-Standardgrants sind nicht minimal und granular.");
        var empty = new JsonObject { ["records"] = new JsonArray() };
        var durable = new JsonObject { ["modules"] = new JsonArray("notes", "tasks") };
        TestAssert.That(TelefonCoordinator.PersonalGrants("personal_sync.batch", empty, durable).SetEquals(new[] { "personal_notes_sync", "personal_tasks_sync" }),
            "Leerer Personal-Sync-Batch umging die durable Modulfreiabe.");

        using (var bridge = BridgeDispatcherContract.Parse("{\"cmd\":\"telefon_waehlen\",\"nummer\":\"+49123\",\"clientRef\":\"x\"}")) { }
        foreach (var payload in new[]
        {
            "{\"cmd\":\"kennwort_setzen\",\"alt\":\"\",\"neu\":\"test\",\"sicherungen\":true,\"sicherungsordner\":\"C:\\\\Backup\"}",
            "{\"cmd\":\"kennwort_entfernen\",\"alt\":\"\",\"sicherungsordner\":\"\"}",
            "{\"cmd\":\"sicherung_wiederherstellen\",\"pfad\":\"C:\\\\a\",\"kennwort\":\"k\",\"sicherungsordner\":\"C:\\\\b\"}",
            "{\"cmd\":\"gesamtarchiv_importieren\",\"pfad\":\"C:\\\\a\",\"kennwort\":\"k\",\"modus\":\"vollstaendig-ersetzen\",\"sicherungsordner\":\"C:\\\\b\"}",
            "{\"cmd\":\"adressen_ods\",\"titel\":\"Adressen\",\"spalten\":[\"Name\"],\"zeilen\":[[\"Ada\"]]}",
            "{\"cmd\":\"planer_ods\",\"layout\":\"year\",\"jahr\":2026,\"titel\":\"Plan\",\"spalten\":[\"Jan\"],\"zeilen\":[[\"1\"]],\"stile\":[[\"\"]],\"inhalte\":[[{\"datum\":\"1\",\"eintraege\":[]}]]}",
            "{\"cmd\":\"gesundheit_ods\",\"tabellen\":[{\"titel\":\"Werte\",\"links\":[\"Tag\"],\"rechts\":[\"Wert\"],\"zeilen\":[[\"1\",\"2\"]]}]}",
            "{\"cmd\":\"telefon_sms_benachrichtigen\",\"kennung\":\"p\",\"nummer\":\"1\",\"name\":\"N\",\"text\":\"T\",\"foto\":\"\",\"stil\":\"standard\",\"dauer\":10}",
            "{\"cmd\":\"telefon_anruf_anzeigen\",\"kennung\":\"p\",\"callRef\":\"c\",\"revision\":1,\"state\":\"ringing\",\"name\":\"N\",\"nummer\":\"1\",\"foto\":\"\",\"stil\":\"standard\",\"dauer\":60,\"annehmen\":true,\"leiser\":false}",
            "{\"cmd\":\"telefon_anruf_lautstaerke_wiederherstellen\",\"callRef\":\"c\"}"
        }) using (var productiveBridgeMessage = BridgeDispatcherContract.Parse(payload)) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"telefon_stand\",\"cmd\":\"telefon_entfernen\",\"kennung\":\"x\"}"), "Doppeltes Bridge-cmd wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"telefon_entfernen\",\"kennung\":7}"), "Bridge-Feld mit falschem Typ wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse("{\"cmd\":\"telefon_stand\",\"extra\":true}"), "Zusätzliches Bridge-Feld wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.ValidateSize(BridgeDispatcherContract.MaximumCharacters + 1, 1), "Übergroße Bridge-Nachricht wurde angenommen.");

        var dial = new JsonObject { ["to"] = "+491701234567", ["client_ref"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" };
        TelefonCallContract.Validate("dial_request.command", dial);
        TestAssert.Throws<InvalidDataException>(() => TelefonCallContract.Validate("dial_request.command", new JsonObject
            { ["to"] = "+49 170", ["client_ref"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" }), "Wählziel mit Leerzeichen wurde angenommen.");
        var incoming = JsonNode.Parse("""{"battery_captured_ms":0,"battery_percent":-1,"call_ref":"123e4567-e89b-42d3-a456-426614174000","control_origin":"unknown","direction":"incoming","ended_ms":0,"number":"","number_status":"permission_missing","occurred_ms":1000,"offhook_ms":0,"revision":1,"spam_status":"unknown","started_ms":1000,"state":"ringing"}""")!.AsObject();
        TelefonCallContract.Validate("incoming_call_state.event", incoming);
        var staleShape = incoming.DeepClone().AsObject(); staleShape["revision"] = 0;
        TestAssert.Throws<InvalidDataException>(() => TelefonCallContract.Validate("incoming_call_state.event", staleShape), "Anrufrevision 0 wurde angenommen.");
        var newer = incoming.DeepClone().AsObject(); newer["revision"] = 2;
        var decreasing = incoming.DeepClone().AsObject();
        var conflicting = newer.DeepClone().AsObject(); conflicting["state"] = "offhook";
        for (var repeat = 0; repeat < 3; repeat++)
            TestAssert.That(TelefonCoordinator.IncomingCallDisposition(newer, decreasing) == "conflict" && TelefonCoordinator.IncomingCallDisposition(newer, newer.DeepClone().AsObject()) == "duplicate" && TelefonCoordinator.IncomingCallDisposition(incoming, newer) == "accepted" && TelefonCoordinator.IncomingCallDisposition(newer, conflicting) == "conflict",
                "Semantisch veralteter oder doppelter Anrufzustand ist nicht deterministisch terminal.");
        TelefonCallContract.Validate("answer_call.command", new JsonObject { ["command_ref"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", ["call_ref"] = "123e4567-e89b-42d3-a456-426614174000", ["expected_state"] = "ringing" });
        TelefonCallContract.Validate("end_call.command", new JsonObject { ["command_ref"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc", ["call_ref"] = "123e4567-e89b-42d3-a456-426614174000", ["expected_revision"] = 2, ["expected_state"] = "offhook" });
        TelefonCallContract.Validate("end_call.command", new JsonObject { ["command_ref"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc", ["call_ref"] = "123e4567-e89b-42d3-a456-426614174000", ["expected_revision"] = 1, ["expected_state"] = "ringing" });
        var wrongDirection = newer.DeepClone().AsObject(); wrongDirection["direction"] = "outgoing";
        TestAssert.That(TelefonCoordinator.IncomingCallDisposition(incoming, wrongDirection) == "conflict", "Call direction changed within one call ID.");
        var endedCall = newer.DeepClone().AsObject(); endedCall["state"] = "idle";
        var resurrectedCall = newer.DeepClone().AsObject(); resurrectedCall["revision"] = 3;
        TestAssert.That(TelefonCoordinator.IncomingCallDisposition(endedCall, resurrectedCall) == "conflict", "A disconnected call was resurrected.");
        var tooLong = Message("answer_call.command", new JsonObject { ["command_ref"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", ["call_ref"] = "123e4567-e89b-42d3-a456-426614174000", ["expected_state"] = "ringing" }, 1, 10_002);
        TestAssert.Throws<TelefonMessageException>(() => TelefonMessageContract.ValidateMessage(tooLong, 1, false), "Destruktive Command-TTL über 10 Sekunden wurde angenommen.");

        var notification = new JsonObject { ["notification_id"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd", ["event"] = "posted", ["package"] = "org.signal", ["app_label"] = "Signal", ["title"] = "Mia", ["text"] = "Hallo", ["posted_ms"] = 1000, ["is_default_sms_app"] = false };
        TelefonMessagingContract.Validate("selected_notifications_readonly.event", notification);
        notification["reply"] = "Nein";
        TestAssert.Throws<InvalidDataException>(() => TelefonMessagingContract.Validate("selected_notifications_readonly.event", notification), "Nur-Lese-Benachrichtigung nahm Reply an.");

        /* Ohne A-Satz kann das Telefon den im SRV-Satz genannten Rechner unter
           Windows nicht auflösen; die WLAN-Verbindung scheitert dann stumm. */
        var deviceId = "44444444-4444-4444-8444-444444444444";
        var announcement = TelefonMdnsPublisher.BuildAnnouncement(deviceId, "Arbeitsplatz",
            "arbeitsplatz.local.", null, System.Net.IPAddress.Parse("192.168.178.42"));
        TestAssert.That(BinaryPrimitives.ReadUInt16BigEndian(announcement.AsSpan(6, 2)) == 4,
            "Die mDNS-Ankündigung nennt nicht genau vier Antworten.");
        TestAssert.That(Contains(announcement, [192, 168, 178, 42]) &&
            Contains(announcement, System.Text.Encoding.UTF8.GetBytes("arbeitsplatz")),
            "Die mDNS-Ankündigung enthält keinen A-Satz mit der Schnittstellenadresse.");
        var withoutAddress = TelefonMdnsPublisher.BuildAnnouncement(deviceId, "Arbeitsplatz",
            "arbeitsplatz.local.", null, null);
        TestAssert.That(BinaryPrimitives.ReadUInt16BigEndian(withoutAddress.AsSpan(6, 2)) == 3,
            "Ohne bekannte Adresse darf kein leerer A-Satz angekündigt werden.");
        var hostLabel = TelefonMdnsPublisher.LocalHostName();
        TestAssert.That(hostLabel.EndsWith(".local.", StringComparison.Ordinal) &&
            hostLabel[..^7].All(character => char.IsAsciiLetterOrDigit(character) || character == '-') &&
            hostLabel.Length > 7,
            "Der mDNS-Rechnername ist kein gültiges DNS-Label.");

        await using var stream = new MemoryStream(); var frame = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_abort", ["reason"] = "timeout" };
        await TelefonCoordinator.WriteFrameAsync(stream, frame, CancellationToken.None); var bytes = stream.ToArray();
        TestAssert.That(BinaryPrimitives.ReadUInt32BigEndian(bytes) == bytes.Length - 4, "Telefonrahmen hat kein Big-Endian-Präfix."); stream.Position = 0;
        TestAssert.That(JsonNode.DeepEquals(await TelefonCoordinator.ReadFrameAsync(stream, 65_536, CancellationToken.None), frame), "Telefonrahmen ist nicht verlustfrei.");

        var tempRoot = Path.Combine(Path.GetTempPath(), "magnolie-phone-tests-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new TelefonStore(new WindowsPaths(tempRoot), Enumerable.Range(0, 32).Select(value => (byte)value).ToArray());
            var freshIdentity = store.LoadOrCreateIdentity();
            TestAssert.That(freshIdentity.Name == KdeConnectIdentityStore.DeviceName[..Math.Min(60, KdeConnectIdentityStore.DeviceName.Length)],
                "Die Telefonidentität verwendet nicht den plattformweiten Organizer-Rechnernamen.");
            TestAssert.That(freshIdentity.PrivateKey.Any(value => value != 0) &&
                TelefonCrypto.X25519Public(freshIdentity.PrivateKey).SequenceEqual(freshIdentity.PublicKey),
                "Die neu erzeugte Telefonidentität verlor ihren privaten Schlüssel.");
            TestAssert.That(store.LoadOrCreateIdentity().PrivateKey.SequenceEqual(freshIdentity.PrivateKey),
                "Die frische Telefonidentität stimmt nicht mit der gespeicherten Identität überein.");
            File.Delete(new WindowsPaths(tempRoot).TelefonIdentityKey);
            var recoveredInitialIdentity = store.LoadOrCreateIdentity();
            TestAssert.That(recoveredInitialIdentity.Id != freshIdentity.Id &&
                TelefonCrypto.X25519Public(recoveredInitialIdentity.PrivateKey).SequenceEqual(recoveredInitialIdentity.PublicKey),
                "Unvollständige Telefon-Erstinitialisierung ohne Peers wurde nicht sicher neu erzeugt.");
            var peerId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"; var peer = new TelefonPeer(peerId, "Telefon", new byte[32]);
            var protocolNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var durableCall = Message("incoming_call_state.event", newer, protocolNow, protocolNow + 10_000);
            var durableAck = store.CommitIncoming(peerId, durableCall, protocolNow + 1, (_, _) => null); store.MarkIncomingProcessed(peerId, durableAck.MessageId, protocolNow + 1);
            var restartedCall = new TelefonStore(new WindowsPaths(tempRoot), Enumerable.Range(0, 32).Select(value => (byte)value).ToArray()).LoadRecent(peerId, "incoming_call_state.event", 1).Single()!.AsObject();
            TestAssert.That(TelefonCoordinator.IncomingCallDisposition(restartedCall, incoming) == "conflict" && TelefonCoordinator.IncomingCallDisposition(restartedCall, newer.DeepClone().AsObject()) == "duplicate",
                "Durabler Anrufzustand verlor nach Neustart seine terminale Revisionssemantik.");
            store.SavePending(peer, new byte[32], Enumerable.Repeat((byte)1, 32).ToArray(), Enumerable.Repeat((byte)2, 32).ToArray(), 100_000);
            TestAssert.Throws<InvalidOperationException>(() => store.SavePending(new TelefonPeer("ffffffff-ffff-4fff-8fff-ffffffffffff", "Zweites", new byte[32]), new byte[32], new byte[32], new byte[32], 100_000),
                "Ein zweites kryptografisch gebundenes Telefon wurde angenommen.");
            store.Cleanup(100_001);
            TestAssert.That(store.LoadPeers().Count == 0, "Abgelaufene ausstehende Paarung blieb sichtbar oder blockierend.");
            store.SavePending(peer, new byte[32], Enumerable.Repeat((byte)1, 32).ToArray(), Enumerable.Repeat((byte)2, 32).ToArray(), long.MaxValue);
            var destructive = store.Enqueue(peerId, "end_call.command", new JsonObject { ["command_ref"] = "11111111-1111-4111-8111-111111111111", ["call_ref"] = "22222222-2222-4222-8222-222222222222", ["expected_revision"] = 1, ["expected_state"] = "offhook" }, 10_000, 10_000);
            var queued = store.Due(peerId, 10_000).Single(); store.MarkAttempt(destructive, queued.Attempts, 10_000);
            TestAssert.That(store.Due(peerId, 19_999).Count == 0, "Destruktiver Anrufauftrag wurde wiederholt.");
            var retryable = store.Enqueue(peerId, "device_status.request",
                new JsonObject { ["request_id"] = "55555555-5555-4555-8555-555555555555" }, 60_000, 20_000);
            var retryAttempt = store.Due(peerId, 20_000).Single(item => item.Id == retryable);
            store.MarkAttempt(retryable, retryAttempt.Attempts, 20_000);
            TestAssert.That(store.RetryOutbox(peerId, retryable, 20_001, "temporary_failure") &&
                store.OutboxMessage(peerId, retryable) is not null && store.Due(peerId, 20_001).All(item => item.Id != retryable) &&
                store.Due(peerId, 21_001).Single(item => item.Id == retryable).Attempts == 1,
                "Temporärer Telefonfehler löschte die Nachricht, plante keinen Retry oder zählte den Versuch doppelt.");
            var runBody = new JsonObject { ["format"] = 1, ["run_id"] = "33333333-3333-4333-8333-333333333333", ["trigger"] = "auto_wifi", ["modules"] = new JsonArray("notes") };
            var personal = new PersonalSyncStore(store); personal.RememberRun(peerId, runBody, 20_000);
            var personalId = store.Enqueue(peerId, "personal_sync.request", runBody, 3_600_000, 20_000, "wifi_only");
            TestAssert.That(store.Due(peerId, 20_000, transport: "bluetooth").All(item => item.Id != personalId) && store.Due(peerId, 20_000, transport: "wifi").Any(item => item.Id == personalId),
                "wifi_only wurde nicht dauerhaft auf die Outbox angewandt.");
            var connectionNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var transportRunBody = runBody.DeepClone().AsObject();
            transportRunBody["run_id"] = "77777777-7777-4777-8777-777777777777";
            personal.RememberRun(peerId, transportRunBody, connectionNow);
            var unrestrictedId = store.Enqueue(peerId, "device_status.request",
                new JsonObject { ["request_id"] = "66666666-6666-4666-8666-666666666666" }, 60_000, connectionNow);
            var wifiOnlyId = store.Enqueue(peerId, "personal_sync.request", transportRunBody, 60_000, connectionNow, "wifi_only");
            await using var bluetoothStream = new MemoryStream();
            using (var bluetoothConnection = new TelefonConnection(peer, bluetoothStream, new byte[16], new byte[72], store,
                (_, _) => Task.FromResult<TelefonAck?>(null), CancellationToken.None, "bluetooth"))
            {
                await bluetoothConnection.PumpOutboxNowAsync();
                TestAssert.That(bluetoothConnection.Transport == "bluetooth" && bluetoothStream.Length > 0 &&
                    store.Due(peerId, connectionNow + 1, transport: "wifi").Any(item => item.Id == wifiOnlyId) &&
                    store.Due(peerId, connectionNow + 1, transport: "bluetooth").All(item => item.Id != wifiOnlyId) &&
                    store.Due(peerId, connectionNow + 1, transport: "wifi").All(item => item.Id != unrestrictedId),
                    "Eine RFCOMM-Sitzung behandelte wifi_only weiterhin wie WLAN.");
            }
            store.SaveStatus(peerId, new JsonObject { ["battery_percent"] = 50 });
            store.RemovePeer(peerId);
            TestAssert.That(store.Due(peerId, 20_000).Count == 0 && personal.LoadRun(peerId, runBody["run_id"]!.GetValue<string>(), 20_000) is null && store.LoadStatus(peerId) is null,
                "Peer-Entfernung ließ Protokollzustand zurück.");
            var damagedSettingsRoot = Path.Combine(tempRoot, "damaged-settings");
            var damagedSettingsPaths = new WindowsPaths(damagedSettingsRoot); damagedSettingsPaths.EnsureDirectories();
            File.WriteAllText(damagedSettingsPaths.TelefonSettings, "{kaputt");
            var damagedSettingsStore = new TelefonStore(damagedSettingsPaths, new byte[32]);
            TestAssert.Throws<InvalidDataException>(() => damagedSettingsStore.SetPersonalSettings(peerId, ownDevice: true),
                "Beschädigte Telefoneinstellungen wurden durch Teil-Defaults überschrieben.");
            TestAssert.That(File.ReadAllText(damagedSettingsPaths.TelefonSettings) == "{kaputt",
                "Fehlgeschlagene Einstellungsänderung veränderte die beschädigte Originaldatei.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            if (Directory.Exists(tempRoot)) Directory.Delete(tempRoot, true);
        }

        await PersonalSyncTests.RunAsync();
    }

    private static bool Contains(byte[] haystack, byte[] needle)
    {
        for (var offset = 0; offset + needle.Length <= haystack.Length; offset++)
            if (haystack.AsSpan(offset, needle.Length).SequenceEqual(needle)) return true;
        return false;
    }

    private static JsonObject Message(string kind, JsonObject body, long created, long expires) => new()
    { ["type"] = "message", ["v"] = 1, ["message_id"] = "abababab-abab-4bab-8bab-abababababab", ["kind"] = kind, ["created_ms"] = created, ["expires_ms"] = expires, ["body"] = body };
}
