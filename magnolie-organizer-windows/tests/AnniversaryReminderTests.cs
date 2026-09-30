using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class AnniversaryReminderTests
{
    internal static Task RunAsync()
    {
        var language = NativeLocalization.Language;
        NativeLocalization.SetLanguage("en");
        try
        {
            using var data = JsonDocument.Parse("""
                {"jahrestage":[{"id":"birth","name":"Sample %s","datum":"--09-30","typ":"birthday"}],
                 "einstellungen":{"regional":{"timeZone":"Europe/Berlin"},
                    "erinnerung":{"an":true,"jahrestage":{"an":true}}}}
                """);
            var root = data.RootElement;
            var occurrence = new DateTime(2026, 9, 30, 8, 0, 0);
            var now = new DateTime(2026, 9, 30, 6, 0, 0, DateTimeKind.Utc);
            ReminderNotice Notice(DateTime instant) => ReminderScheduler.AnniversaryNotice(root,
                "jahrestag:birth@202609300800:am-tag", occurrence, instant, "notification", "system");
            var today = Notice(now);
            TestAssert.That(today.Title == "Birthday today" && today.Body == "Sample %s has a birthday today.",
                "Birthday notification lost its explanatory text or altered the person's name.");
            TestAssert.That(today.RequireDismissal && today.Kind == "notification", "Anniversaries must default to explicit dismissal.");
            NativeLocalization.SetLanguage("de");
            var german = Notice(now);
            TestAssert.That(german.Title == "Geburtstag heute" && german.Body == "Sample %s hat heute Geburtstag.",
                "Die deutsche Geburtstagserinnerung entspricht nicht dem verständlichen Linux-Text.");
            NativeLocalization.SetLanguage("en");
            TestAssert.That(Notice(now.AddDays(-1)).Body.EndsWith("tomorrow."), "Advance reminder says today.");
            TestAssert.That(Notice(now.AddDays(-2)).Body.EndsWith("the day after tomorrow."), "Two-day reminder is incorrect.");
            TestAssert.That(!Notice(now.AddDays(1)).Body.Contains("today"), "Missed birthday was presented as today's birthday.");
            using var automatic = JsonDocument.Parse(root.GetRawText().Replace("\"jahrestage\":{\"an\":true}",
                "\"jahrestage\":{\"an\":true,\"autoAusblenden\":true}"));
            var explicitAutomatic = ReminderScheduler.AnniversaryNotice(automatic.RootElement,
                "jahrestag:birth@202609300800:am-tag", occurrence, now, "notification", "magnolie");
            TestAssert.That(!explicitAutomatic.RequireDismissal, "Explicit automatic dismissal was ignored.");
            TestAssert.That(!new ReminderNotice("Appointment", "Ordinary appointment", "notification", "magnolie").RequireDismissal,
                "Anniversary default leaked into ordinary appointments.");
            using var projected = JsonDocument.Parse(ReminderScheduler.SelectRuntimeData(automatic.RootElement.GetRawText()));
            TestAssert.That(projected.RootElement.GetProperty("einstellungen").GetProperty("erinnerung")
                .GetProperty("jahrestage").GetProperty("autoAusblenden").GetBoolean(), "Background projection lost the independent setting.");
        }
        finally { NativeLocalization.SetLanguage(language); }
        return Task.CompletedTask;
    }
}
