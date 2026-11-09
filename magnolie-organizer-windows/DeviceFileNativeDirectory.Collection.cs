using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

internal sealed partial class DeviceFileNativeDirectory
{
    internal sealed record CollectionDirectory(string Name, Identity Identity, ulong CreationFileTime);
    internal sealed record CollectionMember(IReadOnlyList<CollectionDirectory> Parents, string Name, Identity Identity, long Size, ulong CreationFileTime);
    internal sealed record CollectionInventory(IReadOnlyList<CollectionMember> Members, bool NeedsReview);
    private sealed record CollectionChild(string Name, Identity Identity, long Size, uint Attributes, ulong CreationFileTime);

    // Read-only native content position, not a publication or transfer grant.
    // Access time is deliberately excluded: our own reads may update it.
    internal sealed record CollectionSignature(Identity Identity, long Size, long Creation, long LastWrite, long Change, uint Attributes);
    [StructLayout(LayoutKind.Sequential)]
    private struct CollectionBasicInformation
    {
        internal long Creation, LastAccess, LastWrite, Change;
        internal uint Attributes;
    }
    private static CollectionSignature ReadCollectionSignature(SafeFileHandle file)
    {
        var observed = DeviceFileNativeStagedFile.ReadFile(file);
        if (!GetCollectionBasicInformation(file, 0, out var basic, (uint)Marshal.SizeOf<CollectionBasicInformation>()))
            throw new IOException("media_collection_signature_unavailable", new Win32Exception(Marshal.GetLastWin32Error()));
        return new(observed.Identity, observed.Size, basic.Creation, basic.LastWrite, basic.Change, basic.Attributes);
    }

    // An additional generation witness, not a globally unique ID or deletion
    // proof. A changed/missing witness must never silently inherit history.
    private static ulong ReadCollectionCreation(SafeFileHandle file)
    {
        if (!GetFileInformationByHandle(file, out var info))
            throw new IOException("media_collection_generation_unavailable", new Win32Exception(Marshal.GetLastWin32Error()));
        var result = ((ulong)(uint)info.Creation.dwHighDateTime << 32) | (uint)info.Creation.dwLowDateTime;
        if (result == 0) throw DeviceFileControl.Error("media_collection_generation_required");
        return result;
    }

    internal ulong CurrentCollectionCreationFileTime()
    {
        _ = CurrentCollectionSourceIdentity();
        return WithHandle(ReadCollectionCreation);
    }

    internal Identity CurrentCollectionSourceIdentity()
    {
        if (receiveAccess) throw DeviceFileControl.Error("media_collection_readonly_source_required");
        RequireCollectionDirectory(NativePath, VolumePath);
        return CurrentIdentity();
    }

