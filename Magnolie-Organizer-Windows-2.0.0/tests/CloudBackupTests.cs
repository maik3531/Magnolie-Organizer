namespace MagnolieOrganizer.Windows.Tests;

internal static class CloudBackupTests
{
    internal static Task RunAsync()
    {
        DuePolicy();
        RetentionOwnership();
        SourceRoutingAndSecretSafety();
        return Task.CompletedTask;
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

    private static void SourceRoutingAndSecretSafety()
    {
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));
        var dispatcher = File.ReadAllText(Path.Combine(root, "BridgeDispatcher.cs"));
        var service = File.ReadAllText(Path.Combine(root, "CloudBackupService.cs"));
        TestAssert.That(dispatcher.Contains("RunCloudBackupAfterSaveAsync(document.RootElement.GetRawText(), force: false)"),
            "Automatik muss vom erfolgreichen Save geroutet werden.");
        TestAssert.That(dispatcher.Contains("MutationGate.Global.WaitAsync()") && dispatcher.Contains("cloud_sicherung_test"),
            "Testlauf muss den bestehenden Mutations-Gate verwenden.");
        TestAssert.That(service.Contains("DataProtectionScope.CurrentUser") && service.Contains("Entropy") &&
                        !service.Contains("WriteAllText"), "Kennwort muss nur per DPAPI und atomarem Store geschrieben werden.");
        TestAssert.That(service.IndexOf("GesamtarchivService.Read", StringComparison.Ordinal) <
                        service.IndexOf("ApplyRetention(settings.Folder", StringComparison.Ordinal),
            "Readback muss vor Erfolg und Retention erfolgen.");
    }
}
