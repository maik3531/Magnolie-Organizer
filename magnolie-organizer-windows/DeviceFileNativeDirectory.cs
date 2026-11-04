using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

// A live Windows directory handle, not a browser path or a persisted grant.
// Receive operations use only held-handle-relative names in the partial class.
internal sealed partial class DeviceFileNativeDirectory : IDisposable
{
    private const uint ObjCaseInsensitive = 0x40, ObjDontReparse = 0x1000;
    private const uint ReadDirectoryAccess = 0x001000a1, ShareRead = 1, OpenOnly = 1;
    private const uint ShareDirectory = 3; // READ/WRITE, never DELETE (rename/replacement).
    private const uint DirectorySynchronousNoReparse = 0x00200021;
    private readonly SafeFileHandle handle;
    private readonly object gate = new();
    private bool disposed;
    private readonly bool receiveAccess;
    internal sealed record Identity(ulong VolumeSerial, ulong FileIdLow, ulong FileIdHigh);
    internal Identity OriginalIdentity { get; }
    internal string NativePath { get; }
    internal string VolumePath { get; }

    private DeviceFileNativeDirectory(SafeFileHandle handle, bool receiveAccess = false)
    {
        this.handle = handle;
        this.receiveAccess = receiveAccess;
        try { OriginalIdentity = ReadIdentity(); NativePath = ReadNativePath(); VolumePath = ReadFinalName(1); }
        catch { handle.Dispose(); throw; }
    }

    // Only the future native picker/default-folder owner may call this. In
    // particular this must never be registered as a web-selected-path action.
    internal static DeviceFileNativeDirectory OpenExisting(string nativePath)
        => OpenDirectory(nativePath, false);

    internal static DeviceFileNativeDirectory OpenExistingForReceive(string nativePath)
        => OpenDirectory(nativePath, true);

    private static DeviceFileNativeDirectory OpenDirectory(string nativePath, bool receiveAccess)
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
            // Deny DELETE sharing so the held root cannot be renamed/replaced.
            // Directory WRITE sharing is needed by NT's handle-relative rename;
            // each child operation still verifies this exact non-reparse root.
            var status = NtCreateFile(out var opened, ReadDirectoryAccess | (receiveAccess ? 6u : 0u), ref attributes, out _, IntPtr.Zero,
                0, ShareDirectory, OpenOnly, DirectorySynchronousNoReparse, IntPtr.Zero, 0);
            if (status < 0)
            {
                opened?.Dispose();
                throw new IOException("file_destination_open_failed", new Win32Exception((int)RtlNtStatusToDosError(status)));
            }
            return new(opened, receiveAccess);
        }
        finally { Marshal.FreeHGlobal(pointer); Marshal.FreeHGlobal(text); }
    }

    internal Identity CurrentIdentity()
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var current = ReadIdentity();
            if (current != OriginalIdentity || !string.Equals(ReadNativePath(), NativePath, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(ReadFinalName(1), VolumePath, StringComparison.OrdinalIgnoreCase))
                throw DeviceFileControl.Error("file_destination_identity_changed");
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

    private string ReadNativePath()
    {
        var value = ReadFinalName(0);
        if (!value.StartsWith(@"\\?\", StringComparison.Ordinal)) throw DeviceFileControl.Error("file_destination_path_unsupported");
        value = value[4..]; _ = NtDirectoryName(value);
        return value;
    }

    private string ReadFinalName(uint flags)
    {
        var name = new StringBuilder(512);
        var length = GetFinalPathNameByHandle(handle, name, (uint)name.Capacity, flags);
        if (length >= name.Capacity)
        {
            if (length > 16004) throw DeviceFileControl.Error("file_destination_path_unsupported");
            name = new StringBuilder((int)length + 1);
            length = GetFinalPathNameByHandle(handle, name, (uint)name.Capacity, flags);
        }
        if (length == 0 || length >= name.Capacity) throw new IOException("file_destination_name_unavailable", new Win32Exception(Marshal.GetLastWin32Error()));
        return name.ToString();
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
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder name, uint size, uint flags);
}
