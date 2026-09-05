using System.Globalization;
using System.Threading;

namespace MagnolieOrganizer.Windows;

internal static class Program
{
    private const string MutexName = @"Local\MagnolieOrganizer.Windows";
    private const string HandbookMutexName = @"Local\MagnolieOrganizer.Windows.Handbook";

    [STAThread]
    private static void Main(string[] args)
    {
        CrashReporter.RegisterHandlers();
        var trayStart = args.Contains("--tray-start", StringComparer.OrdinalIgnoreCase);
        var reminderStart = args.Contains("--reminder-start", StringComparer.OrdinalIgnoreCase);
        var handbookStart = args.Contains("--handbook", StringComparer.OrdinalIgnoreCase);
        if (args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = SelfTest.Run();
            return;
        }
        if (args.Contains("--packaging-self-test", StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = SelfTest.RunPackaging();
            return;
        }
        if (args.Contains("--ui-self-test", StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = UiSelfTest.Run();
            return;
        }
        /* Wird ausschließlich von der Anwendung selbst erhöht aufgerufen, um die
           Firewallfreigabe der Netzwerkdienste anzulegen. Es werden keine
           Angaben aus der Befehlszeile übernommen. */
        if (args.Contains(WindowsFirewall.ElevationArgument, StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = WindowsFirewall.Apply().Length == 0 ? 0 : 1;
            return;
        }

        if (handbookStart)
        {
            ApplicationConfiguration.Initialize();
            CultureInfo.DefaultThreadCurrentCulture = CultureInfo.CurrentCulture;
            CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.CurrentUICulture;
            using var handbookMutex = new Mutex(true, HandbookMutexName, out var firstHandbook);
            if (!firstHandbook) { NativeMethods.ActivateExistingWindow(HandbookForm.WindowTitle); return; }
            Application.Run(new HandbookForm());
            return;
        }

        using var mutex = new Mutex(true, MutexName, out var firstInstance);
        if (!firstInstance)
        {
            if (!trayStart) NativeMethods.ActivateExistingWindow("Magnolie Organizer");
            return;
        }

        ApplicationConfiguration.Initialize();
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.CurrentCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.CurrentUICulture;

        var paths = new WindowsPaths();
        var setupState = new FirstRunSetupState(paths);
        var setupClassification = setupState.Classify();
        if (FirstRunSetupStartup.MustExitBackground(setupClassification, trayStart, reminderStart)) return;
        if (setupClassification == FirstRunSetupClassification.ExistingWithoutMarker)
        {
            try { setupState.AdoptExisting(); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                RotatingLog.Append(Path.Combine(paths.Logs, "startup.log"),
                    $"{DateTimeOffset.Now:O} Ersteinrichtung: bestehende Installation konnte nicht adoptiert werden: {error.Message}");
                if (trayStart || reminderStart) return;
            }
        }

        FirstRunSetupSelections? setupSelections = null;
        if (FirstRunSetupStartup.MustShowAssistant(setupClassification, trayStart, reminderStart))
        {
            if (setupClassification == FirstRunSetupClassification.Fresh)
            {
                try { setupState.Begin(); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException)
                {
                    RotatingLog.Append(Path.Combine(paths.Logs, "startup.log"),
                        $"{DateTimeOffset.Now:O} Ersteinrichtung: Status konnte nicht gespeichert werden: {error.Message}");
                    MessageBox.Show(NativeLocalization.Gettext("The setup state could not be saved.") +
                        Environment.NewLine + error.Message, NativeLocalization.Gettext("Magnolie Organizer"),
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                setupClassification = FirstRunSetupClassification.Pending;
            }
            using var setup = new FirstRunSetupForm(paths, setupState);
            if (setup.ShowDialog() != DialogResult.OK) return;
            setupSelections = setup.Selections;
        }

        Application.Run(new MainForm(trayStart, reminderStart, setupSelections));
    }
}
