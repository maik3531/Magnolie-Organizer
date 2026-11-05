using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBackupCatalogTests
{
    private static readonly byte[] Data = "original photo and EXIF remain unchanged"u8.ToArray();
    private static string Folder(DeviceFileReceiveJobTests.Fixture f) => Path.Combine(f.Root, "Backup");
    private static (string JobId, string Version, string Phase) Job(DeviceFileReceiveJobTests.Fixture f)
        => f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Last();
    private static NativeMediaBackupVersion Save(DeviceFileReceiveJobTests.Fixture f, string fileId = "00000000000000000000000000000001", Func<bool>? permit = null)
    {
        var job = Job(f);
        return f.Native.Store.SaveNativeMediaBackup(f.Native.Peer.Id, job.JobId, job.Version, fileId, permit ?? (() => true), createBackup: true);
    }
    private static async Task Seed(DeviceFileReceiveJobTests.Fixture f, byte[]? raw = null)
    {
        raw ??= Data;
        var run = await DeviceFileAlbumTests.Preview(f, f.Manifest(("first.jpg", raw), ("second.jpg", raw)), new string('e', 64), "Kamera");
        if (raw.Length <= DeviceFileManifest.ChunkBytes) { await DeviceFileAlbumTests.Copy(f, run, [raw, raw]); return; }
        DeviceFileConnectionRunsTests.Clear(f);
        var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        var index = 0;
        for (var file = 0; file < 2; file++)
            for (var at = 0; at < raw.Length; at += DeviceFileManifest.ChunkBytes)
            {
                var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index++);
                await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, raw[at..Math.Min(raw.Length, at + DeviceFileManifest.ChunkBytes)]));
            }
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
        await DeviceFileReconcileTests.Finish(f, run, 0); _ = await operation;
        DeviceFileConnectionRunsTests.Clear(f); var ended = f.Native.Connection.EndNativeMediaAlbumAsync(run);
        var end = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(end, run.Lease.RunId, "canceled_held")); await ended;
    }
    private static void Restore(DeviceFileReceiveJobTests.Fixture f, NativeMediaBackupVersion selected, byte[] expected, string leaf)
    {
        using (var root = f.Destination.OpenNative())
        using (var target = root.CreateStagedFile(leaf))
        {
            _ = f.Native.Store.RestoreNativeMediaBackup(f.Destination, selected, target, () => true);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaBackup(f.Destination, selected, target, () => true), "Restore overwrote an occupied target.");
        }
        TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, leaf)).SequenceEqual(expected), "Restored bytes differ.");
    }

    internal static async Task WindowsDedupAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        var first = Save(f); var second = Save(f, "00000000000000000000000000000002");
        TestAssert.That(first.Id != second.Id && first.ObjectKey == second.ObjectKey && !first.GrantsMutationAuthority,
            "Different names did not retain independent versions sharing one content object.");
        var objects = Directory.GetFiles(Folder(f), "object-*.raw");
        TestAssert.That(objects.Length == 1 && File.ReadAllBytes(objects[0]).SequenceEqual(Data), "Identical content was copied twice or changed.");
        var names = Directory.GetFiles(Folder(f)).Order().ToArray();
        TestAssert.That(Save(f) == first && Directory.GetFiles(Folder(f)).Order().SequenceEqual(names), "Unchanged retry copied data/catalog or renewed retention origin.");
        TestAssert.That(f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 2 &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history), "Backup changed Saved/END history.");
        Restore(f, first, Data, "restored-first.jpg"); Restore(f, second, Data, "restored-second.jpg");
        using var root = f.Destination.OpenNative(); using var backup = DeviceFileNativeDirectory.OpenExistingForReceive(Folder(f));
        TestAssert.That(root.FileIdentityAt("restored-first.jpg") != backup.FileIdentityAt(Path.GetFileName(objects[0])), "Restore linked to immutable object.");
    }

    internal static async Task WindowsDifferentVersionsAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var first = Save(f); var second = Save(f, "00000000000000000000000000000002");
        TestAssert.That(first.ObjectKey != second.ObjectKey && Directory.GetFiles(Folder(f), "object-*.raw").Length == 2, "Changed content was merged by filename/version.");
        Restore(f, first, "original first"u8.ToArray(), "version-one.jpg");
        Restore(f, second, "original second"u8.ToArray(), "version-two.jpg");
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        File.WriteAllText(Path.Combine(f.Root, "first.jpg"), "new PC edit survives");
        TestAssert.Throws<InvalidDataException>(() => Save(f), "PC edit was backed up as an old unchanged Saved version.");
        TestAssert.That(File.ReadAllText(Path.Combine(f.Root, "first.jpg")) == "new PC edit survives" &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history), "Edit HOLD modified user data/history.");
    }

    internal static async Task WindowsInterruptedAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var data = RandomNumberGenerator.GetBytes(DeviceFileManifest.ChunkBytes * 2 + 7); await Seed(f, data);
        var job = Job(f); var key = NativeMediaBackupPolicy.ContentKey(data.Length, Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant());
        var payload = Path.Combine(Folder(f), "object-" + key + ".raw");
        TestAssert.Throws<InvalidDataException>(() => Save(f, permit: () => !File.Exists(payload) || new FileInfo(payload).Length == 0), "Withdrawal falsely completed a backup.");
        TestAssert.That(File.Exists(payload) && new FileInfo(payload).Length is > 0 && new FileInfo(payload).Length < data.Length &&
            f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 0, "Incomplete copy became a complete version or lost its owned candidate.");
        DeviceFileNativeDirectory.Identity inode;
        using (var folder = DeviceFileNativeDirectory.OpenExistingForReceive(Folder(f))) inode = folder.FileIdentityAt(Path.GetFileName(payload));
        var selected = Save(f);
        using (var folder = DeviceFileNativeDirectory.OpenExistingForReceive(Folder(f)))
            TestAssert.That(folder.FileIdentityAt(Path.GetFileName(payload)) == inode, "Resume replaced or adopted a new candidate identity.");
        TestAssert.That(File.ReadAllBytes(payload).SequenceEqual(data) && Directory.GetFiles(Folder(f), "object-*.raw").Length == 1 && Job(f) == job,
            "Resume corrupted original bytes/history or duplicated content.");
        Restore(f, selected, data, "resumed.jpg");
    }

    internal static async Task WindowsCorruptCandidateAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f);
        bool Permit()
        {
            var payload = Directory.Exists(Folder(f)) ? Directory.GetFiles(Folder(f), "object-*.raw").FirstOrDefault() : null;
            return payload is null || new FileInfo(payload).Length == 0;
        }
        TestAssert.Throws<InvalidDataException>(() => Save(f, permit: Permit), "Prepared copy ignored native owner withdrawal.");
        var payload = Directory.GetFiles(Folder(f), "object-*.raw").Single(); File.WriteAllBytes(payload, new byte[] { 42 });
        TestAssert.Throws<InvalidDataException>(() => Save(f), "A corrupted registered prefix was silently truncated/replaced.");
        TestAssert.That(File.ReadAllBytes(payload).SequenceEqual(new byte[] { 42 }) && f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 0,
            "Corrupted candidate HOLD changed data or manufactured a version.");
    }

    internal static async Task WindowsForeignFolderAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f);
        Directory.CreateDirectory(Folder(f)); var personal = Path.Combine(Folder(f), "personal.txt"); File.WriteAllText(personal, "keep foreign folder");
        TestAssert.Throws<IOException>(() => Save(f), "An unregistered existing Backup folder was adopted.");
        TestAssert.That(Directory.GetFiles(Folder(f)).Length == 1 && File.ReadAllText(personal) == "keep foreign folder", "Foreign folder was changed.");
    }

    internal static async Task WindowsLocalRestoreAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f); var selected = Save(f);
        var source = Directory.GetFiles(f.Root, "first.jpg", SearchOption.AllDirectories).Single(); File.Delete(source);
        f.Native.Connection.Dispose(); // No old runtime/source/remote permission is needed for LOCAL restore.
        Restore(f, selected, Data, "after-disconnect.jpg");
        TestAssert.That(f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Single() == selected && !File.Exists(source),
            "Local recovery replayed an old deletion or needed the old connection.");
    }

    internal static async Task WindowsCorruptionAsync()
    {
        foreach (var what in new[] { "object", "snapshot", "anchor" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f); var selected = Save(f);
            if (what == "anchor")
            {
                using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = f.Native.Paths.TelefonDatabase, Mode = SqliteOpenMode.ReadWrite }.ToString()); db.Open();
                using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_backup_anchors"; var bytes = (byte[])read.ExecuteScalar()!; bytes[^1] ^= 1;
                using var edit = db.CreateCommand(); edit.CommandText = "UPDATE native_media_backup_anchors SET value=$value"; edit.Parameters.AddWithValue("$value", bytes); edit.ExecuteNonQuery();
            }
            else
            {
                var paths = Directory.GetFiles(Folder(f), what == "object" ? "object-*.raw" : "catalog-*.seal");
                foreach (var path in paths) { var bytes = File.ReadAllBytes(path); bytes[^1] ^= 1; File.WriteAllBytes(path, bytes); }
            }
            var names = Directory.GetFiles(Folder(f)).Order().ToArray();
            using (var root = f.Destination.OpenNative())
            using (var target = root.CreateStagedFile("untouched-new.jpg"))
            {
                var failed = false;
                try { f.Native.Store.RestoreNativeMediaBackup(f.Destination, selected, target, () => true); }
                catch (Exception error) when (error is InvalidDataException or CryptographicException) { failed = true; }
                TestAssert.That(failed && target.Observe().Size == 0, "Corrupt " + what + " was adopted or touched restore target.");
            }
            TestAssert.That(Directory.GetFiles(Folder(f)).Order().SequenceEqual(names), "Corruption silently created a replacement catalog/object.");
        }
    }
}
