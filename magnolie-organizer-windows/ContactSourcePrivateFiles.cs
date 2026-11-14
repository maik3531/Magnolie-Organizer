using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

// Dedicated native consent files only, not a book/profile importer. No default
// creation, account access, cryptographic authority or application callbacks.
// Windows private ownership/ACL and reparse/link checks are mandatory. Unix is
// available solely through the explicit controlled-test constructor switch.
internal sealed class ContactSourcePrivateFiles
{
    private readonly string root;
    private readonly AtomicStore files;
    private static readonly HashSet<string> Names = new(StringComparer.Ordinal)
        { ".key.dpapi", "approval.json", ".transaction", ".save-intent.json" };

    internal ContactSourcePrivateFiles(string nativeRoot, AtomicStore? files = null, bool controlledUnix = false)
    {
        if (!OperatingSystem.IsWindows() && !controlledUnix) throw new PlatformNotSupportedException();
        if (!Path.IsPathFullyQualified(nativeRoot)) throw new ArgumentException("contact_approval_native_root_required");
        root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(nativeRoot));
        this.files = files ?? new AtomicStore();
    }

    internal Session? Open(bool create = false)
    {
        CheckDirectories(root);
        if (!Directory.Exists(root))
        {
            if (!create) return null;
            if (OperatingSystem.IsWindows()) CreateWindowsDirectory(root);
            else Directory.CreateDirectory(root, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        RequirePrivate(new DirectoryInfo(root));
        var lockPath = Path.Combine(root, ".lock");
        var existed = CheckLeaf(lockPath);
        if (!create && !existed && !Names.Any(name => CheckLeaf(Path.Combine(root, name)))) return null;
        FileStream? locked = null;
        try
        {
            locked = new FileStream(lockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None,
                4096, FileOptions.WriteThrough);
            if (!existed)
            {
                if (OperatingSystem.IsWindows()) SetCreatedFileOwner(lockPath);
                else File.SetUnixFileMode(lockPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            CheckOpenedFile(lockPath, locked);
            CheckDirectories(root);
            return new Session(root, locked, files);
        }
        catch { locked?.Dispose(); throw; }
    }

    private static bool CheckLeaf(string path)
    {
        FileAttributes attributes;
        try { attributes = File.GetAttributes(path); }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
        if ((attributes & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0)
            throw new IOException("contact_approval_link_or_nonfile");
        RequirePrivate(new FileInfo(path));
        return true;
    }

    private static void CheckDirectories(string root)
    {
        for (var node = new DirectoryInfo(root); node is not null; node = node.Parent)
        {
            FileAttributes attributes;
            try { attributes = File.GetAttributes(node.FullName); }
            catch (DirectoryNotFoundException) { continue; }
            catch (FileNotFoundException) { continue; }
            if ((attributes & FileAttributes.ReparsePoint) != 0 || (attributes & FileAttributes.Directory) == 0)
                throw new IOException("contact_approval_reparse_directory");
        }
    }

    private static void RequirePrivate(FileSystemInfo node)
    {
        if (OperatingSystem.IsWindows()) RequireWindowsPermissions(node);
        else if ((File.GetUnixFileMode(node.FullName) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute |
                UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0)
            throw new UnauthorizedAccessException("contact_approval_file_not_private");
    }

    private static void CheckOpenedFile(string path, FileStream stream)
    {
        if (!CheckLeaf(path)) throw new IOException("contact_approval_file_changed");
        if (OperatingSystem.IsWindows())
        {
            if (!GetFileInformationByHandle(stream.SafeFileHandle, out var info) || info.NumberOfLinks != 1 ||
                    (info.FileAttributes & ((uint)FileAttributes.ReparsePoint | (uint)FileAttributes.Directory)) != 0)
                throw new IOException("contact_approval_link_or_nonfile");
        }
    }

    [SupportedOSPlatform("windows")]
    private static SecurityIdentifier CurrentUser()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return identity.User ?? throw new UnauthorizedAccessException("contact_approval_native_owner_required");
    }

    [SupportedOSPlatform("windows")]
    private static void CreateWindowsDirectory(string root)
    {
        var user = CurrentUser();
        var security = new DirectorySecurity();
        security.SetOwner(user); security.SetAccessRuleProtection(true, false);
        foreach (var sid in new[] { user, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
                     new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null) })
            security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        new DirectoryInfo(root).Create(security);
    }

    [SupportedOSPlatform("windows")]
    private static void SetCreatedFileOwner(string path)
    {
        // A native-created file need not inherit the current user's owner SID
        // from the directory (e.g. elevated token default owner). Set ONLY the
        // owner of our new file, never repair a pre-existing untrusted file.
        var file = new FileInfo(path);
        var security = file.GetAccessControl(AccessControlSections.Owner);
        security.SetOwner(CurrentUser()); file.SetAccessControl(security);
    }

    [SupportedOSPlatform("windows")]
    private static void RequireWindowsPermissions(FileSystemInfo node)
    {
        FileSystemSecurity security = node is DirectoryInfo directory
            ? directory.GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access)
            : ((FileInfo)node).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access);
        var user = CurrentUser();
        if (!user.Equals(security.GetOwner(typeof(SecurityIdentifier))))
            throw new UnauthorizedAccessException("contact_approval_native_owner_required");
        var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
        var administrators = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
        const FileSystemRights mutation = FileSystemRights.Write | FileSystemRights.Modify | FileSystemRights.Delete |
            FileSystemRights.DeleteSubdirectoriesAndFiles | FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
        foreach (FileSystemAccessRule rule in security.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Allow && (rule.PropagationFlags & PropagationFlags.InheritOnly) == 0 &&
                    (rule.FileSystemRights & mutation) != 0 && !user.Equals(rule.IdentityReference) &&
                    !system.Equals(rule.IdentityReference) && !administrators.Equals(rule.IdentityReference))
                throw new UnauthorizedAccessException("contact_approval_file_not_private");
    }

    internal sealed class Session : IDisposable
    {
        private readonly string root;
        private readonly FileStream locked;
        private readonly AtomicStore files;
        private bool disposed;
        internal Session(string root, FileStream locked, AtomicStore files)
        { this.root = root; this.locked = locked; this.files = files; }

        private string Child(string name)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (!Names.Contains(name)) throw new ArgumentException("contact_approval_private_leaf_required");
            CheckDirectories(root); RequirePrivate(new DirectoryInfo(root));
            CheckOpenedFile(Path.Combine(root, ".lock"), locked);
            return Path.Combine(root, name);
        }

        internal string? Read(string name, int limit)
        {
            if (limit is < 1 or > 256 * 1024) throw new ArgumentOutOfRangeException(nameof(limit));
            var path = Child(name);
            if (!CheckLeaf(path)) return null;
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            CheckOpenedFile(path, stream);
            var bytes = new byte[limit + 1];
            try
            {
                var length = 0;
                while (length < bytes.Length)
                {
                    var read = stream.Read(bytes, length, bytes.Length - length);
                    if (read == 0) break;
                    length += read;
                }
                if (length > limit) throw new IOException("contact_approval_file_too_large");
                CheckOpenedFile(path, stream);
                return new UTF8Encoding(false, true).GetString(bytes, 0, length);
            }
            finally { System.Security.Cryptography.CryptographicOperations.ZeroMemory(bytes); }
        }

        internal void Write(string name, string value, int limit)
        {
            if (limit is < 1 or > 256 * 1024) throw new ArgumentOutOfRangeException(nameof(limit));
            var path = Child(name);
            if (CheckLeaf(path))
            {
                using var existing = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                CheckOpenedFile(path, existing);
            }
            files.Write(path, value, limit);
            // AtomicStore has just replaced this leaf with OUR new temporary.
            if (OperatingSystem.IsWindows()) SetCreatedFileOwner(path);
            else File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            if (Read(name, limit) != value) throw new IOException("contact_approval_private_write_unconfirmed");
        }

        internal void Delete(string name)
        {
            var path = Child(name);
            if (!CheckLeaf(path)) return;
            using (var existing = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) CheckOpenedFile(path, existing);
            File.Delete(path);
        }

        public void Dispose()
        { if (!disposed) { disposed = true; locked.Dispose(); } }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation
    {
        internal uint FileAttributes;
        internal System.Runtime.InteropServices.ComTypes.FILETIME CreationTime, LastAccessTime, LastWriteTime;
        internal uint VolumeSerialNumber, FileSizeHigh, FileSizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation information);
}
