using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NextcloudIcsBirthdayTests
{
    public static Task RunAsync()
    {
        foreach (var (start, end, years, rule, expected) in new (string, string, string, string, string?)[]
        {
            ("19850417", "19850418", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:0\r\nX-NEXTCLOUD-BC-YEAR:1985", "FREQ=YEARLY", "1985-04-17"),
            ("19700417", "19700418", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1", "FREQ=YEARLY", "--04-17"),
            ("19720229", "19720301", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1", "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1", "--02-29"),
            ("19880417", "19880418", "X-NEXTCLOUD-BC-UNKNOWN-YEAR:1\r\nX-NEXTCLOUD-BC-YEAR:1988", "FREQ=YEARLY", null),
        })
        {
            var raw = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nCOLOR:gold\r\nBEGIN:VEVENT\r\nUID:provider-birthday\r\nSUMMARY:Example\r\n" +
                $"DTSTART;VALUE=DATE:{start}\r\nDTEND;VALUE=DATE:{end}\r\nRRULE:{rule}\r\n" +
                $"X-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\n{years}\r\nCOLOR:turquoise\r\nX-TEST-PROVIDER:retained\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
            var imported = ExchangeCodec.ParseIcs(raw, "provider-source");
            if (expected is null)
            {
                TestAssert.That(imported.Jahrestage.Count == 0 && imported.Termine.Count == 1, "Conflicting markers changed the event type.");
                continue;
            }
            TestAssert.That(imported.Termine.Count == 0 && imported.Jahrestage.Count == 1, $"Nextcloud birthday stayed a VEVENT: {start}");
            var item = imported.Jahrestage[0]!;
            TestAssert.That(item["datum"]?.GetValue<string>() == expected && item["typ"]?.GetValue<string>() == "birthday" &&
                item["uid"]?.GetValue<string>() == "provider-birthday" && item["icsQuelleId"]?.GetValue<string>() == "provider-source" &&
                item["akzentFarbe"]?.GetValue<string>() == "#40e0d0", "Birthday date, type, source or colour changed.");
            using var document = JsonDocument.Parse(imported.Jahrestage.ToJsonString());
            var saved = ExchangeCodec.WriteIcs("ics-jahrestage", document.RootElement).Text;
            TestAssert.That(saved.Split("\r\n").Where(line => line.StartsWith("RRULE:")).SequenceEqual(new[] { $"RRULE:{rule}" }),
                "The recurrence changed on export.");
            TestAssert.That(saved.Contains($"DTSTART;VALUE=DATE:{start}") && saved.Contains($"DTEND;VALUE=DATE:{end}"),
                "The original interval did not round-trip.");
            TestAssert.That(saved.Contains("COLOR:gold") && saved.Contains("COLOR:turquoise") && saved.Contains("X-TEST-PROVIDER:retained"),
                "Raw properties were lost.");
            TestAssert.That(ExchangeCodec.ParseIcs(saved).Jahrestage[0]?["datum"]?.GetValue<string>() == expected,
                "The exported birthday date did not round-trip.");
            item["datum"] = "--07-12";
            using var editedDocument = JsonDocument.Parse(imported.Jahrestage.ToJsonString());
            var edited = ExchangeCodec.WriteIcs("ics-jahrestage", editedDocument.RootElement).Text;
            TestAssert.That(!edited.Contains("X-NEXTCLOUD-BC-UNKNOWN-YEAR:") && edited.Contains("X-TEST-PROVIDER:retained") &&
                ExchangeCodec.ParseIcs(edited).Jahrestage[0]?["datum"]?.GetValue<string>() == "--07-12",
                "An edited birthday revived the old anchor or lost unrelated metadata.");
        }
        foreach (var properties in new[] { "", "X-NEXTCLOUD-BC-FIELD-TYPE:DEATHDATE", "X-NEXTCLOUD-BC-FIELD-TYPE:ANNIVERSARY",
            "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\nX-NEXTCLOUD-BC-FIELD-TYPE:DEATHDATE",
            "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\nX-NEXTCLOUD-BC-YEAR:1986",
            "X-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\nEXDATE;VALUE=DATE:20260417",
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-P1D\r\nX-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\nEND:VALARM" })
        {
            var raw = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:control\r\nSUMMARY:Birthday-looking title\r\n" +
                $"DTSTART;VALUE=DATE:19850417\r\nRRULE:FREQ=YEARLY\r\n{properties}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
            var parsed = ExchangeCodec.ParseIcs(raw);
            TestAssert.That(parsed.Jahrestage.Count == 0 && parsed.Termine.Count == 1, $"Control was reclassified: {properties}");
        }
        const string series = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:series\r\nSUMMARY:Master\r\n" +
            "DTSTART;VALUE=DATE:19850417\r\nRRULE:FREQ=YEARLY\r\nX-NEXTCLOUD-BC-FIELD-TYPE:BDAY\r\nEND:VEVENT\r\n" +
            "BEGIN:VEVENT\r\nUID:series\r\nSUMMARY:Moved\r\nRECURRENCE-ID;VALUE=DATE:20260417\r\n" +
            "DTSTART;VALUE=DATE:20260418\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var withException = ExchangeCodec.ParseIcs(series);
        TestAssert.That(withException.Jahrestage.Count == 0 && withException.Termine.Count == 2, "The master was detached from its override.");
        return Task.CompletedTask;
    }
}
