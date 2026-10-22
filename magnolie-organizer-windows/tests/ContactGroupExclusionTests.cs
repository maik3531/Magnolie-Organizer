using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContactGroupExclusionTests
{
    internal static Task RunAsync()
    {
        var book = JsonNode.Parse("""
            {"kontakte":[
              {"id":"patient","kontaktAliase":{"ids":["old-patient"]},"vcardRoundtrip":["CATEGORIES:Work,PATIENTEN","X-OWNED:preserved"]},
              {"id":"colleague","vcardRoundtrip":["CATEGORIES:Colleagues"]}],
             "jahrestage":[
              {"id":"patient-birthday","uid":"patient-source","kontaktId":"patient","name":"Owned Patient","datum":"1980-10-18","typ":"birthday"},
              {"id":"old-patient-birthday","uid":"other-source","kontaktId":"old-patient","name":"Owned Patient","datum":"1980-10-18","typ":"birthday"},
              {"id":"patient-wedding","kontaktId":"patient","name":"Owned Patient","datum":"2000-10-18","typ":"wedding-anniversary"},
              {"id":"colleague-birthday","kontaktId":"colleague","name":"Owned Colleague","datum":"1981-10-18","typ":"birthday"},
              {"id":"unlinked-birthday","name":"Owned Patient","datum":"1980-10-18","typ":"birthday"}],
             "einstellungen":{"adressen":{"gruppenAusschluss":{"enabled":true,"notifications":{"scope":"birthdays","groups":["Patients"]}}},
              "regional":{"timeZone":"UTC"},"sicherheit":{"erinnernTrotzKennwort":true},"erinnerung":{"an":true,"jahrestage":{"an":true,"tage":0,"amTag":true,"stunde":8}}}}
            """)!.AsObject();
        var before = book.ToJsonString();
        using (var document = JsonDocument.Parse(before))
        {
            var root = document.RootElement;
            var exclude = ContactGroupExclusions.Create(root);
            var excluded = root.GetProperty("jahrestage").EnumerateArray().Where(exclude).Select(item => item.GetProperty("id").GetString()).ToArray();
            TestAssert.That(excluded.SequenceEqual(new[] { "patient-birthday", "old-patient-birthday" }), "Group exclusion lost identity aliases or incorrectly used a name alone.");
            var due = ReminderScheduler.DueAnniversaries(root, root.GetProperty("einstellungen").GetProperty("erinnerung"), new DateTime(2026, 10, 18, 8, 1, 0, DateTimeKind.Utc));
            TestAssert.That(!due.Any(item => item.Key.Contains("patient-birthday", StringComparison.Ordinal)) && due.Any(item => item.Key.Contains("colleague-birthday", StringComparison.Ordinal)), "Group exclusion did not govern native anniversary reminders.");
            var projection = ReminderScheduler.SelectBackgroundData(before)!;
            using var projected = JsonDocument.Parse(projection);
            TestAssert.That(!projected.RootElement.TryGetProperty("kontakte", out _) && !projection.Contains("kontaktId", StringComparison.Ordinal) && !projection.Contains("gruppenAusschluss", StringComparison.Ordinal), "Group decisions leaked contacts or membership into the reminder projection.");
            TestAssert.That(!projected.RootElement.GetProperty("jahrestage").EnumerateArray().Any(item => item.GetProperty("id").GetString() is "patient-birthday" or "old-patient-birthday"), "Group filtering must run before reminder privacy redaction.");
        }
        TestAssert.That(book.ToJsonString() == before, "Group filtering modified provider records.");
        book["einstellungen"]!["adressen"]!["gruppenAusschluss"]!["enabled"] = false;
        using var disabled = JsonDocument.Parse(book.ToJsonString());
        TestAssert.That(!disabled.RootElement.GetProperty("jahrestage").EnumerateArray().Any(ContactGroupExclusions.Create(disabled.RootElement)), "Disabled group exclusions still hide reminders.");
        TestAssert.That(book["einstellungen"]!["adressen"]!["gruppenAusschluss"]!["notifications"]!["groups"]![0]!.GetValue<string>() == "Patients", "Disabling cleared the group selection.");
        book["einstellungen"]!["adressen"]!["gruppenAusschluss"]!["enabled"] = true;
        book["einstellungen"]!["regional"]!["homeCountry"] = "US";
        book["einstellungen"]!["adressen"]!["landCode"] = "DE";
        book["kontakte"]![0]!["telefone"] = JsonNode.Parse("""[{"wert":"+12025550123"}]""");
        book["kontakte"]!.AsArray().Add(JsonNode.Parse("""{"id":"other-provider","telefone":[{"wert":"2025550123"}],"vcardRoundtrip":[]}"""));
        book["jahrestage"]!.AsArray().Add(JsonNode.Parse("""{"id":"other-provider-birthday","kontaktId":"other-provider","name":"Owned merged person","datum":"1980-10-18","typ":"birthday"}"""));
        using var regional = JsonDocument.Parse(book.ToJsonString());
        TestAssert.That(ContactGroupExclusions.Create(regional.RootElement)(regional.RootElement.GetProperty("jahrestage").EnumerateArray().Last()), "Merged phone identity must use the explicit regional home country before the address fallback.");
        book["termine"] = JsonNode.Parse("""
            [{"id":"patient-visit","kontaktId":"old-patient","titel":"Visit","datum":"2026-10-18","zeit":"08:00"},
             {"id":"work-meeting","kalenderQuelle":{"id":"work-calendar"},"titel":"Meeting","datum":"2026-10-18","zeit":"08:00"},
             {"id":"private","kontaktId":"colleague","titel":"Private","datum":"2026-10-18","zeit":"08:00"}]
            """);
        book["einstellungen"]!["adressen"]!["gruppenAusschluss"]!["notifications"] = JsonNode.Parse("""{"scope":"appointments","groups":["Patients"],"calendars":["work-calendar"]}""");
        var vacation = book.ToJsonString();
        using (var document = JsonDocument.Parse(vacation))
        {
            var excluded = ContactGroupExclusions.Create(document.RootElement, kind: "appointment");
            TestAssert.That(document.RootElement.GetProperty("termine").EnumerateArray().Where(excluded).Count() == 2, "Vacation filter must select only the chosen contact group and calendar.");
            TestAssert.That(!document.RootElement.GetProperty("jahrestage").EnumerateArray().Any(ContactGroupExclusions.Create(document.RootElement)), "Appointment-only exclusions must retain birthdays.");
        }
        using (var projection = JsonDocument.Parse(ReminderScheduler.SelectBackgroundData(vacation)!))
            TestAssert.That(projection.RootElement.GetProperty("termine").EnumerateArray().Single().GetProperty("id").GetString() == "private", "Vacation filtering must occur before contact and calendar metadata redaction.");
        var appointmentDue = ReminderScheduler.DueAppointments(vacation, new DateTime(2026, 10, 18, 8, 1, 0, DateTimeKind.Utc));
        TestAssert.That(appointmentDue.Count == 1 && appointmentDue[0].Key.StartsWith("private@", StringComparison.Ordinal), "Native appointment scheduler must respect the selected vacation groups.");
        return Task.CompletedTask;
    }
}
