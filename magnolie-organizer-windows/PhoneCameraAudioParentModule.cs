using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

/// <summary>No path/hash configuration, staging, elevation or native worker start.
/// Future C-API owner must retain this module through confirmed native Close.</summary>
[SupportedOSPlatform("windows")]
internal sealed partial class PhoneCameraAudioParentModule : IDisposable
{
    private readonly List<SafeFileHandle> held = [];
    private IntPtr module;
    private PhoneCameraAudioParentModule() { }
    private static readonly SecurityIdentifier Administrators = new(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier SystemAccount = new(WellKnownSidType.LocalSystemSid, null);
    private static readonly SecurityIdentifier Installer = new("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464");
    private static bool Trusted(SecurityIdentifier? sid) => sid is not null &&
        (sid.Equals(Administrators) || sid.Equals(SystemAccount) || sid.Equals(Installer));

    // Same conservative owner/ACE/mutation policy as RuntimeImage::Protected.
    // A deny ACE never compensates for an untrusted allow grant.
    internal static bool AllowsProtectedImage(RawSecurityDescriptor descriptor)
    {
        if (!Trusted(descriptor.Owner) || (descriptor.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0 ||
            descriptor.DiscretionaryAcl is null || descriptor.DiscretionaryAcl.Count > 128) return false;
        const int mutation = unchecked((int)0x500d0156); // GENERIC_WRITE/ALL, concrete file mutations and ownership/ACL/delete.
        foreach (GenericAce ace in descriptor.DiscretionaryAcl)
        {
            if ((ace.AceFlags & AceFlags.InheritOnly) != 0) continue;
            if (ace is not CommonAce common || common.IsCallback) return false;
            if (common.AceQualifier == AceQualifier.AccessDenied) continue;
            if (common.AceQualifier != AceQualifier.AccessAllowed ||
                (common.AccessMask & mutation) != 0 && !Trusted(common.SecurityIdentifier)) return false;
        }
        return true;
    }
    internal static bool IsInstalledProcessLayout(string process, string baseDirectory)
    {
        if (process.Length is < 4 or > 32000 || !char.IsAsciiLetter(process[0]) || process[1] != ':' || process[2] != '\\' ||
            process.Contains('/') || process.AsSpan(2).Contains(':')) return false;
        var parts = process[3..].Split('\\');
        if (parts.Any(p => p.Length == 0 || p is "." or ".." || p.EndsWith(' ') || p.EndsWith('.'))) return false;
        var end = process.LastIndexOf('\\');
        return parts.Length >= 2 && parts[^1].Equals("Magnolie Organizer.exe", StringComparison.OrdinalIgnoreCase) &&
            process[..end].Equals(baseDirectory.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase);
    }
    internal static PhoneCameraAudioParentModule? LoadCurrent(PhoneCameraSession.OutputAuthority original)
    {
        ArgumentNullException.ThrowIfNull(original);
        original.RequireCurrent(); // BEFORE even reading resource identity or OS paths.
        var payload = PhoneCameraAudioParentPayload.LoadEmbedded();
        if (payload is null) return null;
        if (!OperatingSystem.IsWindows() || RuntimeInformation.ProcessArchitecture != Architecture.X64)
            throw new PlatformNotSupportedException("webcam_audio_parent_windows_x64_required");
        var process = Environment.ProcessPath;
        if (process is null || !IsInstalledProcessLayout(process, AppContext.BaseDirectory))
            throw new UnauthorizedAccessException("webcam_audio_parent_installed_process_required");
        var directory = process[..process.LastIndexOf('\\')];
        var path = directory + "\\" + PhoneCameraAudioParentPayload.Filename;
        var result = new PhoneCameraAudioParentModule();
        try
        {
            result.HoldAncestors(path);
            var file = result.Hold(path, directory: false, requireProtection: true);
            using (var stream = new FileStream(file, FileAccess.Read, 16384, isAsync: false))
            {
                if (stream.Length is < 128 or > 8 * 1024 * 1024 ||
                    Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant() != payload.Sha256)
                    throw new CryptographicException("webcam_audio_parent_installed_image_changed");
                // The FileStream owns this handle. Transfer it out of held only
                // after a duplicate has been retained for the module lifetime.
                if (!DuplicateHandle(GetCurrentProcess(), file, GetCurrentProcess(), out var retained, 0, false, 2))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                result.held.Add(retained);
                result.held.Remove(file);
            }
            original.RequireCurrent();
            if (GetModuleHandle(PhoneCameraAudioParentPayload.Filename) != IntPtr.Zero)
                throw new InvalidOperationException("webcam_audio_parent_already_loaded");
            result.module = LoadLibraryEx(path, IntPtr.Zero, 0x100 | 0x800); // Only protected DLL directory + System32 dependencies.
            if (result.module == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            var loaded = new StringBuilder(32768);
            var length = GetModuleFileName(result.module, loaded, loaded.Capacity);
            if (length == 0 || length >= loaded.Capacity || !loaded.ToString().Equals(path, StringComparison.OrdinalIgnoreCase))
                throw new UnauthorizedAccessException("webcam_audio_parent_original_loaded_module_required");
            if (result.Export<VersionFunction>("MagnoliePhoneAudioVersion")() != 1)
                throw new InvalidDataException("webcam_audio_parent_abi_version_invalid");
            foreach (var name in Exports) result.Address(name);
            original.RequireCurrent();
            return result;
        }
        catch { result.Dispose(); throw; }
    }
    private static readonly string[] Exports = ["MagnoliePhoneAudioCreate", "MagnoliePhoneAudioPrepare", "MagnoliePhoneAudioRequireReady",
        "MagnoliePhoneAudioObserveVideo", "MagnoliePhoneAudioWrite", "MagnoliePhoneAudioExportAnchor", "MagnoliePhoneAudioStop", "MagnoliePhoneAudioClose",
        "MagnoliePhoneVideoVersion", "MagnoliePhoneVideoCreate", "MagnoliePhoneVideoPrepare", "MagnoliePhoneVideoRequireReady",
        "MagnoliePhoneVideoWrite", "MagnoliePhoneVideoStop", "MagnoliePhoneVideoClose"];
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate uint VersionFunction();
    internal T Export<T>(string name) where T : Delegate => Marshal.GetDelegateForFunctionPointer<T>(Address(name));
    private IntPtr Address(string name)
    {
        if (module == IntPtr.Zero) throw new ObjectDisposedException(nameof(PhoneCameraAudioParentModule));
        if (name != "MagnoliePhoneAudioVersion" && !Exports.Contains(name, StringComparer.Ordinal))
            throw new InvalidDataException("webcam_audio_parent_unknown_export");
        var address = GetProcAddress(module, name);
        return address != IntPtr.Zero ? address : throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    private void HoldAncestors(string path)
    {
        Hold(path[..3], directory: true, requireProtection: false);
        for (var at = path.IndexOf('\\', 3); at >= 0; at = path.IndexOf('\\', at + 1))
            Hold(path[..at], directory: true, requireProtection: true);
    }
    private SafeFileHandle Hold(string path, bool directory, bool requireProtection)
    {
        var handle = CreateFile(path, 0x80020000, 1, IntPtr.Zero, 3, 0x200000 | (directory ? 0x2000000u : 0), IntPtr.Zero);
        try
        {
            if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (GetFileType(handle) != 1 || !GetFileInformationByHandleEx(handle, 9, out var tag, (uint)Marshal.SizeOf<AttributeTag>()))
                throw new InvalidDataException("webcam_audio_parent_local_disk_required");
            if ((tag.Attributes & 0x400) != 0 || ((tag.Attributes & 0x10) != 0) != directory)
                throw new UnauthorizedAccessException("webcam_audio_parent_no_reparse_required");
            var final = new StringBuilder(32768); var count = GetFinalPathNameByHandle(handle, final, (uint)final.Capacity, 0);
            if (count == 0 || count >= final.Capacity || !final.ToString().Equals("\\\\?\\" + path, StringComparison.OrdinalIgnoreCase))
                throw new UnauthorizedAccessException("webcam_audio_parent_original_file_path_required");
            if (requireProtection)
            {
                var status = GetSecurityInfo(handle, 1, 1 | 4, out _, out _, out _, out _, out var descriptor);
                if (status != 0) throw new Win32Exception((int)status);
                try
                {
                    var size = GetSecurityDescriptorLength(descriptor);
                    if (size is < 20 or > 65536) throw new InvalidDataException("webcam_audio_parent_descriptor_invalid");
                    var bytes = new byte[size]; Marshal.Copy(descriptor, bytes, 0, bytes.Length);
                    if (!AllowsProtectedImage(new RawSecurityDescriptor(bytes, 0)))
                        throw new UnauthorizedAccessException("webcam_audio_parent_protected_image_required");
                }
                finally { LocalFree(descriptor); }
            }
            held.Add(handle); return handle;
        }
        catch { handle.Dispose(); throw; }
    }
    public void Dispose()
    {
        // No worker/registered callback is created by this loader. A future
        // bridge may call Dispose ONLY after its native Close is confirmed.
        if (module != IntPtr.Zero)
        {
            if (!FreeLibrary(module)) throw new Win32Exception(Marshal.GetLastWin32Error());
            module = IntPtr.Zero;
        }
        for (int i = held.Count - 1; i >= 0; --i) held[i].Dispose();
        held.Clear();
    }
    [StructLayout(LayoutKind.Sequential)] private struct AttributeTag { internal uint Attributes, Tag; }
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll")] private static extern uint GetFileType(SafeFileHandle file);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int kind, out AttributeTag value, uint size);
    [DllImport("kernel32.dll", EntryPoint = "GetFinalPathNameByHandleW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder path, uint size, uint flags);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityInfo(SafeFileHandle file, uint type, uint info, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool DuplicateHandle(IntPtr sourceProcess, SafeFileHandle source, IntPtr targetProcess, out SafeFileHandle target, uint access, bool inherit, uint options);
    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleW", CharSet = CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string name);
    [DllImport("kernel32.dll", EntryPoint = "LoadLibraryExW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll", EntryPoint = "GetModuleFileNameW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetModuleFileName(IntPtr module, StringBuilder path, int size);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)] private static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool FreeLibrary(IntPtr module);
}
