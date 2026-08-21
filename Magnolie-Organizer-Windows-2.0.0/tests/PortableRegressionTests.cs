using System.Security.Cryptography;
using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using System.Collections.Concurrent;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PortableRegressionTests
{
internal static async Task RunAsync()
{
var root = Path.Combine(Path.GetTempPath(), $"magnolie-core-test-{Guid.NewGuid():N}");
try
{
    var store = new AtomicStore();
    var paths = new WindowsPaths(root);
    paths.EnsureDirectories();
    Check(PhoneUri.Build("phone", "0203 123456", "DE", false) ==
          "tel:+49203123456", "sichere nationale tel:-URI");
    Check(PhoneUri.Build("teams-call", "+49 170 1234567", "DE", true) ==
          "msteams:/l/call/0/0?users=4%3A%2B491701234567", "Teams-Anruf-URI");
    Check(PhoneUri.Build("teams-call", "+49 170 1234567", "DE", false) == "" &&
          PhoneUri.Build("phone", "++49 170 1234567", "DE", false) == "" &&
          PhoneUri.Build("phone", "0203;calc", "DE", false) == "" &&
          PhoneUri.Build("phone", "+1234567890123456", "DE", false) == "",
        "Teams-Verfügbarkeit und Rufnummerngrenzen");
    const string first = "{\"termine\":[],\"notizen\":[]}";
    const string second = "{\"termine\":[{\"titel\":\"Probe\"}],\"notizen\":[]}";
    store.Write(paths.Data, first);
    Check(store.Read(paths.Data) == first, "atomarer Erstdurchlauf");
    store.Write(paths.Data, second);
    Check(store.Read(paths.Data) == second, "atomarer Ersatz");
    var backup = store.Backup(paths.Data, paths.Backups);
    Check(store.Read(backup) == second, "Sicherung");

    var alicePrivate = Convert.FromHexString("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a");
    var alicePublic = Convert.FromHexString("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a");
    var bobPrivate = Convert.FromHexString("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb");
    var bobPublic = Convert.FromHexString("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f");
    var shared = MagnolienbaumCrypto.X25519(alicePrivate, bobPublic);
    Check(Convert.ToHexString(shared).ToLowerInvariant() == "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742" &&
          MagnolienbaumCrypto.X25519(bobPrivate, alicePublic).SequenceEqual(shared), "X25519 RFC/Python-Golden-Vector");
    var partnerKey = MagnolienbaumCrypto.PartnerKey(alicePrivate, bobPublic, "alpha", "beta");
    Check(Convert.ToHexString(partnerKey).ToLowerInvariant() == "a9640d44146293151db12fceae87087c85bbd7885298fe28e9238eb709b69959",
        "HKDF-SHA256 Python-Golden-Vector");
    Check(MagnolienbaumCrypto.PairingCode(alicePublic, bobPublic) == "353 739" &&
          MagnolienbaumCrypto.PairingCode(bobPublic, alicePublic) == "353 739", "Pairingcode ist symmetrisch und Python-kompatibel");
    Check(MagnolienbaumCrypto.Fingerprint(alicePublic) == "55B2-E4C0-B844-32D9", "Fingerabdruck Python-Golden-Vector");
    var canonicalNode = JsonNode.Parse("""{"z":"Grüße 😀","a":[true,null,3]}""")!;
    Check(System.Text.Encoding.UTF8.GetString(MagnolienbaumCrypto.Canonical(canonicalNode)) ==
          "{\"a\":[true,null,3],\"z\":\"Gr\\u00fc\\u00dfe \\ud83d\\ude00\"}", "kanonisches Python-JSON");
    var pythonCipher = new JsonObject { ["magnolie"] = "baum-1", ["von"] = "alpha", ["zaehler"] = 7,
        ["nonce"] = "AAECAwQFBgcICQoL", ["daten"] = "/JTVW/7t8SZhakNrEgpgGpkANSbkz9aXnN9y2WciNOKK5KSZ/F3z1wiEAceCuAQHFnvtx8uF" };
    var openedBaum = MagnolienbaumCrypto.DecryptBaum1(partnerKey, pythonCipher, "alpha", 6, out var openedCounter);
    Check(openedCounter == 7 && openedBaum["titel"]?.GetValue<string>() == "Grüße" && openedBaum["art"]?.GetValue<string>() == "aufgabe",
        "AES-GCM baum-1 Python-Golden-Vector");
    try { _ = MagnolienbaumCrypto.DecryptBaum1(partnerKey, pythonCipher, "alpha", 7, out _); throw new InvalidOperationException("Replay wurde angenommen"); }
    catch (CryptographicException) { }

    var treePaths = new WindowsPaths(Path.Combine(root, "baum")); treePaths.EnsureDirectories();
    byte[] ProtectTreeSecret(byte[] value) => value.Select(item => (byte)(item ^ 0xa5)).ToArray();
    var treeStore = new MagnolienbaumStore(treePaths, protectSecret: ProtectTreeSecret, unprotectSecret: ProtectTreeSecret);
    var treeState = treeStore.LoadOrCreate();
    var originalId = treeState["kennung"]!.GetValue<string>();
    var persistedTree = File.ReadAllText(treePaths.Baum);
    Check(!persistedTree.Contains("\"geheim\"", StringComparison.Ordinal) &&
          !persistedTree.Contains(treeState["geheim"]!.GetValue<string>(), StringComparison.Ordinal),
        "Baum-Privatschlüssel wird nur geschützt persistiert");
    Check(new MagnolienbaumStore(treePaths, protectSecret: ProtectTreeSecret, unprotectSecret: ProtectTreeSecret)
        .LoadOrCreate()["kennung"]!.GetValue<string>() == originalId, "Baumidentität bleibt persistent");
    treeStore.SaveInbox(new JsonArray(new JsonObject { ["id"] = "in-1", ["art"] = "termin" }));
    treeStore.SaveOutbox(new JsonArray(new JsonObject { ["id"] = "out-1", ["versuche"] = 2 }));
    Check(treeStore.LoadInbox().Count == 1 && treeStore.LoadOutbox()[0]!["versuche"]!.GetValue<int>() == 2, "Inbox und Outbox bleiben persistent");
    treeState["partner"]!.AsArray().Add(new JsonObject { ["kennung"] = "alter-v2-partner", ["name"] = "Alt",
        ["oeffentlich"] = Convert.ToBase64String(alicePublic), ["paarungsart"] = "datei-v2", ["protokoll"] = "baum-1" });
    treeStore.SaveState(treeState);
    Check(new MagnolienbaumStore(treePaths, protectSecret: ProtectTreeSecret, unprotectSecret: ProtectTreeSecret)
        .LoadOrCreate()["partner"]![0]!["protokoll"]!.GetValue<string>() == "baum-fs1",
        "bereits persistierte v2-Partner werden auf FS1 migriert");
    var legacyTreePaths = new WindowsPaths(Path.Combine(root, "baum-alt")); legacyTreePaths.EnsureDirectories();
    new AtomicStore().Write(legacyTreePaths.Baum, treeState.ToJsonString());
    var migratedTree = new MagnolienbaumStore(legacyTreePaths, protectSecret: ProtectTreeSecret,
        unprotectSecret: ProtectTreeSecret).LoadOrCreate();
    Check(migratedTree["geheim"]!.GetValue<string>() == treeState["geheim"]!.GetValue<string>() &&
          !File.ReadAllText(legacyTreePaths.Baum).Contains("\"geheim\"", StringComparison.Ordinal),
        "bestehender Baum-Privatschlüssel wird ohne Identitätswechsel geschützt migriert");
    TelefonDeviceStatusContract.ValidateRequest(JsonNode.Parse("""{"request_id":"90bb6588-b4b5-451d-aa80-3d5f12a032e7"}""")!);
    TelefonDeviceStatusContract.ValidateReport(JsonNode.Parse("""{"request_id":"90bb6588-b4b5-451d-aa80-3d5f12a032e7","model":"Pixel 9","manufacturer":"Google","os_name":"Android","os_version":"16","battery_percent":73,"charging":"charging","captured_ms":1786617000000}""")!);
    foreach (var invalidStatus in new[]
    {
        """{"request_id":"90bb6588-b4b5-451d-aa80-3d5f12a032e7","model":"Pixel","manufacturer":"Google","os_name":"Android","os_version":"16","battery_percent":101,"charging":"charging","captured_ms":1}""",
        """{"request_id":"90bb6588-b4b5-451d-aa80-3d5f12a032e7","model":"Pixel","manufacturer":"Google","os_name":"Android","os_version":"16","battery_percent":50,"charging":"unknown","captured_ms":1,"imei":"123"}"""
    })
    {
        try { TelefonDeviceStatusContract.ValidateReport(JsonNode.Parse(invalidStatus)!); throw new InvalidOperationException("Ungültiger Gerätestatus wurde angenommen"); }
        catch (InvalidDataException) { }
    }

    var damagedPaths = new WindowsPaths(Path.Combine(root, "baum-beschaedigt")); damagedPaths.EnsureDirectories();
    var damagedState = new JsonObject { ["kennung"] = "lokal", ["name"] = "Lokal",
        ["geheim"] = Convert.ToBase64String(alicePrivate), ["oeffentlich"] = Convert.ToBase64String(alicePublic),
        ["an"] = false, ["port"] = 8737, ["partner"] = new JsonArray(new JsonObject
        { ["kennung"] = "vergiftet", ["name"] = "Defekt", ["oeffentlich"] = "kein-base64", ["port"] = 8737 }) };
    new AtomicStore().Write(damagedPaths.Baum, damagedState.ToJsonString());
    try { _ = new MagnolienbaumStore(damagedPaths).LoadOrCreate(); throw new InvalidOperationException("Beschädigter Partner wurde geladen"); }
    catch (InvalidDataException) { }

    var pairingState = new JsonObject { ["kennung"] = "alpha", ["name"] = "Küche", ["geheim"] = Convert.ToBase64String(alicePrivate),
        ["oeffentlich"] = Convert.ToBase64String(alicePublic), ["an"] = true, ["port"] = 8737, ["partner"] = new JsonArray() };
    var pairingFile = MagnolienbaumPairing.CreateFile(pairingState, "127.0.0.1", 8737, 1700000000, Enumerable.Range(0, 32).Select(i => (byte)i).ToArray());
    Check(pairingFile["paarung"]!.GetValue<string>() == "v86cQ3N7M7VVXK6Obxmo2hx0DX7VajXeO4gxvvaRCDA" &&
          pairingFile["mac"]!.GetValue<string>() == "47KiVhsmFfRVaMBZ3e8lYfZJnWBAjIwp_c7pxL7X3bU", "Paarungsdatei-v2 Python-Golden-Vector");
    _ = MagnolienbaumPairing.ValidateFile(pairingFile, 1700000001);
    var requestState = new JsonObject { ["kennung"] = "beta", ["name"] = "Werkstatt", ["geheim"] = Convert.ToBase64String(bobPrivate),
        ["oeffentlich"] = Convert.ToBase64String(bobPublic), ["an"] = true, ["port"] = 8737, ["partner"] = new JsonArray() };
    var pairRequest = MagnolienbaumPairing.BuildRequest(requestState, pairingFile, Enumerable.Repeat((byte)9, 32).ToArray(), 1700000001);
    var pairResponse = MagnolienbaumPairing.AcceptRequest(pairingState, pairRequest, "127.0.0.1", 1700000001);
    MagnolienbaumPairing.ValidateResponse(pairingFile, pairRequest, pairResponse);
    var repeatedResponse = MagnolienbaumPairing.AcceptRequest(pairingState, pairRequest, "127.0.0.1", 1700000002);
    Check(JsonNode.DeepEquals(pairResponse, repeatedResponse) && pairingState["paarungen"]!.AsArray().Count == 0,
        "v2-Paarung ist authentisiert, verbraucht und identisch wiederholbar");

    var aliceFsPartner = new JsonObject { ["kennung"] = "beta", ["oeffentlich"] = Convert.ToBase64String(bobPublic) };
    var bobFsPartner = new JsonObject { ["kennung"] = "alpha", ["oeffentlich"] = Convert.ToBase64String(alicePublic) };
    var authKey = MagnolienbaumFs1.AuthKey(pairingState, aliceFsPartner);
    Check(Convert.ToHexString(authKey).ToLowerInvariant() == "356ad05aa70a0919b0f69598e3123e518fc5b04d721f24f6727ac6f6490c8414",
        "FS1 statischer Auth-Key Python-Golden-Vector");
    using var fsStart = MagnolienbaumFs1.BuildStart(pairingState, aliceFsPartner, Enumerable.Range(0, 16).Select(i => (byte)i).ToArray(),
        Enumerable.Range(0x10, 32).Select(i => (byte)i).ToArray());
    var expectedFsStart = JsonNode.Parse("""{"magnolie":"baum-fs1-start","von":"alpha","an":"beta","sid":"AAECAwQFBgcICQoLDA0ODw==","epk":"2J47rXlDfb7Z+ENBgwT0YP8Fx/6B/kqVd6gEy5Nn/2Y=","mac":"6xiEgPhYn7dLKaZnEkXxVCB43KR2A+OMZ/HMQdFYnj8="}""");
    Check(JsonNode.DeepEquals(fsStart.Message, expectedFsStart), "FS1-Start Python-Golden-Vector");
    var fixedResponderPrivate = Enumerable.Range(0x20, 32).Select(i => (byte)i).ToArray();
    var builtFsResponse = MagnolienbaumFs1.BuildResponse(requestState, bobFsPartner, fsStart.Message, fixedResponderPrivate);
    using var receiverFsSession = builtFsResponse.Session;
    Check(fixedResponderPrivate.All(value => value == 0), "ephemerer Empfänger-Privatschlüssel wird genullt");
    var expectedFsResponse = JsonNode.Parse("""{"magnolie":"baum-fs1-antwort","von":"beta","an":"alpha","sid":"AAECAwQFBgcICQoLDA0ODw==","epk":"NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ=","startHash":"lrIhzdOjhHv1eSmwfXlPdb27oEwJLJhBE0iuKtBJnbg=","mac":"xLonfvVlcgilc6uXReEScZP7vNHQmcCY8gsHOIySYHs="}""");
    Check(JsonNode.DeepEquals(builtFsResponse.Response, expectedFsResponse), "FS1-Antwort Python-Golden-Vector");
    using var senderFsSession = MagnolienbaumFs1.OpenResponse(pairingState, aliceFsPartner, fsStart.Message,
        builtFsResponse.Response, fsStart.EphemeralPrivate);
    Check(Convert.ToHexString(senderFsSession.Transcript).ToLowerInvariant() == "171e823ebffc8c23accdf82c3eef3f0ae51bdb3efe4ee155ecb1ccd36dc060dd" &&
          Convert.ToHexString(senderFsSession.EncryptionKey).ToLowerInvariant() == "99f68ecc7ac980a4956613a37908671ec521499d464454dcb2492800e162b152" &&
          Convert.ToHexString(senderFsSession.AcknowledgementKey).ToLowerInvariant() == "cd4ce9bae0f00eb1c25fad1642c31a12b261fb79061e0c4d72b7dad9b6eda2e5" &&
          senderFsSession.EncryptionKey.SequenceEqual(receiverFsSession.EncryptionKey), "FS1-Transkript, kenc und kack Python-Golden-Vectors");
    var fsEnvelope = MagnolienbaumFs1.BuildEnvelope(senderFsSession, "alpha", "beta",
        JsonNode.Parse("""{"art":"aufgabe","titel":"Grüße","id":"fs-1"}""")!, "QEFCQ0RFRkdISUpLTE1OTw==",
        Enumerable.Range(0xa0, 12).Select(i => (byte)i).ToArray());
    var expectedFsEnvelope = JsonNode.Parse("""{"magnolie":"baum-fs1","von":"alpha","an":"beta","sid":"AAECAwQFBgcICQoLDA0ODw==","mid":"QEFCQ0RFRkdISUpLTE1OTw==","nonce":"oKGio6Slpqeoqaqr","daten":"wMdcT0tsztP3RoSfaglsnGtwJnoT6eMiQxIC22ojvc2wTyZKWISsdCC2iIH48kr8xXU/mRkWicEEuXXaDuRkAwoNvGtfe/c="}""");
    Check(JsonNode.DeepEquals(fsEnvelope, expectedFsEnvelope), "FS1-Datenumschlag und AAD Python-Golden-Vector");
    var openedFs = MagnolienbaumFs1.OpenEnvelope(receiverFsSession, "beta", "alpha", fsEnvelope);
    Check(openedFs.TransportId == "QEFCQ0RFRkdISUpLTE1OTw==" && openedFs.Content["titel"]!.GetValue<string>() == "Grüße",
        "FS1-Datenumschlag wird auf Empfängerseite geöffnet");
    try { _ = MagnolienbaumFs1.OpenEnvelope(receiverFsSession, "beta", "alpha", fsEnvelope); throw new InvalidOperationException("FS1-Sitzung zweimal verwendet"); }
    catch (CryptographicException) { }
    var fsAck = MagnolienbaumFs1.BuildAcknowledgement(receiverFsSession, fsEnvelope);
    var expectedFsAck = JsonNode.Parse("""{"magnolie":"baum-fs1-ack","sid":"AAECAwQFBgcICQoLDA0ODw==","mid":"QEFCQ0RFRkdISUpLTE1OTw==","mac":"zmN4+PbFB9D1dOFlwrJx5FAMk4gvOe7O3iqE4wqBT7s="}""");
    Check(JsonNode.DeepEquals(fsAck, expectedFsAck) && MagnolienbaumFs1.VerifyAcknowledgement(senderFsSession, fsEnvelope, fsAck),
        "FS1-Ack Python-Golden-Vector und Verifikation");
    var senderKencReference = senderFsSession.EncryptionKey; var receiverKackReference = receiverFsSession.AcknowledgementKey;
    senderFsSession.Dispose(); receiverFsSession.Dispose(); fsStart.Dispose();
    Check(senderKencReference.All(value => value == 0) && receiverKackReference.All(value => value == 0) &&
          fsStart.EphemeralPrivate.All(value => value == 0), "verwaltete FS1-Sitzungs- und Ephemeralschlüssel werden genullt");
    CryptographicOperations.ZeroMemory(authKey);

    var networkPathsA = new WindowsPaths(Path.Combine(root, "netz-a")); var networkPathsB = new WindowsPaths(Path.Combine(root, "netz-b"));
    networkPathsA.EnsureDirectories(); networkPathsB.EnsureDirectories();
    var portA = FreeTcpPort(); var portB = FreeTcpPort(); while (portB == portA) portB = FreeTcpPort();
    var networkStoreA = new MagnolienbaumStore(networkPathsA); var networkStoreB = new MagnolienbaumStore(networkPathsB);
    var networkStateA = networkStoreA.LoadOrCreate(); var networkStateB = networkStoreB.LoadOrCreate();
    networkStateA["name"] = "Netz A"; networkStateA["port"] = portA; networkStateA["an"] = false;
    networkStateB["name"] = "Netz B"; networkStateB["port"] = portB; networkStateB["an"] = false;
    networkStoreA.SaveState(networkStateA); networkStoreB.SaveState(networkStateB);
    var eventsA = new ConcurrentQueue<(string Name, JsonNode Payload)>(); var eventsB = new ConcurrentQueue<(string Name, JsonNode Payload)>();
    using (var coordinatorA = new MagnolienbaumCoordinator(networkPathsA, (name, payload) => { eventsA.Enqueue((name, JsonSerializer.SerializeToNode(payload)!)); return Task.CompletedTask; }))
    using (var coordinatorB = new MagnolienbaumCoordinator(networkPathsB, (name, payload) => { eventsB.Enqueue((name, JsonSerializer.SerializeToNode(payload)!)); return Task.CompletedTask; }))
    {
        await coordinatorA.SwitchAsync(true, "Netz A"); await coordinatorB.SwitchAsync(true, "Netz B");
        var poisonedPairing = new JsonObject { ["kennung"] = "angreifer", ["name"] = "Angreifer",
            ["oeffentlich"] = "ungueltig", ["port"] = 8737 };
        Check(coordinatorB.HandleProtocolRequest("/magnolie/v1/paarung", poisonedPairing, "127.0.0.1").Status == 403 &&
              networkStoreB.LoadOrCreate()["partner"]!.AsArray().Count == 0,
            "ungültige v1-Identität wird vor jeder Mutation abgewiesen");

        Check(coordinatorA.TryBeginConnection("127.0.0.1") && coordinatorA.TryBeginConnection("::ffff:127.0.0.1") &&
              coordinatorA.TryBeginConnection("127.0.0.1") && coordinatorA.TryBeginConnection("127.0.0.1") &&
              !coordinatorA.TryBeginConnection("::ffff:127.0.0.1"),
            "IPv4 und IPv4-gemappte IPv6-Adressen teilen das Vierer-Verbindungslimit");
        for (var connectionIndex = 0; connectionIndex < 4; connectionIndex++) coordinatorA.EndConnection("127.0.0.1");
        Check(Enumerable.Range(0, 8).All(_ => coordinatorA.RequestAllowed("192.0.2.1", true)) &&
              !coordinatorA.RequestAllowed("192.0.2.1", true) &&
              Enumerable.Range(0, 120).All(_ => coordinatorA.RequestAllowed("192.0.2.2", false)) &&
              !coordinatorA.RequestAllowed("192.0.2.2", false),
            "60-Sekunden-Limits entsprechen Linux für Paarung und allgemeine Anfragen");
        Check(MagnolienbaumCoordinator.MaxMessageBytes == 40 * 1024 * 1024 &&
              MagnolienbaumCoordinator.RequestBodyLimit("/magnolie/v1/nachricht") == 40 * 1024 * 1024 &&
              MagnolienbaumCoordinator.RequestBodyLimit("/magnolie/v2/nachricht") == 40 * 1024 * 1024 &&
              MagnolienbaumCoordinator.RequestBodyLimit("/magnolie/v2/sitzung") == 128 * 1024 &&
              MagnolienbaumCoordinator.RequestBodyAllowed("/magnolie/v2/nachricht", 40L * 1024 * 1024) &&
              !MagnolienbaumCoordinator.RequestBodyAllowed("/magnolie/v2/nachricht", 40L * 1024 * 1024 + 1) &&
              !MagnolienbaumCoordinator.RequestBodyAllowed("/magnolie/v2/nachricht", -1),
            "Magnolienbaum-Listener akzeptiert höchstens exakt 40 MiB Nachrichtentext");

        await coordinatorA.PairV1Async("127.0.0.1", portB, "");
        var pairEvent = eventsA.Last(item => item.Name == "App.baumPaarung").Payload;
        Check(pairEvent["ok"]!.GetValue<bool>() && pairEvent["code"]!.GetValue<string>().Length == 7,
            "Bridge-nahe v1-Paarung über echten TCP-HTTP-Listener: " + pairEvent.ToJsonString());
        var idA = networkStateA["kennung"]!.GetValue<string>(); var idB = networkStateB["kennung"]!.GetValue<string>();
        await coordinatorA.ConfirmAsync(idB, true); await coordinatorB.ConfirmAsync(idA, true);
        await coordinatorA.SendAsync(idB, "geraete_status", new JsonObject());
        Check(!eventsA.Last(item => item.Name == "App.baumGesendet").Payload["ok"]!.GetValue<bool>(),
            "Gerätestatusarten sind aus dem Magnolienbaum entfernt");
        await coordinatorA.SendAsync(idB, "aufgabe", JsonNode.Parse("""{"id":"task-1","titel":"Netzprobe"}""")!);
        await coordinatorB.ReportStatusAsync();
        var statusB = eventsB.Last(item => item.Name == "App.baumStand").Payload;
        Check(statusB["eingang"]!.AsArray().Any(item => item!["inhalt"]!["titel"]!.GetValue<string>() == "Netzprobe") &&
              eventsA.Last(item => item.Name == "App.baumGesendet").Payload["zugestellt"]!.GetValue<int>() == 1,
            "baum-1 TCP-Transport, persistente Inbox und Bridge-Ergebnis");
        Check(networkStoreB.LoadInbox().Count == 1 && networkStoreB.LoadInbox()[0]!["von"]!.GetValue<string>() == idA,
            "Netzempfang wird vor HTTP-Erfolg persistent gespeichert");

        var inboxBeforeParallelDelivery = networkStoreB.LoadInbox().Count;
        var outboxField = typeof(MagnolienbaumCoordinator).GetField("outbox",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        var liveOutbox = (JsonArray)outboxField.GetValue(coordinatorA)!;
        liveOutbox.Add(new JsonObject { ["id"] = "parallel-1", ["transportId"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)),
            ["an"] = idB, ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["art"] = "aufgabe", ["id"] = "parallel-1", ["titel"] = "Nur einmal" },
            ["versuche"] = 0, ["zuletzt"] = "", ["angelegt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") });
        var maintainMethod = typeof(MagnolienbaumCoordinator).GetMethod("MaintainOutboxAsync",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        var parallelFirst = (Task)maintainMethod.Invoke(coordinatorA, new object[] { 0, CancellationToken.None })!;
        var parallelSecond = (Task)maintainMethod.Invoke(coordinatorA, new object[] { 0, CancellationToken.None })!;
        await Task.WhenAll(parallelFirst, parallelSecond);
        Check(networkStoreB.LoadInbox().Count == inboxBeforeParallelDelivery + 1,
            "parallele Outbox-Wartung stellt denselben Eintrag genau einmal zu");

        var inboxBeforeFifo = networkStoreB.LoadInbox().Count;
        var fifoFirst = new JsonObject { ["id"] = "fifo-1", ["transportId"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)),
            ["an"] = idB, ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["art"] = "aufgabe", ["id"] = "fifo-1", ["titel"] = "FIFO eins" },
            ["versuche"] = 1, ["zuletzt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), ["angelegt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") };
        liveOutbox.Add(fifoFirst);
        liveOutbox.Add(new JsonObject { ["id"] = "fifo-2", ["transportId"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)),
            ["an"] = idB, ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["art"] = "aufgabe", ["id"] = "fifo-2", ["titel"] = "FIFO zwei" },
            ["versuche"] = 0, ["zuletzt"] = "", ["angelegt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") });
        await (Task)maintainMethod.Invoke(coordinatorA, new object[] { 0, CancellationToken.None })!;
        Check(networkStoreB.LoadInbox().Count == inboxBeforeFifo,
            "jüngerer Ausgang überholt keinen noch nicht fälligen Partner-Eintrag");
        fifoFirst["zuletzt"] = DateTime.Now.AddMinutes(-2).ToString("yyyy-MM-dd HH:mm:ss");
        await (Task)maintainMethod.Invoke(coordinatorA, new object[] { 0, CancellationToken.None })!;
        await (Task)maintainMethod.Invoke(coordinatorA, new object[] { 0, CancellationToken.None })!;
        var fifoMessages = networkStoreB.LoadInbox().OfType<JsonObject>().Skip(inboxBeforeFifo).ToArray();
        Check(fifoMessages.Length == 2 && fifoMessages[0]["inhalt"]!["titel"]!.GetValue<string>() == "FIFO eins" &&
              fifoMessages[1]["inhalt"]!["titel"]!.GetValue<string>() == "FIFO zwei",
            "partnerbezogene Ausgangswarteschlange bleibt in Zählerreihenfolge");

        var inboxField = typeof(MagnolienbaumCoordinator).GetField("inbox",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
        var savedInbox = ((JsonArray)inboxField.GetValue(coordinatorB)!).DeepClone().AsArray();
        var fullInbox = new JsonArray(Enumerable.Range(0, 500).Select(index => (JsonNode)new JsonObject
            { ["id"] = $"voll-{index}", ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["titel"] = $"Alt {index}" } }).ToArray());
        inboxField.SetValue(coordinatorB, fullInbox); networkStoreB.SaveInbox(fullInbox);
        var receiverState = networkStoreB.LoadOrCreate();
        var receiverPartner = receiverState["partner"]!.AsArray().OfType<JsonObject>().Single(item => item["kennung"]!.GetValue<string>() == idA);
        var fullKey = MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(receiverState["geheim"]!.GetValue<string>()),
            Convert.FromBase64String(receiverPartner["oeffentlich"]!.GetValue<string>()), idB, idA);
        var rejectedAtCapacity = MagnolienbaumCrypto.EncryptBaum1(fullKey, idA,
            receiverPartner["zaehler_rein"]!.GetValue<long>() + 1, new JsonObject { ["art"] = "aufgabe", ["titel"] = "Nicht verdrängen" });
        Check(coordinatorB.HandleProtocolRequest("/magnolie/v1/nachricht", rejectedAtCapacity, "127.0.0.1").Status == 503 &&
              ((JsonArray)inboxField.GetValue(coordinatorB)!).Count == 500 &&
              ((JsonArray)inboxField.GetValue(coordinatorB)!)[0]!["id"]!.GetValue<string>() == "voll-0",
            "volle Magnolienbaum-Inbox wird retrybar abgewiesen statt alte Post zu löschen");
        CryptographicOperations.ZeroMemory(fullKey);
        inboxField.SetValue(coordinatorB, savedInbox); networkStoreB.SaveInbox(savedInbox);
        Check(coordinatorB.HandleProtocolRequest("/magnolie/v1/nachricht", rejectedAtCapacity, "127.0.0.1").Status == 200,
            "nach Freigabe der Inbox bleibt dieselbe zuvor abgewiesene Zählernachricht zustellbar");

        var livePairingFile = coordinatorA.CreatePairingFile("127.0.0.1", portA);
        await coordinatorB.ImportPairingFileAsync(livePairingFile);
        Check(eventsB.Last(item => item.Name == "App.baumPaarungsdatei").Payload["ok"]!.GetValue<bool>(),
            "v2-Paarung über echten TCP-HTTP-Listener");
        await coordinatorA.SendAsync(idB, "notiz", JsonNode.Parse("""{"freigabeId":"fs-a","titel":"FS von A"}""")!);
        await coordinatorB.SendAsync(idA, "termin", JsonNode.Parse("""{"id":"fs-b","titel":"FS von B"}""")!);
        await coordinatorA.ReportStatusAsync(); await coordinatorB.ReportStatusAsync();
        var fsStatusA = eventsA.Last(item => item.Name == "App.baumStand").Payload;
        var fsStatusB = eventsB.Last(item => item.Name == "App.baumStand").Payload;
        Check(fsStatusA["partner"]![0]!["protokoll"]!.GetValue<string>() == "baum-fs1" &&
              fsStatusB["partner"]![0]!["protokoll"]!.GetValue<string>() == "baum-fs1" &&
              fsStatusA["eingang"]!.AsArray().Any(item => item!["inhalt"]!["titel"]!.GetValue<string>() == "FS von B") &&
              fsStatusB["eingang"]!.AsArray().Any(item => item!["inhalt"]!["titel"]!.GetValue<string>() == "FS von A"),
            "baum-fs1 sendet in echten Zwei-Instanzen-Tests bidirektional");

        var liveStateA = networkStoreA.LoadOrCreate(); var liveStateB = networkStoreB.LoadOrCreate();
        var livePartnerB = liveStateA["partner"]!.AsArray().OfType<JsonObject>().Single(item => item["kennung"]!.GetValue<string>() == idB);
        var inboxBeforeDuplicate = networkStoreB.LoadInbox().Count;
        const string duplicateMid = "EBESExQVFhcYGRobHB0eHw==";
        JsonObject SendDirectFs(string title, string source)
        {
            using var directStart = MagnolienbaumFs1.BuildStart(liveStateA, livePartnerB);
            var startResult = coordinatorB.HandleProtocolRequest("/magnolie/v2/sitzung", directStart.Message, source);
            Check(startResult.Status == 200, "direkter FS1-Sitzungsstart");
            using var directSession = MagnolienbaumFs1.OpenResponse(liveStateA, livePartnerB, directStart.Message,
                startResult.Body, directStart.EphemeralPrivate);
            var directEnvelope = MagnolienbaumFs1.BuildEnvelope(directSession, idA, idB,
                JsonNode.Parse($$"""{"art":"aufgabe","titel":"{{title}}"}""")!, duplicateMid);
            var messageResult = coordinatorB.HandleProtocolRequest("/magnolie/v2/nachricht", directEnvelope, source);
            Check(messageResult.Status == 200 && MagnolienbaumFs1.VerifyAcknowledgement(directSession, directEnvelope, messageResult.Body),
                "direkte FS1-Nachricht erhält gültige Quittung");
            return messageResult.Body;
        }
        _ = SendDirectFs("Deduplizierte FS-Nachricht", "::ffff:127.0.0.1");
        _ = SendDirectFs("Deduplizierte FS-Nachricht", "127.0.0.1");
        Check(networkStoreB.LoadInbox().Count == inboxBeforeDuplicate + 1,
            "bekannte FS1-mid wird erneut quittiert, aber nicht erneut zugestellt");

        using (var boundStart = MagnolienbaumFs1.BuildStart(liveStateA, livePartnerB))
        {
            var boundResponse = coordinatorB.HandleProtocolRequest("/magnolie/v2/sitzung", boundStart.Message, "127.0.0.1");
            using var boundSession = MagnolienbaumFs1.OpenResponse(liveStateA, livePartnerB, boundStart.Message,
                boundResponse.Body, boundStart.EphemeralPrivate);
            var boundEnvelope = MagnolienbaumFs1.BuildEnvelope(boundSession, idA, idB,
                JsonNode.Parse("""{"art":"aufgabe","titel":"Quellbindung"}""")!, "ICEiIyQlJicoKSorLC0uLw==");
            Check(coordinatorB.HandleProtocolRequest("/magnolie/v2/nachricht", boundEnvelope, "127.0.0.2").Status == 403 &&
                  coordinatorB.HandleProtocolRequest("/magnolie/v2/nachricht", boundEnvelope, "127.0.0.1").Status == 403,
                "FS1-Sitzung ist an normalisierte Quell-IP gebunden und wird bei Fehlversuch verbraucht");
        }

        var livePartnerA = liveStateB["partner"]!.AsArray().OfType<JsonObject>().Single(item => item["kennung"]!.GetValue<string>() == idA);
        for (var sessionIndex = 0; sessionIndex < 64; sessionIndex++)
        {
            using var capacityStart = MagnolienbaumFs1.BuildStart(liveStateB, livePartnerA);
            Check(coordinatorA.HandleProtocolRequest("/magnolie/v2/sitzung", capacityStart.Message, "127.0.0.1").Status == 200,
                "FS1-Sitzung innerhalb der 64er-Grenze");
        }
        using (var excessiveStart = MagnolienbaumFs1.BuildStart(liveStateB, livePartnerA))
            Check(coordinatorA.HandleProtocolRequest("/magnolie/v2/sitzung", excessiveStart.Message, "127.0.0.1").Status == 403,
                "mehr als 64 offene FS1-Sitzungen werden abgewiesen");
        await coordinatorA.StopAsync(); await coordinatorB.StopAsync();
    }

    var encryption = new EncryptionService();
    var encrypted = encryption.Enable(second, "Rosenholz1896");
    Check(EncryptionService.IsEncrypted(encrypted), "Hüllenerkennung");
    var damagedEnvelopeMarker = JsonNode.Parse(encrypted)!.AsObject();
    damagedEnvelopeMarker["magnolie"] = "magnolie-verschluesselt-beschaedigt";
    try { _ = EncryptionService.IsEncrypted(damagedEnvelopeMarker.ToJsonString()); throw new InvalidOperationException("Beschädigte Kryptohülle wurde als Klartext erkannt"); }
    catch (CryptographicException) { }
    var unlocked = new EncryptionService().Unlock(encrypted, "Rosenholz1896");
    Check(unlocked == second, "DEK-Hülle öffnet sich");
    try
    {
        _ = new EncryptionService().Unlock(encrypted, "falsch");
        throw new InvalidOperationException("Falsches Kennwort wurde angenommen");
    }
    catch (CryptographicException) { }

    using var before = JsonDocument.Parse(encrypted);
    var changed = encryption.ChangePassword(encrypted, "Rosenholz1896", "Magnolie2026!");
    using var after = JsonDocument.Parse(changed);
    Check(before.RootElement.GetProperty("daten").GetString() ==
          after.RootElement.GetProperty("daten").GetString(), "Kennwortwechsel lässt Nutzdaten bytegleich");
    Check(encryption.Disable(changed, "Magnolie2026!") == second, "Kennwortschutz entfernen");

    var activeEncryption = new EncryptionService();
    Check(activeEncryption.Unlock(encrypted, "Rosenholz1896") == second, "aktive Datenschutzsitzung öffnen");
    var rewrapCandidate = activeEncryption.CloneUnlocked();
    var sessionChanged = rewrapCandidate.ChangePasswordWithSession(encrypted, "Magnolie2027!");
    Check(new EncryptionService().Unlock(sessionChanged, "Magnolie2027!") == second &&
          rewrapCandidate.DisableWithSession(sessionChanged) == second,
        "Kennwortwechsel und Entfernen verwenden die aktive Sitzung ohne altes Kennwort");

    const string pythonLegacy = """
        {
         "magnolie": "magnolie-verschluesselt",
         "fassung": 1,
         "verfahren": "AES-256-GCM/PBKDF2-SHA256",
         "runden": 50000,
         "salz": "AAECAwQFBgcICQoLDA0ODw==",
         "nonce": "AAECAwQFBgcICQoL",
         "daten": "jkBMBGvnqyXQ1f7fhyGHNj0NtJ7/altmNu/D9MZeermfsCY="
        }
        """;
    Check(new EncryptionService().Unlock(pythonLegacy, "Rosenholz1896") == "{\"probe\":\"Grüße\"}",
        "Python-Hülle der Fassung 1 ist kompatibel");

    var fullArchiveData = JsonNode.Parse("""
        {"version":6,"termine":[{"id":"t1","titel":"Grüße 東京","datum":"2026-08-11"}],
        "aufgaben":[{"id":"a1","titel":"Prüfen"}],
        "kontakte":[{"id":"k1","foto":"data:image/jpeg;base64,/9j/2Q==","emails":["a@example.test","b@example.test"],"unbekanntKontakt":{"zukunft":true}},
        {"id":"k2","foto":"data:image/png;base64,iVBORw0KGgo="},{"id":"k3","foto":"data:image/webp;base64,UklGRg=="},{"id":"k4","foto":"data:image/gif;base64,R0lGODlh"}],
        "notizen":[{"id":"n1","html":"<p>Bild</p>","anhaenge":[{"daten":"data:image/png;base64,iVBORw0KGgo="},{"daten":"data:application/pdf;base64,JVBERi0xLjQ="}]}],
        "notizgruppen":[{"id":"g1","name":"Alle"}],"notizbuecher":[{"id":"b1","gruppeId":"g1","name":"Buch"}],
        "jahrestage":[],"feiertage":[],"urlaube":[],"muelltermine":[],"personen":[{"id":"p1","name":"Mia"}],"schichten":[],"zyklusmarker":[],"tagmarken":[],
        "gesundheit":{"vitalwerte":[{"id":"v1","gewicht":70.5}]},"papierkorb":[{"art":"notiz","wert":{"anhaenge":[{"daten":"data:application/pdf;base64,JVBERi0xLjQ="}]}}],
        "tombstones":[{"id":"alt","geaendert":1}],"einstellungen":{"allgemein":{"tray":{"aktiv":true,"autostart":true},"sicherungsordner":"/fremd"},"sync":{"kalenderUids":["fremd"]}},
        "zukuenftigesFeld":{"unicode":"🪻","roh":[1,null,false]}}
        """)!.AsObject();
    var gesamtArchive = GesamtarchivService.Create(fullArchiveData, "windows", "2.0.0", "",
        DateTimeOffset.Parse("2026-08-11T12:34:56+00:00"));
    var archiveInfo = GesamtarchivService.Read(gesamtArchive);
    Check(JsonNode.DeepEquals(archiveInfo.Daten, fullArchiveData) && archiveInfo.Fotos == 4 && archiveInfo.Anhaenge == 3,
        "Gesamtarchiv-Vollmodell mit bytegleichen Data-URLs und unbekannten Feldern");
    Check(JsonNode.Parse(gesamtArchive)!["sha256"]!.GetValue<string>() ==
          "e17205be343f22cf24d379d954c2bfec0fbf62807143fb7af29e90fe1ba1a0c9",
        "gemeinsamer Python/.NET-Golden-Vector des kanonischen Vollmodells");
    var protectedArchive = GesamtarchivService.Create(fullArchiveData, "linux", "1.31.95", "Rosenholz1896");
    Check(JsonNode.DeepEquals(GesamtarchivService.Read(protectedArchive, "Rosenholz1896").Daten, fullArchiveData),
        "Linux/Windows-kompatible AES-GCM-Hülle für Gesamtarchive");
    try { _ = GesamtarchivService.Read(protectedArchive, "falsch"); throw new InvalidOperationException("Falsches Archivkennwort angenommen"); }
    catch (CryptographicException) { }
    var damagedArchive = JsonNode.Parse(gesamtArchive)!.AsObject();
    damagedArchive["daten"]!["termine"]![0]!["titel"] = "manipuliert";
    try { _ = GesamtarchivService.Read(damagedArchive.ToJsonString()); throw new InvalidOperationException("Archivhash-Manipulation angenommen"); }
    catch (InvalidDataException) { }
    damagedArchive = JsonNode.Parse(gesamtArchive)!.AsObject(); damagedArchive["fassung"] = 99;
    try { _ = GesamtarchivService.Read(damagedArchive.ToJsonString()); throw new InvalidOperationException("Unbekannte Archivfassung angenommen"); }
    catch (InvalidDataException) { }
    damagedArchive = JsonNode.Parse(gesamtArchive)!.AsObject(); damagedArchive["zusaetzlich"] = new JsonObject { ["bleibt"] = true };
    Check(JsonNode.DeepEquals(GesamtarchivService.Read(damagedArchive.ToJsonString()).Daten, fullArchiveData),
        "Unbekannte optionale Containerfelder werden akzeptiert");
    var localSettings = JsonNode.Parse("""{"einstellungen":{"allgemein":{"tray":{"aktiv":false,"autostart":false},"sicherungsordner":"C:\\lokal"},"sync":{"kalenderUids":["lokal"]}}}""")!.AsObject();
    var overlaid = GesamtarchivService.PreserveDeviceSettings(fullArchiveData, localSettings, true);
    Check(JsonNode.DeepEquals(overlaid["einstellungen"], localSettings["einstellungen"]),
        "Plattformwechsel bewahrt Tray, Autostart, Sicherungsordner und Sync-Quellen");
    var tokenData = fullArchiveData.DeepClone().AsObject(); tokenData["einstellungen"]!["sync"]!["graphToken"] = "geheim";
    try { _ = GesamtarchivService.Create(tokenData, "windows", "2.0.0"); throw new InvalidOperationException("Graph-Token exportiert"); }
    catch (InvalidDataException) { }
    var unchangedPath = Path.Combine(root, "keine-mutation.json"); store.Write(unchangedPath, second);
    try { _ = GesamtarchivService.Read(damagedArchive.ToJsonString().Replace("\"fassung\":99", "\"fassung\":98")); } catch { }
    Check(store.Read(unchangedPath) == second, "Validierungsfehler mutiert den aktuellen Bestand nicht");
    var oversizedArchive = Path.Combine(root, "gross.magnolie");
    using (var oversizedStream = File.Create(oversizedArchive)) oversizedStream.SetLength(AtomicStore.MaxArchiveBytes + 1);
    try { _ = store.Read(oversizedArchive, AtomicStore.MaxArchiveBytes); throw new InvalidOperationException("Übergröße angenommen"); }
    catch (IOException) { }
    var archivePath = Path.Combine(root, "archiv.magnolie"); store.Write(archivePath, gesamtArchive, AtomicStore.MaxArchiveBytes);
    var archiveLink = Path.Combine(root, "archiv-link.magnolie"); File.CreateSymbolicLink(archiveLink, archivePath);
    try { _ = store.Read(archiveLink, AtomicStore.MaxArchiveBytes); throw new InvalidOperationException("Reparse Point angenommen"); }
    catch (IOException) { }

    const string calendar = """
        BEGIN:VCALENDAR
        VERSION:2.0
        BEGIN:VEVENT
        UID:probe-1
        DTSTART:20260812T093000
        DTEND:20260812T103000
        SUMMARY:Besprechung
        DESCRIPTION:Zeile 1\nZeile 2
        RRULE:FREQ=WEEKLY
        END:VEVENT
        BEGIN:VTODO
        UID:aufgabe-1
        DUE;VALUE=DATE:20260813
        SUMMARY:Unterlagen senden
        PRIORITY:2
        END:VTODO
        END:VCALENDAR
        """;
    var calendarImport = ExchangeCodec.ParseIcs(calendar);
    Check(calendarImport.Termine.Count == 1 && calendarImport.Aufgaben.Count == 1,
        "ICS importiert Termine und Aufgaben");
    Check(calendarImport.Termine[0]?["titel"]?.ToString() == "Besprechung" &&
          calendarImport.Termine[0]?["wiederholung"]?["art"]?.ToString() == "weekly",
        "ICS übernimmt Text und einfache Wiederholung");
    var intervalImport = ExchangeCodec.ParseIcs(calendar.Replace("RRULE:FREQ=WEEKLY", "RRULE:FREQ=WEEKLY;INTERVAL=3"));
    Check(intervalImport.Termine[0]?["wiederholung"]?["intervall"]?.GetValue<int>() == 3,
        "ICS übernimmt Drei-Wochen-Intervalle");
    var customImport = ExchangeCodec.ParseIcs(calendar.Replace("RRULE:FREQ=WEEKLY",
        "RDATE:20260819T093000,20260909T093000"));
    Check(customImport.Termine[0]?["wiederholung"]?["art"]?.ToString() == "custom" &&
          customImport.Termine[0]?["wiederholung"]?["daten"]?.AsArray().Count == 2,
        "ICS übernimmt ausgewählte RDATE-Tage");
    var complexCalendar = ExchangeCodec.ParseIcs(calendar.Replace("RRULE:FREQ=WEEKLY", "RRULE:FREQ=WEEKLY;BYDAY=MO,WE"));
    Check(complexCalendar.Wiederholend == 1 && complexCalendar.Termine[0]?["icsKomplex"]?.GetValue<bool>() == true &&
          complexCalendar.Termine[0]?["wiederholung"]?["art"]?.ToString() == "none",
        "Komplexe ICS-Serie wird nicht falsch vereinfacht");
    using var appointmentDocument = JsonDocument.Parse("""
        [{"uid":"probe-2","datum":"2026-08-14","zeit":"14:15","titel":"Exportprobe","wiederholung":{"art":"none","bis":""}}]
        """);
    var calendarExport = ExchangeCodec.WriteIcs("ics-termine", appointmentDocument.RootElement);
    Check(calendarExport.Count == 1 && calendarExport.Text.Contains("SUMMARY:Exportprobe") &&
          calendarExport.Text.Contains("DTSTART:20260814T141500"), "ICS-Export");
    const string complexIcs = """
        BEGIN:VCALENDAR
        VERSION:2.0
        BEGIN:VEVENT
        UID:roundtrip-series
        DTSTART;TZID=America/New_York:20261101T013000
        DURATION:PT90M
        RRULE:FREQ=WEEKLY;BYDAY=MO,WE
        RDATE;TZID=America/New_York:20261105T013000
        EXDATE;TZID=America/New_York:20261109T013000
        LOCATION:Raum 7
        ATTENDEE;CN=Mia:mailto:mia@example.org
        ATTACH:https://example.org/agenda.pdf
        X-ALT-DESC;FMTTYPE=text/html:<b>Agenda</b>
        TRANSP:OPAQUE
        SUMMARY:Zonenserie
        BEGIN:VALARM
        ACTION:DISPLAY
        TRIGGER:-PT15M
        END:VALARM
        END:VEVENT
        END:VCALENDAR
        """;
    var complexImport = ExchangeCodec.ParseIcs(complexIcs);
    Check(complexImport.Termine[0]?["icsKomplex"]?.GetValue<bool>() == true &&
          complexImport.Termine[0]?["icsRoundtrip"]?.AsArray().Count >= 10,
        "ICS bewahrt komplexe Serie, Quell-TZID, Alarm und Zusatzfelder opak");
    using (var complexDocument = JsonDocument.Parse(complexImport.Termine.ToJsonString()))
    {
        var roundtrip = ExchangeCodec.WriteIcs("ics-termine", complexDocument.RootElement).Text;
        Check(roundtrip.Contains("DTSTART;TZID=America/New_York:20261101T013000") &&
              roundtrip.Contains("RRULE:FREQ=WEEKLY;BYDAY=MO,WE") && roundtrip.Contains("BEGIN:VALARM") &&
              roundtrip.Contains("ATTACH:https://example.org/agenda.pdf"), "ICS-Komplexmetadaten überstehen Export");
    }

    const string vcard = """
        BEGIN:VCARD
        VERSION:3.0
        N:Muster;Mia;;;
        FN:Mia Muster
        EMAIL:mia@example.org
        TEL;TYPE=CELL:+49170123456
        ADR;TYPE=HOME:;;Gartenweg 1;Berlin;;10115;Deutschland
        BDAY:1990-04-02
        END:VCARD
        """;
    var contactImport = ExchangeCodec.ParseVCard(vcard);
    Check(contactImport.Kontakte.Count == 1 && contactImport.Geburtstage.Count == 1,
        "VCF importiert Kontakt und Geburtstag");
    Check(contactImport.Kontakte[0]?["nachname"]?.ToString() == "Muster" &&
          contactImport.Kontakte[0]?["mobil"]?.ToString() == "+49170123456", "VCF-Feldabbildung");
    var escapedAddress = ExchangeCodec.ParseVCard(vcard.Replace("Gartenweg 1;Berlin", "Gartenweg 1\\; Hinterhaus;Berlin"));
    Check(escapedAddress.Kontakte[0]?["strasse"]?.ToString() == "Gartenweg 1; Hinterhaus" &&
          escapedAddress.Kontakte[0]?["ort"]?.ToString() == "Berlin", "VCF-Strukturwerte beachten Escapes");
    try
    {
        _ = ExchangeCodec.ParseVCard("BEGIN:VCARD\nVERSION:3.0\nEND:VCARD");
        throw new InvalidOperationException("Leere vCard wurde angenommen");
    }
    catch (InvalidDataException) { }
    using var contactDocument = JsonDocument.Parse("""
        [{"uid":"kontakt-1","nachname":"Muster","vorname":"Mia","email":"mia@example.org","telefon":"0301234"}]
        """);
    var contactExport = ExchangeCodec.WriteVCard(contactDocument.RootElement);
    Check(contactExport.Count == 1 && contactExport.Text.Contains("VERSION:3.0") &&
          contactExport.Text.Contains("EMAIL:mia@example.org"), "VCF-Export");
    const string photoBase64 = "/9j/2Q==";
    var richVcard = $"""
        BEGIN:VCARD
        VERSION:2.1
        N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=C3=B6rg;;;
        FN:Jörg Müller
        UID:photo-contact
        REV:20260811T120000Z
        EMAIL;TYPE=HOME:joerg@example.org
        EMAIL;TYPE=WORK:j.mueller@example.com
        TEL;TYPE=HOME:0301
        TEL;TYPE=CELL:01701
        ADR;TYPE=HOME:;;Weg 1;Berlin;;10115;Deutschland
        ADR;TYPE=WORK:;;Büro 2;Potsdam;;14467;Deutschland
        BDAY:--02-29
        PHOTO;ENCODING=BASE64;TYPE=JPEG:{photoBase64}
        END:VCARD
        """;
    var richContact = ExchangeCodec.ParseVCard(richVcard);
    Check(richContact.Kontakte[0]?["foto"]?.ToString() == "data:image/jpeg;base64," + photoBase64 &&
          richContact.Kontakte[0]?["geburtstag"]?.ToString() == "2000-02-29" &&
          richContact.Kontakte[0]?["geburtstagJahrUnbekannt"]?.GetValue<bool>() == true &&
          richContact.Kontakte[0]?["telefone"]?.AsArray().Count == 2 && richContact.Kontakte[0]?["anschriften"]?.AsArray().Count == 2,
        "VCF liest QP/Base64-Foto, jahrlose Schaltjahr-BDAY und Mehrfachfelder");
    using (var richDocument = JsonDocument.Parse(richContact.Kontakte.ToJsonString()))
    {
        var exported = ExchangeCodec.WriteVCard(richDocument.RootElement).Text;
        var imported = ExchangeCodec.ParseVCard(exported);
        Check(imported.Kontakte[0]?["foto"]?.ToString() == "data:image/jpeg;base64," + photoBase64 &&
              imported.Kontakte[0]?["geburtstagJahrUnbekannt"]?.GetValue<bool>() == true,
            "VCF-Foto und BDAY bleiben im Windows-Rundlauf bytegleich");
    }

    var ldifImport = ExchangeCodec.ParseLdif("""
        dn: cn=Erika Beispiel
        cn: Erika Beispiel
        givenName: Erika
        sn: Beispiel
        mail: erika@example.org
        mozillaSecondEmail: e.beispiel@example.com
        homePhone: 02031
        mobile: 01711
        mozillaHomeStreet: Rosenweg 2
        mozillaHomeLocalityName: Duisburg
        mozillaHomePostalCode: 47051
        birthMonth: 2
        birthDay: 29
        custom1: Kundin A
        jpegPhoto:: /9j/2Q==

        """);
    Check(ldifImport.Kontakte.Count == 1 && ldifImport.Kontakte[0]?["emails"]?.AsArray().Count == 2 &&
          ldifImport.Kontakte[0]?["foto"]?.ToString().StartsWith("data:image/jpeg;base64,") == true &&
          ldifImport.Kontakte[0]?["geburtstagJahrUnbekannt"]?.GetValue<bool>() == true,
        "Thunderbird-LDIF liest Mozilla-Aliasse, Geburtstagsteile, Home-Felder und jpegPhoto: " + ldifImport.Kontakte.ToJsonString());
    using (var ldifDocument = JsonDocument.Parse("""
        [{"uid":"kontakt,sonder","vorname":"Änne","nachname":"Bei,spiel","firma":"Muster GmbH","emailEintraege":[{"wert":"aenne@example.org","typen":["HOME"]},{"wert":"buero@example.org","typen":["WORK"]}],"telefone":[{"wert":"0203 1","typen":["VOICE"]},{"wert":"0171 2","typen":["CELL"]},{"wert":"0203 3","typen":["HOME"]},{"wert":"0203 4","typen":["WORK"]},{"wert":"0203 5","typen":["FAX"]},{"wert":"0203 6","typen":["PAGER"]}],"anschriften":[{"strasse":"A$B Straße 1","plz":"47051","ort":"Duisburg","land":"Deutschland"},{"strasse":"Büro 2","plz":"10115","ort":"Berlin","land":"Deutschland"}],"notiz":"Erste Zeile\nZweite Zeile mit Unicode Ä und einer ausreichend langen Beschreibung für eine sichere Faltung über mehrere physische LDIF-Zeilen.","geburtstag":"1980-04-03","foto":"data:image/jpeg;base64,/9j/2Q=="}]
        """))
    {
        var ldifExport = ExchangeCodec.WriteLdif(ldifDocument.RootElement);
        var goldenLdif = File.ReadAllText(Path.Combine("tests", "fixtures", "golden-kontakt.ldif")).ReplaceLineEndings("\r\n");
        var roundtripLdif = ExchangeCodec.ParseLdif(ldifExport.Text);
        Check(ldifExport.Text == goldenLdif && ldifExport.Text.Split("\r\n").All(line => System.Text.Encoding.UTF8.GetByteCount(line) <= 76),
            "LDIF-Ausgabe entspricht Python-Golden und Faltungsgrenze");
        Check(roundtripLdif.Kontakte[0]?["emails"]?.AsArray().Count == 2 && roundtripLdif.Kontakte[0]?["telefone"]?.AsArray().Count == 6 &&
              roundtripLdif.Kontakte[0]?["anschriften"]?.AsArray().Count == 2 && roundtripLdif.Kontakte[0]?["anschriften"]?.AsArray()[0]?["strasse"]?.ToString() == "A$B Straße 1" &&
              roundtripLdif.Kontakte[0]?["foto"]?.ToString() == "data:image/jpeg;base64,/9j/2Q==" && roundtripLdif.Kontakte[0]?["geburtstag"]?.ToString() == "1980-04-03",
            "LDIF-Windows-Rundlauf bewahrt Unicode, Mehrfachwerte, Dollar, JPEG und Geburtstag");
    }
    using (var unsafeLdifDocument = JsonDocument.Parse("""
        [{"uid":" #,+=\\\"<>; ","nachname":"Name\r\nmail: injected@example.org","email":"sicher@example.org"},{"nachname":"PNG","foto":"data:image/png;base64,iVBORw0KGgo="},{},{"uid":"gleich","nachname":"A"},{"uid":"gleich","nachname":"B"}]
        """))
    {
        var safe = ExchangeCodec.WriteLdif(unsafeLdifDocument.RootElement);
        Check(!safe.Text.Contains("\r\nmail: injected@example.org") && safe.Count == 4 && safe.Skipped == 1 && safe.PhotoOmitted == 1 &&
              safe.Text.Split("\r\n").Where(line => line.StartsWith("uid: ")).Distinct().Count() == 4 && !safe.Text.Contains("iVBOR"),
            "LDIF maskiert Injektionen, erzeugt eindeutige UIDs und verwirft PNG");
    }
    using (var dnDocument = JsonDocument.Parse("""[{"uid":" #Komma,+Gleich=\\Ende ","nachname":"DN"}]"""))
        Check(ExchangeCodec.WriteLdif(dnDocument.RootElement).Text.Contains("dn: uid=magnolie-"),
            "LDIF ersetzt eine unsichere stabile UID vor der DN-Bildung deterministisch");
    var clawsImport = ExchangeCodec.ParseClawsXml("""
        <?xml version="1.0"?><address-book><person uid="claws-17" first-name="Clara" last-name="Kralle" cn="Clara Kralle"><address-list><address email="clara@example.org" remarks="privat"/></address-list><attribute-list><attribute name="mobile">01722</attribute><attribute name="birthday">1988-05-04</attribute><attribute name="jpegPhoto">data:image/jpeg;base64,/9j/2Q==</attribute></attribute-list></person></address-book>
        """);
    Check(clawsImport.Kontakte[0]?["uid"]?.ToString() == "claws-17" && clawsImport.Kontakte[0]?["foto"]?.ToString().Length > 0,
        "Claws-XML übernimmt UID und Foto");
    var lotusImport = ExchangeCodec.ParseLotusCsv("ANFANGSDATUMZEIT,BESCHREIBUNG\r\n\"08/13/2026 9:30 AM\",\"US-Termin\"\r\n\"04/05/2026\",\"Mehrdeutig\"\r\n");
    Check(lotusImport.Termine.Count == 1 && lotusImport.Uebersprungen == 1 && lotusImport.Bericht.Contains("mehrdeutige"),
        "Lotus erkennt AM/PM als US und meldet mehrdeutige Daten");
    using (var lotusDocument = JsonDocument.Parse("[{\"datum\":\"2026-08-13\",\"zeit\":\"09:30\",\"titel\":\"CSV-Probe\",\"notiz\":\"Zeile 2\"}]"))
    {
        var lotusExport = ExchangeCodec.WriteLotusCsv(lotusDocument.RootElement);
        Check(lotusExport.Count == 1 && ExchangeCodec.ParseLotusCsv(lotusExport.Text).Termine.Count == 1, "Lotus-csv-termine ist ein echter Rundlauf");
    }
    using (var formulaDocument = JsonDocument.Parse("[{\"datum\":\"2026-08-13\",\"titel\":\" =HYPERLINK(\\\"https://example.invalid\\\")\"}]"))
        Check(ExchangeCodec.WriteLotusCsv(formulaDocument.RootElement).Text.Contains("\"' =HYPERLINK("),
            "Lotus-CSV neutralisiert keine Tabellenformeln mit führendem Leerraum");
    var goldenIcs = ExchangeCodec.ParseIcs(File.ReadAllText(Path.Combine("tests", "fixtures", "golden-komplex.ics")));
    var goldenVcf = ExchangeCodec.ParseVCard(File.ReadAllText(Path.Combine("tests", "fixtures", "golden-kontakt.vcf")));
    using (var goldenIcsDocument = JsonDocument.Parse(goldenIcs.Termine.ToJsonString()))
    using (var goldenVcfDocument = JsonDocument.Parse(goldenVcf.Kontakte.ToJsonString()))
    {
        var icsAgain = ExchangeCodec.ParseIcs(ExchangeCodec.WriteIcs("ics-termine", goldenIcsDocument.RootElement).Text);
        var vcfAgain = ExchangeCodec.ParseVCard(ExchangeCodec.WriteVCard(goldenVcfDocument.RootElement).Text);
        Check(icsAgain.Termine[0]?["icsRoundtrip"]?.AsArray().Any(line => line?.ToString() == "TRIGGER:-PT15M") == true &&
              vcfAgain.Kontakte[0]?["foto"]?.ToString() == goldenVcf.Kontakte[0]?["foto"]?.ToString() &&
              vcfAgain.Kontakte[0]?["geburtstagJahrUnbekannt"]?.GetValue<bool>() == true,
            "plattformübergreifende Golden-Rundläufe bewahren Serie, Alarm, Foto und BDAY");
    }

    const string reminders = """
        {
          "einstellungen":{"erinnerung":{"vorlauf":0,"verpasste":true}},
          "termine":[
            {"id":"jetzt","datum":"2026-08-11","zeit":"14:00","titel":"Pünktlich","standardErinnerung":true,"wiederholung":{"art":"none","bis":""}},
            {"id":"serie","datum":"2026-07-21","zeit":"15:00","titel":"Dreiwöchentlich","standardErinnerung":true,"wiederholung":{"art":"weekly","intervall":3,"bis":"2026-09-01"}},
            {"id":"auswahl","datum":"2026-08-01","zeit":"15:00","titel":"Auswahl","standardErinnerung":true,"wiederholung":{"art":"custom","daten":["2026-08-11"]}}
          ]
        }
        """;
    var due = ReminderScheduler.DueAppointments(reminders, new DateTime(2026, 8, 11, 15, 0, 0));
    Check(due.Any(item => item.Key.StartsWith("jetzt@", StringComparison.Ordinal)) &&
          due.Any(item => item.Key.StartsWith("serie@202608111500", StringComparison.Ordinal)) &&
          due.Any(item => item.Key.StartsWith("auswahl@202608111500", StringComparison.Ordinal)),
        "Erinnerungen berücksichtigen Vorlauf, Intervalle und ausgewählte Tage");

    using var reminderDocument = JsonDocument.Parse("""
        {
          "einstellungen":{"erinnerung":{"verpasste":true,"jahrestage":{"an":true,"tage":1,"amTag":true,"stunde":8}}},
          "aufgaben":[{"id":"a1","titel":"Prüfen","faellig":"2026-08-11","faelligZeit":"14:30","erinnern":true,"erledigt":false}],
          "jahrestage":[{"id":"j1","name":"Mia","datum":"1990-08-12","typ":"birthday"}]
        }
        """);
    var reminderRoot = reminderDocument.RootElement;
    var reminderSettings = reminderRoot.GetProperty("einstellungen").GetProperty("erinnerung");
    Check(ReminderScheduler.DueTasks(reminderRoot, reminderSettings, new DateTime(2026, 8, 11, 14, 29, 0)).Count == 0 &&
          ReminderScheduler.DueTasks(reminderRoot, reminderSettings, new DateTime(2026, 8, 11, 14, 30, 0)).Count == 1,
        "Aufgabenerinnerung verwendet die gewählte Fälligkeitszeit");
    Check(ReminderScheduler.DueAnniversaries(reminderRoot, reminderSettings, new DateTime(2026, 8, 11, 9, 0, 0))
        .Any(item => item.Key.Contains(":vorlauf", StringComparison.Ordinal)), "Jahrestagsvorlauf");

    using var trayDocument = JsonDocument.Parse("""
        {"aktiv":true,"startMinimiert":true,"autostart":true,"oeffnen":"zentriert"}
        """);
    var tray = TraySettings.FromJson(trayDocument.RootElement);
    Check(tray.Aktiv && tray.StartMinimiert && tray.Autostart && tray.MinimierenInTray &&
          tray.SchliessenInTray && tray.Oeffnen == "centered", "Tray-Einstellungen normalisieren");
    var trayService = new TraySettingsService(paths.TraySettings);
    trayService.Save(tray);
    Check(trayService.Load() == tray, "Tray-Einstellungen bleiben über Programmstarts erhalten");
    File.WriteAllText(paths.TraySettings, "{beschädigt");
    _ = trayService.Load();
    Check(trayService.LoadFailed, "Eine beschädigte Tray-Konfiguration würde Autostart still als deaktiviert behandeln");
    trayService.Save(tray);
    Check(TraySettingsService.AutostartCommand(@"C:\Programme\Magnolie Organizer.exe") ==
          "\"C:\\Programme\\Magnolie Organizer.exe\" --tray-start", "Autostart-Befehl ist sicher quotiert");

    var legacyTrayPath = Path.Combine(root, "legacy-tray.json");
    var legacyDataPath = Path.Combine(root, "legacy-daten.json");
    File.WriteAllText(legacyDataPath, """
        {"einstellungen":{"allgemein":{"tray":{"aktiv":true,"startMinimiert":true,"autostart":true}}}}
        """);
    var legacyTrayService = new TraySettingsService(legacyTrayPath);
    Check(legacyTrayService.Load(legacyDataPath) is { Aktiv: true, StartMinimiert: true, Autostart: true } &&
          File.Exists(legacyTrayPath), "Vorhandene Tray-Einstellungen werden aus daten.json migriert");

    var libreOfficeFile = Path.Combine(root, "LibreOffice", "4", "user", "registrymodifications.xcu");
    Directory.CreateDirectory(Path.GetDirectoryName(libreOfficeFile)!);
    File.WriteAllText(libreOfficeFile, """
        <?xml version="1.0" encoding="UTF-8"?>
        <oor:items xmlns:oor="http://openoffice.org/2001/registry">
          <item oor:path="/org.openoffice.Office.Common/Save"><prop oor:name="givenname"><value>NichtIch</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="givenname"><value>Erika</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="sn"><value>Beispiel</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="o"><value>Beispiel &amp; Söhne</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="street"><value>Musterweg 3</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="postalcode"><value>47051</value></prop></item>
          <item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="l"><value>Duisburg</value></prop></item>
        </oor:items>
        """);
    Check(LibreOfficeUserData.FindSettingsFile(root) == libreOfficeFile,
        "LibreOffice-Einstellungsdatei wird gefunden");
    var libreOffice = LibreOfficeUserData.Read(libreOfficeFile);
    Check(libreOffice.Ok && libreOffice.Absender ==
          "Erika Beispiel\nBeispiel & Söhne\nMusterweg 3\n47051 Duisburg" &&
          !libreOffice.Absender.Contains("NichtIch"), "LibreOffice-Anschrift wird sicher übernommen");
    File.WriteAllText(libreOfficeFile,
        "<!DOCTYPE x [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><x>&xxe;</x>");
    var xxe = LibreOfficeUserData.Read(libreOfficeFile);
    Check(!xxe.Ok && xxe.Fehler.Contains("nicht gelesen", StringComparison.Ordinal),
        "LibreOffice-Parser blockiert DTD und XXE");

    using var letterContact = JsonDocument.Parse("""
        {"vorname":"Mia","nachname":"Muster","strasse":"Gartenweg 1","plz":"10115","ort":"Berlin"}
        """);
    var letter = DocumentExportService.CreateLetter(letterContact.RootElement, "Max Beispiel\nHauptstraße 2", "din5008");
    using (var letterStream = new MemoryStream(letter))
    using (var letterArchive = new ZipArchive(letterStream, ZipArchiveMode.Read))
    using (var letterContent = new StreamReader(letterArchive.GetEntry("content.xml")!.Open()))
        Check(letterArchive.Entries[0].FullName == "mimetype" && letterContent.ReadToEnd().Contains("Mia Muster"), "ODT-Brief");
    var spreadsheet = DocumentExportService.CreateSpreadsheet(new[]
    {
        new DocumentSheet("Adressen", new[] { "Name", "Ort" }, new[] { (IReadOnlyList<string>)new[] { "Mia Muster", "Berlin" } })
    });
    using (var spreadsheetStream = new MemoryStream(spreadsheet))
    using (var archive = new ZipArchive(spreadsheetStream, ZipArchiveMode.Read))
    {
        Check(archive.Entries[0].FullName == "mimetype" && archive.GetEntry("content.xml") is not null &&
              archive.GetEntry("styles.xml") is not null && archive.GetEntry("META-INF/manifest.xml") is not null,
            "ODS-Paketstruktur");
        using var reader = new StreamReader(archive.GetEntry("content.xml")!.Open());
        var plainContent = reader.ReadToEnd();
        Check(plainContent.Contains("Mia Muster") && plainContent.Contains("office:automatic-styles") &&
              plainContent.Contains("style:column-width") && plainContent.Contains("table:print-ranges"),
            "ODS-Tabelleninhalt und echte automatische Stile");
    }

    using var addressPayload = JsonDocument.Parse("""
        {"cmd":"adressen_ods","titel":"Magnolie Organizer · Kontakte","spalten":["Nachname","Ort"],"zeilen":[["Muster","Berlin"]]}
        """);
    var addressSheet = DocumentExportService.ReadSheet(addressPayload.RootElement, "Adressen");
    Check(addressSheet.Columns.SequenceEqual(new[] { "Nachname", "Ort" }) &&
          addressSheet.Rows[0].SequenceEqual(new[] { "Muster", "Berlin" }),
        "Adress-ODS bildet flache Bridge-Zellen ab");

    using var yearPayload = JsonDocument.Parse("""
        {"cmd":"planer_ods","layout":"year","titel":"Jahresplaner 2026","spalten":["Januar","Februar"],
         "zeilen":[["1 Do\nNeujahr","1 So"]],"stile":[["holiday","sunday"]],"inhalte":[[
           {"datum":"1 Do","eintraege":[{"text":"Neujahr","farbe":"#b5443a"}]},
           {"datum":"1 So","eintraege":[]}
         ]]}
        """);
    var yearSheet = DocumentExportService.ReadSheet(yearPayload.RootElement, "Planer");
    Check(yearSheet.Layout == "year" && yearSheet.Rows[0][0] == "1 Do\nNeujahr" &&
          yearSheet.Rows[0][1] == "1 So" && yearSheet.CellStyles![0][0] == "holiday" &&
          yearSheet.TextColors![0][0][1] == "#b5443a",
        "Jahresplaner-ODS liest strukturierte Vorschauzellen, Zellarten und Anlassfarben");

    using var monthPayload = JsonDocument.Parse("""
        {"cmd":"planer_ods","layout":"month","titel":"August 2026","spalten":["KW","Mo"],
         "zeilen":[["32","3\nFrühdienst\nTermin"]],"stile":[["week-number","holiday"]],"inhalte":[[
           {"datum":"32","eintraege":[]},
           {"datum":"3","marker":[{"text":"X","farbe":"#ad3f50"}],
            "eintraege":[{"text":"Frühdienst","farbe":"#c68a34","art":"schicht"}],"mehr":2}
         ]]}
        """);
    var monthSheet = DocumentExportService.ReadSheet(monthPayload.RootElement, "Planer");
    Check(monthSheet.Layout == "month" && monthSheet.Rows[0][1] == "3\nX\nFrühdienst\n+2" &&
          monthSheet.CellStyles![0][0] == "week-number" && monthSheet.TextColors![0][1][1] == "#ad3f50" &&
          !monthSheet.Rows[0][1].Contains('{') && !monthSheet.Rows[0][1].Contains('['),
        "Monatsplaner-ODS übernimmt Vorschaufarben, Marker, Einträge und Mehr-Hinweis ohne JSON");
    var yearGeometry = new DocumentSheet("Jahresgeometrie", Enumerable.Range(1, 12).Select(index => $"Monat {index}").ToArray(),
        Enumerable.Range(1, 31).Select(day => (IReadOnlyList<string>)Enumerable.Range(1, 12).Select(month => $"{day} M{month}").ToArray()).ToArray(),
        Layout: "year", CellStyles: Enumerable.Range(0, 31).Select(row => (IReadOnlyList<string>)Enumerable.Range(0, 12)
            .Select(column => row == 0 && column == 0 ? "holiday" : column == 11 ? "sunday" : "").ToArray()).ToArray());
    var monthGeometry = new DocumentSheet("Monatsgeometrie", new[] { "KW", "Mo", "Di", "Mi", "Do", "Fr", "Sa", "So" },
        Enumerable.Range(0, 6).Select(week => (IReadOnlyList<string>)new[] { (32 + week).ToString(), "1", "2", "3", "4", "5", "6", "7" }).ToArray(),
        Layout: "month", CellStyles: Enumerable.Range(0, 6).Select(_ => (IReadOnlyList<string>)new[]
            { "week-number", "", "", "", "", "", "", "sunday" }).ToArray());

    using var healthPayload = JsonDocument.Parse("""
        {"cmd":"gesundheit_ods","tabellen":[
          {"titel":"Blutzucker","rechtsTitel":"Insulinschema","links":["Datum","Wert"],
           "rechts":["Medikament","IE"],"zeilen":[["11.08.2026","6.4","Insulin","4"]]},
          {"titel":"Verlauf · Blutdruck","rechtsTitel":"Blutdruck",
           "links":["Datum","Systolisch","Diastolisch"],"rechts":["Blutdruck"],
           "diagramm":{"titel":"Blutdruck","serien":[
             {"name":"Systolisch","farbe":"#a7444e","punkte":[["2026-08-10",128],["2026-08-11",124]]},
             {"name":"Diastolisch","farbe":"#456f91","punkte":[["2026-08-10",82],["2026-08-11",79]]}
           ]},"zeilen":[["10.08.2026","128","82",""]]}
        ]}
        """);
    var healthSheets = DocumentExportService.ReadHealthSheets(healthPayload.RootElement);
    Check(healthSheets.Count == 2 && healthSheets[0].Columns.SequenceEqual(
              new[] { "Datum", "Wert", "", "Medikament", "IE" }) &&
          healthSheets[0].Rows[0].SequenceEqual(new[] { "11.08.2026", "6.4", "", "Insulin", "4" }) &&
          healthSheets[0].Groups![2].Name == "Insulinschema" &&
          healthSheets[1].Columns.SequenceEqual(new[] { "Datum", "Systolisch", "Diastolisch", "", "Blutdruck" }) &&
          healthSheets[1].Rows.Count == 20 && healthSheets[1].Rows[0].SequenceEqual(new[] { "10.08.2026", "128", "82", "", "" }) &&
          healthSheets[1].Groups![0].Name == "" && healthSheets[1].Groups![2].Name == "Blutdruck" &&
          healthSheets[1].Chart is { Series.Count: 2 },
        "Gesundheits-ODS liest singuläres diagramm, hält 20 Verlaufzeilen vor und dupliziert links keine Gruppenüberschrift");

    var mappedSpreadsheet = DocumentExportService.CreateSpreadsheet(
        new[] { addressSheet, yearSheet, monthSheet, yearGeometry, monthGeometry }.Concat(healthSheets).ToArray());
    using (var mappedStream = new MemoryStream(mappedSpreadsheet))
    using (var archive = new ZipArchive(mappedStream, ZipArchiveMode.Read))
    {
        XDocument content;
        using (var contentStream = archive.GetEntry("content.xml")!.Open()) content = XDocument.Load(contentStream);
        var xml = content.ToString(SaveOptions.DisableFormatting);
        XNamespace officeNs = "urn:oasis:names:tc:opendocument:xmlns:office:1.0";
        XNamespace tableNs = "urn:oasis:names:tc:opendocument:xmlns:table:1.0";
        XNamespace styleNs = "urn:oasis:names:tc:opendocument:xmlns:style:1.0";
        XNamespace foNs = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0";
        XNamespace drawNs = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0";
        XNamespace xlinkNs = "http://www.w3.org/1999/xlink";
        var automaticStyles = content.Root!.Element(officeNs + "automatic-styles")!;
        Check(automaticStyles.Elements(styleNs + "style").Any(node =>
                  (string?)node.Attribute(styleNs + "family") == "table-column" &&
                  node.Descendants(styleNs + "table-column-properties").Any(properties => properties.Attribute(styleNs + "column-width") is not null)) &&
              automaticStyles.Descendants(styleNs + "table-row-properties").Any(properties => (string?)properties.Attribute(styleNs + "row-height") == "2.5cm") &&
              automaticStyles.Descendants(styleNs + "table-cell-properties").Any(properties => (string?)properties.Attribute(foNs + "wrap-option") == "wrap" &&
                  (string?)properties.Attribute(foNs + "border") != "none"),
            "ODS definiert Spaltenbreiten, Zeilenhöhen, Rahmen und Umbruch als automatic-styles");
        var fills = automaticStyles.Descendants(styleNs + "table-cell-properties")
            .Select(node => (string?)node.Attribute(foNs + "background-color")).ToHashSet();
        Check(fills.IsSupersetOf(new[] { "#f4c6ca", "#f5c38f", "#5c3f25", "#f0e4ec" }) &&
              xml.Contains("fo:color=\"#b5443a\"") && xml.Contains("fo:color=\"#ad3f50\""),
            "Vorschau-Füllfarben und individuelle Marker-/Eintragsfarben sind im ODS erhalten");
        var tables = content.Descendants(tableNs + "table").ToArray();
        var yearTable = tables.Single(node => (string?)node.Attribute(tableNs + "name") == "Jahresgeometrie");
        var monthTable = tables.Single(node => (string?)node.Attribute(tableNs + "name") == "Monatsgeometrie");
        Check(yearTable.Elements(tableNs + "table-column").Count() == 12 && yearTable.Elements(tableNs + "table-row").Count() == 33 &&
              yearTable.Elements(tableNs + "table-column").All(column =>
                  automaticStyles.Elements(styleNs + "style").Single(style =>
                      (string?)style.Attribute(styleNs + "name") == (string?)column.Attribute(tableNs + "style-name"))
                      .Descendants(styleNs + "table-column-properties").Any(properties => (string?)properties.Attribute(styleNs + "column-width") == "2.35cm")) &&
              monthTable.Elements(tableNs + "table-column").Count() == 8 && monthTable.Elements(tableNs + "table-row").Count() == 8,
            "Jahresplaner hat 12 Spalten und 31 Tageszeilen; Monatsplaner KW plus 7 Tage und 6 Wochenzeilen");
        Check(yearTable.Elements(tableNs + "table-row").First().Elements().First().Attribute(tableNs + "number-columns-spanned")?.Value == "12" &&
              monthTable.Elements(tableNs + "table-row").First().Elements().First().Attribute(tableNs + "number-columns-spanned")?.Value == "8" &&
              monthTable.Elements(tableNs + "table-row").First().Elements().First().Attribute(tableNs + "style-name")?.Value == "ceMonthTitle",
            "Planertitel sind über die gesamte Breite verbunden; der Monatstitel verwendet das braune Titelband");
        var healthTable = tables.Single(node => (string?)node.Attribute(tableNs + "name") == "Verlauf · Blutdruck");
        Check(healthTable.Elements(tableNs + "table-column").ElementAt(3).Attribute(tableNs + "style-name") is { } spacerStyle &&
              automaticStyles.Elements(styleNs + "style").Single(node => (string?)node.Attribute(styleNs + "name") == spacerStyle.Value)
                  .Descendants(styleNs + "table-column-properties").Any(node => (string?)node.Attribute(styleNs + "column-width") == "0.5cm") &&
               healthTable.Elements(tableNs + "table-row").Count() == 22 &&
               healthTable.Descendants(drawNs + "frame").Single().Attribute(XNamespace.Get("urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0") + "height")?.Value == "11.4cm",
            "Gesundheitsverlauf hat 20 Datenzeilen, 5-mm-Spacer und geometrisch verankerten Diagrammbereich");
        var imageHref = healthTable.Descendants(drawNs + "image").Single().Attribute(xlinkNs + "href")!.Value;
        Check(archive.GetEntry(imageHref) is not null && archive.GetEntry("META-INF/manifest.xml") is not null,
            "SVG-Diagramm ist als echtes ODS-Paketobjekt vorhanden");
        using (var svgStream = archive.GetEntry(imageHref)!.Open())
        {
            var svg = XDocument.Load(svgStream).ToString(SaveOptions.DisableFormatting);
            Check(svg.Contains("polyline") && svg.Contains("circle") && svg.Contains("#a7444e") && svg.Contains("#456f91") &&
                  svg.Split("<line", StringSplitOptions.None).Length >= 5,
                "SVG-Diagramm enthält Raster, Achsenrahmen, beide Serien und Messpunkte");
        }
        using (var manifestStream = archive.GetEntry("META-INF/manifest.xml")!.Open())
        {
            var manifestXml = XDocument.Load(manifestStream).ToString(SaveOptions.DisableFormatting);
            Check(manifestXml.Contains(imageHref) && manifestXml.Contains("image/svg+xml"), "Diagramm ist im ODF-Manifest registriert");
        }
        using (var stylesStream = archive.GetEntry("styles.xml")!.Open())
        {
            var stylesDocument = XDocument.Load(stylesStream);
            Check(stylesDocument.Descendants(styleNs + "page-layout-properties").Any(node =>
                      (string?)node.Attribute(foNs + "page-width") == "29.7cm" &&
                      (string?)node.Attribute(foNs + "page-height") == "21cm" &&
                      (string?)node.Attribute(styleNs + "print-orientation") == "landscape" &&
                      (string?)node.Attribute(foNs + "margin-left") == "0.7cm" &&
                      (string?)node.Attribute(styleNs + "scale-to-pages") == "1"),
                "ODS-Drucklayout ist A4 quer mit 7-mm-Rändern und Einseiten-Skalierung");
        }
        Check(content.Descendants(tableNs + "database-range").Any(node =>
                  (string?)node.Attribute(tableNs + "display-filter-buttons") == "true") &&
              tables.All(node => node.Attribute(tableNs + "print-ranges") is not null) &&
              healthTable.Descendants(tableNs + "table-cell").Any(node =>
                  (string?)node.Attribute(officeNs + "value-type") == "float" && (string?)node.Attribute(officeNs + "value") == "128") &&
              xml.Contains("Insulinschema") && xml.Contains("Frühdienst") && xml.Contains("text:line-break") &&
              !xml.Contains("{\"datum\"") && !xml.Contains("{\"punkte\""),
            "Filter, Druckbereiche, typisierte Messwerte und bereinigte Zellinhalte sind gesetzt");
    }

    var contactData = JsonNode.Parse("""{"vorname":"Mia","nachname":"Muster/Probe:*?","firma":"Magnolie","strasse":"Weg 1","plz":"10115","ort":"Berlin","land":"Deutschland","email":"mia@example.org","emails":["mia@example.org","muster@example.org"],"telefon":"0301","mobil":"01701","geburtstag":"1990-04-02","notiz":"Zeile 1\nZeile 2"}""")!.AsObject();
    var contactXml = WindowsContactStore.Serialize(contactData, "mag-test@magnolie-organizer");
    var parsedContact = WindowsContactStore.Parse(contactXml);
    Check(ContactFields.Text(parsedContact, "vorname") == "Mia" && ContactFields.Text(parsedContact, "firma") == "Magnolie" &&
          ContactFields.Text(parsedContact, "mobil") == "01701" && parsedContact["emails"]!.AsArray().Count == 2 &&
          ContactFields.Text(parsedContact, "notiz").Contains("Zeile 2"), ".contact-Roundtrip und Feldabbildung");
    Check(!WindowsContactStore.SafeFileStem("../Muster: *? <Kontakt>").Contains('/') &&
          !WindowsContactStore.SafeFileStem("../Muster: *? <Kontakt>").Contains(':') &&
          WindowsContactStore.SafeFileStem("...") == "Kontakt", ".contact-Dateinamen werden bereinigt");
    try { _ = WindowsContactStore.Parse("<!DOCTYPE x [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><Contact><Notes>&xxe;</Notes></Contact>"); throw new InvalidOperationException("XXE wurde angenommen"); }
    catch (System.Xml.XmlException) { }

    var contactDirectory = Path.Combine(root, "Contacts");
    var contactStore = new WindowsContactStore(contactDirectory);
    var madeContact = await contactStore.CreateAsync("mag-local@magnolie-organizer", contactData, CancellationToken.None);
    Check((await contactStore.ReadAsync(CancellationToken.None)).Single().Owned && madeContact.Id.EndsWith(".contact", StringComparison.Ordinal),
        "lokaler Kontakt wird atomar angelegt und eindeutig zugeordnet");
    var foreignPath = Path.Combine(contactDirectory, "Fremd.contact"); File.WriteAllText(foreignPath, contactXml.Replace("<m:MagnolieUid>mag-test@magnolie-organizer</m:MagnolieUid>", ""));
    var foreign = (await contactStore.ReadAsync(CancellationToken.None)).Single(item => item.Id == "Fremd.contact");
    try { await contactStore.DeleteAsync(foreign, "mag-foreign@magnolie-organizer", CancellationToken.None); throw new InvalidOperationException("Fremder Kontakt wurde gelöscht"); }
    catch (IOException) { }
    Check(File.Exists(foreignPath), "fremde .contact-Dateien werden niemals gelöscht");

    var conflictLocal = new JsonArray(new JsonObject { ["id"] = "local", ["uid"] = "uid-1", ["vorname"] = "Alt", ["geaendert"] = 100L,
        ["sync"] = true, ["syncQuellen"] = new JsonObject { ["probe"] = new JsonObject { ["id"] = "remote-1", ["etag"] = "a", ["geaendert"] = 100L } } });
    var fakeRemote = new MemoryContactRemote(new RemoteContact("remote-1", "b", 200L, new JsonObject { ["vorname"] = "Neu" }, false));
    var conflict = await new ContactSyncEngine().SyncAsync("probe", conflictLocal, new JsonArray(), 50, fakeRemote);
    Check(ContactFields.Text(conflict.Contacts[0]!.AsObject(), "vorname") == "Neu" && conflict.Counts.Updated == 1 &&
          ContactFields.Source(conflict.Contacts[0]!.AsObject(), "probe")?["etag"]?.GetValue<string>() == "b",
        "Konfliktregel übernimmt die zuletzt geänderte Remote-Fassung samt ETag");
    var uidRemote = new MemoryContactRemote(new RemoteContact("remote-uid", "a", 0,
        new JsonObject { ["uid"] = "provider-original-uid", ["vorname"] = "Remote" }, true));
    var uidImport = await new ContactSyncEngine().SyncAsync("probe", new JsonArray(), new JsonArray(), 0, uidRemote);
    Check(uidImport.Contacts[0]?["uid"]?.ToString() == "provider-original-uid",
        "Windows-Kontaktsync ersetzte die originale vCard-UID");

    var pageHandler = new FakeHttpHandler(request => request.RequestUri!.Query.Contains("page=2", StringComparison.Ordinal)
        ? JsonResponse("""{"value":[{"id":"g2","givenName":"Zwei","lastModifiedDateTime":"2026-08-11T10:00:00Z"}]}""")
        : JsonResponse("""{"value":[{"id":"g1","givenName":"Eins","emailAddresses":[{"address":"eins@example.org"}],"lastModifiedDateTime":"2026-08-11T09:00:00Z"}],"@odata.nextLink":"https://graph.microsoft.com/v1.0/me/contacts?page=2"}"""));
    using (var graphHttp = new HttpClient(pageHandler))
    {
        var graphContacts = await new GraphApiClient(graphHttp, "access-test").ReadAsync(CancellationToken.None);
        Check(graphContacts.Count == 2 && ContactFields.Text(graphContacts[0].Data, "email") == "eins@example.org" && pageHandler.Requests == 2,
            "Graph-JSON-Mapping und Pagination mit Fake-Handler");
    }
    var deviceResponse = OAuthResponseParser.DeviceCode("""{"device_code":"device","user_code":"ABCD-EFGH","verification_uri":"https://microsoft.com/devicelogin","expires_in":900,"interval":5}""");
    var tokenResponse = OAuthResponseParser.Token("""{"access_token":"access","refresh_token":"refresh","expires_in":3600}""");
    Check(deviceResponse.UserCode == "ABCD-EFGH" && tokenResponse.RefreshToken == "refresh", "Gerätecode- und Token-Antwortparser");
    var tokenPath = Path.Combine(root, "graph-token.dat"); var fakeProtector = new ReversingProtector(); var tokenStore = new GraphTokenStore(tokenPath, fakeProtector);
    tokenStore.Save("nur-test"); Check(tokenStore.Load() == "nur-test" && !File.ReadAllText(tokenPath).Contains("nur-test"), "DPAPI-Abstraktion ohne echte Tokens");
    tokenStore.Delete(); Check(!tokenStore.Exists, "Graph-Abmeldung löscht Tokens");

}
finally
{
    try { if (Directory.Exists(root)) Directory.Delete(root, true); }
    catch (Exception) { }
}

static void Check(bool condition, string name)
{
    if (!condition) throw new InvalidOperationException(name);
}

static int FreeTcpPort()
{
    var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
    listener.Start();
    var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
    listener.Stop();
    return port;
}

static HttpResponseMessage JsonResponse(string json) => new(System.Net.HttpStatusCode.OK)
{
    Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json")
};
}
}

sealed class ReversingProtector : ISecretProtector
{
    public byte[] Protect(byte[] plain) => plain.Reverse().ToArray();
    public byte[] Unprotect(byte[] protectedData) => protectedData.Reverse().ToArray();
}

sealed class FakeHttpHandler(Func<HttpRequestMessage, HttpResponseMessage> response) : HttpMessageHandler
{
    internal int Requests { get; private set; }
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    { Requests++; return Task.FromResult(response(request)); }
}

sealed class MemoryContactRemote(params RemoteContact[] contacts) : IContactRemote
{
    private readonly List<RemoteContact> contacts = contacts.ToList();
    public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>(contacts);
    public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => throw new NotSupportedException();
    public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken) => throw new NotSupportedException();
    public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) => throw new NotSupportedException();
}