    internal static void RequireCollectionDirectory(string path, string volumePath)
    {
        NativeMediaBackupExclusions.RequireMediaDirectory(path, volumePath);
        if (path.Split('\\').Concat(volumePath.Split('\\')).Any(item => item.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase)))
            throw DeviceFileControl.Error("media_collection_private_storage_excluded");
    }

    internal sealed class CollectionSource : IDisposable
    {
        private readonly ManagedSource source;
        private readonly IReadOnlyList<DeviceFileNativeDirectory> parents;
        internal ulong CreationFileTime { get; }
        internal CollectionSource(ManagedSource source, IReadOnlyList<DeviceFileNativeDirectory> parents, ulong creation)
        { this.source = source; this.parents = parents; CreationFileTime = creation; }
        internal long Size => source.Size;
        internal Identity FileIdentity => source.FileIdentity;
        internal CollectionSignature Observe() => source.ObserveCollection();
        internal void Require() => source.Require();
        internal byte[] ReadExact(long offset, int count) => source.ReadExact(offset, count);
        internal bool MatchesPhotoMetadata() => source.MatchesPhotoMetadata();
        public void Dispose()
        {
            try { source.Dispose(); }
            finally { for (var index = parents.Count - 1; index >= 0; index--) parents[index].Dispose(); }
        }
    }

    internal CollectionSource OpenCollectionMember(CollectionMember member, Action current)
    {
        if (member.Parents.Count > 16) throw DeviceFileControl.Error("media_collection_inventory_bound");
        _ = CurrentCollectionSourceIdentity(); NativeMediaBackupExclusions.RequireMediaDirectory(this);
        var held = new List<DeviceFileNativeDirectory>(); ManagedSource? source = null;
        var rootCreation = CurrentCollectionCreationFileTime();
        void Require()
        {
            current(); _ = CurrentIdentity();
            if (CurrentCollectionCreationFileTime() != rootCreation) throw DeviceFileControl.Error("media_collection_root_generation_changed");
            for (var index = 0; index < held.Count; index++)
                if (held[index].CurrentCollectionCreationFileTime() != member.Parents[index].CreationFileTime)
                    throw DeviceFileControl.Error("media_collection_directory_generation_changed");
        }
        try
        {
            Require(); var parent = this;
            foreach (var item in member.Parents)
            {
                parent = parent.OpenCollectionDirectory(item.Name, item.Identity, item.CreationFileTime, Require); held.Add(parent);
                NativeMediaBackupExclusions.RequireMediaDirectory(parent);
            }
            if (member.Name.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase) ||
                member.Parents.Any(item => item.Name.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase)))
                throw DeviceFileControl.Error("media_collection_private_storage_excluded");
            source = parent.OpenManagedSource(member.Name, member.Identity, Require, member.CreationFileTime);
            if (source.Size != member.Size) throw DeviceFileControl.Error("media_collection_member_changed");
            Require(); return new(source, held.AsReadOnly(), member.CreationFileTime);
        }
        catch
        {
            source?.Dispose();
            for (var index = held.Count - 1; index >= 0; index--) held[index].Dispose();
            throw;
        }
    }

    // Read-only local source discovery. Nothing here is a phone reference,
    // consent, stable completed snapshot, absence evidence or send grant.
    // The caller must retain this root and independently fence book/intent/peer.
    internal CollectionInventory InventoryCollection(Action current, CancellationToken cancellation,
        int maximumEntries = 4096, int maximumDepth = 16)
    {
        if (maximumEntries is < 1 or > 4096 || maximumDepth is < 0 or > 16)
            throw DeviceFileControl.Error("media_collection_inventory_bound");
        _ = CurrentCollectionSourceIdentity(); NativeMediaBackupExclusions.RequireMediaDirectory(this);
        var members = new List<CollectionMember>(); var count = 0; var review = false;
        var identities = new HashSet<Identity>();
        var rootCreation = CurrentCollectionCreationFileTime();
        void Require()
        {
            cancellation.ThrowIfCancellationRequested(); current(); _ = CurrentIdentity();
            if (CurrentCollectionCreationFileTime() != rootCreation) throw DeviceFileControl.Error("media_collection_root_generation_changed");
        }
        void Walk(DeviceFileNativeDirectory directory, CollectionDirectory[] parents, ulong creation)
        {
            void DirectoryCurrent()
            {
                Require();
                if (directory.CurrentCollectionCreationFileTime() != creation) throw DeviceFileControl.Error("media_collection_directory_generation_changed");
            }
            DirectoryCurrent();
            foreach (var child in directory.CollectionChildren(DirectoryCurrent))
            {
                DirectoryCurrent();
                if (++count > maximumEntries) throw DeviceFileControl.Error("media_collection_inventory_bound");
                // Private backup/trash/staging names are never source material.
                // These deny-only exclusions do not prove ownership or deletion.
                if (child.Name.Equals("Backup", StringComparison.OrdinalIgnoreCase) ||
                    child.Name.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase)) continue;
                if ((child.Attributes & 0x400) != 0) { review = true; continue; }
                if (!identities.Add(child.Identity)) throw DeviceFileControl.Error("media_collection_ambiguous_identity");
                if ((child.Attributes & 0x10) != 0)
                {
                    if (parents.Length >= maximumDepth) throw DeviceFileControl.Error("media_collection_inventory_bound");
                    using var nested = directory.OpenCollectionDirectory(child.Name, child.Identity, child.CreationFileTime, DirectoryCurrent);
                    NativeMediaBackupExclusions.RequireMediaDirectory(nested);
                    Walk(nested, parents.Append(new CollectionDirectory(child.Name, child.Identity, child.CreationFileTime)).ToArray(), child.CreationFileTime);
                }
                else
                {
                    if (child.Size is < 1 or > DeviceFileManifest.MaxFileBytes) { review = true; continue; }
                    // Verify a plain, single-link, unchanged actual handle now;
                    // a later sender must independently reopen the same identity.
                    using var source = directory.OpenManagedSource(child.Name, child.Identity, DirectoryCurrent, child.CreationFileTime);
                    if (source.Size != child.Size) throw DeviceFileControl.Error("media_collection_member_changed");
                    members.Add(new(Array.AsReadOnly(parents.ToArray()), child.Name, child.Identity, child.Size, child.CreationFileTime));
                }
            }
            DirectoryCurrent();
        }
        Require(); identities.Add(CurrentIdentity()); Walk(this, [], rootCreation); Require();
        return new(members.AsReadOnly(), review);
    }

    private DeviceFileNativeDirectory OpenCollectionDirectory(string name, Identity expected, ulong creation, Action current)
        => WithHandle(parent =>
        {
            current();
            var child = new DeviceFileNativeDirectory(OpenRelative(parent, ReceiveLeaf(name), ReadDirectoryAccess,
                ShareDirectory, OpenOnly, DirectorySynchronousNoReparse));
            try
            {
                if (child.CurrentIdentity() != expected || child.CurrentCollectionCreationFileTime() != creation)
                    throw DeviceFileControl.Error("media_collection_original_directory_required");
                current(); return child;
            }
            catch { child.Dispose(); throw; }
        });

    private IReadOnlyList<CollectionChild> CollectionChildren(Action current)
        => WithHandle(parent =>
        {
            const int capacity = 65536;
            var bytes = new byte[capacity]; var buffer = Marshal.AllocHGlobal(capacity);
            var result = new List<CollectionChild>(); var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            try
            {
                var restart = true;
                while (true)
                {
                    current(); Array.Clear(bytes); Marshal.Copy(bytes, 0, buffer, bytes.Length);
                    // FILE_ID_EXTD_DIR_INFO, fixed header88, full128-bit file ID.
                    // A directory handle's enumeration cursor is protected by gate.
                    if (!GetCollectionInformation(parent, restart ? 20 : 19, buffer, capacity))
                    {
                        var error = Marshal.GetLastWin32Error();
                        if (error == 18) break; // ERROR_NO_MORE_FILES, not absence/deletion proof.
                        throw new IOException("media_collection_enumeration_failed", new Win32Exception(error));
                    }
                    restart = false; Marshal.Copy(buffer, bytes, 0, bytes.Length);
                    for (var offset = 0; ;)
                    {
                        current();
                        if (offset > capacity - 88) throw DeviceFileControl.Error("media_collection_directory_record_invalid");
                        var next = BitConverter.ToUInt32(bytes, offset); var length = BitConverter.ToUInt32(bytes, offset + 60);
                        if (length is < 2 or > 510 || length % 2 != 0 || length > capacity - offset - 88 ||
                            next != 0 && (next % 8 != 0 || next < 88 + length || next > capacity - offset - 88))
                            throw DeviceFileControl.Error("media_collection_directory_record_invalid");
                        var name = Encoding.Unicode.GetString(bytes, offset + 88, (int)length);
                        if (name is not ("." or ".."))
                        {
                            _ = ReceiveLeaf(name);
                            if (!names.Add(name) || result.Count >= 4096) throw DeviceFileControl.Error("media_collection_inventory_bound");
                            var id = new Identity(OriginalIdentity.VolumeSerial, BitConverter.ToUInt64(bytes, offset + 72), BitConverter.ToUInt64(bytes, offset + 80));
                            if (id.FileIdLow == 0 && id.FileIdHigh == 0) throw DeviceFileControl.Error("media_collection_identity_required");
                            result.Add(new(name, id, BitConverter.ToInt64(bytes, offset + 40), BitConverter.ToUInt32(bytes, offset + 56), BitConverter.ToUInt64(bytes, offset + 8)));
                        }
                        if (next == 0) break;
                        offset += (int)next;
                    }
                }
                current(); return result;
            }
            finally { Array.Clear(bytes); Marshal.Copy(bytes, 0, buffer, bytes.Length); Marshal.FreeHGlobal(buffer); }
        });

    [DllImport("kernel32.dll", EntryPoint = "GetFileInformationByHandleEx", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetCollectionInformation(SafeFileHandle file, int infoClass, IntPtr information, int length);

    [DllImport("kernel32.dll", EntryPoint = "GetFileInformationByHandleEx", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetCollectionBasicInformation(SafeFileHandle file, int infoClass, out CollectionBasicInformation information, uint length);
}
