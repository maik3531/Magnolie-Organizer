using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static async Task SetupPreparationAsync(string root)
    {
        var modes = new[] { "saved", "loaded-no-witness", "wrong-token", "wrong-hash", "not-idle", "expired", "new-owner", "disposed", "cancel-wait" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode));
            if (mode == "loaded-no-witness") h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
            var now = 0L; var source = h.Host.Source();
            using var preparation = new NotesOriginalSetupPreparation(() => source, h.Host.Snapshot, () => now);
            var hash = BaumSyncSnapshot.Hash(h.Host.CurrentNativeText!);
            if (mode == "expired") now = 40_000;
            if (mode == "new-owner") source = new string('d', 64);
            if (mode is "disposed" or "cancel-wait")
            {
                if (mode == "cancel-wait")
                {
                    using var stop = new CancellationTokenSource(); stop.Cancel();
                    await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await preparation.WaitAsync(stop.Token); }, "Cancelled preparation wait completed");
                }
                preparation.Dispose();
                TestAssert.That(!preparation.Accept(preparation.Token, true, hash), "Disposed setup preparation accepted reply");
                await TestAssert.ThrowsAsync<OperationCanceledException>(async () => { await preparation.WaitAsync(default); }, "Disposed setup preparation wait completed");
                continue;
            }
            if (mode == "wrong-token") TestAssert.That(!preparation.Accept(new string('f', 64), true, hash), "Foreign preparation token consumed request");
            var accepted = preparation.Accept(preparation.Token, mode != "not-idle", mode == "wrong-hash" ? new string('c', 64) : hash);
            var expected = mode is "saved" or "wrong-token";
            TestAssert.That(accepted == expected && (await preparation.WaitAsync(default) is not null) == expected, "Renderer idle/hash supplied a native saved witness");
            TestAssert.That(!preparation.Accept(preparation.Token, true, hash), "Preparation reply replayed");
            TestAssert.That(!h.Store.HasDesiredConsent(), "Preparation granted original source");
        }
        Console.WriteLine($"Notes setup preparation native guard: {modes.Length} saved/load/token/expiry/owner/cancel cases passed.");
        using (BridgeDispatcherContract.Parse(new JsonObject { ["cmd"] = "notes_setup_prepared", ["token"] = "synthetic", ["bereit"] = false, ["standSha256"] = "" }.ToJsonString())) { }
        foreach (var invalid in new[] {
            new JsonObject { ["cmd"] = "notes_setup_prepared", ["token"] = "synthetic", ["bereit"] = "true", ["standSha256"] = "" },
            new JsonObject { ["cmd"] = "notes_setup_prepared", ["token"] = "synthetic", ["bereit"] = true, ["standSha256"] = "", ["permission"] = true } })
            Hold(() => { using var parsed = BridgeDispatcherContract.Parse(invalid.ToJsonString()); });
        if (OperatingSystem.IsWindows()) return; // Existing Node on host only, no native GUI claim.
        var repository = TestSource.Root("contracts/contact-provider-labels.md");
        var windows = File.Exists(Path.Combine(repository, "MagnolieOrganizer.Windows.csproj")) ? repository : Path.Combine(repository, "magnolie-organizer-windows");
        foreach (var mode in new[] { "fresh", "pending", "note-snapshot", "string-ack", "replay", "failed-writer", "locked", "editor", "modal" })
        {
            using var h = new Fixture(Path.Combine(root, "wire-" + mode));
            var book = JsonNode.Parse(h.Host.CurrentNativeText!)!.AsObject();
            book["notizen"] = new JsonArray(new JsonObject { ["id"] = "synthetic-setup-note", ["titel"] = "Note", ["text"] = "Keep", ["html"] = "Keep" });
            TestAssert.That((await h.Host.SaveOriginalContactResultAsync("", book))["ok"]!.GetValue<bool>(), "Preparation fixture save failed");
            h.Host = new(Path.Combine(h.Root, "book"), "", reopen: true);
            TestAssert.That(h.Host.Snapshot() is null, "Reopen invented saved witness");
            using var preparation = new NotesOriginalSetupPreparation(h.Host.Source, h.Host.Snapshot);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(25));
            var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("NODE") ?? "node") {
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
            start.ArgumentList.Add(Path.Combine(windows, "tests", "notes-setup-preparation.js"));
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Existing Node runtime required");
            var errors = process.StandardError.ReadToEndAsync();
            async Task Send(object packet)
            {
                await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(packet));
                await process.StandardInput.FlushAsync(deadline.Token);
            }
            JsonObject? delayedAck = null; var saves = 0; var replies = 0;
            try
            {
                await Send(new { type = "init", mode, daten = JsonNode.Parse(h.Host.CurrentNativeText!) });
                while (true)
                {
                    var line = await process.StandardOutput.ReadLineAsync(deadline.Token);
                    if (line is null) throw new InvalidOperationException("Preparation DOM exited: " + await errors);
                    var packet = JsonNode.Parse(line)!.AsObject();
                    if (packet["type"]!.GetValue<string>() == "initialized")
                    { await Send(new { callback = "notesSetupVorbereiten", value = new { token = preparation.Token } }); continue; }
                    if (packet["type"]!.GetValue<string>() == "string-ack-ignored")
                    { await Send(new { callback = "gespeichert", value = delayedAck }); continue; }
                    if (packet["type"]!.GetValue<string>() != "command") continue;
                    var command = packet["value"]!.AsObject();
                    switch (command["cmd"]!.GetValue<string>())
                    {
                        case "speichern":
                            TestAssert.That(replies == 0 && command["id"]!.GetValue<int>() > 0, "Preparation replied before numeric save completion");
                            saves++; h.Host.FailAfterPrimary = mode == "failed-writer";
                            var ack = await h.Host.SaveBridgeEnvelopeAsync(command);
                            if (mode == "string-ack")
                            {
                                delayedAck = ack; var fake = ack.DeepClone().AsObject(); fake["id"] = command["id"]!.GetValue<int>().ToString();
                                await Send(new { callback = "gespeichert", value = fake });
                            }
                            else await Send(new { callback = "gespeichert", value = ack });
                            break;
                        case "notes_setup_prepared":
                            using (BridgeDispatcherContract.Parse(command.ToJsonString())) { }
                            replies++;
                            await MutationGate.Global.WaitAsync(deadline.Token);
                            bool accepted;
                            try { accepted = preparation.Accept(command["token"]!.GetValue<string>(), command["bereit"]!.GetValue<bool>(), command["standSha256"]!.GetValue<string>()); }
                            finally { MutationGate.Global.Release(); }
                            var expected = mode is not ("failed-writer" or "locked" or "editor" or "modal");
                            TestAssert.That(accepted == expected && (await preparation.WaitAsync(deadline.Token) is not null) == expected, "DOM/native writer preparation mismatch: " + mode);
                            TestAssert.That(!preparation.Accept(preparation.Token, true, command["standSha256"]!.GetValue<string>()), "Duplicate native reply accepted");
                            if (expected)
                            {
                                var decision = await new NotesOriginalSetupFlow(h.Store, h.Capture).BeginAsync(deadline.Token); decision.Cancel();
                                if (mode == "pending") TestAssert.That(h.Host.CurrentNativeText!.Contains("Latest synthetic edit during pending save"), "Pending edit was not flushed");
                                if (mode == "note-snapshot") TestAssert.That(h.Host.CurrentNativeText!.Contains("Latest pending synthetic note"), "Actual Notes editor snapshot was not flushed");
                            }
                            TestAssert.That(!h.Store.HasDesiredConsent() && replies == 1 && saves == (mode is "locked" or "editor" or "modal" ? 0 : mode == "pending" ? 2 : 1), "Preparation started grants or duplicated/skipped serial saves");
                            await Send(new { type = "finish" });
                            await process.WaitForExitAsync(deadline.Token);
                            TestAssert.That(process.ExitCode == 0, "Preparation DOM failed: " + await errors);
                            Console.WriteLine("Notes actual DOM/native setup preparation PASS " + mode);
                            goto Finished;
                    }
                }
                Finished: ;
            }
            finally { if (!process.HasExited) { process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); } }
        }
    }
}
