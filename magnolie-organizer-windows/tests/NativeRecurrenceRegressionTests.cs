using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NativeRecurrenceRegressionTests
{
    internal static void Run()
    {
        var now = new DateTime(2026, 9, 8, 9, 0, 0, DateTimeKind.Utc);
        foreach (var lag in new[] { 7, 30 })
        foreach (var related in new[] { "START", "END" })
        foreach (var task in new[] { false, true })
        {
            var component = task ? "VTODO" : "VEVENT";
            var parsed = ExchangeCodec.ParseIcs($"BEGIN:{component}\nUID:follow-up\nSUMMARY:Follow-up\n" +
                "DTSTART:20260901T090000Z\nDURATION:PT1H\nBEGIN:VALARM\nACTION:DISPLAY\n" +
                $"TRIGGER;RELATED={related}:P{lag}D\nEND:VALARM\nEND:{component}", timeZone: TimeZoneInfo.Utc);
            var data = new JsonObject { [task ? "aufgaben" : "termine"] = (task ? parsed.Aufgaben : parsed.Termine).DeepClone(),
                ["einstellungen"] = new JsonObject { ["regional"] = new JsonObject { ["timeZone"] = "UTC" },
                    ["erinnerung"] = new JsonObject { ["vorlauf"] = 0 } } }.ToJsonString();
            var due = new DateTime(2026, 9, 1, related == "END" ? 10 : 9, 0, 0, DateTimeKind.Utc).AddDays(lag);
            using var document = JsonDocument.Parse(data);
            int DueCount(DateTime when) => task ? ReminderScheduler.DueTasks(document.RootElement,
                document.RootElement.GetProperty("einstellungen").GetProperty("erinnerung"), when).Count :
                ReminderScheduler.DueAppointments(data, when).Count;
            TestAssert.That(DueCount(due) == 1,
                "A supported after-event alarm was omitted.");
            TestAssert.That(DueCount(due.AddDays(1)) == 1,
                "A missed after-event alarm was omitted.");
            var state = Path.Combine(Path.GetTempPath(), "follow-up-" + Guid.NewGuid() + ".json");
            try
            {
                var notices = new List<ReminderNotice>();
                using (var scheduler = new ReminderScheduler(state, notices.Add))
                {
                    scheduler.UpdateData(ReminderScheduler.SelectRuntimeData(data));
                    scheduler.RunOnce(due);
                    scheduler.RunOnce(due.AddMinutes(1));
                }
                using (var scheduler = new ReminderScheduler(state, notices.Add))
                {
                    scheduler.UpdateData(ReminderScheduler.SelectRuntimeData(data));
                    scheduler.RunOnce(due.AddMinutes(2));
                }
                TestAssert.That(notices.Count == 1, "After-event reminder was lost or repeated after restart.");
            }
            finally { foreach (var file in new[] { state, AtomicStore.BackupPath(state), state + ".log" }) File.Delete(file); }
        }
        var period = JsonSerializer.SerializeToElement(new { icsRoundtrip = new[] {
            "DTSTART:20210101T090000Z", "DURATION:PT1H", "RDATE;VALUE=PERIOD:20260801T090000Z/PT960H", "EXRULE:FREQ=DAILY" } });
        foreach (var task in new[] { false, true })
            TestAssert.That(CalendarRecurrence.Expand(period, now.Date, now.Date.AddDays(1), TimeZoneInfo.Utc, task, true).Count == 0, "Old PERIOD escaped EXRULE.");

        var cancel = ExchangeCodec.ParseIcs("BEGIN:VCALENDAR\nVERSION:2.0\nMETHOD:CANCEL\nBEGIN:VEVENT\nUID:cancel\nRECURRENCE-ID:20260908T090000Z\nSTATUS:CANCELLED\nEND:VEVENT\nEND:VCALENDAR", timeZone: TimeZoneInfo.Utc);
        TestAssert.That(cancel.Termine.Count == 1 && CalendarRecurrence.Expand(JsonSerializer.SerializeToElement(cancel.Termine[0]), now.Date, now.Date.AddDays(1), TimeZoneInfo.Utc).Count == 0, "Cancellation became an appointment or was lost.");
        var unresolvedCancel = ExchangeCodec.ParseIcs("BEGIN:VCALENDAR\nVERSION:2.0\nMETHOD:CANCEL\nBEGIN:VEVENT\nUID:cancel-zone\nRECURRENCE-ID;TZID=Unknown/Regression:20260908T090000\nSTATUS:CANCELLED\nEND:VEVENT\nEND:VCALENDAR", timeZone: TimeZoneInfo.Utc);
        TestAssert.That(unresolvedCancel.Termine.Count == 1 && CalendarRecurrence.Expand(JsonSerializer.SerializeToElement(unresolvedCancel.Termine[0]), now.Date, now.Date.AddDays(1), TimeZoneInfo.Utc).Count == 0, "Unresolved cancellation identity was discarded.");

        foreach (var task in new[] { false, true })
        foreach (var rule in new[] { "FREQ=SECONDLY", "FREQ=INVALID", "FREQ=DAILY;INTERVAL=broken" })
        {
            var kind = task ? "VTODO" : "VEVENT";
            var parsed = ExchangeCodec.ParseIcs($"BEGIN:{kind}\nUID:bad\nSUMMARY:Bad\nDTSTART:20260901T090000Z\nDURATION:PT1S\nRRULE:{rule}\nEND:{kind}", timeZone: TimeZoneInfo.Utc);
            var items = (task ? parsed.Aufgaben : parsed.Termine).DeepClone().AsArray();
            items[0]!["erinnern"] = true;
            items.Add(new JsonObject { ["id"] = "healthy", ["titel"] = "Healthy", ["datum"] = "2026-09-08", ["zeit"] = "09:00", ["faellig"] = "2026-09-08", ["faelligZeit"] = "09:00", ["erinnern"] = true });
            var root = new JsonObject { [task ? "aufgaben" : "termine"] = items, ["einstellungen"] = new JsonObject { ["regional"] = new JsonObject { ["timeZone"] = "UTC" }, ["erinnerung"] = new JsonObject { ["vorlauf"] = 0 } } };
            var path = Path.Combine(Path.GetTempPath(), "native-reminder-" + Guid.NewGuid() + ".json");
            try
            {
                var notices = new List<ReminderNotice>();
                using (var scheduler = new ReminderScheduler(path, notices.Add))
                {
                    scheduler.UpdateData(ReminderScheduler.SelectRuntimeData(root.ToJsonString()));
                    scheduler.RunOnce(now);
                    scheduler.RunOnce(now.AddSeconds(30));
                    TestAssert.That(scheduler.LastError is not null && scheduler.LastError.Contains("bad"), "Failed series falsely reported success.");
                    TestAssert.That(scheduler.ExpansionErrors.Count == 1, "Missing per-item expansion status.");
                }
                using (var scheduler = new ReminderScheduler(path, notices.Add))
                { scheduler.UpdateData(ReminderScheduler.SelectRuntimeData(root.ToJsonString())); scheduler.RunOnce(now.AddMinutes(1)); }
                TestAssert.That(notices.Count(value => value.Body.Contains("Healthy")) == 1, "Healthy reminder suppressed or repeated after restart.");
                TestAssert.That(!File.ReadAllText(path).Contains("bad@"), "Failed series was acknowledged.");
            }
            finally { foreach (var file in new[] { path, AtomicStore.BackupPath(path), path + ".log" }) File.Delete(file); }
        }

        var old = JsonSerializer.SerializeToElement(new { icsRoundtrip = new[] { "DTSTART:19980101T090000Z", "DURATION:PT1S", "RRULE:FREQ=HOURLY;BYMINUTE=0;COUNT=1000000" } });
        var pending = false;
        try { CalendarRecurrence.Expand(old, now, now.AddHours(2), TimeZoneInfo.Utc); }
        catch (InvalidDataException error) { pending = error.Data["retryable"] is true; }
        TestAssert.That(pending, "Count budget did not retain retryable prefix progress.");
        var resumed = CalendarRecurrence.Expand(old, now, now.AddHours(2), TimeZoneInfo.Utc);
        TestAssert.That(resumed.Select(value => value.StartUtc).SequenceEqual(new[] { now, now.AddHours(1), now.AddHours(2) }), "Resumed prefix lost occurrences.");

        var boundary = new DateTime(2026, 2, 1, 9, 0, 0, DateTimeKind.Utc);
        var count = (long)(boundary - new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds + 61;
        var densePrefix = JsonSerializer.SerializeToElement(new { icsRoundtrip = new[] { "DTSTART:20260101T000000Z", "DURATION:PT0S",
            "RRULE:FREQ=MINUTELY;BYSECOND=" + string.Join(',', Enumerable.Range(0, 60)) + ";COUNT=" + count } });
        pending = false;
        try { CalendarRecurrence.Expand(densePrefix, boundary, boundary.AddMinutes(2), TimeZoneInfo.Utc); }
        catch (InvalidDataException error) { pending = error.Data["retryable"] is true; }
        TestAssert.That(pending, "Candidate-budget prefix was not retained.");
        var exact = CalendarRecurrence.Expand(densePrefix, boundary, boundary.AddMinutes(2), TimeZoneInfo.Utc);
        TestAssert.That(exact.Count == 61 && exact[^1].StartUtc == boundary.AddMinutes(1), "Mid-period budget retry changed COUNT.");
    }
}
