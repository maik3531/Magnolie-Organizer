using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;
using System.Runtime.Versioning;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Elevated preparation only, never an installer or incoming-control entry.
/// Publishes a complete original package under the native helper's fixed root.
/// No replacement, recursive deletion, ownership takeover or ACL repair of
/// existing objects. Unknown/partial staging stays visible for manual review.
/// </summary>
[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioStaging
{
    private const string Security = "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)";
    private const uint ReadControl = 0x00020000, ReadAttributes = 0x80;
    private const uint BackupSemantics = 0x02000000, OpenReparsePoint = 0x00200000;
    private const uint ShareReadWrite = 3, OpenExisting = 3;
    private static readonly SecurityIdentifier Administrators = new(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier System = new(WellKnownSidType.LocalSystemSid, null);

    // Checked in-memory policy shared by actual held-handle ACL validation and
    // tests. ProgramData may permit creating NEW siblings, not deleting ours.
    internal static bool AllowsProtectedDirectory(RawSecurityDescriptor descriptor, bool programData)
    {
        if (descriptor.Owner is null || !(descriptor.Owner.Equals(Administrators) || descriptor.Owner.Equals(System)) ||
            (descriptor.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0 || descriptor.DiscretionaryAcl is null)
            return false;
        const int dangerousCommon = 0x00000040 | 0x00010000 | 0x00040000 | 0x00080000 | 0x10000000;
        var dangerous = dangerousCommon | 0x00000010 | 0x00000100 | 0x40000000;
        if (!programData) dangerous |= 0x00000002 | 0x00000004;
        foreach (GenericAce ace in descriptor.DiscretionaryAcl)
        {
            if ((ace.AceFlags & AceFlags.InheritOnly) != 0) continue;
            if (ace is not CommonAce common || common.IsCallback) return false;
            if (common.AceQualifier == AceQualifier.AccessDenied) continue;
            if (common.AceQualifier != AceQualifier.AccessAllowed) return false;
            if ((common.AccessMask & dangerous) != 0 && !common.SecurityIdentifier.Equals(Administrators) && !common.SecurityIdentifier.Equals(System))
                return false;
        }
        return true;
    }

    internal static string Prepare(PhoneCameraAudioPackage package)
    {
        ArgumentNullException.ThrowIfNull(package);
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("webcam_audio_windows_required");
        using var identity = WindowsIdentity.GetCurrent();
        if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
            throw new UnauthorizedAccessException("webcam_audio_administrator_required");
        var programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
        // This first supported path is a local drive's immediate ProgramData
        // child. Relocated/nested/UNC paths require a held-ancestor design, not
        // path-based checks that an unrelated parent could replace afterwards.
        var drive = Path.GetPathRoot(programData);
        if (!Path.IsPathFullyQualified(programData) || drive is null || drive.Length != 3 || drive[1] != ':' ||
            !string.Equals(Directory.GetParent(programData)?.FullName.TrimEnd(Path.DirectorySeparatorChar),
                drive.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("webcam_audio_programdata_invalid");
        using var parent = HoldProtected(programData, programData: true);
        var root = Path.Combine(programData, "Magnolie-Webcam-Driver-Setup");
        CreateProtected(root, allowExisting: true);
        using var rootHandle = HoldProtected(root, programData: false);
        var id = Guid.NewGuid().ToString("B");
        var unpublished = Path.Combine(root, ".preparing-" + id);
        var published = Path.Combine(root, id);
        CreateProtected(unpublished, allowExisting: false);
        try
        {
            using (var preparation = HoldProtected(unpublished, programData: false))
            {
                // Original bytes were owned/verified before this step. All
                // members inherit admin/system-only write access at creation.
                // Files are CreateNew + WriteThrough + Flush(true), never an
                // untrusted cache rename into a privileged execution location.
                package.ExtractIntoEmptyDirectory(unpublished);
            }
            // No replacement flag. A collision or interruption never makes a
            // partial package eligible for the native helper's GUID-only path.
            if (!MoveFileEx(unpublished, published, 0x8)) throw new Win32Exception(Marshal.GetLastWin32Error());
            using var complete = HoldProtected(published, programData: false);
            return published;
        }
        catch (Exception error)
        {
            // Preserve unexpected files/outcomes; never recursively remove a
            // path or silently repair/retry a failed privileged preparation.
            error.Data["webcam_audio_staging"] = Directory.Exists(published) ? published : unpublished;
            throw;
        }
    }

    private static SafeFileHandle HoldProtected(string path, bool programData)
    {
        var handle = CreateFile(path, ReadControl | ReadAttributes, ShareReadWrite, IntPtr.Zero, OpenExisting,
            BackupSemantics | OpenReparsePoint, IntPtr.Zero);
        try
        {
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (!GetFileInformationByHandleEx(handle, 9, out var attributes, (uint)Marshal.SizeOf<AttributeTag>()))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            if ((attributes.Attributes & 0x10) == 0 || (attributes.Attributes & 0x400) != 0)
                throw new InvalidDataException("webcam_audio_protected_directory_required");
            var status = GetSecurityInfo(handle, 1, 0x1 | 0x4, out _, out _, out _, out _, out var descriptor);
            if (status != 0) throw new Win32Exception((int)status);
            try
            {
                var bytes = new byte[checked((int)GetSecurityDescriptorLength(descriptor))];
                Marshal.Copy(descriptor, bytes, 0, bytes.Length);
                if (!AllowsProtectedDirectory(new RawSecurityDescriptor(bytes, 0), programData))
                    throw new UnauthorizedAccessException("webcam_audio_unprotected_existing_directory");
            }
            finally { LocalFree(descriptor); }
            return handle;
        }
        catch { handle.Dispose(); throw; }
    }
    private static void CreateProtected(string path, bool allowExisting)
    {
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor(Security, 1, out var descriptor, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            var security = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(), Descriptor = descriptor };
            if (!CreateDirectory(path, ref security))
            {
                var error = Marshal.GetLastWin32Error();
                if (!(allowExisting && error == 183)) throw new Win32Exception(error);
            }
        }
        finally { LocalFree(descriptor); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct AttributeTag { internal uint Attributes, Tag; }
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { internal int Length; internal IntPtr Descriptor; internal int Inherit; }
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint sharing, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int type, out AttributeTag result, uint size);
    [DllImport("advapi32.dll")]
    private static extern uint GetSecurityInfo(SafeFileHandle handle, int type, uint flags, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, out uint size);
    [DllImport("kernel32.dll", EntryPoint = "CreateDirectoryW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateDirectory(string path, ref SecurityAttributes security);
    [DllImport("kernel32.dll", EntryPoint = "MoveFileExW", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string source, string destination, uint flags);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
}
