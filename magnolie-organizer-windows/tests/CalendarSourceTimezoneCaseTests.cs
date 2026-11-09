using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarSourceTimezoneCaseTests
{
    internal static Task RunAsync()
    {
        static string Calendar(string zone, string uid) => "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + zone +
            "BEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART;TZID=Custom/Case:20260102T120000\r\nSUMMARY:Case probe\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        foreach (var (begin, standard, property, end) in new[] {
            ("BEGIN:VTIMEZONE", "BEGIN:STANDARD", "TZID", "END:VTIMEZONE"),
            ("BEGIN:Vtimezone", "BEGIN:Standard", "TZID", "END:Vtimezone"),
            ("begin:VTIMEZONE", "begin:STANDARD", "tZiD", "end:VTIMEZONE") })
        {
            var endStandard = standard.Replace("BEGIN", "END", StringComparison.Ordinal).Replace("begin", "end", StringComparison.Ordinal);
            var zone = string.Join("\r\n", begin, property + ":Custom/Case", standard, "DTSTART:19700101T000000",
                "TZOFFSETFROM:+0300", "TZOFFSETTO:+0300", endStandard, end) + "\r\n";
            var source = Calendar(zone, "source-case-459");
            var imported = ExchangeCodec.ParseIcs(source, "case-459", TimeZoneInfo.Utc);
            TestAssert.That(imported.Uebersprungen == 0 && imported.Termine.Count == 1 &&
                imported.Termine[0]!["datum"]!.GetValue<string>() == "2026-01-02" &&
                imported.Termine[0]!["zeit"]!.GetValue<string>() == "09:00",
                "Source VTIMEZONE case changed the imported UTC instant: " + begin);
            using var restarted = JsonDocument.Parse(imported.Termine.ToJsonString());
            var exported = ExchangeCodec.WriteIcs("ics-termine", restarted.RootElement).Text;
            TestAssert.That(exported.Contains(zone, StringComparison.Ordinal), "Export rewrote or discarded original source lines: " + begin);
            var again = ExchangeCodec.ParseIcs(exported, "case-459", TimeZoneInfo.Utc);
            TestAssert.That(again.Termine.Count == 1 && again.Termine[0]!["zeit"]!.GetValue<string>() == "09:00" &&
                again.Termine[0]!["uid"]!.GetValue<string>() == "source-case-459",
                "Source-case export/reimport changed identity or instant: " + begin);
            TestAssert.Throws<InvalidDataException>(() => ExchangeCodec.ParseIcs(source.Replace(endStandard, "END:DAYLIGHT", StringComparison.Ordinal)),
                "Mixed-case acceptance relaxed component-stack validation.");
            TestAssert.Throws<InvalidDataException>(() => ExchangeCodec.ParseIcs(Calendar(zone + zone, "duplicate-zone")),
                "Duplicate source definitions were accepted.");
        }
        const string firstZone = "begin:VTIMEZONE\r\ntZiD:Custom/Case\r\nBEGIN:Standard\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0300\r\nTZOFFSETTO:+0300\r\nEND:Standard\r\nend:VTIMEZONE\r\n";
        var first = ExchangeCodec.ParseIcs(Calendar(firstZone, "first-source"), timeZone: TimeZoneInfo.Utc);
        var second = ExchangeCodec.ParseIcs(Calendar(firstZone.Replace("+0300", "+0200", StringComparison.Ordinal), "second-source"), timeZone: TimeZoneInfo.Utc);
        var combined = new System.Text.Json.Nodes.JsonArray(first.Termine[0]!.DeepClone(), second.Termine[0]!.DeepClone());
        using var combinedRestart = JsonDocument.Parse(combined.ToJsonString());
        var aliased = ExchangeCodec.WriteIcs("ics-termine", combinedRestart.RootElement).Text;
        var recovered = ExchangeCodec.ParseIcs(aliased, timeZone: TimeZoneInfo.Utc);
        TestAssert.That(aliased.Contains(firstZone, StringComparison.Ordinal) && aliased.Contains("TZID:Magnolie/", StringComparison.Ordinal) &&
            recovered.Termine.Count == 2 && recovered.Termine.Single(item => item!["uid"]!.GetValue<string>() == "first-source")!["zeit"]!.GetValue<string>() == "09:00" &&
            recovered.Termine.Single(item => item!["uid"]!.GetValue<string>() == "second-source")!["zeit"]!.GetValue<string>() == "10:00",
            "Preserving untouched source lines disabled required aliases or changed conflicting-zone instants.");
        return Task.CompletedTask;
    }
}
