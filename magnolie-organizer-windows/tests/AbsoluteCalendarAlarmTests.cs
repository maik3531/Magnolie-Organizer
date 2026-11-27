using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class AbsoluteCalendarAlarmTests
{
    internal static Task RunAsync()
    {
        var root = Directory.CreateTempSubdirectory("magnolie-absolute-alarms-");
        try
        {
            var failures = new List<string>();
            var now = new DateTime(2026, 11, 27, 10, 30, 17, DateTimeKind.Utc);
            foreach (var task in new[] { false, true })
            foreach (var (mode, day, recurrence, trigger) in new[] {
                ("absolute", "20261129", "", "TRIGGER;VALUE=DATE-TIME:20261127T103017Z"),
                ("series-outside-window", "20260801", "\nRRULE:FREQ=DAILY;COUNT=4", "TRIGGER;VALUE=DATE-TIME:20261127T103017Z"),
                ("relative-start", "20261127", "", "TRIGGER:-PT2H"),
                ("relative-end", "20261127", "", "TRIGGER;RELATED=END:-PT3H")
            })
            {
                var kind = task ? "VTODO" : "VEVENT";
                var data = Import(task,
                    $"DTSTART:{day}T123017Z\nDURATION:PT1H{recurrence}\n" +
                    $"BEGIN:VALARM\nACTION:DISPLAY\n{trigger}\nEND:VALARM").ToJsonString();
                foreach (var (projection, source) in new[] {
                    ("direct", data),
                    ("runtime", ReminderScheduler.SelectRuntimeData(data)),
                    ("background", ReminderScheduler.SelectBackgroundData(data)!)
                })
                {
                    var label = $"{kind}-{mode}-{projection}";
                    var path = Path.Combine(root.FullName, label + ".json");
                    var notices = new List<ReminderNotice>();
                    using (var scheduler = new ReminderScheduler(path, notices.Add))
                    {
                        scheduler.UpdateData(source);
                        scheduler.RunOnce(now.AddSeconds(-1));
                        if (notices.Count != 0) failures.Add($"{label}: fired before exact trigger.");
                        scheduler.RunOnce(now);
                        if (notices.Count != 1 || !File.Exists(path))
                            failures.Add($"{label}: expected one persisted notice, received {notices.Count}.");
                    }
                    notices.Clear();
                    using var restarted = new ReminderScheduler(path, notices.Add);
                    restarted.UpdateData(source);
                    restarted.RunOnce(now.AddMinutes(1));
                    if (notices.Count != 0) failures.Add($"{label}: repeated after restart.");
                }
            }
            TestAssert.That(failures.Count == 0, string.Join(Environment.NewLine, failures));
            CheckGuards(root.FullName, now);
        }
        finally { root.Delete(recursive: true); }
        return Task.CompletedTask;
    }

    private static JsonObject Import(bool task, string body)
    {
        var kind = task ? "VTODO" : "VEVENT";
        var imported = ExchangeCodec.ParseIcs(
            $"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:{kind}\nUID:fixture\nSUMMARY:Fixture\n{body}\nEND:{kind}\nEND:VCALENDAR",
            "fixture", TimeZoneInfo.Utc);
        TestAssert.That((task ? imported.Aufgaben : imported.Termine).Count == 1, $"{kind}: native import lost the item.");
        return new JsonObject
        {
            ["termine"] = imported.Termine,
            ["aufgaben"] = imported.Aufgaben,
            ["einstellungen"] = JsonNode.Parse("""
                {"regional":{"timeZone":"UTC"},"sicherheit":{"erinnernTrotzKennwort":true},
                 "erinnerung":{"an":true,"vorlauf":0,"verpasste":true}}
                """)
        };
    }

    private static void CheckGuards(string root, DateTime now)
    {
        const string utc = "20261127T103017Z", later = "20261127T103041Z";
        const string anchor = "DTSTART:20261129T123000Z\nDURATION:PT1H";
        static string Alarm(string utc, string action = "DISPLAY") =>
            $"\nBEGIN:VALARM\nACTION:{action}\nTRIGGER;VALUE=DATE-TIME:{utc}\nEND:VALARM";
        foreach (var task in new[] { false, true })
        {
            foreach (var (label, line) in new[] {
                ("cancelled", "\nSTATUS:CANCELLED" + Alarm(utc)),
                ("different-action", Alarm(utc, "EMAIL")),
                ("invalid-local", Alarm("20261127T103017")),
                ("private", Alarm(utc)),
            }.Concat(task ? [("completed", "\nSTATUS:COMPLETED" + Alarm(utc))] : []))
            {
                var book = Import(task, anchor + line);
                if (label == "private") book[task ? "aufgaben" : "termine"]![0]!["vertraulich"] = true;
                var notices = new List<ReminderNotice>();
                using var scheduler = new ReminderScheduler(Path.Combine(root, $"{task}-{label}.json"), notices.Add);
                scheduler.UpdateData(ReminderScheduler.SelectBackgroundData(book.ToJsonString())!);
                scheduler.RunOnce(now);
                TestAssert.That(notices.Count == 0, $"{task}/{label}: an excluded alarm fired.");
            }

            var timed = Import(task, (task ? "" : anchor) + Alarm(utc) + Alarm(utc) + Alarm(later));
            var noticesInZone = new List<ReminderNotice>();
            using var timedScheduler = new ReminderScheduler(Path.Combine(root, $"{task}-two-seconds.json"), noticesInZone.Add);
            timed["einstellungen"]!["regional"]!["timeZone"] = "Europe/Berlin";
            timedScheduler.UpdateData(ReminderScheduler.SelectBackgroundData(timed.ToJsonString())!);
            timedScheduler.RunOnce(now);
            TestAssert.That(noticesInZone.Count == 1, "Duplicate absolute triggers or undated task scheduled incorrectly.");
            timed["einstellungen"]!["regional"]!["timeZone"] = "UTC";
            timedScheduler.UpdateData(timed.ToJsonString());
            timedScheduler.RunOnce(now.AddSeconds(24));
            TestAssert.That(noticesInZone.Count == 2, "Different seconds collapsed, or changing zone repeated a reported alarm.");
        }
    }
}
