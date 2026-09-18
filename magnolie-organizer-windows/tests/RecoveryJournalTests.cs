using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RecoveryJournalTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-journal-{Guid.NewGuid():N}");
        var now = new DateTimeOffset(2026, 8, 12, 10, 0, 0, TimeSpan.Zero);
        try
        {
            await TestLoadedOutboxQuarantine(root);
            var migrationRoot = Path.Combine(root, "migration");
            var migrationPaths = new WindowsPaths(migrationRoot);
            Directory.CreateDirectory(migrationPaths.RecoveryJournal);
            var currentId = Guid.NewGuid().ToString();
            Directory.CreateDirectory(Path.Combine(migrationPaths.RecoveryJournal, currentId));
            var legacy = Path.Combine(migrationRoot, "wiederherstellungsstaende");
            Directory.CreateDirectory(legacy);
            var legacyId = Guid.NewGuid().ToString();
            Directory.CreateDirectory(Path.Combine(legacy, legacyId));
            migrationPaths.EnsureDirectories();
            TestAssert.That(!Directory.Exists(legacy) &&
                Directory.Exists(Path.Combine(migrationPaths.RecoveryJournal, currentId)) &&
                Directory.Exists(Path.Combine(migrationPaths.RecoveryJournal, legacyId)),
                "Nach der ersten Migration neu angelegte alte Snapshotpunkte werden nicht sicher nachgezogen.");

            var journal = new RecoveryJournal(Path.Combine(root, "wiederherstellungsstaende"),
                Path.Combine(root, "journal.json"), clock: () => now);
            TestAssert.That(journal.Schedule() is { Mode: "days", Maximum: 20, Days: 3650 },
                "Recovery defaults diverged from the desktop settings contract.");
            var data = new JsonObject { ["termine"] = new JsonArray(new JsonObject { ["id"] = "t1" }),
                ["kontakte"] = new JsonArray(), ["notizen"] = new JsonArray(new JsonObject { ["id"] = "n1",
                    ["anhaenge"] = new JsonArray(new JsonObject { ["name"] = "a.pdf", ["sha256"] = new string('a', 64),
                        ["daten"] = "data:application/pdf;base64,JVBERg==" }) }), ["syncEpoch"] = "epoch-1" };
            var first = journal.Create(data, SnapshotReason.Periodic, "2.0.2");
            var manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(first.Directory, "manifest.json")))!.AsObject();
            TestAssert.That(manifest["format"]?.GetValue<string>() == "magnolie-snapshot" &&
                manifest["version"]?.GetValue<int>() == 1 && manifest["platform"]?.GetValue<string>() == "windows" &&
                manifest["reason"]?.GetValue<string>() == "weekly" && first.Reason == "weekly" &&
                Guid.TryParse(manifest["id"]?.GetValue<string>(), out _) && first.SyncEpoch == "epoch-1",
                "Snapshot-Manifest verletzt Format, UUID, Plattform oder Sync-Epoche.");
            TestAssert.That(GesamtarchivService.Read(journal.ReadPayload(first.Id)).Daten["termine"]!.AsArray().Count == 1,
                "Journal verwendet nicht den vorhandenen Gesamtarchiv-Payload.");
            TestAssert.That(GesamtarchivService.Read(journal.ReadPayload(first.Id)).Anhaenge == 1 &&
                data["notizen"]![0]!["anhaenge"]![0]!["daten"]!.ToString().StartsWith("data:", StringComparison.Ordinal),
                "Snapshot lost attachment bytes or mutated live data.");
            var archivedData = GesamtarchivService.Read(journal.ReadPayload(first.Id)).Daten;
            TestAssert.That(JsonNode.DeepEquals(RestoreSelection.Select(archivedData, new JsonObject(),
                ["all"], "replace")["notizen"], data["notizen"]), "Deleted attachment was not recovered from snapshot bytes.");
            foreach (var field in new[] { "sha256", "attachment_id", "id" })
            {
                var legacyAttachment = new JsonObject { [field] = "unique", ["name"] = "same.pdf", ["daten"] = "" };
                var liveAttachment = legacyAttachment.DeepClone().AsObject();
                liveAttachment["daten"] = "data:application/pdf;base64,JVBERg==";
                var legacyData = new JsonObject { ["anhaenge"] = new JsonArray(legacyAttachment) };
                var liveData = new JsonObject { ["anhaenge"] = new JsonArray(liveAttachment) };
                TestAssert.That(RestoreSelection.Select(legacyData, liveData, ["all"], "replace")["anhaenge"]![0]!["daten"]!
                    .ToString().StartsWith("data:"), "Unique legacy attachment was not recovered.");
                liveData["anhaenge"]!.AsArray().Add(liveAttachment.DeepClone());
                try { RestoreSelection.Select(legacyData, liveData, ["all"], "replace"); throw new Exception("Ambiguous identity accepted."); }
                catch (InvalidDataException) { }
                try { RestoreSelection.Select(legacyData, new JsonObject(), ["all"], "replace"); throw new Exception("Missing bytes accepted."); }
                catch (InvalidDataException) { }
            }
            var filenameOnly = JsonNode.Parse("{\"anhaenge\":[{\"name\":\"same.pdf\",\"daten\":\"\"}]}")!.AsObject();
            var sameFilename = JsonNode.Parse("{\"anhaenge\":[{\"name\":\"same.pdf\",\"daten\":\"data:application/pdf;base64,JVBERg==\"}]}")!.AsObject();
            try { RestoreSelection.Select(filenameOnly, sameFilename, ["all"], "replace"); throw new Exception("Filename-only identity accepted."); }
            catch (InvalidDataException) { }
            var duplicate = journal.Create(data, SnapshotReason.Periodic, "2.0.2");
            TestAssert.That(duplicate.Id == first.Id && journal.List().Count == 1, "15-Minuten-Deduplizierung greift nicht.");

            File.AppendAllText(Path.Combine(first.Directory, "payload.magnolie"), "x");
            TestAssert.That(journal.List().Single(item => item.Id == first.Id).Integrity == "damaged",
                "Ein beschädigter Snapshot wird in der Liste fälschlich als intakt gemeldet.");
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
            TestAssert.That(journal.SetMaximum(3).Maximum == 3,
                "Die gewählte Anzahl der Wiederherstellungspunkte wird nicht gespeichert.");
            for (var index = 0; index < 5; index++)
            {
                now = now.AddHours(1);
                journal.Create(new JsonObject { ["termine"] = new JsonArray(
                    new JsonObject { ["id"] = $"retention-{index}" }) }, SnapshotReason.PreSync, "2.0.2");
            }
            TestAssert.That(journal.List().Count == 3,
                "Die gewählte Anzahl der Wiederherstellungspunkte wird nicht durchgesetzt.");
            var daysSchedule = journal.SetRetention("days", 9, 2);
            TestAssert.That(daysSchedule.Mode == "days" && daysSchedule.Maximum == 9 && daysSchedule.Days == 2,
                "Der tagebasierte Aufbewahrungsmodus wird nicht vollständig gespeichert.");
            var persistedJournal = new RecoveryJournal(Path.Combine(root, "wiederherstellungsstaende"),
                Path.Combine(root, "journal.json"), clock: () => now);
            TestAssert.That(persistedJournal.Schedule() is { Mode: "days", Maximum: 9, Days: 2 },
                "Die Aufbewahrungswahl überlebt keinen Neustart.");
            var expiring = journal.Create(new JsonObject { ["termine"] = new JsonArray(
                new JsonObject { ["id"] = "days-old" }) }, SnapshotReason.PreSync, "2.0.2");
            now = now.AddDays(3);
            var current = journal.Create(new JsonObject { ["termine"] = new JsonArray(
                new JsonObject { ["id"] = "days-current" }) }, SnapshotReason.PreSync, "2.0.2");
            TestAssert.That(journal.List().All(item => item.Id != expiring.Id) &&
                journal.List().Any(item => item.Id == current.Id) && journal.List().Any(item => item.Id == manual.Id),
                "Die tagebasierte Aufbewahrung entfernt junge oder angeheftete Stände nicht korrekt.");
            TestAssert.That(journal.SetMaximum(2) is { Mode: "count", Maximum: 2, Days: 2 },
                "Der alte journal_anzahl-Vertrag schaltet nicht kompatibel auf Anzahl zurück.");

            var protectedMaximumRoot = Path.Combine(root, "protected-maximum");
            var protectedMaximum = new RecoveryJournal(protectedMaximumRoot,
                Path.Combine(root, "protected-maximum.json"), clock: () => now);
            protectedMaximum.SetRetention("count", 2, 1);
            var pinnedOne = protectedMaximum.Create(new JsonObject { ["id"] = "manual-1" }, SnapshotReason.Manual, "2.0.2");
            now = now.AddSeconds(1);
            var pinnedTwo = protectedMaximum.Create(new JsonObject { ["id"] = "manual-2" }, SnapshotReason.Manual, "2.0.2");
            now = now.AddSeconds(1);
            var newest = protectedMaximum.Create(new JsonObject { ["id"] = "automatic" }, SnapshotReason.Periodic, "2.0.2");
            TestAssert.That(protectedMaximum.List().Any(item => item.Id == pinnedOne.Id) &&
                protectedMaximum.List().Any(item => item.Id == pinnedTwo.Id) &&
                protectedMaximum.List().Any(item => item.Id == newest.Id),
                "Ein neuer automatischer Stand wurde gelöscht, obwohl bereits alle Zählplätze geschützt waren.");
            now = now.AddSeconds(1);
            var nextAutomatic = protectedMaximum.Create(new JsonObject { ["id"] = "next-automatic" }, SnapshotReason.Periodic, "2.0.2");
            TestAssert.That(protectedMaximum.List().Count == 3 &&
                protectedMaximum.List().Any(item => item.Id == nextAutomatic.Id) &&
                protectedMaximum.List().All(item => item.Id != newest.Id),
                "The temporary creation lease retained an extra old automatic point.");

            var compressionRoot = Path.Combine(root, "compression");
            var compressionNow = new DateTimeOffset(2024, 1, 1, 10, 0, 0, TimeSpan.Zero);
            var compressionJournal = new RecoveryJournal(compressionRoot,
                Path.Combine(root, "compression.json"), clock: () => compressionNow);
            var compressionData = new JsonObject { ["notizen"] = new JsonArray(
                Enumerable.Range(0, 200).Select(index => (JsonNode)new JsonObject
                    { ["id"] = index.ToString(), ["text"] = new string('M', 200) }).ToArray()) };
            var oldPoint = compressionJournal.Create(compressionData, SnapshotReason.Manual, "2.0.2");
            compressionNow = compressionNow.AddDays(366);
            var compressed = compressionJournal.CompressOld();
            TestAssert.That(compressed == (1, 0) &&
                File.Exists(Path.Combine(oldPoint.Directory, "payload.magnolie.tar.xz")) &&
                !File.Exists(Path.Combine(oldPoint.Directory, "payload.magnolie")) &&
                GesamtarchivService.Read(compressionJournal.ReadPayload(oldPoint.Id)).Daten["notizen"]!.AsArray().Count == 200,
                "Ein mehr als ein Jahr alter Einzelstand wurde nicht verlustfrei als XZ komprimiert.");
            using (var retentionCommand = BridgeDispatcherContract.Parse(
                "{\"cmd\":\"journal_aufbewahrung\",\"modus\":\"days\",\"maximum\":20,\"tage\":14}")) { }
            using (var legacyCountCommand = BridgeDispatcherContract.Parse(
                "{\"cmd\":\"journal_anzahl\",\"maximum\":20}")) { }
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
            var failedRewrite = failingJournal.RewritePayloads((text, _) =>
                text == beforeFailedRewrite ? text + "veraendert" : text);
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

            var leasedPayloadPath = Path.Combine(leasedPoint.Directory, "payload.magnolie");
            var leasedPayload = File.ReadAllText(leasedPayloadPath);
            File.AppendAllText(leasedPayloadPath, "manipuliert");
            TestAssert.That(restartedJournal.ReleaseAbandonedRestoreLeases() == 1 &&
                !File.Exists(Path.Combine(leasedPoint.Directory, ".restore-lease")),
                "Die Lease-Bereinigung hing von der Payload-Prüfung ab oder gab den Lease nicht frei.");
            try { restartedJournal.ReadPayload(leasedPoint.Id); throw new InvalidOperationException("Manipulierter Restore-Payload wurde angenommen."); }
            catch (InvalidDataException) { }
            File.WriteAllText(leasedPayloadPath, leasedPayload);
            TestAssert.That(restartedJournal.List().Any(item => item.Id == leasedPoint.Id && !item.Pinned),
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
                { ["kontakte"] = new JsonArray(new JsonObject { ["uid"] = "dead" }), ["termine"] = new JsonArray(),
                    ["aufgaben"] = new JsonArray(new JsonObject { ["uid"] = "dead-task" }) } };
            var newEpoch = RestoreSyncState.Prepare(restored, now);
            TestAssert.That(newEpoch != "old" && restored["syncNachRestore"]?["additiv"]?.GetValue<bool>() == true &&
                restored["geloescht"]?["kontakte"]?.AsArray().Count == 0 &&
                restored["geloescht"]?["aufgaben"]?.AsArray().Count == 0 &&
                restored["syncMetadaten"]?["quarantinedDeletes"]?["geloescht"]?["kontakte"]?.AsArray().Count == 1 &&
                restored["syncMetadaten"]?["quarantinedDeletes"]?["geloescht"]?["aufgaben"]?.AsArray().Count == 1,
                "Restore erneuert die Epoche oder quarantänisiert alte Tombstones nicht.");
            var crossPlatform = JsonNode.Parse(File.ReadAllText("tests/fixtures/recovery-deletions.json"))!.AsObject();
            foreach (var platform in new[] { "linux", "windows" })
            {
                var fixture = crossPlatform[platform]!.DeepClone().AsObject();
                RestoreSyncState.Prepare(fixture, now);
                foreach (var field in new[] { "geloescht", "tombstones", "baumKontaktGeloescht" })
                    TestAssert.That(JsonNode.DeepEquals(fixture["syncMetadaten"]!["quarantinedDeletes"]![field],
                        crossPlatform[platform]![field]), "Cross-platform deletion quarantine lost " + field);
                TestAssert.That(fixture["tombstones"]!.AsArray().Count == 0 && fixture["baumKontaktGeloescht"]!.AsArray().Count == 0,
                    "Archived deletion authority remains active.");
            }
            var liveCustom = new JsonObject { ["personalSync"] = new JsonObject {
                ["actor_id"] = "live-actor", ["custom_revision"] = 100,
                ["custom_entities"] = new JsonObject { ["retained"] = new JsonObject { ["item_id"] = "removed-item", ["hash"] = "prior" } } } };
            foreach (var archive in new[] { new JsonObject(), new JsonObject { ["personalSync"] = new JsonObject {
                ["actor_id"] = "archive-actor", ["custom_revision"] = 10, ["custom_auto_hash"] = "old-proof" } } })
            {
                RestoreSyncState.Prepare(archive, now, liveCustom);
                TestAssert.That(archive["personalSync"]?["actor_id"]?.GetValue<string>() == "live-actor" &&
                    archive["personalSync"]?["custom_revision"]?.GetValue<int>() == 100 &&
                    JsonNode.DeepEquals(archive["personalSync"]?["custom_entities"], liveCustom["personalSync"]?["custom_entities"]) &&
                    archive["personalSync"]?["custom_auto_hash"] is null, "Restore imported archive protocol authority or lost deletion baseline.");
            }
        }
        finally { try { Directory.Delete(root, true); } catch { } }
    }

    private static async Task TestLoadedOutboxQuarantine(string root)
    {
        var paths = new WindowsPaths(Path.Combine(root, "loaded-tree"));
        var storage = new MagnolienbaumStore(paths); var state = storage.LoadOrCreate();
        state["partner"] = new JsonArray(new JsonObject { ["kennung"] = "peer", ["name"] = "Peer", ["bestaetigt"] = true,
            ["oeffentlich"] = Convert.ToBase64String(MagnolienbaumCrypto.GenerateX25519().Public),
            ["adresse"] = "192.0.2.1", ["port"] = 8737, ["protokoll"] = "baum-1" });
        storage.SaveState(state);
        storage.SaveOutbox(new JsonArray(new JsonObject { ["id"] = "before-restore", ["transportId"] = Convert.ToBase64String(new byte[16]),
            ["an"] = "peer", ["art"] = "notiz", ["inhalt"] = new JsonObject { ["art"] = "notiz", ["text"] = "OLD" },
            ["versuche"] = 0, ["angelegt"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"), ["zuletzt"] = "" }));
        using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
        using var handler = new WaitingOutboxHandler();
        var flags = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
        var clientField = typeof(MagnolienbaumCoordinator).GetField("client", flags)!;
        ((HttpClient)clientField.GetValue(coordinator)!).Dispose(); clientField.SetValue(coordinator, new HttpClient(handler));
        var maintain = typeof(MagnolienbaumCoordinator).GetMethod("MaintainOutboxAsync", flags)!;
        var inFlight = (Task)maintain.Invoke(coordinator, [1, CancellationToken.None])!;
        await handler.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var quarantine = await coordinator.QuarantineOutboxAsync().WaitAsync(TimeSpan.FromSeconds(5));
        await TestAssert.ThrowsAsync<OperationCanceledException>(() => inFlight, "Restore did not cancel the old in-flight delivery.");
        TestAssert.That(quarantine is not null && File.Exists(quarantine) && JsonNode.Parse(File.ReadAllText(quarantine))!.AsArray().Count == 1 &&
            new MagnolienbaumStore(paths).LoadOutbox().Count == 0, "Restore did not durably quarantine the loaded queue.");
        await (Task)maintain.Invoke(coordinator, [1, CancellationToken.None])!;
        TestAssert.That(handler.Calls == 1 && !File.Exists(paths.BaumOutbox), "Quarantined memory state sent or recreated the old live queue.");
        var dispatcher = File.ReadAllText("BridgeDispatcher.cs");
        foreach (var method in new[] { "RestoreBackupAsync", "ImportGesamtarchivAsync", "RestoreSnapshotAsync" })
        {
            var start = dispatcher.IndexOf("private async Task " + method, StringComparison.Ordinal);
            var end = dispatcher.IndexOf("\n    private ", start + 1, StringComparison.Ordinal);
            var body = dispatcher[start..end];
            var quarantineAt = body.IndexOf("await baum.QuarantineOutboxAsync();", StringComparison.Ordinal);
            var writeAt = body.IndexOf("CommitRestoredProfile(", StringComparison.Ordinal);
            TestAssert.That(quarantineAt >= 0 && writeAt > quarantineAt, "Restore replaced data before quiescing and quarantining the live outbox.");
        }
        var commitStart = dispatcher.IndexOf("private string CommitRestoredProfile(", StringComparison.Ordinal);
        var commitEnd = dispatcher.IndexOf("\n    private ", commitStart + 1, StringComparison.Ordinal);
        var commit = dispatcher[commitStart..commitEnd];
        var intentAt = commit.IndexOf("telefon.PrepareRestoreCommit(", StringComparison.Ordinal);
        TestAssert.That(intentAt >= 0 && intentAt < commit.IndexOf("store.WriteRecoverableJson(paths.Data,", StringComparison.Ordinal),
            "Profile replacement lost its durable restore intent.");
    }

    private sealed class WaitingOutboxHandler : HttpMessageHandler
    {
        internal readonly TaskCompletionSource<bool> Started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int Calls;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++; Started.TrySetResult(true);
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            throw new InvalidOperationException("Old delivery unexpectedly completed.");
        }
    }
}
