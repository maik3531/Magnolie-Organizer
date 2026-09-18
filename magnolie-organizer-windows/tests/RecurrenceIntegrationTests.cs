using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RecurrenceIntegrationTests
{
    internal static void Probe()
    {
        using var input = JsonDocument.Parse(Console.In.ReadToEnd());
        var output = new List<object>();
        foreach (var test in input.RootElement.EnumerateArray())
        {
            var text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + string.Join("\r\n", test.GetProperty("components").EnumerateArray().SelectMany(component => component.EnumerateArray().Select(line => line.GetString()))) + "\r\nEND:VCALENDAR\r\n";
            var zone = CalendarRecurrence.Zone(test.GetProperty("zone").GetString()!);
            var imported = ExchangeCodec.ParseIcs(text, "fixture", zone);
            var task = test.TryGetProperty("task", out var taskValue) && taskValue.GetBoolean();
            var items = task ? imported.Aufgaben : imported.Termine;
            if (test.TryGetProperty("additionalCalendars", out var calendars))
            {
                var index = 0;
                foreach (var calendar in calendars.EnumerateArray())
                {
                    var extraText = "BEGIN:VCALENDAR\nVERSION:2.0\n" + string.Join("\n", calendar.EnumerateArray().SelectMany(block => block.EnumerateArray().Select(line => line.GetString()))) + "\nEND:VCALENDAR";
                    var extra = ExchangeCodec.ParseIcs(extraText, "fixture-" + index++, zone);
                    foreach (var value in task ? extra.Aufgaben : extra.Termine) items.Add(value!.DeepClone());
                }
            }
            using var data = JsonDocument.Parse(items.ToJsonString());
            var lower = DateTime.Parse(test.GetProperty("lower").GetString()!, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
            var upper = DateTime.Parse(test.GetProperty("upper").GetString()!, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
            if (test.TryGetProperty("expectedError", out _))
            {
                string? error = null;
                try { foreach (var item in data.RootElement.EnumerateArray()) _ = CalendarRecurrence.Expand(item, lower, upper, zone, task); }
                catch (Exception failure) when (failure is InvalidDataException or TimeZoneNotFoundException) { error = failure.Message; }
                TestAssert.That(error is not null && items.Count > 0, "Unresolved source was lost or returned success.");
                output.Add(new { name = test.GetProperty("name").GetString(), error, items });
                continue;
            }
            var occurrences = data.RootElement.EnumerateArray().SelectMany(item => CalendarRecurrence.Expand(item, lower, upper, zone, task)).ToArray();
            var exported = ExchangeCodec.WriteIcs(task ? "ics-aufgaben" : "ics-termine", data.RootElement);
            TestAssert.That(exported.Skipped == 0, "Recurrence export skipped an item.");
            var roundtrip = ExchangeCodec.ParseIcs(exported.Text, "fixture", zone);
            var roundtripItems = task ? roundtrip.Aufgaben : roundtrip.Termine;
            if (test.TryGetProperty("roundtrip", out _))
            {
                using var reimported = JsonDocument.Parse(roundtripItems.ToJsonString());
                var again = reimported.RootElement.EnumerateArray().SelectMany(item => CalendarRecurrence.Expand(item, lower, upper, zone, task));
                TestAssert.That(again.OrderBy(v => v.Start).SequenceEqual(occurrences.OrderBy(v => v.Start)), "Own ICS roundtrip changed recurrence.");
            }
            var values = occurrences.Select(value => value.Start.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture) + "/" + value.End.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture)).Order().ToArray();
            if (test.TryGetProperty("oracle", out _))
            {
                output.Add(new { name = test.GetProperty("name").GetString(), values, items });
                continue;
            }
            if (test.TryGetProperty("expectedTitles", out var expectedTitles))
            {
                var projected = data.RootElement.EnumerateArray().SelectMany(item => CalendarRecurrence.Expand(item, lower, upper, zone, task).Select(value => (
                    value.Start, Summary: value.Summary is null ? item.GetProperty("titel").GetString() : CalendarRecurrence.TextValue(value.Summary),
                    Location: CalendarRecurrence.TextValue(value.Location ?? CalendarRecurrence.Properties(item).FirstOrDefault(p => p.Name == "LOCATION").Value ?? "")))).OrderBy(v => v.Start).ToArray();
                TestAssert.That(projected.Select(v => v.Summary).SequenceEqual(expectedTitles.EnumerateArray().Select(v => v.GetString())), "Native RANGE summary inheritance.");
                TestAssert.That(projected.Select(v => v.Location).SequenceEqual(test.GetProperty("expectedLocations").EnumerateArray().Select(v => v.GetString())), "Native RANGE location inheritance.");
            }
            var partitioned = new List<CalendarOccurrence>();
            for (var from = lower; from <= upper; from = from.AddDays(2))
                foreach (var item in data.RootElement.EnumerateArray()) partitioned.AddRange(CalendarRecurrence.Expand(item, from, from.AddDays(2).AddSeconds(-1) < upper ? from.AddDays(2).AddSeconds(-1) : upper, zone, task));
            TestAssert.That(partitioned.OrderBy(value => value.Start).SequenceEqual(occurrences.OrderBy(value => value.Start)), "Native window partition changed COUNT.");
            var selected = items.DeepClone().AsArray();
            foreach (var item in selected.OfType<JsonObject>()) { item["erinnern"] = true; item["standardErinnerung"] = true; }
            var root = new JsonObject { [task ? "aufgaben" : "termine"] = selected, ["einstellungen"] = new JsonObject {
                ["regional"] = new JsonObject { ["timeZone"] = zone.Id }, ["erinnerung"] = new JsonObject { ["vorlauf"] = 0 } } };
            var snapshot = ReminderScheduler.SelectRuntimeData(root.ToJsonString());
            using var scheduled = JsonDocument.Parse(snapshot);
            var reminders = new HashSet<string>();
            foreach (var occurrence in occurrences)
            {
                var when = task ? occurrence.EndUtc : occurrence.AllDay ? CalendarRecurrence.ToUtc(occurrence.Start.AddHours(8), zone) : occurrence.StartUtc;
                var titles = new Dictionary<string, string>();
                var due = task ? ReminderScheduler.DueTasks(scheduled.RootElement, default, when, titles) : ReminderScheduler.DueAppointments(snapshot, when, titles);
                if (occurrence.Summary is not null) TestAssert.That(titles.Values.Contains(CalendarRecurrence.TextValue(occurrence.Summary)), "Reminder snapshot lost RANGE summary.");
                TestAssert.That(due.Any(value => value.Start == (task ? occurrence.End : occurrence.AllDay ? occurrence.Start.AddHours(8) : occurrence.Start)), "Native scheduler lost " + test.GetProperty("name").GetString());
                foreach (var value in due) reminders.Add(value.Key);
                if (test.TryGetProperty("endAlarm", out _))
                {
                    var endAlarm = ReminderScheduler.DueAppointments(snapshot, occurrence.EndUtc.AddMinutes(-30));
                    TestAssert.That(endAlarm.Any(value => value.Key.EndsWith(":alarm-end-30", StringComparison.Ordinal) && value.Due == occurrence.End.AddMinutes(-30)), "Long PERIOD END alarm was outside the start window.");
                }
            }
            output.Add(new { name = test.GetProperty("name").GetString(), values, items, exported = exported.Text, roundtripItems, reminderCount = reminders.Count });
        }
        Console.WriteLine(JsonSerializer.Serialize(output));
    }
}
