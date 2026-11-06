using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileBackupExclusionTests
{
    internal static Task ClassifierAsync()
    {
        foreach (var path in new[] { @"C:\Backup", @"D:\old-device\BACKUP\album\nested", @"E:\alternative\Backup\older\camera",
            @"C:\Pictures\phone\Backup\objects" })
            TestAssert.That(NativeMediaBackupExclusions.ContainsBackupDirectory(path), "Backup subtree was not excluded: " + path);
        foreach (var path in new[] { @"C:\", @"C:\Pictures\phone", @"C:\Backup-other\camera", @"D:\myBackup\camera", @"E:\alternative" })
            TestAssert.That(!NativeMediaBackupExclusions.ContainsBackupDirectory(path), "Backup classifier overmatched a different component: " + path);
        foreach (var path in new[] { @"C:\Pictures\..\Backup", @"C:\Pictures\Backup.", @"C:\Backup\..\Photos" })
            TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupExclusions.ContainsBackupDirectory(path), "Malformed native path escaped classification.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaBackupExclusions.RequireMediaDirectory(@"X:\mounted-alias",
            @"\\?\Volume{11111111-1111-4111-8111-111111111111}\Pictures\Backup\objects"), "Drive alias hid the canonical backup component.");
        return Task.CompletedTask;
    }

    internal static async Task WindowsDestinationAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var backup = Path.Combine(f.Native.Paths.Root, "former-location", "Backup", "deep", "video"); Directory.CreateDirectory(backup);
        var original = Path.Combine(backup, "unchanged.mp4"); File.WriteAllText(original, "immutable original backup");
        var before = f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images");
        using (var native = DeviceFileNativeDirectory.OpenExistingForReceive(backup))
        {
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, native),
                "A retained former backup subtree became a native synchronization destination.");
        }
        TestAssert.That(f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "video") is null &&
            f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == before && File.ReadAllText(original) == "immutable original backup",
            "Backup exclusion changed the previous destination, backup bytes or history.");
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE name='native_media_backup_anchors'";
        TestAssert.That(Convert.ToInt32(query.ExecuteScalar()) == 0, "Classifier needed to create or adopt a backup catalog.");
    }
}
