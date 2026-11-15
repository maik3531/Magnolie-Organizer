using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NotesOriginalPendingTests
{
    internal static async Task RunAsync(string root)
    {
        foreach (var mode in new[] { "success", "duplicate", "conflict", "wrong-result", "bool-version", "float-version", "stale-revision",
            "extra-result", "bad-export-hash", "bad-setup", "cancel-choice", "chooser-book-change", "choice-revoke", "source-revoke",
            "stop-before-save", "changed-book", "mixed-content", "failed-primary", "fake-witness", "same-hash-display-change", "unchanged" })
            await ScenarioAsync(Path.Combine(root, mode), mode);
        Projection();
        Console.WriteLine("Notes native export/result/writer: 21 synthetic scenarios plus projection guards passed (actual generated SaveAsync, no durable ACK history).");
    }

    private static async Task ScenarioAsync(string root, string mode)
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
        target["bestaetigt"] = true; peer["bestaetigt"] = true; peer["vertraut"] = true; peer["kontaktSync"] = true;
        var paths = new WindowsPaths(Path.Combine(root, "tree")); var storage = new MagnolienbaumStore(paths); storage.SaveState(local);
        using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        var before = new JsonObject { ["vorname"] = "Provider", ["nachname"] = "Original", ["anzeigename"] = "Provider Original",
            ["vcardName"] = new JsonArray("N:Original;Provider;;;", "FN:Provider Original"), ["anschriften"] = new JsonArray(),
            ["telefone"] = new JsonArray(new JsonObject { ["art"] = "mobil", ["wert"] = "+491234" }),
            ["emailEintraege"] = new JsonArray(new JsonObject { ["art"] = "arbeit", ["wert"] = "synthetic@example.invalid" }),
            ["foto"] = "preserved-native-photo", ["gruppen"] = new JsonArray("Preserved Group") };
        var selected = new JsonObject { ["id"] = "chosen-id", ["uid"] = "canonical-uid", ["vorname"] = "Local", ["nachname"] = "Original",
            ["anzeigename"] = "Local Original", ["vcardRoundtrip"] = new JsonArray("N:Original;Local;;;", "FN:Local Original"),
            ["anschriften"] = new JsonArray(), ["telefon"] = "not-a-requested-field" };
        if (mode is "unchanged" or "same-hash-display-change")
        {
            selected["vorname"] = "Provider"; selected["anzeigename"] = "Provider Original";
            selected["vcardRoundtrip"] = new JsonArray("N:Original;Provider;;;", mode == "unchanged" ? "FN:Provider Original" : "FN:Literal different display");
        }
        if (mode == "same-hash-display-change")
        {
            before.Remove("gruppen"); before["anzeigename"] = ""; before["vcardName"] = new JsonArray();
            selected["vcardRoundtrip"] = new JsonArray();
        }
        var book = new JsonObject { ["kontakte"] = new JsonArray(selected, new JsonObject { ["id"] = "unrelated", ["uid"] = "other-uid", ["notiz"] = "Preserve other contact" }),
            ["independent-domain"] = "preserve", ["syncEpoch"] = "synthetic-save-epoch" };
        var host = new PersonalActorNativeSaveHost(Path.Combine(root, "book"), book.ToJsonString());
        var original = host.Saved()!; var originalBytes = File.ReadAllBytes(host.DataPath);
        var export = new JsonObject { ["art"] = "kontakt_original_export", ["fassung"] = 1, ["share_id"] = "private-original-share",
            ["before_basis"] = new string('b', 64), ["setup_id"] = "11111111-1111-4111-8111-111111111111", ["native_revision"] = 1L,
            ["content_sha256"] = NotesOriginalReturnHash.ContentHash(before), ["kontakt"] = before.DeepClone() };
        if (mode == "bad-export-hash") export["content_sha256"] = new string('0', 64);
        if (mode == "bad-setup") export["setup_id"] = true;
        JsonObject? observed = null; MagnolienbaumCoordinator.NativeNotesOrigin? exportOrigin = null; string exportTransport = "";
        NotesOriginalPendingResult? pending = null; var receiving = false; var granted = true; var choices = 0;
        NativeActorBookSnapshot? Capture()
        { TestAssert.That(!receiving, "Book access in FS1 callback"); return host.Snapshot(); }
        void SourceGuard()
        { TestAssert.That(!receiving, "Source permission access in FS1 callback"); if (!granted) throw new InvalidOperationException("synthetic-source-revoked"); }
        coordinator.NotesOriginalReceive = (_, body, origin, mid) =>
        {
            receiving = true;
            try
            {
                if (body["art"]!.GetValue<string>() == "kontakt_original_export")
                { observed = body.DeepClone().AsObject(); exportOrigin = origin; exportTransport = mid; }
                else pending!.StageResult(body, origin, mid);
                return true;
            }
            finally { receiving = false; }
        };
        int Send(JsonObject body)
        {
            using var start = MagnolienbaumFs1.BuildStart(remote, target);
            var reply = coordinator.HandleProtocolRequest("/magnolie/v2/sitzung", start.Message, "127.0.0.1");
            TestAssert.That(reply.Status == 200, "Synthetic genuine FS1 handshake failed");
            using var session = MagnolienbaumFs1.OpenResponse(remote, target, start.Message, reply.Body, start.EphemeralPrivate);
            var envelope = MagnolienbaumFs1.BuildEnvelope(session, "synthetic-notes", "synthetic-desktop", body,
                Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)));
            var result = coordinator.HandleProtocolRequest("/magnolie/v2/nachricht", envelope, "127.0.0.1");
            if (result.Status == 200) TestAssert.That(MagnolienbaumFs1.VerifyAcknowledgement(session, envelope, result.Body), "FS1 receipt is not genuine");
            return result.Status;
        }
        TestAssert.That(Send(export) == 200 && observed is not null, "Native export was not staged");
        string? Choose(IReadOnlyList<JsonObject> values)
        {
            TestAssert.That(!receiving && values.Count == 2, "Choice invoked inside receive or against another native book"); choices++;
            if (mode == "chooser-book-change")
            {
                // A fresh successful native saved observation, not a fake flag.
                var owner = (NativeBookOwnerScope)typeof(PersonalActorNativeSaveHost).GetField("actorBookOwner", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(host)!;
                owner.RecordSaved(Path.GetFullPath(host.DataPath), true, original.Sha256);
            }
            return mode == "cancel-choice" ? null : "chosen-id";
        }
        if (mode is "bad-export-hash" or "bad-setup" or "cancel-choice" or "chooser-book-change")
        {
            var rejected = false;
            try { _ = new NotesOriginalExportChoice(observed!, exportOrigin!, exportTransport, Capture()!, Capture, Choose, SourceGuard); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException) { rejected = true; }
            TestAssert.That(rejected && choices == (mode is "cancel-choice" or "chooser-book-change" ? 1 : 0) &&
                File.ReadAllBytes(host.DataPath).AsSpan().SequenceEqual(originalBytes), "Rejected native export/choice reached writer");
            return;
        }
        var choice = new NotesOriginalExportChoice(observed!, exportOrigin!, exportTransport, Capture()!, Capture, Choose, SourceGuard);
        pending = choice.CreatePending();
        TestAssert.Throws<InvalidOperationException>(() => new NotesOriginalPendingResult(new object()), "Counterfeit pending seed accepted");
        if (mode == "unchanged") { TestAssert.That(pending is null && choices == 1, "Exact no-op created pending mutation"); return; }
        TestAssert.That(pending is not null, "Real exact target change was erased by semantic hash equality");
        var request = pending!.Request(); var targetContent = before.DeepClone().AsObject();
        foreach (var field in request["ziel"]!.AsObject()) targetContent[field.Key] = field.Value?.DeepClone();
        if (mode == "same-hash-display-change") TestAssert.That(request["target_sha256"]!.GetValue<string>() == export["content_sha256"]!.GetValue<string>() &&
            request["ziel"]!["anzeigename"]!.GetValue<string>() != before["anzeigename"]!.GetValue<string>(), "Synthetic semantic-hash collision was not exercised");
        TestAssert.That(request["ziel"]!.AsObject().Count == 9 && request["target_sha256"]!.GetValue<string>() == NotesOriginalReturnHash.ContentHash(targetContent) &&
            request["ziel"]!["telefone"] is null && request["ziel"]!["foto"] is null, "Native request altered excluded fields");
        var resultBody = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1,
            ["request_sha256"] = NotesOriginalSchema.Hash(request), ["receipt_id"] = "22222222-2222-4222-8222-222222222222",
            ["native_revision"] = long.MaxValue, ["next_basis"] = new string('d', 64) };
        foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) resultBody[name] = request[name]!.DeepClone();
        if (mode == "wrong-result") resultBody["request_sha256"] = new string('0', 64);
        if (mode == "bool-version") resultBody["fassung"] = true;
        if (mode == "float-version") resultBody["fassung"] = JsonNode.Parse("1.0");
        if (mode == "stale-revision") resultBody["native_revision"] = 1;
        if (mode == "extra-result") resultBody["confirmed"] = true;
        if (mode is "wrong-result" or "bool-version" or "float-version" or "stale-revision" or "extra-result")
        {
            TestAssert.That(Send(resultBody) == 403, "Invalid native result admitted");
            TestAssert.Throws<InvalidOperationException>(() => pending.PrepareCommit(host.SourceResultCommit), "Invalid result prepared writer");
            return;
        }
        TestAssert.That(Send(resultBody) == 200, "Native result was not staged");
        if (mode == "duplicate") TestAssert.That(Send(resultBody) == 200, "Identical result was not idempotent");
        if (mode == "conflict")
        {
            var conflict = resultBody.DeepClone().AsObject(); conflict["receipt_id"] = Guid.NewGuid().ToString();
            TestAssert.That(Send(conflict) == 403, "Conflicting result was accepted");
            TestAssert.Throws<InvalidOperationException>(() => pending.PrepareCommit(host.SourceResultCommit), "Conflict did not hold local writer");
            return;
        }
        TestAssert.Throws<InvalidOperationException>(() => pending.ConfirmedSave(), "Result/transport receipt fabricated a saved witness");
        var commit = pending.PrepareCommit(host.SourceResultCommit);
        TestAssert.That(ReferenceEquals(commit, pending.PrepareCommit(host.SourceResultCommit)), "Duplicate result created new writer invocation");
        var proposal = JsonNode.Parse(commit.Text)!.AsObject();
        if (mode == "choice-revoke") choice.Revoke();
        if (mode == "source-revoke") granted = false;
        if (mode == "stop-before-save") await coordinator.StopAsync();
        if (mode == "changed-book") await host.SaveOriginalContactResultAsync("", book.DeepClone().AsObject());
        if (mode == "mixed-content") proposal["independent-domain"] = "unauthorized";
        if (mode == "failed-primary") host.FailAfterPrimary = true;
        if (mode == "fake-witness")
        {
            TestAssert.Throws<InvalidOperationException>(() => new ContactSourceSavedCommit.SavedWitness(new object()).RequireCurrent(), "Boolean/copied witness accepted");
            TestAssert.Throws<InvalidOperationException>(() => pending.ConfirmedSave(), "Unwritten invocation fabricated saved witness");
            return;
        }
        var replySave = await host.SaveOriginalContactResultAsync(commit.Offer.Token, proposal);
        if (mode is "choice-revoke" or "source-revoke" or "stop-before-save" or "changed-book" or "mixed-content" or "failed-primary")
        {
            TestAssert.That(!replySave["ok"]!.GetValue<bool>(), "Stale/mixed/failed native writer was acknowledged: " + mode);
            TestAssert.Throws<InvalidOperationException>(() => pending.ConfirmedSave(), "Rejected native writer issued saved witness");
            if (mode is not ("changed-book" or "failed-primary")) TestAssert.That(File.ReadAllBytes(host.DataPath).AsSpan().SequenceEqual(originalBytes), "Rejected writer changed encrypted book");
            return;
        }
        TestAssert.That(replySave["ok"]!.GetValue<bool>() && pending.ConfirmedSave().RequireCurrent() == host.Saved() && host.Saved()!.Sequence == original.Sequence + 1,
            "Actual generated encrypted SaveAsync did not supply a real witness");
        var saved = JsonNode.Parse(new EncryptionService().Unlock(File.ReadAllText(host.DataPath), PersonalActorNativeSaveHost.Password))!.AsObject();
        var unchangedContact = saved["kontakte"]![0]!.DeepClone().AsObject(); unchangedContact.Remove("notesOriginalBasis");
        TestAssert.That(saved["independent-domain"]!.GetValue<string>() == "preserve" &&
            JsonNode.DeepEquals(unchangedContact, book["kontakte"]![0]) &&
            JsonNode.DeepEquals(saved["kontakte"]![1], book["kontakte"]![1]) &&
            saved["kontakte"]![0]!["uid"]!.GetValue<string>() == "canonical-uid" &&
            saved["kontakte"]![0]!["notesOriginalBasis"]!["native_revision"]!.GetValue<string>() == long.MaxValue.ToString(),
            "Metadata commit altered canonical identity/other domain or lost exact Long revision");
        TestAssert.That(!JsonNode.DeepEquals(saved, book), "Actual metadata commit did not reach encrypted primary");
    }

    private static void Projection()
    {
        var contact = new JsonObject { ["geburtstag"] = "2000-02-03", ["geburtstagJahrUnbekannt"] = true,
            ["vcardRoundtrip"] = new JsonArray("FN:Preserve", "X-NOT-A-NAME:ignore"),
            ["anschriften"] = new JsonArray(new JsonObject { ["typen"] = new JsonArray("HOME"), ["strasse"] = "Synthetic" }) };
        var projected = NotesOriginalExportChoice.Project(contact, new());
        TestAssert.That(projected["geburtstag"]!.GetValue<string>() == "--02-03" && projected["vcardName"]!.AsArray().Count == 1 &&
            projected["anschriften"]![0]!["art"]!.GetValue<string>() == "privat", "Native saved projection mismatch");
        contact["anschriften"]![0]!["typen"] = new JsonArray("HOME", "WORK");
        TestAssert.Throws<InvalidDataException>(() => NotesOriginalExportChoice.Project(contact, new()), "Unsupported postal type silently reduced");
        contact["anschriften"]![0]!["typen"] = new JsonArray(); contact["anschriften"]![0]!["label"] = "not-supported";
        TestAssert.Throws<InvalidDataException>(() => NotesOriginalExportChoice.Project(contact, new()), "Changed custom postal label silently reduced");
        TestAssert.That(!NotesOriginalSchema.Share("\ud800") && NotesOriginalSchema.Share("valid-🌱"), "Share Unicode scalar validation mismatch");
    }
}
