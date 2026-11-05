using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Raw backup object IO only. The catalog must register a new candidate's FID
// BEFORE CopyToNew. These functions never create/adopt a folder, publish, link,
// remove, expire or modify a source. A hash/key is not native mutation authority.
internal static class NativeMediaBackupBytes
{
    internal sealed record VerifiedRaw(DeviceFileNativeDirectory.Identity Identity, long Size, string Sha256)
    {
        internal string ContentKey => NativeMediaBackupPolicy.ContentKey(Size, Sha256);
        internal bool GrantsMutationAuthority => false;
    }

    internal static VerifiedRaw Verify(DeviceFileNativeDirectory.DeviceFileNativeStagedFile held,
        long expectedSize, string expectedSha256, Action ensureNative)
    {
        _ = NativeMediaBackupPolicy.ContentKey(expectedSize, expectedSha256);
        ArgumentNullException.ThrowIfNull(ensureNative);
        ensureNative(); var before = held.Observe();
        if (before.Size != expectedSize) throw DeviceFileControl.Error("media_backup_original_content_changed");
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        for (long offset = 0; offset < expectedSize;)
        {
            ensureNative();
            var bytes = held.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, expectedSize - offset));
            try { hash.AppendData(bytes); offset += bytes.Length; }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }
        ensureNative();
        if (held.Observe() != before || Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant() != expectedSha256)
            throw DeviceFileControl.Error("media_backup_original_content_changed");
        return new(before.Identity, expectedSize, expectedSha256);
    }

    internal static VerifiedRaw CopyToNew(DeviceFileNativeDirectory.DeviceFileNativeStagedFile source,
        DeviceFileNativeDirectory.DeviceFileNativeStagedFile candidate, long size, string sha256, Action ensureNative)
    {
        var original = Verify(source, size, sha256, ensureNative);
        ensureNative(); var target = candidate.Observe();
        if (target.Size != 0 || target.Identity == original.Identity)
            throw DeviceFileControl.Error("media_backup_new_candidate_required");
        return ResumeOwnedCandidate(source, candidate, size, sha256, ensureNative);
    }

    // Only an exact candidate FID already registered by the protected catalog.
    // Verify all existing prefix bytes; never truncate or adopt arbitrary data.
    internal static VerifiedRaw ResumeOwnedCandidate(DeviceFileNativeDirectory.DeviceFileNativeStagedFile source,
        DeviceFileNativeDirectory.DeviceFileNativeStagedFile candidate, long size, string sha256, Action ensureNative)
    {
        var original = Verify(source, size, sha256, ensureNative);
        ensureNative(); var target = candidate.Observe();
        if (target.Size > size || target.Identity == original.Identity) throw DeviceFileControl.Error("media_backup_original_candidate_changed");
        for (long offset = 0; offset < target.Size;)
        {
            ensureNative(); var count = (int)Math.Min(DeviceFileManifest.ChunkBytes, target.Size - offset);
            var expected = source.ReadExact(offset, count); var actual = candidate.ReadExact(offset, count);
            try
            {
                if (!CryptographicOperations.FixedTimeEquals(expected, actual)) throw DeviceFileControl.Error("media_backup_original_candidate_changed");
                offset += count;
            }
            finally { CryptographicOperations.ZeroMemory(expected); CryptographicOperations.ZeroMemory(actual); }
        }
        for (long offset = target.Size; offset < size;)
        {
            ensureNative();
            var bytes = source.ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, size - offset));
            try { ensureNative(); candidate.WriteChunk(offset, bytes); offset += bytes.Length; }
            finally { CryptographicOperations.ZeroMemory(bytes); }
        }
        ensureNative();
        var checkpoint = candidate.DurableCheckpoint();
        if (checkpoint.Size != size || checkpoint.Sha256 != sha256)
            throw DeviceFileControl.Error("media_backup_candidate_content_changed");
        var copied = Verify(candidate, size, sha256, ensureNative); // Read real disk bytes, not just write buffers.
        if (copied.Identity != target.Identity || Verify(source, size, sha256, ensureNative) != original)
            throw DeviceFileControl.Error("media_backup_original_content_changed");
        ensureNative(); return copied;
    }

    internal static VerifiedRaw RestoreRawToNew(DeviceFileNativeDirectory.DeviceFileNativeStagedFile source,
        DeviceFileNativeDirectory.DeviceFileNativeStagedFile candidate, VerifiedRaw selected, Action ensureNative)
    {
        ArgumentNullException.ThrowIfNull(selected);
        if (Verify(source, selected.Size, selected.Sha256, ensureNative) != selected)
            throw DeviceFileControl.Error("media_backup_original_representation_changed");
        return CopyToNew(source, candidate, selected.Size, selected.Sha256, ensureNative);
    }
}
