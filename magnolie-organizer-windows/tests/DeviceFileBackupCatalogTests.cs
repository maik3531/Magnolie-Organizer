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
    private static async Task Seed(DeviceFileReceiveJobTests.Fixture f, byte[]? raw = null, Action? nativeGuard = null)
    {
        raw ??= Data;
        var run = await DeviceFileAlbumTests.Preview(f, f.Manifest(("first.jpg", raw), ("second.jpg", raw)), new string('e', 64), "Kamera");
        run.NativeWorkerGuard = nativeGuard;
        if (raw.Length <= DeviceFileManifest.ChunkBytes && nativeGuard is null) { await DeviceFileAlbumTests.Copy(f, run, [raw, raw]); return; }
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
        if (nativeGuard is not null) TestAssert.That(!Directory.Exists(Folder(f)), "Backup registered completion before actual source END.");
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

    internal static async Task WindowsJoinedLifecycleAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        const string book = "{\"syncEpoch\":\"backup-joined\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}";
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "native-book"), book);
        var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        await Seed(f, nativeGuard: permit.Require);
        // No explicit catalog Save call here: the ACTUAL receive/Saved/END lane
        // must have created the independent local versions before completing.
        var versions = f.Native.Store.NativeMediaBackupVersions(f.Destination, () => { permit.Require(); return true; }).ToArray();
        TestAssert.That(versions.Length == 2 && versions[0].ObjectKey == versions[1].ObjectKey &&
            Directory.GetFiles(Folder(f), "object-*.raw").Length == 1, "Actual saved-book receive lane did not create shared backup versions.");
        var names = Directory.GetFiles(Folder(f)).Order().ToArray(); var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        var run = await DeviceFileAlbumTests.Preview(f, f.Manifest(("first.jpg", Data), ("second.jpg", Data)), new string('e', 64), "Kamera");
        run.NativeWorkerGuard = permit.Require;
        var repeat = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        await DeviceFileReconcileTests.Finish(f, run, 0); var result = await repeat;
        TestAssert.That(result.Plan.Members.All(member => member.Action == "unchanged") && result.ReceivedJobId is null &&
            Directory.GetFiles(Folder(f)).Order().SequenceEqual(names) && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).SequenceEqual(versions), "Unchanged actual lane copied again or rewrote Saved/END/backup timestamps.");
        DeviceFileConnectionRunsTests.Clear(f); var ended = f.Native.Connection.EndNativeMediaAlbumAsync(run);
        var request = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held")); await ended;
        Restore(f, versions[0], Data, "joined-restore.jpg");
    }

    internal static async Task WindowsPublishedRestoreAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f); var selected = Save(f);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        f.Native.Connection.Dispose();
        foreach (var path in Directory.GetFiles(f.Root, "first.jpg", SearchOption.AllDirectories)) File.Delete(path);
        var result = f.Native.Store.RestoreNativeMediaBackupToDestination(f.Destination, selected, () => true);
        TestAssert.That(result.State == "restored" && !result.IsRemoteSavedReceipt && File.ReadAllBytes(Path.Combine(f.Root, result.Name)).SequenceEqual(Data) &&
            Directory.GetFiles(f.Root, ".magnolie-restore-*.part").Length == 0 && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history),
            "Native new-file publication needed the phone/source, leaked a stage, replayed deletion or altered Saved/END.");
        var again = f.Native.Store.RestoreNativeMediaBackupToDestination(f.Destination, selected, () => true);
        TestAssert.That(again.Name != result.Name && File.ReadAllBytes(Path.Combine(f.Root, result.Name)).SequenceEqual(Data), "A fresh explicit restore overwrote an existing file.");
    }

    internal static async Task WindowsInterruptedPublishedRestoreAsync()
    {
        foreach (var afterPublication in new[] { false, true })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
            var bytes = RandomNumberGenerator.GetBytes(DeviceFileManifest.ChunkBytes * 2 + 1); await Seed(f, bytes); var selected = Save(f);
            bool Permit()
            {
                if (afterPublication) return Directory.GetFiles(f.Root, "* - restored *.jpg").Length == 0;
                var stage = Directory.GetFiles(f.Root, ".magnolie-restore-*.part").SingleOrDefault();
                return stage is null || new FileInfo(stage).Length == 0;
            }
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaBackupToDestination(f.Destination, selected, Permit), "Uncertain restore falsely completed.");
            var before = Directory.GetFiles(f.Root, afterPublication ? "* - restored *.jpg" : ".magnolie-restore-*.part").Single();
            DeviceFileNativeDirectory.Identity identity;
            using (var root = f.Destination.OpenNative()) identity = root.FileIdentityAt(Path.GetFileName(before));
            if (!afterPublication) TestAssert.That(new FileInfo(before).Length is > 0 && new FileInfo(before).Length < bytes.Length, "Restore did not stop between bounded blocks.");
            var restored = f.Native.Store.RestoreNativeMediaBackupToDestination(f.Destination, selected, () => true);
            using (var root = f.Destination.OpenNative()) TestAssert.That(root.FileIdentityAt(restored.Name) == identity, "Retry created a second file or adopted a different candidate.");
            TestAssert.That(Directory.GetFiles(f.Root, "* - restored *.jpg").Length == 1 && Directory.GetFiles(f.Root, ".magnolie-restore-*.part").Length == 0 &&
                File.ReadAllBytes(Path.Combine(f.Root, restored.Name)).SequenceEqual(bytes), "Uncertain restore lost bytes or duplicated publication.");
        }
    }

    internal static async Task WindowsLocalBackupUiAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Seed(f); var selected = Save(f);
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        TestAssert.Throws<InvalidDataException>(() => coordinator.ReadNativeMediaBackupUi(f.Native.Peer.Id, "images"), "Backup UI bypassed the saved/unlocked book.");
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "native-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        TestAssert.That(coordinator.ReadNativeMediaBackupUi(f.Native.Peer.Id, "images").Single() == selected, "Local backup list required an online phone.");
        var choice = coordinator.PrepareNativeMediaBackupRestore(f.Native.Peer.Id, "images", selected.Id, selected.RecordSha256);
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var lane = typeof(TelefonCoordinator).GetField("nativeMediaWorker", flags)!; lane.SetValue(coordinator, 1);
        try { TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreConfirmedNativeMediaBackup(choice), "Restore overlapped a media worker."); }
        finally { lane.SetValue(coordinator, 0); }
        var result = coordinator.RestoreConfirmedNativeMediaBackup(choice);
        TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, result.Name)).SequenceEqual(Data), "Local saved-book restore failed.");
        host.FailAfterPrimary = true;
        using (var message = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = "{\"changed\":true,\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}" }.ToJsonString()))
            await host.SaveAsync(message.RootElement);
        TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreConfirmedNativeMediaBackup(choice), "Old native confirmation survived a failed book save.");
    }
}
