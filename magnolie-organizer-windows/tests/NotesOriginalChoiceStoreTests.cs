using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NotesOriginalChoiceStoreTests
{
    private sealed class CallbackViolation : Exception { }
    private sealed class Protector : ISecretProtector, IDisposable
    {
        private readonly byte[] key = RandomNumberGenerator.GetBytes(32);
        internal bool Unavailable, Raw;
        internal readonly List<byte[]> Secrets = [];
        public byte[] Protect(byte[] plain)
        {
            Secrets.Add(plain);
            if (Raw) return plain.ToArray();
            var output = new byte[plain.Length + 28]; RandomNumberGenerator.Fill(output.AsSpan(0, 12));
            using var aes = new AesGcm(key, 16);
            aes.Encrypt(output.AsSpan(0, 12), plain, output.AsSpan(12, plain.Length), output.AsSpan(12 + plain.Length, 16));
            return output;
        }
        public byte[] Unprotect(byte[] cipher)
        {
            if (Unavailable) throw new CryptographicException("synthetic-key-unavailable");
            var plain = new byte[cipher.Length - 28];
            using var aes = new AesGcm(key, 16);
            aes.Decrypt(cipher.AsSpan(0, 12), cipher.AsSpan(12, plain.Length), cipher.AsSpan(12 + plain.Length, 16), plain);
            Secrets.Add(plain); return plain;
        }
        public void Dispose() => CryptographicOperations.ZeroMemory(key);
    }

    private sealed class Fixture : IDisposable
    {
        internal readonly string Root, ConsentRoot;
        internal readonly Protector Protector = new();
        internal readonly JsonObject Export, Book;
        internal readonly MagnolienbaumCoordinator Coordinator;
        internal PersonalActorNativeSaveHost Host;
        internal readonly NotesOriginalChoiceStore Store;
        internal readonly NotesOriginalExportChoice Choice;
        internal int Choices;
        internal bool NoCallbacks, CheckOutsideLock;
        internal Action? GuardHook;
        internal string? FailSaveStage;
        private readonly bool nativeDefault;
        private readonly JsonObject sender, target;
        private bool receiving;
        private JsonObject? observed;
        private MagnolienbaumCoordinator.NativeNotesOrigin? origin;
        private string transport = "";
        internal NotesOriginalPendingResult? PendingResult;
        internal NotesOriginalNegotiation? Protocol;
        internal bool CaptureRecovery;
        internal (JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport) RecoveryObservation =>
            (observed!.DeepClone().AsObject(), origin!, transport);

        internal Fixture(string root, bool nativeDefault = false)
        {
            Root = root; ConsentRoot = Path.Combine(root, "private-choice"); this.nativeDefault = nativeDefault;
            JsonObject State(string id)
            {
                var keys = MagnolienbaumCrypto.GenerateX25519();
                return new() { ["kennung"] = id, ["name"] = id, ["geheim"] = Convert.ToBase64String(keys.Private),
                    ["oeffentlich"] = Convert.ToBase64String(keys.Public), ["port"] = 8737, ["an"] = true, ["partner"] = new JsonArray() };
            }
            sender = State("synthetic-notes"); var receiver = State("synthetic-desktop");
            target = MagnolienbaumPairing.AddPartner(sender, MagnolienbaumPairing.Identity(receiver), "127.0.0.1", false);
            var peer = MagnolienbaumPairing.AddPartner(receiver, MagnolienbaumPairing.Identity(sender), "127.0.0.1", false);
            target["bestaetigt"] = true; peer["bestaetigt"] = true; peer["vertraut"] = true; peer["kontaktSync"] = true;
            var paths = new WindowsPaths(Path.Combine(root, "tree")); new MagnolienbaumStore(paths).SaveState(receiver);
            Coordinator = new(paths, (_, _) => Task.CompletedTask);
            var contact = new JsonObject { ["id"] = "chosen-private-id", ["uid"] = "canonical-private-uid", ["vorname"] = "Local",
                ["notesOriginalBasis"] = new JsonObject { ["permission"] = true, ["auto"] = true } };
            Book = new() { ["kontakte"] = new JsonArray(contact), ["other-domain"] = "preserve", ["syncEpoch"] = "synthetic" };
            Host = new(Path.Combine(root, "book"), Book.ToJsonString()); Store = NewStore();
            var before = new JsonObject { ["vorname"] = "Provider" };
            Export = new() { ["art"] = "kontakt_original_export", ["fassung"] = 1, ["share_id"] = "private-original-share",
                ["setup_id"] = "11111111-1111-4111-8111-111111111111", ["native_revision"] = 1, ["before_basis"] = new string('b', 64),
                ["content_sha256"] = NotesOriginalReturnHash.ContentHash(before), ["kontakt"] = before };
            Coordinator.NotesOriginalReceive = (_, body, proof, mid) =>
            {
                receiving = true;
                try
                {
                    if (body["art"]!.GetValue<string>() == "kontakt_original_aushandlung" && Protocol is not null)
                        Protocol.Accept(body, proof, mid);
                    else if (!CaptureRecovery && body["art"]!.GetValue<string>() == "kontakt_original_ergebnis" && PendingResult is not null)
                        PendingResult.StageResult(body, proof, mid);
                    else { observed = body.DeepClone().AsObject(); origin = proof; transport = mid; }
                    return true;
                }
                finally { receiving = false; }
            };
            Send(Export); Choice = MakeChoice();
        }

        private void Outside()
        {
            if (receiving || NoCallbacks) throw new CallbackViolation();
            if (CheckOutsideLock) _ = Store.HasDesiredConsent(); // Would fail if our file session were still locked.
        }
        internal NativeActorBookSnapshot? Capture() { Outside(); return Host.Snapshot(); }
        internal ContactSourcePrimaryBook Primary() { Outside(); return Host.Primary(); }
        private string Binding() { Outside(); return Path.GetFullPath(Host.DataPath); }
        internal NotesOriginalChoiceStore NewStore() => new(new(ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()),
            Capture, Primary, Binding, nativeDefault ? null : Protector, () => Host.CurrentNativeText,
            stage => { if (stage == FailSaveStage) throw new IOException("synthetic-notes-consent-save-interruption"); });
        internal void Send(JsonObject body)
        {
            using var start = MagnolienbaumFs1.BuildStart(sender, target);
            var response = Coordinator.HandleProtocolRequest("/magnolie/v2/sitzung", start.Message, "127.0.0.1");
            TestAssert.That(response.Status == 200, "Synthetic native consent FS1 handshake failed");
            using var session = MagnolienbaumFs1.OpenResponse(sender, target, start.Message, response.Body, start.EphemeralPrivate);
            var envelope = MagnolienbaumFs1.BuildEnvelope(session, "synthetic-notes", "synthetic-desktop", body,
                Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)));
            var result = Coordinator.HandleProtocolRequest("/magnolie/v2/nachricht", envelope, "127.0.0.1");
            TestAssert.That(result.Status == 200 && MagnolienbaumFs1.VerifyAcknowledgement(session, envelope, result.Body), "Genuine consent export not staged");
        }
        internal NotesOriginalExportChoice MakeChoice() => new(observed!, origin!, transport, Capture()!, Capture,
            _ => { Outside(); Choices++; return "chosen-private-id"; }, () => { Outside(); GuardHook?.Invoke(); });
        internal NotesOriginalExportChoice Restore(NotesOriginalChoiceStore? store = null) => (store ?? Store).Restore(observed!, origin!, transport);
        internal string File(string name) => Path.Combine(ConsentRoot, name);
        public void Dispose() { Coordinator.Dispose(); Protector.Dispose(); }
    }

    private static void Hold(Action action)
    {
        try { action(); }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or CryptographicException or JsonException or FormatException or IOException or UnauthorizedAccessException) { return; }
        throw new Exception("Unknown private consent state granted authority");
    }

    internal static async Task RunAsync(string root)
    {
        var modes = new[] { "missing", "restore", "revoke", "lost-key", "corrupt", "pending", "old-record-replay", "foreign-book", "foreign-choice",
            "wrong-setup", "wrong-share", "changed-book", "same-content-save", "reopen-no-witness", "raw-protector", "fake-seal",
            "callbacks-outside-lock", "newer-decision-cas", "changed-during-approval", "zeroed-keys", "unavailable-key", "native-default" };
        foreach (var mode in modes) await ScenarioAsync(Path.Combine(root, mode), mode);
        Console.WriteLine($"Notes durable private consent core: {modes.Length} synthetic scenarios passed (stable-book only; no native save-chain activation).");
    }

    internal static async Task SaveChainAsync(string root)
    {
        var modes = new[] { "actual-save", "actual-metadata", "first-real-save", "prepared-before-write", "failed-primary-recover",
            "fake-intent", "foreign-intent-owner", "wrong-target", "tampered-intent", "no-rollback", "revoke", "newer-decision",
            "callbacks-outside-lock", "uid-change", "missing-current-model" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode)); h.Store.Approve([h.Choice]);
            var oldKey = System.IO.File.ReadAllText(h.File(".key.dpapi")); var next = h.Book.DeepClone().AsObject(); next["known-user-edit"] = "preserve";
            if (mode == "fake-intent")
            {
                Hold(() => h.Store.ConfirmSave(new(new object()), h.Host.Snapshot()!)); continue;
            }
            if (mode == "missing-current-model")
            {
                h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
                var unowned = new NotesOriginalChoiceStore(new(h.ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()), h.Capture, h.Primary,
                    () => Path.GetFullPath(h.Host.DataPath), h.Protector);
                Hold(() => unowned.PrepareCurrentSave(h.Book.ToJsonString()));
                TestAssert.That(!System.IO.File.Exists(h.File(".save-intent.json")) && h.Host.Snapshot() is null, "Unsaved primary bypassed owned native model"); continue;
            }
            if (mode is "actual-save" or "callbacks-outside-lock" or "uid-change" or "actual-metadata" or "first-real-save" or "failed-primary-recover")
            {
                h.Host.NativeNotesChoices = h.Store;
                if (mode == "callbacks-outside-lock") h.CheckOutsideLock = true;
                if (mode == "first-real-save")
                {
                    h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true); h.Host.NativeNotesChoices = h.Store;
                    TestAssert.That(h.Host.Snapshot() is null, "Reopen fabricated saved observation"); next = h.Book.DeepClone().AsObject();
                }
                if (mode == "uid-change") next["kontakte"]![0]!["uid"] = "changed-canonical-identity";
                NotesOriginalPendingResult? pending = null; NotesOriginalPendingResult.NativeCommit? metadata = null;
                if (mode == "actual-metadata")
                {
                    pending = h.Choice.CreatePending()!; h.PendingResult = pending;
                    var request = pending.Request();
                    var result = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = NotesOriginalSchema.Hash(request),
                        ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
                    foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) result[name] = request[name]!.DeepClone();
                    h.Send(result); metadata = pending.PrepareCommit(h.Host.SourceResultCommit); next = JsonNode.Parse(metadata.Text)!.AsObject();
                }
                if (mode == "failed-primary-recover") h.Host.FailAfterPrimary = true;
                var response = await h.Host.SaveOriginalContactResultAsync(metadata?.Offer.Token ?? "", next);
                if (mode == "failed-primary-recover")
                {
                    TestAssert.That(!response["ok"]!.GetValue<bool>() && h.Host.Snapshot() is null && System.IO.File.Exists(h.File(".save-intent.json")), "Failed primary lost prepared recovery intent");
                    Hold(() => h.Store.RecoverPrimary(h.Host.Primary())); // Stale owned model must not be adopted.
                    h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
                    h.Store.RecoverPrimary(h.Host.Primary());
                    TestAssert.That(h.Host.Snapshot() is null && !System.IO.File.Exists(h.File(".save-intent.json")), "Primary permission recovery minted a saved witness");
                    Hold(() => h.Restore()); h.Host.NativeNotesChoices = h.Store;
                    response = await h.Host.SaveOriginalContactResultAsync("", JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject());
                }
                TestAssert.That(response["ok"]!.GetValue<bool>() && response["notesOriginalDauerhaft"]!.GetValue<bool>() &&
                    !response["notesOriginalFehler"]!.GetValue<bool>() && !System.IO.File.Exists(h.File(".save-intent.json")) &&
                    System.IO.File.ReadAllText(h.File(".key.dpapi")) == oldKey, "Actual writer did not advance known-book consent with the same key: " + mode);
                if (mode == "uid-change") { Hold(h.Choice.RequireCurrent); Hold(() => h.Restore()); continue; }
                if (pending is not null) TestAssert.That(pending.ConfirmedSave().RequireCurrent() == h.Host.Saved(), "Persistent source seal blocked actual metadata writer witness");
                h.Send(h.Export); h.Restore(h.NewStore()).RequireCurrent(); TestAssert.That(h.Choices == 1, "Real save chain requested source setup again"); continue;
            }
            var intent = h.Store.PrepareCurrentSave(next.ToJsonString())!;
            TestAssert.That(System.IO.File.Exists(h.File(".save-intent.json")), "Native intent was not durable before writer invalidation");
            h.Choice.RequireCurrent();
            if (mode == "prepared-before-write")
            {
                h.Store.RecoverSaved(h.Host.Snapshot()!);
                TestAssert.That(!System.IO.File.Exists(h.File(".save-intent.json")), "Prepared-only crash failed to return to known before"); continue;
            }
            if (mode == "foreign-intent-owner") { Hold(() => h.NewStore().ConfirmSave(intent, h.Host.Snapshot()!)); continue; }
            if (mode == "tampered-intent")
            {
                var frame = JsonNode.Parse(System.IO.File.ReadAllText(h.File(".save-intent.json")))!.AsObject(); frame["payload"]!["new"] = new string('f', 64);
                System.IO.File.WriteAllText(h.File(".save-intent.json"), frame.ToJsonString()); Hold(() => h.Store.HasDesiredConsent()); continue;
            }
            if (mode == "revoke") h.Store.Revoke();
            var actual = next.DeepClone().AsObject(); if (mode == "wrong-target") actual["unplanned-user-edit"] = true;
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", actual))["ok"]!.GetValue<bool>(), "Actual unhooked native writer failed");
            if (mode == "wrong-target") { Hold(() => h.Store.ConfirmSave(intent, h.Host.Snapshot()!)); Hold(() => h.Store.RecoverSaved(h.Host.Snapshot()!)); continue; }
            if (mode == "revoke") { Hold(() => h.Store.ConfirmSave(intent, h.Host.Snapshot()!)); TestAssert.That(!h.Store.HasDesiredConsent(), "Old intent rearmed revoked consent"); continue; }
            if (mode == "newer-decision")
            {
                var fresh = h.MakeChoice(); h.Store.Approve([fresh]); var current = System.IO.File.ReadAllText(h.File("approval.json"));
                Hold(() => h.Store.ConfirmSave(intent, h.Host.Snapshot()!)); fresh.RequireCurrent();
                TestAssert.That(System.IO.File.ReadAllText(h.File("approval.json")) == current, "Old save completion overwrote newer conscious setup"); continue;
            }
            var archive = System.IO.File.ReadAllText(h.File(".save-intent.json")); h.Store.ConfirmSave(intent, h.Host.Snapshot()!);
            if (mode == "no-rollback")
            {
                System.IO.File.WriteAllText(h.File(".save-intent.json"), archive);
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", h.Book.DeepClone().AsObject()))["ok"]!.GetValue<bool>(), "Actual synthetic rollback writer failed");
                Hold(() => h.Store.RecoverSaved(h.Host.Snapshot()!)); Hold(h.Choice.RequireCurrent);
            }
        }
        Console.WriteLine($"Notes actual known-book save chain: {modes.Length} synthetic native-writer/recovery scenarios passed (no primary-read saved witness).");
        foreach (var phase in new[] { "intent-written", "content-written", "content-readback", "before-intent-delete", "intent-deleted" })
        {
            using var h = new Fixture(Path.Combine(root, "fault-" + phase)); h.Store.Approve([h.Choice]); h.Host.NativeNotesChoices = h.Store;
            h.FailSaveStage = phase;
            var proposal = h.Book.DeepClone().AsObject(); proposal["known-user-edit"] = phase;
            var response = await h.Host.SaveOriginalContactResultAsync("", proposal);
            TestAssert.That(response["ok"]!.GetValue<bool>() && response["notesOriginalFehler"]!.GetValue<bool>(), "Consent interruption blocked ordinary actual user save");
            var saved = h.Host.Saved(); TestAssert.That(saved is not null, "Actual user writer lost real saved observation");
            h.FailSaveStage = null; h.Store.RecoverSaved(h.Host.Snapshot()!);
            TestAssert.That(h.Host.Saved() == saved && h.Store.RecognizesSaved() && !System.IO.File.Exists(h.File(".save-intent.json")),
                "Interrupted private save-chain recovery rewrote user data or invented a new saved observation");
            h.Send(h.Export); h.Restore(h.NewStore()).RequireCurrent();
        }
        Console.WriteLine("Notes private save-chain interruption: 5 signed-intent/content/readback/delete boundary scenarios passed.");
    }

    internal static void Requests(string root)
    {
        var modes = new[] { "fresh", "physical-crash", "archive-crash", "readback-crash", "stop", "stop-during-seal", "revoke",
            "key-change", "missing-identity", "unknown-existing-root", "tampered-archive", "different-uuid", "different-setup", "foreign-proof", "no-consent", "missing-store",
            "result-arrived", "cancelled-protocol", "changed-book", "tampered-physical" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var journalRoot = Path.Combine(h.Root, "independent-requests");
            byte keyByte = 42;
            var copies = new List<byte[]>();
            byte[] Key() { var key = Enumerable.Repeat(keyByte, 32).ToArray(); copies.Add(key); return key; }
            ContactSourcePrivateFiles Boundary() => new(journalRoot, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
            NotesOriginalRequestIntents? requests = null;
            requests = new(Boundary(), Key, phase =>
            {
                if (mode == "physical-crash" && phase == "physical-written" || mode == "archive-crash" && phase == "archive-written" || mode == "readback-crash" && phase == "after-readback")
                    throw new IOException("synthetic-request-crash");
                if (mode == "stop-during-seal" && phase == "after-readback") requests!.Stop();
            });
            var binding = Path.GetFullPath(h.Host.DataPath);
            if (mode == "missing-store")
            {
                TestAssert.That(requests.LoadPhysical(binding, "chosen-private-id") is null && !Directory.Exists(journalRoot), "Read-only request discovery created store"); continue;
            }
            if (mode != "no-consent") h.Store.Approve([h.Choice]);
            var pending = h.Choice.CreatePending()!;
            if (mode == "no-consent") { Hold(() => requests.Seal(pending)); TestAssert.That(!Directory.Exists(journalRoot), "Request without private consent reserved a slot"); continue; }
            h.Protocol = new(h.Choice.Pins.Peer, h.Choice.Pins.Own);
            var offer = h.Protocol.Probe(); offer["antwort"] = true; h.Send(offer);
            if (mode == "unknown-existing-root")
            {
                using (Boundary().Open(create: true)) { }
                Hold(() => requests.Seal(pending));
                TestAssert.That(!System.IO.File.Exists(Path.Combine(journalRoot, ".journal-key")), "Unknown root was silently initialized"); continue;
            }
            if (mode is "physical-crash" or "archive-crash" or "readback-crash" or "stop-during-seal")
            {
                Hold(() => requests.Seal(pending));
                var restarted = new NotesOriginalRequestIntents(Boundary(), Key);
                TestAssert.That(restarted.LoadPhysical(binding, "chosen-private-id") is not null, "Physical-first crash intention lost");
                Hold(() => restarted.Seal(pending));
                if (mode == "physical-crash") TestAssert.That(!Directory.EnumerateFiles(journalRoot, "r-*.json").Any(), "Physical-only crash unexpectedly had archive");
                continue;
            }
            var fresh = requests.Seal(pending);
            TestAssert.That(JsonNode.DeepEquals(fresh.RequireFor(pending, h.Protocol), pending.Request()), "Fresh owned intention did not correlate request");
            TestAssert.That(JsonNode.DeepEquals(requests.Seal(pending).RequireFor(pending, h.Protocol), pending.Request()), "Owned repeated seal changed request");
            var loaded = new NotesOriginalRequestIntents(Boundary(), Key).LoadPhysical(binding, "chosen-private-id")!;
            loaded["request"]!["request_id"] = Guid.NewGuid().ToString();
            TestAssert.That(!JsonNode.DeepEquals(loaded, requests.LoadPhysical(binding, "chosen-private-id")), "Loaded history mutation altered native state");
            var another = h.Choice.CreatePending()!;
            Hold(() => fresh.RequireFor(another, h.Protocol));
            Hold(() => new NotesOriginalRequestIntents.FreshRequest(new object()).RequireFor(pending, h.Protocol));
            Hold(() => new NotesOriginalRequestIntents(Boundary(), Key).Seal(pending)); // Loaded intention never restores nonce.
            if (mode == "fresh") continue;
            if (mode == "stop") requests.Stop();
            if (mode == "revoke") h.Store.Revoke();
            if (mode == "key-change") keyByte = 43;
            if (mode == "missing-identity") System.IO.File.Delete(Path.Combine(journalRoot, ".journal-key"));
            if (mode == "tampered-archive") System.IO.File.WriteAllText(Directory.GetFiles(journalRoot, "r-*.json").Single(), "{}");
            if (mode == "tampered-physical")
            {
                System.IO.File.WriteAllText(Directory.GetFiles(journalRoot, "p-*.json").Single(), "{}");
                Hold(() => requests.LoadPhysical(binding, "chosen-private-id"));
            }
            if (mode == "cancelled-protocol") h.Protocol.Cancel();
            if (mode == "changed-book")
            {
                h.Host.NativeNotesChoices = h.Store;
                var changed = h.Book.DeepClone().AsObject(); changed["unrelated-edit"] = "preserve";
                TestAssert.That(h.Host.SaveOriginalContactResultAsync("", changed).GetAwaiter().GetResult()["ok"]!.GetValue<bool>(), "Intervening native save failed");
            }
            if (mode == "result-arrived")
            {
                h.PendingResult = pending; var request = pending.Request();
                var result = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = NotesOriginalSchema.Hash(request),
                    ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
                foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) result[name] = request[name]!.DeepClone();
                h.Send(result);
            }
            if (mode == "different-uuid") { Hold(() => requests.Seal(another)); continue; }
            if (mode == "different-setup")
            {
                var export = h.Export.DeepClone().AsObject(); export["setup_id"] = Guid.NewGuid().ToString(); h.Send(export);
                var reconfigured = h.MakeChoice(); h.Store.Approve([reconfigured]);
                Hold(() => requests.Seal(reconfigured.CreatePending()!));
            }
            if (mode == "foreign-proof") { Hold(() => fresh.RequireFor(another, h.Protocol)); continue; }
            Hold(() => fresh.RequireFor(pending, h.Protocol));
            TestAssert.That(copies.All(key => key.All(value => value == 0)), "Request journal retained a key copy");
        }
        Console.WriteLine($"Notes physical-first request intentions: {modes.Length} synthetic cases passed (loaded history never restores send rights).");
    }

    internal static async Task UnconfirmedQueriesAsync(string root)
    {
        var modes = new[] { "restart", "physical-only", "revoke", "target-change", "unrelated-save", "no-offer", "stop", "missing", "wrong-pins", "tampered-physical" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode)); h.Store.Approve([h.Choice]);
            var journalRoot = Path.Combine(h.Root, "request-history");
            ContactSourcePrivateFiles Boundary() => new(journalRoot, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
            byte[] Key() => Enumerable.Repeat((byte)42, 32).ToArray();
            var store = new NotesOriginalRequestIntents(Boundary(), Key, stage =>
            { if (mode == "physical-only" && stage == "physical-written") throw new IOException("synthetic-physical-only-request"); });
            var pending = h.Choice.CreatePending()!; var expected = pending.Request();
            if (mode == "physical-only") Hold(() => store.Seal(pending));
            else if (mode != "missing") store.Seal(pending);
            if (mode == "revoke") h.Store.Revoke();
            if (mode is "target-change" or "unrelated-save")
            {
                h.Host.NativeNotesChoices = h.Store;
                var next = h.Book.DeepClone().AsObject(); next["new-independent-edit"] = "preserve";
                if (mode == "target-change") next["kontakte"]![0]!["vorname"] = "Changed chosen target";
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", next))["ok"]!.GetValue<bool>(), "Known intervening native save failed");
            }
            if (mode == "tampered-physical") System.IO.File.WriteAllText(Directory.GetFiles(journalRoot, "p-*.json").Single(), "{}");
            store.Stop(); h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
            var reloaded = new NotesOriginalRequestIntents(Boundary(), Key);
            var pins = h.Choice.Pins;
            h.Protocol = new(mode == "wrong-pins" ? new("other-native-peer", pins.Peer.PublicKey) : pins.Peer, pins.Own);
            if (mode != "no-offer" && mode != "wrong-pins") { var offer = h.Protocol.Probe(); offer["antwort"] = true; h.Send(offer); }
            var binding = Path.GetFullPath(h.Host.DataPath);
            if (mode is "revoke" or "target-change" or "no-offer" or "missing" or "wrong-pins" or "tampered-physical")
                Hold(() => reloaded.ReadOnlyQuery(binding, "chosen-private-id", h.NewStore(), h.Protocol));
            else
            {
                var query = reloaded.ReadOnlyQuery(binding, "chosen-private-id", h.NewStore(), h.Protocol);
                var body = query.Request(h.Protocol);
                TestAssert.That(body.Count == 7 && body["ziel"] is null && body["desktop_sha256"] is null &&
                    body["request_id"]!.GetValue<string>() == expected["request_id"]!.GetValue<string>(), "Loaded unconfirmed query changed UUID or supplied write/ACK data");
                if (mode == "stop") { reloaded.Stop(); Hold(() => query.Request(h.Protocol)); }
            }
            TestAssert.That(h.Host.Snapshot() is null, "Unconfirmed query fabricated saved snapshot");
            Hold(() => reloaded.Seal(pending));
            TestAssert.Throws<InvalidOperationException>(() => new NotesOriginalRequestIntents.UnconfirmedQuery(new object()).Request(h.Protocol), "Fake unconfirmed query accepted");
            if (mode == "missing") TestAssert.That(!Directory.Exists(journalRoot), "Query without record created history root");
        }
        Console.WriteLine($"Notes unconfirmed query-only restart: {modes.Length} synthetic cases passed (no replay, pending writer, saved witness or ACK).");
    }

    internal static async Task SavedAcksAsync(string root)
    {
        var modes = new[] { "success", "before-save", "failed-save", "missing-request", "tampered-history", "missing-history", "key-change", "request-tamper",
            "revoke", "later-real-save", "stop", "history-written-crash", "readback-crash", "stop-during-seal", "reloaded-request-store", "unknown-ack-root", "revoke-during-seal",
            "query-restart", "query-later-save", "query-revoked", "query-target-changed", "query-mapping-changed", "query-no-offer", "query-no-history", "query-stop",
            "query-prepared", "query-settled", "query-wrong-receipt", "query-wrong-desktop", "query-copy-origin", "query-expire-origin", "query-no-reconstructed-ack" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode)); h.Store.Approve([h.Choice]); h.Host.NativeNotesChoices = h.Store;
            var requestRoot = Path.Combine(h.Root, "requests"); var ackRoot = Path.Combine(h.Root, "acks");
            byte keyByte = 42;
            byte[] Key() => Enumerable.Repeat(keyByte, 32).ToArray();
            ContactSourcePrivateFiles Boundary(string path) => new(path, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
            var requests = new NotesOriginalRequestIntents(Boundary(requestRoot), Key);
            NotesOriginalSavedAckIntents? outcomes = null;
            outcomes = new(Boundary(ackRoot), Key, requests, phase =>
            {
                if (mode == "history-written-crash" && phase == "history-written" || mode == "readback-crash" && phase == "after-readback")
                    throw new IOException("synthetic-saved-history-interruption");
                if (mode == "stop-during-seal" && phase == "after-readback") outcomes!.Stop();
                if (mode == "revoke-during-seal" && phase == "after-readback") h.Store.Revoke();
            });
            var pending = h.Choice.CreatePending()!; h.PendingResult = pending;
            if (mode != "missing-request") requests.Seal(pending);
            var request = pending.Request(); var historyKey = NotesOriginalSchema.Hash(request);
            TestAssert.That(outcomes.LoadHeld(historyKey) is null && !Directory.Exists(ackRoot), "Missing saved history read created a store");
            var result = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = historyKey,
                ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
            foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) result[name] = request[name]!.DeepClone();
            h.Send(result);
            if (mode == "before-save")
            {
                Hold(() => outcomes.Seal(pending)); TestAssert.That(!Directory.Exists(ackRoot), "Transport/result created saved history without actual write"); continue;
            }
            var commit = pending.PrepareCommit(h.Host.SourceResultCommit);
            if (mode == "failed-save") h.Host.FailAfterPrimary = true;
            var saved = await h.Host.SaveOriginalContactResultAsync(commit.Offer.Token, JsonNode.Parse(commit.Text)!.AsObject());
            if (mode is "failed-save" or "missing-request")
            {
                TestAssert.That(saved["ok"]!.GetValue<bool>() == (mode == "missing-request"), "Actual synthetic writer returned unexpected status");
                Hold(() => outcomes.Seal(pending)); TestAssert.That(!Directory.Exists(ackRoot), "Missing request/genuine save minted ACK history"); continue;
            }
            if (mode == "reloaded-request-store")
            {
                var reloadedRequests = new NotesOriginalRequestIntents(Boundary(requestRoot), Key);
                var reloadedOutcomes = new NotesOriginalSavedAckIntents(Boundary(ackRoot), Key, reloadedRequests);
                Hold(() => reloadedOutcomes.Seal(pending));
                TestAssert.That(!Directory.Exists(ackRoot), "Loaded request history reconstructed saved-ACK authority"); continue;
            }
            if (mode == "unknown-ack-root")
            {
                using (Boundary(ackRoot).Open(create: true)) { }
                Hold(() => outcomes.Seal(pending));
                TestAssert.That(!System.IO.File.Exists(Path.Combine(ackRoot, ".journal-key")), "Unknown ACK root silently initialized"); continue;
            }
            if (mode is "history-written-crash" or "readback-crash" or "stop-during-seal" or "revoke-during-seal")
            {
                Hold(() => outcomes.Seal(pending));
                var reloaded = new NotesOriginalSavedAckIntents(Boundary(ackRoot), Key, requests);
                TestAssert.That(reloaded.LoadHeld(historyKey) is JsonObject, "Genuine saved history was lost after interruption");
                TestAssert.Throws<InvalidOperationException>(() => new NotesOriginalSavedAckIntents.SavedAck(new object()).Body(), "Loaded/counterfeit history became an ACK proof"); continue;
            }
            var ack = outcomes.Seal(pending); var body = ack.Body();
            TestAssert.That(body["art"]!.GetValue<string>() == "kontakt_original_saveack" && body["desktop_sha256"]!.GetValue<string>() == h.Host.Saved()!.Sha256 &&
                body["request_sha256"]!.GetValue<string>() == historyKey && JsonNode.DeepEquals(outcomes.Seal(pending).Body(), body), "Native saved ACK lost exact witness correlation/idempotence");
            var loaded = new NotesOriginalSavedAckIntents(Boundary(ackRoot), Key, requests).LoadHeld(historyKey)!;
            loaded["result"]!["receipt_id"] = Guid.NewGuid().ToString();
            TestAssert.That(!JsonNode.DeepEquals(loaded, outcomes.LoadHeld(historyKey)), "Loaded saved history alias changed private outcome");
            if (mode.StartsWith("query-", StringComparison.Ordinal))
            {
                if (mode is "query-later-save" or "query-target-changed" or "query-mapping-changed")
                {
                    var later = JsonNode.Parse(commit.Text)!.AsObject(); later["independent-user-edit"] = "preserve";
                    if (mode == "query-target-changed") later["kontakte"]![0]!["vorname"] = "New chosen target";
                    if (mode == "query-mapping-changed") later["kontakte"]![0]!["notesOriginalBasis"]!["receipt_id"] = Guid.NewGuid().ToString();
                    TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", later))["ok"]!.GetValue<bool>(), "Known later save failed");
                }
                if (mode == "query-revoked") h.Store.Revoke();
                if (mode == "query-no-history") System.IO.File.Delete(Directory.GetFiles(ackRoot, "a-*.json").Single());
                requests.Stop(); outcomes.Stop();
                h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
                TestAssert.That(h.Host.Snapshot() is null, "Restart read invented saved snapshot");
                var reloadedRequests = new NotesOriginalRequestIntents(Boundary(requestRoot), Key);
                var reloadedOutcomes = new NotesOriginalSavedAckIntents(Boundary(ackRoot), Key, reloadedRequests);
                h.Protocol = new(h.Choice.Pins.Peer, h.Choice.Pins.Own);
                if (mode != "query-no-offer") { var offer = h.Protocol.Probe(); offer["antwort"] = true; h.Send(offer); }
                if (mode is "query-revoked" or "query-target-changed" or "query-mapping-changed" or "query-no-offer" or "query-no-history")
                    Hold(() => reloadedOutcomes.ReadOnlyQuery(historyKey, h.NewStore(), h.Protocol));
                else
                {
                    var query = reloadedOutcomes.ReadOnlyQuery(historyKey, h.NewStore(), h.Protocol);
                    var outgoing = query.Request(h.Protocol);
                    TestAssert.That(outgoing.Count == 7 && outgoing["ziel"] is null && outgoing["desktop_sha256"] is null &&
                        outgoing["request_sha256"]!.GetValue<string>() == historyKey, "Historical query supplied target or ACK authority");
                    if (mode == "query-stop") { reloadedOutcomes.Stop(); Hold(() => query.Request(h.Protocol)); }
                    else
                    {
                        var response = result.DeepClone().AsObject();
                        if (mode is "query-prepared" or "query-settled" or "query-wrong-desktop" or "query-no-reconstructed-ack")
                        {
                            response["art"] = "kontakt_original_abschlussstatus"; response["phase"] = mode == "query-settled" ? "settled" : "prepared";
                            response["desktop_sha256"] = mode == "query-wrong-desktop" ? new string('0', 64) : body["desktop_sha256"]!.DeepClone();
                        }
                        if (mode == "query-wrong-receipt") response["receipt_id"] = Guid.NewGuid().ToString();
                        h.CaptureRecovery = true; h.Send(response); var observation = h.RecoveryObservation;
                        if (mode == "query-no-reconstructed-ack") System.IO.File.Delete(Directory.GetFiles(ackRoot, "a-*.json").Single());
                        if (mode is "query-wrong-receipt" or "query-wrong-desktop" or "query-copy-origin" or "query-no-reconstructed-ack")
                            Hold(() => reloadedOutcomes.Reauthorize(query, observation.Body,
                                mode == "query-copy-origin" ? new(new object()) : observation.Origin, observation.Transport, h.Protocol));
                        else
                        {
                            var restored = reloadedOutcomes.Reauthorize(query, observation.Body, observation.Origin, observation.Transport, h.Protocol);
                            TestAssert.That(JsonNode.DeepEquals(restored.Body(), body) && restored.TerminalConfirmed() == (mode == "query-settled"),
                                "Fresh result did not reauthorize exact historical ACK/hash or falsely settled history");
                            TestAssert.That(reloadedRequests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id") is not null,
                                "Terminal observation released physical hold without exact installation");
                            if (mode == "query-expire-origin")
                            {
                                var native = observation.Origin.GetType().GetFields(BindingFlags.Instance | BindingFlags.NonPublic).Single().GetValue(observation.Origin)!;
                                native.GetType().GetProperty("Expires")!.SetValue(native, 0L);
                                Hold(() => restored.Body());
                            }
                            TestAssert.Throws<InvalidOperationException>(() => new NotesOriginalSavedAckIntents.RestoredAck(new object()).Body(), "Counterfeit restored ACK proof accepted");
                        }
                    }
                }
                TestAssert.That(h.Host.Snapshot() is null, "Query recovery called RecordSaved");
                Hold(() => ack.Body()); continue;
            }
            if (mode == "success") continue;
            if (mode == "tampered-history") System.IO.File.WriteAllText(Directory.GetFiles(ackRoot, "a-*.json").Single(), "{}");
            if (mode == "missing-history") System.IO.File.Delete(Directory.GetFiles(ackRoot, "a-*.json").Single());
            if (mode == "key-change") keyByte = 43;
            if (mode == "request-tamper") System.IO.File.WriteAllText(Directory.GetFiles(requestRoot, "r-*.json").Single(), "{}");
            if (mode == "revoke") h.Store.Revoke();
            if (mode == "stop") outcomes.Stop();
            if (mode == "later-real-save")
            {
                var later = JsonNode.Parse(commit.Text)!.AsObject(); later["new-user-edit"] = "preserve";
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", later))["ok"]!.GetValue<bool>(), "Later actual save failed");
            }
            Hold(() => ack.Body());
            if (mode is "revoke" or "later-real-save" or "stop")
                TestAssert.That(outcomes.LoadHeld(historyKey) is not null, "Live witness invalidation erased independent genuine history");
        }
        Console.WriteLine($"Notes independent genuine saved-ACK history: {modes.Length} actual-writer synthetic cases passed (loaded history is not ACK authority).");
    }

    private static async Task ScenarioAsync(string root, string mode)
    {
        using var h = new Fixture(root, mode == "native-default");
        if (mode == "missing")
        {
            h.NoCallbacks = true;
            TestAssert.That(!h.Store.HasDesiredConsent(), "Portable permission-looking book data granted source consent");
            h.Store.Revoke(); Hold(() => h.Restore());
            TestAssert.That(!Directory.Exists(h.ConsentRoot), "Missing-store reader/revoke created a root/key"); return;
        }
        if (mode == "native-default" && !OperatingSystem.IsWindows())
        {
            TestAssert.Throws<PlatformNotSupportedException>(() => h.Store.Approve([h.Choice]), "Production key protector fell back to a raw host key");
            TestAssert.That(!Directory.Exists(h.ConsentRoot), "Unsupported production protector created consent state"); return;
        }
        if (mode == "raw-protector")
        {
            h.Protector.Raw = true; Hold(() => h.Store.Approve([h.Choice]));
            TestAssert.That(!Directory.Exists(h.ConsentRoot), "Raw protector wrote a portable consent key"); Hold(h.Choice.RequireCurrent); return;
        }
        if (mode == "foreign-choice")
        {
            var foreign = new PersonalActorNativeSaveHost(Path.Combine(root, "foreign-book"), h.Book.ToJsonString());
            var originalCapture = foreign.Snapshot;
            // Same IDs/content, different real native book owner: never transfer its choice.
            var frame = h.Export.DeepClone().AsObject(); h.Send(frame);
            var foreignChoice = new NotesOriginalExportChoice(frame,
                (MagnolienbaumCoordinator.NativeNotesOrigin)typeof(Fixture).GetField("origin", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(h)!,
                (string)typeof(Fixture).GetField("transport", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(h)!,
                foreign.Snapshot()!, originalCapture, _ => "chosen-private-id", () => { });
            Hold(() => h.Store.Approve([foreignChoice]));
            TestAssert.That(!Directory.Exists(h.ConsentRoot), "Foreign native book choice was rebound to this store"); return;
        }
        if (mode == "changed-during-approval")
        {
            h.GuardHook = () =>
            {
                h.GuardHook = null;
                var changed = h.Book.DeepClone().AsObject(); changed["user-newer-field"] = "preserve";
                TestAssert.That(h.Host.SaveOriginalContactResultAsync("", changed).GetAwaiter().GetResult()["ok"]!.GetValue<bool>(), "Synthetic actual intervening save failed");
            };
            Hold(() => h.Store.Approve([h.Choice]));
            TestAssert.That(System.IO.File.ReadAllText(h.File(".transaction")) == "pending\n", "Stale approval remained active");
            Hold(h.Choice.RequireCurrent); return;
        }
        h.Store.Approve([h.Choice]);
        TestAssert.That(h.Store.HasDesiredConsent() && !System.IO.File.ReadAllText(h.File("approval.json")).Contains("chosen-private-id", StringComparison.Ordinal),
            "Private source choice was missing or stored unencrypted");
        var oldRecord = System.IO.File.ReadAllText(h.File("approval.json")); var oldKey = System.IO.File.ReadAllText(h.File(".key.dpapi"));
        if (mode == "newer-decision-cas")
        {
            var older = h.MakeChoice(); var newer = h.MakeChoice(); var secondStore = h.NewStore(); string? protectedDecision = null;
            h.GuardHook = () => { h.GuardHook = null; secondStore.Approve([newer]); protectedDecision = System.IO.File.ReadAllText(h.File("approval.json")); };
            Hold(() => h.Store.Approve([older]));
            TestAssert.That(protectedDecision is not null && System.IO.File.ReadAllText(h.File("approval.json")) == protectedDecision, "Stale approval overwrote newer explicit decision");
            newer.RequireCurrent(); Hold(older.RequireCurrent); return;
        }
        if (mode == "callbacks-outside-lock") h.CheckOutsideLock = true;
        if (mode == "fake-seal")
        {
            Hold(() => h.Choice.AttachConsent(new(new object())));
            var seal = (NotesOriginalChoiceStore.SourceSeal)typeof(NotesOriginalExportChoice).GetField("consent", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(h.Choice)!;
            var other = h.MakeChoice(); Hold(() => other.AttachConsent(seal)); h.Choice.RequireCurrent(); return;
        }
        if (mode is "revoke" or "old-record-replay")
        {
            h.NoCallbacks = true;
            h.Store.Revoke();
            TestAssert.That(!h.Store.HasDesiredConsent() && System.IO.File.ReadAllText(h.File(".key.dpapi")) != oldKey, "Revocation failed to rotate dedicated key");
            Hold(h.Choice.RequireCurrent);
            if (mode == "revoke") { Hold(() => h.Restore()); return; }
            System.IO.File.WriteAllText(h.File("approval.json"), oldRecord); Hold(() => h.Restore()); return;
        }
        if (mode == "lost-key") System.IO.File.Delete(h.File(".key.dpapi"));
        if (mode == "pending") System.IO.File.WriteAllText(h.File(".transaction"), "pending\n");
        if (mode == "corrupt")
        {
            var record = JsonNode.Parse(oldRecord)!.AsObject(); var bytes = Convert.FromBase64String(record["cipher"]!.GetValue<string>());
            bytes[0] ^= 1; record["cipher"] = Convert.ToBase64String(bytes); System.IO.File.WriteAllText(h.File("approval.json"), record.ToJsonString());
        }
        if (mode == "unavailable-key") h.Protector.Unavailable = true;
        if (mode is "lost-key" or "pending" or "corrupt" or "unavailable-key")
        {
            Hold(() => h.Store.HasDesiredConsent()); Hold(() => h.Restore()); Hold(h.Choice.RequireCurrent);
            TestAssert.That(mode != "lost-key" || !System.IO.File.Exists(h.File(".key.dpapi")), "Missing key was silently replaced"); return;
        }
        if (mode is "wrong-setup" or "wrong-share")
        {
            var changed = h.Export.DeepClone().AsObject(); changed[mode == "wrong-setup" ? "setup_id" : "share_id"] = mode == "wrong-setup" ? Guid.NewGuid().ToString() : "different-share";
            h.Send(changed); Hold(() => h.Restore()); TestAssert.That(h.Choices == 1, "Wrong source triggered a new/default choice"); return;
        }
        if (mode == "foreign-book")
        {
            var foreign = new PersonalActorNativeSaveHost(Path.Combine(root, "foreign-book"), h.Book.ToJsonString());
            var copied = new NotesOriginalChoiceStore(new(h.ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()), foreign.Snapshot,
                foreign.Primary, () => Path.GetFullPath(foreign.DataPath), h.Protector);
            Hold(() => h.Restore(copied)); return;
        }
        if (mode is "changed-book" or "same-content-save")
        {
            var changed = h.Book.DeepClone().AsObject(); if (mode == "changed-book") changed["new-user-edit"] = true;
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", changed))["ok"]!.GetValue<bool>(), "Actual ordinary native writer failed");
            if (mode == "changed-book")
            {
                Hold(() => h.Restore()); Hold(h.Choice.RequireCurrent);
                TestAssert.That(System.IO.File.ReadAllText(h.File("approval.json")) == oldRecord, "Unknown book was silently adopted"); return;
            }
        }
        if (mode == "reopen-no-witness")
        {
            h.Host = new(Path.Combine(root, "book"), "", reopen: true);
            TestAssert.That(h.Host.Snapshot() is null && h.Store.HasDesiredConsent(), "Primary read fabricated native saved witness");
            Hold(() => h.Restore()); TestAssert.That(h.Host.Snapshot() is null, "Consent read called RecordSaved"); return;
        }
        h.Send(h.Export);
        var restored = h.Restore(h.NewStore()); restored.RequireCurrent();
        TestAssert.That(h.Choices == 1 && restored.CreatePending() is not null && System.IO.File.ReadAllText(h.File("approval.json")) == oldRecord,
            "Stable private source restore prompted/rewrote state or failed exact native selection");
        if (mode == "native-default" && OperatingSystem.IsWindows())
        {
            var wrapped = Convert.FromBase64String(oldKey);
            TestAssert.Throws<CryptographicException>(() =>
            {
                if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
                ProtectedData.Unprotect(wrapped, Encoding.UTF8.GetBytes("Magnolie/native-original-contact-consent/key/v1"), DataProtectionScope.CurrentUser);
            },
                "Notes consent key reused DAV protector purpose");
        }
        TestAssert.That(h.Protector.Secrets.All(bytes => bytes.All(value => value == 0)), "Raw private consent key buffer was retained");
    }
}
