using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CycleCalendarTests
{
    internal static Task RunAsync()
    {
        var root = new JsonObject {
            ["zyklusmarker"] = new JsonArray(new JsonObject { ["id"] = "bleeding", ["art"] = "bleeding-light", ["name"] = "Renamed" }),
            ["tagmarken"] = new JsonArray(),
            ["einstellungen"] = new JsonObject { ["kalender"] = new JsonObject { ["zykluskalenderAn"] = true,
                ["zyklusErinnerungen"] = new JsonObject { ["prognose"] = true, ["vorlauf"] = 2, ["abweichung"] = true, ["abweichungTage"] = 7 } } } };
        void Dates(params string[] dates) => root["tagmarken"] = new JsonArray(dates.Select(date => (JsonNode)new JsonObject { ["datum"] = date, ["zyklusIds"] = new JsonArray("bleeding") }).ToArray());
        JsonDocument Document() => JsonDocument.Parse(root.ToJsonString());
        Dates("2026-01-01", "2026-01-02", "2026-01-29", "2026-02-26");
        using (var doc = Document()) {
            var stats = CycleCalendar.Estimate(doc.RootElement, "2026-04-10");
            TestAssert.That(stats.Starts.Length == 3 && stats.Length == 28 && stats.Predicted == "2026-03-26", "Episode grouping or forecast changed.");
            var reminders = CycleCalendar.Reminders(doc.RootElement, "2026-04-10");
            TestAssert.That(reminders.Length == 1 && reminders[0]["individuelleErinnerungTage"]!.GetValue<int>() == 2, "Forecast lead not projected.");
        }
        Dates("2026-01-01", "2026-01-29", "2026-02-26", "2026-04-09");
        using (var doc = Document()) {
            var stats = CycleCalendar.Estimate(doc.RootElement, "2026-04-10");
            TestAssert.That(stats.Baseline == 28 && stats.Latest == 42 && stats.Predicted == "2026-05-07" && CycleCalendar.Reminders(doc.RootElement, "2026-04-10").Length == 2,
                "Unusual intervals must use the preceding baseline and separate reminder.");
        }
        Dates("2026-01-01", "2026-01-29");
        using (var doc = Document()) TestAssert.That(CycleCalendar.Reminders(doc.RootElement, "2026-04-10").Length == 0, "Too few starts invented a forecast.");
        using (var doc = Document()) {
            var today = DateOnly.Parse(CycleCalendar.OrganizerToday(doc.RootElement), System.Globalization.CultureInfo.InvariantCulture);
            Dates(new[] { 98, 70, 42, 0 }.Select(offset => today.AddDays(-offset).ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture)).ToArray());
        }
        using (var projected = JsonDocument.Parse(ReminderScheduler.SelectRuntimeData(root.ToJsonString())))
            TestAssert.That(projected.RootElement.GetProperty("termine").GetArrayLength() == 2, "Native encrypted reminder projection omitted cycle reminders.");
        Dates("9999-11-02", "9999-11-30", "9999-12-28");
        using (var doc = Document()) TestAssert.That(CycleCalendar.Estimate(doc.RootElement, "9999-12-31").Predicted is null, "Year overflow must not create an invalid date.");
        return CycleForecastTests.RunAsync();
    }
}
