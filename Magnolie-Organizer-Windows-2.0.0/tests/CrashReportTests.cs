using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CrashReportTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-crash-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "crash.log");
            TestAssert.That(CrashReportWriter.DefaultPath.EndsWith(
                    Path.Combine("Magnolie Organizer", "Logs", "crash.log"), StringComparison.Ordinal),
                "Der Absturzbericht verwendet nicht den lokalen Magnolie-Organizer-Protokollpfad.");
            Exception exception;
            try { throw new InvalidOperationException("outer failure", new IOException("inner failure")); }
            catch (Exception error) { exception = error; }
            TestAssert.That(CrashReportWriter.TryWrite(path, "test source", exception,
                    DateTimeOffset.Parse("2026-08-28T12:34:56Z"), "2.0.0-test", "Test OS", "Test runtime"),
                "Der Absturzbericht meldete einen erfolgreichen Schreibvorgang als fehlgeschlagen.");

            using (var report = JsonDocument.Parse(File.ReadAllLines(path).Single()))
            {
                var rootElement = report.RootElement;
                TestAssert.That(rootElement.GetProperty("TimestampUtc").GetDateTimeOffset().Offset == TimeSpan.Zero &&
                                rootElement.GetProperty("AppVersion").GetString() == "2.0.0-test" &&
                                rootElement.GetProperty("Os").GetString() == "Test OS" &&
                                rootElement.GetProperty("Runtime").GetString() == "Test runtime" &&
                                rootElement.GetProperty("SourceKind").GetString() == "test source",
                    "Der Absturzbericht enthält nicht die erwarteten Metadaten.");
                var reportedException = rootElement.GetProperty("Exception");
                TestAssert.That(reportedException.GetProperty("Type").GetString() == typeof(InvalidOperationException).FullName &&
                                reportedException.GetProperty("Message").GetString() == "outer failure" &&
                                reportedException.GetProperty("Stack").GetString()!.Contains(nameof(RunAsync), StringComparison.Ordinal) &&
                                reportedException.GetProperty("InnerExceptions")[0].GetProperty("Message").GetString() == "inner failure",
                    "Ausnahmetyp, Meldung, Stack oder innere Ausnahme fehlt.");
            }

            var privateMarker = "MAGNOLIE_PRIVATE_" + Guid.NewGuid().ToString("N");
            Environment.SetEnvironmentVariable("MAGNOLIE_TEST_PRIVATE", privateMarker);
            TestAssert.That(CrashReportWriter.TryWrite(path, "privacy test", new Exception("public diagnostic")),
                "Der Datenschutz-Testbericht konnte nicht geschrieben werden.");
            var privacyReport = File.ReadAllLines(path).Last();
            TestAssert.That(!privacyReport.Contains(privateMarker, StringComparison.Ordinal) &&
                            !privacyReport.Contains("CommandLine", StringComparison.OrdinalIgnoreCase) &&
                            !privacyReport.Contains("Settings", StringComparison.OrdinalIgnoreCase) &&
                            !privacyReport.Contains("Contacts", StringComparison.OrdinalIgnoreCase) &&
                            !privacyReport.Contains("Token", StringComparison.OrdinalIgnoreCase),
                "Der Absturzbericht enthält Umgebungs-, Befehlszeilen-, Einstellungs-, Kontakt- oder Token-Daten.");

            File.WriteAllBytes(path, new byte[CrashReportWriter.MaximumBytes - 8]);
            CrashReportWriter.TryWrite(path, "rotation", new Exception("rotate now"));
            TestAssert.That(File.Exists(path + ".old") && new FileInfo(path + ".old").Length <= CrashReportWriter.MaximumBytes &&
                            new FileInfo(path).Length <= CrashReportWriter.MaximumBytes &&
                            File.ReadAllText(path).Contains("rotate now", StringComparison.Ordinal),
                "Das Absturzprotokoll wurde nicht auf genau eine begrenzte Altdatei rotiert.");
            File.WriteAllBytes(path, new byte[CrashReportWriter.MaximumBytes - 8]);
            CrashReportWriter.TryWrite(path, "rotation again", new Exception("replace old"));
            TestAssert.That(Directory.GetFiles(root, "crash.log.old*").Length == 1,
                "Die Rotation erzeugte mehr als eine Altdatei.");

            File.Delete(path);
            await Task.WhenAll(Enumerable.Range(0, 32).Select(index => Task.Run(() =>
                CrashReportWriter.TryWrite(path, "concurrent", new Exception($"failure-{index}"),
                    appVersion: "test", os: "test", runtime: "test"))));
            var entries = File.ReadAllLines(path);
            TestAssert.That(entries.Length == 32 && entries.All(line =>
                JsonDocument.Parse(line).RootElement.GetProperty("SourceKind").GetString() == "concurrent"),
                "Parallele Absturzberichte gingen verloren oder wurden vermischt.");

            var duplicate = new Exception("same instance");
            var deduplicator = new CrashReportDeduplicator();
            TestAssert.That(deduplicator.TryBegin(duplicate) && !deduplicator.TryBegin(duplicate),
                "Ein laufender Schreibvorgang wurde nicht gegen parallele Duplikate geschützt.");
            deduplicator.Complete(duplicate, success: false);
            TestAssert.That(deduplicator.TryBegin(duplicate),
                "Eine fehlgeschlagene Aufzeichnung konnte nicht erneut versucht werden.");
            deduplicator.Complete(duplicate, success: true);
            TestAssert.That(!deduplicator.TryBegin(duplicate),
                "Eine erfolgreich aufgezeichnete Ausnahme wurde erneut zugelassen.");

            var outside = Path.Combine(Path.GetTempPath(), $"magnolie-crash-outside-{Guid.NewGuid():N}");
            Directory.CreateDirectory(outside);
            try
            {
                var linkedLogs = Path.Combine(root, "linked-logs");
                Directory.CreateSymbolicLink(linkedLogs, outside);
                TestAssert.That(!CrashReportWriter.TryWrite(Path.Combine(linkedLogs, "crash.log"), "reparse", new Exception("blocked")) &&
                                !File.Exists(Path.Combine(outside, "crash.log")),
                    "Der Absturzbericht folgte einem Reparse-Point für das Logs-Verzeichnis.");

                var linkedLog = Path.Combine(root, "linked-crash.log");
                var outsideLog = Path.Combine(outside, "target.log");
                File.WriteAllText(outsideLog, "unchanged");
                File.CreateSymbolicLink(linkedLog, outsideLog);
                TestAssert.That(!CrashReportWriter.TryWrite(linkedLog, "reparse", new Exception("blocked")) &&
                                File.ReadAllText(outsideLog) == "unchanged",
                    "Der Absturzbericht folgte einem Reparse-Point für die Protokolldatei.");
            }
            finally
            {
                try { Directory.Delete(outside, true); } catch (Exception) { }
            }

            var programSource = File.ReadAllText("Program.cs");
            var reporterSource = File.ReadAllText("CrashReporter.cs");
            var writerSource = File.ReadAllText("CrashReportWriter.cs");
            var mainSource = File.ReadAllText("MainForm.cs");
            var handbookSource = File.ReadAllText("HandbookForm.cs");
            TestAssert.That(programSource.IndexOf("CrashReporter.RegisterHandlers();", StringComparison.Ordinal) <
                            programSource.IndexOf("args.Contains", StringComparison.Ordinal) &&
                            reporterSource.Contains("SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException)", StringComparison.Ordinal) &&
                            !reporterSource.Contains("Application.ThreadException +=", StringComparison.Ordinal) &&
                            reporterSource.Contains("AppDomain.CurrentDomain.UnhandledException +=", StringComparison.Ordinal) &&
                            reporterSource.Contains("TaskScheduler.UnobservedTaskException +=", StringComparison.Ordinal) &&
                            !reporterSource.Contains("SetObserved()", StringComparison.Ordinal) &&
                            reporterSource.Contains("diagnostic.log", StringComparison.Ordinal) &&
                            !mainSource.Contains("CrashReporter.Record", StringComparison.Ordinal) &&
                            !handbookSource.Contains("CrashReporter.Record", StringComparison.Ordinal),
                "Fataler UI-Absturz und nichtfatale Task-/WebView-Diagnosen sind nicht sauber getrennt.");
            TestAssert.That(writerSource.Contains("FileAttributes.ReparsePoint", StringComparison.Ordinal) &&
                            writerSource.Contains("WindowsIdentity.GetCurrent()", StringComparison.Ordinal) &&
                            writerSource.Contains("SetNamedSecurityInfo", StringComparison.Ordinal) &&
                            writerSource.Contains("(A;{flags};FA;;;SY)", StringComparison.Ordinal) &&
                            !writerSource.Contains("GetCommandLineArgs", StringComparison.Ordinal),
                "Reparse-Point-Schutz, private Windows-ACL oder Datenschutzgrenze fehlt.");
        }
        finally
        {
            Environment.SetEnvironmentVariable("MAGNOLIE_TEST_PRIVATE", null);
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }
}
