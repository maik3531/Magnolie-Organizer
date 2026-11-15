using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task SetupCollectorAsync(string root)
    {
        var modes = new[] { "native-choice", "cancel", "expired", "missing-offer", "foreign-challenge", "invalid-offer", "conflict",
            "duplicate", "budget", "coexist-worker", "coordinator-stop", "occupied-slot", "choice-cancel", "changed-during-choice", "stop-during-choice",
            "export-before-offer", "wait-cancel", "forged-candidate" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            long now = 0;
            var protocol = new NotesOriginalNegotiation(h.Choice.Pins.Peer, h.Choice.Pins.Own);
            var collector = new NotesOriginalSetupCollector(h.Coordinator, protocol, () => now, budget: 2);
            var originalReceive = h.Coordinator.NotesOriginalReceive;
            collector.Attach();
            try
            {
                TestAssert.That(!await collector.ProbeAsync(() => false), "Offline setup probe invented transport/source authority");
                if (mode == "wait-cancel")
                {
                    using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
                    await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await collector.WaitAsync(cancelled.Token); }, "Cancelled setup acquisition returned candidates");
                    continue;
                }
                if (mode == "export-before-offer")
                {
                    using var waiting = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                    var pending = collector.WaitAsync(waiting.Token);
                    h.NoCallbacks = true; h.Send(h.Export); h.NoCallbacks = false;
                    TestAssert.That(!pending.IsCompleted, "Early export bypassed protocol negotiation");
                    var lateOffer = protocol.Probe(); lateOffer["antwort"] = true; h.Send(lateOffer);
                    TestAssert.That((await pending).Count == 1, "Out-of-order genuine export did not resume after negotiation");
                }
                if (mode == "coexist-worker")
                {
                    h.Store.Approve([h.Choice]); h.Host.NativeNotesChoices = h.Store;
                    ContactSourcePrivateFiles Boundary(string name) => new(Path.Combine(h.Root, name), controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
                    byte[] Key() => Enumerable.Repeat((byte)42, 32).ToArray();
                    var requests = new NotesOriginalRequestIntents(Boundary("requests"), Key);
                    h.Controller = new(h.Store, requests, new NotesOriginalSavedAckIntents(Boundary("outcomes"), Key, requests), h.Host.SourceResultCommit, () => true);
                    await h.Controller.ProcessOneAsync();
                    var workerProtocol = (NotesOriginalNegotiation)h.Controller.ProbeOne().Invocation!;
                    var workerOffer = workerProtocol.Probe(); workerOffer["antwort"] = true;
                    h.NoCallbacks = true; h.Send(workerOffer); h.NoCallbacks = false;
                    TestAssert.That((await h.Controller.ProcessOneAsync()).Kind == "negotiated", "Setup intercepted worker challenge");
                }
                if (mode != "missing-offer")
                {
                    var offer = protocol.Probe(); offer["antwort"] = mode != "invalid-offer";
                    if (mode == "foreign-challenge") offer["challenge"] = Guid.NewGuid().ToString();
                    h.NoCallbacks = true; h.Send(offer); h.NoCallbacks = false;
                }
                h.NoCallbacks = true; h.Send(h.Export); h.NoCallbacks = false;
                if (mode == "cancel") collector.Stop();
                if (mode == "expired") now = 120_000;
                if (mode == "coordinator-stop") await h.Coordinator.StopAsync();
                if (mode is "cancel" or "expired" or "coordinator-stop" or "missing-offer" or "foreign-challenge" or "invalid-offer")
                { Hold(() => collector.Candidates()); continue; }
                using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                var candidate = (await collector.WaitAsync(deadline.Token)).Single();
                if (mode == "occupied-slot")
                {
                    var other = new NotesOriginalSetupCollector(h.Coordinator, new(h.Choice.Pins.Peer, h.Choice.Pins.Own));
                    Hold(other.Attach); other.Stop();
                    TestAssert.That(collector.Candidates().Count == 1, "Foreign setup Stop detached the owner");
                }
                if (mode == "forged-candidate")
                { Hold(() => new NotesOriginalSetupCollector.Candidate(new object()).Display()); continue; }
                if (mode == "conflict")
                {
                    var changed = h.Export.DeepClone().AsObject(); changed["native_revision"] = 2L;
                    h.Send(changed);
                    TestAssert.That(collector.Candidates().Count == 0, "Conflicting same-source setup export was not isolated");
                    Hold(() => candidate.Display()); continue;
                }
                if (mode == "duplicate")
                {
                    for (var index = 0; index < 30; index++) h.Send(h.Export);
                    Hold(() => candidate.Display());
                    candidate = collector.Candidates().Single();
                }
                if (mode == "budget")
                {
                    for (var index = 0; index < 10; index++)
                    {
                        var next = h.Export.DeepClone().AsObject(); next["share_id"] = "bounded-share-" + index; h.Send(next);
                    }
                    TestAssert.That(collector.Candidates().Count == 2, "Setup receive grew beyond bounded exports");
                }
                if (mode == "coexist-worker")
                {
                    TestAssert.That((await h.Controller!.ProcessOneAsync()).Kind == "request" && h.Controller.Counts.Owners == 1,
                        "Setup collector displaced existing source owner/work");
                    collector.Stop();
                    TestAssert.That(h.Coordinator.NotesOriginalReceive == originalReceive && h.Controller.Counts.Owners == 1,
                        "Setup Stop revoked the worker or its owner");
                    h.Controller.Stop(); continue;
                }
                var displayed = candidate.Display(); displayed["setup_id"] = "not-a-permission";
                TestAssert.That(candidate.Display()["setup_id"]!.GetValue<string>() != "not-a-permission", "Display alias changed native setup candidate");
                var snapshot = h.Host.Snapshot()!;
                if (mode == "choice-cancel")
                { Hold(() => candidate.Choose(snapshot, h.Capture, _ => null)); continue; }
                if (mode == "changed-during-choice")
                {
                    Hold(() => candidate.Choose(snapshot, h.Capture, contacts =>
                    {
                        var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["later-native-edit"] = "preserve";
                        TestAssert.That(h.Host.SaveOriginalContactResultAsync("", edit).GetAwaiter().GetResult()["ok"]!.GetValue<bool>(), "Actual intervening native setup edit failed");
                        return contacts[0]["id"]!.GetValue<string>();
                    })); continue;
                }
                if (mode == "stop-during-choice")
                {
                    Hold(() => candidate.Choose(snapshot, h.Capture, contacts =>
                    {
                        collector.Stop(); return contacts[0]["id"]!.GetValue<string>();
                    })); continue;
                }
                var choices = 0;
                var choice = candidate.Choose(snapshot, h.Capture, contacts => { choices++; return contacts[0]["id"]!.GetValue<string>(); });
                TestAssert.That(choices == 1 && !h.Store.HasDesiredConsent() && !Directory.Exists(h.ConsentRoot),
                    "Transport/setup collection or native contact choice published consent");
                Hold(() => choice.RequestBinding()); // Native choice is still not durable source consent.
                collector.Stop(); Hold(choice.RequireCurrent);
            }
            finally
            {
                collector.Stop();
                TestAssert.That(h.Coordinator.NotesOriginalReceive == originalReceive, "Setup acquisition replaced regular receive binding");
                if (mode != "coexist-worker") TestAssert.That(!Directory.Exists(h.ConsentRoot), "Setup receive/cancel path created durable consent");
            }
        }
        using (var h = new Fixture(Path.Combine(root, "result-terminal-isolation")))
        {
            var staged = 0;
            Action stop = () => { };
            h.Coordinator.AttachNotesSetup((_, _, _) => { staged++; return true; }, stop);
            try
            {
                // The shared native receiver must not even present these lanes
                // to a setup observer, regardless of its implementation.
                h.Send(new JsonObject { ["art"] = "kontakt_original_ergebnis" });
                h.Send(new JsonObject { ["art"] = "kontakt_original_abschlussstatus" });
                TestAssert.That(staged == 0, "Setup observer intercepted result/terminal authority");
            }
            finally { h.Coordinator.DetachNotesSetup(stop); }
        }
        Console.WriteLine($"Notes native setup acquisition: {modes.Length} bounded real-FS1/choice/coexistence/cancel plus 1 result/terminal isolation case passed (no grant/dialog/startup).");
    }
}
