using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileDestinationSelectionTests
{
    // Architectural counterproof, not a claim that backup history is a current
    // selection owner, and not a simulated legitimate target migration.
    internal static async Task WindowsBackupAnchorIsNotCurrentSelectionAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        await DeviceFileReconcileTests.Establish(f);
        var first = DeviceFileBackupCatalogTests.Save(f);
        byte[] Anchor()
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT value FROM native_media_backup_anchors";
            return (byte[])read.ExecuteScalar()!;
        }
        void PutAnchor(byte[] value)
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
            write.CommandText = "UPDATE native_media_backup_anchors SET value=$value";
            write.Parameters.AddWithValue("$value", value);
            TestAssert.That(write.ExecuteNonQuery() == 1, "Counterproof did not isolate one original backup anchor.");
        }
        var oldAnchor = Anchor();
        var second = DeviceFileBackupCatalogTests.Save(f, "00000000000000000000000000000002");
        var latestAnchor = Anchor();
        TestAssert.That(!oldAnchor.SequenceEqual(latestAnchor) && first != second &&
            f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 2,
            "Counterproof did not establish two actual backup catalog revisions.");
        var folder = Path.Combine(f.Root, "Backup");
        var files = Directory.GetFiles(folder).ToDictionary(path => path, path => SHA256.HashData(File.ReadAllBytes(path)));
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).ToArray();
        try
        {
            PutAnchor(oldAnchor); // Fault injection only; NOT a user selection.
            var oldView = f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true);
            TestAssert.That(oldView.Count == 1 && oldView.Single() == first && Anchor().SequenceEqual(oldAnchor),
                "Retained snapshot behavior changed; reassess current-head counterproof before using it.");
        }
        finally { PutAnchor(latestAnchor); }
        TestAssert.That(f.Native.Store.NativeMediaBackupVersions(f.Destination, () => true).Count == 2 &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            Directory.GetFiles(folder).Length == files.Count && files.All(item => File.Exists(item.Key) &&
                SHA256.HashData(File.ReadAllBytes(item.Key)).SequenceEqual(item.Value)),
            "Read-only counterproof changed raw bytes, native snapshots or completed receive history.");
    }
}
