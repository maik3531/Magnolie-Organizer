using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace MagnolieOrganizer.Windows;

internal static partial class DocumentExportService
{
    // Windows' registry-backed TimeZoneInfo can omit historical IANA changes.
    // Use the existing Windows system ICU calendar, not a larger tolerance for
    // untrusted renderer projections or a guessed historical offset.
    [SupportedOSPlatform("windows")]
    private static DateTimeOffset TimeSheetIcuLocal(DateTimeOffset instant, string zone)
    {
        if (string.IsNullOrEmpty(zone) || zone.Length > 255 || zone.Contains('\0'))
            throw new ArgumentException("Invalid time zone.");
        if (TimeZoneInfo.TryConvertWindowsIdToIanaId(zone, out var iana)) zone = iana;
        var status = 0;
        var canonical = new char[256];
        var length = TimeSheetIcu.Canonical(zone, zone.Length, canonical, canonical.Length, out var system, ref status);
        if (status > 0 || system == 0 || length <= 0 || length >= canonical.Length)
            throw new ArgumentException("Invalid time zone.");
        status = 0;
        var calendar = TimeSheetIcu.Open(zone, zone.Length, "en_US_POSIX", 1, ref status);
        if (calendar == IntPtr.Zero || status > 0)
        {
            if (calendar != IntPtr.Zero) TimeSheetIcu.Close(calendar);
            throw new ArgumentException("Invalid time zone.");
        }
        try
        {
            TimeSheetIcu.SetMillis(calendar, instant.ToUnixTimeMilliseconds(), ref status);
            var offset = (long)TimeSheetIcu.Get(calendar, 15, ref status) + TimeSheetIcu.Get(calendar, 16, ref status);
            if (status > 0 || offset is < -86_400_000 or > 86_400_000)
                throw new ArgumentException("Invalid time zone.");
            // Civil cells only; elapsed time is still derived from UTC minutes.
            return new DateTimeOffset(instant.UtcDateTime.AddMilliseconds(offset), TimeSpan.Zero);
        }
        finally { TimeSheetIcu.Close(calendar); }
    }

    [SupportedOSPlatform("windows")]
    private static class TimeSheetIcu
    {
        [DllImport("icu.dll", EntryPoint = "ucal_getCanonicalTimeZoneID", CharSet = CharSet.Unicode, CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        internal static extern int Canonical(string id, int length, [Out] char[] result, int capacity, out byte system, ref int status);

        [DllImport("icu.dll", EntryPoint = "ucal_open", CharSet = CharSet.Unicode, CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        internal static extern IntPtr Open(string id, int length, [MarshalAs(UnmanagedType.LPUTF8Str)] string locale, int type, ref int status);

        [DllImport("icu.dll", EntryPoint = "ucal_setMillis", CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        internal static extern void SetMillis(IntPtr calendar, double instant, ref int status);

        [DllImport("icu.dll", EntryPoint = "ucal_get", CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        internal static extern int Get(IntPtr calendar, int field, ref int status);

        [DllImport("icu.dll", EntryPoint = "ucal_close", CallingConvention = CallingConvention.Cdecl)]
        [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
        internal static extern void Close(IntPtr calendar);
    }
}
