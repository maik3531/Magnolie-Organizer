using MagnolieOrganizer.Windows;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMediaTrashTests
{
    internal static async Task WindowsOriginalTrashRestoreAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var manifest = f.Manifest(("first.jpg", "original first"u8.ToArray()), ("second.jpg", "original second"u8.ToArray()));
        var first = manifest.Files[0]; var path = Path.Combine(f.Root, first.Path); var bytes = File.ReadAllBytes(path);
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, first.Id, () => true);
        var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation);
        TestAssert.That(entry.State == "trashed" && !entry.GrantsWriteAuthority && !entry.IsRemoteDeletionReceipt && !File.Exists(path) && File.ReadAllBytes(trash).SequenceEqual(bytes),
            "Native trash did not preserve the original bytes or fabricated a remote deletion proof.");
        var restored = f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true);
        TestAssert.That(restored.State == "restored" && !File.Exists(trash) && File.ReadAllBytes(path).SequenceEqual(bytes) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L),
            "Native restore changed original receive/Saved/END history or lost the original bytes.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true), "Old deletion entry replayed after restore.");
        var again = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, first.Id, () => true);
        TestAssert.That(again.Operation != entry.Operation && f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Count == 2,
            "A new explicit trash operation erased/restored the historical operation.");
    }

    internal static async Task WindowsRestoreOccupiedTargetAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var fileId = f.Manifest(("first.jpg", "original first"u8.ToArray()), ("second.jpg", "original second"u8.ToArray())).Files[0].Id;
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, fileId, () => true);
        var path = Path.Combine(f.Root, "first.jpg"); var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation); var bytes = File.ReadAllBytes(trash);
        File.WriteAllText(path, "new user file must survive");
        TestAssert.Throws<IOException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true), "Restore replaced a newly occupied target.");
        var pending = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single();
        TestAssert.That(pending.State == "restore_prepared" && File.ReadAllText(path) == "new user file must survive" && File.ReadAllBytes(trash).SequenceEqual(bytes),
            "Occupied restore target lost user content or original trash bytes/history.");
        File.Move(path, Path.Combine(f.Root, "user-kept.jpg"));
        var restored = f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, pending, () => true);
        TestAssert.That(restored.State == "restored" && File.ReadAllBytes(path).SequenceEqual(bytes), "Original prepared restore could not be retried without a new operation.");
    }

    internal static async Task WindowsTrashChangedSourceAndPermitHoldAsync()
    {
        foreach (var mutation in new[] { "content", "identity", "permit" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
            var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var first = f.Manifest(("first.jpg", "original first"u8.ToArray()), ("second.jpg", "original second"u8.ToArray())).Files[0];
            var path = Path.Combine(f.Root, "first.jpg");
            if (mutation == "content") { using var edit = File.OpenWrite(path); edit.WriteByte(42); }
            if (mutation == "identity") { File.Move(path, path + ".original"); File.WriteAllBytes(path, "original first"u8.ToArray()); }
            var bytes = File.ReadAllBytes(path);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, first.Id, () => mutation != "permit"),
                "Changed source or missing actual native permit was accepted: " + mutation);
            TestAssert.That(File.ReadAllBytes(path).SequenceEqual(bytes) && f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Count == 0 &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job, "Failed trash changed bytes or manufactured durable trash history: " + mutation);
        }
    }

    internal static async Task WindowsInterruptedMoveRecoveryAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var fileId = new string('0', 31) + "1";
        var path = Path.Combine(f.Root, "first.jpg"); var bytes = File.ReadAllBytes(path);
        // Withdraw the actual permit immediately AFTER the physical NT rename,
        // before its completion event. The prepared record must survive intact.
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, fileId, () => File.Exists(path)),
            "An uncertain trash move falsely completed after native permit withdrawal.");
        var pending = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single(); var trash = Path.Combine(f.Root, ".magnolie-trash-" + pending.Operation);
        TestAssert.That(pending.State == "prepared" && !File.Exists(path) && File.ReadAllBytes(trash).SequenceEqual(bytes), "Uncertain trash lost the original prepared history/bytes.");
        var trashed = f.Native.Store.RecoverNativeMediaTrashOperation(f.Native.Peer.Id, pending, () => true);
        TestAssert.That(trashed.State == "trashed" && trashed.Operation == pending.Operation, "Trash recovery substituted a new operation.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, trashed, () => File.Exists(trash)),
            "An uncertain restore falsely completed after native permit withdrawal.");
        pending = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single();
        TestAssert.That(pending.State == "restore_prepared" && !File.Exists(trash) && File.ReadAllBytes(path).SequenceEqual(bytes), "Uncertain restore lost original bytes or recovery provenance.");
        var restored = f.Native.Store.RecoverNativeMediaTrashOperation(f.Native.Peer.Id, pending, () => true);
        TestAssert.That(restored.State == "restored" && restored.Operation == pending.Operation && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job,
            "Original uncertain restore did not finish without modifying receive history.");
    }

    internal static async Task WindowsAlbumTrashRestoreAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var data = new[] { "album original first"u8.ToArray(), "album original second"u8.ToArray() };
        var manifest = f.Manifest(("same.jpg", data[0]), ("other.jpg", data[1])); var epoch = new string('e', 64);
        var run = await DeviceFileAlbumTests.Preview(f, manifest, epoch, "Kamera"); await DeviceFileAlbumTests.Copy(f, run, data);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, manifest.Files[0].Id, () => true);
        var folder = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder); var trash = Path.Combine(folder, ".magnolie-trash-" + entry.Operation);
        TestAssert.That(File.ReadAllBytes(trash).SequenceEqual(data[0]) && !File.Exists(Path.Combine(folder, "same.jpg")), "Album trash escaped its original native parent.");
        var restored = f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true);
        TestAssert.That(restored.State == "restored" && File.ReadAllBytes(Path.Combine(folder, "same.jpg")).SequenceEqual(data[0]), "Native album original could not be restored.");
        var repeated = await DeviceFileAlbumTests.Preview(f, f.Manifest(("same.jpg", data[0]), ("other.jpg", data[1])), epoch, "New label");
        TestAssert.That(f.Native.Connection.PlanNativeMediaRun(repeated).Members.All(member => member.Action == "unchanged"), "Restoration replayed an old deletion or lost stable album identity.");
    }

    internal static async Task WindowsCorruptTrashHistoryHoldAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, new string('0', 31) + "1", () => true);
        var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation); var bytes = File.ReadAllBytes(trash);
        using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = f.Native.Paths.TelefonDatabase, Mode = SqliteOpenMode.ReadWrite }.ToString()); db.Open();
        using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_trash_events WHERE operation=$operation AND sequence=1"; read.Parameters.AddWithValue("$operation", entry.Operation);
        var cipher = (byte[])read.ExecuteScalar()!; cipher[^1] ^= 1;
        using var corrupt = db.CreateCommand(); corrupt.CommandText = "UPDATE native_media_trash_events SET value=$value WHERE operation=$operation AND sequence=1";
        corrupt.Parameters.AddWithValue("$value", cipher); corrupt.Parameters.AddWithValue("$operation", entry.Operation); corrupt.ExecuteNonQuery();
        TestAssert.Throws<System.Security.Cryptography.CryptographicException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true),
            "Altered original trash history was silently adopted/rebuilt.");
        TestAssert.That(File.ReadAllBytes(trash).SequenceEqual(bytes) && !File.Exists(Path.Combine(f.Root, "first.jpg")) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job, "Corrupt trash history mutated original bytes or receive proofs.");
    }
}
