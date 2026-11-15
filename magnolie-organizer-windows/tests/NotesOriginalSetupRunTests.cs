using System.Collections.Concurrent;
using System.Reflection;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    [ThreadStatic] private static bool setupRunUi;

    internal static async Task SetupRunAsync(string root)
    {
        var modes = new[] { "complete", "alias", "source-cancel", "contact-cancel", "bad-index", "source-error",
            "contact-error", "replay", "cancel-queued", "revoke-queued", "save-queued", "cancel-contact",
            "cancel-before", "offline", "reject", "post-error", "wrong-ui", "foreground", "notice-error", "dispose",
            "cancel-wait", "cancel-contact-post", "stop-contact" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var sessions = new List<MagnolienbaumFsSession>();
            var queue = new ConcurrentQueue<Func<Task>>();
            var active = new List<Task>(); var notices = new List<string>();
            var calls = 0; var sources = 0; var contacts = 0;
            var arrived = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var before = File.ReadAllBytes(h.Host.DataPath);
            var receiver = h.Coordinator.NotesOriginalReceive;
            using var handler = new NotesHandler(async (message, cancellation) =>
            {
                TestAssert.That(!setupRunUi, "Setup network ran on UI thread");
                calls++;
                var body = JsonNode.Parse(await message.Content!.ReadAsStringAsync(cancellation))!.AsObject(); JsonObject response;
                if (message.RequestUri!.AbsolutePath.EndsWith("/sitzung", StringComparison.Ordinal))
                { var answer = MagnolienbaumFs1.BuildResponse(h.RemoteState, h.RemotePeer, body); sessions.Add(answer.Session); response = answer.Response; }
                else
                {
                    var session = sessions.Last();
                    var clear = MagnolienbaumFs1.OpenEnvelope(session, "synthetic-notes", "synthetic-desktop", body).Content.AsObject();
                    TestAssert.That(clear["art"]!.GetValue<string>() == "kontakt_original_aushandlung", "Dispatcher sent a mutation");
                    var offer = clear.DeepClone().AsObject(); offer["antwort"] = true;
                    h.NoCallbacks = true;
                    try { h.Send(offer); if (mode != "cancel-wait") h.Send(h.Export); } finally { h.NoCallbacks = false; }
                    arrived.TrySetResult();
                    response = MagnolienbaumFs1.BuildAcknowledgement(session, body);
                }
                return new(System.Net.HttpStatusCode.OK) { Content = new StringContent(response.ToJsonString()) };
            });
            var client = typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ((HttpClient)client.GetValue(h.Coordinator)!).Dispose(); client.SetValue(h.Coordinator, new HttpClient(handler));
            var acquisition = await NotesOriginalSetupAcquisition.BeginAsync(new(h.Store, h.Capture), h.Coordinator,
                (_, _) => Task.FromResult<string?>(h.Choice.Pins.Peer.Id),
                () => { if (h.NoCallbacks) throw new CallbackViolation(); }, () => mode != "offline");
            NotesOriginalSetupRun? run = null;
            bool Post(Func<Task> callback)
            {
                if (mode == "reject") return false;
                if (mode == "post-error") throw new InvalidOperationException("synthetic dispatcher failure");
                queue.Enqueue(callback); return true;
            }
            run = new(acquisition!, Post, () => setupRunUi,
                async (views, token) =>
                {
                    TestAssert.That(setupRunUi, "Source dialog outside native UI dispatch"); sources++;
                    TestAssert.That(MutationGate.Global.Wait(0), "Source dialog under book gate"); MutationGate.Global.Release();
                    if (mode == "alias") views[0].Export["share_id"] = "display-only";
                    await Task.Yield(); // Force continuation off the synthetic UI frame; contact must be reposted.
                    token.ThrowIfCancellationRequested();
                    if (mode == "source-error") throw new InvalidOperationException("synthetic source error");
                    return mode == "source-cancel" ? null : mode == "bad-index" ? views.Count : 0;
                },
                async (view, token) =>
                {
                    TestAssert.That(setupRunUi, "Contact dialog outside native UI dispatch"); contacts++;
                    TestAssert.That(MutationGate.Global.Wait(0), "Contact dialog under book gate"); MutationGate.Global.Release();
                    if (mode == "cancel-contact") run!.Cancel();
                    if (mode == "stop-contact") await h.Coordinator.StopAsync();
                    if (mode == "contact-error") throw new InvalidOperationException("synthetic contact error");
                    token.ThrowIfCancellationRequested();
                    await Task.Delay(2, token); // Replay must not remove ownership of an active UI request.
                    return mode == "contact-cancel" ? null : view.Contacts[0]["id"]!.GetValue<string>();
                }, result =>
                {
                    TestAssert.That(setupRunUi, "Status outside native UI dispatch"); notices.Add(result);
                    if (mode == "notice-error") throw new InvalidOperationException("synthetic status error");
                });
            try
            {
                TestAssert.That(run.Phase == "created" && calls == 0 && !h.Store.HasDesiredConsent(), "Constructor started work/granted consent");
                if (mode == "cancel-before") run.Cancel();
                if (mode == "foreground")
                { setupRunUi = true; try { await run.RunAsync(); } finally { setupRunUi = false; } }
                else
                {
                    var worker = Task.Run(run.RunAsync);
                    if (mode == "cancel-wait") { await arrived.Task.WaitAsync(TimeSpan.FromSeconds(5)); run.Cancel(); }
                    await worker.WaitAsync(TimeSpan.FromSeconds(10));
                }
                if (mode == "cancel-queued") run.Cancel();
                if (mode == "dispose") run.Dispose();
                if (mode == "revoke-queued") h.Store.Revoke();
                if (mode == "save-queued")
                {
                    var edit = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject(); edit["during-dispatch"] = "preserve";
                    TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", edit))["ok"]!.GetValue<bool>(), "Native queued save failed");
                    before = File.ReadAllBytes(h.Host.DataPath);
                }
                var deadline = DateTime.UtcNow.AddSeconds(10);
                // Pump nested UI posts while outer callbacks are awaiting them.
                while (!run.Done.IsCompleted || !queue.IsEmpty || active.Any(task => !task.IsCompleted))
                {
                    TestAssert.That(DateTime.UtcNow < deadline, "Nested UI dispatch did not terminate");
                    while (queue.TryDequeue(out var callback))
                    {
                        if (mode == "cancel-contact-post" && sources > 0 && contacts == 0) run.Cancel();
                        setupRunUi = mode != "wrong-ui";
                        try { active.Add(callback()); if (mode == "replay") active.Add(callback()); }
                        finally { setupRunUi = false; }
                    }
                    await Task.Delay(1);
                }
                await Task.WhenAll(active);
                var granted = mode is "complete" or "alias" or "replay" or "notice-error";
                var expected = granted ? "configured" : mode is "cancel-before" or "cancel-queued" or "cancel-contact" or "source-cancel" or "contact-cancel" or "dispose" or "cancel-wait" or "cancel-contact-post" ? "cancelled" : mode == "offline" ? "waiting-network" : "held";
                TestAssert.That(run.Phase == expected && h.Store.HasDesiredConsent() == granted, $"Dispatcher result/consent mismatch: {mode}/{run.Phase}");
                TestAssert.That(!run.RetainsPendingData && !acquisition!.IsActive, "Terminal dispatcher retained native snapshots");
                TestAssert.That(File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Dispatcher overwrote native book");
                TestAssert.That(h.Coordinator.NotesOriginalReceive == receiver, "Dispatcher replaced independent receiver");
                TestAssert.That(sources <= 1 && contacts <= 1, "Replayed UI callback prompted twice");
                TestAssert.That(notices.Count == (mode is "reject" or "post-error" or "wrong-ui" ? 0 : 1), "Status replay/loss");
                await run.RunAsync();
            }
            finally
            {
                run.Dispose(); acquisition!.Stop();
                foreach (var session in sessions) session.Dispose();
            }
        }
        Console.WriteLine($"Notes native setup dispatcher: {modes.Length} real FS1/worker/nested UI/cancel/replay cases passed (no modal/startup).");
    }
}
