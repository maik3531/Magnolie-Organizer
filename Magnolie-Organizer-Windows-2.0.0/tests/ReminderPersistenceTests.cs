using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ReminderPersistenceTests
{
    internal static Task RunAsync()
    {
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
            var springDue = ReminderScheduler.DueAppointments(spring, new DateTime(2026, 3, 29, 3, 5, 0));
            var autumnFirst = ReminderScheduler.DueAppointments(spring.Replace("2026-03-29", "2026-10-25", StringComparison.Ordinal),
                new DateTime(2026, 10, 25, 2, 35, 0));
            var autumnSecond = ReminderScheduler.DueAppointments(spring.Replace("2026-03-29", "2026-10-25", StringComparison.Ordinal),
                new DateTime(2026, 10, 25, 2, 55, 0));
            TestAssert.That(springDue.Count == 1 && autumnFirst.Single().Key == autumnSecond.Single().Key,
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
            Console.WriteLine("         REMINDER-PERSIST-OK REMINDER-PROTECTED-OK REMINDER-DST-OK REMINDER-ALARMS-OK");
            return Task.CompletedTask;
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }
}
