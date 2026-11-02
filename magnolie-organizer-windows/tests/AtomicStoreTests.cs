using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class AtomicStoreTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-atomic-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var store = new AtomicStore();
            VerifyProfileBackup(root);
            var path = Path.Combine(root, "data.json");
            store.Write(path, "alt");
            await Task.WhenAll(Enumerable.Range(0, 12).Select(index => Task.Run(() =>
                store.Write(path, $"{{\"generation\":{index},\"payload\":\"{new string('x', 4096)}\"}}"))));
            var value = store.Read(path, 16 * 1024) ?? "";
            TestAssert.That(value.StartsWith("{\"generation\":", StringComparison.Ordinal) && value.EndsWith("\"}", StringComparison.Ordinal),
                "Eine konkurrierende atomare Ersetzung hinterließ eine Teil-Datei.");
            TestAssert.That(!Directory.EnumerateFiles(root).Any(file => Path.GetFileName(file).Contains(".tmp", StringComparison.OrdinalIgnoreCase)),
                "AtomicStore ließ temporäre Dateien zurück.");

            var recoverable = Path.Combine(root, "recoverable.json");
            store.WriteRecoverableJson(recoverable, "{\"generation\":1}");
            store.WriteRecoverableJson(recoverable, "{\"generation\":2}");
            var interrupted = false;
            var interruptedStore = new AtomicStore(stage =>
            {
                if (!interrupted && stage == AtomicStore.WriteStage.TemporaryFlushed)
                {
                    interrupted = true;
                    throw new IOException("simulierter Prozessabbruch vor Replace");
                }
            });
            await TestAssert.ThrowsAsync<IOException>(() => Task.Run(() =>
                interruptedStore.WriteRecoverableJson(recoverable, "{\"generation\":3}")),
                "Der simulierte Abbruch vor Replace wurde nicht ausgelöst.");
            TestAssert.That(store.ReadRecoverableJson(recoverable) == "{\"generation\":2}",
                "Ein Abbruch zwischen Tempwrite und Replace beschädigte den bestätigten Bestand.");

            File.WriteAllText(recoverable, "{beschaedigt");
            TestAssert.That(store.ReadRecoverableJson(recoverable) == "{\"generation\":2}" &&
                            File.ReadAllText(recoverable) == "{\"generation\":2}",
                "Die letzte gültige atomare Kopie wurde nicht wiederhergestellt.");
            File.WriteAllText(recoverable, "defekt");
            File.WriteAllText(AtomicStore.BackupPath(recoverable), "auch defekt");
            await TestAssert.ThrowsAsync<InvalidDataException>(() => Task.Run(() => store.ReadRecoverableJson(recoverable)),
                "Zwei beschädigte Kopien wurden als gültiger Datenbestand angenommen.");

            var backupDirectory = Path.Combine(root, "backups");
            var firstBackup = store.Backup(path, backupDirectory);
            var secondBackup = store.Backup(path, backupDirectory);
            TestAssert.That(firstBackup != secondBackup && File.Exists(firstBackup) && File.Exists(secondBackup),
                "Zwei Sicherungen in derselben Sekunde überschrieben einander.");

            var backupSource = Path.Combine(root, "backup-source.json");
            store.WriteRecoverableJson(backupSource, "{\"generation\":1}");
            store.WriteRecoverableJson(backupSource, "{\"generation\":2}");
            File.WriteAllText(backupSource, "{beschaedigt");
            var recoveredBackup = store.Backup(backupSource, backupDirectory);
            TestAssert.That(File.ReadAllText(recoveredBackup) == "{\"generation\":2}" &&
                            File.ReadAllText(backupSource) == "{\"generation\":2}",
                "Die Sicherung verwendete nicht die letzte gültige Ersatzkopie.");

            var directoryLink = Path.Combine(root, "linked");
            Directory.CreateSymbolicLink(directoryLink, root);
            await TestAssert.ThrowsAsync<IOException>(() => Task.Run(() => store.Write(Path.Combine(directoryLink, "escape.json"), "x")),
                "AtomicStore schrieb durch einen symbolischen Verzeichnislink.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static void VerifyProfileBackup(string root)
    {
        var store = new AtomicStore();
        var profile = new WindowsPaths(Path.Combine(root, "profile"));
        TestAssert.That(profile.Backups == Path.Combine(profile.Root, "Sicherungen"),
            "An explicit test profile still sends backups to the personal Documents directory.");
        TestAssert.That(new WindowsPaths().Backups == Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "Magnolie Organizer", "Sicherungen"),
            "The normal personal backup directory was changed.");
        profile.EnsureDirectories();
        store.WriteRecoverableJson(profile.Data, "{\"synthetic-profile-backup\":true}");
        var backup = store.Backup(profile.Data, profile.Backups);
        TestAssert.That(Path.GetRelativePath(profile.Root, backup).StartsWith("Sicherungen" + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
            File.ReadAllText(backup) == "{\"synthetic-profile-backup\":true}",
            "A real synthetic backup escaped its explicit profile or lost its contents.");
    }

    internal static async Task<int> NativeProfileBackupAsync(string receipt)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var relative = Path.GetRelativePath(Path.GetTempPath(), Path.GetFullPath(receipt));
        if (Path.IsPathRooted(relative) || relative == ".." || relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new ArgumentException("Private temporary receipt required.");
        if (File.Exists(receipt)) throw new IOException("Receipt already exists.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-profile-backup-" + Guid.NewGuid().ToString("N"));
        try
        {
            VerifyProfileBackup(root);
            using var output = new FileStream(receipt, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            await System.Text.Json.JsonSerializer.SerializeAsync(output, new { passed = true, backupStayedInProfile = true,
                defaultPersonalPathUnchanged = true, actualSyntheticReadback = true });
            Console.WriteLine("WINDOWS-ISOLATED-PROFILE-BACKUP-OK");
            return 0;
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
    }
}
