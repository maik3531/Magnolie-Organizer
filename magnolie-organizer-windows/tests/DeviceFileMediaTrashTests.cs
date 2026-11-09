using MagnolieOrganizer.Windows;
using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMediaTrashTests
{
    internal static NativeMediaPreviewRaster RenderActualProduct(byte[] bytes, string kind, int side, Action current)
    {
        var folder = Path.Combine(AppContext.BaseDirectory, "preview-product");
        var context = System.Runtime.Loader.AssemblyLoadContext.Default;
        System.Reflection.Assembly? Resolve(System.Runtime.Loader.AssemblyLoadContext _, System.Reflection.AssemblyName name)
        {
            var path = Path.Combine(folder, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        }
        context.Resolving += Resolve;
        try
        {
            var actual = context.LoadFromAssemblyPath(Path.Combine(folder, "Magnolie Organizer.dll"));
            var render = actual.GetType("MagnolieOrganizer.Windows.NativeMediaPreviewDrawing", true)!
                .GetMethod("Render", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
            object result;
            try { result = render.Invoke(null, new object[] { bytes, kind, side, current })!; }
            catch (System.Reflection.TargetInvocationException error) when (error.InnerException is not null)
            { System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(error.InnerException).Throw(); throw; }
            object Value(string name) => result.GetType().GetProperty(name)!.GetValue(result)!;
            return new((string)Value("MimeType"), (int)Value("Width"), (int)Value("Height"), (string)Value("DataBase64"));
        }
        finally { context.Resolving -= Resolve; }
    }

    internal static Task WindowsActualProductDrawingPreviewAsync()
    {
        var folder = Path.Combine(AppContext.BaseDirectory, "preview-product");
        var context = System.Runtime.Loader.AssemblyLoadContext.Default;
        System.Reflection.Assembly? Resolve(System.Runtime.Loader.AssemblyLoadContext _, System.Reflection.AssemblyName name)
        {
            var path = Path.Combine(folder, name.Name + ".dll");
            return File.Exists(path) ? context.LoadFromAssemblyPath(path) : null;
        }
        context.Resolving += Resolve;
        try
        {
            var actual = context.LoadFromAssemblyPath(Path.Combine(folder, "Magnolie Organizer.dll"));
            var render = actual.GetType("MagnolieOrganizer.Windows.NativeMediaPreviewDrawing", true)!
                .GetMethod("Render", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
            var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC");
            var before = png.ToArray();
            foreach (var side in new[] { 192, 1024 })
            {
                var result = render.Invoke(null, new object[] { png, "images", side, (Action)(() => { }) })!;
                object Value(string name) => result.GetType().GetProperty(name)!.GetValue(result)!;
                var jpeg = Convert.FromBase64String((string)Value("DataBase64"));
                TestAssert.That((int)Value("Width") == 1 && (int)Value("Height") == 1 && (string)Value("MimeType") == "image/jpeg" &&
                    jpeg[0] == 255 && jpeg[1] == 216 && png.SequenceEqual(before), "Actual product native decoder did not return an unchanged-input bounded JPEG raster.");
            }
            foreach (var bytes in new[] { "<svg href='file:///private'/>"u8.ToArray(), Array.Empty<byte>() })
                TestAssert.Throws<System.Reflection.TargetInvocationException>(() => render.Invoke(null, new object[] { bytes, "images", 192, (Action)(() => { }) }),
                    "Product decoder accepted an active/unknown image format.");
            var checks = 0;
            TestAssert.Throws<System.Reflection.TargetInvocationException>(() => render.Invoke(null, new object[] { png, "images", 192,
                (Action)(() => { if (++checks == 2) throw new InvalidDataException("native_preview_retired"); }) }), "Product decoder ignored current-owner withdrawal.");
            TestAssert.That(checks == 2, "Product decoder did not recheck native ownership after decoding.");
        }
        finally { context.Resolving -= Resolve; }
        return Task.CompletedTask;
    }

    // Actual native retained-file IO/ownership; rendering is a separate platform boundary.
    internal static async Task WindowsReadonlyTrashPreviewAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aX0AAAAASUVORK5CYII=");
        var data = new[] { png, png }; var manifest = f.Manifest(("renamed.bin", png), ("other.png", png));
        var epoch = new string('e', 64); var run = await DeviceFileAlbumTests.Preview(f, manifest, epoch, "Kamera");
        await DeviceFileAlbumTests.Copy(f, run, data);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var entry = f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, manifest.Files[0].Id, () => true);
        var folder = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder);
        var trash = Path.Combine(folder, ".magnolie-trash-" + entry.Operation);
        var names = Directory.GetFiles(folder).Order().ToArray(); var history = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).ToArray();
        byte[]? clear = null; var allowed = true; var renders = 0;
        NativeMediaPreviewRaster Render(byte[] bytes, string kind, int side, Action current)
        {
            current(); renders++; clear = bytes;
            TestAssert.That(bytes.SequenceEqual(png) && kind == "images" && side is 192 or 1024, "Preview did not read authenticated original media bytes.");
            return new("image/png", 1, 1, Convert.ToBase64String(png));
        }
        foreach (var side in new[] { 192, 1024 })
        {
            var result = f.Native.Store.PreviewNativeMediaTrash(f.Native.Peer.Id, entry, () => allowed, side, Render);
            TestAssert.That(result.Width == 1 && result.MimeType == "image/png" && clear!.All(value => value == 0), "Readonly preview failed or left original input plaintext live.");
        }
        TestAssert.That(renders == 2 && Directory.GetFiles(folder).Order().SequenceEqual(names) && File.ReadAllBytes(trash).SequenceEqual(png) &&
            !File.Exists(Path.Combine(folder, "renamed.bin")) && f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job, "Viewing moved, copied, deleted or rewrote retained original/history.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PreviewNativeMediaTrash(f.Native.Peer.Id, entry with { Version = new string('0', 64) },
            () => true, 192, Render), "A stale selection reached rendering.");
        TestAssert.That(renders == 2, "Stale selection invoked renderer.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PreviewNativeMediaTrash(f.Native.Peer.Id, entry, () => allowed, 192,
            (bytes, kind, side, current) => { var result = Render(bytes, kind, side, current); allowed = false; return result; }), "Revoked native permit leaked a rendered result.");
        TestAssert.That(clear!.All(value => value == 0) && File.ReadAllBytes(trash).SequenceEqual(png), "Withdrawal lost original bytes or left plaintext buffers.");
        File.Move(trash, trash + ".kept"); File.WriteAllBytes(trash, png);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PreviewNativeMediaTrash(f.Native.Peer.Id, entry, () => true, 192, Render),
            "A foreign same-content inode was accepted for preview.");
        TestAssert.That(File.ReadAllBytes(trash + ".kept").SequenceEqual(png) && File.ReadAllBytes(trash).SequenceEqual(png), "Preview repaired/replaced a foreign file.");
    }

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
