using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RegionalSettingsTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-regional-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var path = new WindowsPaths(root).RegionalSettings;
            using var valid = JsonDocument.Parse("""
                {"language":"fr","formatLocale":"en_US","hourCycle":"h12",
                 "firstDayOfWeek":"sunday","weekRule":"other","temperatureUnit":"fahrenheit",
                 "timeZone":"America/New_York","homeCountry":"us"}
                """);
            var saved = RegionalSettings.Write(path, valid.RootElement);
            TestAssert.That(saved["language"]!.GetValue<string>() == "fr" &&
                saved["formatLocale"]!.GetValue<string>() == "en-US" &&
                saved["weekRule"]!.GetValue<string>() == "iso" &&
                saved["homeCountry"]!.GetValue<string>() == "US" &&
                saved["timeZone"]!.GetValue<string>() == "America/New_York",
                "Gültige Regionalwerte wurden nicht stabil normalisiert.");
            var loaded = RegionalSettings.Read(path);
            TestAssert.That(loaded.ToJsonString() == saved.ToJsonString(),
                "Frühe Regionalauswahl wurde nicht unabhängig von Benutzerdaten gespeichert.");
            var languageOnly = RegionalSettings.WriteLanguage(path, "de");
            TestAssert.That(languageOnly["language"]!.GetValue<string>() == "de" &&
                            languageOnly["hourCycle"]!.GetValue<string>() == "h12",
                "Die frühe Sprachwahl ersetzt bestehende Regionaleinstellungen statt sie zu erhalten.");
            using var legacyWriter = JsonDocument.Parse("""{"language":"en"}""");
            TestAssert.That(RegionalSettings.Write(path, legacyWriter.RootElement)["homeCountry"]!.GetValue<string>() == "US",
                "Ein älterer Schreiber hat das gespeicherte Heimatland überschrieben.");

            var beforeChecked = RegionalSettings.ReadVerified(path);
            var wanted = beforeChecked.DeepClone(); wanted["hourCycle"] = "h23"; wanted["timeZone"] = "UTC";
            var checkedValue = RegionalSettings.WriteChecked(path, JsonSerializer.SerializeToElement(wanted), JsonSerializer.SerializeToElement(beforeChecked));
            TestAssert.That(checkedValue["timeZone"]!.GetValue<string>() == "UTC" && checkedValue["homeCountry"]!.GetValue<string>() == "US",
                "Geprüftes Speichern muss die tatsächliche Native-Datei mit Heimatland und UTC erhalten.");
            var checkedText = File.ReadAllText(path);
            var staleRejected = false;
            try { RegionalSettings.WriteChecked(path, JsonSerializer.SerializeToElement(wanted), JsonSerializer.SerializeToElement(beforeChecked)); }
            catch (InvalidOperationException error) when (error.Message == "regional_conflict") { staleRejected = true; }
            TestAssert.That(staleRejected && File.ReadAllText(path) == checkedText, "Eine veraltete Native-Konfiguration darf keine Datei überschreiben.");
            var invalidZone = checkedValue.DeepClone(); invalidZone["timeZone"] = "Mars/Olympus";
            var zoneRejected = false;
            try { RegionalSettings.WriteChecked(path, JsonSerializer.SerializeToElement(invalidZone), JsonSerializer.SerializeToElement(checkedValue)); }
            catch (InvalidDataException error) when (error.Message == "invalid_regional_settings") { zoneRejected = true; }
            TestAssert.That(zoneRejected && File.ReadAllText(path) == checkedText, "Eine nicht existente Native-Zeitzone muss vor dem Dateischreiben scheitern.");

            using var invalid = JsonDocument.Parse("""
                {"language":"../../de","formatLocale":[],"hourCycle":"h99",
                 "firstDayOfWeek":"friday","temperatureUnit":"kelvin","timeZone":"../Berlin","homeCountry":"ZZ"}
                """);
            var clean = RegionalSettings.Write(path, invalid.RootElement);
            TestAssert.That(clean["language"]!.GetValue<string>() == "system" &&
                clean["formatLocale"]!.GetValue<string>() == "system" &&
                clean["hourCycle"]!.GetValue<string>() == "system" &&
                clean["firstDayOfWeek"]!.GetValue<string>() == "locale" &&
                clean["temperatureUnit"]!.GetValue<string>() == "system" &&
                clean["homeCountry"]!.GetValue<string>() == "DE" &&
                clean["timeZone"]!.GetValue<string>() == "system",
                "Ungültige Regionalwerte verlassen das Systemprofil.");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
        return Task.CompletedTask;
    }
}
