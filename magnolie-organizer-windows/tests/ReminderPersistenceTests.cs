using System.Text.Json;
using System.Text.Json.Nodes;
using System.Globalization;
using System.Diagnostics;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ReminderPersistenceTests
{
    internal static Task RunAsync()
    {
        NativeRecurrenceRegressionTests.Run();
        RecurrenceRegressions();
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-reminder-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var state = Path.Combine(root, "erinnerungen.json");
            const string data = """
                {"einstellungen":{"erinnerung":{"an":true,"vorlauf":15,"verpasste":true,"art":"notification"}},
                 "termine":[{"id":"auszeit","datum":"2026-08-12","zeit":"09:00","titel":"Nach Neustart","standardErinnerung":true}]}
                """;
            var firstNotices = new List<ReminderNotice>();
            using (var first = new ReminderScheduler(state, firstNotices.Add))
            {
                first.UpdateData(data);
                first.RunOnce(new DateTime(2026, 8, 12, 10, 0, 0, DateTimeKind.Local));
            }
            TestAssert.That(firstNotices.Count == 1 && File.Exists(state),
                "Der während der Auszeit verpasste Termin wurde beim Login nicht genau einmal gemeldet.");

            var secondNotices = new List<ReminderNotice>();
            using (var second = new ReminderScheduler(state, secondNotices.Add))
            {
                second.UpdateData(data);
                second.RunOnce(new DateTime(2026, 8, 12, 10, 1, 0, DateTimeKind.Local));
            }
            TestAssert.That(secondNotices.Count == 0, "Der persistierte Termin wurde nach Prozessneustart doppelt gemeldet.");

            const string protectedData = """
                {"einstellungen":{"sicherheit":{"erinnernTrotzKennwort":true,"vertraulicheErinnerungen":false},
                  "erinnerung":{"an":true,"verpasste":true}},
                 "termine":[{"id":"offen","datum":"2026-08-12","zeit":"09:00","titel":"Erlaubt","notiz":"Geheim Termin"},
                              {"id":"privat","datum":"2026-08-12","zeit":"09:00","titel":"Privat","vertraulich":true},
                              {"id":"alarm","datum":"2026-08-13","zeit":"09:00","endDatum":"2026-08-13","endZeit":"10:00","titel":"Alarm",
                               "alarme":[{"offsetMinuten":60,"aktiviert":true,"related":"END","aktion":"display","geheim":"Nein"}]}],
                  "aufgaben":[{"id":"a1","titel":"Aufgabe","faellig":"2026-08-12","erinnern":true,"notiz":"Geheim Aufgabe"}],
                  "jahrestage":[{"id":"j1","name":"Anna","datum":"1980-08-12","typ":"Birthday"}],
                  "kontakte":[{"name":"Darf nicht hinaus"}],"notizen":[{"text":"Geheim"}]}
                """;
            var selected = ReminderScheduler.SelectBackgroundData(protectedData)!;
            using (var selectedDocument = JsonDocument.Parse(selected))
            {
                var selectedRoot = selectedDocument.RootElement;
                var selectedAlarm = selectedRoot.GetProperty("termine")[1].GetProperty("alarme")[0];
                TestAssert.That(selectedRoot.GetProperty("termine").GetArrayLength() == 2 &&
                                selectedRoot.GetProperty("termine")[0].GetProperty("id").GetString() == "offen" &&
                                  selectedRoot.GetProperty("aufgaben").GetArrayLength() == 1 &&
                                  !selectedRoot.GetProperty("termine")[0].TryGetProperty("notiz", out _) &&
                                  selectedRoot.GetProperty("termine")[1].GetProperty("endZeit").GetString() == "10:00" &&
                                  selectedAlarm.GetProperty("offsetMinuten").GetInt32() == 60 &&
                                  !selectedAlarm.TryGetProperty("geheim", out _) &&
                                  selectedRoot.GetProperty("einstellungen").GetProperty("erinnerung")
                                      .GetProperty("an").GetBoolean() &&
                                  selectedRoot.GetProperty("jahrestage")[0].GetProperty("typ").GetString() == "Birthday" &&
                                  !selectedRoot.GetProperty("aufgaben")[0].TryGetProperty("notiz", out _) &&
                                 !selectedRoot.TryGetProperty("kontakte", out _) && !selectedRoot.TryGetProperty("notizen", out _) &&
                                 !selectedRoot.TryGetProperty("personen", out _),
                    "Die Kennwort-Reminderdatei enthält nicht erlaubte oder verliert erlaubte Daten.");
            }
            TestAssert.That(ReminderScheduler.SelectBackgroundData(protectedData.Replace(
                "\"erinnernTrotzKennwort\":true", "\"erinnernTrotzKennwort\":false", StringComparison.Ordinal)) is null,
                "Kennwortgeschützte Erinnerungsdaten wurden ohne ausdrückliche Erlaubnis freigegeben.");

            const string spring = """
                {"einstellungen":{"erinnerung":{"vorlauf":15,"verpasste":true}},
                 "termine":[{"id":"dst","datum":"2026-03-29","zeit":"02:30","titel":"DST"}]}
                """;
            var springEarly = ReminderScheduler.DueAppointments(spring, new DateTime(2026, 3, 29, 3, 5, 0));
            var springDue = ReminderScheduler.DueAppointments(spring, new DateTime(2026, 3, 29, 3, 15, 0));
            var autumnFirst = ReminderScheduler.DueAppointments(spring.Replace("2026-03-29", "2026-10-25", StringComparison.Ordinal),
                new DateTime(2026, 10, 25, 2, 35, 0));
            var autumnSecond = ReminderScheduler.DueAppointments(spring.Replace("2026-03-29", "2026-10-25", StringComparison.Ordinal),
                new DateTime(2026, 10, 25, 2, 55, 0));
            TestAssert.That(springEarly.Count == 0 && springDue.Count == 1 && autumnFirst.Single().Key == autumnSecond.Single().Key,
                "Lokale Uhr- oder DST-Grenzen erzeugen verlorene oder doppelte Vorkommensschlüssel.");

            const string structured = """
                {"einstellungen":{"erinnerung":{"vorlauf":15,"verpasste":true}},
                 "termine":[{"id":"mehrfach","datum":"2026-08-13","zeit":"09:00","endZeit":"10:30","titel":"Mehrfach",
                   "standardErinnerung":false,"individuelleErinnerungTage":1,
                   "alarme":[{"offsetMinuten":1440,"aktiviert":true,"related":"START","aktion":"display"},
                              {"offsetMinuten":120,"aktiviert":true,"related":"START","aktion":"display"},
                              {"offsetMinuten":15,"aktiviert":true,"related":"START","aktion":"display"},
                              {"offsetMinuten":60,"aktiviert":true,"related":"END","aktion":"display"},
                              {"offsetMinuten":30,"aktiviert":false,"related":"START","aktion":"display"},
                              {"offsetMinuten":45,"aktiviert":true,"related":"START","aktion":"audio"}]}]}
                """;
            var dayDue = ReminderScheduler.DueAppointments(structured, new DateTime(2026, 8, 12, 9, 0, 0));
            var hourDue = ReminderScheduler.DueAppointments(structured, new DateTime(2026, 8, 13, 7, 0, 0));
            var minuteDue = ReminderScheduler.DueAppointments(structured, new DateTime(2026, 8, 13, 8, 45, 0));
            var endDue = ReminderScheduler.DueAppointments(structured, new DateTime(2026, 8, 13, 9, 30, 0));
            const string structuredDay = """
                {"einstellungen":{"erinnerung":{"verpasste":true}},"termine":[{"id":"tag","datum":"2026-08-23","zeit":"09:00",
                 "standardErinnerung":false,"individuelleErinnerungTage":1,
                 "alarme":[{"offsetMinuten":14400,"aktiviert":true,"related":"START","aktion":"display"}]}]}
                """;
            var structuredDayDue = ReminderScheduler.DueAppointments(structuredDay, new DateTime(2026, 8, 13, 9, 0, 0));
            TestAssert.That(dayDue.Count == 1 && dayDue[0].Key.EndsWith(":individuell", StringComparison.Ordinal) &&
                            hourDue.Count == 2 && minuteDue.Count == 3 && endDue.Count == 4 &&
                            endDue.Any(item => item.Due == new DateTime(2026, 8, 13, 9, 30, 0) &&
                                               item.Key.EndsWith(":alarm-end-60", StringComparison.Ordinal)) &&
                            structuredDayDue.Count == 1 &&
                            structuredDayDue[0].Key.EndsWith(":alarm-start-14400", StringComparison.Ordinal),
                "Strukturierte Minuten-, Stunden-, Tages- oder END-Alarme werden nicht korrekt geplant oder dedupliziert.");
            const string recurrenceChanges = """
                {"einstellungen":{"erinnerung":{"vorlauf":15,"verpasste":true}},
                 "termine":[{"id":"serie-ausnahmen","datum":"2026-08-03","zeit":"09:00","titel":"Serie",
                   "wiederholung":{"art":"weekly","intervall":1},"icsAusnahmen":["2026-08-10"],
                   "icsZusatzDaten":["2026-08-11"],"icsZusatzTermine":[{"datum":"2026-08-12","zeit":"15:30"}]}]}
                """;
            var excludedDue = ReminderScheduler.DueAppointments(recurrenceChanges, new DateTime(2026, 8, 10, 8, 45, 0));
            var dateAdditionDue = ReminderScheduler.DueAppointments(recurrenceChanges, new DateTime(2026, 8, 11, 8, 45, 0));
            var timedAdditionDue = ReminderScheduler.DueAppointments(recurrenceChanges, new DateTime(2026, 8, 12, 15, 15, 0));
            var selectedChanges = ReminderScheduler.SelectRuntimeData(recurrenceChanges);
            TestAssert.That(excludedDue.Count == 0 && dateAdditionDue.Any(item => item.Start == new DateTime(2026, 8, 11, 9, 0, 0)) &&
                timedAdditionDue.Any(item => item.Start == new DateTime(2026, 8, 12, 15, 30, 0)) &&
                selectedChanges.Contains("icsAusnahmen", StringComparison.Ordinal) && selectedChanges.Contains("icsZusatzTermine", StringComparison.Ordinal),
                "Native Reminder ignorieren strukturierte Serienausnahmen oder Zusatztermine.");
            Console.WriteLine("         REMINDER-PERSIST-OK REMINDER-PROTECTED-OK REMINDER-DST-OK REMINDER-ALARMS-OK");
            return Task.CompletedTask;
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static void RecurrenceRegressions()
    {
        static string Calendar(string start, string rule, string extra = "", string end = "") =>
            $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:series\r\nSUMMARY:Series\r\nDTSTART:{start}\r\n" +
            (end.Length > 0 ? "DTEND:" + end + "\r\n" : "DURATION:PT1H\r\n") + "RRULE:" + rule + "\r\n" + extra + "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        static CalendarOccurrence[] Expand(string text, string from, string through)
        {
            var parsed = ExchangeCodec.ParseIcs(text, timeZone: TimeZoneInfo.Utc);
            using var saved = JsonDocument.Parse(parsed.Termine.ToJsonString());
            return saved.RootElement.EnumerateArray().SelectMany(item => CalendarRecurrence.Expand(item,
                DateTime.Parse(from, CultureInfo.InvariantCulture), DateTime.Parse(through, CultureInfo.InvariantCulture), TimeZoneInfo.Utc)).OrderBy(value => value.Start).ToArray();
        }
        foreach (var anchor in new[] { "19980105T090000", "20210301T090000" })
        {
            var text = Calendar(anchor, "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;WKST=MO");
            for (var round = 0; round < 2; round++)
            {
                var occurrences = Expand(text, "2026-09-01", "2026-09-30T23:59:59");
                TestAssert.That(occurrences.Select(value => value.Start.ToString("yyyy-MM-dd HH:mm")).SequenceEqual(["2026-09-07 09:00", "2026-09-21 09:00"]), "Historical biweekly series changed phase or ended prematurely.");
                using var saved = JsonDocument.Parse(ExchangeCodec.ParseIcs(text).Termine.ToJsonString());
                text = ExchangeCodec.WriteIcs("ics-termine", saved.RootElement).Text;
            }
        }
        foreach (var (start, rule, from, through, expected) in new[] {
            ("20260901T090000", "FREQ=DAILY;INTERVAL=2;COUNT=5", "2026-09-01", "2026-09-15", new[] { "2026-09-01", "2026-09-03", "2026-09-05", "2026-09-07", "2026-09-09" }),
            ("20260901T090000", "FREQ=DAILY;UNTIL=20260907T080000", "2026-09-07", "2026-09-08", Array.Empty<string>()),
            ("20260907T090000", "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=5", "2026-09-07", "2026-09-30", new[] { "2026-09-07", "2026-09-09", "2026-09-14", "2026-09-16", "2026-09-21" }),
            ("20260131T090000", "FREQ=MONTHLY;COUNT=4", "2026-02-01", "2026-08-01", new[] { "2026-03-31", "2026-05-31", "2026-07-31" }),
            ("20240101T090000", "FREQ=MONTHLY;INTERVAL=2;BYDAY=1MO", "2026-09-01", "2026-12-01", new[] { "2026-09-07", "2026-11-02" }),
            ("20240126T090000", "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", "2026-09-01", "2026-10-31T23:59:59", new[] { "2026-09-30", "2026-10-30" }),
            ("20240229T090000", "FREQ=YEARLY;COUNT=3", "2025-01-01", "2033-01-01", new[] { "2028-02-29", "2032-02-29" }),
            ("19980105T090000", "FREQ=YEARLY;INTERVAL=2", "2026-01-01", "2029-01-01", new[] { "2026-01-05", "2028-01-05" }) })
        {
            var actual = Expand(Calendar(start, rule), from, through).Select(value => value.Start.ToString("yyyy-MM-dd")).ToArray();
            TestAssert.That(actual.SequenceEqual(expected), $"RFC recurrence {rule}: expected {string.Join(',', expected)}, actual {string.Join(',', actual)}");
        }
        var timed = Calendar("20260901T090000", "FREQ=DAILY;COUNT=1", "RDATE:20260908T090000,20260908T150000,20260908T180000\r\nEXDATE:20260908T150000");
        TestAssert.That(Expand(timed, "2026-09-08", "2026-09-09").Select(value => value.Start.Hour).SequenceEqual([9, 18]), "Timed EXDATE removed the wrong same-day RDATE instances.");
        var moved = Calendar("19980105T090000", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO").Replace("END:VCALENDAR", "BEGIN:VEVENT\r\nUID:series\r\nRECURRENCE-ID:20260907T090000\r\nDTSTART:20260907T110000\r\nDTEND:20260907T120000\r\nSUMMARY:Moved\r\nEND:VEVENT\r\nEND:VCALENDAR", StringComparison.Ordinal);
        TestAssert.That(Expand(moved, "2026-09-07", "2026-09-08").Select(value => value.Start.Hour).SequenceEqual([11]), "Override and original recurrence were both expanded.");
        var cancelled = moved.Replace("SUMMARY:Moved", "SUMMARY:Moved\r\nSTATUS:CANCELLED", StringComparison.Ordinal);
        TestAssert.That(Expand(cancelled, "2026-09-07", "2026-09-08").Length == 0, "Cancelled recurrence instance still appeared.");
        var range = moved.Replace("RECURRENCE-ID:", "RECURRENCE-ID;RANGE=THISANDFUTURE:", StringComparison.Ordinal);
        TestAssert.That(Expand(range, "2026-09-07", "2026-10-01").Select(value => value.Start.ToString("yyyy-MM-dd HH:mm")).SequenceEqual(["2026-09-07 11:00", "2026-09-21 11:00"]),
            "THISANDFUTURE did not shift subsequent instances or duplicated the first override.");
        foreach (var (rule, expected) in new[] { ("FREQ=HOURLY;INTERVAL=2;COUNT=3", new[] { "09:00:00", "11:00:00", "13:00:00" }),
            ("FREQ=MINUTELY;INTERVAL=20;COUNT=3", new[] { "09:00:00", "09:20:00", "09:40:00" }),
            ("FREQ=SECONDLY;INTERVAL=20;COUNT=3", new[] { "09:00:00", "09:00:20", "09:00:40" }) })
            TestAssert.That(Expand(Calendar("19980105T090000", rule), "1998-01-05", "1998-01-06").Select(value => value.Start.ToString("HH:mm:ss")).SequenceEqual(expected),
                "Subdaily interval/count expansion was not exact: " + rule);
        foreach (var (duration, expectedEnd) in new[] { ("P1D", "2026-03-08 13:00"), ("PT24H", "2026-03-08 14:00") })
        {
            var source = "BEGIN:VEVENT\nUID:dst-duration\nDTSTART;TZID=America/New_York:20260307T090000\nDURATION:" + duration + "\nEND:VEVENT\n";
            TestAssert.That(Expand(source, "2026-03-07", "2026-03-09").Single().EndUtc.ToString("yyyy-MM-dd HH:mm") == expectedEnd,
                "Nominal days and exact hours were confused across a DST transition.");
        }
        var oldCount = Calendar("19980105T090000", "FREQ=DAILY;COUNT=100000");
        var clock = Stopwatch.StartNew();
        TestAssert.That(Expand(oldCount, "2026-09-07", "2026-09-08").Length == 1 && clock.Elapsed < TimeSpan.FromSeconds(3), "COUNT expansion scanned or truncated the old series incorrectly.");
        var midnight = """{"einstellungen":{"regional":{"timeZone":"UTC"},"erinnerung":{"vorlauf":0}},"termine":[{"uid":"midnight","datum":"2026-09-07","zeit":"00:00","titel":"Midnight"}]}""";
        TestAssert.That(ReminderScheduler.DueAppointments(midnight, new DateTime(2026,9,7,0,0,0,DateTimeKind.Utc)).Single().Start.Hour == 0, "Midnight was rejected as an invalid time.");
        var month = """{"termine":[{"uid":"month","datum":"2026-01-31","zeit":"09:00","wiederholung":{"art":"monthly"}}]}""";
        TestAssert.That(ReminderScheduler.DueAppointments(month, new DateTime(2026,3,31,9,0,0)).Any(value => value.Start.Day == 31), "Native month-end recurrence drifted to the previously clamped day.");
        var leap = month.Replace("2026-01-31", "2024-02-29", StringComparison.Ordinal).Replace("monthly", "yearly", StringComparison.Ordinal);
        TestAssert.That(ReminderScheduler.DueAppointments(leap, new DateTime(2028,2,29,9,0,0)).Any(value => value.Start.Day == 29), "Native leap-day recurrence did not recover its original anchor.");
        var newYork = """{"einstellungen":{"regional":{"timeZone":"America/New_York"},"erinnerung":{"vorlauf":0}},"termine":[{"id":"ny","datum":"2026-09-07","zeit":"10:00"}]}""";
        TestAssert.That(ReminderScheduler.DueAppointments(newYork, new DateTime(2026,9,7,13,59,0,DateTimeKind.Utc)).Count == 0 &&
            ReminderScheduler.DueAppointments(newYork, new DateTime(2026,9,7,14,0,0,DateTimeKind.Utc)).Single().Start.Hour == 10 &&
            ReminderScheduler.SelectRuntimeData(newYork).Contains("America/New_York", StringComparison.Ordinal), "Organizer zone was lost during native scheduling or projection.");
        var fold = ExchangeCodec.ParseIcs(Calendar("20261025T003000Z", "FREQ=DAILY;COUNT=1", "RDATE:20261025T013000Z"));
        var foldRoot = new JsonObject { ["termine"] = fold.Termine.DeepClone(), ["einstellungen"] = new JsonObject {
            ["regional"] = new JsonObject { ["timeZone"] = "Europe/Berlin" }, ["erinnerung"] = new JsonObject { ["vorlauf"] = 0 } } };
        var foldFirst = ReminderScheduler.DueAppointments(foldRoot.ToJsonString(), new DateTime(2026,10,25,0,30,0,DateTimeKind.Utc));
        var foldBoth = ReminderScheduler.DueAppointments(foldRoot.ToJsonString(), new DateTime(2026,10,25,1,30,0,DateTimeKind.Utc));
        TestAssert.That(foldFirst.Count == 1 && foldBoth.Count == 2 && foldBoth.Select(value => value.Key).Distinct().Count() == 2,
            "Two explicitly distinct UTC occurrences in a DST fold shared a reminder identity.");
        var scoped = JsonNode.Parse(midnight)!.AsObject(); var scopedEvents = scoped["termine"]!.AsArray();
        scopedEvents[0]!["icsQuelleId"] = "profile-A"; var other = scopedEvents[0]!.DeepClone(); other["icsQuelleId"] = "profile-B"; scopedEvents.Add(other);
        TestAssert.That(ReminderScheduler.DueAppointments(scoped.ToJsonString(), new DateTime(2026,9,7,0,0,0,DateTimeKind.Utc)).Select(value => value.Key).Distinct().Count() == 2,
            "Native reminder identities collided before frontend-assigned local IDs.");
        var dst = Calendar("20260301T090000", "FREQ=WEEKLY;COUNT=6").Replace("DTSTART:", "DTSTART;TZID=America/New_York:", StringComparison.Ordinal);
        var dstOccurrences = Expand(dst, "2026-03-01", "2026-03-16");
        TestAssert.That(dstOccurrences.Select(value => value.StartUtc.Hour).SequenceEqual([14,13,13]), "Imported zoned RRULE did not preserve source wall time across DST.");
        var todo = "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:task-series\nSUMMARY:Task\nDTSTART:19980105T090000\nDUE:19980105T170000\nRRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO\nX-MAGNOLIE-ERINNERUNG-AM-TAG:1\nEND:VTODO\nEND:VCALENDAR\n";
        var taskRoot = new JsonObject { ["aufgaben"] = ExchangeCodec.ParseIcs(todo).Aufgaben.DeepClone() };
        using var tasks = JsonDocument.Parse(taskRoot.ToJsonString()); using var settings = JsonDocument.Parse("{}");
        TestAssert.That(ReminderScheduler.DueTasks(tasks.RootElement, settings.RootElement, new DateTime(2026,9,7,16,59,0)).Count == 0 &&
            ReminderScheduler.DueTasks(tasks.RootElement, settings.RootElement, new DateTime(2026,9,7,17,0,0)).Single().Start.Hour == 17, "Recurring VTODO did not use its independent due time.");
    }
}
