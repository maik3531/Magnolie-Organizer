using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneRegionInfoTests
{
    internal static Task RunAsync()
    {
        using var vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            AppContext.BaseDirectory, "resources", "phone-region-vectors.json")));
        foreach (var vector in vectors.RootElement.GetProperty("vectors").EnumerateArray())
        {
            var result = PhoneRegionInfo.Analyze(vector.GetProperty("number").GetString(),
                vector.GetProperty("number_status").GetString()!,
                vector.GetProperty("home_country").GetString(),
                vector.GetProperty("language").GetString());
            var status = vector.GetProperty("status").GetString();
            TestAssert.That(result.Status == status, "Telefonherkunft weicht vom gemeinsamen Vektor ab.");
            if (status == "known")
                TestAssert.That(result.E164 == vector.GetProperty("e164").GetString() &&
                    result.Region == vector.GetProperty("region").GetString() &&
                    result.IsForeign == vector.GetProperty("foreign").GetBoolean() &&
                    result.CountryName.Length > 0,
                    "Telefonnummer wurde nicht stabil normalisiert oder lokalisiert.");
            else TestAssert.That(result.E164.Length == 0 && result.IsForeign is null,
                "Für eine unbekannte Herkunft wurde geraten.");
        }
        foreach (var status in new[] { "withheld", "unavailable", "permission_missing", "not_shared" })
            TestAssert.That(PhoneRegionInfo.Analyze("+12025550123", status, "DE", "de").Status == "unknown",
                "Ein nicht freigegebener Nummernstatus wurde ausgewertet.");
        TestAssert.That(PhoneRegionInfo.HomeCountry(null) == "DE" &&
            PhoneRegionInfo.HomeCountry("us") == "US" && PhoneRegionInfo.HomeCountry("ZZ") == "DE",
            "homeCountry-Migration oder ISO-Validierung ist falsch.");
        return Task.CompletedTask;
    }
}
