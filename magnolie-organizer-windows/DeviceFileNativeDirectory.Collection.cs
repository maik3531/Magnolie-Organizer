using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

internal sealed partial class DeviceFileNativeDirectory
{
    internal sealed record CollectionDirectory(string Name, Identity Identity);
    internal sealed record CollectionMember(IReadOnlyList<CollectionDirectory> Parents, string Name, Identity Identity, long Size);
    internal sealed record CollectionInventory(IReadOnlyList<CollectionMember> Members, bool NeedsReview);
    private sealed record CollectionChild(string Name, Identity Identity, long Size, uint Attributes);

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
        internal CollectionSource(ManagedSource source, IReadOnlyList<DeviceFileNativeDirectory> parents)
        { this.source = source; this.parents = parents; }
        internal long Size => source.Size;
        internal Identity FileIdentity => source.FileIdentity;
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
        void Require() { current(); _ = CurrentIdentity(); }
        try
        {
            Require(); var parent = this;
            foreach (var item in member.Parents)
            {
                parent = parent.OpenCollectionDirectory(item.Name, item.Identity, Require); held.Add(parent);
                NativeMediaBackupExclusions.RequireMediaDirectory(parent);
            }
            if (member.Name.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase) ||
                member.Parents.Any(item => item.Name.StartsWith(".magnolie-", StringComparison.OrdinalIgnoreCase)))
                throw DeviceFileControl.Error("media_collection_private_storage_excluded");
            source = parent.OpenManagedSource(member.Name, member.Identity, Require);
            if (source.Size != member.Size) throw DeviceFileControl.Error("media_collection_member_changed");
            Require(); return new(source, held.AsReadOnly());
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
        void Require() { cancellation.ThrowIfCancellationRequested(); current(); _ = CurrentIdentity(); }
        void Walk(DeviceFileNativeDirectory directory, CollectionDirectory[] parents)
        {
            Require();
            foreach (var child in directory.CollectionChildren(Require))
            {
                Require();
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
                    using var nested = directory.OpenCollectionDirectory(child.Name, child.Identity, Require);
                    NativeMediaBackupExclusions.RequireMediaDirectory(nested);
                    Walk(nested, parents.Append(new CollectionDirectory(child.Name, child.Identity)).ToArray());
                }
                else
                {
                    if (child.Size is < 1 or > DeviceFileManifest.MaxFileBytes) { review = true; continue; }
                    // Verify a plain, single-link, unchanged actual handle now;
                    // a later sender must independently reopen the same identity.
                    using var source = directory.OpenManagedSource(child.Name, child.Identity, Require);
                    if (source.Size != child.Size) throw DeviceFileControl.Error("media_collection_member_changed");
                    members.Add(new(Array.AsReadOnly(parents.ToArray()), child.Name, child.Identity, child.Size));
                }
            }
            Require();
        }
        Require(); identities.Add(CurrentIdentity()); Walk(this, []); Require();
        return new(members.AsReadOnly(), review);
    }

    private DeviceFileNativeDirectory OpenCollectionDirectory(string name, Identity expected, Action current)
        => WithHandle(parent =>
        {
            current();
            var child = new DeviceFileNativeDirectory(OpenRelative(parent, ReceiveLeaf(name), ReadDirectoryAccess,
                ShareDirectory, OpenOnly, DirectorySynchronousNoReparse));
            try
            {
                if (child.CurrentIdentity() != expected) throw DeviceFileControl.Error("media_collection_original_directory_required");
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
                            result.Add(new(name, id, BitConverter.ToInt64(bytes, offset + 40), BitConverter.ToUInt32(bytes, offset + 56)));
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
}
