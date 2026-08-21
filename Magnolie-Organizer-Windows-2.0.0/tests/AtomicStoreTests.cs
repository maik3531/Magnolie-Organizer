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
}
