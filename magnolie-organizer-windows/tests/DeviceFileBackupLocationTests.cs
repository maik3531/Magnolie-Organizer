using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBackupLocationTests
{
    private static DeviceFileNativeDirectory Parent(DeviceFileReceiveJobTests.Fixture f, string name)
    {
        var path = Path.Combine(f.Native.Paths.Root, name); Directory.CreateDirectory(path);
        return DeviceFileNativeDirectory.OpenExistingForReceive(path);
    }
    private static byte[] Blob(DeviceFileReceiveJobTests.Fixture f)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_backup_locations WHERE media_type='images'";
        return (byte[])read.ExecuteScalar()!;
    }

    internal static async Task WindowsChoicesAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        using var videoRoot = Parent(f, "native-video-data");
        f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, videoRoot);
        var originalPreferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); var originalBinding = f.Current();
        var initial = f.Native.Store.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "images");
        TestAssert.That(initial.Version is null && initial.SelectedId is null && initial.Current.NativePath == f.Root && initial.Parents.Count == 1,
            "Read changed the per-destination Backup default.");
        using var first = Parent(f, "alternative-first"); using var second = Parent(f, "alternative-second");
        var chosen = f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, first, () => { });
        var cipher = Blob(f);
        TestAssert.That(chosen.Current.NativePath == first.NativePath && chosen.Parents.Count == 2 && !Directory.Exists(Path.Combine(first.NativePath, "Backup")) &&
            !Directory.Exists(Path.Combine(f.Root, "Backup")), "Choosing a backup parent created storage or moved existing data.");
        var same = f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", chosen.Version, first, () => { });
        TestAssert.That(same.Version == chosen.Version && cipher.SequenceEqual(Blob(f)), "Idempotent backup parent choice rewrote history or ciphertext.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, second, () => { }),
            "A stale backup choice replaced the newer selection.");
        var next = f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", chosen.Version, second, () => { });
        var reset = f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", next.Version, null, () => { });
        TestAssert.That(reset.SelectedId is null && reset.Current == initial.Current && reset.Parents.Count == 3 &&
            reset.Parents.Contains(chosen.Current) && reset.Parents.Contains(next.Current), "Default selection discarded alternative/former parents.");
        TestAssert.That(f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id) == originalPreferences && f.Current() == originalBinding &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0,
            "Backup parent choices altered media preferences, the actual data ACK or receive history.");
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var cleanup = db.CreateCommand(); cleanup.CommandText = "DELETE FROM meta"; cleanup.ExecuteNonQuery();
        var reopened = new TelefonStore(f.Native.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        var saved = reopened.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "images");
        TestAssert.That(saved.Version == reset.Version && saved.Parents.SequenceEqual(reset.Parents), "Reopen or generic cleanup erased retained backup parents.");
        var videos = reopened.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "video");
        TestAssert.That(videos.Version is null && videos.SelectedId is null && videos.Current.NativePath == videoRoot.NativePath && videos.Parents.Count == 1,
            "Photo backup choices altered the independent video default.");
    }

    internal static async Task WindowsCatalogsAndRestoreAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileBackupCatalogTests.Seed(f);
        var original = DeviceFileBackupCatalogTests.Save(f);
        var oldFolder = Path.Combine(f.Root, "Backup");
        var before = Directory.GetFiles(oldFolder).ToDictionary(path => Path.GetFileName(path)!, File.ReadAllBytes);
        using var alternate = Parent(f, "new-backup-parent");
        var selected = f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, alternate, () => { });
        TestAssert.That(!Directory.Exists(Path.Combine(alternate.NativePath, "Backup")), "Choice silently copied old backups to the new parent.");
        var other = DeviceFileBackupCatalogTests.Save(f, "00000000000000000000000000000002");
        TestAssert.That(Directory.GetFiles(Path.Combine(alternate.NativePath, "Backup"), "object-*.raw").Length == 1 &&
            before.All(item => File.ReadAllBytes(Path.Combine(oldFolder, item.Key!)).SequenceEqual(item.Value)) && Directory.GetFiles(oldFolder).Length == before.Count,
            "New backup location changed or moved the original catalog/objects.");
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "location-book"), "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}");
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        f.Native.Connection.Dispose(); // Local catalog access/restore must not borrow an old data session.
        var current = coordinator.ReadNativeMediaBackupUiPage(f.Native.Peer.Id, "images", null);
        var old = coordinator.ReadNativeMediaBackupUiPage(f.Native.Peer.Id, "images", selected.Default.Id);
        TestAssert.That(current.Source == selected.Current && current.Versions.Single() == other && old.Versions.Single() == original,
            "Changing storage lost access to the current or retained original catalog.");
        var choice = coordinator.PrepareNativeMediaBackupRestore(f.Native.Peer.Id, "images", original.Id, original.RecordSha256, selected.Default.Id);
        var restored = coordinator.RestoreConfirmedNativeMediaBackup(choice);
        TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, restored.Name)).SequenceEqual("original photo and EXIF remain unchanged"u8.ToArray()) &&
            !File.Exists(Path.Combine(alternate.NativePath, restored.Name)) && before.All(item => File.ReadAllBytes(Path.Combine(oldFolder, item.Key!)).SequenceEqual(item.Value)),
            "Historical restore published into the backup storage parent, changed original backups or failed to retain original bytes.");
        coordinator.SetNativeMediaBackupUiParent(f.Native.Peer.Id, "images", selected.Version, null);
        TestAssert.That(coordinator.ReadNativeMediaBackupUiPage(f.Native.Peer.Id, "images", selected.Current.Id).Versions.Single() == other,
            "Returning to the default hid the retained alternate catalog.");
    }

    internal static async Task WindowsFencesAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); using var alternate = Parent(f, "candidate-parent");
        var calls = 0;
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, alternate, () => {
            if (++calls == 3) throw DeviceFileControl.Error("synthetic_book_revoked_after_write");
        }), "Book revocation during parent write was ignored.");
        TestAssert.That(f.Native.Store.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "images").Version is null &&
            !Directory.EnumerateFileSystemEntries(alternate.NativePath).Any(), "Failed parent write changed selection or created backup data.");
        Directory.CreateDirectory(Path.Combine(alternate.NativePath, "Backup")); var foreign = Path.Combine(alternate.NativePath, "Backup", "personal.txt");
        File.WriteAllText(foreign, "foreign backup stays untouched");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, alternate, () => { }),
            "Alternative selection adopted a foreign existing Backup folder.");
        TestAssert.That(File.ReadAllText(foreign) == "foreign backup stays untouched" &&
            f.Native.Store.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "images").Version is null, "Foreign backup HOLD changed bytes or saved the unsafe choice.");
        using var safe = Parent(f, "safe-parent"); f.Native.Store.ChangeNativeMediaBackupParent(f.Native.Peer.Id, "images", null, safe, () => { });
        var damaged = Blob(f); damaged[^1] ^= 1;
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var update = db.CreateCommand();
        update.CommandText = "UPDATE native_media_backup_locations SET value=$value"; update.Parameters.AddWithValue("$value", damaged); update.ExecuteNonQuery();
        TestAssert.Throws<CryptographicException>(() => f.Native.Store.ReadNativeMediaBackupLocations(f.Native.Peer.Id, "images"), "Corrupt backup locations silently became new defaults.");
        TestAssert.That(damaged.SequenceEqual(Blob(f)) && !Directory.EnumerateFileSystemEntries(safe.NativePath).Any(), "Corruption HOLD discarded location history or created data.");
    }
}
