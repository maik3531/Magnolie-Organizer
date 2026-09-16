using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

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
    internal static readonly uint ExitMessage = RegisterWindowMessage("MagnolieOrganizer.Windows.Exit");

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

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int RegCreateKeyEx(nint root, string subkey, uint reserved, string? keyClass,
        uint options, uint access, nint security, out SafeRegistryHandle key, out uint disposition);

    internal static RegistryKey CreateCurrentUserKey(string path, out bool created)
    {
        var error = RegCreateKeyEx(unchecked((nint)(int)0x80000001), path, 0, null, 0, 0x2001f,
            nint.Zero, out var handle, out var disposition);
        if (error != 0) { handle.Dispose(); throw new System.ComponentModel.Win32Exception(error); }
        created = disposition == 1;
        return RegistryKey.FromHandle(handle);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern void SHChangeNotify(uint eventId, uint flags, [MarshalAs(UnmanagedType.LPWStr)] string path, nint other);

    internal static void NotifyShortcutChanged(string path, bool deleted = false) =>
        SHChangeNotify(deleted ? 4u : 2u, 0x1005, path, nint.Zero);

    [DllImport("shell32.dll")]
    private static extern int SHGetKnownFolderPath(ref Guid folder, uint flags, nint token, out nint path);

    internal static string UserProgramsPath()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var folder = new Guid("A77F5D77-2E2B-44C3-A6A2-ABA601054A51");
        var error = SHGetKnownFolderPath(ref folder, 0, identity.AccessToken.DangerousGetHandle(), out var path);
        try
        {
            Marshal.ThrowExceptionForHR(error);
            var value = Marshal.PtrToStringUni(path) ?? "";
            return Path.IsPathFullyQualified(value) ? value : throw new IOException("Programs folder is unavailable.");
        }
        finally { Marshal.FreeCoTaskMem(path); }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PropertyKey(Guid format, uint id) { internal Guid Format = format; internal uint Id = id; }
    [StructLayout(LayoutKind.Explicit, Size = 24)]
    private struct PropertyValue
    {
        [FieldOffset(0)] internal ushort Type;
        [FieldOffset(8)] internal nint Pointer;
    }
    [DllImport("ole32.dll")]
    private static extern int PropVariantClear(ref PropertyValue value);
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink { }
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLink
    {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int length, nint data, uint flags);
        void GetIDList(out nint value);
        void SetIDList(nint value);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int length);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int length);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int length);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short value);
        void SetHotkey(short value);
        void GetShowCmd(out int value);
        void SetShowCmd(int value);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int length, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
        void Resolve(nint window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore
    {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropertyValue value);
        void SetValue(ref PropertyKey key, ref PropertyValue value);
        void Commit();
    }

    internal static void CreateToastShortcut(string path, string executable, string appId, Guid activator)
    {
        var instance = new ShellLink();
        try
        {
            var link = (IShellLink)instance;
            link.SetPath(executable); link.SetArguments("");
            link.SetWorkingDirectory(Path.GetDirectoryName(executable)!);
            link.SetDescription("Magnolie Organizer"); link.SetIconLocation(executable, 0);
            var properties = (IPropertyStore)instance;
            var key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
            var value = new PropertyValue { Type = 31, Pointer = Marshal.StringToCoTaskMemUni(appId) };
            try { properties.SetValue(ref key, ref value); }
            finally { _ = PropVariantClear(ref value); }
            key.Id = 26;
            value = new PropertyValue { Type = 72, Pointer = Marshal.AllocCoTaskMem(16) };
            try { Marshal.StructureToPtr(activator, value.Pointer, false); properties.SetValue(ref key, ref value); }
            finally { _ = PropVariantClear(ref value); }
            properties.Commit(); ((IPersistFile)instance).Save(path, true);
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

    internal static bool ToastShortcutMatches(string path, string executable, string appId, Guid activator, string ownerSid)
    {
        if (!File.Exists(path) || (File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0 ||
            new FileInfo(path).GetAccessControl().GetOwner(typeof(SecurityIdentifier))?.Value != ownerSid) return false;
        var instance = new ShellLink();
        try
        {
            ((IPersistFile)instance).Load(path, 0);
            var link = (IShellLink)instance;
            var valueText = new StringBuilder(32768);
            link.GetPath(valueText, valueText.Capacity, nint.Zero, 4);
            if (!string.Equals(valueText.ToString(), executable, StringComparison.OrdinalIgnoreCase)) return false;
            valueText.Clear(); link.GetArguments(valueText, valueText.Capacity);
            if (valueText.Length != 0) return false;
            var properties = (IPropertyStore)instance;
            var key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
            properties.GetValue(ref key, out var value);
            try { if (value.Type != 31 || Marshal.PtrToStringUni(value.Pointer) != appId) return false; }
            finally { _ = PropVariantClear(ref value); }
            key.Id = 26; properties.GetValue(ref key, out value);
            try { return value.Type == 72 && value.Pointer != nint.Zero && Marshal.PtrToStructure<Guid>(value.Pointer) == activator; }
            finally { _ = PropVariantClear(ref value); }
        }
        finally { Marshal.FinalReleaseComObject(instance); }
    }

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
