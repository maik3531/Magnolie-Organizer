using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NextcloudMailboxTests
{
    internal static async Task RunAsync()
    {
        TestServerAndSecretStorage();
        TestAuthenticatedDocuments();
        await TestWebDavAsync();
        await TestWebDavFailuresAsync();
        await TestDamagedSettingsStatusAsync();
        TestReservedCounterRecovery();
    }

    private static void TestServerAndSecretStorage()
    {
        using (var statusCommand = BridgeDispatcherContract.Parse("{\"cmd\":\"baum_briefkasten_status\"}")) { }
        using (var testCommand = BridgeDispatcherContract.Parse("{\"cmd\":\"baum_briefkasten_pruefen\"}")) { }
        using (var saveCommand = BridgeDispatcherContract.Parse("{\"cmd\":\"baum_briefkasten_speichern\",\"davAktiv\":true,\"briefkastenAktiv\":false,\"url\":\"https://cloud.example\",\"benutzer\":\"user\",\"anwendungskennwort\":\"\",\"kennwortLoeschen\":false}")) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(
            "{\"cmd\":\"baum_briefkasten_speichern\",\"davAktiv\":true,\"briefkastenAktiv\":false,\"url\":\"https://cloud.example\",\"benutzer\":\"user\",\"kennwortLoeschen\":false}"),
            "Der Briefkastenvertrag akzeptierte einen Speicherbefehl ohne Kennwortfeld.");
        foreach (var invalid in new[]
                 {
                     "http://cloud.example", "//cloud.example", "https://user@cloud.example", "https://cloud.example?q=1",
                     "https://cloud.example/#fragment"
                 })
            TestAssert.Throws<ArgumentException>(() => NextcloudMailbox.ValidateServer(invalid), $"Unsichere Serverbasis akzeptiert: {invalid}");

        var root = Path.Combine(Path.GetTempPath(), $"magnolie-webdav-secret-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var settingsPath = Path.Combine(root, "settings.json");
            var passwordPath = Path.Combine(root, "password.dpapi");
            var store = new NextcloudMailboxSettingsStore(settingsPath, passwordPath, new FakeProtector());
            store.Save(new NextcloudMailboxSettings(true, "https://cloud.example/nextcloud/", "ä user"));
            store.SetApplicationPassword("app-secret-cleartext");
            var loaded = store.Load();
            TestAssert.That(loaded is { DavActive: true, MailboxActive: true, ServerBase: "https://cloud.example/nextcloud", User: "ä user" } && store.HasApplicationPassword,
                "Separate Nextcloud-Einstellungen wurden nicht korrekt gespeichert.");
            File.WriteAllText(settingsPath, "{\"aktiv\":true,\"server\":\"https://cloud.example/nextcloud\",\"benutzer\":\"ä user\"}");
            loaded = store.Load();
            TestAssert.That(loaded is { DavActive: true, MailboxActive: true },
                "Die bisherige Nextcloud-Aktivierung wurde nicht auf DAV und Briefkasten migriert.");
            TestAssert.That(!File.ReadAllText(settingsPath).Contains("secret", StringComparison.Ordinal) &&
                !File.ReadAllText(passwordPath).Contains("app-secret-cleartext", StringComparison.Ordinal),
                "Das Anwendungskennwort wurde im Klartext abgelegt.");
            TestAssert.That(typeof(NextcloudMailboxSettingsStore).GetMethods(
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
                .Where(method => method.Name.Contains("Password", StringComparison.Ordinal))
                .All(method => method.ReturnType == typeof(void) || method.ReturnType == typeof(bool)),
                "Die Settings-API gibt das Anwendungskennwort zurück.");
            using (var timedMailbox = new NextcloudMailbox(store))
            {
                var mailboxHttp = (HttpClient)typeof(NextcloudMailbox).GetField("http",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(timedMailbox)!;
                TestAssert.That(mailboxHttp.Timeout == TimeSpan.FromSeconds(12),
                    "Der native WebDAV-Client besitzt kein kurzes Zeitlimit.");
            }
            using (var handler = NextcloudMailbox.CreateHandler())
                TestAssert.That(!handler.AllowAutoRedirect,
                    "Der native WebDAV-Client würde Basic Auth über eine Weiterleitung tragen.");
            var context = store.Context();
            store.Save(new NextcloudMailboxSettings(true, "https://other.example", "other"));
            store.SetApplicationPassword("other-password");
            TestAssert.That(context.Settings.ServerBase == "https://cloud.example/nextcloud" &&
                Encoding.UTF8.GetString(Convert.FromBase64String(context.Authorization.Parameter!)) == "ä user:app-secret-cleartext",
                "WebDAV-Ziel und Basic Auth stammen nicht aus demselben atomaren Einstellungssnapshot.");
            store.Save(new NextcloudMailboxSettings(true, "https://cloud.example/nextcloud", "ä user"));
            store.SetApplicationPassword("app-secret-cleartext");

            var unsafeStore = new NextcloudMailboxSettingsStore(settingsPath, Path.Combine(root, "unsafe"), new PlaintextProtector());
            TestAssert.Throws<CryptographicException>(() => unsafeStore.SetApplicationPassword("must-not-write"),
                "Ein Protector mit Klartextausgabe wurde akzeptiert.");
            TestAssert.That(!File.Exists(Path.Combine(root, "unsafe")), "Klartext wurde trotz fehlgeschlagenem Schutz geschrieben.");
            var settingsBeforeFailure = File.ReadAllText(settingsPath);
            var passwordBeforeFailure = File.ReadAllText(passwordPath);
            var failingStore = new NextcloudMailboxSettingsStore(settingsPath, passwordPath, new ThrowingProtector());
            TestAssert.Throws<CryptographicException>(() => failingStore.SaveConfiguration(
                new NextcloudMailboxSettings(true, "https://changed.example", "changed"), "new-password", false),
                "Fehlgeschlagener Briefkasten-Commit wurde angenommen.");
            TestAssert.That(File.ReadAllText(settingsPath) == settingsBeforeFailure &&
                File.ReadAllText(passwordPath) == passwordBeforeFailure,
                "Fehlgeschlagener Briefkasten-Commit veränderte die vorherige Konfiguration.");
            store.ClearApplicationPassword();
            TestAssert.That(!store.HasApplicationPassword, "Das geschützte Kennwort konnte nicht entfernt werden.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static void TestAuthenticatedDocuments()
    {
        var id = Enumerable.Range(0, 16).Select(value => (byte)value).ToArray();
        var key = Enumerable.Range(1, 32).Select(value => (byte)value).ToArray();
        TestAssert.That(MagnolienbaumCoordinator.DirectUnavailable(new HttpRequestException("offline")) &&
            MagnolienbaumCoordinator.DirectUnavailable(new TaskCanceledException("timeout")) &&
            !MagnolienbaumCoordinator.DirectUnavailable(new HttpRequestException("antwort", null, HttpStatusCode.ServiceUnavailable)) &&
            !MagnolienbaumCoordinator.DirectUnavailable(new InvalidDataException("Antwort zu groß")),
            "HTTP-Antworten wurden fälschlich als Nichterreichbarkeit für den Briefkasten eingestuft.");
        var document = NextcloudMailboxProtocol.CreateMessage(id, "alpha", "beta", new JsonObject { ["text"] = "Blüte" }, key);
        TestAssert.That(NextcloudMailboxProtocol.ReadSender(document, id, "beta") == "alpha" &&
            NextcloudMailboxProtocol.ReadMessage(document, id, "alpha", "beta", key)["text"]?.GetValue<string>() == "Blüte",
            "Authentisierte WebDAV-Nachricht ließ sich nicht lesen.");
        var tampered = JsonNode.Parse(document)!.AsObject();
        tampered["inhalt"]!["text"] = "verändert";
        TestAssert.Throws<CryptographicException>(() => NextcloudMailboxProtocol.ReadMessage(
            MagnolienbaumCrypto.Canonical(tampered), id, "alpha", "beta", key), "Manipulierte WebDAV-Nachricht wurde akzeptiert.");

        var receipt = NextcloudMailboxProtocol.CreateReceipt(id, "beta", "alpha", key);
        NextcloudMailboxProtocol.VerifyReceipt(receipt, id, "beta", "alpha", key);
        var changedReceipt = JsonNode.Parse(receipt)!.AsObject();
        changedReceipt["transportId"] = MagnolienbaumCrypto.Base64Url(RandomNumberGenerator.GetBytes(16));
        TestAssert.Throws<CryptographicException>(() => NextcloudMailboxProtocol.VerifyReceipt(
            MagnolienbaumCrypto.Canonical(changedReceipt), id, "beta", "alpha", key), "Manipulierte WebDAV-Quittung wurde akzeptiert.");
        TestAssert.That(NextcloudMailboxProtocol.StableId(id) == "000102030405060708090a0b0c0d0e0f",
            "Der stabile WebDAV-Dateiname ist nicht deterministisch.");
    }

    private static async Task TestWebDavAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-webdav-http-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var store = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"), Path.Combine(root, "password.dpapi"), new FakeProtector());
            store.Save(new NextcloudMailboxSettings(true, "https://cloud.example/nc", "a b@example.test"));
            store.SetApplicationPassword("application-password");
            var requests = new List<RequestRecord>();
            var putCount = 0;
            var id = Enumerable.Range(0, 16).Select(value => (byte)value).ToArray();
            var listedId = Enumerable.Range(16, 16).Select(value => (byte)value).ToArray();
            using var http = new HttpClient(new RecordingHandler(async request =>
            {
                requests.Add(new RequestRecord(request.Method.Method, request.RequestUri!.AbsoluteUri,
                    request.Headers.Authorization?.ToString() ?? "",
                    request.Headers.TryGetValues("If-None-Match", out var match) ? match.Single() : "",
                    request.Headers.TryGetValues("Depth", out var depth) ? depth.Single() : "",
                    request.Content is null ? "" : await request.Content.ReadAsStringAsync()));
                if (request.Method.Method == "MKCOL") return new HttpResponseMessage(HttpStatusCode.Created);
                if (request.Method == HttpMethod.Put) return new HttpResponseMessage(++putCount == 1 ? HttpStatusCode.Created : HttpStatusCode.PreconditionFailed);
                if (request.Method.Method == "PROPFIND") return Xml(HttpStatusCode.MultiStatus,
                    $"<?xml version=\"1.0\"?><d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>/nc/remote.php/dav/files/user/Magnolie/baum-1/nachrichten/beta/</d:href><d:status>HTTP/1.1 200 OK</d:status></d:response><d:response><d:href>/nc/remote.php/dav/files/user/Magnolie/baum-1/nachrichten/beta/{NextcloudMailboxProtocol.StableId(listedId)}.json</d:href><d:status>HTTP/1.1 200 OK</d:status></d:response><d:response><d:href>/nc/remote.php/dav/files/user/Magnolie/baum-1/nachrichten/beta/not-a-message.txt</d:href><d:status>HTTP/1.1 200 OK</d:status></d:response></d:multistatus>");
                return new HttpResponseMessage(HttpStatusCode.NotFound);
            }));
            using var mailbox = new NextcloudMailbox(store, http);
            await mailbox.EnsureHierarchyAsync("beta", CancellationToken.None);
            var first = await mailbox.UploadAsync(id, "alpha", "beta", new JsonObject { ["x"] = 1 }, new byte[32], CancellationToken.None);
            var duplicate = await mailbox.UploadAsync(id, "alpha", "beta", new JsonObject { ["x"] = 1 }, new byte[32], CancellationToken.None);
            var listed = await mailbox.ListIncomingAsync("beta", CancellationToken.None);

            var expectedBasic = "Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes("a b@example.test:application-password"));
            TestAssert.That(requests.All(value => value.Authorization == expectedBasic), "Basic Auth wurde nicht ausschließlich/konsistent im Header gesetzt.");
            TestAssert.That(requests.All(value => !value.Uri.Contains("application-password", StringComparison.Ordinal)) &&
                requests[0].Uri == "https://cloud.example/nc/remote.php/dav/files/a%20b%40example.test/Magnolie/" &&
                requests[5].Uri.EndsWith("/Magnolie/baum-1/quittungen/beta/", StringComparison.Ordinal),
                "WebDAV-Basis, Benutzer-Escaping oder MKCOL-Hierarchie ist falsch.");
            TestAssert.That(first && !duplicate && requests.Where(value => value.Method == "PUT").All(value => value.IfNoneMatch == "*"),
                "PUT If-None-Match oder idempotentes HTTP 412 ist falsch.");
            TestAssert.That(requests.Single(value => value.Method == "PROPFIND").Depth == "1" && listed.Count == 1 && listed[0].SequenceEqual(listedId),
                "PROPFIND Depth 1 wurde nicht sicher ausgewertet.");

            using var hostileHttp = new HttpClient(new RecordingHandler(_ => Task.FromResult(Xml(HttpStatusCode.MultiStatus,
                "<?xml version=\"1.0\"?><!DOCTYPE x [<!ENTITY e SYSTEM \"file:///etc/passwd\">]><d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>&e;</d:href></d:response></d:multistatus>"))));
            using var hostileMailbox = new NextcloudMailbox(store, hostileHttp);
            await TestAssert.ThrowsAsync<System.Xml.XmlException>(() => hostileMailbox.ListIncomingAsync("beta", CancellationToken.None),
                "PROPFIND erlaubte eine DTD bzw. einen externen Resolver.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static async Task TestWebDavFailuresAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-webdav-errors-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var store = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"),
                Path.Combine(root, "password.dpapi"), new FakeProtector());
            store.Save(new NextcloudMailboxSettings(true, "https://cloud.example", "user"));
            store.SetApplicationPassword("application-password");

            foreach (var status in new[] { HttpStatusCode.Unauthorized, HttpStatusCode.Forbidden,
                         HttpStatusCode.NotFound, HttpStatusCode.InsufficientStorage, HttpStatusCode.MovedPermanently,
                         HttpStatusCode.Redirect })
            {
                var calls = 0;
                using var http = new HttpClient(new RecordingHandler(_ =>
                { calls++; return Task.FromResult(new HttpResponseMessage(status)); }));
                using var mailbox = new NextcloudMailbox(store, http);
                try
                {
                    await mailbox.EnsureHierarchyAsync("beta", CancellationToken.None);
                    throw new InvalidOperationException($"WebDAV-Status {(int)status} wurde akzeptiert.");
                }
                catch (HttpRequestException error)
                {
                    TestAssert.That(error.StatusCode == status && calls == 1,
                        $"WebDAV-Status {(int)status} wurde nicht unverändert und ohne Redirect gemeldet.");
                }
            }

            using (var existingHttp = new HttpClient(new RecordingHandler(_ =>
                       Task.FromResult(new HttpResponseMessage(HttpStatusCode.MethodNotAllowed)))))
            using (var existingMailbox = new NextcloudMailbox(store, existingHttp))
                await existingMailbox.EnsureHierarchyAsync("beta", CancellationToken.None);

            using (var timeoutHttp = new HttpClient(new RecordingHandler(_ =>
                       Task.FromException<HttpResponseMessage>(new TaskCanceledException("Frist abgelaufen")))))
            using (var timeoutMailbox = new NextcloudMailbox(store, timeoutHttp))
                await TestAssert.ThrowsAsync<TaskCanceledException>(() =>
                    timeoutMailbox.EnsureHierarchyAsync("beta", CancellationToken.None),
                    "Eine WebDAV-Zeitüberschreitung wurde verschluckt.");

            using (var brokenHttp = new HttpClient(new RecordingHandler(_ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                   { Content = new BrokenContent() }))))
            using (var brokenMailbox = new NextcloudMailbox(store, brokenHttp))
                await TestAssert.ThrowsAsync<HttpRequestException>(() => brokenMailbox.GetIncomingDocumentAsync("beta", new byte[16], CancellationToken.None),
                    "Ein Übertragungsabbruch mitten im WebDAV-Dokument wurde akzeptiert.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static async Task TestDamagedSettingsStatusAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-webdav-status-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root);
            File.WriteAllText(paths.BaumMailboxSettings, "{kaputt");
            JsonObject? status = null;
            using var coordinator = new MagnolienbaumCoordinator(paths, (_, payload) =>
            {
                status = JsonSerializer.SerializeToNode(payload)!.AsObject();
                return Task.CompletedTask;
            });
            await coordinator.ReportMailboxStatusAsync();
            TestAssert.That(status?["zustand"]?.GetValue<string>() == "unvollstaendig" &&
                !string.IsNullOrWhiteSpace(status?["fehler"]?.GetValue<string>()),
                "Eine beschädigte Briefkastenkonfiguration verhinderte die Statusantwort.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static void TestReservedCounterRecovery()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-webdav-counter-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var paths = new WindowsPaths(root);
            var store = new MagnolienbaumStore(paths);
            var state = store.LoadOrCreate();
            state["partner"]!.AsArray().Add(new JsonObject { ["kennung"] = "beta", ["name"] = "Beta",
                ["oeffentlich"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)), ["zaehler_raus"] = 2 });
            store.SaveState(state);
            store.SaveOutbox(new JsonArray(new JsonObject { ["an"] = "beta", ["briefZaehler"] = 7,
                ["briefUmschlag"] = new JsonObject { ["magnolie"] = "baum-1" } }));
            using var coordinator = new MagnolienbaumCoordinator(paths, (_, _) => Task.CompletedTask);
            var recovered = store.LoadOrCreate()["partner"]!.AsArray()[0]!["zaehler_raus"]!.GetValue<long>();
            TestAssert.That(recovered == 7,
                "Ein vor dem Absturz reservierter Briefkastenzähler wurde beim Neustart nicht rekonstruiert.");
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static HttpResponseMessage Xml(HttpStatusCode status, string xml) => new(status)
    {
        Content = new StringContent(xml, Encoding.UTF8, "application/xml")
    };

    private sealed record RequestRecord(string Method, string Uri, string Authorization, string IfNoneMatch, string Depth, string Body);

    private sealed class RecordingHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request);
    }

    private sealed class BrokenContent : HttpContent
    {
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            Task.FromException(new IOException("Verbindung während der Übertragung abgebrochen."));
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
    }

    private sealed class FakeProtector : ISecretProtector
    {
        public byte[] Protect(byte[] plain) => new byte[] { 0x44, 0x50, 0x41, 0x50, 0x49 }.Concat(plain.Reverse()).ToArray();
        public byte[] Unprotect(byte[] protectedData)
        {
            if (!protectedData.AsSpan(0, 5).SequenceEqual(new byte[] { 0x44, 0x50, 0x41, 0x50, 0x49 })) throw new CryptographicException();
            return protectedData[5..].Reverse().ToArray();
        }
    }

    private sealed class PlaintextProtector : ISecretProtector
    {
        public byte[] Protect(byte[] plain) => plain.ToArray();
        public byte[] Unprotect(byte[] protectedData) => protectedData.ToArray();
    }

    private sealed class ThrowingProtector : ISecretProtector
    {
        public byte[] Protect(byte[] plain) => throw new CryptographicException("simulierter Schutzfehler");
        public byte[] Unprotect(byte[] protectedData) => throw new CryptographicException();
    }
}
