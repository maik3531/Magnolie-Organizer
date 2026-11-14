using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NotesOriginalReceiveTests
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;

    internal static void Run(string root)
    {
        foreach (var mode in new[] { "success", "export", "result", "status", "request-denied", "ack-denied", "query-denied",
            "default-off", "refused", "late-revoke", "body", "transport", "peer-pin",
            "own-pin", "revoked", "stop", "stop-before-receive", "disposed", "expiry", "oversize", "fake", "generic" })
            Scenario(Path.Combine(root, mode), mode);
        Console.WriteLine("Notes native FS1 origin: 22 synthetic scenarios passed (no installed counterpart acceptance).");
    }

    private static void Scenario(string root, string mode)
    {
        JsonObject State(string id)
        {
            var keys = MagnolienbaumCrypto.GenerateX25519();
            return new() { ["kennung"] = id, ["name"] = id, ["geheim"] = Convert.ToBase64String(keys.Private),
                ["oeffentlich"] = Convert.ToBase64String(keys.Public), ["port"] = 8737, ["an"] = true, ["partner"] = new JsonArray() };
        }
        var remote = State("synthetic-notes"); var local = State("synthetic-desktop");
        var target = MagnolienbaumPairing.AddPartner(remote, MagnolienbaumPairing.Identity(local), "127.0.0.1", false);
        var peer = MagnolienbaumPairing.AddPartner(local, MagnolienbaumPairing.Identity(remote), "127.0.0.1", false);
        target["bestaetigt"] = true; peer["bestaetigt"] = true;
        peer["vertraut"] = true; peer["kontaktSync"] = true;
        var paths = new WindowsPaths(root); var storage = new MagnolienbaumStore(paths); storage.SaveState(local);
        using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        var live = (JsonObject)typeof(MagnolienbaumCoordinator).GetField("state", Private)!.GetValue(coordinator)!;
        var currentPeer = live["partner"]![0]!.AsObject();
        var body = new JsonObject { ["art"] = "kontakt_original_aushandlung", ["fassung"] = 1,
            ["challenge"] = Guid.NewGuid().ToString(), ["antwort"] = true, ["profil"] = "notes-original-return-draft1" };
        body["art"] = mode switch
        {
            "export" => "kontakt_original_export", "result" => "kontakt_original_ergebnis", "status" => "kontakt_original_abschlussstatus",
            "request-denied" => "kontakt_original_anfrage", "ack-denied" => "kontakt_original_saveack", "query-denied" => "kontakt_original_statusanfrage",
            _ => "kontakt_original_aushandlung"
        };
        if (mode == "oversize") body["oversize"] = new string('x', 256 * 1024);
        MagnolienbaumCoordinator.NativeNotesOrigin? captured = null;
        string transport = ""; var received = 0;
        if (mode != "default-off") coordinator.NotesOriginalReceive = (who, content, origin, mid) =>
        {
            received++; captured = origin; transport = mid;
            var pins = origin.RequireCurrent(content, mid);
            TestAssert.That(pins.Peer.Id == "synthetic-notes" && pins.Own.Id == "synthetic-desktop" &&
                who["kennung"]!.GetValue<string>() == pins.Peer.Id, "Native origin relabeled genuine FS1 pins.");
            if (mode == "late-revoke") currentPeer["kontaktSync"] = false;
            return mode != "refused";
        };
        using var start = MagnolienbaumFs1.BuildStart(remote, target);
        var response = coordinator.HandleProtocolRequest("/magnolie/v2/sitzung", start.Message, "127.0.0.1");
        TestAssert.That(response.Status == 200, "Synthetic FS1 handshake failed.");
        using var session = MagnolienbaumFs1.OpenResponse(remote, target, start.Message, response.Body, start.EphemeralPrivate);
        if (mode == "stop-before-receive") coordinator.StopAsync().GetAwaiter().GetResult();
        var envelope = MagnolienbaumFs1.BuildEnvelope(session, "synthetic-notes", "synthetic-desktop", body,
            Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)));
        var delivered = coordinator.HandleProtocolRequest("/magnolie/v2/nachricht", envelope, "127.0.0.1");
        if (mode is "default-off" or "refused" or "late-revoke" or "oversize" or "stop-before-receive" or "request-denied" or "ack-denied" or "query-denied")
        {
            TestAssert.That(delivered.Status == 403 && received == (mode is "refused" or "late-revoke" ? 1 : 0), "Draft receive bypassed native admission.");
            TestAssert.That(storage.LoadInbox().Count == 0, "Rejected draft reached generic inbox.");
            return;
        }
        TestAssert.That(delivered.Status == 200 && received == 1 && captured is not null &&
            MagnolienbaumFs1.VerifyAcknowledgement(session, envelope, delivered.Body) && storage.LoadInbox().Count == 0,
            "Native draft did not remain separate from generic inbox/transport acceptance.");
        if (mode is "success" or "export" or "result" or "status")
        {
            _ = captured!.RequireCurrent(body.DeepClone().AsObject(), transport);
            return;
        }
        if (mode == "fake") captured = new(new object());
        if (mode == "body") body["challenge"] = Guid.NewGuid().ToString();
        if (mode == "transport") transport = "copied-transport";
        if (mode == "peer-pin") currentPeer["oeffentlich"] = State("replacement")["oeffentlich"]!.DeepClone();
        if (mode == "own-pin") live["kennung"] = "changed-desktop-id";
        if (mode == "revoked") currentPeer["kontaktSync"] = false;
        if (mode == "stop") coordinator.StopAsync().GetAwaiter().GetResult();
        if (mode == "disposed") coordinator.Dispose();
        if (mode == "expiry")
        {
            // Only shorten the genuine proof's deadline in this synthetic test;
            // no alternate production clock or public origin issuer is added.
            var proof = captured!.GetType().GetFields(Private).Single().GetValue(captured)!;
            proof.GetType().GetProperty("Expires")!.SetValue(proof, 0L);
        }
        if (mode == "generic")
        {
            var key = MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(remote["geheim"]!.GetValue<string>()),
                Convert.FromBase64String(local["oeffentlich"]!.GetValue<string>()), "synthetic-notes", "synthetic-desktop");
            try
            {
                foreach (var kind in new[] { "kontakt_original_aushandlung", "kontakt_original_export", "kontakt_original_ergebnis",
                    "kontakt_original_abschlussstatus", "kontakt_original_anfrage", "kontakt_original_saveack", "kontakt_original_statusanfrage" })
                {
                    var copied = body.DeepClone().AsObject(); copied["art"] = kind;
                    var legacy = MagnolienbaumCrypto.EncryptBaum1(key, "synthetic-notes", 1L, copied);
                    TestAssert.That(coordinator.HandleProtocolRequest("/magnolie/v1/nachricht", legacy, "127.0.0.1").Status == 403,
                        "Copied draft entered generic legacy receive: " + kind);
                }
            }
            finally { CryptographicOperations.ZeroMemory(key); }
            TestAssert.That(storage.LoadInbox().Count == 0, "Generic rejection persisted a draft.");
            return;
        }
        TestAssert.Throws<InvalidOperationException>(() => captured!.RequireCurrent(body, transport), "Stale/copied native FS1 origin remained usable.");
    }
}
