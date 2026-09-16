using System.Diagnostics;
using System.Security.Principal;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Windows Defender Firewall lässt eingehende Verbindungen einer nicht erhöht
/// gestarteten Anwendung ohne ausdrückliche Regel nicht zu. Der Installer läuft
/// bewusst nur im Benutzerkontext und kann deshalb keine Regel anlegen. Ohne
/// Regel öffnet der Organizer zwar seine Listener, andere Geräte erreichen ihn
/// aber nie und die Netzwerkfunktionen scheitern ohne erkennbaren
/// Grund. Diese Klasse prüft die Regeln ohne Rechteerhöhung und legt sie auf
/// ausdrückliche Benutzerhandlung mit genau einer UAC-Abfrage an.
/// </summary>
internal static class WindowsFirewall
{
    internal const string ElevationArgument = "--firewall-freigeben";
    private const string TcpRule = "Magnolie Organizer – Netzwerkdienste (TCP)";
    private const string UdpRule = "Magnolie Organizer – Netzwerkdienste (UDP)";
    private const string LegacyTcpRule = "Magnolie Organizer – Telefonverbindung (TCP)";
    private const string LegacyUdpRule = "Magnolie Organizer – Telefonverbindung (UDP)";

    /* Magnolie-Telefonprotokoll 8741/TCP, Magnolienbaum 8737/TCP+UDP,
       KDE-Connect 1716-1764/TCP, KDE-Connect-Suche 1716/UDP und mDNS 5353/UDP. */
    private const string TcpPorts = "8741,8737,1716-1764";
    private const string UdpPorts = "8737,1716,5353";

    private static readonly object CacheGate = new();
    private static bool cachedConfigured;
    private static DateTimeOffset cachedUntil = DateTimeOffset.MinValue;

    internal static string ExecutablePath => Environment.ProcessPath ?? "";

