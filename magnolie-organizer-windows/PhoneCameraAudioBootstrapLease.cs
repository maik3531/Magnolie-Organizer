using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

/// <summary>Do not elevate a mutable managed apphost/runtime directory. All
/// bootstrap directories and load inputs stay held until the child exits.
/// Unsupported/portable writable installations use the official manual route.</summary>
[SupportedOSPlatform("windows")]
internal sealed class PhoneCameraAudioBootstrapLease : IDisposable
{
    private readonly List<SafeFileHandle> held = [];
    private static readonly SecurityIdentifier Admin = new(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier LocalSystem = new(WellKnownSidType.LocalSystemSid, null);
    private static readonly SecurityIdentifier TrustedInstaller = new("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464");
    private PhoneCameraAudioBootstrapLease() { }
    internal static bool ProtectedLoadInput(RawSecurityDescriptor descriptor)
    {
        bool Trusted(SecurityIdentifier? sid) => sid is not null && (sid.Equals(Admin) || sid.Equals(LocalSystem) || sid.Equals(TrustedInstaller));
        if (!Trusted(descriptor.Owner) || descriptor.DiscretionaryAcl is null || (descriptor.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0) return false;
        const int mutation = 0x500d0156; // Generic/all, data/append/EA/attributes, delete/child-delete, DACL/owner.
        foreach (GenericAce ace in descriptor.DiscretionaryAcl)
        {
            if ((ace.AceFlags & AceFlags.InheritOnly) != 0) continue;
            if (ace is not CommonAce common || common.IsCallback) return false;
            if (common.AceQualifier == AceQualifier.AccessDenied) continue;
            if (common.AceQualifier != AceQualifier.AccessAllowed || ((common.AccessMask & mutation) != 0 && !Trusted(common.SecurityIdentifier))) return false;
        }
        return true;
    }
    internal static PhoneCameraAudioBootstrapLease? TryAcquire()
    {
        var result = new PhoneCameraAudioBootstrapLease();
        try
        {
            var directory = Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
            var drive = Path.GetPathRoot(directory);
            if (drive is null || drive.Length != 3 || drive[1] != ':' || string.IsNullOrEmpty(Environment.ProcessPath) ||
                !string.Equals(Path.GetDirectoryName(Environment.ProcessPath), directory, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.GetDirectoryName(typeof(PhoneCameraAudioBootstrapLease).Assembly.Location), directory, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("webcam_audio_protected_apphost_required");
            var current = drive;
            result.Hold(current, folder: true, checkAcl: false);
            foreach (var component in directory[drive.Length..].Split(Path.DirectorySeparatorChar))
            {
                current = Path.Combine(current, component);
                result.Hold(current, folder: true, checkAcl: string.Equals(current, directory, StringComparison.OrdinalIgnoreCase));
            }
            // Apphost, managed entry, deps/runtimeconfig, hostfxr/hostpolicy and
            // runtime/culture/native subdirectories must all be immutable to
            // ordinary users, not just the eventual staged native helper. Do
            // not follow reparse points or scan outside this fixed app tree.
            var pending = new Stack<string>(); pending.Push(directory); var count = 0;
            while (pending.TryPop(out var parent))
            {
                foreach (var path in Directory.EnumerateFileSystemEntries(parent))
                {
                    if (++count > 32768) throw new InvalidDataException("webcam_audio_bootstrap_inputs_invalid");
                    var folder = (File.GetAttributes(path) & FileAttributes.Directory) != 0;
                    result.Hold(path, folder, checkAcl: true);
                    if (folder) pending.Push(path);
                }
            }
            if (count < 2) throw new InvalidDataException("webcam_audio_bootstrap_inputs_invalid");
            return result;
        }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or ArgumentException or System.ComponentModel.Win32Exception)
        { result.Dispose(); return null; }
    }
    private void Hold(string path, bool folder, bool checkAcl)
    {
        const uint readControl = 0x20000, readAttributes = 0x80, dataRead = 1;
        var file = CreateFile(path, readControl | readAttributes | dataRead, 1, IntPtr.Zero, 3, 0x00200000u | (folder ? 0x02000000u : 0), IntPtr.Zero);
        held.Add(file);
        if (file.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if (!GetFileInformationByHandleEx(file, 9, out var attributes, (uint)Marshal.SizeOf<AttributeTag>())) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if ((attributes.Attributes & 0x400) != 0 || ((attributes.Attributes & 0x10) != 0) != folder)
            throw new InvalidDataException("webcam_audio_bootstrap_reparse_refused");
        if (!checkAcl) return;
        var status = GetSecurityInfo(file, 1, 1 | 4, out _, out _, out _, out _, out var descriptor);
        if (status != 0) throw new System.ComponentModel.Win32Exception((int)status);
        try
        {
            var bytes = new byte[checked((int)GetSecurityDescriptorLength(descriptor))]; Marshal.Copy(descriptor, bytes, 0, bytes.Length);
            if (!ProtectedLoadInput(new RawSecurityDescriptor(bytes, 0))) throw new UnauthorizedAccessException("webcam_audio_mutable_managed_bootstrap_refused");
        }
        finally { LocalFree(descriptor); }
    }
    public void Dispose() { for (int i = held.Count - 1; i >= 0; --i) held[i].Dispose(); held.Clear(); }
    [StructLayout(LayoutKind.Sequential)] private struct AttributeTag { internal uint Attributes, Tag; }
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint sharing, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int type, out AttributeTag result, uint size);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityInfo(SafeFileHandle handle, int type, uint flags, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
}
