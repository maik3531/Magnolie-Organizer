using System.Reflection;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task SetupPeerAsync(string root)
    {
        var modes = new[] { "complete", "addition", "peer-cancel", "wrong-id", "display-alias", "display-return-fake", "cosmetic-peer",
            "revoke-peer", "save-peer", "epoch-peer", "key-peer", "stop-peer", "disabled", "contact-off", "duplicate-peer",
            "wlan-off", "epoch-after", "revoke-after", "secret-after", "contact-cancel", "fake-candidate", "foreign-peer",
            "wait-cancel", "stop-contact", "mid-probe-revoke" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var stateField = typeof(MagnolienbaumCoordinator).GetField("state", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var treeGate = typeof(MagnolienbaumCoordinator).GetField("gate", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(h.Coordinator)!;
            void Edit(Action<JsonObject> action) { lock (treeGate) action((JsonObject)stateField.GetValue(h.Coordinator)!); }
            JsonObject Peer(JsonObject state) => state["partner"]!.AsArray().OfType<JsonObject>().Single();
            if (mode == "addition")
            {
                var book = h.Book.DeepClone().AsObject(); var second = book["kontakte"]![0]!.DeepClone().AsObject();
                second["id"] = "second-peer-id"; second["uid"] = "second-peer-uid"; book["kontakte"]!.AsArray().Add(second);
                TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Native peer fixture save failed");
                h.Store.Approve([h.Choice]);
            }
            h.Host.NativeNotesChoices = h.Store;
            if (mode == "disabled") Edit(state => state["an"] = false);
            if (mode == "contact-off") Edit(state => Peer(state)["kontaktSync"] = false);
            if (mode == "duplicate-peer") Edit(state => state["partner"]!.AsArray().Add(Peer(state).DeepClone()));
            if (mode == "foreign-peer")
            {
                var selected = h.Coordinator.CaptureNotesSetupPeers().Single();
                using var other = new Fixture(Path.Combine(root, "foreign-owner"));
                Hold(() => selected.RequireCurrent(other.Coordinator));
                Hold(() => new MagnolienbaumCoordinator.NativeNotesSetupPeer(new object()).Display());
                continue;
            }
            var dialogs = 0; var calls = 0; var contacts = 0;
            var before = File.ReadAllBytes(h.Host.DataPath);
            var receiver = h.Coordinator.NotesOriginalReceive;
            var incomingExport = h.Export.DeepClone().AsObject();
            if (mode == "addition")
            {
                incomingExport["share_id"] = "second-private-share";
                incomingExport["setup_id"] = "55555555-5555-4555-8555-555555555555";
            }
            var sessions = new List<MagnolienbaumFsSession>();
            NotesOriginalSetupAcquisition? acquisition = null;
            using var handler = new NotesHandler(async (message, cancellation) =>
            {
                calls++;
                var outside = await Task.Run(() =>
                {
                    var book = MutationGate.Global.Wait(0); if (book) MutationGate.Global.Release();
                    var tree = Monitor.TryEnter(treeGate); if (tree) Monitor.Exit(treeGate);
                    return book && tree;
                });
                TestAssert.That(outside, "Native setup HTTP callback ran under book/tree gate");
                var body = JsonNode.Parse(await message.Content!.ReadAsStringAsync(cancellation))!.AsObject(); JsonObject response;
                if (message.RequestUri!.AbsolutePath.EndsWith("/sitzung", StringComparison.Ordinal))
                {
                    var answer = MagnolienbaumFs1.BuildResponse(h.RemoteState, h.RemotePeer, body); sessions.Add(answer.Session); response = answer.Response;
                    if (mode == "mid-probe-revoke") h.Store.Revoke();
                }
                else
                {
                    var session = sessions.Last();
                    var clear = MagnolienbaumFs1.OpenEnvelope(session, "synthetic-notes", "synthetic-desktop", body).Content.AsObject();
                    TestAssert.That(clear["art"]!.GetValue<string>() == "kontakt_original_aushandlung", "Setup sent a provider mutation");
                    var offer = clear.DeepClone().AsObject(); offer["antwort"] = true;
                    h.NoCallbacks = true;
                    try { h.Send(offer); if (mode != "wait-cancel") h.Send(incomingExport); }
                    finally { h.NoCallbacks = false; }
                    response = MagnolienbaumFs1.BuildAcknowledgement(session, body);
                }
                return new(System.Net.HttpStatusCode.OK) { Content = new StringContent(response.ToJsonString()) };
            });
            var client = typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ((HttpClient)client.GetValue(h.Coordinator)!).Dispose(); client.SetValue(h.Coordinator, new HttpClient(handler));
            async Task<string?> Choose(IReadOnlyList<MagnolienbaumCoordinator.NotesSetupPeerView> peers, CancellationToken token)
            {
                dialogs++;
                var outside = await Task.Run(() => { var taken = MutationGate.Global.Wait(0); if (taken) MutationGate.Global.Release(); return taken; });
                TestAssert.That(outside, "Native peer dialog ran under book gate");
                if (mode is "display-alias" or "display-return-fake")
                    ((MagnolienbaumCoordinator.NotesSetupPeerView[])peers)[0] = new("display-only-id", "display-only-key", "not-native");
                if (mode == "cosmetic-peer") Edit(state => { Peer(state)["name"] = "New cosmetic label"; Peer(state)["protokoll"] = "negotiating-fs1"; });
                if (mode == "revoke-peer") h.Store.Revoke();
                if (mode == "save-peer")
                {
                    var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["during-peer"] = "preserve";
                    TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", edit))["ok"]!.GetValue<bool>(), "Actual native save during peer chooser failed");
                    before = File.ReadAllBytes(h.Host.DataPath);
                }
                if (mode == "epoch-peer") Edit(state => state["syncEpoch"] = "changed-native-epoch");
                if (mode == "key-peer") Edit(state => Peer(state)["oeffentlich"] = "changed-not-pinned-key");
                if (mode == "stop-peer") await h.Coordinator.StopAsync();
                return mode == "peer-cancel" ? null : mode == "wrong-id" ? "foreign-id" : mode == "display-return-fake" ? peers[0].Id : h.Choice.Pins.Peer.Id;
            }
            void Usable() { if (h.NoCallbacks) throw new CallbackViolation(); } // Must NEVER run in native receive.
            try
            {
                Task<NotesOriginalSetupAcquisition?> Begin() => NotesOriginalSetupAcquisition.BeginAsync(new(h.Store, h.Capture), h.Coordinator,
                    Choose, Usable, () => mode != "wlan-off");
                if (mode is "wrong-id" or "display-return-fake" or "revoke-peer" or "save-peer" or "epoch-peer" or "key-peer" or "stop-peer" or
                    "disabled" or "contact-off" or "duplicate-peer")
                {
                    await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await Begin(); }, "Changed peer/private context was silently recaptured");
                    if (mode is "disabled" or "contact-off" or "duplicate-peer") TestAssert.That(dialogs == 0, "Unavailable native peer catalog opened a chooser");
                    TestAssert.That(calls == 0, "Denied peer setup started network traffic");
                }
                else
                {
                    acquisition = await Begin();
                    if (mode == "peer-cancel") { TestAssert.That(acquisition is null && calls == 0, "Peer cancellation acquired transport authority"); continue; }
                    TestAssert.That(acquisition!.IsActive && h.Store.HasDesiredConsent() == (mode == "addition"), "Native acquisition granted a source");
                    if (mode is "epoch-after" or "revoke-after" or "secret-after")
                    {
                        if (mode == "epoch-after") Edit(state => state["syncEpoch"] = "changed-after-peer");
                        if (mode == "revoke-after") h.Store.Revoke();
                        if (mode == "secret-after") Edit(state => state["geheim"] = "changed-owned-synthetic-secret");
                        await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await acquisition.ProbeAsync(); }, "Stale native acquisition sent a probe");
                        TestAssert.That(calls == 0 && !acquisition.IsActive, "Stale setup retained its slot");
                    }
                    else if (mode == "wlan-off") TestAssert.That(!await acquisition.ProbeAsync() && calls == 0, "Offline setup bypassed native WLAN policy");
                    else if (mode == "mid-probe-revoke")
                    {
                        await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await acquisition.ProbeAsync(); }, "Revocation during handshake was hidden");
                        TestAssert.That(calls == 1 && !acquisition.IsActive, "Revoked handshake sent an export/mutation or retained the setup slot");
                    }
                    else
                    {
                        TestAssert.That(await acquisition.ProbeAsync() && calls == 2, "Actual FS1 setup probe/export acquisition failed");
                        if (mode == "wait-cancel")
                        {
                            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
                            await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await acquisition.WaitAsync(cancelled.Token); }, "Cancelled acquisition wait returned candidates");
                            TestAssert.That(!acquisition.IsActive && !h.Store.HasDesiredConsent(), "Cancelled wait kept native acquisition or granted a source");
                            continue;
                        }
                        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                        var candidate = (await acquisition.WaitAsync(deadline.Token)).Single();
                        if (mode == "fake-candidate")
                        {
                            await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await acquisition.ConfigureAsync(new(new object()), (_, _) => Task.FromResult<string?>(null)); }, "Forged native candidate was accepted");
                            await TestAssert.ThrowsAsync<ArgumentNullException>(async () => { await acquisition.ConfigureAsync(null!, (_, _) => Task.FromResult<string?>(null)); }, "Null candidate was accepted");
                            await TestAssert.ThrowsAsync<ArgumentNullException>(async () => { await acquisition.ConfigureAsync(candidate, null!); }, "Null chooser was accepted");
                        }
                        async Task<string?> Contact(NotesOriginalSetupFlow.View view, CancellationToken token)
                        {
                            contacts++;
                            var outside = await Task.Run(() => { var taken = MutationGate.Global.Wait(0); if (taken) MutationGate.Global.Release(); return taken; });
                            TestAssert.That(outside && view.Peer == h.Choice.Pins.Peer, "Contact chooser ran under gate or with display-only pins");
                            if (mode == "stop-contact") await h.Coordinator.StopAsync();
                            return mode == "contact-cancel" ? null : view.Contacts[mode == "addition" ? 1 : 0]["id"]!.GetValue<string>();
                        }
                        if (mode == "stop-contact")
                            await TestAssert.ThrowsAsync<InvalidOperationException>(async () => { await acquisition.ConfigureAsync(candidate, Contact); }, "Service stop during contact choice granted a source");
                        else TestAssert.That(await acquisition.ConfigureAsync(candidate, Contact) == (mode != "contact-cancel"), "Explicit contact setup result changed");
                        TestAssert.That(!acquisition.IsActive && contacts == 1, "Completed setup retained acquisition or skipped native choice");
                    }
                }
                TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Peer setup overwrote native user book");
                var granted = mode is "complete" or "addition" or "display-alias" or "cosmetic-peer" or "fake-candidate";
                TestAssert.That(h.Store.HasDesiredConsent() == granted, "Peer/acquisition context created or replaced permission without native choice");
            }
            finally
            {
                acquisition?.Stop();
                foreach (var session in sessions) session.Dispose();
                TestAssert.That(h.Coordinator.NotesOriginalReceive == receiver, "Setup acquisition displaced the existing native receiver");
            }
        }
        Console.WriteLine($"Notes native peer/acquisition: {modes.Length} actual FS1/pins/before-dialog/opt-out/cancel cases passed (no modal/startup).");
    }
}
