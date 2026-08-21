using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class SelfTest
{
    internal static int RunPackaging()
    {
        if (BridgeDispatcher.ReadContributorHash() is not { Length: 32 })
        {
            Console.Error.WriteLine("PACKAGING-SELBSTTEST FEHLGESCHLAGEN: contributorHash nicht initialisiert");
            return 1;
        }
        Console.WriteLine("PACKAGING-CONTRIBUTOR-HASH-OK");
        return 0;
    }

    internal static int Run()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-windows-test-{Guid.NewGuid():N}");
        try
        {
            var paths = new WindowsPaths(root);
            paths.EnsureDirectories();
            var store = new AtomicStore();
            const string first = "{\"termine\":[],\"notizen\":[]}";
            const string second = "{\"termine\":[{\"titel\":\"Probe\"}],\"notizen\":[]}";
            store.WriteRecoverableJson(paths.Data, first);
            Require(store.ReadRecoverableJson(paths.Data) == first, "atomarer Erstdurchlauf");
            store.WriteRecoverableJson(paths.Data, second);
            File.WriteAllText(paths.Data, "{defekt");
            Require(store.ReadRecoverableJson(paths.Data) == second, "Recovery aus atomarer Kopie");
            Require(JsonDocument.Parse(store.ReadRecoverableJson(paths.Data)!).RootElement
                .GetProperty("termine").GetArrayLength() == 1, "JSON bleibt lesbar");
            var backup = store.Backup(paths.Data, paths.Backups);
            Require(File.Exists(backup) && store.Read(backup) == second, "Sicherung");
            Console.WriteLine("RECOVERY-ATOMIC-OK RECOVERY-CORRUPT-MAIN-OK");

            var reminderState = Path.Combine(root, "reminder-state.json");
            var notices = new List<ReminderNotice>();
            using (var scheduler = new ReminderScheduler(reminderState, notices.Add))
            {
                scheduler.UpdateData("""{"einstellungen":{"erinnerung":{"an":true,"vorlauf":0,"verpasste":true}},"termine":[{"id":"vm","datum":"2026-08-12","zeit":"09:00","titel":"VM"}]}""");
                scheduler.RunOnce(new DateTime(2026, 8, 12, 10, 0, 0));
            }
            var repeated = new List<ReminderNotice>();
            using (var scheduler = new ReminderScheduler(reminderState, repeated.Add))
            {
                scheduler.UpdateData("""{"einstellungen":{"erinnerung":{"an":true,"vorlauf":0,"verpasste":true}},"termine":[{"id":"vm","datum":"2026-08-12","zeit":"09:00","titel":"VM"}]}""");
                scheduler.RunOnce(new DateTime(2026, 8, 12, 10, 1, 0));
            }
            Require(notices.Count == 1 && repeated.Count == 0, "Reminder-Persistenz");
            Console.WriteLine("REMINDER-LOGIN-ONCE-OK REMINDER-NO-DUPLICATE-OK");

            var web = Path.Combine(AppContext.BaseDirectory, "web");
            foreach (var file in new[] { "index.html", "stil.css", "anwendung.js", "i18n.js" })
                Require(File.Exists(Path.Combine(web, file)), $"Webressource {file}");
            Require(Directory.Exists(Path.Combine(web, "i18n")) &&
                    Directory.GetFiles(Path.Combine(web, "i18n"), "*.js").Length == 19,
                "19 Übersetzungskataloge");

            var spelling = WindowsSpellChecker.Check("Haus", "de");
            Require(spelling.Correct, "deutsche Windows-Rechtschreibprüfung");

            Console.WriteLine("ALLE WINDOWS-SELBSTTESTS BESTANDEN");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"WINDOWS-SELBSTTEST FEHLGESCHLAGEN: {error.Message}");
            return 1;
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); }
            catch (Exception) { }
        }
    }

    private static void Require(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException(name);
    }
}
