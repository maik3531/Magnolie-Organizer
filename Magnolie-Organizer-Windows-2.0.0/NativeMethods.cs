using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal static class NativeMethods
{
    private const uint SndAsync = 0x0001;
    private const uint SndNoDefault = 0x0002;
    private const uint SndFileName = 0x00020000;
    private const int DwmUseImmersiveDarkMode = 20;
    private const int DwmUseImmersiveDarkModeBefore20H1 = 19;
    internal const int SettingChangeMessage = 0x001A;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern nint FindWindow(string? className, string windowName);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(nint window, uint message, nint wParam, nint lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern uint RegisterWindowMessage(string message);

    [DllImport("winmm.dll", CharSet = CharSet.Unicode, EntryPoint = "PlaySoundW")]
    private static extern bool PlaySound(string sound, nint module, uint flags);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(nint window, int attribute, ref int value, int size);

    internal static readonly uint ActivationMessage = RegisterWindowMessage(
        "MagnolieOrganizer.Windows.Activate");

    internal static void ActivateExistingWindow(string title)
    {
        var window = FindWindow(null, title);
        if (window == nint.Zero) return;
        PostMessage(window, ActivationMessage, nint.Zero, nint.Zero);
    }

    internal static bool HasUriScheme(string scheme)
    {
        if (!OperatingSystem.IsWindows() || !Regex.IsMatch(scheme, "^[a-z][a-z0-9+.-]{1,31}$")) return false;
        try
        {
            using var key = Registry.ClassesRoot.OpenSubKey(scheme);
            using var command = key?.OpenSubKey(@"shell\open\command");
            return key?.GetValue("URL Protocol") is not null &&
                   command?.GetValue(null) is string value && !string.IsNullOrWhiteSpace(value);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                             System.Security.SecurityException)
        {
            return false;
        }
    }

    internal static bool PlaySoundFile(string path) =>
        File.Exists(path) && PlaySound(path, nint.Zero, SndAsync | SndNoDefault | SndFileName);

    internal static void ApplySystemTitleBarTheme(nint window)
    {
        if (!OperatingSystem.IsWindows() || window == nint.Zero) return;
        var dark = SystemUsesDarkApps() ? 1 : 0;
        if (DwmSetWindowAttribute(window, DwmUseImmersiveDarkMode, ref dark, sizeof(int)) != 0)
            DwmSetWindowAttribute(window, DwmUseImmersiveDarkModeBefore20H1, ref dark, sizeof(int));
    }

    private static bool SystemUsesDarkApps()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            return key?.GetValue("AppsUseLightTheme") is int value && value == 0;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                             System.Security.SecurityException)
        {
            return false;
        }
    }
}