    internal static bool IsElevated()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            using var identity = WindowsIdentity.GetCurrent();
            return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
        }
        catch (Exception error) when (error is UnauthorizedAccessException or System.Security.SecurityException)
        {
            return false;
        }
    }

    /// <summary>
    /// Prüft ohne Rechteerhöhung, ob beide Regeln auf diese Programmdatei zeigen.
    /// Jede Prüfung startet zwei <c>netsh</c>-Prozesse; weil der Telefonstand
    /// häufig gemeldet wird, gilt das Ergebnis eine Minute lang.
    /// </summary>
    internal static bool Configured()
    {
        lock (CacheGate) if (DateTimeOffset.UtcNow < cachedUntil) return cachedConfigured;
        var program = ExecutablePath;
        var configured = program.Length > 0 &&
            RuleMatchesProgram(TcpRule, program, TcpPorts) && RuleMatchesProgram(UdpRule, program, UdpPorts);
        lock (CacheGate) { cachedConfigured = configured; cachedUntil = DateTimeOffset.UtcNow.AddMinutes(1); }
        return configured;
    }

    private static void InvalidateCache()
    { lock (CacheGate) cachedUntil = DateTimeOffset.MinValue; }

    /// <summary>
    /// Legt die Regeln an. Setzt einen erhöhten Prozess voraus; ohne Rechte
    /// meldet <c>netsh</c> einen Fehler, der als Text zurückkommt.
    /// </summary>
    internal static string Apply()
    {
        var program = ExecutablePath;
        if (program.Length == 0) return "Die eigene Programmdatei konnte nicht bestimmt werden.";

        /* Nur eigene aktuelle und frühere Regeln ersetzen. Benutzerdefinierte
           Erlaubnisregeln für denselben Programmpfad bleiben unangetastet.

           Zusätzlich müssen Blockregeln für genau diese Programmdatei weg: Sie
           haben in Windows Vorrang vor jeder Erlaubnis, und eine einmal mit
           „Abbrechen“ beantwortete Firewallabfrage hinterlässt genau so eine
           Regel. Ohne diesen Schritt bliebe die Freigabe wirkungslos. */
        foreach (var rule in new[] { TcpRule, UdpRule, LegacyTcpRule, LegacyUdpRule }.Concat(BlockingRuleNames(program)))
            Run(["advfirewall", "firewall", "delete", "rule", "name=" + rule, "program=" + program], out _);

        var tcp = Run(["advfirewall", "firewall", "add", "rule", "name=" + TcpRule, "dir=in",
            "action=allow", "program=" + program, "protocol=TCP", "localport=" + TcpPorts,
            "profile=any", "enable=yes"], out var tcpOutput);
        var udp = Run(["advfirewall", "firewall", "add", "rule", "name=" + UdpRule, "dir=in",
            "action=allow", "program=" + program, "protocol=UDP", "localport=" + UdpPorts,
            "profile=any", "enable=yes"], out var udpOutput);
        InvalidateCache();
        if (tcp && udp) return "";
        var detail = (tcp ? udpOutput : tcpOutput).Trim();
        return detail.Length > 0 ? detail : "Die Firewallregel konnte nicht angelegt werden.";
    }

    /// <summary>
    /// Sorgt für vorhandene Regeln. Fehlen sie, wird genau einmal mit einer
    /// UAC-Abfrage erhöht. Rückgabe ist leer, wenn die Regeln danach stehen.
    /// </summary>
    internal static string Ensure()
    {
        if (!OperatingSystem.IsWindows()) return "";
        if (Configured()) return "";
        if (IsElevated()) return Apply();

        var program = ExecutablePath;
        if (program.Length == 0) return "Die eigene Programmdatei konnte nicht bestimmt werden.";
        try
        {
            var start = new ProcessStartInfo(program)
            {
                UseShellExecute = true,
                Verb = "runas",
                WorkingDirectory = Environment.SystemDirectory,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            start.ArgumentList.Add(ElevationArgument);
            using var process = Process.Start(start);
            if (process is null) return FirewallHint;
            if (!process.WaitForExit(60_000)) return FirewallHint;
            InvalidateCache();
            return process.ExitCode == 0 && Configured() ? "" : FirewallHint;
        }
        catch (System.ComponentModel.Win32Exception error) when (error.NativeErrorCode == 1223)
        {
            return "Die Firewallfreigabe wurde abgelehnt. Ohne sie blockiert Windows " +
                   "eingehende Verbindungen dieser Anwendung.";
        }
        catch (Exception error) when (error is System.ComponentModel.Win32Exception or InvalidOperationException
                                          or PlatformNotSupportedException)
        {
            return FirewallHint;
        }
    }

    internal static string FirewallHint =>
        "Windows blockiert eingehende Verbindungen dieser Anwendung. Die Netzwerkdienste " +
        "benötigen eine Firewallfreigabe für „Magnolie Organizer“.";

    /// <summary>
    /// Namen aller Blockregeln, die genau auf diese Programmdatei zeigen.
    ///
    /// Gelesen wird die Regelliste aus der Registrierung, nicht aus der
    /// <c>netsh</c>-Ausgabe: Deren Beschriftungen sind übersetzt, die Felder
    /// <c>Action</c> und <c>App</c> in der Registrierung dagegen nicht. Ein
    /// Löschen nach Aktion ist über <c>netsh</c> ohnehin nicht möglich, wohl
    /// aber nach Namen.
    ///
    /// Fehlende Leseberechtigung ist kein Fehlerfall – dann bleibt es bei den
    /// vier eigenen Regelnamen.
    /// </summary>
    private static List<string> BlockingRuleNames(string program)
    {
        var result = new List<string>();
        if (!OperatingSystem.IsWindows()) return result;
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules");
            if (key is null) return result;
            foreach (var entry in key.GetValueNames())
            {
                if (key.GetValue(entry) is not string value) continue;
                string name = ""; var blocking = false; var sameProgram = false;
                foreach (var part in value.Split('|'))
                {
                    if (part.StartsWith("Action=", StringComparison.OrdinalIgnoreCase))
                        blocking = part["Action=".Length..].Equals("Block", StringComparison.OrdinalIgnoreCase);
                    else if (part.StartsWith("App=", StringComparison.OrdinalIgnoreCase))
                        sameProgram = string.Equals(part["App=".Length..], program, StringComparison.OrdinalIgnoreCase);
                    else if (part.StartsWith("Name=", StringComparison.OrdinalIgnoreCase))
                        name = part["Name=".Length..];
                }
                if (blocking && sameProgram && name.Length > 0 && !result.Contains(name)) result.Add(name);
            }
        }
        catch (Exception error) when (error is System.Security.SecurityException or UnauthorizedAccessException
                                          or IOException or ObjectDisposedException) { }
        return result;
    }

    private static bool RuleMatchesProgram(string rule, string program, string ports)
    {
        /* „show rule“ ist auch ohne Administratorrechte erlaubt. Die Ausgabe ist
           übersetzt; deshalb werden nur Programmpfad und Portwerte geprüft. */
        return Run(["advfirewall", "firewall", "show", "rule", "name=" + rule, "verbose"], out var output) &&
               output.Contains(program, StringComparison.OrdinalIgnoreCase) && OutputContainsPorts(output, ports);
    }

    internal static bool OutputContainsPorts(string output, string requiredPorts)
    {
        var tokens = output.Split([',', ' ', '\r', '\n', '\t'], StringSplitOptions.RemoveEmptyEntries);
        return requiredPorts.Split(',').All(port => tokens.Contains(port, StringComparer.Ordinal));
    }

    private static bool Run(string[] arguments, out string output)
    {
        output = "";
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "netsh.exe"))
            {
                WorkingDirectory = Environment.SystemDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            foreach (var argument in arguments) start.ArgumentList.Add(argument);
            using var process = Process.Start(start);
            if (process is null) return false;
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(30_000)) { try { process.Kill(true); } catch (Exception) { } return false; }
            output = stdout.WaitAsync(TimeSpan.FromSeconds(3)).GetAwaiter().GetResult() + stderr.WaitAsync(TimeSpan.FromSeconds(3)).GetAwaiter().GetResult();
            return process.ExitCode == 0;
        }
        catch (Exception error) when (error is System.ComponentModel.Win32Exception or InvalidOperationException
                                          or PlatformNotSupportedException or IOException or TimeoutException)
        {
            return false;
        }
    }
}
