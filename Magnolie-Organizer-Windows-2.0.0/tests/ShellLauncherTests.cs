namespace MagnolieOrganizer.Windows.Tests;

internal static class ShellLauncherTests
{
    internal static Task RunAsync()
    {
        foreach (var target in new[]
                 {
                     "https://example.org/path", "http://example.org/", "mailto:user@example.org", "tel:+491234567"
                 })
            TestAssert.That(ShellLauncher.IsAllowedExternalUri(target), $"Erlaubte externe URI wurde abgelehnt: {target}");

        foreach (var target in new[]
                 {
                     "file:///C:/Windows/System32/calc.exe", "search-ms:query=test", "ms-msdt:/id=test",
                     "custom:payload", "C:\\Windows\\System32\\calc.exe", "relative/path", ""
                 })
            TestAssert.That(!ShellLauncher.IsAllowedExternalUri(target), $"Unsicheres URI-Schema wurde erlaubt: {target}");

        TestAssert.That(ShellLauncher.IsAllowedContactUri("sms:+491234567"), "SMS-URI wurde abgelehnt.");
        TestAssert.That(ShellLauncher.IsAllowedContactUri("msteams:/l/call/0/0?users=4%3A%2B491234567"),
            "Teams-Anruf-URI wurde abgelehnt.");
        TestAssert.That(!ShellLauncher.IsAllowedContactUri("shell:AppsFolder"),
            "Beliebiges registriertes Kontaktschema wurde erlaubt.");

        var root = Path.Combine(Path.GetTempPath(), "Magnolie-ShellLauncherTests-" + Guid.NewGuid().ToString("N"));
        var outside = root + "-outside";
        try
        {
            var directory = Path.Combine(root, "sub");
            Directory.CreateDirectory(directory);
            Directory.CreateDirectory(outside);
            var file = Path.Combine(directory, "export.ods");
            var outsideFile = Path.Combine(outside, "other.ods");
            File.WriteAllText(file, "test");
            File.WriteAllText(outsideFile, "test");

            TestAssert.That(ShellLauncher.TryGetExistingLocalPath(Path.Combine(directory, ".", "export.ods"), root,
                directory: false, out var canonicalFile) && canonicalFile == Path.GetFullPath(file),
                "Vorhandene lokale Datei wurde nicht kanonisch aufgelöst.");
            TestAssert.That(ShellLauncher.TryGetExistingLocalPath(directory, root, directory: true, out var canonicalDirectory) &&
                            canonicalDirectory == Path.GetFullPath(directory),
                "Vorhandenes lokales Verzeichnis wurde nicht kanonisch aufgelöst.");
            TestAssert.That(!ShellLauncher.TryGetExistingLocalPath(outsideFile, root, directory: false, out _),
                "Datei außerhalb des erwarteten Verzeichnisses wurde erlaubt.");
            TestAssert.That(!ShellLauncher.TryGetExistingLocalPath(Path.Combine(root, "missing.ods"), root,
                directory: false, out _), "Fehlende lokale Datei wurde erlaubt.");
            TestAssert.That(!ShellLauncher.TryGetExistingLocalPath(directory, root, directory: false, out _),
                "Verzeichnis wurde als Datei erlaubt.");
            TestAssert.That(!ShellLauncher.TryGetExistingLocalPath(file, root, directory: true, out _),
                "Datei wurde als Verzeichnis erlaubt.");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
            if (Directory.Exists(outside)) Directory.Delete(outside, true);
        }

        return Task.CompletedTask;
    }
}
