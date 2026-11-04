using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

internal sealed partial class DeviceFileNativeDirectory
{
    private const uint CreateOnly = 2, FileSynchronousNoReparse = 0x00200060;

    internal static string ReceiveLeaf(string name)
    {
        if (string.IsNullOrEmpty(name) || name.Length > 255 || name.Contains('\\') || name.Contains('/') ||
            name.Normalize(NormalizationForm.FormC) != name)
            throw DeviceFileControl.Error("file_destination_invalid_leaf");
        _ = NtDirectoryName(@"C:\" + name);
        return name;
    }

    internal T WithHandle<T>(Func<SafeFileHandle, T> action)
    {
        lock (gate)
        {
            _ = CurrentIdentity();
            var result = action(handle);
            try { _ = CurrentIdentity(); return result; }
            catch { if (result is IDisposable resource) resource.Dispose(); throw; }
        }
    }

    private void RequireReceive()
    {
        _ = CurrentIdentity();
        if (!receiveAccess) throw DeviceFileControl.Error("file_destination_receive_handle_required");
    }

    internal Identity CurrentReceiveIdentity()
    {
        lock (gate) { RequireReceive(); return CurrentIdentity(); }
    }

    // Native receiver ownership must be established by the caller before these
    // primitives are used. A path/name or a successful create is not a grant.
    internal DeviceFileNativeDirectory CreateChild(string nativeName)
    {
        var name = ReceiveLeaf(nativeName);
        return WithHandle(parent =>
        {
            RequireReceive();
            return new DeviceFileNativeDirectory(OpenRelative(parent, name, ReadDirectoryAccess | 6,
                ShareDirectory, CreateOnly, DirectorySynchronousNoReparse), true);
        });
    }

    internal DeviceFileNativeStagedFile CreateStagedFile(string nativeName)
    {
        var name = ReceiveLeaf(nativeName);
        return WithHandle(parent =>
        {
            RequireReceive();
            // GENERIC_READ | GENERIC_WRITE | DELETE | SYNCHRONIZE. No shared
            // WRITE/DELETE: other handles cannot edit, link or replace this file.
            return new DeviceFileNativeStagedFile(this, OpenRelative(parent, name, 0xc0110000,
                ShareRead, CreateOnly, FileSynchronousNoReparse));
        });
    }

    internal Identity FileIdentityAt(string nativeName)
    {
        var name = ReceiveLeaf(nativeName);
        return WithHandle(parent =>
        {
            // Verification only. Sharing permits the already-held source
            // handle; that original handle still forbids all other mutation.
            using var file = OpenRelative(parent, name, 0x80100080, 7, OpenOnly, FileSynchronousNoReparse);
            return DeviceFileNativeStagedFile.ReadFile(file).Identity;
        });
    }

    internal Identity? ExistingFileIdentity(string nativeName)
    {
        try { return FileIdentityAt(nativeName); }
        catch (IOException error) when (error.InnerException is Win32Exception { NativeErrorCode: 2 }) { return null; }
    }

    private static SafeFileHandle OpenRelative(SafeFileHandle parent, string name, uint access,
        uint share, uint disposition, uint options)
    {
        var text = Marshal.StringToHGlobalUni(name);
        var pointer = Marshal.AllocHGlobal(Marshal.SizeOf<UnicodeString>());
        var security = IntPtr.Zero;
        try
        {
            if (disposition == CreateOnly)
            {
                if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("file_destination_windows_required");
                using var identity = WindowsIdentity.GetCurrent();
                var user = identity.User?.Value ?? throw DeviceFileControl.Error("file_destination_native_user_required");
                // Do not inherit a permissive Pictures/Videos ACL for uncommitted
                // media bytes. Only this Windows user and SYSTEM can access new
                // staging files/directories; existing directories are untouched.
                var descriptor = "O:" + user + "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;" + user + ")";
                if (!ConvertStringSecurityDescriptorToSecurityDescriptor(descriptor, 1, out security, out _))
                    throw NativeFailure("file_destination_private_security_failed");
            }
            Marshal.StructureToPtr(new UnicodeString { Length = checked((ushort)(name.Length * 2)),
                MaximumLength = checked((ushort)(name.Length * 2 + 2)), Buffer = text }, pointer, false);
            var attributes = new ObjectAttributes { Length = (uint)Marshal.SizeOf<ObjectAttributes>(),
                RootDirectory = parent.DangerousGetHandle(), ObjectName = pointer,
                Attributes = ObjCaseInsensitive | ObjDontReparse, SecurityDescriptor = security };
            var status = NtCreateFile(out var opened, access, ref attributes, out _, IntPtr.Zero,
                0, share, disposition, options, IntPtr.Zero, 0);
            if (status < 0)
            {
                opened?.Dispose();
                throw new IOException("file_destination_relative_open_failed", new Win32Exception((int)RtlNtStatusToDosError(status)));
            }
            return opened;
        }
        finally
        {
            if (security != IntPtr.Zero) _ = LocalFree(security);
            Marshal.FreeHGlobal(pointer); Marshal.FreeHGlobal(text); GC.KeepAlive(parent);
        }
    }

    internal sealed class DeviceFileNativeStagedFile : IDisposable
    {
        private readonly DeviceFileNativeDirectory originalParent;
        private readonly SafeFileHandle file;
        private readonly object fileGate = new();
        private readonly Identity originalIdentity;
        private long written;
        private bool closed, published;
        internal sealed record Observation(Identity Identity, long Size);

        internal DeviceFileNativeStagedFile(DeviceFileNativeDirectory parent, SafeFileHandle file)
        {
            originalParent = parent; this.file = file;
            try
            {
                var observed = ReadFile(file); originalIdentity = observed.Identity;
                if (observed.Size != 0) throw DeviceFileControl.Error("file_destination_new_stage_not_empty");
            }
            catch { file.Dispose(); throw; }
        }

        private void Current()
        {
            ObjectDisposedException.ThrowIf(closed, this);
            _ = originalParent.CurrentIdentity();
            var value = ReadFile(file);
            if (value.Identity != originalIdentity || value.Size != written)
                throw DeviceFileControl.Error("file_destination_stage_changed");
        }

        internal Observation Observe()
        {
            lock (fileGate) { Current(); return ReadFile(file); }
        }

        internal byte[] ReadExact(long offset, int count)
        {
            lock (fileGate)
            {
                Current();
                if (offset < 0 || count < 0 || count > DeviceFileManifest.ChunkBytes || offset > written - count)
                    throw DeviceFileControl.Error("file_destination_stage_read_invalid");
                var result = new byte[count]; var read = 0;
                try
                {
                    while (read < count)
                    {
                        var amount = RandomAccess.Read(file, result.AsSpan(read), offset + read);
                        if (amount == 0) throw DeviceFileControl.Error("file_destination_stage_short_read"); read += amount;
                    }
                    Current(); return result;
                }
                catch { CryptographicOperations.ZeroMemory(result); throw; }
            }
        }

        internal void WriteChunk(long offset, ReadOnlySpan<byte> bytes)
        {
            lock (fileGate)
            {
                Current();
                if (published || offset != written || bytes.Length is < 1 or > DeviceFileManifest.ChunkBytes ||
                    offset > DeviceFileManifest.MaxFileBytes - bytes.Length)
                    throw DeviceFileControl.Error("file_destination_stage_chunk_invalid");
                RandomAccess.Write(file, bytes, offset);
                written += bytes.Length;
                Current();
            }
        }

        // Hash the actual held file, not a sender-supplied digest or an earlier
        // in-memory buffer. Caller's durable prepared-history record must exist
        // BEFORE Publish; an uncertain successful rename is never rolled back.
        internal Observation Publish(DeviceFileNativeDirectory destination, string nativeName,
            long expectedSize, string expectedSha256, Action ensureNative)
        {
            var name = ReceiveLeaf(nativeName);
            if (ensureNative is null || expectedSize is < 0 or > DeviceFileManifest.MaxFileBytes ||
                string.IsNullOrEmpty(expectedSha256) || expectedSha256.Length != 64 || expectedSha256.Any(c => !char.IsAsciiHexDigitLower(c)))
                throw DeviceFileControl.Error("file_destination_publication_invalid");
            lock (fileGate)
            {
                Current();
                if (published || written != expectedSize) throw DeviceFileControl.Error("file_destination_stage_not_complete");
                ensureNative();
                if (!FlushFileBuffers(file)) throw NativeFailure("file_destination_stage_flush_failed");
                using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                var buffer = new byte[DeviceFileManifest.ChunkBytes]; long position = 0;
                try
                {
                    while (position < written)
                    {
                        ensureNative(); Current();
                        var count = RandomAccess.Read(file, buffer.AsSpan(0, (int)Math.Min(buffer.Length, written - position)), position);
                        if (count == 0) throw DeviceFileControl.Error("file_destination_stage_short_read");
                        digest.AppendData(buffer.AsSpan(0, count)); position += count;
                    }
                }
                finally { CryptographicOperations.ZeroMemory(buffer); }
                if (Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != expectedSha256)
                    throw DeviceFileControl.Error("file_destination_stage_hash_changed");
                Current(); ensureNative();
                return destination.WithHandle(parent =>
                {
                    destination.RequireReceive(); Current(); ensureNative();
                    if (destination.OriginalIdentity.VolumeSerial != originalIdentity.VolumeSerial)
                        throw DeviceFileControl.Error("file_destination_same_volume_required");
                    RenameNoReplace(file, parent, name);
                    published = true; // Preserve the file after any later failure.
                    ensureNative();
                    if (!FlushFileBuffers(file)) throw NativeFailure("file_destination_publication_flush_failed");
                    Current();
                    if (destination.FileIdentityAt(name) != originalIdentity)
                        throw DeviceFileControl.Error("file_destination_publication_readback_failed");
                    ensureNative(); return ReadFile(file);
                });
            }
        }

        internal static Observation ReadFile(SafeFileHandle file)
        {
            if (!GetFileInformationByHandle(file, out var info)) throw NativeFailure("file_destination_file_attributes_unavailable");
            if ((info.Attributes & (0x10 | 0x400)) != 0 || info.Links != 1)
                throw DeviceFileControl.Error("file_destination_not_plain_single_file");
            if (!GetFileInformationByHandleEx(file, 18, out var id, (uint)Marshal.SizeOf<FileIdInformation>()) || id.Low == 0 && id.High == 0)
                throw NativeFailure("file_destination_file_identity_unavailable");
            var size = ((ulong)info.SizeHigh << 32) | info.SizeLow;
            if (size > DeviceFileManifest.MaxFileBytes) throw DeviceFileControl.Error("file_destination_file_size_invalid");
            return new(new(id.Volume, id.Low, id.High), (long)size);
        }

        private static void RenameNoReplace(SafeFileHandle file, SafeFileHandle parent, string name)
        {
            var bytes = Encoding.Unicode.GetBytes(name);
            var rootOffset = IntPtr.Size == 8 ? 8 : 4;
            var lengthOffset = rootOffset + IntPtr.Size; var nameOffset = lengthOffset + 4;
            var length = nameOffset + bytes.Length;
            var data = Marshal.AllocHGlobal(length);
            try
            {
                for (var i = 0; i < nameOffset; i++) Marshal.WriteByte(data, i, 0); // ReplaceIfExists = FALSE.
                Marshal.WriteIntPtr(data, rootOffset, parent.DangerousGetHandle());
                Marshal.WriteInt32(data, lengthOffset, bytes.Length); Marshal.Copy(bytes, 0, data + nameOffset, bytes.Length);
                var status = NtSetInformationFile(file, out _, data, (uint)length, 10); // FileRenameInformation.
                if (status < 0) throw new IOException("file_destination_no_replace_failed",
                    new Win32Exception((int)RtlNtStatusToDosError(status)));
            }
            finally { Marshal.FreeHGlobal(data); GC.KeepAlive(parent); }
        }

        public void Dispose()
        {
            lock (fileGate) { if (closed) return; closed = true; file.Dispose(); }
        }
    }

    private static IOException NativeFailure(string code) => new(code, new Win32Exception(Marshal.GetLastWin32Error()));
    [DllImport("ntdll.dll", ExactSpelling = true)]
    private static extern int NtSetInformationFile(SafeFileHandle file, out IoStatusBlock io, IntPtr data, uint length, int kind);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FlushFileBuffers(SafeFileHandle file);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, out uint size);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);
}
