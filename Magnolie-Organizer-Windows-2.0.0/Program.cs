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
        if (args.Length == 1 && args[0] == "--unregister-call-notifications")
        {
            using var notifications = new WindowsCallNotifications(_ => Task.FromResult(false), listen: false);
            try { Environment.ExitCode = notifications.Unregister() ? 0 : 1; }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                System.Runtime.InteropServices.COMException or System.Security.SecurityException or ArgumentException)
            { Environment.ExitCode = 1; }
            return;
        }
        if (args.Contains("--call-action", StringComparer.Ordinal))
        {
            Environment.ExitCode = args.Length == 2 && args[0] == "--call-action" && WindowsCallNotifications.Activate(args[1]) ? 0 : 1;
            return;
        }
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
        if (args.Contains("--setup-ui-self-test", StringComparer.OrdinalIgnoreCase))
        {
            Environment.ExitCode = FirstRunSetupUiSelfTest.Run();
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
        ProfileLease profileLease;
        try { profileLease = ProfileLease.Acquire(paths.Root); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            if (!trayStart && !reminderStart) MessageBox.Show(NativeLocalization.Gettext(
                "The profile could not be locked. It may already be open in another session."), "Magnolie Organizer", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        using var ownedProfile = profileLease;
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
            using var setupServices = new FirstRunSetupServices(paths);
            using var setupPhones = new FirstRunSetupPhoneServices(paths);
            using var setup = new FirstRunSetupForm(paths, setupState, setupServices, phoneServices: setupPhones);
            if (setup.ShowDialog() != DialogResult.OK) return;
            setupSelections = setup.Selections;
        }

        Application.Run(new MainForm(trayStart, reminderStart, setupSelections));
    }
}
