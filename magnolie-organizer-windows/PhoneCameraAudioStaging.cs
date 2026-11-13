using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;
using System.Runtime.Versioning;
using System.Security.Cryptography;

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
    private const uint ReadControl = 0x00020000, ReadAttributes = 0x80, ListDirectory = 0x1;
    private const uint BackupSemantics = 0x02000000, OpenReparsePoint = 0x00200000;
    private const uint ShareReadOnly = 1, ShareReadWrite = 3, OpenExisting = 3;
    private static readonly SecurityIdentifier Administrators = new(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier SystemAccount = new(WellKnownSidType.LocalSystemSid, null);

    // Checked in-memory policy shared by actual held-handle ACL validation and
    // tests. ProgramData may permit creating NEW siblings, not deleting ours.
    internal static bool AllowsProtectedDirectory(RawSecurityDescriptor descriptor, bool programData)
    {
        if (descriptor.Owner is null || !(descriptor.Owner.Equals(Administrators) || descriptor.Owner.Equals(SystemAccount)) ||
            (descriptor.ControlFlags & ControlFlags.DiscretionaryAclPresent) == 0 || descriptor.DiscretionaryAcl is null)
            return false;
        const int dangerousCommon = 0x00000040 | 0x00010000 | 0x00040000 | 0x00080000 | 0x10000000;
        var dangerous = dangerousCommon | 0x40000000;
        if (!programData) dangerous |= 0x00000002 | 0x00000004 | 0x00000010 | 0x00000100;
        foreach (GenericAce ace in descriptor.DiscretionaryAcl)
        {
            if ((ace.AceFlags & AceFlags.InheritOnly) != 0) continue;
            if (ace is not CommonAce common || common.IsCallback) return false;
            if (common.AceQualifier == AceQualifier.AccessDenied) continue;
            if (common.AceQualifier != AceQualifier.AccessAllowed) return false;
            if ((common.AccessMask & dangerous) != 0 && !common.SecurityIdentifier.Equals(Administrators) && !common.SecurityIdentifier.Equals(SystemAccount))
                return false;
        }
        return true;
    }

    internal static Prepared Prepare(PhoneCameraAudioPackage package, PhoneCameraAudioHelperPayload helper)
    {
        ArgumentNullException.ThrowIfNull(package);
        ArgumentNullException.ThrowIfNull(helper);
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
        var rootCreated = CreateProtected(root, allowExisting: true);
        using var rootHandle = HoldProtected(root, programData: false);
        var id = Guid.NewGuid().ToString("B");
        var unpublished = Path.Combine(root, ".preparing-" + id);
        var published = Path.Combine(root, id);
        CreateProtected(unpublished, allowExisting: false);
        try
        {
            IReadOnlyDictionary<string, string> members;
            using (var preparation = HoldProtected(unpublished, programData: false))
            {
                // Original bytes were owned/verified before this step. All
                // members inherit admin/system-only write access at creation.
                // Files are CreateNew + WriteThrough + Flush(true), never an
                // untrusted cache rename into a privileged execution location.
                members = package.ExtractIntoEmptyDirectory(unpublished);
                using var executable = new FileStream(Path.Combine(unpublished, PhoneCameraAudioHelperPayload.Filename),
                    FileMode.CreateNew, FileAccess.Write, FileShare.Read, 16384, FileOptions.WriteThrough);
                helper.WriteSnapshot(executable); executable.Flush(flushToDisk: true);
            }
            // No replacement flag. A collision or interruption never makes a
            // partial package eligible for the native helper's GUID-only path.
            if (!MoveFileEx(unpublished, published, 0x8)) throw new Win32Exception(Marshal.GetLastWin32Error());
            return Prepared.Open(programData, root, published, helper, rootCreated, members);
        }
        catch (Exception error)
        {
            // Preserve unexpected files/outcomes; never recursively remove a
            // path or silently repair/retry a failed privileged preparation.
            error.Data["webcam_audio_staging"] = Directory.Exists(published) ? published : unpublished;
            throw;
        }
    }

    internal sealed class Prepared : IDisposable
    {
        private readonly List<IDisposable> held = [];
        private readonly Dictionary<string, string> expected;
        private readonly string root;
        private int mutationState;
        internal string Directory { get; }
        internal bool RootCreated { get; }
        internal string Executable => Path.Combine(Directory, PhoneCameraAudioHelperPayload.Filename);
        private Prepared(string directory, string root, bool rootCreated, IReadOnlyDictionary<string, string> members, PhoneCameraAudioHelperPayload helper)
        {
            Directory = directory; this.root = root; RootCreated = rootCreated;
            expected = new Dictionary<string, string>(members, StringComparer.OrdinalIgnoreCase) { [PhoneCameraAudioHelperPayload.Filename] = helper.Sha256 };
        }
        internal static Prepared Open(string programData, string root, string directory, PhoneCameraAudioHelperPayload helper, bool rootCreated, IReadOnlyDictionary<string, string> members)
        {
            var result = new Prepared(directory, root, rootCreated, members, helper);
            try
            {
                result.held.Add(HoldProtected(programData, programData: true));
                result.held.Add(HoldProtected(root, programData: false));
                result.held.Add(HoldProtected(directory, programData: false));
                // Hold executable and all native verifier inputs without
                // write/delete sharing for the entire child-process lifetime.
                foreach (var name in new[] { PhoneCameraAudioHelperPayload.Filename, "vbMmeCable64_win10.inf",
                    "vbaudio_cable64_win10.cat", "vbaudio_cable64_win10.sys", "vbaudio_cable64arm_win10.sys" })
                {
                    var path = Path.Combine(directory, name);
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                        throw new InvalidDataException("webcam_audio_staged_file_reparse");
                    var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                    result.held.Add(file);
                    if (name == PhoneCameraAudioHelperPayload.Filename &&
                        Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant() != helper.Sha256)
                        throw new CryptographicException("webcam_audio_staged_helper_changed");
                }
                return result;
            }
            catch { result.Dispose(); throw; }
        }
        internal void MarkInstallationStarted()
        {
            if (Interlocked.CompareExchange(ref mutationState, 1, 0) != 0)
                throw new InvalidOperationException("webcam_audio_original_preparation_already_consumed");
        }
        internal void RemoveKnownUninstalledPreparation()
        {
            if (Interlocked.CompareExchange(ref mutationState, 2, 0) != 0)
                throw new InvalidOperationException("webcam_audio_mutated_or_unknown_preparation_must_be_preserved");
            Dispose(); // Own file/directory leases must close before deletion.
            if ((File.GetAttributes(Directory) & FileAttributes.ReparsePoint) != 0 ||
                !System.IO.Directory.EnumerateFileSystemEntries(Directory).Select(Path.GetFileName).Order(StringComparer.Ordinal)
                    .SequenceEqual(expected.Keys.Order(StringComparer.Ordinal)))
                throw new InvalidDataException("webcam_audio_unknown_staging_contents_preserved");
            foreach (var (name, hash) in expected)
            {
                var path = Path.Combine(Directory, name);
                using var file = File.OpenRead(path);
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0 || Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant() != hash)
                    throw new CryptographicException("webcam_audio_unknown_staging_bytes_preserved");
            }
            foreach (var name in expected.Keys) File.Delete(Path.Combine(Directory, name));
            System.IO.Directory.Delete(Directory, recursive: false);
            if (RootCreated && !System.IO.Directory.EnumerateFileSystemEntries(root).Any()) System.IO.Directory.Delete(root, recursive: false);
        }
        public void Dispose()
        {
            for (int i = held.Count - 1; i >= 0; --i) held[i].Dispose();
            held.Clear(); // Do not delete unknown setup/journal outcomes.
        }
    }

    internal static SafeFileHandle HoldProtected(string path, bool programData)
    {
        // Normal ProgramData grants users concrete child-create/EA/attribute
        // rights. Never repair its ACL: deny write/delete sharing on the held
        // directory instead, blocking the data-write/delete access needed to
        // replace its namespace/reparse point while using that parent. This is
        // not a claim that sharing disables every metadata-only attribute API.
        // A metadata-only open does not participate in Windows data sharing
        // checks. FILE_LIST_DIRECTORY is required for this lease to enforce
        // FILE_SHARE_READ against later data-write/delete opens.
        // Our own protected root/children already deny unprivileged writes by
        // ACL. Permit write sharing there so Windows can atomically rename a
        // child; still deny delete sharing on each held directory itself.
        var handle = CreateFile(path, ReadControl | ReadAttributes | ListDirectory, programData ? ShareReadOnly : ShareReadWrite, IntPtr.Zero, OpenExisting,
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
    internal static bool CreateProtected(string path, bool allowExisting)
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
                return false;
            }
            return true;
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
