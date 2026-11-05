using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBackupBytesTests
{
    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "magnolie-backup392-" + Guid.NewGuid().ToString("N"));
        internal readonly DeviceFileNativeDirectory Owner;
        internal Fixture() { Directory.CreateDirectory(Root); Owner = DeviceFileNativeDirectory.OpenExistingForReceive(Root); }
        public void Dispose() { Owner.Dispose(); Directory.Delete(Root, true); } // Only the unique synthetic fixture.
    }
    private static string Hash(byte[] value) => Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant();
    private static void Fill(DeviceFileNativeDirectory.DeviceFileNativeStagedFile held, byte[] value)
    {
        for (var offset = 0; offset < value.Length;)
        {
            var count = Math.Min(DeviceFileManifest.ChunkBytes, value.Length - offset);
            held.WriteChunk(offset, value.AsSpan(offset, count)); offset += count;
        }
        _ = held.DurableCheckpoint();
    }

    internal static Task WindowsCopyRestoreAsync()
    {
        using var fixture = new Fixture();
        var raw = RandomNumberGenerator.GetBytes(DeviceFileManifest.ChunkBytes * 2 + 19);
        using var source = fixture.Owner.CreateStagedFile("original.jpg"); Fill(source, raw);
        using var backup = fixture.Owner.CreateStagedFile("object.raw");
        var selected = NativeMediaBackupBytes.CopyToNew(source, backup, raw.Length, Hash(raw), () => { });
        TestAssert.That(selected.Identity != source.Observe().Identity && !selected.GrantsMutationAuthority,
            "Backup shared the mutable source inode or granted write authority.");
        TestAssert.That(selected.ContentKey == NativeMediaBackupPolicy.ContentKey(raw.Length, Hash(raw)), "Content identity changed by name.");
        using var restore = fixture.Owner.CreateStagedFile("new-restored.jpg");
        var restored = NativeMediaBackupBytes.RestoreRawToNew(backup, restore, selected, () => { });
        TestAssert.That(restored.Identity != selected.Identity && restored.Sha256 == Hash(raw), "Restore linked or changed original bytes.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupBytes.RestoreRawToNew(backup, restore, selected, () => { }), "Existing target overwritten.");
        TestAssert.That(NativeMediaBackupBytes.Verify(source, raw.Length, Hash(raw), () => { }).Sha256 == selected.Sha256, "Backup changed active original.");
        // Verification prepares no public target or Saved/END/mapping update.
        TestAssert.That(fixture.Owner.ExistingFileIdentity("published.jpg") is null, "Raw copy published itself.");
        return Task.CompletedTask;
    }

    internal static Task WindowsRejectAsync()
    {
        using var fixture = new Fixture();
        var raw = new byte[] { 1, 2, 3, 4, 5 };
        using var source = fixture.Owner.CreateStagedFile("original.mp4"); Fill(source, raw);
        using var candidate = fixture.Owner.CreateStagedFile("new.raw");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupBytes.CopyToNew(source, candidate, raw.Length, new string('0', 64), () => { }), "Wrong digest copied bytes.");
        TestAssert.That(candidate.Observe().Size == 0, "Failed source verification touched target.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupBytes.CopyToNew(source, source, raw.Length, Hash(raw), () => { }), "Source used as destination.");
        Fill(candidate, new byte[] { 9 });
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupBytes.CopyToNew(source, candidate, raw.Length, Hash(raw), () => { }), "Nonempty candidate overwritten.");
        TestAssert.That(candidate.ReadExact(0, 1)[0] == 9, "Existing candidate data changed.");
        using var other = fixture.Owner.CreateStagedFile("same-bytes-other-inode.raw"); Fill(other, raw);
        var selected = NativeMediaBackupBytes.Verify(source, raw.Length, Hash(raw), () => { });
        using var restore = fixture.Owner.CreateStagedFile("empty-restore.raw");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupBytes.RestoreRawToNew(other, restore, selected, () => { }), "Different inode adopted from matching bytes.");
        TestAssert.That(restore.Observe().Size == 0, "Stale selection touched restore target.");
        return Task.CompletedTask;
    }

    internal static Task WindowsAbortAsync()
    {
        using var fixture = new Fixture();
        var raw = RandomNumberGenerator.GetBytes(DeviceFileManifest.ChunkBytes * 2 + 1);
        using var source = fixture.Owner.CreateStagedFile("original.jpg"); Fill(source, raw);
        using var candidate = fixture.Owner.CreateStagedFile("prepared.raw");
        var canceled = false;
        void Current() { if (candidate.Observe().Size > 0) throw new OperationCanceledException(); }
        try { NativeMediaBackupBytes.CopyToNew(source, candidate, raw.Length, Hash(raw), Current); }
        catch (OperationCanceledException) { canceled = true; }
        TestAssert.That(canceled && candidate.Observe().Size is > 0 && candidate.Observe().Size < raw.Length, "Copy did not stop between bounded chunks.");
        _ = NativeMediaBackupBytes.Verify(source, raw.Length, Hash(raw), () => { });
        TestAssert.Throws<IOException>(() => File.WriteAllBytes(Path.Combine(fixture.Root, "original.jpg"), new byte[] { 0 }), "Held source allowed a concurrent external edit.");
        TestAssert.That(fixture.Owner.ExistingFileIdentity("published.jpg") is null, "Canceled candidate was published.");
        return Task.CompletedTask;
    }

    internal static Task WindowsEmptyAsync()
    {
        using var fixture = new Fixture();
        using var source = fixture.Owner.CreateStagedFile("empty.jpg");
        using var target = fixture.Owner.CreateStagedFile("empty-copy.raw");
        var result = NativeMediaBackupBytes.CopyToNew(source, target, 0, Hash([]), () => { });
        TestAssert.That(result.Size == 0 && result.Identity != source.Observe().Identity, "Empty object identity/verification failed.");
        return Task.CompletedTask;
    }
}
