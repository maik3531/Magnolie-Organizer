using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NoteSendTests
{
    internal static async Task RunAsync()
    {
        var directory = Path.Combine(Path.GetTempPath(), "magnolie-owned-note-send-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "owned.pdf");
            var bytes = Encoding.UTF8.GetBytes("%PDF-1.4\nOwned selected synthetic note only\n%%EOF\n");
            File.WriteAllBytes(path, bytes);
            using var defaults = JsonDocument.Parse("{}");
            var disabled = NoteSendTransport.Settings(defaults.RootElement);
            TestAssert.That(!disabled.Enabled && disabled.FaxServer == "", "Note sending must be disabled by default.");
            var calls = 0;
            Reject("feature_disabled", () => NoteSendTransport.Handoff(disabled, "email", "owned@example.test", "Owned", path, directory, _ => { calls++; return 0; }));
            TestAssert.That(calls == 0, "Disabled note sending invoked an adapter.");
            var config = new NoteSendSettings(true, "");
            var sent = NoteSendTransport.Handoff(config, "email", "owned@example.test", "Owned 🌸 selection", path, directory, envelope =>
            {
                calls++;
                TestAssert.That(envelope.Recipient == "owned@example.test" && envelope.Subject == "Owned 🌸 selection" &&
                    File.ReadAllBytes(envelope.PdfPath).SequenceEqual(bytes), "MAPI handoff lost the selected PDF, recipient or Unicode subject.");
                return 0;
            });
            TestAssert.That(calls == 1 && sent.Stage == "handed_off" && sent.Accepted && !sent.DeliveryConfirmed &&
                sent.Document.Bytes == bytes.Length && sent.Document.Sha256 == Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(), "MAPI receipt must prove only document handoff, never delivery.");
            var cancelled = NoteSendTransport.Handoff(config, "email", "owned@example.test", "Owned", path, directory, _ => 1);
            TestAssert.That(cancelled.Stage == "cancelled" && !cancelled.Accepted && !cancelled.DeliveryConfirmed, "MAPI user cancellation was reported as sent.");
            Reject("unsupported_adapter", () => NoteSendTransport.Handoff(config, "email", "owned@example.test", "Owned 🌸", path, directory, _ => 27));
            try
            {
                NoteSendTransport.Handoff(config, "email", "owned@example.test", "Owned", path, directory, _ => 2);
                throw new InvalidOperationException("MAPI failure was accepted.");
            }
            catch (NoteSendException error) { TestAssert.That(error.Code == "native_operation_failed" && error.Dispatched, "Post-dispatch failure lost the unknown native outcome."); }
            Reject("unsupported_adapter", () => NoteSendTransport.Handoff(config, "fax", "+49305550123", "Owned", path, directory, _ => 0));
            Reject("invalid_recipient", () => NoteSendTransport.Recipient("email", "owned@example.test\r\nBcc:foreign@example.test"));
            Reject("invalid_recipient", () => NoteSendTransport.Recipient("fax", "--other-option"));
            foreach (var server in new[] { "--other-option", "user:password@host", "host;owned", "host:99999" })
                Reject("invalid_fax_server", () => NoteSendTransport.FaxServer(server));
            TestAssert.That(NoteSendTransport.FaxServer("FAX.EXAMPLE.TEST:04559") == "fax.example.test:4559", "Fax server normalization differs from the shared settings.");
            File.WriteAllText(path, "not a PDF");
            Reject("invalid_document", () => NoteSendTransport.PdfReceipt(path, directory));
            if (!OperatingSystem.IsWindows()) TestAssert.That(!NoteSendTransport.DiscoverMailClient().Available, "Portable fixtures must not activate a Windows mail client.");
            const string faxCard = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Recipient;Owned;;;\r\nFN:Owned Recipient\r\nTEL;TYPE=HOMEFAX:+49305550125\r\nTEL;TYPE=WORKFAX:+49305550126\r\nTEL;TYPE=CELL:+49305550124\r\nX-OWNED:preserved\r\nEND:VCARD\r\n";
            var imported = ExchangeCodec.ParseVCard(faxCard).Kontakte.OfType<JsonObject>().Single();
            using (var data = JsonDocument.Parse(new JsonArray(imported.DeepClone()).ToJsonString()))
            {
                var exported = ExchangeCodec.WriteVCard(data.RootElement).Text;
                var restored = ExchangeCodec.ParseVCard(exported).Kontakte.OfType<JsonObject>().Single();
                var phones = restored["telefone"]!.AsArray().OfType<JsonObject>().ToDictionary(item => item["wert"]!.GetValue<string>());
                TestAssert.That(IsFax(phones["+49305550125"]) && IsFax(phones["+49305550126"]) &&
                    !IsFax(phones["+49305550124"]) && exported.Contains("X-OWNED:preserved", StringComparison.Ordinal),
                    "Existing HOMEFAX/WORKFAX contact semantics or foreign fields were lost in native interchange.");
            }
            await CheckJobsAsync(Path.Combine(directory, "jobs"));
        }
        finally { Directory.Delete(directory, recursive: true); }
    }
    private static async Task CheckJobsAsync(string directory)
    {
        var config = new NoteSendSettings(true, "");
        var renders = new System.Collections.Concurrent.ConcurrentQueue<(string Path, TaskCompletionSource Release)>();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var releaseHandoff = new ManualResetEventSlim();
        var calls = 0; var nativeCancel = false; var context = new AsyncLocal<string?> { Value = "owned-front-context" };
        using var service = new NoteSendJobs(directory, () => config, async (html, path) =>
        {
            TestAssert.That(context.Value is null && html.Contains("Owned", StringComparison.Ordinal), "PDF preparation inherited an unrelated front-end action context.");
            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            renders.Enqueue((path, release)); await release.Task;
            File.WriteAllText(path, "%PDF-1.4\nOwned selected synthetic note\n%%EOF\n");
        }, () => new(true, true, "owned-client", "Owned synthetic MAPI"), (settings, kind, target, subject, pdf, root) =>
        {
            Interlocked.Increment(ref calls);
            TestAssert.That(context.Value is null, "Mail handoff inherited an unrelated front-end action context.");
            entered.TrySetResult(); TestAssert.That(releaseHandoff.Wait(TimeSpan.FromSeconds(3)), "Synthetic handoff release timed out.");
            return new(nativeCancel ? "cancelled" : "handed_off", "simple-mapi", !nativeCancel, false, NoteSendTransport.PdfReceipt(pdf, root));
        });
        var revision = service.Read()["revision"]!.GetValue<string>();
        var first = new string('1', 48);
        service.Begin("<p>Owned selected</p>", "email", "owned@example.test", "Owned", revision, first);
        await WaitUntilAsync(() => renders.Count == 1);
        TestAssert.That(service.Begin("<p>Owned selected</p>", "email", "owned@example.test", "Owned", revision, first)["phase"]!.GetValue<string>() == "preparing" && renders.Count == 1,
            "Replaying the exact operation ID created a second document/handoff.");
        Reject("conflict", () => service.Begin("<p>Different Owned</p>", "email", "owned@example.test", "Owned", revision, first));
        var cancelled = service.Cancel(first);
        TestAssert.That(cancelled["cancel_accepted"]!.GetValue<bool>() && cancelled["phase"]!.GetValue<string>() == "cancelled", "Cancellation before PDF completion was not accepted.");
        TestAssert.That(renders.TryDequeue(out var firstRender), "Missing first renderer."); firstRender.Release.TrySetResult();
        await WaitUntilAsync(() => !Directory.Exists(Path.GetDirectoryName(firstRender.Path)));
        TestAssert.That(calls == 0, "A cancelled PDF preparation invoked mail handoff.");
        var second = new string('2', 48);
        service.Begin("<p>Owned selected</p>", "email", "owned@example.test", "Owned", revision, second);
        await WaitUntilAsync(() => renders.Count == 1); config = new(false, "");
        TestAssert.That(renders.TryDequeue(out var secondRender), "Missing second renderer."); secondRender.Release.TrySetResult();
        await WaitUntilAsync(() => service.Status(second)["phase"]!.GetValue<string>() == "failed");
        TestAssert.That(service.Status(second)["error_code"]!.GetValue<string>() == "conflict" && calls == 0, "Disabling during PDF preparation did not prevent external dispatch.");
        config = new(true, "");
        var third = new string('3', 48);
        service.Begin("<p>Owned selected</p>", "email", "owned@example.test", "Owned", service.Read()["revision"]!.GetValue<string>(), third);
        await WaitUntilAsync(() => renders.Count == 1);
        TestAssert.That(renders.TryDequeue(out var thirdRender), "Missing third renderer."); thirdRender.Release.TrySetResult();
        try
        {
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(3));
            var pending = service.Status(third);
            TestAssert.That(pending["phase"]!.GetValue<string>() == "external_pending" && pending["native_outcome_unknown"]!.GetValue<bool>() &&
                !service.Cancel(third)["cancel_accepted"]!.GetValue<bool>(), "Already dispatched handoff was incorrectly recalled.");
        }
        finally { releaseHandoff.Set(); }
        await WaitUntilAsync(() => service.Status(third)["phase"]!.GetValue<string>() == "handed_off");
        var completed = service.Status(third);
        TestAssert.That(calls == 1 && completed["handed_off"]!.GetValue<bool>() && !completed["delivery_confirmed"]!.GetValue<bool>() && completed["document"]!["sha256"]!.GetValue<string>().Length == 64,
            "Asynchronous note-send result did not carry the actual PDF readback and honest handoff receipt.");
        nativeCancel = true;
        var fourth = new string('4', 48);
        service.Begin("<p>Owned selected</p>", "email", "owned@example.test", "Owned", service.Read()["revision"]!.GetValue<string>(), fourth);
        await WaitUntilAsync(() => renders.Count == 1);
        TestAssert.That(renders.TryDequeue(out var fourthRender), "Missing fourth renderer."); fourthRender.Release.TrySetResult();
        await WaitUntilAsync(() => !Directory.Exists(Path.GetDirectoryName(fourthRender.Path)));
        var userCancelled = service.Status(fourth);
        TestAssert.That(userCancelled["phase"]!.GetValue<string>() == "cancelled" && !userCancelled["handed_off"]!.GetValue<bool>() &&
            !userCancelled["native_outcome_unknown"]!.GetValue<bool>() && !service.Cancel(fourth)["cancel_accepted"]!.GetValue<bool>(), "Native mail-dialog cancellation did not preserve its honest phase and clean the prepared PDF.");
    }
    private static async Task WaitUntilAsync(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow.AddSeconds(3);
        while (!condition()) { TestAssert.That(DateTime.UtcNow < deadline, "Owned asynchronous note-send fixture timed out."); await Task.Delay(5); }
    }
    private static bool IsFax(JsonObject phone) => phone["typen"]!.AsArray()
        .Any(value => value!.GetValue<string>().ToUpperInvariant() is "FAX" or "HOMEFAX" or "WORKFAX");
    private static void Reject(string code, Action action)
    {
        try { action(); throw new InvalidOperationException("Expected " + code); }
        catch (NoteSendException error) { TestAssert.That(error.Code == code, "Unexpected note-send rejection: " + error.Code); }
    }
}
