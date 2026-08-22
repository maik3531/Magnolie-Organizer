using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RecoveryJournalTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-journal-{Guid.NewGuid():N}");
        var now = new DateTimeOffset(2026, 8, 12, 10, 0, 0, TimeSpan.Zero);
        try
        {
            var journal = new RecoveryJournal(Path.Combine(root, "wiederherstellungsstaende"),
                Path.Combine(root, "journal.json"), clock: () => now);
            var data = new JsonObject { ["termine"] = new JsonArray(new JsonObject { ["id"] = "t1" }),
                ["kontakte"] = new JsonArray(), ["notizen"] = new JsonArray(), ["syncEpoch"] = "epoch-1" };
            var first = journal.Create(data, SnapshotReason.Periodic, "2.0.2");
            var manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(first.Directory, "manifest.json")))!.AsObject();
            TestAssert.That(manifest["format"]?.GetValue<string>() == "magnolie-snapshot" &&
                manifest["version"]?.GetValue<int>() == 1 && manifest["platform"]?.GetValue<string>() == "windows" &&
                manifest["reason"]?.GetValue<string>() == "weekly" && first.Reason == "weekly" &&
                Guid.TryParse(manifest["id"]?.GetValue<string>(), out _) && first.SyncEpoch == "epoch-1",
                "Snapshot-Manifest verletzt Format, UUID, Plattform oder Sync-Epoche.");
            TestAssert.That(GesamtarchivService.Read(journal.ReadPayload(first.Id)).Daten["termine"]!.AsArray().Count == 1,
                "Journal verwendet nicht den vorhandenen Gesamtarchiv-Payload.");
            var duplicate = journal.Create(data, SnapshotReason.Periodic, "2.0.2");
            TestAssert.That(duplicate.Id == first.Id && journal.List().Count == 1, "15-Minuten-Deduplizierung greift nicht.");

            File.AppendAllText(Path.Combine(first.Directory, "payload.magnolie"), "x");
            try { journal.Verify(first.Id); throw new InvalidOperationException("Manipulierter Payload wurde angenommen."); }
            catch (InvalidDataException) { }
            var replacement = journal.Create(data, SnapshotReason.Periodic, "2.0.2");
            TestAssert.That(replacement.Id != first.Id && journal.Verify(replacement.Id).Id == replacement.Id,
                "Ein beschädigter Snapshot wurde als gültiges Deduplizierungsziel wiederverwendet.");

            var contact = journal.Create(data, SnapshotReason.PreContact, "2.0.2");
            TestAssert.That(contact.Reason == "pre-contact", "Der allgemeine Kontaktgrund ist nicht plattformstabil.");
            var contactManifestPath = Path.Combine(contact.Directory, "manifest.json");
            var legacyManifest = JsonNode.Parse(File.ReadAllText(contactManifestPath))!.AsObject();
            legacyManifest["reason"] = "periodic";
            File.WriteAllText(contactManifestPath, legacyManifest.ToJsonString());
            TestAssert.That(journal.Verify(contact.Id).Reason == "weekly",
                "Ein vorhandener Windows-Grund 'periodic' wird nicht als 'weekly' normalisiert.");

            if (Directory.Exists(first.Directory)) Directory.Delete(first.Directory, true);
            var manual = journal.Create(data, SnapshotReason.Manual, "2.0.2");
            now = now.AddDays(400);
            journal.Prune(2L * 1024 * 1024 * 1024, 20L * 1024 * 1024 * 1024);
            TestAssert.That(journal.List().Any(item => item.Id == manual.Id), "Angehefteter manueller Stand wurde entfernt.");
            TestAssert.That(journal.Schedule().Interval == "weekly" && journal.IsDue(), "Standardintervall ist nicht wöchentlich/fällig.");
            journal.RecordPeriodicResult(true);
            TestAssert.That(!journal.IsDue(), "Scheduler bleibt direkt nach erfolgreichem Lauf fällig.");
            foreach (var interval in new[] { "off", "6h", "12h", "daily", "weekly" })
                TestAssert.That(journal.SetInterval(interval).Interval == interval, $"Intervall {interval} wird nicht angenommen.");
            File.WriteAllText(Path.Combine(root, "journal.json"), "{kaputt");
            File.WriteAllText(AtomicStore.BackupPath(Path.Combine(root, "journal.json")), "{auch-kaputt");
            var damagedSchedule = journal.Schedule();
            TestAssert.That(damagedSchedule.Interval == "off" && damagedSchedule.Status == "off" && damagedSchedule.Error.Length > 0,
                "Beschädigte Journal-Einstellungen aktivierten fail-open neue Snapshots.");
            try { journal.ReadPayload("../fremd"); throw new InvalidOperationException("Pfadtraversal wurde angenommen."); }
            catch (InvalidDataException) { }

            var encryption = new EncryptionService();
            _ = encryption.Enable("{}", "Rosenholz1896");
            var protectedPoint = journal.Create(new JsonObject { ["notizen"] = new JsonArray() }, SnapshotReason.PreRestore,
                "2.0.2", encryption.EncryptData);
            var protectedPayload = journal.ReadPayload(protectedPoint.Id);
            TestAssert.That(EncryptionService.IsEncrypted(protectedPayload) &&
                GesamtarchivService.Read(encryption.DecryptDataWithSession(protectedPayload)).Daten["notizen"] is JsonArray,
                "Geschützter Snapshot ist unverschlüsselt oder nicht mit der Sitzung lesbar.");
            var protectedCopies = journal.RewritePayloads((text, encrypted) => encrypted
                ? encryption.RewrapWithSession(text) : encryption.EncryptData(text));
            TestAssert.That(protectedCopies.Failed == 0 && journal.List().All(item => item.Encrypted),
                "Vorhandene Recovery-Payloads wurden beim Kennwortschutz nicht vollständig geschützt.");
            var plainCopies = journal.RewritePayloads((text, encrypted) => encrypted
                ? encryption.DecryptDataWithSession(text) : text);
            TestAssert.That(plainCopies.Failed == 0 && journal.List().All(item => !item.Encrypted),
                "Recovery-Payloads blieben nach Entfernen des Kennwortschutzes verschlüsselt.");

            var rewriteWrites = 0;
            var failingJournal = new RecoveryJournal(Path.Combine(root, "wiederherstellungsstaende"),
                Path.Combine(root, "journal.json"), new AtomicStore(stage =>
                {
                    if (stage == AtomicStore.WriteStage.TemporaryFlushed && ++rewriteWrites == 2)
                        throw new IOException("simulierter Fehler zwischen Payload und Manifest");
                }), () => now);
            var beforeFailedRewrite = failingJournal.ReadPayload(protectedPoint.Id);
            var failedRewrite = failingJournal.RewritePayloads((text, _) => text + "veraendert");
            TestAssert.That(failedRewrite.Failed == 1 && failingJournal.ReadPayload(protectedPoint.Id) == beforeFailedRewrite,
                "Ein Fehler zwischen Payload- und Manifest-Schreibvorgang verlor den gültigen Snapshot-Stand.");

            var interruptedDirectory = protectedPoint.Directory;
            var interruptedPrevious = Path.Combine(Path.GetDirectoryName(interruptedDirectory)!, $".{protectedPoint.Id}.rewrite-old");
            Directory.Move(interruptedDirectory, interruptedPrevious);
            TestAssert.That(failingJournal.List().Any(item => item.Id == protectedPoint.Id) && Directory.Exists(interruptedDirectory),
                "Ein Prozessabbruch während des Snapshot-Swaps stellte den alten gültigen Stand nicht wieder her.");

            var leasedPoint = journal.CreateRestorePoint(
                new JsonObject { ["notizen"] = new JsonArray(new JsonObject { ["id"] = "rollback" }) }, "2.0.2");
            journal.Prune(1024L * 1024 * 1024 - 1, 20L * 1024 * 1024 * 1024);
            TestAssert.That(journal.List().Any(item => item.Id == leasedPoint.Id && item.Pinned),
                "Der aktive Pre-Restore-Lease wurde bei weniger als 1 GiB freiem Speicher gelöscht.");

            var restartedJournal = new RecoveryJournal(Path.Combine(root, "wiederherstellungsstaende"),
                Path.Combine(root, "journal.json"), clock: () => now);
            restartedJournal.Prune(0, 20L * 1024 * 1024 * 1024);
            TestAssert.That(restartedJournal.List().Any(item => item.Id == leasedPoint.Id && item.Pinned),
                "Der Pre-Restore-Lease überlebte einen Neustart oder die Nullspeichergrenze nicht.");
            TestAssert.That(restartedJournal.ReleaseAbandonedRestoreLeases() == 1 &&
                restartedJournal.List().Any(item => item.Id == leasedPoint.Id && !item.Pinned),
                "Ein nach Daten-Recovery verwaister Restore-Lease wurde nicht sauber freigegeben.");
            restartedJournal.Prune(1024L * 1024 * 1024, 20L * 1024 * 1024 * 1024);
            TestAssert.That(restartedJournal.List().Any(item => item.Id == leasedPoint.Id),
                "Die 1-GiB-Grenze wurde fälschlich als Speichermangel behandelt.");
            restartedJournal.Prune(1024L * 1024 * 1024 - 1, 20L * 1024 * 1024 * 1024);
            TestAssert.That(restartedJournal.List().All(item => item.Id != leasedPoint.Id),
                "Der freigegebene Restore-Lease blieb unterhalb der Speichergrenze dauerhaft angeheftet.");

            var failedRestorePoint = restartedJournal.CreateRestorePoint(
                new JsonObject { ["notizen"] = new JsonArray(new JsonObject { ["id"] = "failed-restore" }) }, "2.0.2");
            try { throw new IOException("simulierter Restore-Fehler"); }
            catch (IOException) { }
            finally { restartedJournal.ReleaseRestoreLease(failedRestorePoint.Id); }
            restartedJournal.Prune(0, 20L * 1024 * 1024 * 1024);
            TestAssert.That(restartedJournal.List().All(item => item.Id != failedRestorePoint.Id),
                "Ein Restore-Fehler gab den Pre-Restore-Lease nicht sauber frei.");

            var restored = new JsonObject { ["syncEpoch"] = "old", ["geloescht"] = new JsonObject
                { ["kontakte"] = new JsonArray(new JsonObject { ["uid"] = "dead" }), ["termine"] = new JsonArray() } };
            var newEpoch = RestoreSyncState.Prepare(restored, now);
            TestAssert.That(newEpoch != "old" && restored["syncNachRestore"]?["additiv"]?.GetValue<bool>() == true &&
                restored["geloescht"]?["kontakte"]?.AsArray().Count == 0 &&
                restored["quarantaeneTombstones"]?["kontakte"]?.AsArray().Count == 1,
                "Restore erneuert die Epoche oder quarantänisiert alte Tombstones nicht.");
        }
        finally { try { Directory.Delete(root, true); } catch { } }
        return Task.CompletedTask;
    }
}
