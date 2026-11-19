using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    private sealed class SetupProtector(ISecretProtector inner, Action beforeProtect) : ISecretProtector
    {
        public byte[] Protect(byte[] plain) { beforeProtect(); return inner.Protect(plain); }
        public byte[] Unprotect(byte[] cipher) => inner.Unprotect(cipher);
    }
    internal static async Task SetupFlowAsync(string root)
    {
        var modes = new[] { "initial", "addition", "cancel", "cancelled-before", "cancelled-dialog", "concurrent-revoke-initial", "concurrent-revoke-addition",
            "concurrent-replace-initial", "concurrent-replace-addition", "native-save", "stop", "fake-id", "display-alias", "one-use", "forged-decision",
            "revoked-before-dialog", "unknown-book", "pending", "revoke-during-publish" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var book = h.Book.DeepClone().AsObject(); var other = book["kontakte"]![0]!.DeepClone().AsObject();
            other["id"] = "second-id"; other["uid"] = "second-uid"; book["kontakte"]!.AsArray().Add(other);
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Native setup flow fixture save failed");
            var adding = mode is "addition" or "concurrent-revoke-addition" or "concurrent-replace-addition" or "unknown-book" or "pending";
            if (adding || mode == "revoked-before-dialog") h.Store.Approve([h.Choice]);
            if (mode == "revoked-before-dialog") h.Store.Revoke();
            h.Host.NativeNotesChoices = h.Store;
            var protocol = new NotesOriginalNegotiation(h.Choice.Pins.Peer, h.Choice.Pins.Own);
            var collector = new NotesOriginalSetupCollector(h.Coordinator, protocol); collector.Attach();
            try
            {
                var offer = protocol.Probe(); offer["antwort"] = true; h.Send(offer);
                var export = h.Export.DeepClone().AsObject(); export["share_id"] = "setup-explicit-share";
                export["setup_id"] = "33333333-3333-4333-8333-333333333333"; h.Send(export);
                var candidate = collector.Candidates().Single();
                if (mode == "forged-decision")
                { Hold(() => new NotesOriginalChoiceStore.SetupDecision(new object()).Commit(h.Choice)); continue; }
                if (mode == "pending") using (var directory = new ContactSourcePrivateFiles(h.ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()).Open()!) directory.Write(".transaction", "pending\n", 32);
                if (mode == "unknown-book")
                {
                    h.Host.NativeNotesChoices = null; var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["untracked"] = true;
                    await h.Host.SaveOriginalContactResultAsync("", edit); h.Host.NativeNotesChoices = h.Store;
                }
                var keyPath = Path.Combine(h.ConsentRoot, ".key.dpapi");
                var keyBefore = File.Exists(keyPath) ? File.ReadAllText(keyPath) : null;
                var before = File.ReadAllBytes(h.Host.DataPath);
                if (mode == "one-use")
                {
                    await MutationGate.Global.WaitAsync();
                    try
                    {
                        var decision = h.Store.BeginSetupDecision();
                        var choice = candidate.Choose(decision.Snapshot, h.Capture, _ => "second-id");
                        decision.Commit(choice); var key = File.ReadAllText(keyPath);
                        Hold(() => decision.Commit(choice));
                        TestAssert.That(File.ReadAllText(keyPath) == key, "One-use native setup decision replay rotated a key");
                    }
                    finally { MutationGate.Global.Release(); }
                    continue;
                }
                NotesOriginalChoiceStore? setupStore = null;
                setupStore = mode == "revoke-during-publish"
                    ? new NotesOriginalChoiceStore(new(h.ConsentRoot, controlledUnix: !OperatingSystem.IsWindows()), h.Capture, h.Primary,
                        () => Path.GetFullPath(h.Host.DataPath), new SetupProtector(h.Protector, () => setupStore!.Revoke()), () => h.Host.CurrentNativeText)
                    : h.Store;
                var flow = new NotesOriginalSetupFlow(setupStore, h.Capture);
                using var cancelled = new CancellationTokenSource();
                if (mode == "cancelled-before") cancelled.Cancel();
                var dialogs = 0;
                async Task<string?> Choose(NotesOriginalSetupFlow.View view, CancellationToken token)
                {
                    dialogs++;
                    var outside = await Task.Run(() => { var taken = MutationGate.Global.Wait(0); if (taken) MutationGate.Global.Release(); return taken; });
                    TestAssert.That(outside && view.Addition == adding && view.Peer == h.Choice.Pins.Peer,
                        "Native dialog was called under book gate or with invented source/setup mode");
                    _ = h.Store.HasDesiredConsent(); // No private-file session may span the dialog either.
                    if (mode.StartsWith("concurrent-revoke", StringComparison.Ordinal)) h.Store.Revoke();
                    if (mode.StartsWith("concurrent-replace", StringComparison.Ordinal)) h.Store.Approve([h.Choice]);
                    if (mode == "native-save")
                    {
                        var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["during-dialog"] = "preserve";
                        TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", edit))["ok"]!.GetValue<bool>(), "Actual native save during setup dialog failed");
                        before = File.ReadAllBytes(h.Host.DataPath);
                    }
                    if (mode == "stop") collector.Stop();
                    if (mode == "cancelled-dialog") cancelled.Cancel();
                    if (mode == "display-alias") { view.Contacts[1]["uid"] = "display-only-change"; view.Export["share_id"] = "display-only-share"; }
                    return mode == "cancel" ? null : mode == "fake-id" ? "foreign-local-id" : "second-id";
                }
                bool configured = false;
                if (mode is "initial" or "addition" or "cancel" or "display-alias" or "revoked-before-dialog")
                    configured = await flow.ConfigureAsync(candidate, Choose, cancelled.Token);
                else
                {
                    try { await flow.ConfigureAsync(candidate, Choose, cancelled.Token); throw new Exception("Stale/fake/cancelled native setup published a source: " + mode); }
                    catch (Exception error) when (error is InvalidOperationException or InvalidDataException or OperationCanceledException) { }
                }
                TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Setup publication overwrote native user book");
                if (configured)
                {
                    var selected = h.Store.DiscoverySources()!.Value.Sources;
                    TestAssert.That(selected.Count == (adding ? 2 : 1) && selected.Any(value => value["local_id"]!.GetValue<string>() == "second-id" &&
                        value["local_uid"]!.GetValue<string>() == "second-uid" && value["share_id"]!.GetValue<string>() == "setup-explicit-share"),
                        "Native setup flow persisted display data or replaced existing addition sources");
                    if (adding) TestAssert.That(File.ReadAllText(keyPath) == keyBefore, "Native addition dialog rotated old consent key");
                }
                if (mode is "cancelled-before" or "unknown-book" or "pending") TestAssert.That(dialogs == 0, "Unavailable setup context displayed a permission dialog");
                if (mode is "concurrent-revoke-initial" or "concurrent-revoke-addition" or "revoke-during-publish")
                    TestAssert.That(!h.Store.HasDesiredConsent(), "Late native dialog completion resurrected a concurrent revocation");
                if (mode is "cancel" or "cancelled-before" or "cancelled-dialog" or "stop" or "fake-id" or "native-save")
                    TestAssert.That(!File.Exists(keyPath), "Cancelled/stale/fake initial selection created a consent key");
            }
            finally { collector.Stop(); }
        }
        Console.WriteLine($"Notes native setup decision flow: {modes.Length} synthetic dialog-boundary/CAS/initial-addition cases passed (no actual modal/startup).");
    }

    internal static async Task SetupBeforePeerAsync(string root)
    {
        var modes = new[] { "initial", "addition", "empty-revoke", "revoke", "other-store-revoke", "replace", "native-save",
            "foreign-decision", "forged-decision", "cancel-before-contact", "cancel-contact", "chooser-error", "replay" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var adding = mode is "addition" or "revoke" or "other-store-revoke" or "replace";
            if (adding)
            {
                var book = h.Book.DeepClone().AsObject(); var other = book["kontakte"]![0]!.DeepClone().AsObject();
                other["id"] = "second-peer-id"; other["uid"] = "second-peer-uid"; book["kontakte"]!.AsArray().Add(other);
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Native peer fixture save failed");
                h.Store.Approve([h.Choice]);
            }
            h.Host.NativeNotesChoices = h.Store;
            var flow = new NotesOriginalSetupFlow(h.Store, h.Capture);
            var decision = await flow.BeginAsync(); // Before any peer chooser/export acquisition.
            TestAssert.That(decision.IsAddition == adding, "Before-peer decision invented setup mode");
            if (mode == "foreign-decision") decision = await new NotesOriginalSetupFlow(h.NewStore(), h.Capture).BeginAsync();
            if (mode == "forged-decision") decision = new(new object());
            if (mode is "empty-revoke" or "revoke") h.Store.Revoke();
            if (mode == "other-store-revoke") h.NewStore().Revoke();
            if (mode == "replace") h.Store.Approve([h.Choice]);
            if (mode == "cancel-before-contact") decision.Cancel();
            if (mode == "native-save")
            {
                var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["between-dialogs"] = "preserve";
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", edit))["ok"]!.GetValue<bool>(), "Actual intervening native save failed");
            }
            var protocol = new NotesOriginalNegotiation(h.Choice.Pins.Peer, h.Choice.Pins.Own);
            var collector = new NotesOriginalSetupCollector(h.Coordinator, protocol); collector.Attach();
            try
            {
                var offer = protocol.Probe(); offer["antwort"] = true; h.NoCallbacks = true; h.Send(offer);
                var export = h.Export.DeepClone().AsObject(); export["share_id"] = "before-peer-source";
                export["setup_id"] = "55555555-5555-4555-8555-555555555555"; h.Send(export); h.NoCallbacks = false;
                var candidate = collector.Candidates().Single(); var dialogs = 0;
                var before = File.ReadAllBytes(h.Host.DataPath);
                async Task<string?> Choose(NotesOriginalSetupFlow.View view, CancellationToken token)
                {
                    dialogs++;
                    var outside = await Task.Run(() => { var taken = MutationGate.Global.Wait(0); if (taken) MutationGate.Global.Release(); return taken; });
                    TestAssert.That(outside && view.Addition == adding, "Before-peer chooser ran under book gate or with a replacement mode");
                    _ = h.Store.HasDesiredConsent();
                    if (mode == "chooser-error") throw new IOException("synthetic native dialog failure");
                    return mode == "cancel-contact" ? null : view.Contacts[adding ? 1 : 0]["id"]!.GetValue<string>();
                }
                Task<bool> Configure() => flow.ConfigureAsync(candidate, Choose, beforePeerDecision: decision);
                if (mode is "initial" or "addition" or "replay")
                {
                    TestAssert.That(await Configure(), "Original before-peer decision did not publish the explicit source");
                    TestAssert.That(h.Store.DiscoverySources()!.Value.Sources.Any(value => value["share_id"]!.GetValue<string>() == "before-peer-source"),
                        "Before-peer native source was not persisted");
                    if (mode == "replay") await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await Configure(); }, "Used before-peer decision replayed");
                    TestAssert.That(dialogs == 1, "Used native peer decision displayed another dialog");
                }
                else if (mode is "cancel-contact" or "chooser-error")
                {
                    if (mode == "cancel-contact") TestAssert.That(!await Configure(), "Cancelled contact dialog granted a source");
                    else await TestAssert.ThrowsAsync<IOException>(async () => { await Configure(); }, "Synthetic dialog exception was hidden");
                    Hold(() => decision.RequireCurrent(h.Store));
                    await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await Configure(); }, "Cancelled before-peer proof was reused");
                    TestAssert.That(dialogs == 1 && !h.Store.HasDesiredConsent(), "Cancelled or failed chooser recreated permission");
                }
                else
                {
                    await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await Configure(); }, "Fresh contact decision bypassed stale before-peer context");
                    TestAssert.That(dialogs == 0, "Stale/foreign before-peer decision opened a contact dialog");
                }
                TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Peer setup overwrote native user book");
                if (mode is "revoke" or "other-store-revoke" or "empty-revoke") TestAssert.That(!h.Store.HasDesiredConsent(), "Peer acquisition resurrected revocation");
                if (!adding && mode is not ("initial" or "replay")) TestAssert.That(!File.Exists(h.File(".key.dpapi")), "Read/cancel/stale peer decision created a key");
            }
            finally { collector.Stop(); }
        }
        Console.WriteLine($"Notes before-peer native decision: {modes.Length} acquisition/owner/CAS/cancel cases passed (no modal/peer UI registration).");
    }
}
