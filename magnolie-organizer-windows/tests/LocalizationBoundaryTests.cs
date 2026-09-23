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
                        sync.Contains("NextcloudStatusText.For(error)", StringComparison.Ordinal),
            "Lokalisierte UI-Fehler und vollständige lokale Diagnosen sind nicht gemeinsam verdrahtet.");
        var language = MagnolieOrganizer.Windows.NativeLocalization.Language;
        try
        {
            MagnolieOrganizer.Windows.NativeLocalization.SetLanguage("de");
            var message = MagnolieOrganizer.Windows.NextcloudStatusText.For(new HttpRequestException(
                "PRIVATE-SERVER-DETAIL", null, System.Net.HttpStatusCode.Unauthorized));
            TestAssert.That(message.StartsWith("Anmeldung fehlgeschlagen.", StringComparison.Ordinal) &&
                !message.Contains("PRIVATE-SERVER-DETAIL", StringComparison.Ordinal),
                "DAV-Anmeldefehler sind unübersetzt oder enthalten technische Diagnosen.");
        }
        finally { MagnolieOrganizer.Windows.NativeLocalization.SetLanguage(language); }
        return Task.CompletedTask;
    }
}
