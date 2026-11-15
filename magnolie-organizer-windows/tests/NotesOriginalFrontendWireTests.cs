using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task FrontendWireAsync(string root)
    {
        if (OperatingSystem.IsWindows()) return; // Existing Node lane on host; no installed/interactive Windows UI claim.
        foreach (var mode in new[] { "normal", "restart", "late-edit" })
        {
            using var h = new Fixture(Path.Combine(root, mode)); h.Store.Approve([h.Choice]); h.Host.NativeNotesChoices = h.Store;
            h.Host.ConcurrentNativeWorker = true;
            var initialBook = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject();
            initialBook["notizen"] = new JsonArray(new JsonObject { ["id"] = "wire-synthetic-note", ["titel"] = "Keep", ["text"] = "Unrelated synthetic note" });
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", initialBook))["ok"]!.GetValue<bool>(), "Synthetic wire note setup failed");
            ContactSourcePrivateFiles Boundary(string path) => new(Path.Combine(h.Root, path), controlledUnix: true, layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
            byte[] Key() => Enumerable.Repeat((byte)42, 32).ToArray();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(55));
            using var loopStop = new CancellationTokenSource();
            var retired = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var requests = new NotesOriginalRequestIntents(Boundary("requests"), Key, phase =>
            { if (phase == "retired-physical-written") retired.TrySetResult(); });
            var outcomes = new NotesOriginalSavedAckIntents(Boundary("acks"), Key, requests);
            var readiness = new NotesOriginalUiReadiness(() => h.Host.CurrentNativeText);
            NotesOriginalController? controller = null;
            NotesOriginalUiSaveSession? ui = null;
            NotesOriginalWorker? worker = null;
            var repository = TestSource.Root("contracts/contact-provider-labels.md");
            var windows = File.Exists(Path.Combine(repository, "MagnolieOrganizer.Windows.csproj")) ? repository : Path.Combine(repository, "magnolie-organizer-windows");
            var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("NODE") ?? "node") {
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
            start.ArgumentList.Add(Path.Combine(windows, "tests", "notes-original-ui-save.js")); start.ArgumentList.Add("--wire");
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Existing Node runtime required");
            var errors = process.StandardError.ReadToEndAsync();
            using var input = new SemaphoreSlim(1, 1);
            async Task Send(object packet)
            {
                await input.WaitAsync(timeout.Token);
                try { await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(packet)); await process.StandardInput.FlushAsync(timeout.Token); }
                finally { input.Release(); }
            }
            Task Reply(string callback, object value) => Send(new { callback, value });
            NotesOriginalWorker CreateWorker(NotesOriginalController current, NotesOriginalUiSaveSession session) => new(current, session, readiness, h.Coordinator, async work =>
            {
                NotesOriginalUiSaveSession.Offer offer;
                await MutationGate.Global.WaitAsync(timeout.Token);
                try { offer = session.Publish(work); }
                finally { MutationGate.Global.Release(); }
                await Reply("notesOriginalSpeichern", new { token = offer.Token, kind = offer.Kind, beforeText = offer.BeforeText, text = offer.Text });
            }, async () =>
            {
                NotesOriginalUiReadiness.Probe probe;
                await MutationGate.Global.WaitAsync(timeout.Token);
                try { probe = readiness.Request(); }
                finally { MutationGate.Global.Release(); }
                await Reply("notesOriginalBereit", new { token = probe.Token, beforeText = probe.BeforeText });
            }, () => true);
            var sessions = new List<MagnolienbaumFsSession>();
            JsonObject? verified = null; string? requestHash = null; string? savedHash = null;
            var requestCount = 0; var ackCount = 0; var uiSaves = 0; Task? loop = null; var initialized = false;
            using var handler = new NotesHandler(async (message, cancellation) =>
            {
                var payload = JsonNode.Parse(await message.Content!.ReadAsStringAsync(cancellation))!.AsObject(); JsonObject response;
                if (message.RequestUri!.AbsolutePath == "/magnolie/v2/sitzung")
                { var built = MagnolienbaumFs1.BuildResponse(h.RemoteState, h.RemotePeer, payload); sessions.Add(built.Session); response = built.Response; }
                else
                {
                    if (message.RequestUri.AbsolutePath != "/magnolie/v2/nachricht") throw new CallbackViolation();
                    var session = sessions.Last(); var body = MagnolienbaumFs1.OpenEnvelope(session, "synthetic-notes", "synthetic-desktop", payload).Content.AsObject();
                    response = MagnolienbaumFs1.BuildAcknowledgement(session, payload);
                    switch (body["art"]!.GetValue<string>())
                    {
                        case "kontakt_original_aushandlung":
                            var offer = body.DeepClone().AsObject(); offer["antwort"] = true; h.Send(offer); h.Send(h.Export); break;
                        case "kontakt_original_anfrage":
                            requestCount++; requestHash = NotesOriginalSchema.Hash(body);
                            verified = new() { ["art"] = "kontakt_original_ergebnis", ["fassung"] = 1, ["request_sha256"] = requestHash,
                                ["receipt_id"] = "22222222-2222-4222-8222-222222222222", ["native_revision"] = 2L, ["next_basis"] = new string('d', 64) };
                            foreach (var name in new[] { "request_id", "share_id", "before_basis", "target_sha256" }) verified[name] = body[name]!.DeepClone();
                            h.Send(verified); break;
                        case "kontakt_original_statusanfrage":
                            if (verified is null) throw new CallbackViolation(); h.Send(verified); break;
                        case "kontakt_original_saveack":
                            ackCount++; savedHash = body["desktop_sha256"]!.GetValue<string>();
                            var settled = body.DeepClone().AsObject(); settled["art"] = "kontakt_original_abschlussstatus"; settled["phase"] = "settled";
                            h.Send(settled); break;
                        default: throw new CallbackViolation();
                    }
                }
                return new(System.Net.HttpStatusCode.OK) { Content = new StringContent(response.ToJsonString()) };
            });
            var client = typeof(MagnolienbaumCoordinator).GetField("client", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ((HttpClient)client.GetValue(h.Coordinator)!).Dispose(); client.SetValue(h.Coordinator, new HttpClient(handler));
            try
            {
                await Send(new { type = "init", mode, daten = JsonNode.Parse(h.Host.CurrentNativeText!) });
                Task<string?> line = process.StandardOutput.ReadLineAsync(timeout.Token).AsTask();
                string? frontendText = null;
                while (true)
                {
                    if (frontendText is not null && retired.Task.IsCompleted) break;
                    if (frontendText is not null) await Task.WhenAny(line, retired.Task).WaitAsync(timeout.Token);
                    if (!line.IsCompleted && retired.Task.IsCompleted) continue;
                    var raw = await line; if (raw is null) throw new InvalidOperationException("Frontend wire exited before terminal completion; synthetic counts " +
                        $"requests={requestCount} ack={ackCount} ui={uiSaves} controller={controller?.Counts}: " + await errors);
                    var packet = JsonNode.Parse(raw)!.AsObject();
                    line = process.StandardOutput.ReadLineAsync(timeout.Token).AsTask();
                    switch (packet["type"]!.GetValue<string>())
                    {
                        case "command":
                            var command = packet["value"]!.AsObject();
                            switch (command["cmd"]!.GetValue<string>())
                            {
                                case "speichern":
                                    if (command["notesOriginalLauf"] is not null) uiSaves++;
                                    var saved = await h.Host.SaveBridgeEnvelopeAsync(command); await Reply("gespeichert", saved); break;
                                case "notes_original_ready":
                                    using (BridgeDispatcherContract.Parse(command.ToJsonString())) { }
                                    await MutationGate.Global.WaitAsync(timeout.Token);
                                    bool ready;
                                    try { ready = readiness.Accept(command["token"]!.GetValue<string>(), command["bereit"]!.GetValue<bool>()); }
                                    finally { MutationGate.Global.Release(); }
                                    if (ready) worker?.Wake(); break;
                                case "notes_original_save_cancel": ui?.Cancel(command["token"]!.GetValue<string>()); break;
                            }
                            break;
                        case "initialized":
                            TestAssert.That(!initialized && h.Host.Snapshot() is not null, "Wire initialization invented native saved observation"); initialized = true;
                            if (mode == "restart")
                            {
                                await h.Coordinator.StopAsync(); h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
                                h.Host.NativeNotesChoices = h.Store;
                                h.Host.ConcurrentNativeWorker = true;
                                TestAssert.That(h.Host.Snapshot() is null, "Wire reopen fabricated a saved witness");
                            }
                            // Bind the controller to the actual current writer,
                            // not the discarded pre-reopen synthetic host.
                            controller = new(h.Store, requests, outcomes, h.Host.SourceResultCommit, () => readiness.IsReady);
                            ui = new(controller, () => h.Host.CurrentNativeText); h.Host.NativeNotesUi = ui;
                            worker = CreateWorker(controller, ui);
                            h.Host.NativeNotesWake = worker.Wake; h.Coordinator.NotesOriginalReceive = null; worker.Attach();
                            loop = (Task)typeof(MagnolienbaumCoordinator).GetMethod("MaintenanceLoopAsync", BindingFlags.Instance | BindingFlags.NonPublic)!
                                .Invoke(h.Coordinator, [loopStop.Token])!;
                            break;
                        case "frontend-complete": frontendText = packet["text"]!.GetValue<string>(); break;
                        default: throw new InvalidOperationException("Unexpected frontend packet");
                    }
                }
                TestAssert.That(initialized && requestCount == 1 && ackCount >= 1 && uiSaves == (mode == "restart" ? 2 : 1) &&
                    requestHash is not null && savedHash is not null && outcomes.LoadHeld(requestHash)!["saved_book"]![2]!.GetValue<string>() == savedHash &&
                    h.Host.CurrentNativeText == frontendText && new EncryptionService().Unlock(File.ReadAllText(h.Host.DataPath), PersonalActorNativeSaveHost.Password) == frontendText &&
                    requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id")!["state"]!.GetValue<string>() == "request_settled",
                    "Combined DOM/native lease/actual encrypted writer/inline ACK/terminal chain failed");
                TestAssert.That(JsonNode.Parse(frontendText!)!["notizen"]![0]!["text"]!.GetValue<string>() == "Unrelated synthetic note", "Combined wire rewrote unrelated synthetic note");
                if (mode == "late-edit") TestAssert.That(JsonNode.Parse(frontendText!)!["kontakte"]![0]!["notiz"]!.GetValue<string>() == "Later local edit after genuine metadata SaveACK",
                    "Combined wire lost later real saved user edit");
                await Send(new { type = "finish" });
                var finished = JsonNode.Parse(await line ?? throw new InvalidOperationException("No frontend completion"))!;
                TestAssert.That(finished["type"]!.GetValue<string>() == "finished", "Unexpected final wire packet");
                await process.WaitForExitAsync(timeout.Token); TestAssert.That(process.ExitCode == 0, "Frontend wire failed: " + await errors);
                Console.WriteLine("Notes actual DOM/native worker wire PASS " + mode);
            }
            finally
            {
                loopStop.Cancel(); if (loop is not null) await loop;
                if (worker is not null) await worker.StopAsync();
                if (!process.HasExited) { process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); }
                foreach (var session in sessions) session.Dispose();
            }
        }
    }
}
