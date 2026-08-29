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

        ApplicationConfiguration.Initialize();
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.CurrentCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.CurrentUICulture;
        if (handbookStart)
        {
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

        Application.Run(new MainForm(trayStart, reminderStart));
    }
}
