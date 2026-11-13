using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

// Future combined elevated setup ONLY. Not wired to the audio-only installer.
// Does not activate COM/FrameServer, load a DLL or establish capture authority.
[SupportedOSPlatform("windows")]
internal static class PhoneCameraSourceRegistration
{
    private const string ClassParent = "SOFTWARE\\Classes\\CLSID";
    private const string ClassName = "{" + PhoneCameraSourcePayload.ClassId + "}";
    private const string Security = "O:BAG:BAD:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)(A;CI;KR;;;BU)";
    private static readonly SecurityIdentifier Administrators = new(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier SystemAccount = new(WellKnownSidType.LocalSystemSid, null);
    internal sealed record RegistryValue(RegistryValueKind Kind, object? Data);
    // Readback comparison only; expectedPath comes from our private protected
    // module lease, never from a caller's runtime/configuration trust manifest.
    internal static bool MatchesRegistration(IReadOnlyDictionary<string, RegistryValue> classValues, IReadOnlyList<string> classChildren,
        IReadOnlyDictionary<string, RegistryValue> serverValues, IReadOnlyList<string> serverChildren, string expectedPath) =>
        expectedPath.Length > 0 && classValues.Count == 1 && classValues.TryGetValue("", out var friendly) &&
        friendly == new RegistryValue(RegistryValueKind.String, "Magnolie Phone Camera Source") &&
        classChildren.Count == 1 && classChildren[0] == "InprocServer32" && serverChildren.Count == 0 &&
        serverValues.Count == 2 && serverValues.TryGetValue("", out var module) &&
        module == new RegistryValue(RegistryValueKind.String, expectedPath) && serverValues.TryGetValue("ThreadingModel", out var threading) &&
        threading == new RegistryValue(RegistryValueKind.String, "Both");
    internal static bool AllowsRegistrySecurity(RawSecurityDescriptor descriptor)
    {
        if (descriptor.Owner is null || !(descriptor.Owner.Equals(Administrators) || descriptor.Owner.Equals(SystemAccount)) ||
            (descriptor.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0 || descriptor.DiscretionaryAcl is null)
            return false;
        // KEY_SET_VALUE/CREATE_SUB_KEY/CREATE_LINK, DELETE, WRITE_DAC/OWNER,
        // GENERIC_WRITE/ALL. KEY_NOTIFY(0x10) is READ, not FILE_WRITE_EA.
        const int dangerous = 0x2 | 0x4 | 0x20 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000;
        foreach (GenericAce ace in descriptor.DiscretionaryAcl)
        {
            if ((ace.AceFlags & AceFlags.InheritOnly) != 0) continue;
            if (ace is not CommonAce common || common.IsCallback) return false;
            if (common.AceQualifier == AceQualifier.AccessDenied) continue;
            if (common.AceQualifier != AceQualifier.AccessAllowed || (common.AccessMask & dangerous) != 0 &&
                !common.SecurityIdentifier.Equals(Administrators) && !common.SecurityIdentifier.Equals(SystemAccount)) return false;
        }
        return true;
    }
    internal static void InstallCurrent(PhoneCameraSetupJournal journal)
    {
        ArgumentNullException.ThrowIfNull(journal);
        using var identity = WindowsIdentity.GetCurrent();
        if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
            throw new UnauthorizedAccessException("webcam_source_install_administrator_required");
        var payload = PhoneCameraSourcePayload.LoadEmbedded() ?? throw new InvalidOperationException("webcam_source_payload_required");
        if (payload.Sha256 != journal.SourceSha256) throw new CryptographicException("webcam_source_original_journal_required");
        // Explicit machine64 view only; never HKCR or a per-user DLL fallback.
        using var machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
        using var user = RegistryKey.OpenBaseKey(RegistryHive.CurrentUser, RegistryView.Registry64);
        using var parent = machine.OpenSubKey(ClassParent, writable: true) ?? throw new InvalidDataException("webcam_source_class_parent_missing");
        RequireRegistrySecurity(parent);
        using var existingMachine = parent.OpenSubKey(ClassName, writable: false);
        using var existingUser = user.OpenSubKey(ClassParent + "\\" + ClassName, writable: false);
        if (existingMachine is not null || existingUser is not null)
            throw new InvalidOperationException("webcam_source_existing_class_preserved");
        journal.BeginSource(); // Durable intent BEFORE file/key mutation.
        try
        {
            using var module = ModuleLease.Publish(payload);
            using var ownClass = CreateNewKey(parent, ClassName); // Disposition checked; no overwrite on a race.
            ownClass.SetValue("", "Magnolie Phone Camera Source", RegistryValueKind.String);
            using var inproc = CreateNewKey(ownClass, "InprocServer32");
            inproc.SetValue("", module.Path, RegistryValueKind.String);
            inproc.SetValue("ThreadingModel", "Both", RegistryValueKind.String);
            inproc.Flush(); ownClass.Flush();
            RequireRegistrySecurity(ownClass); RequireRegistrySecurity(inproc);
            if (!MatchesRegistration(ReadValues(ownClass), ownClass.GetSubKeyNames(), ReadValues(inproc), inproc.GetSubKeyNames(), module.Path))
                throw new InvalidDataException("webcam_source_registration_readback_changed");
            module.RequireDigest(payload.Sha256);
            journal.ConfirmSource(); // Accounting, NOT readiness/activation/OS binding.
        }
        catch
        {
            // Never delete DLLs/keys, roll back someone else's class, erase an
            // old transaction or retry an unknown Win32/file/flush outcome.
            try { journal.RecordFailure(unknown: true); } catch (Exception) { }
            throw;
        }
    }
    private static IReadOnlyDictionary<string, RegistryValue> ReadValues(RegistryKey key) => key.GetValueNames().ToDictionary(name => name,
        name => new RegistryValue(key.GetValueKind(name), key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames)), StringComparer.Ordinal);
    private static RegistryKey CreateNewKey(RegistryKey parent, string name)
    {
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor(Security, 1, out var descriptor, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            var security = new SecurityAttributes { Length = Marshal.SizeOf<SecurityAttributes>(), Descriptor = descriptor };
            var status = RegCreateKeyEx(parent.Handle, name, 0, null, 0, 0x2001f | 0x100, ref security, out var handle, out var disposition);
            if (status != 0) { handle?.Dispose(); throw new Win32Exception(status); }
            if (disposition != 1) { handle.Dispose(); throw new InvalidOperationException("webcam_source_class_collision_preserved"); }
            try { return RegistryKey.FromHandle(handle, RegistryView.Registry64); }
            catch { handle.Dispose(); throw; }
        }
        finally { LocalFree(descriptor); }
    }
    private static void RequireRegistrySecurity(RegistryKey key)
    {
        uint size = 0;
        var status = RegGetKeySecurity(key.Handle, 0x1 | 0x4, null, ref size);
        if (status != 122 || size is < 20 or > 65536) throw new Win32Exception(status == 122 ? 13 : status);
        var bytes = new byte[size];
        status = RegGetKeySecurity(key.Handle, 0x1 | 0x4, bytes, ref size);
        if (status != 0) throw new Win32Exception(status);
        if (!AllowsRegistrySecurity(new RawSecurityDescriptor(bytes, 0)))
            throw new UnauthorizedAccessException("webcam_source_unprotected_registry_key");
    }
    private sealed class ModuleLease : IDisposable
    {
        private readonly List<IDisposable> held = [];
        private FileStream? image;
        internal string Path { get; private set; } = "";
        internal static ModuleLease Publish(PhoneCameraSourcePayload payload)
        {
            var result = new ModuleLease();
            try
            {
                var programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
                var drive = System.IO.Path.GetPathRoot(programData);
                if (!System.IO.Path.IsPathFullyQualified(programData) || drive is null || drive.Length != 3 || drive[1] != ':' ||
                    !string.Equals(Directory.GetParent(programData)?.FullName.TrimEnd(System.IO.Path.DirectorySeparatorChar),
                        drive.TrimEnd(System.IO.Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("webcam_source_programdata_invalid");
                result.held.Add(PhoneCameraAudioStaging.HoldProtected(programData, programData: true));
                var root = System.IO.Path.Combine(programData, "Magnolie-Webcam-Source");
                PhoneCameraAudioStaging.CreateProtected(root, allowExisting: true);
                result.held.Add(PhoneCameraAudioStaging.HoldProtected(root, programData: false));
                var directory = System.IO.Path.Combine(root, payload.Sha256);
                PhoneCameraAudioStaging.CreateProtected(directory, allowExisting: false);
                result.held.Add(PhoneCameraAudioStaging.HoldProtected(directory, programData: false));
                result.Path = System.IO.Path.Combine(directory, PhoneCameraSourcePayload.Filename);
                using (var output = PhoneCameraAudioStaging.CreateProtectedFile(result.Path))
                { payload.WriteSnapshot(output); output.Flush(flushToDisk: true); }
                // Explicit trusted owner + DACL at CREATE_NEW, never a token's
                // assumed default owner or promotion of a user-owned cache.
                var handle = OpenImage(result.Path, 0x80020000, 1, IntPtr.Zero, 3, 0x200000, IntPtr.Zero);
                try
                {
                    if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
                    if (GetFileType(handle) != 1 || !GetFileInformationByHandleEx(handle, 9, out var tag, (uint)Marshal.SizeOf<AttributeTag>()) ||
                        (tag.Attributes & (0x400 | 0x10)) != 0)
                        throw new UnauthorizedAccessException("webcam_source_original_local_file_required");
                    var final = new System.Text.StringBuilder(32768);
                    var count = GetFinalPathNameByHandle(handle, final, (uint)final.Capacity, 0);
                    if (count == 0 || count >= final.Capacity || !final.ToString().Equals("\\\\?\\" + result.Path, StringComparison.OrdinalIgnoreCase))
                        throw new UnauthorizedAccessException("webcam_source_original_file_path_required");
                    RequireImageSecurity(handle);
                    result.image = new FileStream(handle, FileAccess.Read);
                }
                catch { handle.Dispose(); throw; }
                result.RequireDigest(payload.Sha256);
                return result;
            }
            catch { result.Dispose(); throw; } // Preserve every partial directory/file.
        }
        internal void RequireDigest(string expected)
        {
            if (image is null) throw new ObjectDisposedException(nameof(ModuleLease));
            image.Position = 0;
            if (Convert.ToHexString(SHA256.HashData(image)).ToLowerInvariant() != expected)
                throw new CryptographicException("webcam_source_installed_bytes_changed");
        }
        public void Dispose()
        {
            try { image?.Dispose(); image = null; }
            finally { for (var i = held.Count - 1; i >= 0; --i) held[i].Dispose(); held.Clear(); }
        }
    }
    private static void RequireImageSecurity(SafeFileHandle file)
    {
        var status = GetSecurityInfo(file, 1, 0x1 | 0x4, out _, out _, out _, out _, out var descriptor);
        if (status != 0) throw new Win32Exception((int)status);
        try
        {
            var size = GetSecurityDescriptorLength(descriptor);
            if (size is < 20 or > 65536) throw new InvalidDataException("webcam_source_image_descriptor_invalid");
            var bytes = new byte[size]; Marshal.Copy(descriptor, bytes, 0, bytes.Length);
            if (!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor(bytes, 0)))
                throw new UnauthorizedAccessException("webcam_source_protected_image_required");
        }
        finally { LocalFree(descriptor); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct AttributeTag { internal uint Attributes, Tag; }
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { internal int Length; internal IntPtr Descriptor; internal int Inherit; }
    [DllImport("advapi32.dll", EntryPoint = "RegCreateKeyExW", CharSet = CharSet.Unicode)]
    private static extern int RegCreateKeyEx(SafeRegistryHandle parent, string name, int reserved, string? @class, uint options, uint access,
        ref SecurityAttributes security, out SafeRegistryHandle result, out uint disposition);
    [DllImport("advapi32.dll")] private static extern int RegGetKeySecurity(SafeRegistryHandle key, uint information, byte[]? descriptor, ref uint length);
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle OpenImage(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll")] private static extern uint GetFileType(SafeFileHandle file);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(SafeFileHandle file, int kind, out AttributeTag value, uint size);
    [DllImport("kernel32.dll", EntryPoint = "GetFinalPathNameByHandleW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle file, System.Text.StringBuilder path, uint size, uint flags);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityInfo(SafeFileHandle file, uint type, uint information,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, out uint size);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
}
