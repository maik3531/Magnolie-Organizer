using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task NativeSessionAsync(string root)
    {
        var modes = new[] { "no-choice", "key-missing", "wrong-profile", "unknown-primary", "foreign-receiver", "attach", "reopen", "detach", "foreign-after-attach", "key-loss-after-attach" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode)); using var protector = new Protector();
            if (mode != "no-choice") h.Store.Approve([h.Choice]);
            h.Host.NativeNotesChoices = h.Store;
            var paths = new WindowsPaths(mode == "wrong-profile" ? Path.Combine(h.Root, "other-profile") : Path.GetDirectoryName(h.Host.DataPath)!);
            if (mode != "key-missing")
            {
                var secret = Enumerable.Repeat((byte)42, 32).ToArray(); byte[]? encrypted = null;
                try
                {
                    encrypted = OperatingSystem.IsWindows()
                        ? ProtectedData.Protect(secret, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)
                        : protector.Protect(secret);
                    var seed = new ContactSourcePrivateFiles(paths.Telefon, controlledUnix: !OperatingSystem.IsWindows());
                    using (var directory = seed.Open(create: true)!) directory.Write(".key.dpapi", Convert.ToBase64String(encrypted), 4096);
                    File.Move(Path.Combine(paths.Telefon, ".key.dpapi"), paths.TelefonStorageKey);
                }
                finally { CryptographicOperations.ZeroMemory(secret); if (encrypted is not null) CryptographicOperations.ZeroMemory(encrypted); }
            }
            if (mode == "unknown-primary")
            {
                h.Host.NativeNotesChoices = null;
                var changed = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); changed["untracked-change"] = true;
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", changed))["ok"]!.GetValue<bool>(), "Unknown-primary fixture save failed");
                h.Host.NativeNotesChoices = h.Store;
            }
            if (mode == "reopen")
            {
                h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true); h.Host.NativeNotesChoices = h.Store;
                TestAssert.That(h.Host.Snapshot() is null, "Composition fixture reopen invented a saved scope");
            }
            var keyReads = 0; var asks = 0; var offers = 0;
            byte[] Unprotect(byte[] encrypted)
            {
                keyReads++;
                return OperatingSystem.IsWindows()
                    ? ProtectedData.Unprotect(encrypted, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)
                    : protector.Unprotect(encrypted);
            }
            NotesOriginalNativeSession? session = null;
            session = new(paths, h.Store, h.Host.SourceResultCommit, () => h.Host.CurrentNativeText, h.Coordinator, async work =>
            {
                NotesOriginalUiSaveSession.Offer offer;
                await MutationGate.Global.WaitAsync();
                try { offer = session!.Ui.Publish(work); }
                finally { MutationGate.Global.Release(); }
                offers++;
                var saved = await h.Host.SaveBridgeEnvelopeAsync(new JsonObject { ["cmd"] = "speichern", ["id"] = 900 + offers,
                    ["text"] = offer.Text, ["notesOriginalLauf"] = offer.Token });
                TestAssert.That(saved["ok"]!.GetValue<bool>(), "Composed actual native UI lease writer failed");
            }, () =>
            {
                asks++; var probe = session!.Readiness.Request(); session.Readiness.Accept(probe.Token, true); return Task.CompletedTask;
            }, () => false, controlledUnix: true, controlledUnprotect: Unprotect);
            h.Host.NativeNotesUi = session.Ui; h.Host.NativeNotesWake = session.Worker.Wake;
            var originalReceive = h.Coordinator.NotesOriginalReceive;
            if (mode is not ("no-choice" or "key-missing" or "wrong-profile" or "unknown-primary" or "foreign-receiver")) h.Coordinator.NotesOriginalReceive = null;
            if (mode == "no-choice") h.NoCallbacks = true;
            var admission = await session.TryAttachKnownAsync(); h.NoCallbacks = false;
            var expected = mode switch {
                "no-choice" => NotesOriginalNativeSession.Admission.NoChoice,
                "key-missing" => NotesOriginalNativeSession.Admission.KeyMissing,
                "wrong-profile" or "unknown-primary" or "foreign-receiver" => NotesOriginalNativeSession.Admission.Held,
                _ => NotesOriginalNativeSession.Admission.Attached };
            TestAssert.That(admission == expected && asks == 0 && offers == 0 && !File.Exists(paths.TelefonDatabase), "Native composition admitted ungranted/foreign state or started services");
            if (mode is "no-choice" or "key-missing" or "wrong-profile" or "unknown-primary")
            {
                if (mode != "key-missing") TestAssert.That(keyReads == 0, "Composition probed phone key before real native source/book admission");
                TestAssert.That(h.Coordinator.NotesOriginalReceive == originalReceive && !Directory.Exists(Path.Combine(paths.Root, "notes-original-requests")),
                    "Inactive composition replaced a receiver or created journal state");
                await session.StopAsync(); continue;
            }
            if (mode == "foreign-receiver")
            {
                await session.StopAsync(); TestAssert.That(h.Coordinator.NotesOriginalReceive == originalReceive, "Rejected composition detached foreign callback"); continue;
            }
            TestAssert.That(session.IsActive && await session.TryAttachKnownAsync() == NotesOriginalNativeSession.Admission.Attached, "Explicit native attachment was not stable/idempotent");
            if (mode is "detach" or "foreign-after-attach")
            {
                Func<JsonObject, JsonObject, MagnolienbaumCoordinator.NativeNotesOrigin, string, bool>? replacement = null;
                if (mode == "foreign-after-attach") h.Coordinator.NotesOriginalReceive = replacement = (_, _, _, _) => false;
                var state = (JsonObject)typeof(MagnolienbaumCoordinator).GetField("state", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(h.Coordinator)!;
                var before = state.ToJsonString();
                await session.StopAsync();
                TestAssert.That(!session.IsActive && h.Coordinator.NotesOriginalReceive == replacement && state.ToJsonString() == before && h.Store.HasDesiredConsent() &&
                    await session.TryAttachKnownAsync() == NotesOriginalNativeSession.Admission.Stopped, "Notes-only detach changed tree identity/private consent or removed foreign receiver");
                continue;
            }
            if (mode == "key-loss-after-attach") File.Delete(paths.TelefonStorageKey);
            await session.Worker.PulseAsync();
            var protocol = (NotesOriginalNegotiation)session.Controller.ProbeOne().Invocation!;
            var answer = protocol.Probe(); answer["antwort"] = true;
            h.NoCallbacks = true; h.Send(answer); h.NoCallbacks = false; await session.Worker.PulseAsync();
            h.NoCallbacks = true; h.Send(h.Export); h.NoCallbacks = false; await session.Worker.PulseAsync();
            if (mode == "key-loss-after-attach")
            {
                TestAssert.That(offers == 0 && !File.Exists(paths.TelefonStorageKey) && !Directory.Exists(Path.Combine(paths.Root, "notes-original-requests")),
                    "Key loss after composition recreated key or provider intent"); await session.StopAsync(); continue;
            }
            if (mode == "reopen") await session.Worker.PulseAsync(); // Use the real first bootstrap observation, never synthesize one.
            var reader = new NotesOriginalExistingJournalKey(paths, controlledUnix: true, controlledUnprotect: Unprotect);
            var files = new ContactSourcePrivateFiles(Path.Combine(paths.Root, "notes-original-requests"), controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
            var requests = new NotesOriginalRequestIntents(files, reader.ReadExisting);
            var request = requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id")!["request"]!.AsObject();
            var result = new JsonObject { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = NotesOriginalSchema.Hash(request),
                ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
            foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) result[name] = request[name]!.DeepClone();
            h.NoCallbacks = true; h.Send(result); h.NoCallbacks = false; await session.Worker.PulseAsync();
            var outcomes = new NotesOriginalSavedAckIntents(new ContactSourcePrivateFiles(Path.Combine(paths.Root, "notes-original-outcomes"),
                controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal), reader.ReadExisting, requests);
            TestAssert.That(offers == (mode == "reopen" ? 2 : 1) && outcomes.LoadHeld(NotesOriginalSchema.Hash(request)) is not null && h.Host.Saved()!.Sequence == 2,
                "Concrete existing-key/native-source composition did not produce actual bootstrap/metadata saves and independent ACK");
            await session.StopAsync();
            TestAssert.That(h.Coordinator.NotesOriginalReceive is null && requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id") is not null,
                "Concrete session Stop left receiver attached or retired physical hold");
        }
        Console.WriteLine($"Notes explicit native composition: {modes.Length} synthetic admission/existing-key/actual-writer/owned-detach cases passed (no startup call).");
    }
}
