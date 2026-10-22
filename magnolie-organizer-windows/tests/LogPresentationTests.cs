namespace MagnolieOrganizer.Windows.Tests;

internal static class LogPresentationTests
{
    internal static Task RunAsync()
    {
        using (var vectors = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "resources", "diagnostics-redaction-v1.json"))))
            foreach (var entry in vectors.RootElement.GetProperty("cases").EnumerateArray())
            {
                var expected = entry.GetProperty("expected").GetString()!;
                TestAssert.That(LogPresentation.MaskSensitive(entry.GetProperty("input").GetString()!) == expected, "Diagnostic redaction differs from shared vector.");
                TestAssert.That(LogPresentation.MaskSensitive(expected) == expected, "Diagnostic masking is not idempotent.");
            }
        const string unlockedData = "{\"einstellungen\":{\"allgemein\":{\"contributorFreigeschaltet\":true}}}";
        const string lockedData = "{\"einstellungen\":{\"allgemein\":{\"contributorFreigeschaltet\":false}}}";
        CheckMarked(LogPresentation.Format("eins\nzwei\ndrei\n", false));
        CheckMarked(LogPresentation.Format("", false));
        CheckMarked(LogPresentation.Format("eins\n", false));
        CheckMarked(LogPresentation.Format($"eins\n{LogPresentation.Marker}\nzwei\n{LogPresentation.Marker}\ndrei\n", false));

        TestAssert.That(!LogPresentation.HasPersistentContributorUnlock(unlockedData, false, true),
            "Ein Eigenbau ohne Hash darf nicht freigeschaltet sein.");
        TestAssert.That(!LogPresentation.HasPersistentContributorUnlock(lockedData, true, true),
            "Ein offizieller, nicht freigeschalteter Build darf keinen markerfreien Log liefern.");
        TestAssert.That(LogPresentation.HasPersistentContributorUnlock(unlockedData, true, true),
            "Die persistente Freischaltung wurde nicht erkannt.");
        TestAssert.That(!LogPresentation.HasPersistentContributorUnlock(unlockedData, true, false),
            "Ein gesperrter Datenbestand muss fail-closed bleiben.");
        var cleaned = LogPresentation.Format($"eins\n{LogPresentation.Marker}\nzwei\n", true);
        TestAssert.That(!cleaned.Contains(LogPresentation.Marker, StringComparison.Ordinal),
            "Ein alter Marker blieb nach Freischaltung sichtbar.");

        var root = Path.Combine(Path.GetTempPath(), "magnolie-log-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(root);
            File.WriteAllText(Path.Combine(root, "webview.log"), "eins\nzwei\n");
            var view = LogPresentation.CreateView(root, false);
            CheckMarked(File.ReadAllText(Path.Combine(view, "webview.log")));
            TestAssert.That(File.ReadAllText(Path.Combine(root, "webview.log")) == "eins\nzwei\n",
                "Das Originalprotokoll wurde verändert.");

            var rotating = Path.Combine(root, "rotating.log");
            using (var oversized = new FileStream(rotating, FileMode.Create, FileAccess.Write))
                oversized.SetLength(RotatingLog.MaximumBytes - 4);
            RotatingLog.Append(rotating, "neuer Eintrag");
            TestAssert.That(File.Exists(rotating + ".old") && new FileInfo(rotating).Length < 1024,
                "Protokollrotation begrenzt die aktive Datei oder Altdatei nicht.");
            var parallel = Path.Combine(root, "parallel.log");
            Task.WaitAll(Enumerable.Range(0, 100).Select(index => Task.Run(() =>
                RotatingLog.Append(parallel, $"eintrag-{index}"))).ToArray());
            TestAssert.That(File.ReadAllLines(parallel).Length == 100,
                "Parallele Protokollschreiber verloren Einträge.");
            var limited = Path.Combine(root, "limited.log");
            var redacted = Path.Combine(root, "redacted.log");
            RotatingLog.Append(redacted, "password=fixture-password; phone=+49 351 1234567; mail=person@example.test");
            TestAssert.That(File.ReadAllText(redacted).Contains("password=***") && !File.ReadAllText(redacted).Contains("fixture-password") &&
                !File.ReadAllText(redacted).Contains("person@example.test") && !File.ReadAllText(redacted).Contains("1234567"), "Sensitive values reached the persisted log.");
            var crashPath = Path.Combine(root, "redacted-crash.log");
            TestAssert.That(CrashReportWriter.TryWrite(crashPath, "fixture", new InvalidOperationException("password=fixture-password; mail=person@example.test; phone=+49 351 1234567")), "Redacted crash was not written.");
            var crashText = File.ReadAllText(crashPath);
            TestAssert.That(crashText.Contains("InvalidOperationException") && crashText.Contains("***") &&
                !crashText.Contains("fixture-password") && !crashText.Contains("person@example.test") && !crashText.Contains("1234567"), "Sensitive values reached the persisted crash report.");
            RotatingLog.Append(limited, new string('x', RotatingLog.MaximumEntryBytes * 2));
            TestAssert.That(new FileInfo(limited).Length <= RotatingLog.MaximumEntryBytes + 4 &&
                File.ReadAllText(limited).Contains("[gekürzt]", StringComparison.Ordinal),
                "Ein einzelner Protokolleintrag umging die Größenbegrenzung.");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
        return Task.CompletedTask;
    }

    private static void CheckMarked(string text)
    {
        var lines = text.ReplaceLineEndings("\n").Split('\n', StringSplitOptions.RemoveEmptyEntries);
        TestAssert.That(lines.Count(line => line == LogPresentation.Marker) == 1,
            "Der Marker muss exakt einmal als alleinstehende Zeile vorkommen.");
        var position = Array.IndexOf(lines, LogPresentation.Marker);
        TestAssert.That(position > 0 && position < lines.Length - 1,
            "Der Marker darf weder erste noch letzte Zeile sein.");
    }
}
