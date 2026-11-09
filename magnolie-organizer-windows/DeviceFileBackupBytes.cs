using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Raw backup object IO only. The catalog must register a new candidate's FID
// BEFORE CopyToNew. These functions never create/adopt a folder, publish, link,
// remove, expire or modify a source. A hash/key is not native mutation authority.
internal static class NativeMediaBackupBytes
{
    // Closed set of actual native inputs. No arbitrary reader callbacks or
    // inheritance can turn metadata into prepared-cache read authority.
    internal sealed class Input
    {
        private readonly DeviceFileNativeDirectory.DeviceFileNativeStagedFile? staged;
        private readonly TelefonStore.NativePreparedMediaSource? prepared;
        private readonly string? version, nonce;
        private Input(DeviceFileNativeDirectory.DeviceFileNativeStagedFile value) { staged = value; }
        private Input(TelefonStore.NativePreparedMediaSource value)
        { prepared = value; version = value.Version; nonce = value.Nonce; }
        internal static Input FromStaged(DeviceFileNativeDirectory.DeviceFileNativeStagedFile value) => new(value);
        internal static Input FromPrepared(TelefonStore.NativePreparedMediaSource value) => new(value);
        private void Current()
        {
            if (prepared is null) return;
            prepared.RequireBackupIdentity(version!, nonce!);
        }
        internal DeviceFileNativeDirectory.Identity? Identity => staged?.Observe().Identity;
        internal byte[] ReadExact(long offset, int count)
        {
            if (staged is not null) return staged.ReadExact(offset, count);
            Current();
            if (offset < 0 || count < 1 || count > DeviceFileManifest.ChunkBytes || offset > prepared!.Manifest.TotalBytes - count)
                throw DeviceFileControl.Error("media_backup_source_range_invalid");
            var result = new byte[count];
            try
            {
                for (var at = 0; at < count;)
                {
                    Current(); var position = offset + at;
                    var chunk = prepared.ReadChunk(checked((int)(position / DeviceFileManifest.ChunkBytes)));
                    try
                    {
                        var start = (int)(position % DeviceFileManifest.ChunkBytes); var size = Math.Min(count - at, chunk.Length - start);
                        if (size < 1) throw DeviceFileControl.Error("media_backup_source_range_invalid");
                        chunk.AsSpan(start, size).CopyTo(result.AsSpan(at)); at += size;
                    }
                    finally { CryptographicOperations.ZeroMemory(chunk); }
                }
                Current(); return result;
            }
            catch { CryptographicOperations.ZeroMemory(result); throw; }
        }
        internal void Verify(long size, string hash, Action native)
        {
            if (staged is not null) { _ = NativeMediaBackupBytes.Verify(staged, size, hash, native); return; }
            native(); Current(); _ = NativeMediaBackupPolicy.ContentKey(size, hash);
            var file = prepared!.Manifest.Files.Single();
            if (file.Size != size || file.Sha256 != hash) throw DeviceFileControl.Error("media_backup_original_content_changed");
            using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (long offset = 0; offset < size;)
            {
                native(); var bytes = ReadExact(offset, (int)Math.Min(DeviceFileManifest.ChunkBytes, size - offset));
                try { digest.AppendData(bytes); offset += bytes.Length; }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            native(); Current();
            if (Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant() != hash)
                throw DeviceFileControl.Error("media_backup_original_content_changed");
        }
    }

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
        => ResumeOwnedCandidate(Input.FromStaged(source), candidate, size, sha256, ensureNative);

    internal static VerifiedRaw ResumeOwnedCandidate(Input source,
        DeviceFileNativeDirectory.DeviceFileNativeStagedFile candidate, long size, string sha256, Action ensureNative)
    {
        source.Verify(size, sha256, ensureNative); var originalIdentity = source.Identity;
        ensureNative(); var target = candidate.Observe();
        if (target.Size > size || target.Identity == originalIdentity) throw DeviceFileControl.Error("media_backup_original_candidate_changed");
        for (long offset = 0; offset < target.Size;)
        {
            ensureNative(); var count = (int)Math.Min(DeviceFileManifest.ChunkBytes, target.Size - offset);
            var expected = source.ReadExact(offset, count); byte[]? actual = null;
            try
            {
                actual = candidate.ReadExact(offset, count);
                if (!CryptographicOperations.FixedTimeEquals(expected, actual)) throw DeviceFileControl.Error("media_backup_original_candidate_changed");
                offset += count;
            }
            finally { CryptographicOperations.ZeroMemory(expected); if (actual is not null) CryptographicOperations.ZeroMemory(actual); }
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
        source.Verify(size, sha256, ensureNative);
        if (copied.Identity != target.Identity || source.Identity != originalIdentity)
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
