namespace MagnolieOrganizer.Windows.Tests;

internal static class LocalizationBoundaryTests
{
    internal static Task RunAsync()
    {
        var bridge = File.ReadAllText("BridgeDispatcher.cs");
        var sync = File.ReadAllText("BridgeDispatcher.Sync.cs");
        foreach (var callback in new[] { "App.gespeichert", "App.sicherungFertig", "App.gesamtarchivAusgewaehlt",
                     "App.gesamtarchivExportiert", "App.gesamtarchivImportiert" })
            TestAssert.That(!System.Text.RegularExpressions.Regex.IsMatch(bridge,
                    System.Text.RegularExpressions.Regex.Escape(callback) + @"[\s\S]{0,300}fehler\s*=\s*error\.Message"),
                $"{callback} gibt einen technischen oder deutschen Ausnahmetext an die Oberfläche weiter.");
        TestAssert.That(bridge.Contains("ReportErrorAsync(\"gesamtarchiv_pruefen\", error.ToString())", StringComparison.Ordinal) &&
                        bridge.Contains("T(\"The complete archive could not be verified.\")", StringComparison.Ordinal) &&
                        sync.Contains("ReportErrorAsync(\"sync\", error.ToString())", StringComparison.Ordinal) &&
                        sync.Contains("T(\"Synchronization failed.\")", StringComparison.Ordinal),
            "Lokalisierte UI-Fehler und vollständige lokale Diagnosen sind nicht gemeinsam verdrahtet.");
        return Task.CompletedTask;
    }
}
