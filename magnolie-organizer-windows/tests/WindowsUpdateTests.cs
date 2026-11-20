using System.Net;
using System.Security.Cryptography;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsUpdateTests
{
    private static readonly string RepositoryManifest = Path.Combine(AppContext.BaseDirectory, "release-update.xml");
    private const string RawBase = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/";
    private const string RegistryBase = "https://gitlab.com/api/v4/projects/78301901/packages/generic/magnolie-desktop/";

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
        foreach (var newline in new[] { "\n", "\r\n" })
        {
            var fixture = signed.ReplaceLineEndings(newline);
            _ = WindowsUpdateService.ValidateManifest(fixture);
            var document = System.Xml.Linq.XDocument.Parse(fixture);
            var windows = document.Root!.Element("windows")!;
            // Duplicate the same value so rejection proves structural validation,
            // rather than merely a changed version or invalid signature.
            windows.Add(new System.Xml.Linq.XElement(windows.Element("version")!));
            TestAssert.That(windows.Elements("version").Count() == 2,
                "Die negative Manifest-Fixture enthält kein doppeltes Versionsfeld.");
            TestAssert.Throws<InvalidDataException>(() => WindowsUpdateService.ValidateManifest(
                document.ToString(System.Xml.Linq.SaveOptions.DisableFormatting)),
                "Ein doppeltes Windows-Versionsfeld wurde angenommen.");
        }
        TestAssert.Throws<InvalidDataException>(() => WindowsUpdateService.ValidateManifest(
            signed.Replace("<update>", "<!DOCTYPE update [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><update>", StringComparison.Ordinal)),
            "Eine DTD-/ENTITY-Deklaration wurde angenommen.");
        TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(
            "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/Magnolie-Organizer-Windows-2.0.14-Setup-x64.exe?x=1",
            "Magnolie-Organizer-Windows-2.0.14-Setup-x64.exe", "2.0.14"), "Eine Update-URL mit Query wurde angenommen.");
        CheckRegistryUrlPolicy(signed, parsed.Windows.Version);

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
        await CheckRegistryDownloadAsync(signed, package, release);
        var root = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        string started = "";
        try
        {
            using var updater = new WindowsUpdateService(root, new FixtureHandler(signed, package), false,
                path => { started = path; return true; }, release);
            var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
            var manifestHttp = (HttpClient)typeof(WindowsUpdateService).GetField("http", flags)!.GetValue(updater)!;
            var installerHttp = (HttpClient)typeof(WindowsUpdateService).GetField("packageHttp", flags)!.GetValue(updater)!;
            TestAssert.That(manifestHttp.Timeout == TimeSpan.FromSeconds(30) &&
                installerHttp.Timeout == TimeSpan.FromMinutes(10) && !ReferenceEquals(manifestHttp, installerHttp),
                "Der große Installer muss eine eigene begrenzte Downloadfrist erhalten; die Manifestfrist bleibt kurz.");
            TestAssert.That(updater.IsValidatedReleaseUrl(release.Url) &&
                            !updater.IsValidatedReleaseUrl(release.Url + "?untrusted=1") &&
                            !updater.IsValidatedReleaseUrl(release.Url.Replace("9.8.7", "9.8.8", StringComparison.Ordinal)),
                "Der manuelle Download ist nicht auf die zuvor signaturgeprüfte exakte Release-URL begrenzt.");
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
            TestAssert.That(rejected.Error == NativeLocalization.Gettext("The package could not be opened."),
                "Der Installationsfehler wurde nicht über den nativen Katalog lokalisiert.");
        }
        finally { try { Directory.Delete(tamperRoot, true); } catch (Exception) { } }

        var redirectHandler = new FixtureHandler(signed, package) { RedirectPackage = true };
        var redirectRoot = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            NativeLocalization.SetLanguage("de");
            using var updater = new WindowsUpdateService(redirectRoot, redirectHandler, false, _ => true, release);
            var rejected = await updater.DownloadAsync();
            TestAssert.That(!rejected.Ok && !Directory.EnumerateFiles(Path.Combine(redirectRoot, "updates")).Any(),
                "Ein fremdes Redirectziel wurde angenommen oder die Teildatei blieb liegen.");
            TestAssert.That(rejected.Error == NativeLocalization.Gettext("The package could not be opened.", "de") &&
                            !rejected.Error.Contains("redirect", StringComparison.OrdinalIgnoreCase),
                "Der Downloadfehler wurde nicht lokalisiert oder gab einen technischen Exception-Text weiter.");
        }
        finally
        {
            NativeLocalization.SetLanguage("system");
            try { Directory.Delete(redirectRoot, true); } catch (Exception) { }
        }

        var checkRoot = Path.Combine(Path.GetTempPath(), "magnolie-update-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            NativeLocalization.SetLanguage("de");
            using var updater = new WindowsUpdateService(checkRoot, new FailingHandler(), false);
            var rejected = await updater.CheckAsync("1.0.0");
            TestAssert.That(!rejected.Ok &&
                            rejected.Error == NativeLocalization.Gettext("The update check failed.", "de") &&
                            !rejected.Error.Contains(FailingHandler.Secret, StringComparison.Ordinal),
                "Der Prüfungsfehler wurde nicht lokalisiert oder gab Exception.Message an die UI weiter.");

            var bridge = File.ReadAllText("BridgeDispatcher.cs");
            var manualStart = bridge.IndexOf("private async Task DownloadManualAsync", StringComparison.Ordinal);
            var manualEnd = bridge.IndexOf("private async Task FetchWeatherAsync", manualStart, StringComparison.Ordinal);
            var manual = bridge[manualStart..manualEnd];
            TestAssert.That(manual.Contains("T(\"The manual package could not be opened.\")", StringComparison.Ordinal) &&
                            !manual.Contains("fehler = error.Message", StringComparison.Ordinal),
                "Der Handbuch-Updatefehler reicht weiterhin Exception.Message an die UI durch.");
        }
        finally
        {
            NativeLocalization.SetLanguage("system");
            try { Directory.Delete(checkRoot, true); } catch (Exception) { }
        }
    }

    private static void CheckRegistryUrlPolicy(string signed, string signedVersion)
    {
        const string version = "9.8.7";
        const string installer = "Magnolie-Organizer-Windows-9.8.7-Setup-x64.exe";
        var registry = RegistryBase + version + "/" + installer;
        TestAssert.That(WindowsUpdateService.ManifestUrl == RawBase + "update.xml",
            "Die feste Manifest-Adresse darf durch Registry-Kompatibilität nicht wechseln.");
        foreach (var file in new[] { installer, "magnolie-organizer_9.8.7_all.deb",
            "magnolie-handbuch_9.8.7_all.deb", "Magnolie-Organizer-9.8.7-x86_64.AppImage" })
        {
            TestAssert.That(WindowsUpdateService.IsExactPackageUrl(RawBase + file, file, version) &&
                            WindowsUpdateService.IsExactPackageUrl(RegistryBase + version + "/" + file, file, version),
                "Nur der exakte bestehende Raw- oder zusätzliche Registry-Paketpfad muss angenommen werden.");
        }
        var invalid = new[]
        {
            registry.Replace("/78301901/", "/78301902/", StringComparison.Ordinal),
            registry.Replace("/magnolie-desktop/", "/magnolie-notes-fdroid-reference/", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.8/", StringComparison.Ordinal),
            registry.Replace("Setup-x64.exe", "Setup-x86.exe", StringComparison.Ordinal),
            registry.Replace("https://", "http://", StringComparison.Ordinal),
            registry.Replace("gitlab.com", "gitlab.com.example.invalid", StringComparison.Ordinal),
            registry.Replace("gitlab.com", "GITLAB.COM", StringComparison.Ordinal),
            registry.Replace("gitlab.com", "gitlab.com:443", StringComparison.Ordinal),
            registry.Replace("gitlab.com", "gitlab.com:8443", StringComparison.Ordinal),
            registry.Replace("gitlab.com", "user@gitlab.com", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/%39.8.7/", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.7/unused/../", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.7/./", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.7/%2e/", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.7%2f", StringComparison.Ordinal),
            registry.Replace("/9.8.7/", "/9.8.7\\", StringComparison.Ordinal),
            registry.Replace(installer, "%4d" + installer[1..], StringComparison.Ordinal),
            registry + "?", registry + "?download=1", registry + "#", registry + "#payload",
            registry + "/", " " + registry, registry + "\n"
        };
        foreach (var target in invalid)
            TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(target, installer, version),
                "Eine fremde oder nicht kanonisch geschriebene Registry-Adresse wurde angenommen.");
        foreach (var suffix in new[] { "?x=1", "#payload", "/", "\n" })
            TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(RawBase + installer + suffix, installer, version),
                "Die bestehende Raw-Route darf keine zusätzlichen URL-Bestandteile akzeptieren.");
        TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(registry, installer, "9.8.8"),
            "Das Registry-Verzeichnis muss an die signierte Hauptversion gebunden sein.");
        TestAssert.That(!WindowsUpdateService.IsExactPackageUrl(RawBase + "../" + installer, "../" + installer, version),
            "Ein manipuliertes erwartetes Dateinamenargument darf keinen Pfad einschleusen.");

        // There is deliberately no alternate public key or fabricated production
        // signature. Repointing a real signed Raw manifest must reach signature
        // verification and fail there even when all new Registry URLs are allowed.
        var repointed = signed.Replace(RawBase, RegistryBase + signedVersion + "/", StringComparison.Ordinal);
        TestAssert.That(repointed != signed, "Die Registry-Manipulationsfixture enthält keine URL-Änderung.");
        try
        {
            _ = WindowsUpdateService.ValidateManifest(repointed);
            throw new InvalidOperationException("Ein nachträglich auf Registry umgebogenes Manifest wurde angenommen.");
        }
        catch (InvalidDataException error)
        {
            TestAssert.That(error.Message.Contains("signature", StringComparison.OrdinalIgnoreCase),
                "Die exakten Registry-Adressen müssen die URL-Prüfung passieren; die vorhandene Signatur muss sie dennoch ablehnen.");
        }
    }

    private static async Task CheckRegistryDownloadAsync(string signed, byte[] package, ValidatedRelease rawRelease)
    {
        var release = rawRelease with { Url = RegistryBase + rawRelease.Version + "/" + Path.GetFileName(new Uri(rawRelease.Url).AbsolutePath) };
        var root = Path.Combine(Path.GetTempPath(), "magnolie-registry-update-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            // The existing test-only initialRelease seam supplies synthetic bytes;
            // this is a transport/hash test, never a signed release/native proof.
            using var updater = new WindowsUpdateService(root, new FixtureHandler(signed, package), false,
                _ => true, release);
            TestAssert.That(updater.IsValidatedReleaseUrl(release.Url) &&
                            !updater.IsValidatedReleaseUrl(rawRelease.Url) &&
                            !updater.IsValidatedReleaseUrl(release.Url.Replace("/9.8.7/", "/9.8.8/", StringComparison.Ordinal)),
                "Die manuelle Registry-URL ist nicht an die zuvor geprüfte exakte Adresse gebunden.");
            TestAssert.That((await updater.DownloadAsync()).Ok && updater.PrepareInstallation().Ok,
                "Das synthetische Registry-Paket wurde nicht mit bestehender Hash-/Installationsbindung geprüft.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }

        foreach (var target in new[]
        {
            "https://example.invalid/payload.exe", rawRelease.Url,
            release.Url.Replace("/78301901/", "/78301902/", StringComparison.Ordinal),
            release.Url.Replace("/9.8.7/", "/9.8.8/", StringComparison.Ordinal),
            release.Url.Replace("/9.8.7/", "/9.8.7/unused/../", StringComparison.Ordinal),
            release.Url.Replace("/9.8.7/", "/%39.8.7/", StringComparison.Ordinal),
            release.Url.Replace("gitlab.com", "gitlab.com:443", StringComparison.Ordinal),
            "./" + Path.GetFileName(new Uri(release.Url).AbsolutePath)
        })
        {
            root = Path.Combine(Path.GetTempPath(), "magnolie-registry-redirect-test-" + Guid.NewGuid().ToString("N"));
            var handler = new FixtureHandler(signed, package) { RedirectTarget = new Uri(target, UriKind.RelativeOrAbsolute) };
            try
            {
                using var updater = new WindowsUpdateService(root, handler, false, _ => true, release);
                TestAssert.That(!(await updater.DownloadAsync()).Ok && handler.Requests == 1 &&
                                !Directory.EnumerateFiles(Path.Combine(root, "updates")).Any(),
                    "Ein abweichendes oder zuvor normalisiertes Registry-Redirectziel wurde angefordert.");
            }
            finally { try { Directory.Delete(root, true); } catch (Exception) { } }
        }
        foreach (var target in new[] { release.Url, new Uri(release.Url).AbsolutePath,
                                      Path.GetFileName(new Uri(release.Url).AbsolutePath) })
        {
            root = Path.Combine(Path.GetTempPath(), "magnolie-registry-exact-redirect-test-" + Guid.NewGuid().ToString("N"));
            var handler = new FixtureHandler(signed, package)
            {
                RedirectTarget = new Uri(target, UriKind.RelativeOrAbsolute), RedirectOnce = true
            };
            try
            {
                using var updater = new WindowsUpdateService(root, handler, false, _ => true, release);
                TestAssert.That((await updater.DownloadAsync()).Ok && handler.Requests == 2,
                    "Eine kanonisch geschriebene Weiterleitung auf dasselbe signierte Registry-Ziel wurde abgelehnt.");
            }
            finally { try { Directory.Delete(root, true); } catch (Exception) { } }
        }
        root = Path.Combine(Path.GetTempPath(), "magnolie-registry-hash-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var updater = new WindowsUpdateService(root, new FixtureHandler(signed, [.. package, 0]), false,
                _ => throw new InvalidOperationException("Ein falsches Registry-Paket wurde gestartet."), release);
            TestAssert.That(!(await updater.DownloadAsync()).Ok &&
                            !Directory.EnumerateFiles(Path.Combine(root, "updates")).Any(),
                "Ein Registry-Paket mit falschem Hash wurde vorbereitet oder nicht entfernt.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private sealed class FailingHandler : HttpMessageHandler
    {
        internal const string Secret = "raw-transport-detail";

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            throw new HttpRequestException(Secret);
    }

    private sealed class FixtureHandler(string manifest, byte[] package) : HttpMessageHandler
    {
        internal bool RedirectPackage { get; init; }
        internal Uri? RedirectTarget { get; init; }
        internal bool RedirectOnce { get; init; }
        internal int Requests { get; private set; }
        private bool redirected;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests++;
            if (request.RequestUri?.AbsoluteUri == WindowsUpdateService.ManifestUrl)
                return Task.FromResult(Response(HttpStatusCode.OK, Encoding.UTF8.GetBytes(manifest), "application/xml"));
            if ((RedirectPackage || RedirectTarget is not null) && (!RedirectOnce || !redirected))
            {
                redirected = true;
                var response = Response(HttpStatusCode.Redirect, [], "application/octet-stream");
                response.Headers.Location = RedirectTarget ?? new Uri("https://example.invalid/payload.exe");
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
