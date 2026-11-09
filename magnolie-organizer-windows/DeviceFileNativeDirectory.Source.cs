using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows;

internal sealed partial class DeviceFileNativeDirectory
{
    // Explicit original mapping identity only. This does not select arbitrary
    // collection members or confer a phone SEND grant. The composition owner
    // supplies its live saved-book/intent/local-consent guard on every read.
    internal ManagedSource OpenManagedSource(string nativeName, Identity expected, Action requireNative, ulong? expectedCreation = null)
    {
        var name = ReceiveLeaf(nativeName);
        return WithHandle(parent =>
        {
            requireNative();
            var source = new ManagedSource(this,
                OpenRelative(parent, name, 0x80100080, ShareRead, OpenOnly, FileSynchronousNoReparse), expected, requireNative, expectedCreation);
            try { source.Require(); return source; }
            catch { source.Dispose(); throw; }
        });
    }

    internal sealed class ManagedSource : IDisposable
    {
        private readonly object sourceGate = new();
        private readonly DeviceFileNativeDirectory parent;
        private readonly SafeFileHandle file;
        private readonly Identity parentIdentity;
        private readonly DeviceFileNativeStagedFile.Observation original;
        private readonly Action requireNative;
        private readonly ulong? expectedCreation;
        private readonly CollectionSignature? collectionSignature;
        private bool retired;

        internal ManagedSource(DeviceFileNativeDirectory parent, SafeFileHandle file, Identity expected, Action requireNative, ulong? expectedCreation = null)
        {
            this.parent = parent; this.file = file; this.requireNative = requireNative; this.expectedCreation = expectedCreation;
            try
            {
                parentIdentity = parent.CurrentIdentity();
                original = DeviceFileNativeStagedFile.ReadFile(file);
                if (expectedCreation is not null) collectionSignature = ReadCollectionSignature(file);
                if (original.Identity != expected || original.Size is < 1 or > DeviceFileManifest.MaxFileBytes)
                    throw DeviceFileControl.Error("media_source_original_file_required");
                Require();
            }
            catch { retired = true; file.Dispose(); throw; }
        }

        internal long Size => original.Size;
        internal Identity FileIdentity => original.Identity;
        internal CollectionSignature ObserveCollection()
        {
            lock (sourceGate) { Require(); return ReadCollectionSignature(file); }
        }

        internal void Require()
        {
            lock (sourceGate)
            {
                try
                {
                    if (retired || file.IsClosed) throw DeviceFileControl.Error("media_source_retired");
                    requireNative();
                    if (parent.CurrentIdentity() != parentIdentity || DeviceFileNativeStagedFile.ReadFile(file) != original)
                        throw DeviceFileControl.Error("media_source_original_file_changed");
                    if (expectedCreation is ulong creation && ReadCollectionCreation(file) != creation)
                        throw DeviceFileControl.Error("media_collection_file_generation_changed");
                    if (collectionSignature is not null && ReadCollectionSignature(file) != collectionSignature)
                        throw DeviceFileControl.Error("media_collection_original_content_changed");
                    requireNative();
                }
                catch { retired = true; throw; }
            }
        }

        internal byte[] ReadExact(long offset, int count)
        {
            lock (sourceGate)
            {
                Require();
                if (offset < 0 || count is < 1 or > DeviceFileManifest.ChunkBytes || offset > Size - count)
                    throw DeviceFileControl.Error("media_source_read_bounds");
                var result = new byte[count];
                try
                {
                    var read = 0;
                    while (read < count)
                    {
                        Require();
                        var next = RandomAccess.Read(file, result.AsSpan(read), offset + read);
                        if (next == 0) throw DeviceFileControl.Error("media_source_short_read");
                        read += next;
                    }
                    Require(); return result;
                }
                catch { retired = true; CryptographicOperations.ZeroMemory(result); throw; }
            }
        }

        internal bool MatchesPhotoMetadata()
        {
            lock (sourceGate)
            {
                Require();
                var prefix = new byte[(int)Math.Min(Size, PhotoCaptureMetadata.MaximumBytes)];
                try
                {
                    for (var offset = 0; offset < prefix.Length;)
                    {
                        var chunk = ReadExact(offset, Math.Min(DeviceFileManifest.ChunkBytes, prefix.Length - offset));
                        try { chunk.CopyTo(prefix, offset); offset += chunk.Length; }
                        finally { CryptographicOperations.ZeroMemory(chunk); }
                    }
                    Require();
                    var selected = PhotoCaptureMetadata.Matches(prefix);
                    Require(); return selected; // Exclusion is never deletion evidence.
                }
                finally { CryptographicOperations.ZeroMemory(prefix); }
            }
        }

        public void Dispose()
        {
            // Cancellation must retire the permission callback first; closing
            // waits for the actual bounded read to return, not merely UI stop.
            lock (sourceGate) { retired = true; file.Dispose(); }
        }
    }
}
