using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class FirstRunSetupTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-first-run-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root);
            var state = new FirstRunSetupState(paths);
            TestAssert.That(state.Classify() == FirstRunSetupClassification.Fresh,
                "Ein leerer LocalAppData-Ordner wurde nicht als frische Installation erkannt.");

            state.Begin();
            RegionalSettings.WriteLanguage(paths.RegionalSettings, "de");
            TestAssert.That(state.Classify() == FirstRunSetupClassification.Pending &&
                            FirstRunSetupStartup.MustShowAssistant(FirstRunSetupClassification.Pending, false, false) &&
                            FirstRunSetupStartup.MustExitBackground(FirstRunSetupClassification.Pending, true, false),
                "Sprachwahl und Abbruch unterdruecken den noch ausstehenden Assistenten.");
            File.Delete(paths.FirstRunSetup);
            File.Delete(AtomicStore.BackupPath(paths.FirstRunSetup));
            File.Delete(paths.RegionalSettings);

            File.WriteAllText(paths.Data, "{beschädigte-altdaten");
            TestAssert.That(state.Classify() == FirstRunSetupClassification.ExistingWithoutMarker,
                "Beschädigte vorhandene Daten wurden fälschlich als frische Installation eingestuft.");
            state.AdoptExisting();
            TestAssert.That(state.Classify() == FirstRunSetupClassification.Complete,
                "Eine bestehende Installation wurde nicht mit einem gültigen Marker adoptiert.");
            using (var adopted = JsonDocument.Parse(new AtomicStore().ReadRecoverableJson(paths.FirstRunSetup)!))
                TestAssert.That(adopted.RootElement.GetProperty("Status").GetString() == "adopted" &&
                                adopted.RootElement.GetProperty("Selections").TryGetProperty("language", out _),
                    "Der Adoptionsstatus fehlt im Setup-Marker.");

            VerifySelectionContract(paths.Backups);
            VerifySelectionNormalization(paths.Backups);

            var interrupted = false;
            var interruptedState = new FirstRunSetupState(paths, new AtomicStore(stage =>
            {
                if (!interrupted && stage == AtomicStore.WriteStage.TemporaryFlushed)
                {
                    interrupted = true;
                    throw new IOException("simulierter Abbruch");
                }
            }));
            await TestAssert.ThrowsAsync<IOException>(() => Task.Run(() => interruptedState.Complete(
                new FirstRunSetupSelections { Language = "de", BackupPath = paths.Backups })),
                "Ein Abbruch beim atomaren Setup-Marker wurde nicht simuliert.");
            TestAssert.That(state.Classify() == FirstRunSetupClassification.Complete &&
                            !Directory.EnumerateFiles(root).Any(file => Path.GetFileName(file).Contains(".tmp", StringComparison.Ordinal)),
                "Ein unterbrochener Marker-Schreibvorgang beschädigte den bestätigten Zustand.");

            File.WriteAllText(paths.FirstRunSetup, "defekt");
            File.WriteAllText(AtomicStore.BackupPath(paths.FirstRunSetup), "auch defekt");
            TestAssert.That(state.Classify() == FirstRunSetupClassification.DamagedMarker,
                "Ein beschädigtes Markerpaar wurde als frisch oder abgeschlossen behandelt.");
            TestAssert.That(FirstRunSetupStartup.MustExitBackground(FirstRunSetupClassification.Fresh, true, false) &&
                            FirstRunSetupStartup.MustExitBackground(FirstRunSetupClassification.DamagedMarker, false, true) &&
                            !FirstRunSetupStartup.MustExitBackground(FirstRunSetupClassification.Complete, true, true) &&
                            !FirstRunSetupStartup.MustExitBackground(FirstRunSetupClassification.ExistingWithoutMarker, true, false),
                "Das Hintergrund-Gate trennt unvollständige und bestehende Installationen nicht korrekt.");
            TestAssert.That(FirstRunSetupStartup.MustShowAssistant(FirstRunSetupClassification.Fresh, false, false) &&
                            FirstRunSetupStartup.MustShowAssistant(FirstRunSetupClassification.DamagedMarker, false, false) &&
                            !FirstRunSetupStartup.MustShowAssistant(FirstRunSetupClassification.DamagedMarker, true, false) &&
                            !FirstRunSetupStartup.MustShowAssistant(FirstRunSetupClassification.Complete, false, false),
                "Das Vordergrund-Gate öffnet den Assistenten bei einem beschädigten Marker nicht sicher.");

            VerifyProgramSourceOrder();
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch (Exception) { }
        }
    }

    private static void VerifyProgramSourceOrder()
    {
        var program = File.ReadAllText("Program.cs");
        var mutex = program.IndexOf("using var mutex = new Mutex", StringComparison.Ordinal);
        var initialize = program.IndexOf("ApplicationConfiguration.Initialize();", mutex, StringComparison.Ordinal);
        var classification = program.IndexOf("setupState.Classify()", initialize, StringComparison.Ordinal);
        var backgroundGate = program.IndexOf("FirstRunSetupStartup.MustExitBackground", classification, StringComparison.Ordinal);
        var pending = program.IndexOf("setupState.Begin()", backgroundGate, StringComparison.Ordinal);
        var pendingGuard = program.IndexOf("catch (Exception error) when (error is IOException or UnauthorizedAccessException)", pending, StringComparison.Ordinal);
        var pendingMessage = program.IndexOf("The setup state could not be saved.", pending, StringComparison.Ordinal);
        var wizard = program.IndexOf("new FirstRunSetupForm", pending, StringComparison.Ordinal);
        var mainForm = program.IndexOf("new MainForm", wizard, StringComparison.Ordinal);
        TestAssert.That(mutex >= 0 && initialize > mutex && classification > initialize &&
                        backgroundGate > classification && pending > backgroundGate && pendingGuard > pending &&
                        pendingMessage > pending && pendingMessage < wizard && wizard > pending && mainForm > wizard,
            "Haupt-Mutex, WinForms-Initialisierung, Setup-Gate, Wizard und MainForm stehen nicht in sicherer Reihenfolge.");
        var foregroundGate = program.IndexOf("FirstRunSetupStartup.MustShowAssistant", backgroundGate, StringComparison.Ordinal);
        TestAssert.That(foregroundGate > backgroundGate && foregroundGate < wizard,
            "Der Assistent wird nicht über das getestete Fresh-/Damaged-Vordergrund-Gate gestartet.");
        var beforeWizard = program[..wizard];
        TestAssert.That(!beforeWizard.Contains("new MainForm", StringComparison.Ordinal) &&
                        !beforeWizard.Contains("new WebView2", StringComparison.Ordinal) &&
                        !beforeWizard.Contains("new NotifyIcon", StringComparison.Ordinal) &&
                        !beforeWizard.Contains("new BridgeDispatcher", StringComparison.Ordinal) &&
                        !beforeWizard.Contains("new ReminderScheduler", StringComparison.Ordinal),
            "Vor dem Ersteinrichtungsassistenten wird bereits Haupt- oder Hintergrundlaufzeit erzeugt.");
        var wizardSource = File.ReadAllText("FirstRunSetupForm.cs");
        TestAssert.That(!wizardSource.Contains("Microsoft.Web.WebView2", StringComparison.Ordinal) &&
                        !wizardSource.Contains("NotifyIcon", StringComparison.Ordinal) &&
                        !wizardSource.Contains("BridgeDispatcher", StringComparison.Ordinal),
            "Der native Wizard zieht WebView, Tray oder Dispatcher vor.");
        foreach (var required in new[]
        {
            "claws", "vcard", "ldif", "csv-lotus", "windows-contacts",
            "tasks", "addresses", "notes", "appointments", "anniversaries", "planner", "health"
        })
            TestAssert.That(wizardSource.Contains($"\"{required}\"", StringComparison.Ordinal),
                $"Die Assistenten-ID {required} fehlt.");
        TestAssert.That(wizardSource.Contains("ClientSize = new Size(900, 680)", StringComparison.Ordinal) &&
                         wizardSource.Contains("Dock = DockStyle.Top, Height = 190", StringComparison.Ordinal) &&
                          wizardSource.Contains("Color.FromArgb(218, 207, 178)", StringComparison.Ordinal) &&
                          wizardSource.Contains("MaxLength = 4096", StringComparison.Ordinal),
            "Fenstergeometrie, Kopfzeile oder Begrenzung freier Listen entsprechen nicht dem Vertrag.");
        TestAssert.That(wizardSource.Contains("Shown += (_, _) => PlayWelcomeSound()", StringComparison.Ordinal) &&
                        wizardSource.Contains("NativeMethods.PlaySoundFile", StringComparison.Ordinal) &&
                        wizardSource.Contains("erinnerung.wav", StringComparison.Ordinal) &&
                        wizardSource.Contains("if (welcomeSoundPlayed) return", StringComparison.Ordinal) &&
                        !wizardSource.Contains("PlayWelcomeChime", StringComparison.Ordinal) &&
                        !wizardSource.Contains("SystemSounds", StringComparison.Ordinal),
            "Der Begrüßungston wird nicht genau einmal automatisch und ohne Auswahl abgespielt.");
        TestAssert.That(wizardSource.Contains("region = Value(result.Felder, \"st\")", StringComparison.Ordinal) &&
                        wizardSource.Contains("AddressSort = addressSort", StringComparison.Ordinal) &&
                        wizardSource.Contains("PhoneActions = []", StringComparison.Ordinal) &&
                        wizardSource.Contains("https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Notes-1.0.13.apk", StringComparison.Ordinal) &&
                        wizardSource.Contains("https://play.google.com/store/apps/details?id=org.kde.kdeconnect_tp&hl=de&pli=1", StringComparison.Ordinal) &&
                         !wizardSource.Contains("ms-settings:bluetooth", StringComparison.Ordinal) &&
                         !wizardSource.Contains("OpenBluetoothSettings", StringComparison.Ordinal) &&
                        !wizardSource.Contains("phoneIntentions", StringComparison.Ordinal) &&
                        !wizardSource.Contains("magnolienbaum", StringComparison.OrdinalIgnoreCase) &&
                        !wizardSource.Contains("\"thunderbird\"", StringComparison.Ordinal) &&
                        !wizardSource.Contains("finishManual", StringComparison.Ordinal) &&
                        !wizardSource.Contains("openHandbook: true", StringComparison.Ordinal) &&
                         !wizardSource.Contains("RecoveryPointsIntent", StringComparison.Ordinal) &&
                         !wizardSource.Contains("retentionMode", StringComparison.Ordinal) &&
                          wizardSource.Contains("RestoreRequest = restoreRequest", StringComparison.Ordinal) &&
                         !wizardSource.Contains("Restoring is deferred", StringComparison.Ordinal) &&
                         !wizardSource.Contains("FirstRunSetupCustomBlock", StringComparison.Ordinal) &&
                        !wizardSource.Contains("Design custom tab after startup", StringComparison.Ordinal),
            "Adress-, Telefon-, Quellen-, Recovery- oder Handbuchseite entspricht nicht dem direkten Setup-Vertrag.");

        var main = File.ReadAllText("MainForm.cs");
        var bridge = File.ReadAllText("BridgeDispatcher.cs");
        TestAssert.That(program.Contains("new MainForm(trayStart, reminderStart, setupSelections)", StringComparison.Ordinal) &&
                        main.Contains("new BridgeDispatcher(this, paths, setupSelections)", StringComparison.Ordinal) &&
                         bridge.Split("setupSelections", StringSplitOptions.None).Length >= 6,
            "Die vollständige Setup-Auswahl wird nicht in beide App.init-Pfade weitergereicht.");
    }

    private static void VerifySelectionNormalization(string backupPath)
    {
        var normalized = FirstRunSetupSelectionNormalizer.Normalize(new FirstRunSetupSelections
        {
            AddressSort = "first-name",
            OneTimeImports = ["windows-contacts", "vcard", "thunderbird", "claws"],
            PhoneActions = ["kde-connect", "bluetooth", "magnolie-notes"],
            Registers = ["health", "calendar", "tasks"],
            Address = new FirstRunSetupAddress { FirstName = "  Ada  ", Country = "DE", State = "Mecklenburg-Vorpommern" },
            CustomTabEnabled = true,
            CustomTabName = "  Reisen  ",
            CustomOrganizer = new FirstRunSetupCustomOrganizer { Modules =
            [
                new() { Id = "fremd", Type = "appointments", Page = "right", Order = 9 },
                new() { Id = "fremd-2", Type = "unknown", Page = "left", Order = 0 },
                new() { Id = "fremd-3", Type = "notes", Page = "right", Order = 4 },
                new() { Id = "fremd-4", Type = "tasks", Page = "right", Order = 7 }
            ] },
            BackupPath = "  ",
            Autostart = true,
            Tray = false
        }, backupPath);
        TestAssert.That(normalized.AddressSort == "first-name" &&
                        normalized.OneTimeImports.SequenceEqual(new[] { "claws", "vcard", "windows-contacts" }) &&
                        normalized.PhoneActions.Count == 0 &&
                        normalized.Registers.SequenceEqual(new[] { "tasks", "health" }) &&
                        normalized.Address.FirstName == "Ada" && normalized.Address.State == "DE-MV" &&
                        normalized.CustomTabName == "Reisen" &&
                         normalized.CustomOrganizer.Version == 3 && normalized.CustomOrganizer.Modules.Count == 3 &&
                        normalized.CustomOrganizer.Modules[0] is { Id: "setup-0", Type: "appointments", Page: "left", Order: 0 } &&
                        normalized.CustomOrganizer.Modules[1] is { Id: "setup-1", Type: "notes", Page: "right", Order: 0 } &&
                        normalized.CustomOrganizer.Modules[2] is { Id: "setup-2", Type: "tasks", Page: "left", Order: 1 } &&
                        normalized.Autostart && normalized.Tray,
            "Mehrfachauswahlen werden nicht in kanonischer UI-Reihenfolge gespeichert.");
        TestAssert.That(normalized.BackupPath == backupPath,
            "Ein leerer Backup-Pfad fällt nicht auf den Standard-Backupordner zurück.");

        var skipped = FirstRunSetupSelectionNormalizer.Normalize(new FirstRunSetupSelections
        {
            Language = "de",
            OneTimeImports = ["vcard"],
            PhoneActions = ["magnolie-notes"],
            OpenHandbook = true,
            Address = new FirstRunSetupAddress { FirstName = "Ada" },
            BackupPath = "anderer-ordner",
            BackupInterval = "daily"
        }, backupPath, skipped: true);
        TestAssert.That(skipped.Language == "de" && !skipped.OpenHandbook && skipped.Address.FirstName.Length == 0 &&
                        skipped.OneTimeImports.Count == 0 && skipped.PhoneActions.Count == 0 &&
                        skipped.BackupPath == backupPath && skipped.BackupInterval == "manual",
            "Vollständiges Überspringen verwendet nicht die sicheren Linux-semantischen Werte.");
    }

    private static void VerifySelectionContract(string backupPath)
    {
        var defaults = new FirstRunSetupSelections { BackupPath = backupPath };
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(defaults));
        var root = document.RootElement;
        var expected = new[]
        {
            "language", "address", "addressSource", "addressSort", "calendarUids", "addressBookUid", "oneTimeImports", "phoneActions",
            "registers", "customTabEnabled", "customTabName", "customTabDesignRequested", "customTabChanged", "customOrganizerChanged", "customOrganizer",
            "openHandbook", "backupPath", "backupInterval", "autostart", "tray", "weather", "restoreRequest"
        };
        TestAssert.That(root.EnumerateObject().Select(property => property.Name).SequenceEqual(expected),
            "Das Setup-Auswahlobjekt verwendet nicht exakt die gemeinsamen camelCase-JSON-Schlüssel.");
        TestAssert.That(root.GetProperty("addressSource").GetString() == "own" &&
                         root.GetProperty("addressSort").GetString() == "last-name" &&
                         root.GetProperty("address").GetProperty("country").GetString() == "DE" &&
                        root.GetProperty("backupInterval").GetString() == "manual" &&
                         !root.GetProperty("openHandbook").GetBoolean() &&
                         !root.GetProperty("customTabChanged").GetBoolean() &&
                         !root.GetProperty("customOrganizerChanged").GetBoolean() &&
                         root.GetProperty("phoneActions").GetArrayLength() == 0 &&
                         root.GetProperty("customOrganizer").GetProperty("version").GetInt32() == 3 &&
                         root.GetProperty("customOrganizer").GetProperty("modules").GetArrayLength() == 0,
            "Die sicheren Standardwerte des Assistenten stimmen nicht.");
        TestAssert.That(root.GetProperty("registers").EnumerateArray().Select(value => value.GetString()).SequenceEqual(
                            new[] { "tasks", "addresses", "notes", "anniversaries", "planner", "health" }),
            "Nicht alle sechs auswählbaren Standardregister sind aktiviert.");
    }
}
