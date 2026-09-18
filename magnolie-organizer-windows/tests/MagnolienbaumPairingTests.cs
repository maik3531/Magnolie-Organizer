using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class MagnolienbaumPairingTests
{
    internal static async Task RunAsync(string root)
    {
        const long now = 1_700_000_000;
        var a = State("alpha"); var b = State("beta");
        var peerB = Trust(a, b); var peerA = Trust(b, a);
        var originalA = peerA.ToJsonString(); var originalB = peerB.ToJsonString();
        var forged = MagnolienbaumPairing.Identity(b);
        forged["name"] = "Forged"; forged["port"] = 1;
        MagnolienbaumPairing.AddPartner(a, forged, "203.0.113.9", false);
        TestAssert.That(peerB.ToJsonString() == originalB, "Unauthenticated known-key pairing changed a trusted partner.");
        forged["oeffentlich"] = State("attacker")["oeffentlich"]!.DeepClone();
        TestAssert.Throws<CryptographicException>(() => MagnolienbaumPairing.AddPartner(a, forged, "203.0.113.9", false), "Unauthenticated pairing replaced a pinned key.");

        var file = MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, now);
        var request = MagnolienbaumPairing.BuildRequest(b, file, now: now + 1);
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.BuildRequest(b, file, new byte[31], now + 1), "Malformed nonce was signed into a pairing request.");
        var invalid = request.DeepClone().AsObject(); invalid["beweis"] = MagnolienbaumCrypto.Base64Url(new byte[32]);
        var before = a.ToJsonString();
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.AcceptRequest(a, invalid, "203.0.113.9", now + 1), "Forged v2 proof changed a confirmed partner.");
        TestAssert.That(a.ToJsonString() == before, "Rejected v2 request changed state or consumed the invitation.");
        var wrongKey = State("beta");
        var wrongKeyRequest = MagnolienbaumPairing.BuildRequest(wrongKey, file, now: now + 1);
        TestAssert.Throws<CryptographicException>(() => MagnolienbaumPairing.AcceptRequest(a, wrongKeyRequest, "203.0.113.9", now + 1), "Valid invitation proof replaced an existing pinned key.");
        TestAssert.That(a.ToJsonString() == before, "Key rejection mutated trusted state.");

        var response = MagnolienbaumPairing.AcceptRequest(a, request, "203.0.113.9", now + 1);
        MagnolienbaumPairing.ValidateResponse(file, request, response);
        MagnolienbaumPairing.AddPartner(b, file["einlader"]!.AsObject(), "203.0.113.8", true);
        foreach (var (partner, original) in new[] { (peerA, originalA), (peerB, originalB) })
        {
            var expected = JsonNode.Parse(original)!.AsObject(); expected["protokoll"] = "baum-fs1"; expected["paarungsart"] = "datei-v2";
            TestAssert.That(JsonNode.DeepEquals(partner, expected), "Authenticated file upgrade failed or changed endpoint, key, consent, capabilities, counters or replay history.");
        }
        before = a.ToJsonString();
        TestAssert.That(JsonNode.DeepEquals(response, MagnolienbaumPairing.AcceptRequest(a, request, "192.0.2.99", now + 2)) && a.ToJsonString() == before,
            "Exact request replay was not idempotent or redirected the trusted peer.");
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.AcceptRequest(a, request, "192.0.2.99", now + 86402), "Expired replay receipt was accepted indefinitely.");
        var newNonce = MagnolienbaumPairing.BuildRequest(b, file, now: now + 2);
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.AcceptRequest(a, newNonce, "127.0.0.1", now + 2), "Consumed invitation accepted a different nonce.");
        var wrongNonceResponse = response.DeepClone().AsObject(); wrongNonceResponse["nonce"] = MagnolienbaumCrypto.Base64Url(RandomNumberGenerator.GetBytes(32));
        SignResponse(file, wrongNonceResponse);
        TestAssert.Throws<CryptographicException>(() => MagnolienbaumPairing.ValidateResponse(file, request, wrongNonceResponse), "Valid response MAC bypassed nonce binding.");
        var wrongIdentityResponse = response.DeepClone().AsObject(); wrongIdentityResponse["zweig"]!["oeffentlich"] = wrongKey["oeffentlich"]!.DeepClone();
        SignResponse(file, wrongIdentityResponse);
        TestAssert.Throws<CryptographicException>(() => MagnolienbaumPairing.ValidateResponse(file, request, wrongIdentityResponse), "Valid response MAC bypassed inviter key binding.");
        var expired = MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, now);
        var expiredRequest = MagnolienbaumPairing.BuildRequest(b, expired, now: now + 1);
        before = a.ToJsonString();
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.ValidateFile(expired, now + 900), "Expired selected file was accepted.");
        TestAssert.Throws<InvalidDataException>(() => MagnolienbaumPairing.AcceptRequest(a, expiredRequest, "127.0.0.1", now + 900), "Expired invitation upgraded a peer.");
        TestAssert.That(a.ToJsonString() == before, "Expired request mutated trusted state.");
        MagnolienbaumPairing.AddPartner(a, MagnolienbaumPairing.Identity(b), "203.0.113.9", false);
        TestAssert.That(a.ToJsonString() == before, "V1 request downgraded a file-upgraded peer.");

        // Exercise the actual selected-file coordinator path without contacting a real peer.
        peerA["protokoll"] = "baum-1"; peerA["paarungsart"] = "lokal-v1";
        var paths = new WindowsPaths(root); var storage = new MagnolienbaumStore(paths); storage.SaveState(b);
        var key = MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(b["geheim"]!.GetValue<string>()), Convert.FromBase64String(a["oeffentlich"]!.GetValue<string>()), "beta", "alpha");
        var envelope = MagnolienbaumCrypto.EncryptBaum1(key, "beta", 21, new JsonObject { ["art"] = "aufgabe", ["titel"] = "Queued legacy content" });
        CryptographicOperations.ZeroMemory(key);
        var queued = new JsonObject { ["id"] = "legacy-pending", ["transportId"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)), ["an"] = "alpha",
            ["art"] = "aufgabe", ["inhalt"] = new JsonObject { ["art"] = "aufgabe", ["titel"] = "Queued legacy content" },
            ["briefUmschlag"] = envelope, ["briefZaehler"] = 21L, ["versuche"] = 1, ["zuletzt"] = "", ["angelegt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") };
        storage.SaveOutbox(new JsonArray(queued.DeepClone()));
        var events = new List<JsonObject>(); var responder = a; var delayResponse = false; var tamperResponse = false; var calls = 0;
        using var coordinator = new MagnolienbaumCoordinator(paths, (name, payload) =>
        { if (name == "App.baumPaarungsdatei") events.Add(JsonSerializer.SerializeToNode(payload)!.AsObject()); return Task.CompletedTask; });
        using var http = new PairingHandler(async (message, _) =>
        {
            calls++;
            if (message.RequestUri!.AbsolutePath == "/magnolie/v2/paarung")
            {
                var incoming = JsonNode.Parse(await message.Content!.ReadAsStringAsync())!.AsObject();
                var result = MagnolienbaumPairing.AcceptRequest(responder, incoming, "127.0.0.1", DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                if (delayResponse) await Task.Delay(2100);
                if (tamperResponse) result["beweis"] = MagnolienbaumCrypto.Base64Url(new byte[32]);
                return Json(result);
            }
            TestAssert.That(message.RequestUri.AbsolutePath == "/magnolie/v1/nachricht" &&
                JsonNode.DeepEquals(JsonNode.Parse(await message.Content!.ReadAsStringAsync()), envelope), "Pending legacy envelope was re-encoded as a new FS1 delivery.");
            return Json(new JsonObject { ["ok"] = true, ["protokoll"] = "baum-1", ["vertraut"] = true, ["oeffentlich"] = wrongKey["oeffentlich"]!.DeepClone() });
        });
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        var clientField = typeof(MagnolienbaumCoordinator).GetField("client", flags)!;
        ((HttpClient)clientField.GetValue(coordinator)!).Dispose(); clientField.SetValue(coordinator, new HttpClient(http));
        using var sessionStart = MagnolienbaumFs1.BuildStart(a, peerB);
        var sessionResponse = coordinator.HandleProtocolRequest("/magnolie/v2/sitzung", sessionStart.Message, "127.0.0.1");
        TestAssert.That(sessionResponse.Status == 200, "Pinned-key session setup failed before upgrade.");
        using var session = MagnolienbaumFs1.OpenResponse(a, peerB, sessionStart.Message, sessionResponse.Body, sessionStart.EphemeralPrivate);
        var liveFile = MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        await coordinator.ImportPairingFileAsync(liveFile);
        var expectedPeer = JsonNode.Parse(originalA)!.AsObject(); expectedPeer["protokoll"] = "baum-fs1"; expectedPeer["paarungsart"] = "datei-v2";
        TestAssert.That(events.Last()["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer), "Selected-file coordinator did not persist the authenticated upgrade.");
        TestAssert.That(storage.LoadOutbox().OfType<JsonObject>().Any(item => JsonNode.DeepEquals(item, queued)), "Pairing upgrade discarded or rewrote pending user content.");
        var liveState = (JsonObject)typeof(MagnolienbaumCoordinator).GetField("state", flags)!.GetValue(coordinator)!;
        var livePeer = liveState["partner"]![0]!.AsObject();
        var delivery = typeof(MagnolienbaumCoordinator).GetMethod("DeliverAsync", flags)!;
        TestAssert.That(!await (Task<bool>)delivery.Invoke(coordinator, [livePeer, queued, CancellationToken.None])! && JsonNode.DeepEquals(livePeer, expectedPeer), "Unauthenticated legacy ACK was accepted or changed the trusted peer.");
        var forgedNetwork = MagnolienbaumPairing.Identity(a); forgedNetwork["port"] = 1; forgedNetwork["name"] = "Forged";
        TestAssert.That(coordinator.HandleProtocolRequest("/magnolie/v1/paarung", forgedNetwork, "203.0.113.9").Status == 200 &&
            JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer), "Unauthenticated coordinator route mutated trusted state.");
        var receiverFile = coordinator.CreatePairingFile("127.0.0.1", 8737);
        var receiverRequest = MagnolienbaumPairing.BuildRequest(a, receiverFile);
        var firstReceipt = coordinator.HandleProtocolRequest("/magnolie/v2/paarung", receiverRequest, "127.0.0.1");
        TestAssert.That(firstReceipt.Status == 200, "Fresh receiver-side file exchange failed.");
        var outboxField = typeof(MagnolienbaumCoordinator).GetField("outbox", flags)!;
        var afterProbeDelivery = new JsonArray(((JsonArray)outboxField.GetValue(coordinator)!).OfType<JsonObject>()
            .Where(item => item["art"]?.GetValue<string>() != "kontakt_faehigkeiten").Select(item => item.DeepClone()).ToArray());
        outboxField.SetValue(coordinator, afterProbeDelivery); storage.SaveOutbox(afterProbeDelivery);
        var replayReceipt = coordinator.HandleProtocolRequest("/magnolie/v2/paarung", receiverRequest, "203.0.113.9");
        TestAssert.That(replayReceipt.Status == 200 && JsonNode.DeepEquals(firstReceipt.Body, replayReceipt.Body) &&
            JsonNode.DeepEquals(storage.LoadOutbox(), afterProbeDelivery) && JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer),
            "Captured pairing replay changed trusted state or requeued capability probes.");
        responder = State("alpha");
        var replacementFile = MagnolienbaumPairing.CreateFile(responder, "127.0.0.1", 8737, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        await coordinator.ImportPairingFileAsync(replacementFile);
        TestAssert.That(!events.Last()["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer), "Authenticated file import replaced a pinned key.");
        responder = a;
        var invalidFile = MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        invalidFile["mac"] = MagnolienbaumCrypto.Base64Url(new byte[32]); var previousCalls = calls;
        await coordinator.ImportPairingFileAsync(invalidFile);
        TestAssert.That(!events.Last()["ok"]!.GetValue<bool>() && calls == previousCalls, "Invalid selected file reached the network.");
        tamperResponse = true;
        await coordinator.ImportPairingFileAsync(MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, DateTimeOffset.UtcNow.ToUnixTimeSeconds()));
        TestAssert.That(!events.Last()["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer), "Forged pairing response changed trusted state.");
        tamperResponse = false; delayResponse = true;
        await coordinator.ImportPairingFileAsync(MagnolienbaumPairing.CreateFile(a, "127.0.0.1", 8737, DateTimeOffset.UtcNow.ToUnixTimeSeconds() - 899));
        TestAssert.That(!events.Last()["ok"]!.GetValue<bool>() && JsonNode.DeepEquals(storage.LoadOrCreate()["partner"]![0], expectedPeer), "File expiring in flight was applied as a fresh authorization.");
        var sessionEnvelope = MagnolienbaumFs1.BuildEnvelope(session, "alpha", "beta", new JsonObject { ["art"] = "aufgabe", ["titel"] = "Existing authenticated session" }, Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)));
        var sessionResult = coordinator.HandleProtocolRequest("/magnolie/v2/nachricht", sessionEnvelope, "127.0.0.1");
        TestAssert.That(sessionResult.Status == 200 && MagnolienbaumFs1.VerifyAcknowledgement(session, sessionEnvelope, sessionResult.Body), "Same-key protocol upgrade discarded a valid source-bound session.");
    }

    private static JsonObject State(string id)
    {
        var keys = MagnolienbaumCrypto.GenerateX25519();
        return new JsonObject { ["kennung"] = id, ["name"] = id, ["geheim"] = Convert.ToBase64String(keys.Private), ["oeffentlich"] = Convert.ToBase64String(keys.Public),
            ["port"] = 8737, ["an"] = true, ["partner"] = new JsonArray() };
    }

    private static JsonObject Trust(JsonObject state, JsonObject peer)
    {
        var value = MagnolienbaumPairing.AddPartner(state, MagnolienbaumPairing.Identity(peer), "127.0.0.1", false);
        value["bestaetigt"] = true; value["wartet"] = false; value["vertraut"] = false; value["kontakte"] = false; value["kontaktLoeschen"] = false;
        value["zaehler_raus"] = 21L; value["zaehler_rein"] = 17L; value["transportIds"] = new JsonArray("seen");
        value["kontaktSyncFassungen"] = new JsonArray(1, 2); value["kontaktImportFassungen"] = new JsonArray(1);
        return value;
    }

    private static void SignResponse(JsonObject file, JsonObject response)
    {
        response.Remove("beweis");
        response["beweis"] = MagnolienbaumCrypto.Base64Url(MagnolienbaumCrypto.Hmac(MagnolienbaumCrypto.ReadBase64Url(file["geheimnis"]!.GetValue<string>(), 32),
            "magnolie-pair-response-v2\0"u8.ToArray(), response));
    }

    private static HttpResponseMessage Json(JsonObject value) => new(HttpStatusCode.OK) { Content = new StringContent(value.ToJsonString()) };
    private sealed class PairingHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> handler) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => handler(request, cancellationToken);
    }
}
