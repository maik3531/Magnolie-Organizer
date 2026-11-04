using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

// A live Windows directory handle, not a browser path or a persisted grant.
// No path-based writes, directory creation or publication is implemented here.
internal sealed class DeviceFileNativeDirectory : IDisposable
{
    private const uint ObjCaseInsensitive = 0x40, ObjDontReparse = 0x1000;
    private const uint ReadDirectoryAccess = 0x001000a1, ShareRead = 1, OpenOnly = 1;
    private const uint DirectorySynchronousNoReparse = 0x00200021;
    private readonly SafeFileHandle handle;
    private readonly object gate = new();
    private bool disposed;
    internal sealed record Identity(ulong VolumeSerial, ulong FileIdLow, ulong FileIdHigh);
    internal Identity OriginalIdentity { get; }

    private DeviceFileNativeDirectory(SafeFileHandle handle)
    {
        this.handle = handle;
        try { OriginalIdentity = ReadIdentity(); }
        catch { handle.Dispose(); throw; }
    }

    // Only the future native picker/default-folder owner may call this. In
    // particular this must never be registered as a web-selected-path action.
    internal static DeviceFileNativeDirectory OpenExisting(string nativePath)
    {
        var name = NtDirectoryName(nativePath);
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("file_destination_windows_required");
        var text = Marshal.StringToHGlobalUni(name);
        var unicode = new UnicodeString { Length = checked((ushort)(name.Length * 2)),
            MaximumLength = checked((ushort)(name.Length * 2 + 2)), Buffer = text };
        var pointer = Marshal.AllocHGlobal(Marshal.SizeOf<UnicodeString>());
        try
        {
            Marshal.StructureToPtr(unicode, pointer, false);
            var attributes = new ObjectAttributes { Length = (uint)Marshal.SizeOf<ObjectAttributes>(), ObjectName = pointer,
                Attributes = ObjCaseInsensitive | ObjDontReparse };
            // FILE_LIST_DIRECTORY | FILE_TRAVERSE | FILE_READ_ATTRIBUTES | SYNCHRONIZE.
            // Request no write/delete sharing on this root. This is not a
            // substitute for the receiver's future handle-relative operations.
            var status = NtCreateFile(out var opened, ReadDirectoryAccess, ref attributes, out _, IntPtr.Zero,
                0, ShareRead, OpenOnly, DirectorySynchronousNoReparse, IntPtr.Zero, 0);
            if (status < 0)
            {
                opened?.Dispose();
                throw new IOException("file_destination_open_failed", new Win32Exception((int)RtlNtStatusToDosError(status)));
            }
            return new(opened);
        }
        finally { Marshal.FreeHGlobal(pointer); Marshal.FreeHGlobal(text); }
    }

    internal Identity CurrentIdentity()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var current = ReadIdentity();
            if (current != OriginalIdentity) throw DeviceFileControl.Error("file_destination_identity_changed");
            return current;
        }
    }

    private Identity ReadIdentity()
    {
        if (!GetFileInformationByHandle(handle, out var basic))
            throw new IOException("file_destination_attributes_unavailable", new Win32Exception(Marshal.GetLastWin32Error()));
        if ((basic.Attributes & 0x10) == 0 || (basic.Attributes & 0x400) != 0)
            throw DeviceFileControl.Error("file_destination_not_plain_directory");
        if (!GetFileInformationByHandleEx(handle, 18, out var id, (uint)Marshal.SizeOf<FileIdInformation>()))
            throw new IOException("file_destination_identity_unavailable", new Win32Exception(Marshal.GetLastWin32Error()));
        if (id.Low == 0 && id.High == 0) throw DeviceFileControl.Error("file_destination_identity_unavailable");
        return new(id.Volume, id.Low, id.High);
    }

    internal static string NtDirectoryName(string nativePath)
    {
        // Conservative local-drive grammar. UNC/device/ADS paths are held, never
        // guessed, normalized to another root or used to replace old mappings.
        if (string.IsNullOrEmpty(nativePath) || nativePath.Length > 16000 || nativePath.Length < 3 ||
            !char.IsAsciiLetter(nativePath[0]) || nativePath[1] != ':' || nativePath[2] != '\\' ||
            nativePath.Any(character => character < 32 || character == 127 || "/*?\"<>|".Contains(character)) ||
            nativePath.AsSpan(2).Contains(':') || nativePath.Length > 3 && nativePath[3] == '\\')
            throw DeviceFileControl.Error("file_destination_path_unsupported");
        var path = nativePath.Length > 3 && nativePath.EndsWith('\\') ? nativePath[..^1] : nativePath;
        if (path.Length > 3)
            foreach (var component in path[3..].Split('\\'))
            {
                var stem = component.Split('.')[0];
                if (component.Length == 0 || component is "." or ".." || component.EndsWith(' ') || component.EndsWith('.') ||
                    stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
                    stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase) ||
                    stem.Equals("CONIN$", StringComparison.OrdinalIgnoreCase) || stem.Equals("CONOUT$", StringComparison.OrdinalIgnoreCase) ||
                    stem.Length == 4 && (stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase)) &&
                    "123456789¹²³".Contains(stem[3])) throw DeviceFileControl.Error("file_destination_path_unsupported");
            }
        return "\\??\\" + path;
    }

    public void Dispose()
    {
        lock (gate) { if (disposed) return; disposed = true; handle.Dispose(); }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct UnicodeString { internal ushort Length, MaximumLength; internal IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ObjectAttributes
    {
        internal uint Length; internal IntPtr RootDirectory, ObjectName; internal uint Attributes;
        internal IntPtr SecurityDescriptor, SecurityQualityOfService;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoStatusBlock { internal IntPtr Status, Information; }
    [StructLayout(LayoutKind.Sequential)]
    private struct FileIdInformation { internal ulong Volume, Low, High; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        internal uint Attributes; internal System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        internal uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtCreateFile(out SafeFileHandle handle, uint access, ref ObjectAttributes attributes,
        out IoStatusBlock io, IntPtr allocationSize, uint fileAttributes, uint shareAccess, uint disposition,
        uint options, IntPtr ea, uint eaLength);
    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern uint RtlNtStatusToDosError(int status);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out ByHandleFileInformation information);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int kind, out FileIdInformation information, uint size);
}
