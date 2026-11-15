using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraSetupJournalTests
{
    private sealed class Fixture : IDisposable
    {
        private readonly string root = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "magnolie-setup-journal-" + Guid.NewGuid().ToString("N"));
        internal string Path => System.IO.Path.Combine(root, "transaction.journal");
        internal Fixture() => Directory.CreateDirectory(root);
        internal byte[] Read()
        {
            using var file = new FileStream(Path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var output = new MemoryStream(); file.CopyTo(output); return output.ToArray();
        }
        public void Dispose()
        {
            // Exact own fixture file only; no recursive deletion or installer IO.
            if (File.Exists(Path)) File.Delete(Path);
            Directory.Delete(root, recursive: false);
        }
    }
    private static PhoneCameraSetupJournal.Audit Audit(Fixture fixture) => PhoneCameraSetupJournal.Inspect(fixture.Read());
    private static JsonObject NativeReboot() => new() { ["schema"] = 1, ["driver"] = "VB-CABLE", ["mode"] = "install",
        ["state"] = "reboot_required", ["error"] = 0, ["ownDeviceRegistered"] = true, ["ownDeviceRemoved"] = false,
        ["rebootRequired"] = true, ["defaultsPreserved"] = true, ["ownInstance"] = "ROOT\\MEDIA\\original-native-1" };
    internal static Task NativeResultAfterSourceAsync()
    {
        var json = NativeReboot().ToJsonString();
        TestAssert.That(PhoneCameraAudioSetupWire.IsRebootResult(json, out var own) && own == "ROOT\\MEDIA\\original-native-1",
            "Original helper OwnInstance not extracted verbatim");
        using var fixture = new Fixture();
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            foreach (var stage in Enumerable.Range(0, 3))
            {
                var before = fixture.Read();
                TestAssert.Throws<InvalidOperationException>(() => writer.RecordMicrophoneResult(3010, json), "Mic-only outcome skipped original Source or intent");
                TestAssert.That(fixture.Read().SequenceEqual(before), "Rejected mic-only result changed journal");
                if (stage == 0) writer.BeginSource();
                if (stage == 1) writer.ConfirmSource();
            }
            writer.BeginMicrophone();
            TestAssert.That(writer.RecordMicrophoneResult(3010, json) == PhoneCameraSetupJournal.Phase.RebootRequired, "Exact native outcome refused");
            TestAssert.Throws<InvalidOperationException>(() => writer.RecordMicrophoneResult(3010, json), "Confirmed native outcome consumed twice");
        }
        var audit = Audit(fixture);
        TestAssert.That(audit.SourceConfirmed && audit.MicrophoneStarted && audit.OwnMicrophoneInstance == own &&
            audit.Outcome == PhoneCameraSetupJournal.Phase.RebootRequired, "Joint native result lost original instance or Source step");
        return Task.CompletedTask;
    }
    internal static Task NativeAmbiguityIsTerminalAsync()
    {
        var variants = new List<(int Exit, string? Json)> { (0, NativeReboot().ToJsonString()), (5, NativeReboot().ToJsonString()),
            (1223, NativeReboot().ToJsonString()), (3010, null), (3010, ""), (3010, "{"), (3010, "[]"),
            (3010, new string('x', PhoneCameraAudioSetupWire.MaximumNativeResult + 1)) };
        foreach (var mutation in new Action<JsonObject>[] {
            o => o["schema"] = 2, o => o["driver"] = "foreign", o => o["mode"] = "plan", o => o["state"] = "unknown_pending",
            o => o["error"] = 5, o => o["error"] = "0", o => o["error"] = JsonNode.Parse("9999999999999999999999999999999"),
            o => o["ownDeviceRegistered"] = false, o => o["ownDeviceRemoved"] = true, o => o["rebootRequired"] = false,
            o => o["defaultsPreserved"] = false, o => o["defaultsPreserved"] = "true", o => o["ownInstance"] = "",
            o => o["ownInstance"] = "ROOT\nMEDIA", o => o["ownInstance"] = new string('a', 200),
            o => o.Remove("ownInstance"), o => o["unknown"] = "keep" })
        { var reply = NativeReboot(); mutation(reply); variants.Add((3010, reply.ToJsonString())); }
        variants.Add((3010, NativeReboot().ToJsonString().Replace("\"schema\":1", "\"schema\":1,\"schema\":1", StringComparison.Ordinal)));
        foreach (var (exit, reply) in variants)
        {
            using var fixture = new Fixture();
            using var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path);
            writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone();
            TestAssert.That(writer.RecordMicrophoneResult(exit, reply) == PhoneCameraSetupJournal.Phase.UnknownPending,
                "Ambiguous native outcome certified completion");
            var audit = Audit(fixture);
            TestAssert.That(audit.Outcome == PhoneCameraSetupJournal.Phase.UnknownPending && audit.SourceConfirmed &&
                audit.MicrophoneStarted && audit.OwnMicrophoneInstance is null, "Uncertain outcome lost known steps or invented devnode");
            TestAssert.Throws<InvalidOperationException>(writer.BeginMicrophone, "Uncertain native mutation retried");
            TestAssert.Throws<InvalidOperationException>(() => writer.RecordMicrophoneResult(3010, NativeReboot().ToJsonString()), "Late receipt revived uncertain transaction");
        }
        foreach (var (exit, state) in new[] { (1603, "failed"), (1618, "unknown_pending"), (1618, "cleanup_pending") })
        {
            using var fixture = new Fixture(); using var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path);
            writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone();
            var reply = NativeReboot(); reply["state"] = state; reply["error"] = 5;
            TestAssert.That(writer.RecordMicrophoneResult(exit, reply.ToJsonString()) == PhoneCameraSetupJournal.Phase.UnknownPending &&
                Audit(fixture).OwnMicrophoneInstance == "ROOT\\MEDIA\\original-native-1", "Known partial native devnode was discarded or certified as success");
        }
        return Task.CompletedTask;
    }
    internal static async Task NativeResultExclusiveAndPoisonedAsync()
    {
        using (var fixture = new Fixture())
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone();
            var accepted = 0;
            await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() => {
                try { writer.RecordMicrophoneResult(3010, NativeReboot().ToJsonString()); Interlocked.Increment(ref accepted); }
                catch (InvalidOperationException) { }
            })));
            TestAssert.That(accepted == 1 && Audit(fixture).Outcome == PhoneCameraSetupJournal.Phase.RebootRequired, "Native result had multiple journal winners");
        }
        using (var fixture = new Fixture())
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone(); writer.JournalFixtureBreakWriter();
            TestAssert.Throws<ObjectDisposedException>(() => writer.RecordMicrophoneResult(3010, NativeReboot().ToJsonString()), "Broken durable outcome write succeeded");
            TestAssert.Throws<InvalidOperationException>(() => writer.RecordMicrophoneResult(3010, NativeReboot().ToJsonString()), "Unconfirmed durable write retried");
            TestAssert.That(Audit(fixture).Outcome == PhoneCameraSetupJournal.Phase.UnknownPending &&
                Audit(fixture).LastPhase == PhoneCameraSetupJournal.Phase.MicrophoneIntent, "Write failure fabricated completed journal");
        }
    }
    internal static Task DurableOrderAsync()
    {
        using var fixture = new Fixture();
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            var initial = Audit(fixture);
            TestAssert.That(initial.LastPhase == PhoneCameraSetupJournal.Phase.Prepared &&
                initial.Outcome == PhoneCameraSetupJournal.Phase.UnknownPending && !initial.SourceStarted, "Prepared journal authorized completion/retry");
            writer.BeginSource(); TestAssert.That(Audit(fixture).SourceStarted && !Audit(fixture).SourceConfirmed, "Source intent not durable before confirmation");
            writer.ConfirmSource(); TestAssert.That(Audit(fixture).SourceConfirmed && !Audit(fixture).MicrophoneStarted, "Source and microphone collapsed into one step");
            writer.BeginMicrophone(); TestAssert.That(Audit(fixture).MicrophoneStarted, "Microphone intent not durable");
            writer.ConfirmMicrophoneRebootRequired("ROOT\\MEDIA\\0001");
        }
        var final = Audit(fixture);
        TestAssert.That(final.Outcome == PhoneCameraSetupJournal.Phase.RebootRequired && final.OwnMicrophoneInstance == "ROOT\\MEDIA\\0001" &&
            final.SourceSha256 == new string('a', 64) && final.HelperSha256 == new string('b', 64) &&
            final.SourceRelativePath == "Magnolie-Webcam-Source\\" + new string('a', 64) + "\\" + PhoneCameraSourcePayload.Filename,
            "Combined identity/outcome lost");
        var bytes = fixture.Read();
        var ends = bytes.Select((value, index) => (value, index)).Where(pair => pair.value == '\n').Select(pair => pair.index + 1).ToArray();
        TestAssert.That(ends.Length == 5, "Unexpected journal sequence");
        foreach (var end in ends[..^1])
        {
            var interrupted = PhoneCameraSetupJournal.Inspect(bytes.AsSpan(0, end));
            TestAssert.That(interrupted.Outcome == PhoneCameraSetupJournal.Phase.UnknownPending, "Interrupted setup marked complete");
        }
        foreach (var end in ends)
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraSetupJournal.Inspect(bytes.AsSpan(0, end - 1)), "Torn row treated as unused/completed");
        return Task.CompletedTask;
    }
    internal static Task GuardsAndUncertaintyAsync()
    {
        using (var fixture = new Fixture())
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            var before = fixture.Read();
            TestAssert.Throws<InvalidOperationException>(writer.ConfirmSource, "Unstarted Source confirmed");
            TestAssert.Throws<InvalidOperationException>(writer.BeginMicrophone, "Mic ran before Source");
            TestAssert.Throws<InvalidOperationException>(() => writer.ConfirmMicrophoneRebootRequired("ROOT\\MEDIA\\1"), "Audio-only completion accepted");
            TestAssert.That(fixture.Read().SequenceEqual(before), "Invalid ordering changed journal");
            writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone();
            foreach (var invalid in new[] { "", new string('x', 200), "ROOT\nMEDIA", "ROOT\0MEDIA" })
                TestAssert.Throws<InvalidOperationException>(() => writer.ConfirmMicrophoneRebootRequired(invalid), "Invalid own devnode accepted");
            writer.RecordFailure(unknown: true, knownMicrophoneInstance: "ROOT\\MEDIA\\2");
            var audit = Audit(fixture);
            TestAssert.That(audit.SourceConfirmed && audit.MicrophoneStarted && audit.OwnMicrophoneInstance == "ROOT\\MEDIA\\2" &&
                audit.Outcome == PhoneCameraSetupJournal.Phase.UnknownPending, "Partial/unknown mic outcome lost known source/devnode");
            TestAssert.Throws<InvalidOperationException>(writer.BeginSource, "Unknown source retried");
            TestAssert.Throws<InvalidOperationException>(() => writer.ConfirmMicrophoneRebootRequired("ROOT\\MEDIA\\2"), "Unknown outcome revived");
        }
        foreach (var stage in Enumerable.Range(0, 4))
        using (var fixture = new Fixture())
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            if (stage >= 1) writer.BeginSource();
            if (stage >= 2) writer.ConfirmSource();
            if (stage >= 3) writer.BeginMicrophone();
            writer.RecordFailure(unknown: false);
            TestAssert.That(Audit(fixture).Outcome == PhoneCameraSetupJournal.Phase.Failed &&
                Audit(fixture).SourceConfirmed == (stage >= 2), "Known failure discarded partial ownership history");
            TestAssert.Throws<InvalidOperationException>(writer.BeginSource, "Failed setup retried");
        }
        using (var fixture = new Fixture())
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            writer.JournalFixtureBreakWriter();
            TestAssert.Throws<ObjectDisposedException>(writer.BeginSource, "Closed journal write succeeded");
            TestAssert.Throws<InvalidOperationException>(writer.BeginSource, "Writer retried uncertain write");
            TestAssert.That(Audit(fixture).LastPhase == PhoneCameraSetupJournal.Phase.Prepared, "Failed write fabricated Source intent");
        }
        return Task.CompletedTask;
    }
    internal static Task StrictAuditAsync()
    {
        using var fixture = new Fixture();
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        { writer.BeginSource(); writer.ConfirmSource(); writer.BeginMicrophone(); writer.ConfirmMicrophoneRebootRequired("ROOT\\MEDIA\\3"); }
        var bytes = fixture.Read();
        var changed = bytes.ToArray(); changed[70] ^= 1;
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSetupJournal.Inspect(changed), "Changed journal accepted");
        foreach (var mutate in new Action<JsonObject>[] {
            o => o["schema"] = 2, o => o["sourceClassId"] = Guid.Empty.ToString(),
            o => o["sourceRelativePath"] = "..\\external.dll", o => o["sourceSha256"] = new string('A', 64),
            o => o["helperSha256"] = new string('c', 64), o => o["microphonePackageSha256"] = new string('d', 64),
            o => o["sequence"] = 99, o => o["previousSha256"] = new string('e', 64),
            o => o["phase"] = "SourceIntent", o => o["phase"] = "CaptureReady",
            o => o["ownMicrophoneInstance"] = "", o => o["unknown"] = true,
            o => o.Remove("sourceClassId") })
        {
            var rows = Encoding.UTF8.GetString(bytes).Split('\n');
            var entry = JsonNode.Parse(rows[^2][65..])!.AsObject(); mutate(entry);
            var payload = Encoding.UTF8.GetBytes(entry.ToJsonString());
            rows[^2] = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant() + ":" + Encoding.UTF8.GetString(payload);
            var forged = Encoding.UTF8.GetBytes(string.Join("\n", rows));
            TestAssert.Throws<InvalidDataException>(() => PhoneCameraSetupJournal.Inspect(forged), "Rehashed invalid identity/history accepted");
        }
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSetupJournal.Inspect([]), "Empty journal treated as unused");
        TestAssert.Throws<InvalidDataException>(() => PhoneCameraSetupJournal.Inspect(new byte[32769]), "Unbounded journal accepted");
        return Task.CompletedTask;
    }
    internal static async Task ExclusiveOrderAsync()
    {
        using var fixture = new Fixture();
        using (var writer = PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path))
        {
            TestAssert.Throws<IOException>(() => PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path), "Concurrent transaction replaced original");
            var passed = 0;
            await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() => {
                try { writer.BeginSource(); Interlocked.Increment(ref passed); }
                catch (InvalidOperationException) { }
            })));
            TestAssert.That(passed == 1 && Audit(fixture).LastPhase == PhoneCameraSetupJournal.Phase.SourceIntent, "Source mutation intent consumed more than once");
        }
        var original = fixture.Read();
        TestAssert.Throws<IOException>(() => PhoneCameraSetupJournal.JournalFixtureCreate(fixture.Path), "Interrupted transaction automatically reopened");
        TestAssert.That(fixture.Read().SequenceEqual(original), "Existing journal overwritten");
    }
}
