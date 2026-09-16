using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeConnectTests
{
    internal static async Task RunAsync()
    {
        var identityPacket = KdeConnectProtocol.Encode("kdeconnect.identity",
            KdeConnectProtocol.IdentityBody("phone_1234", "Pixel", 1716), 42);
        var decoded = KdeConnectProtocol.Decode(identityPacket);
        var identity = KdeConnectProtocol.ParseIdentity(decoded);
        TestAssert.That(decoded.Id == 42 && identity.DeviceId == "phone_1234" && identity.TcpPort == 1716 &&
            identity.IncomingCapabilities.SequenceEqual(new[] { KdeConnectProtocol.SmsMessages }) &&
            identity.OutgoingCapabilities.SequenceEqual(new[] { KdeConnectProtocol.SmsRequest,
                KdeConnectProtocol.SmsRequestConversations, KdeConnectProtocol.SmsRequestConversation }),
            "Protocol-v8-Identität verlor Paketkopf oder Fähigkeiten.");

        using var fragmented = new FragmentedStream(identityPacket);
        var streamed = await KdeConnectProtocol.ReadAsync(fragmented, CancellationToken.None);
        TestAssert.That(streamed.Type == "kdeconnect.identity", "Fragmentiertes TCP-Paket wurde nicht bis LF gelesen.");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.Decode(Encoding.UTF8.GetBytes("{}\n{}\n")),
            "Mehrere JSON-Zeilen wurden als einzelnes Paket akzeptiert.");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.Decode(Encoding.UTF8.GetBytes(
            "{\"id\":1,\"id\":2,\"type\":\"x\",\"body\":{}}\n")),
            "Doppelte JSON-Felder wurden akzeptiert.");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.ParseIdentity(new KdeConnectPacket(1,
            "kdeconnect.identity", KdeConnectProtocol.IdentityBody("phone_1234", "Pixel", 1765))),
            "Ein TCP-Port außerhalb des KDE-Connect-Bereichs wurde akzeptiert.");
        var targeted = KdeConnectProtocol.IdentityBody("phone_1234", "Pixel", 1716, "windows_1234");
        TestAssert.That(KdeConnectProtocol.ParseTargetedIdentity(new KdeConnectPacket(1,
            "kdeconnect.identity", targeted), "windows_1234").DeviceId == "phone_1234",
            "Korrekte Plaintext-Zieladressierung wurde verworfen.");
        var untargeted = KdeConnectProtocol.IdentityBody("phone_1234", "Pixel", 1716);
        TestAssert.That(KdeConnectProtocol.ParseTargetedIdentity(new KdeConnectPacket(1,
            "kdeconnect.identity", untargeted), "windows_1234").DeviceId == "phone_1234",
            "Kompatible ältere Version-8-Identity ohne optionale Zielfelder wurde verworfen.");
        targeted.Remove("targetProtocolVersion");
        TestAssert.That(KdeConnectProtocol.ParseTargetedIdentity(new KdeConnectPacket(1,
            "kdeconnect.identity", targeted), "windows_1234").DeviceId == "phone_1234",
            "Upstream-kompatible Zieladressierung nur mit targetDeviceId wurde verworfen.");
        var wrongTarget = KdeConnectProtocol.IdentityBody("phone_1234", "Pixel", 1716, "windows_1234");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.ParseTargetedIdentity(new KdeConnectPacket(1,
            "kdeconnect.identity", wrongTarget), "windows_other"),
            "Fremde Plaintext-targetDeviceId wurde akzeptiert.");
        TestAssert.That(KdeConnectDirectBackend.IsPrivateAddress(IPAddress.Parse("192.168.1.5")) &&
            KdeConnectDirectBackend.IsPrivateAddress(IPAddress.IPv6Loopback) &&
            !KdeConnectDirectBackend.IsPrivateAddress(IPAddress.Parse("8.8.8.8")),
            "Private Netzwerkgrenze ist fehlerhaft.");
        TestAssert.That(Ipv4Broadcast.Calculate(IPAddress.Parse("192.168.17.42"), IPAddress.Parse("255.255.255.0"))
                .Equals(IPAddress.Parse("192.168.17.255")),
            "Die gerichtete IPv4-Rundsendeadresse ist fehlerhaft.");
        /* Der Rueckruf zu ungepaarten Nachbarn ist am Geraet gemessen: Neunzig
           Kennungs-Rundsendungen in drei Minuten blieben unbeantwortet, weil
           Android sie im WLAN-Stromsparmodus verwirft; ein einziger vom Rechner
           ausgehender Verbindungsaufbau genuegte dagegen. Ohne ihn erscheint der
           Rechner nie in der Geraeteliste des Telefons.

           Diese Pruefung existiert, weil die Methode bereits einmal bei einem
           Zusammenfuehren verlorenging und der Verlust erst am Geraet auffiel. */
        var backendQuelle = File.ReadAllText("KdeConnectDirectBackend.cs");
        TestAssert.That(backendQuelle.Contains("private void TryAnnounce(", StringComparison.Ordinal) &&
            backendQuelle.Contains("else TryAnnounce(device);", StringComparison.Ordinal) &&
            backendQuelle.Contains("MaxCandidates = 256", StringComparison.Ordinal) &&
            backendQuelle.Contains("outgoingSlots = new(8, 8)", StringComparison.Ordinal),
            "Der KDE-Connect-Rueckruf zu ungepaarten Nachbarn fehlt; ohne ihn erscheint " +
            "der Rechner nie in der Geraeteliste des Telefons, oder seine Ressourcen sind unbegrenzt.");

        const string firewallOutput = "Program: C:\\Magnolie.exe\r\nLocalPort: 8741,8737,1716-1764\r\n";
        TestAssert.That(WindowsFirewall.OutputContainsPorts(firewallOutput, "8741,8737,1716-1764") &&
            !WindowsFirewall.OutputContainsPorts(firewallOutput, "8741,8737,1716-1764,9999"),
            "Die Firewallprüfung erkennt fehlende Pflichtports nicht.");

        var sms = KdeConnectProtocol.SmsBody("+491701234567", "Nur Text");
        TestAssert.That(sms["version"]!.GetValue<int>() == 2 && sms["messageBody"]!.GetValue<string>() == "Nur Text" &&
            sms["addresses"]![0]!["address"]!.GetValue<string>() == "+491701234567" && sms["attachments"] is null,
            "SMS request v2 ist nicht text-only oder verlor den Empfänger.");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.SmsBody("+49170", "Text\0Anhang"),
            "Binär-/NUL-Inhalt wurde als Text-SMS akzeptiert.");
        var normalized = KdeConnectProtocol.NormalizeSmsText("Grüße 🙂 ❤️ 👍🏽 — ‘ok’ …");
        TestAssert.That(normalized.Text == "Grüße :) <3 +1 - 'ok' ..." && normalized.Changed &&
            KdeConnectProtocol.NormalizeSmsText(new string('a', 160)).Segments == 1 &&
            KdeConnectProtocol.NormalizeSmsText(new string('a', 161)).Segments == 2 &&
            KdeConnectProtocol.NormalizeSmsText(new string('^', 81)).Segments == 2,
            "GSM-03.38-Normalisierung oder Segmentgrenzen sind instabil.");
        TestAssert.Throws<InvalidDataException>(() => KdeConnectProtocol.SmsBody("+49170", new string('a', 1531)),
            "Eine SMS mit mehr als zehn Segmenten wurde akzeptiert.");

        var parsePacket = SmsMessagesPacket([
            SmsRow(3, 7, "Eingang", 1, 1), SmsRow(4, null, "Ausgang", 2, 1),
            SmsRow(5, 9, "Kein SMS-Ereignis", 1, 0)]);
        var parsedMessages = KdeConnectProtocol.ParseSmsMessages(parsePacket, "phone_1234", out var skipped);
        var parsedAgain = KdeConnectProtocol.ParseSmsMessages(parsePacket, "phone_1234", out _);
        TestAssert.That(parsedMessages.Count == 2 && parsedMessages[0].Incoming && !parsedMessages[1].Incoming &&
            parsedMessages[1].SmsId.StartsWith('h') && parsedMessages[1].Id == parsedAgain[1].Id && skipped == 1,
            "SMS-v2-Parser verlor Richtung, Filterung oder stabile Fallback-ID.");

        using var first = Certificate("first"); using var second = Certificate("second");
        TestAssert.That(KdeConnectProtocol.PairingCode(first, second, 1786617000) ==
            KdeConnectProtocol.PairingCode(second, first, 1786617000) &&
            KdeConnectProtocol.PairingCode(first, second, 1786617000).Length == 8 &&
            KdeConnectProtocol.CertificatePin(first).Length == 64,
            "Protocol-v8-Paarungscode oder SHA-256-Zertifikatpin ist instabil.");

        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            var store = new KdeConnectIdentityStore(paths, protector); var created = store.LoadOrCreate();
            var oldMetadata = JsonNode.Parse(File.ReadAllText(paths.KdeConnectIdentity))!.AsObject();
            oldMetadata["deviceName"] = "Magnolie Organizer auf ALTER-PC";
            File.WriteAllText(paths.KdeConnectIdentity, oldMetadata.ToJsonString());
            var loaded = new KdeConnectIdentityStore(paths, protector).LoadOrCreate();
            TestAssert.That(created.Id == loaded.Id && created.Certificate.Thumbprint == loaded.Certificate.Thumbprint &&
                created.Name == KdeConnectIdentityStore.DeviceName && loaded.Name == KdeConnectIdentityStore.DeviceName &&
                KdeConnectIdentityStore.DeviceName.StartsWith("Magnolie Organizer (", StringComparison.Ordinal) &&
                KdeConnectIdentityStore.DeviceName.Length <= 128 &&
                JsonNode.Parse(File.ReadAllText(paths.KdeConnectIdentity))!["deviceName"]!.GetValue<string>() ==
                    KdeConnectIdentityStore.DeviceName &&
                created.Certificate.GetECDsaPrivateKey() is not null &&
                !File.ReadAllText(paths.KdeConnectIdentityKey).Contains(Convert.ToBase64String(created.Certificate.Export(X509ContentType.Pfx)), StringComparison.Ordinal),
                "P-256-Identität ist nicht persistent oder liegt ungeschützt vor.");
            File.Delete(paths.KdeConnectIdentity);
            var recovered = new KdeConnectIdentityStore(paths, protector).LoadOrCreate();
            TestAssert.That(recovered.Id == created.Id && recovered.Certificate.Thumbprint == created.Certificate.Thumbprint,
                "KDE-Schlüsseldatei ohne Metadaten konnte die bestehende Identität nicht rekonstruieren.");
            var peer = new KdeConnectPeer("phone_1234", "Pixel", KdeConnectProtocol.CertificatePin(second), 1234);
            store.Pin(peer);
            TestAssert.That(store.LoadPeers().Single() == peer, "Der Peer-Zertifikatpin wurde nicht persistent gespeichert.");
            store.Remove(peer.Id);
            TestAssert.That(store.LoadPeers().Count == 0, "Ein entfernter Peer blieb gepinnt.");
            var retainedIds = Enumerable.Range(0, KdeConnectIdentityStore.MaxRememberedSms + 1)
                .Select(index => $"phone_1234:7:{index}").ToArray();
            TestAssert.That(store.RememberSms(retainedIds).Count == retainedIds.Length,
                "Neue SMS-Kennungen wurden nicht vollständig gespeichert.");
            var restartedStore = new KdeConnectIdentityStore(paths, protector);
            var afterRestart = restartedStore.RememberSms([retainedIds[0], retainedIds[^1]]);
            TestAssert.That(afterRestart.SetEquals([retainedIds[0]]) &&
                !File.ReadAllText(Path.Combine(paths.KdeConnect, "sms-seen.dpapi")).Contains(retainedIds[^1], StringComparison.Ordinal),
                "SMS-Deduplizierung überlebte Neustart/Begrenzung nicht oder liegt ungeschützt vor.");
            created.Certificate.Dispose(); loaded.Certificate.Dispose(); recovered.Certificate.Dispose();

            await OutgoingTlsLoopbackAsync(paths, protector);

            var invalidMetadata = JsonNode.Parse(File.ReadAllText(paths.KdeConnectIdentity))!.AsObject();
            invalidMetadata["deviceId"] = new string('a', 39);
            File.WriteAllText(paths.KdeConnectIdentity, invalidMetadata.ToJsonString());
            var migrated = store.LoadOrCreate();
            TestAssert.That(migrated.Id.Length is >= 32 and <= 38 && migrated.Id != new string('a', 39),
                "Eine KDE-Connect-Kennung außerhalb 32 bis 38 Zeichen wurde nicht ersetzt.");
            migrated.Certificate.Dispose();
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }

        await IncomingPairingLoopbackAsync();
        await StagedConnectionSurvivesCandidateExpiryAsync();
        await HistoryBootstrapLoopbackAsync();
        await IncomingReplacementLoopbackAsync();
        await TransactionalPairingReplacementLoopbackAsync();
        await PersistentCandidateLoopbackAsync();
        await SelectedSetupPairingLoopbackAsync();
        await CancelSelectedSetupPairingLoopbackAsync();

        var backendSource = File.ReadAllText(Path.Combine("KdeConnectDirectBackend.cs"));
        var adapterSource = File.ReadAllText(Path.Combine("KdeConnectSms.cs"));
        var bridgeSource = File.ReadAllText(Path.Combine("BridgeDispatcher.cs"));
        TestAssert.That(backendSource.Contains("SslStream", StringComparison.Ordinal) &&
            backendSource.Contains("FixedTimeEquals", StringComparison.Ordinal) &&
            backendSource.Contains("AuthenticateAsServerAsync", StringComparison.Ordinal) &&
            backendSource.Contains("AuthenticateAsClientAsync", StringComparison.Ordinal) &&
            backendSource.Contains("ClientCertificateRequired = true", StringComparison.Ordinal) &&
            backendSource.Contains("X509NameType.SimpleName", StringComparison.Ordinal) &&
            backendSource.Contains("ReferenceEquals(current, connection)", StringComparison.Ordinal) &&
            backendSource.Contains("ReconnectSeconds", StringComparison.Ordinal) &&
            backendSource.Contains("TransferFrom", StringComparison.Ordinal) &&
            backendSource.Contains("SendIdentity(device.Address)", StringComparison.Ordinal) &&
            backendSource.Contains("callback.reverse_wait", StringComparison.Ordinal) &&
            backendSource.IndexOf("SendIdentity(device.Address)", StringComparison.Ordinal) <
                backendSource.IndexOf("callback.start", StringComparison.Ordinal) &&
            backendSource.Contains("EnabledSslProtocols = SslProtocols.Tls12", StringComparison.Ordinal) &&
            !backendSource.Contains("RetryDelay", StringComparison.Ordinal),
            "Die statische Integration erzwingt mTLS/Pinning oder Retry-Freiheit nicht.");
        TestAssert.That(adapterSource.IndexOf("native.StatusAsync", StringComparison.Ordinal) <
            adapterSource.IndexOf("FindExecutable", StringComparison.Ordinal) &&
            bridgeSource.Contains("kde_paarung_bestaetigen", StringComparison.Ordinal),
            "Der native Backend-Vorrang oder die explizite Pairing-Bestätigung fehlt.");
    }

    private static async Task OutgoingTlsLoopbackAsync(WindowsPaths paths, IKdeConnectSecretProtector protector)
    {
        const string phoneId = "phone_outgoing";
        using var phoneCertificate = Certificate(phoneId);
        var phoneListener = BindKdeListener();
        try
        {
            var phonePort = ((IPEndPoint)phoneListener.LocalEndpoint).Port;
            using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            new KdeConnectIdentityStore(paths, protector).Pin(new KdeConnectPeer(phoneId, "Pixel",
                KdeConnectProtocol.CertificatePin(phoneCertificate), 1));
            var phone = Task.Run(async () =>
            {
                using var client = await phoneListener.AcceptTcpClientAsync();
                var network = client.GetStream();
                var plainPacket = await KdeConnectProtocol.ReadAsync(network, CancellationToken.None);
                var plain = KdeConnectProtocol.ParseTargetedIdentity(plainPacket, phoneId);
                TestAssert.That(plain.DeviceId == backend.LocalDeviceId &&
                    !plainPacket.Body.ContainsKey("targetDeviceId") && !plainPacket.Body.ContainsKey("targetProtocolVersion"),
                    "Ausgehende Plaintext-Identity enthält wieder eine Zielkennung.");
                using var tls = new SslStream(network, false, (_, _, _, _) => true);
                await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions {
                    TargetHost = backend.LocalDeviceId,
                    ClientCertificates = new X509CertificateCollection { phoneCertificate },
                    EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck });
                var windowsIdentity = KdeConnectProtocol.ParseIdentity(
                    await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None));
                await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                    PhoneIdentity(phoneId, phonePort)));
                TestAssert.That(windowsIdentity.DeviceName == KdeConnectIdentityStore.DeviceName,
                    "Ausgehende TLS-Identity verwendet nicht den festen Gerätenamen.");
                var sms = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                TestAssert.That(sms.Type == KdeConnectProtocol.SmsRequest,
                    "SMS lief nicht über die ausgehende TLS-Verbindung.");
            });
            var discovered = new KdeConnectDiscovered(KdeConnectProtocol.ParseIdentity(new KdeConnectPacket(1,
                "kdeconnect.identity", PhoneIdentity(phoneId, phonePort))), IPAddress.Loopback, DateTimeOffset.UtcNow);
            await backend.ConnectForTestAsync(discovered, KdeConnectProtocol.CertificatePin(phoneCertificate));
            var status = await backend.StatusAsync();
            TestAssert.That(status.Available && status.DeviceCount == 1,
                "Ausgehende gepinnte TLS-Verbindung wurde vom Status nicht bevorzugt.");
            await backend.SendSmsAsync("+491701234567", "Ausgehend", "DE", phoneId, KdeConnectProtocol.CertificatePin(phoneCertificate));
            await phone.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally { phoneListener.Stop(); }
    }

    private static async Task IncomingPairingLoopbackAsync()
    {
        const string phoneId = "phone_incoming";
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-incoming-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            using var phoneCertificate = Certificate(phoneId);
            using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var phone = Task.Run(async () =>
            {
                using var client = new TcpClient(AddressFamily.InterNetwork);
                await client.ConnectAsync(IPAddress.Loopback, backend.ListenerPort);
                var network = client.GetStream();
                await network.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                    KdeConnectProtocol.IdentityBody(phoneId, "Pixel", KdeConnectProtocol.FirstPort, backend.LocalDeviceId)));
                using var tls = new SslStream(network, false, (_, certificate, _, _) =>
                    certificate?.GetCertHashString() is { Length: > 0 });
                await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions {
                    ServerCertificate = phoneCertificate,
                    ClientCertificateRequired = true,
                    EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck });
                await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                    PhoneIdentity(phoneId, KdeConnectProtocol.FirstPort)));
                var windowsIdentity = KdeConnectProtocol.ParseIdentity(
                    await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None));
                TestAssert.That(windowsIdentity.DeviceName == KdeConnectIdentityStore.DeviceName,
                    "Eingehende TLS-Identity verwendet nicht den festen Gerätenamen.");
                var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair", new JsonObject {
                    ["pair"] = true, ["timestamp"] = timestamp }));
                var confirmation = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                TestAssert.That(confirmation.Type == "kdeconnect.pair" &&
                    confirmation.Body["pair"]?.GetValue<bool>() == true,
                    "Eingehende Paarung wurde nicht auf derselben Verbindung bestätigt.");
                var firstSms = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                var secondSms = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                TestAssert.That(firstSms.Type == KdeConnectProtocol.SmsRequest && secondSms.Type == KdeConnectProtocol.SmsRequest &&
                    firstSms.Body["messageBody"]?.GetValue<string>() == "Erste" &&
                    secondSms.Body["messageBody"]?.GetValue<string>() == "Zweite",
                    "Status/SMS haben die übernommene Verbindung nicht exakt einmal je Nachricht wiederverwendet.");
            });

            KdeConnectPairing pairing;
            using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10)))
            {
                while (true)
                {
                    try { pairing = await backend.BeginPairingAsync(timeout.Token); break; }
                    catch (InvalidOperationException) { await Task.Delay(20, timeout.Token); }
                }
            }
            TestAssert.That(pairing.DeviceId == phoneId && pairing.Code.Length == 8,
                "Eingehende Pairing-Verbindung wurde nicht zur Bestätigung übernommen.");
            await backend.ConfirmPairingAsync(phoneId, true);
            var status = await WaitForDeviceAsync(backend, phoneId);
            TestAssert.That(status.DeviceCount == 1,
                "Übernommene SMS-fähige Pairing-Verbindung ist nicht aktiv.");
            await backend.SendSmsAsync("+491701234567", "Erste", "DE", status.DeviceId, status.DeviceFingerprint);
            await backend.SendSmsAsync("+491701234567", "Zweite", "DE", status.DeviceId, status.DeviceFingerprint);
            await phone.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task StagedConnectionSurvivesCandidateExpiryAsync()
    {
        const string phoneId = "phone_staged_lifetime";
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-staged-lifetime-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            using var phoneCertificate = Certificate(phoneId);
            using var backend = new KdeConnectDirectBackend(paths, new TestProtector(), activeDiscovery: false);
            var phone = await ConnectIncomingPhoneAsync(backend, phoneId, phoneCertificate);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            KdeConnectStatus status;
            do { await Task.Delay(20, timeout.Token); status = await backend.GetStatusAsync(timeout.Token); }
            while (!status.CandidateReachable);

            backend.ExpireCandidatesForTest(DateTimeOffset.UtcNow.AddMinutes(6));
            status = await backend.GetStatusAsync();
            var debugLog = File.ReadAllText(Path.Combine(paths.Logs, "kde-connect-debug.log"));
            TestAssert.That(status.CandidateReachable && status.UnpairedCandidateId == phoneId &&
                debugLog.Contains("stage=incoming.tls_ready", StringComparison.Ordinal) &&
                debugLog.Contains("stage=staged.set", StringComparison.Ordinal),
                "Die vorgemerkte TLS-Verbindung überlebte den Discovery-Ablauf nicht oder wurde nicht diagnostiziert.");
            phone.Stream.Dispose(); phone.Client.Dispose();
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task HistoryBootstrapLoopbackAsync()
    {
        const string phoneId = "phone_history";
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-history-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            using var phoneCertificate = Certificate(phoneId);
            using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var received = new List<KdeConnectSmsReceived>();
            var receivedSignal = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            backend.SmsReceived += value => { lock (received) { received.Add(value); if (received.Count == 3) receivedSignal.TrySetResult(); } };
            var phone = Task.Run(async () =>
            {
                using var client = new TcpClient(AddressFamily.InterNetwork);
                await client.ConnectAsync(IPAddress.Loopback, backend.ListenerPort);
                var network = client.GetStream();
                await network.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                    KdeConnectProtocol.IdentityBody(phoneId, "Pixel", KdeConnectProtocol.FirstPort, backend.LocalDeviceId)));
                using var tls = new SslStream(network, false, (_, _, _, _) => true);
                await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions {
                    ServerCertificate = phoneCertificate, ClientCertificateRequired = true,
                    EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck });
                await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity", PhoneIdentity(phoneId,
                    KdeConnectProtocol.FirstPort, history: true)));
                _ = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair", new JsonObject {
                    ["pair"] = true, ["timestamp"] = timestamp }));
                _ = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                var conversations = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                TestAssert.That(conversations.Type == KdeConnectProtocol.SmsRequestConversations,
                    "Verlaufsbootstrap forderte keine Konversationsübersicht an.");
                await tls.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsMessages,
                    SmsMessagesPacket([SmsRow(7, 41, "Zusammenfassung", 1, 1)]).Body));
                var fullRequest = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
                TestAssert.That(fullRequest.Type == KdeConnectProtocol.SmsRequestConversation &&
                    fullRequest.Body["threadID"]!.GetValue<long>() == 7,
                    "Konversationsübersicht löste keine vollständige Verlaufsanfrage aus.");
                await tls.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsMessages,
                    SmsMessagesPacket([SmsRow(7, 41, "Zusammenfassung", 1, 1),
                        SmsRow(7, 42, "Eigene Antwort", 2, 1)]).Body));
                await Task.Delay(1300);
                await tls.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsMessages,
                    SmsMessagesPacket([SmsRow(7, 43, "Live", 1, 1)]).Body));
                await receivedSignal.Task.WaitAsync(TimeSpan.FromSeconds(5));
                await Task.Delay(500);
            });

            KdeConnectPairing pairing;
            using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10)))
                while (true) { try { pairing = await backend.BeginPairingAsync(timeout.Token); break; }
                    catch (InvalidOperationException) { await Task.Delay(20, timeout.Token); } }
            await backend.ConfirmPairingAsync(pairing.DeviceId, true);
            await receivedSignal.Task.WaitAsync(TimeSpan.FromSeconds(10));
            KdeConnectSmsReceived[] events; lock (received) events = received.ToArray();
            TestAssert.That(events.Select(value => value.Message.SmsId).SequenceEqual(["41", "42", "43"]) &&
                events[0].History && !events[0].Notify && events[1].History && !events[1].Notify &&
                !events[2].History && events[2].Notify,
                "Bootstrap-Deduplizierung, Ausgangsverlauf oder Live-Benachrichtigung ist fehlerhaft.");
            var status = await backend.GetStatusAsync();
            TestAssert.That(status.HistoryAvailable && status.BootstrapState == "live" &&
                status.ConnectionDirection == "incoming" && status.ConnectionGeneration > 0 &&
                status.NextReconnectSeconds is >= 0 and <= 60,
                "Verlaufs-/Reconnect-/Generationsdiagnostik fehlt im Status.");
            await phone.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task IncomingReplacementLoopbackAsync()
    {
        const string phoneId = "phone_replacement";
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-replacement-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            using var phoneCertificate = Certificate(phoneId);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (var identity = store.LoadOrCreate().Certificate) { }
            store.Pin(new KdeConnectPeer(phoneId, "Pixel", KdeConnectProtocol.CertificatePin(phoneCertificate), 1));
            using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var first = await ConnectIncomingPhoneAsync(backend, phoneId, phoneCertificate);
            var firstStatus = await WaitForGenerationAsync(backend, 1);
            var second = await ConnectIncomingPhoneAsync(backend, phoneId, phoneCertificate);
            var secondStatus = await WaitForGenerationAsync(backend, firstStatus.ConnectionGeneration + 1);
            TestAssert.That(secondStatus.ConnectionDirection == "incoming" &&
                secondStatus.ConnectionGeneration > firstStatus.ConnectionGeneration && secondStatus.DeviceCount == 1,
                "Gleichzeitiger eingehender Ersatz war nicht generationssicher oder erzeugte doppelte Geräte.");
            first.Stream.Dispose(); first.Client.Dispose();
            await Task.Delay(100);
            var afterStaleClose = await backend.GetStatusAsync();
            TestAssert.That(afterStaleClose.ConnectionGeneration == secondStatus.ConnectionGeneration && afterStaleClose.Available,
                "Der Finalizer der alten Verbindung entfernte die neue Generation.");
            second.Stream.Dispose(); second.Client.Dispose();
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task PersistentCandidateLoopbackAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-candidate-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var backend = new KdeConnectDirectBackend(new WindowsPaths(root), new TestProtector(),
                activeDiscovery: false);
            var initial = await backend.GetStatusAsync();
            if (!initial.Listening) return;
            using var sender = new UdpClient(AddressFamily.InterNetwork);
            var packet = KdeConnectProtocol.Encode("kdeconnect.identity", PhoneIdentity("phone_candidate", 1716));
            await sender.SendAsync(packet, new IPEndPoint(IPAddress.Loopback, backend.DiscoveryPort));
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            KdeConnectStatus status;
            try
            {
                do { await Task.Delay(20, timeout.Token); status = await backend.GetStatusAsync(timeout.Token); }
                while (!backend.HasCandidateForTest("phone_candidate"));
            }
            catch (OperationCanceledException)
            {
                var last = await backend.GetStatusAsync();
                throw new InvalidOperationException("Binnen drei Sekunden kam kein UDP-Kandidat an. " +
                    $"Grund={last.Reason} Lauscht={last.Listening} Port={last.ListenerPort} " +
                    $"Gelesen={last.ParseValid} Verworfen={last.ParseSkipped} LetzterEmpfangMs={last.LastReceiveMs}");
            }
            TestAssert.That(status.UnpairedCandidateCount > 0 &&
                (status.UnpairedCandidateCount > 1 || status.UnpairedCandidateId == "phone_candidate" &&
                    status.UnpairedCandidateName == "Pixel") && status.ReplacementPeerId == "" &&
                !status.CandidateReachable &&
                status.NextReconnectSeconds is >= 0 and <= 60,
                "Persistenter UDP-Listener, Kandidatencache oder begrenzter Reconnect-Status ist fehlerhaft.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task TransactionalPairingReplacementLoopbackAsync()
    {
        for (var attempt = 0; attempt < 30; attempt++)
            await TransactionalPairingReplacementAttemptAsync(attempt).WaitAsync(TimeSpan.FromSeconds(15));
    }

    private static async Task TransactionalPairingReplacementAttemptAsync(int attempt)
    {
        var oldId = $"phone_transaction_old_{attempt}";
        var newId = $"phone_transaction_new_{attempt}";
        var removedCandidateId = $"phone_transaction_removed_{attempt}";
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-kde-transaction-{attempt}-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            using var oldCertificate = Certificate(oldId);
            using var newCertificate = Certificate(newId);
            using var removedCertificate = Certificate(removedCandidateId);
            var store = new KdeConnectIdentityStore(paths, protector);
            using (var identity = store.LoadOrCreate().Certificate) { }
            store.Pin(new KdeConnectPeer(oldId, "Pixel", KdeConnectProtocol.CertificatePin(oldCertificate), 1));
            var identityBefore = File.ReadAllBytes(paths.KdeConnectIdentity);
            var keyBefore = File.ReadAllBytes(paths.KdeConnectIdentityKey);
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            var oldPhone = await ConnectIncomingPhoneAsync(backend, oldId, oldCertificate);
            _ = await WaitForStatusAsync(backend, status => status.Available && status.DeviceId == oldId);
            var peersBefore = store.LoadPeers().ToArray();

            var rejectedPhone = await ConnectIncomingPhoneAsync(backend, newId, newCertificate);
            var rejectedRequested = PairingBarrier(backend, newId, "requested");
            await RequestPairingAsync(rejectedPhone.Stream);
            await rejectedRequested;
            var rejectedPairing = await backend.BeginPairingAsync();
            var stagedStatus = await backend.GetStatusAsync();
            TestAssert.That(stagedStatus.Available && stagedStatus.DeviceId == oldId &&
                stagedStatus.ReplacementPeerId == oldId && stagedStatus.UnpairedCandidateId == newId &&
                stagedStatus.CandidateReachable && stagedStatus.PairingState == "requested",
                "Ersatzkandidat verdrängte den vertrauenswürdigen Peer oder fehlt im Status.");
            var rejectedBarrier = PairingBarrier(backend, newId, "rejected");
            await backend.ConfirmPairingAsync(rejectedPairing.DeviceId, false);
            await rejectedBarrier;
            var rejectedStatus = await backend.GetStatusAsync();
            TestAssert.That(rejectedStatus.Available && rejectedStatus.DeviceId == oldId &&
                rejectedStatus.PairingState == "failed_rejected" && !rejectedStatus.CandidateReachable &&
                store.LoadPeers().SequenceEqual(peersBefore) &&
                File.ReadAllBytes(paths.KdeConnectIdentity).SequenceEqual(identityBefore) &&
                File.ReadAllBytes(paths.KdeConnectIdentityKey).SequenceEqual(keyBefore) &&
                backend.LocalDeviceId == JsonNode.Parse(identityBefore)!["deviceId"]!.GetValue<string>(),
                "Abgelehnter Ersatz beschädigte den alten Peer oder meldete den Fehler nicht.");
            rejectedPhone.Stream.Dispose(); rejectedPhone.Client.Dispose();

            var acceptedPhone = await ConnectIncomingPhoneAsync(backend, newId, newCertificate);
            _ = await WaitForStatusAsync(backend, status => status.CandidateReachable &&
                status.UnpairedCandidateId == newId);
            var acceptedPairing = await backend.BeginPairingAsync();
            var request = await KdeConnectProtocol.ReadAsync(acceptedPhone.Stream, CancellationToken.None);
            TestAssert.That(request.Type == "kdeconnect.pair" && request.Body["pair"]!.GetValue<bool>(),
                "Die lokal initiierte Ersatzpaarung wurde nicht an das Telefon gesendet.");
            await backend.ConfirmPairingAsync(acceptedPairing.DeviceId, true);
            var waitingForPhone = await backend.GetStatusAsync();
            TestAssert.That(waitingForPhone.Available && waitingForPhone.DeviceId == oldId &&
                waitingForPhone.PairingState == "requested" && store.LoadPeers().SequenceEqual(peersBefore) &&
                File.ReadAllBytes(paths.KdeConnectIdentity).SequenceEqual(identityBefore) &&
                File.ReadAllBytes(paths.KdeConnectIdentityKey).SequenceEqual(keyBefore),
                $"Lokale Bestätigung schrieb den Ersatz vor der gegenseitigen Authentisierung fest: " +
                $"available={waitingForPhone.Available} device={waitingForPhone.DeviceId} " +
                $"state={waitingForPhone.PairingState} peers={string.Join(',', store.LoadPeers().Select(peer => peer.Id))}.");
            var pairedBarrier = PairingBarrier(backend, newId, "paired");
            await RequestPairingAsync(acceptedPhone.Stream);
            await pairedBarrier;
            var committed = await backend.GetStatusAsync();
            var committedPeers = store.LoadPeers();
            TestAssert.That(committed.Available && committed.DeviceId == newId && committed.PairedCount == 1 &&
                committedPeers.Count == 1 && committedPeers[0].Id == newId,
                $"Bestätigter Ersatz wurde nicht atomar als einziger Peer übernommen: available={committed.Available}, " +
                $"device={committed.DeviceId}, count={committed.PairedCount}, peers={string.Join(',', committedPeers.Select(value => value.Id))}.");
            await AssertClosedAsync(oldPhone.Stream,
                "Die alte Verbindung blieb nach dem atomaren Ersatz geöffnet.");

            var removedPhone = await ConnectIncomingPhoneAsync(backend, removedCandidateId, removedCertificate);
            var removedRequested = PairingBarrier(backend, removedCandidateId, "requested");
            await RequestPairingAsync(removedPhone.Stream);
            await removedRequested;
            _ = await backend.BeginPairingAsync();
            backend.Remove(newId);
            var removed = await backend.GetStatusAsync();
            TestAssert.That(removed.PairedCount == 0 && removed.PairingState == "idle" &&
                !removed.CandidateReachable && store.LoadPeers().Count == 0,
                $"Entfernen ließ eine Ersatzpaarung oder Kandidatenverbindung aktiv: paired={removed.PairedCount} " +
                $"state={removed.PairingState} reachable={removed.CandidateReachable} " +
                $"candidate={removed.UnpairedCandidateId} peers={store.LoadPeers().Count}.");
            await AssertClosedAsync(removedPhone.Stream,
                "Entfernen brach die ausstehende Ersatzverbindung nicht ab.");
            acceptedPhone.Stream.Dispose(); acceptedPhone.Client.Dispose();
            removedPhone.Stream.Dispose(); removedPhone.Client.Dispose();
            oldPhone.Stream.Dispose(); oldPhone.Client.Dispose();
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task SelectedSetupPairingLoopbackAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-setup-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            using var selectedCertificate = Certificate("phone_selected");
            using var neighbourCertificate = Certificate("phone_neighbour");
            var selected = await ConnectIncomingPhoneAsync(backend, "phone_selected", selectedCertificate);
            using var selectedClient = selected.Client; using var selectedStream = selected.Stream;
            var neighbour = await ConnectIncomingPhoneAsync(backend, "phone_neighbour", neighbourCertificate);
            using var neighbourClient = neighbour.Client; using var neighbourStream = neighbour.Stream;
            await WaitForStatusAsync(backend, status => status.UnpairedCandidateCount == 2);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var pairing = await backend.BeginPairingAsync("phone_selected", timeout.Token);
            var request = await KdeConnectProtocol.ReadAsync(selectedStream, timeout.Token);
            TestAssert.That(pairing.DeviceId == "phone_selected" && request.Type == "kdeconnect.pair" &&
                request.Body["pair"]!.GetValue<bool>() && !backend.HasPairedPeers,
                "Selected setup request did not reach the chosen phone before trust was stored.");
            var store = new KdeConnectIdentityStore(paths, protector);
            await backend.ConfirmPairingAsync(pairing.DeviceId, true, timeout.Token);
            TestAssert.That(store.LoadPeers().Count == 0, "Local approval alone authenticated the phone.");
            var paired = PairingBarrier(backend, pairing.DeviceId, "paired");
            await RequestPairingAsync(selectedStream);
            await paired;
            var before = store.LoadPeers().ToArray();
            TestAssert.That(before.Length == 1 && before[0].Id == pairing.DeviceId &&
                before[0].CertificatePin == KdeConnectProtocol.CertificatePin(selectedCertificate),
                "Selected setup pairing pinned the wrong certificate.");
            backend.CancelSetupPairing(pairing);
            try
            {
                await backend.BeginPairingAsync("phone_neighbour", timeout.Token);
                throw new Exception("Setup replaced a confirmed phone.");
            }
            catch (InvalidOperationException) { }
            TestAssert.That(store.LoadPeers().SequenceEqual(before), "Setup cancellation/replacement changed established trust.");
            TestAssert.Throws<InvalidOperationException>(() => store.ConfirmFirst(new KdeConnectPeer(
                "phone_neighbour", "Pixel", KdeConnectProtocol.CertificatePin(neighbourCertificate), 1)),
                "First-pair commit replaced a phone that became paired while setup was waiting.");
            TestAssert.That(store.LoadPeers().SequenceEqual(before), "First-pair commit guard changed stored trust.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task CancelSelectedSetupPairingLoopbackAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-kde-setup-cancel-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root); var protector = new TestProtector();
            await using var backend = new KdeConnectDirectBackend(paths, protector, activeDiscovery: false);
            using var certificate = Certificate("phone_cancel");
            var phone = await ConnectIncomingPhoneAsync(backend, "phone_cancel", certificate);
            using var client = phone.Client; using var stream = phone.Stream;
            await WaitForStatusAsync(backend, status => status.CandidateReachable);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            try
            {
                await backend.BeginPairingAsync("phone_absent", timeout.Token);
                throw new Exception("Missing selection was substituted with a discovered neighbour.");
            }
            catch (InvalidOperationException) { }
            var pairing = await backend.BeginPairingAsync("phone_cancel", timeout.Token);
            _ = await KdeConnectProtocol.ReadAsync(stream, timeout.Token);
            backend.CancelSetupPairing(pairing with { ExpiresAt = pairing.ExpiresAt.AddSeconds(-1) });
            TestAssert.That((await backend.GetStatusAsync()).CandidateReachable,
                "Cleanup for a different selection closed this request.");
            var cancelled = PairingBarrier(backend, "phone_cancel", "failed");
            backend.CancelSetupPairing(pairing);
            await cancelled;
            await AssertClosedAsync(stream, "Setup cancellation left its TLS listener connection open.");
            TestAssert.That(!backend.HasPairedPeers && (await backend.GetStatusAsync()).Listening,
                "Cancelling setup trusted a phone or stopped the pre-existing backend listener.");

            var incoming = await ConnectIncomingPhoneAsync(backend, "phone_cancel", certificate);
            using var incomingClient = incoming.Client; using var incomingStream = incoming.Stream;
            var requested = PairingBarrier(backend, "phone_cancel", "requested");
            await RequestPairingAsync(incomingStream);
            await requested;
            backend.CancelSetupPairing(pairing);
            TestAssert.That((await backend.GetStatusAsync()).CandidateReachable,
                "Setup cleanup cancelled an incoming operation it did not own.");
            try
            {
                await backend.BeginPairingAsync("phone_cancel", timeout.Token);
                throw new Exception("Setup adopted an incoming request.");
            }
            catch (InvalidOperationException) { }
            await backend.ConfirmPairingAsync("phone_cancel", false, timeout.Token);
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static async Task PairingBarrier(KdeConnectDirectBackend backend, string deviceId, string state)
    {
        var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void Handler(KdeConnectPairingEvent value)
        {
            if (value.DeviceId == deviceId && value.State == state) reached.TrySetResult();
        }
        backend.PairingChanged += Handler;
        try { await reached.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
        finally { backend.PairingChanged -= Handler; }
    }

    private static async Task<KdeConnectStatus> WaitForStatusAsync(KdeConnectDirectBackend backend,
        Func<KdeConnectStatus, bool> predicate)
    {
        var reached = new TaskCompletionSource<KdeConnectStatus>(TaskCreationOptions.RunContinuationsAsynchronously);
        void Handler(KdeConnectStatus value) { if (predicate(value)) reached.TrySetResult(value); }
        backend.StatusChanged += Handler;
        try
        {
            var current = await backend.GetStatusAsync();
            return predicate(current) ? current : await reached.Task.WaitAsync(TimeSpan.FromSeconds(5));
        }
        finally { backend.StatusChanged -= Handler; }
    }

    private static async Task RequestPairingAsync(SslStream stream)
    {
        await stream.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair", new JsonObject {
            ["pair"] = true, ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() }));
    }

    private static async Task<KdeConnectPairing> WaitForPairingAsync(KdeConnectDirectBackend backend)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (true)
        {
            try { return await backend.BeginPairingAsync(timeout.Token); }
            catch (InvalidOperationException)
            {
                try { await Task.Delay(20, timeout.Token); }
                catch (OperationCanceledException error) { throw new InvalidOperationException(
                    "Paarung wurde nicht rechtzeitig sichtbar. KDE-Debug:\n" + backend.DebugLogForTest(), error); }
            }
            catch (OperationCanceledException error) { throw new InvalidOperationException(
                "Paarung wurde nicht rechtzeitig sichtbar. KDE-Debug:\n" + backend.DebugLogForTest(), error); }
        }
    }

    private static async Task<KdeConnectStatus> WaitForDeviceAsync(KdeConnectDirectBackend backend, string deviceId)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (true)
        {
            var status = await backend.GetStatusAsync(timeout.Token);
            if (status.DeviceId == deviceId && status.Available) return status;
            await Task.Delay(20, timeout.Token);
        }
    }

    private static async Task AssertClosedAsync(Stream stream, string message)
    {
        var buffer = new byte[4096];
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            while (await stream.ReadAsync(buffer, timeout.Token) != 0) { }
        }
        catch (Exception error) when (error is IOException or ObjectDisposedException or AuthenticationException) { }
        catch (OperationCanceledException) { throw new InvalidOperationException(message); }
    }

    private static async Task<(TcpClient Client, SslStream Stream)> ConnectIncomingPhoneAsync(
        KdeConnectDirectBackend backend, string phoneId, X509Certificate2 certificate)
    {
        var client = new TcpClient(AddressFamily.InterNetwork);
        await client.ConnectAsync(IPAddress.Loopback, backend.ListenerPort);
        var network = client.GetStream();
        await network.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
            KdeConnectProtocol.IdentityBody(phoneId, "Pixel", KdeConnectProtocol.FirstPort, backend.LocalDeviceId)));
        var tls = new SslStream(network, false, (_, _, _, _) => true);
        await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions {
            ServerCertificate = certificate, ClientCertificateRequired = true,
            EnabledSslProtocols = SslProtocols.Tls12,
            CertificateRevocationCheckMode = X509RevocationMode.NoCheck });
        _ = await KdeConnectProtocol.ReadAsync(tls, CancellationToken.None);
        await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
            PhoneIdentity(phoneId, KdeConnectProtocol.FirstPort)));
        return (client, tls);
    }

    private static async Task<KdeConnectStatus> WaitForGenerationAsync(KdeConnectDirectBackend backend, int minimum)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while (true)
        {
            var status = await backend.GetStatusAsync(timeout.Token);
            if (status.ConnectionGeneration >= minimum) return status;
            await Task.Delay(20, timeout.Token);
        }
    }

    private static JsonObject PhoneIdentity(string id, int port, bool history = false) => new()
    {
        ["deviceId"] = id, ["deviceName"] = "Pixel", ["protocolVersion"] = KdeConnectProtocol.Version,
        ["deviceType"] = "phone", ["tcpPort"] = port,
        ["incomingCapabilities"] = history
            ? new JsonArray(KdeConnectProtocol.SmsRequest, KdeConnectProtocol.SmsRequestConversations,
                KdeConnectProtocol.SmsRequestConversation)
            : new JsonArray(KdeConnectProtocol.SmsRequest),
        ["outgoingCapabilities"] = new JsonArray(KdeConnectProtocol.SmsMessages)
    };

    private static KdeConnectPacket SmsMessagesPacket(IEnumerable<JsonObject> rows) => new(1,
        KdeConnectProtocol.SmsMessages, new JsonObject { ["version"] = 2,
            ["messages"] = new JsonArray(rows.Select(value => (JsonNode)value).ToArray()) });

    private static JsonObject SmsRow(long thread, long? id, string text, int type, int smsEvent) => new()
    {
        ["_id"] = id, ["thread_id"] = thread,
        ["addresses"] = new JsonArray(new JsonObject { ["address"] = "+491701234567" }),
        ["body"] = text, ["date"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
        ["type"] = type, ["read"] = 1, ["sub_id"] = 0, ["event"] = smsEvent
    };

    private static TcpListener BindKdeListener()
    {
        for (var port = KdeConnectProtocol.FirstPort; port <= KdeConnectProtocol.LastPort; port++)
        {
            var listener = new TcpListener(IPAddress.Loopback, port);
            try { listener.Start(); return listener; }
            catch (SocketException) { listener.Stop(); }
        }
        throw new InvalidOperationException("Kein KDE-Connect-Testport ist frei.");
    }

    private static X509Certificate2 Certificate(string name)
    {
        using var key = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var request = new CertificateRequest("CN=" + name, key, HashAlgorithmName.SHA256);
        using var generated = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(1));
#pragma warning disable SYSLIB0057
        return new X509Certificate2(generated.Export(X509ContentType.Pfx), (string?)null,
            X509KeyStorageFlags.UserKeySet | X509KeyStorageFlags.Exportable);
#pragma warning restore SYSLIB0057
    }

    private sealed class TestProtector : IKdeConnectSecretProtector
    {
        private readonly byte[] key = SHA256.HashData(Encoding.UTF8.GetBytes("portable-test-key"));
        public byte[] Protect(byte[] plain) => Transform(plain);
        public byte[] Unprotect(byte[] cipher) => Transform(cipher);
        private byte[] Transform(byte[] value) => value.Select((item, index) => (byte)(item ^ key[index % key.Length])).ToArray();
    }

    private sealed class FragmentedStream(byte[] bytes) : MemoryStream(bytes)
    {
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
            base.ReadAsync(buffer[..Math.Min(1, buffer.Length)], cancellationToken);
    }
}
