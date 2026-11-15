using System.Collections.Concurrent;
using System.Reflection;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task SetupHostAsync(string root)
    {
        var modes = new[] { "complete", "source-cancel", "contact-cancel", "offline", "reject-ui", "reject-worker",
            "worker-error", "prepare-cancel", "prepare-error", "cancel-prepare", "cancel-wait", "cancel-active-contact",
            "replay", "notice-error", "pre-cancelled", "busy-start" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            var sessions = new List<MagnolienbaumFsSession>();
            var queue = new ConcurrentQueue<Func<Task>>(); var active = new List<Task>(); var notices = new List<string>();
            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var arrived = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var preparations = 0; var calls = 0; var sources = 0; var contacts = 0;
            var before = File.ReadAllBytes(h.Host.DataPath); var receiver = h.Coordinator.NotesOriginalReceive;
            NotesOriginalSetupAcquisition? acquisition = null;
            using var handler = new NotesHandler(async (message, cancellation) =>
            {
                TestAssert.That(!setupRunUi, "Host ran network on UI thread"); calls++;
                var body = JsonNode.Parse(await message.Content!.ReadAsStringAsync(cancellation))!.AsObject(); JsonObject response;
                if (message.RequestUri!.AbsolutePath.EndsWith("/sitzung", StringComparison.Ordinal))
                { var answer = MagnolienbaumFs1.BuildResponse(h.RemoteState, h.RemotePeer, body); sessions.Add(answer.Session); response = answer.Response; }
                else
                {
                    var session = sessions.Last();
                    var clear = MagnolienbaumFs1.OpenEnvelope(session, "synthetic-notes", "synthetic-desktop", body).Content.AsObject();
                    TestAssert.That(clear["art"]!.GetValue<string>() == "kontakt_original_aushandlung", "Host sent a provider mutation");
                    var offer = clear.DeepClone().AsObject(); offer["antwort"] = true;
                    h.NoCallbacks = true;
                    try { h.Send(offer); if (mode != "cancel-wait") h.Send(h.Export); } finally { h.NoCallbacks = false; }
                    arrived.TrySetResult(); response = MagnolienbaumFs1.BuildAcknowledgement(session, body);
                }
                return new(System.Net.HttpStatusCode.OK) { Content = new StringContent(response.ToJsonString()) };
            });
            var client = typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ((HttpClient)client.GetValue(h.Coordinator)!).Dispose(); client.SetValue(h.Coordinator, new HttpClient(handler));
            var host = new NotesOriginalSetupHost(async token =>
            {
                preparations++;
                if (mode == "prepare-cancel") return null;
                if (mode == "prepare-error") throw new InvalidOperationException("synthetic preparation error");
                if (mode == "cancel-prepare") await release.Task; // Intentionally late native completion must be stopped, not adopted.
                acquisition = await NotesOriginalSetupAcquisition.BeginAsync(new(h.Store, h.Capture), h.Coordinator,
                    (_, _) => Task.FromResult<string?>(h.Choice.Pins.Peer.Id),
                    () => { if (h.NoCallbacks) throw new CallbackViolation(); }, () => mode != "offline",
                    mode == "cancel-prepare" ? default : token);
                return acquisition;
            }, work =>
            {
                if (mode == "reject-worker") return Task.CompletedTask;
                if (mode == "worker-error") throw new InvalidOperationException("synthetic scheduler error");
                return Task.Run(work);
            }, callback =>
            {
                if (mode == "reject-ui") return false;
                queue.Enqueue(callback); return true;
            }, () => setupRunUi,
            async (views, token) =>
            {
                TestAssert.That(setupRunUi, "Host source choice outside UI"); sources++;
                TestAssert.That(MutationGate.Global.Wait(0), "Host chooser under book gate"); MutationGate.Global.Release();
                await Task.Yield(); token.ThrowIfCancellationRequested();
                return mode == "source-cancel" ? null : 0;
            }, async (view, token) =>
            {
                TestAssert.That(setupRunUi, "Host contact choice outside UI"); contacts++;
                if (mode == "cancel-active-contact") await release.Task;
                token.ThrowIfCancellationRequested();
                return mode == "contact-cancel" ? null : view.Contacts[0]["id"]!.GetValue<string>();
            }, result =>
            {
                TestAssert.That(setupRunUi, "Host status outside UI"); notices.Add(result);
                if (mode == "notice-error") throw new InvalidOperationException("synthetic status error");
            });
            try
            {
                TestAssert.That(preparations == 0 && calls == 0, "Host constructor started application work");
                using var external = new CancellationTokenSource();
                if (mode == "pre-cancelled") external.Cancel();
                var running = host.StartAsync(external.Token);
                if (mode == "busy-start") Hold(() => host.StartAsync());
                if (mode == "cancel-prepare")
                {
                    var stopping = host.StopAsync();
                    TestAssert.That(!stopping.IsCompleted && !host.Completion.IsCompleted, "Host claimed pending preparation joined");
                    release.TrySetResult();
                }
                if (mode == "cancel-wait")
                { await arrived.Task.WaitAsync(TimeSpan.FromSeconds(5)); external.Cancel(); }
                var deadline = DateTime.UtcNow.AddSeconds(10);
                while (!running.IsCompleted || !queue.IsEmpty || active.Any(task => !task.IsCompleted))
                {
                    TestAssert.That(DateTime.UtcNow < deadline, "Application setup host failed to join");
                    while (queue.TryDequeue(out var callback))
                    {
                        setupRunUi = true;
                        try { active.Add(callback()); if (mode == "replay") active.Add(callback()); }
                        finally { setupRunUi = false; }
                    }
                    if (mode == "cancel-active-contact" && contacts > 0 && !release.Task.IsCompleted)
                    {
                        var stopping = host.StopAsync();
                        TestAssert.That(!stopping.IsCompleted && !host.Completion.IsCompleted, "Host claimed active asynchronous UI callback joined");
                        release.TrySetResult();
                    }
                    await Task.Delay(1);
                }
                await Task.WhenAll(active);
                var result = await running;
                var granted = mode is "complete" or "replay" or "notice-error" or "busy-start";
                var expected = granted ? "configured" : mode == "offline" ? "waiting-network" : mode is "worker-error" or "prepare-error" or "reject-ui" ? "held" : "cancelled";
                TestAssert.That(result == expected && h.Store.HasDesiredConsent() == granted, "Application host result/grant mismatch: " + mode + "/" + result);
                TestAssert.That(acquisition?.IsActive != true && File.ReadAllBytes(h.Host.DataPath).AsSpan().SequenceEqual(before), "Host retained acquisition or overwrote book");
                TestAssert.That(h.Coordinator.NotesOriginalReceive == receiver && sources <= 1 && contacts <= 1, "Host replay replaced independent receiver or repeated choice");
                TestAssert.That(notices.Count == (mode == "reject-ui" ? 0 : 1), "Host final status lost/replayed");
                TestAssert.That(preparations == (mode == "pre-cancelled" ? 0 : 1), "Host retried native preparation");
                await host.StopAsync(); await host.DisposeAsync(); await host.StopAsync();
                Hold(() => host.StartAsync());
            }
            finally
            {
                release.TrySetResult(); await host.DisposeAsync(); acquisition?.Stop();
                foreach (var session in sessions) session.Dispose();
            }
        }
        Console.WriteLine($"Notes application setup host: {modes.Length} actual FS1/owned scheduling/lifecycle/quiescence cases passed (no modal/startup).");
    }
}
