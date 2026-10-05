using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class OpenHolidayDataTests
{
    internal static Task RunAsync()
    {
        using var document = JsonDocument.Parse("""
            [
              {"startDate":"2026-01-01","name":[{"language":"EN","text":"New Year"},{"language":"DE","text":"Neujahr"}],"nationwide":true},
              {"startDate":"2026-08-15","name":"Synthetic regional holiday","nationwide":false,"subdivisions":[{"code":"DE-SL"},{"code":"DE-BY"},{"code":"DE-BY"},{"code":4}]},
              {"startDate":"2026-05-01","endDate":"2026-04-30","name":"Corrected end","nationwide":true},
              {"startDate":"invalid","name":"Ignored"}
            ]
            """);
        var all = OpenHolidayData.Parse(document.RootElement, "public-holiday", "DE", "", "", "DE");
        TestAssert.That(all.Count == 3, "Valid provider holidays were dropped.");
        TestAssert.That(all.All(value => value.country == "DE"), "Country provenance was lost.");
        TestAssert.That(all[0].nationwide && all[0].regions.Length == 0 && all[0].name == "Neujahr", "Nationwide or localized provider data changed.");
        TestAssert.That(!all[1].nationwide && all[1].regions.SequenceEqual(new[] { "DE-BY", "DE-SL" }), "Regional scope was guessed or lost.");
        TestAssert.That(all[2].von == all[2].bis, "Invalid provider end dates must match the Linux normalization.");
        using var legacy = JsonDocument.Parse("""[{"startDate":"2026-01-02","name":"Scoped query"}]""");
        var scoped = OpenHolidayData.Parse(legacy.RootElement, "public-holiday", "DE", "DE-BY", "Bayern", "EN").Single();
        TestAssert.That(!scoped.nationwide && scoped.regions.SequenceEqual(new[] { "DE-BY" }), "A scoped query was promoted to a nationwide holiday.");
        return Task.CompletedTask;
    }
}
