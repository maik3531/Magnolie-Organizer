using System.Net;
using System.Security.Cryptography;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsUpdateTests
{
    private static readonly string RepositoryManifest = Path.Combine(AppContext.BaseDirectory, "release-update.xml");

    internal static async Task RunAsync()
    {
        var signed = File.ReadAllText(RepositoryManifest);
        var parsed = WindowsUpdateService.ValidateManifest(signed);
        TestAssert.That(parsed.Windows.Artifact == "windows" && parsed.Windows.Version == parsed.Manual.Version &&
            parsed.Windows.Url.EndsWith($"Magnolie-Organizer-Windows-{parsed.Windows.Version}-Setup-x64.exe", StringComparison.Ordinal),
            "Das veröffentlichte Manifest wurde nicht mit dem festen Ed25519-Schlüssel validiert.");

        TestAssert.Throws<InvalidDataException>(() => WindowsUpdateService.ValidateManifest(
            signed.Replace($"<version>{parsed.Windows.Version}</version>", "<version>9.9.9</version>", StringComparison.Ordinal)),
            "Ein nach der Signatur verändertes Manifest wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => WindowsUpdateService.ValidateManifest(
            signed.Replace("<windows>\n    <version>", "<windows><version>1.0.0</version>\n    <version>", StringComparison.Ordinal)),
            "Ein doppeltes Windows-Versionsfeld wurde angenommen.");
        TestAssert.Throws<InvalidDataException>(() => WindowsUpdateService.ValidateManifest(
            signed.Replace("<update>", "<!DOCTYPE update [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><update>", StringComparison.Ordinal)),
            "Eine DTD-/ENTITY-Deklaration wurde angenommen.");
        TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(
            "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Organizer-Windows-2.0.14-Setup-x64.exe?x=1",
            "Magnolie-Organizer-Windows-2.0.14-Setup-x64.exe"), "Eine Update-URL mit Query wurde angenommen.");

        using (var command = BridgeDispatcherContract.Parse("{\"cmd\":\"update_herunterladen\"}")) { }
        using (var command = BridgeDispatcherContract.Parse("{\"cmd\":\"update_installieren\"}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(
            "{\"cmd\":\"update_herunterladen\",\"url\":\"https://example.invalid\"}"),
            "Der parameterlose Downloadvertrag akzeptierte ein zusätzliches Feld.");

        var package = Encoding.ASCII.GetBytes("verified windows installer fixture");
        var sha = Convert.ToHexString(SHA256.HashData(package)).ToLowerInvariant();
        var release = new ValidatedRelease("9.8.7",
            "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe",
            sha, "windows");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        string started = "";
        try
        {
            using var updater = new WindowsUpdateService(root, new FixtureHandler(signed, package), false,
                path => { started = path; return true; }, release);
            var download = await updater.DownloadAsync();
            TestAssert.That(download.Ok && download.Ready && download.Artifact == "windows", "Verifiziertes Windows-Update wurde nicht vorbereitet.");
            var install = updater.PrepareInstallation();
            TestAssert.That(install.Ok && install.ReadyToExit && File.Exists(started) &&
                SHA256.HashData(File.ReadAllBytes(started)).SequenceEqual(SHA256.HashData(package)),
                "Es wurde nicht ausschließlich die verifizierte lokale EXE gestartet.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }

        var tamperRoot = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        var tamperStarted = false;
        try
        {
            using var updater = new WindowsUpdateService(tamperRoot, new FixtureHandler(signed, package), false,
                _ => { tamperStarted = true; return true; }, release);
            TestAssert.That((await updater.DownloadAsync()).Ok, "Die Manipulationsfixture wurde nicht geladen.");
            var downloaded = Directory.GetFiles(Path.Combine(tamperRoot, "updates")).Single();
            await File.AppendAllTextAsync(downloaded, "tampered");
            var rejected = updater.PrepareInstallation();
            TestAssert.That(!rejected.Ok && !tamperStarted && !File.Exists(downloaded),
                "Eine nachträglich manipulierte EXE wurde gestartet oder nicht gelöscht.");
        }
        finally { try { Directory.Delete(tamperRoot, true); } catch (Exception) { } }

        var redirectHandler = new FixtureHandler(signed, package) { RedirectPackage = true };
        var redirectRoot = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var updater = new WindowsUpdateService(redirectRoot, redirectHandler, false, _ => true, release);
            var rejected = await updater.DownloadAsync();
            TestAssert.That(!rejected.Ok && !Directory.EnumerateFiles(Path.Combine(redirectRoot, "updates")).Any(),
                "Ein fremdes Redirectziel wurde angenommen oder die Teildatei blieb liegen.");
        }
        finally { try { Directory.Delete(redirectRoot, true); } catch (Exception) { } }
    }

    private sealed class FixtureHandler(string manifest, byte[] package) : HttpMessageHandler
    {
        internal bool RedirectPackage { get; init; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.RequestUri?.AbsoluteUri == WindowsUpdateService.ManifestUrl)
                return Task.FromResult(Response(HttpStatusCode.OK, Encoding.UTF8.GetBytes(manifest), "application/xml"));
            if (RedirectPackage)
            {
                var response = Response(HttpStatusCode.Redirect, [], "application/octet-stream");
                response.Headers.Location = new Uri("https://example.invalid/payload.exe");
                return Task.FromResult(response);
            }
            return Task.FromResult(Response(HttpStatusCode.OK, package, "application/octet-stream"));
        }

        private static HttpResponseMessage Response(HttpStatusCode status, byte[] content, string type) => new(status)
        {
            Content = new ByteArrayContent(content) { Headers = { ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(type) } }
        };
    }
}
