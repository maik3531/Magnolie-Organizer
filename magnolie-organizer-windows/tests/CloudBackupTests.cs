using System.Collections.Concurrent;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CloudBackupTests
{
    internal static async Task RunAsync()
    {
        DuePolicy();
        RetentionOwnership();
        CapacityPreflight();
        NativeCapacityRetries();
        SourceRoutingAndSecretSafety();
        await WorkerCorrelationAsync();
    }

    private static void CapacityPreflight()
    {
        var root = Directory.CreateTempSubdirectory("magnolie-cloud-capacity-");
        try
        {
            for (var index = 0; index < CloudBackupService.ListingLimit - 1; index++)
                File.WriteAllText(Path.Combine(root.FullName, $"unrelated-{index:D4}.txt"), "keep");
            CloudBackupService.EnsureCapacity(root.FullName);
            Directory.CreateDirectory(Path.Combine(root.FullName, "unrelated-directory"));
            var before = Directory.GetFileSystemEntries(root.FullName).Order(StringComparer.Ordinal).ToArray();
            for (var attempt = 0; attempt < 3; attempt++)
                TestAssert.Throws<IOException>(() => CloudBackupService.EnsureCapacity(root.FullName),
                    "Auch Ordner zählen zur Auflistungsgrenze.");
            TestAssert.That(before.SequenceEqual(Directory.GetFileSystemEntries(root.FullName).Order(StringComparer.Ordinal)) &&
                Directory.GetFiles(root.FullName).All(path => File.ReadAllText(path) == "keep"),
                "Wiederholte Kapazitätsprüfungen dürfen fremde Inhalte nicht verändern.");
        }
        finally { root.Delete(recursive: true); }
    }

    private static void DuePolicy()
    {
        var now = DateTimeOffset.Parse("2026-08-31T12:00:00Z");
        TestAssert.That(!CloudBackupService.IsDue(false, "daily", "", now), "Ausgeschaltet darf nie fällig sein.");
        TestAssert.That(CloudBackupService.IsDue(true, "daily", "", now), "Ohne Erfolg ist täglich fällig.");
        TestAssert.That(!CloudBackupService.IsDue(true, "daily", "2026-08-30T12:00:01Z", now), "Vor 24 Stunden nicht fällig.");
        TestAssert.That(CloudBackupService.IsDue(true, "daily", "2026-08-30T12:00:00Z", now), "Nach 24 Stunden fällig.");
        TestAssert.That(!CloudBackupService.IsDue(true, "weekly", "2026-08-25T12:00:00Z", now), "Woche nicht vorzeitig fällig.");
        TestAssert.That(CloudBackupService.IsDue(true, "weekly", "2026-08-24T12:00:00Z", now), "Woche ist fällig.");
        TestAssert.That(CloudBackupService.BoundRetention(1) == 2 && CloudBackupService.BoundRetention(99) == 30,
            "Aufbewahrung muss 2..30 bleiben.");
    }

    private static void RetentionOwnership()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-cloud-retention-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var files = Enumerable.Range(0, 4).Select(index => Path.Combine(root,
                $"magnolie-auto-2026083{index}-120000-000000-{new string((char)('a' + index), 32)}.magnolie")).ToArray();
            foreach (var file in files) File.WriteAllText(file, "x");
            var unrelated = Path.Combine(root, "magnolie-auto-owned.txt"); File.WriteAllText(unrelated, "keep");
            var deleted = CloudBackupService.ApplyRetention(root, 2, files[^1]);
            TestAssert.That(deleted.Count == 2 && File.Exists(files[^1]), "Neue verifizierte Sicherung muss bleiben.");
            TestAssert.That(File.Exists(unrelated), "Fremde Datei darf nicht gelöscht werden.");
        }
        finally { Directory.Delete(root, true); }
    }

    private static void NativeCapacityRetries()
    {
        if (!OperatingSystem.IsWindows())
        {
            Console.WriteLine("  SKIP CloudBackup CreateVerified / DPAPI: requires native Windows; capacity policy ran.");
            return;
        }
        var root = Path.Combine(Path.GetTempPath(), "magnolie-cloud-native-capacity-" + Guid.NewGuid().ToString("N"));
        var folder = Path.Combine(root, "backups");
        Directory.CreateDirectory(folder);
        try
        {
            var service = new CloudBackupService(Path.Combine(root, "owned-secret"));
            service.StorePassword("owned-capacity-regression-password");
            var data = System.Text.Json.Nodes.JsonNode.Parse("{\"version\":7,\"notizen\":[],\"einstellungen\":{}}")!.AsObject();
            var settings = new CloudBackupSettings(true, "daily", 2, "", folder);
            for (var index = 0; index < CloudBackupService.ListingLimit - 1; index++)
                File.WriteAllText(Path.Combine(folder, $"unrelated-{index:D4}.txt"), "keep");
            var verified = service.CreateVerified(data, settings, "owned-version");
            TestAssert.That(File.Exists(verified), "999 Einträge müssen eine verifizierte neue Sicherung zulassen.");
            var verifiedBytes = File.ReadAllBytes(verified);
            var before = Directory.GetFileSystemEntries(folder).Order(StringComparer.Ordinal).ToArray();
            for (var attempt = 0; attempt < 3; attempt++)
                TestAssert.Throws<IOException>(() => service.CreateVerified(data, settings, "owned-version"),
                    "Volle Sicherungsordner müssen vor einer weiteren Archiverzeugung abgewiesen werden.");
            TestAssert.That(before.SequenceEqual(Directory.GetFileSystemEntries(folder).Order(StringComparer.Ordinal)),
                "Fehlgeschlagene Wiederholungen dürfen keine weiteren Archive hinterlassen.");
            TestAssert.That(File.Exists(verified) && File.ReadAllBytes(verified).SequenceEqual(verifiedBytes),
                "Die zuvor verifizierte Sicherung muss bytegleich erhalten bleiben.");
        }
        finally { Directory.Delete(root, true); }
    }

    private static void SourceRoutingAndSecretSafety()
    {
        var root = TestSource.Root("MagnolieOrganizer.Windows.csproj");
        var dispatcher = File.ReadAllText(Path.Combine(root, "BridgeDispatcher.cs"));
        var service = File.ReadAllText(Path.Combine(root, "CloudBackupService.cs"));
        TestAssert.That(dispatcher.Contains("RunCloudBackupAfterSaveAsync(document.RootElement.GetRawText(), force: false)"),
            "Automatik muss vom erfolgreichen Save geroutet werden.");
        TestAssert.That(dispatcher.Contains("MutationGate.Global.WaitAsync()") && dispatcher.Contains("cloud_sicherung_test"),
            "Testlauf muss den bestehenden Mutations-Gate verwenden.");
        TestAssert.That(service.Contains("DataProtectionScope.CurrentUser") && service.Contains("Entropy") &&
                        !service.Contains("WriteAllText"), "Kennwort muss nur per DPAPI und atomarem Store geschrieben werden.");
        var preflight = service.IndexOf("EnsureCapacity(settings.Folder)", StringComparison.Ordinal);
        TestAssert.That(preflight >= 0 && preflight < service.IndexOf("GesamtarchivService.Create", StringComparison.Ordinal),
            "Ein voller Zielordner muss vor der Archiverzeugung abgewiesen werden.");
        TestAssert.That(service.IndexOf("GesamtarchivService.Read", StringComparison.Ordinal) <
                        service.IndexOf("ApplyRetention(settings.Folder", StringComparison.Ordinal),
            "Readback muss vor Erfolg und Retention erfolgen.");
    }

    private static async Task WorkerCorrelationAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-cloud-worker-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var files = new AtomicStore();
            var service = new CloudBackupService(Path.Combine(root, "owned-secret"), files);
            var replies = new ConcurrentQueue<JsonElement>();
            var fail = false;
            await using (var worker = new CloudBackupWorker(service, Path.Combine(root, "worker-state.json"), "owned-version",
                (_callback, payload) => { replies.Enqueue(JsonSerializer.SerializeToElement(payload)); return Task.CompletedTask; },
                pollingInterval: TimeSpan.FromHours(1), passwordAvailable: () => true,
                create: (data, settings, _cancellation) =>
                {
                    if (fail) throw new IOException("owned-private-worker-error");
                    var path = Path.Combine(settings.Folder, "owned-verified.magnolie");
                    files.Write(path, GesamtarchivService.Create(data, "windows", "owned-version", "owned-worker-password"));
                    _ = GesamtarchivService.Read(files.Read(path)!, "owned-worker-password");
                    return path;
                }))
            {
                string Snapshot(string folder) => JsonSerializer.Serialize(new { version = 7,
                    notizen = new[] { new { id = "owned-worker-note", titel = "Owned", text = "Owned worker payload" } },
                    einstellungen = new { allgemein = new { sicherungsordner = folder,
                        cloudSicherung = new { aktiv = false, intervall = "weekly", aufbewahrung = 7 } } } });
                worker.UpdateSnapshot(Snapshot(root));
                await worker.RunNowAsync("owned-success-request", "owned-success-source").WaitAsync(TimeSpan.FromSeconds(5));
                var success = replies.Last(value => value.GetProperty("requestId").GetString() == "owned-success-request");
                TestAssert.That(success.GetProperty("sourceToken").GetString() == "owned-success-source" && success.GetProperty("status").GetString() == "success",
                    "Erfolg muss die tatsächliche Request-/Quellidentität behalten.");
                var archive = GesamtarchivService.Read(files.Read(success.GetProperty("pfad").GetString()!)!, "owned-worker-password");
                TestAssert.That(archive.Daten["notizen"]![0]!["text"]!.GetValue<string>() == "Owned worker payload",
                    "Workererfolg muss zu tatsächlich geschriebenen und verifizierten Archivdaten gehören.");
                worker.UpdateSnapshot(Snapshot(""));
                await worker.RunNowAsync("owned-folder-request", "owned-folder-source").WaitAsync(TimeSpan.FromSeconds(5));
                var missing = replies.Last(value => value.GetProperty("requestId").GetString() == "owned-folder-request");
                TestAssert.That(missing.GetProperty("status").GetString() == "folder_missing" && missing.GetProperty("sourceToken").GetString() == "owned-folder-source",
                    "Auch fehlende Voraussetzungen müssen korreliert antworten.");
                fail = true; worker.UpdateSnapshot(Snapshot(root));
                await worker.RunNowAsync("owned-failure-request", "owned-failure-source").WaitAsync(TimeSpan.FromSeconds(5));
                var failed = replies.Last(value => value.GetProperty("requestId").GetString() == "owned-failure-request");
                TestAssert.That(failed.GetProperty("status").GetString() == "failed" && failed.GetProperty("sourceToken").GetString() == "owned-failure-source" &&
                    !failed.GetRawText().Contains("owned-private-worker-error"), "Workerfehler müssen korreliert und ohne Rohfehler antworten.");
            }
        }
        finally { Directory.Delete(root, true); }
    }
}
