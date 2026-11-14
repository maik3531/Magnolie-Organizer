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
                    if (body["art"]!.GetValue<string>() == "kontakt_original_ergebnis" && PendingResult is not null)
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
