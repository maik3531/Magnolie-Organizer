using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileNativeReceiveTests
{
    internal static Task LeafGrammarAsync()
    {
        foreach (var valid in new[] { "photo.jpg", "Film 2026.mp4", ".magnolie-stage-123", "Bäume.png" })
            TestAssert.That(DeviceFileNativeDirectory.ReceiveLeaf(valid) == valid, "Native leaf was reinterpreted.");
        foreach (var invalid in new[] { "", ".", "..", @"a\b", "a/b", "C:photo", "x:stream", "CON.jpg", "NUL", "COM¹.jpg",
            "tail.", "tail ", "a\0b", "a\nb", "*", "cafe\u0301.jpg", new string('a', 256) })
            TestAssert.Throws<InvalidDataException>(() => DeviceFileNativeDirectory.ReceiveLeaf(invalid), "Invalid native leaf admitted: " + invalid);
        if (!OperatingSystem.IsWindows())
            TestAssert.Throws<PlatformNotSupportedException>(() => DeviceFileNativeDirectory.OpenExistingForReceive(@"C:\Synthetic"), "Non-Windows created a receive owner.");
        return Task.CompletedTask;
    }

    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "magnolie-receive-" + Guid.NewGuid().ToString("N"));
        internal readonly DeviceFileNativeDirectory Destination;
        internal Fixture()
        {
            Directory.CreateDirectory(Root);
            Destination = DeviceFileNativeDirectory.OpenExistingForReceive(Root);
        }
        public void Dispose() { Destination.Dispose(); Directory.Delete(Root, true); } // This fixture's own files only.
    }
    private static string Sha(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static byte[] ReadShared(string path)
    {
        using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var output = new MemoryStream(); source.CopyTo(output); return output.ToArray();
    }

    internal static Task WindowsPublicationAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        using var f = new Fixture();
        using var stage = f.Destination.CreateChild("stage");
        using var file = stage.CreateStagedFile("payload");
        using var user = WindowsIdentity.GetCurrent(); var sid = user.User!.Value;
        var directorySecurity = new DirectoryInfo(Path.Combine(f.Root, "stage")).GetAccessControl();
        var fileSecurity = new FileInfo(Path.Combine(f.Root, "stage", "payload")).GetAccessControl();
        foreach (var security in new FileSystemSecurity[] { directorySecurity, fileSecurity })
        {
            TestAssert.That(security.AreAccessRulesProtected, "Stage inherited a potentially public parent ACL.");
            var rules = security.GetAccessRules(true, true, typeof(SecurityIdentifier)).Cast<FileSystemAccessRule>().ToArray();
            TestAssert.That(rules.Length > 0, "Stage has no explicit private ACL.");
            foreach (var rule in rules)
                TestAssert.That(rule.AccessControlType == AccessControlType.Allow &&
                    (rule.IdentityReference.Value == sid || rule.IdentityReference.Value == "S-1-5-18"), "Stage was exposed to another Windows identity.");
        }
        var bytes = "hello native bytes"u8.ToArray(); file.WriteChunk(0, bytes);
        TestAssert.Throws<IOException>(() => stage.CreateStagedFile("payload"), "Existing stage payload was reopened/truncated.");
        TestAssert.Throws<IOException>(() => f.Destination.CreateChild("stage"), "Existing directory was silently adopted.");
        File.WriteAllText(Path.Combine(f.Root, "photo.jpg"), "keep user bytes");
        TestAssert.Throws<IOException>(() => file.Publish(f.Destination, "photo.jpg", bytes.Length, Sha(bytes), () => { }), "Publication overwrote an existing file.");
        TestAssert.That(File.ReadAllText(Path.Combine(f.Root, "photo.jpg")) == "keep user bytes", "Collision changed user bytes.");
        TestAssert.That(ReadShared(Path.Combine(f.Root, "stage", "payload")).SequenceEqual(bytes), "Collision discarded staged bytes.");
        var identity = file.Publish(f.Destination, "new-photo.jpg", bytes.Length, Sha(bytes), () => { });
        TestAssert.That(identity.Size == bytes.Length && f.Destination.FileIdentityAt("new-photo.jpg") == identity.Identity, "Published native identity mismatched.");
        TestAssert.That(ReadShared(Path.Combine(f.Root, "new-photo.jpg")).SequenceEqual(bytes) && !File.Exists(Path.Combine(f.Root, "stage", "payload")), "Published bytes/path not verified.");
        TestAssert.Throws<InvalidDataException>(() => file.WriteChunk(bytes.Length, new byte[] { 1 }), "Published file remained writable through the staging API.");
        TestAssert.Throws<InvalidDataException>(() => file.Publish(f.Destination, "replayed.jpg", bytes.Length, Sha(bytes), () => { }), "Publication replayed an old staged object.");
        return Task.CompletedTask;
    }

    internal static Task WindowsVerificationAsync()
    {
        using var f = new Fixture();
        var readOnlyPath = Path.Combine(f.Root, "readonly"); Directory.CreateDirectory(readOnlyPath);
        using var readOnly = DeviceFileNativeDirectory.OpenExisting(readOnlyPath);
        TestAssert.Throws<InvalidDataException>(() => readOnly.CreateChild("not-created"), "Read-only native root allowed creation.");
        TestAssert.That(!Directory.Exists(Path.Combine(readOnlyPath, "not-created")), "Read-only failure wrote a directory.");
        using var stage = f.Destination.CreateChild("stage"); using var file = stage.CreateStagedFile("payload");
        var bytes = "hello"u8.ToArray(); file.WriteChunk(0, bytes);
        TestAssert.Throws<InvalidDataException>(() => file.WriteChunk(0, bytes), "Out-of-order chunk rewrote staged bytes.");
        TestAssert.Throws<InvalidDataException>(() => file.Publish(f.Destination, "wrong-size.jpg", 6, Sha(bytes), () => { }), "Wrong expected size published.");
        TestAssert.Throws<InvalidDataException>(() => file.Publish(f.Destination, "wrong-hash.jpg", 5, new string('0', 64), () => { }), "Wrong expected hash published.");
        TestAssert.Throws<InvalidOperationException>(() => file.Publish(f.Destination, "revoked.jpg", 5, Sha(bytes), () => throw new InvalidOperationException("revoked native owner")), "Withdrawn native owner published.");
        TestAssert.That(!File.Exists(Path.Combine(f.Root, "wrong-size.jpg")) && !File.Exists(Path.Combine(f.Root, "wrong-hash.jpg")) && !File.Exists(Path.Combine(f.Root, "revoked.jpg")), "Rejected publication created a visible file.");
        TestAssert.That(ReadShared(Path.Combine(f.Root, "stage", "payload")).SequenceEqual(bytes), "Rejected verification discarded staged bytes.");
        return Task.CompletedTask;
    }

    internal static Task WindowsUncertainAndReparseAsync()
    {
        using var f = new Fixture();
        using var stage = f.Destination.CreateChild("stage"); using var file = stage.CreateStagedFile("payload");
        var bytes = "hello"u8.ToArray(); file.WriteChunk(0, bytes);
        TestAssert.Throws<IOException>(() => File.Move(Path.Combine(f.Root, "stage", "payload"), Path.Combine(f.Root, "raced")), "An unrelated handle could rename the owned stage file.");
        TestAssert.Throws<IOException>(() => File.WriteAllText(Path.Combine(f.Root, "stage", "payload"), "edited"), "An unrelated writer could change the owned stage file.");
        var alias = Path.Combine(f.Root, "alias.jpg"); File.CreateSymbolicLink(alias, Path.Combine(f.Root, "elsewhere.jpg"));
        TestAssert.Throws<IOException>(() => file.Publish(f.Destination, "alias.jpg", 5, Sha(bytes), () => { }), "Publication replaced/followed a reparse entry.");
        TestAssert.That(!File.Exists(Path.Combine(f.Root, "elsewhere.jpg")), "A reparse target was modified.");
        var after = false;
        TestAssert.Throws<InvalidOperationException>(() => file.Publish(f.Destination, "uncertain.jpg", 5, Sha(bytes), () =>
        {
            if (File.Exists(Path.Combine(f.Root, "uncertain.jpg"))) { after = true; throw new InvalidOperationException("post-rename native withdrawal"); }
        }), "Post-rename native withdrawal was ignored.");
        TestAssert.That(after && ReadShared(Path.Combine(f.Root, "uncertain.jpg")).SequenceEqual(bytes), "Uncertain publication discarded visible bytes.");
        TestAssert.Throws<InvalidDataException>(() => file.Publish(f.Destination, "again.jpg", 5, Sha(bytes), () => { }), "Uncertain publication could be replayed.");
        return Task.CompletedTask;
    }

    internal static Task WindowsManagedSourceAsync()
    {
        using var f = new Fixture();
        var path = Path.Combine(f.Root, "managed.jpg");
        var bytes = new byte[DeviceFileManifest.ChunkBytes + 37]; RandomNumberGenerator.Fill(bytes);
        File.WriteAllBytes(path, bytes); File.WriteAllText(Path.Combine(f.Root, "other.jpg"), "not the mapped file");
        var original = f.Destination.FileIdentityAt("managed.jpg");
        var other = f.Destination.FileIdentityAt("other.jpg");
        TestAssert.Throws<InvalidDataException>(() => f.Destination.OpenManagedSource("managed.jpg", other, () => { }),
            "A different mapping identity opened the local source.");
        // An intentional edit of the mapped inode BEFORE native source capture
        // is allowed. Historical incoming bytes are not the outgoing PC version.
        bytes[0] ^= 0xff; File.WriteAllBytes(path, bytes);
        var allowed = true;
        using (var source = f.Destination.OpenManagedSource("managed.jpg", original, () =>
        {
            if (!allowed) throw new InvalidOperationException("original native source owner retired");
        }))
        {
            TestAssert.That(source.Size == bytes.Length && source.FileIdentity == original, "Source did not hold the mapped inode.");
            var first = source.ReadExact(0, DeviceFileManifest.ChunkBytes);
            var last = source.ReadExact(DeviceFileManifest.ChunkBytes, 37);
            TestAssert.That(first.Concat(last).SequenceEqual(bytes), "Native source changed the current PC bytes.");
            TestAssert.Throws<IOException>(() => File.WriteAllBytes(path, "replace"u8.ToArray()), "An unrelated writer edited the held source.");
            TestAssert.Throws<IOException>(() => File.Move(path, Path.Combine(f.Root, "renamed.jpg")), "The held original source was renamed.");
            foreach (var (offset, count) in new (long, int)[] { (-1, 1), (0, 0), (0, DeviceFileManifest.ChunkBytes + 1), (bytes.Length, 1), (long.MaxValue, 2) })
                TestAssert.Throws<InvalidDataException>(() => source.ReadExact(offset, count), "Unbounded native source read.");
            allowed = false;
            TestAssert.Throws<InvalidOperationException>(() => source.ReadExact(0, 1), "Withdrawn native owner returned source bytes.");
            allowed = true;
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Retired source revived after owner replacement.");
        }
        var alias = Path.Combine(f.Root, "alias-source.jpg"); File.CreateSymbolicLink(alias, path);
        TestAssert.Throws<InvalidDataException>(() => f.Destination.OpenManagedSource("alias-source.jpg", original, () => { }),
            "Native source followed a reparse entry.");
        TestAssert.That(File.ReadAllBytes(path).SequenceEqual(bytes), "Source inspection changed the original file.");
        return Task.CompletedTask;
    }

    internal static async Task WindowsManagedSourceDrainAsync()
    {
        using var f = new Fixture(); File.WriteAllText(Path.Combine(f.Root, "mapped.jpg"), "source");
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        var block = false; var canceled = false;
        using var source = f.Destination.OpenManagedSource("mapped.jpg", f.Destination.FileIdentityAt("mapped.jpg"), () =>
        {
            if (Volatile.Read(ref block))
            {
                entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(5))) throw new TimeoutException("source read fixture deadline");
                if (Volatile.Read(ref canceled)) throw new OperationCanceledException("source owner stopped");
            }
        });
        Volatile.Write(ref block, true);
        var read = Task.Run(() => TestAssert.Throws<OperationCanceledException>(() => source.ReadExact(0, 1), "Canceled read returned source bytes."));
        Task? drain = null;
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(5)), "Native source read did not enter.");
            Volatile.Write(ref canceled, true);
            drain = Task.Run(source.Dispose);
            await Task.Delay(50);
            TestAssert.That(!read.IsCompleted && !drain.IsCompleted, "UI stop/disposal claimed an undrained source read.");
        }
        finally { release.Set(); await read; if (drain is not null) await drain; }
        TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Disposed source was reused.");
    }

    internal static Task WindowsManagedSourceMetadataAsync()
    {
        using var f = new Fixture();
        var capture = new byte[PhotoCaptureMetadata.MaximumBytes + 100];
        PhotoCaptureMetadataTests.Jpeg().CopyTo(capture, 0);
        File.WriteAllBytes(Path.Combine(f.Root, "renamed.bin"), capture);
        File.WriteAllBytes(Path.Combine(f.Root, "IMG_camera.jpg"), new byte[] { 255, 216, 255, 217 });
        using (var source = f.Destination.OpenManagedSource("renamed.bin", f.Destination.FileIdentityAt("renamed.bin"), () => { }))
            TestAssert.That(source.MatchesPhotoMetadata(), "Real capture metadata in a renamed mapped PC source was excluded.");
        using (var unknown = f.Destination.OpenManagedSource("IMG_camera.jpg", f.Destination.FileIdentityAt("IMG_camera.jpg"), () => { }))
            TestAssert.That(!unknown.MatchesPhotoMetadata(), "A camera filename without actual EXIF was admitted.");
        var active = false; var checks = 0;
        using (var source = f.Destination.OpenManagedSource("renamed.bin", f.Destination.FileIdentityAt("renamed.bin"), () =>
        {
            if (active && ++checks == 8) throw new InvalidOperationException("native owner retired during metadata read");
        }))
        {
            active = true;
            TestAssert.Throws<InvalidOperationException>(() => source.MatchesPhotoMetadata(), "Metadata selection ignored source-owner retirement.");
            active = false;
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Failed metadata source became a new read grant.");
        }
        TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, "renamed.bin")).SequenceEqual(capture), "Metadata filter changed the mapped original.");
        return Task.CompletedTask;
    }
}
