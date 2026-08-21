using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class WindowsContactGraphTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), $"magnolie-contacts-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var store = new WindowsContactStore(root);
            var contact = new JsonObject { ["vorname"] = "Änne", ["nachname"] = "Beispiel", ["email"] = "a@example.test" };
            await TestAssert.ThrowsAsync<IOException>(() => store.UpdateAsync(
                    new RemoteContact("../fremd.contact", "", 0, contact, true), "uid", contact, CancellationToken.None),
                "Windows Contacts akzeptierte Pfadtraversal als Remote-ID.");

            var oversized = Path.Combine(root, "gross.contact");
            await using (var stream = File.Create(oversized)) stream.SetLength(2 * 1024 * 1024 + 1);
            TestAssert.That((await store.ReadAsync(CancellationToken.None)).Count == 0,
                "Windows Contacts las eine übergroße .contact-Datei.");

            var requests = new List<(HttpMethod Method, string Uri, string Authorization, string IfMatch, string Body)>();
            var handler = new RecordingHttpHandler(async request =>
            {
                var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync();
                requests.Add((request.Method, request.RequestUri!.ToString(), request.Headers.Authorization?.ToString() ?? "",
                    request.Headers.TryGetValues("If-Match", out var values) ? values.Single() : "", body));
                return request.Method == HttpMethod.Post
                    ? Json(HttpStatusCode.Created, "{\"id\":\"created/id\",\"givenName\":\"Änne\",\"lastModifiedDateTime\":\"2026-08-11T10:00:00Z\"}")
                    : new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"next\"") } };
            });
            using var http = new HttpClient(handler);
            var graph = new GraphApiClient(http, "access-test");
            var made = await graph.CreateAsync("uid", contact, CancellationToken.None);
            await graph.UpdateAsync(made with { ETag = "\"old\"" }, "uid", contact, CancellationToken.None);
            await graph.DeleteAsync(made with { ETag = "\"next\"" }, "uid", CancellationToken.None);
            TestAssert.That(requests.Count == 3 && requests.All(item => item.Authorization == "Bearer access-test") &&
                requests[1].Method == HttpMethod.Patch && requests[1].IfMatch == "\"old\"" &&
                requests[2].Method == HttpMethod.Delete && requests[2].Uri.EndsWith("created%2Fid", StringComparison.Ordinal),
                "Graph Create/Update/Delete übertrug Authentisierung, ETag oder escaped ID nicht korrekt.");
            TestAssert.That(JsonNode.Parse(requests[0].Body)?["givenName"]?.GetValue<string>() == "Änne" && made.Id == "created/id",
                "Graph verlor Unicode-Kontaktdaten beim Erstellen.");

            var fake = new FakeContactRemote();
            var old = new JsonObject { ["uid"] = "old", ["geaendert"] = 1,
                ["syncQuellen"] = new JsonObject { ["fake"] = new JsonObject { ["id"] = "missing", ["eigen"] = true } } };
            var tombstone = old.DeepClone().AsObject();
            var additiveResult = await new ContactSyncEngine().SyncAsync("fake", new JsonArray(old),
                new JsonArray(tombstone), 100, fake, additiveOnly: true);
            TestAssert.That(additiveResult.Contacts.Count == 1 && additiveResult.Tombstones.Count == 1 && fake.Deletes == 0,
                "Erster Sync nach Restore war nicht additiv und löschungsfrei.");
            var partial = new FailingContactRemote();
            var changedLocal = old.DeepClone().AsObject(); changedLocal["geaendert"] = 200L;
            changedLocal["syncQuellen"]!["fake"]!["id"] = "remote";
            changedLocal["syncQuellen"]!["fake"]!["etag"] = "\"old\"";
            var deleteCandidate = old.DeepClone().AsObject(); deleteCandidate["syncQuellen"]!["fake"]!["id"] = "delete";
            var partialResult = await new ContactSyncEngine().SyncAsync("fake", new JsonArray(changedLocal), new JsonArray(deleteCandidate), 100, partial);
            TestAssert.That(partialResult.Counts.Errors == 1 && partial.Deletes == 0,
                "Ein partiell fehlgeschlagener Kontaktlauf führte eine Remote-Löschung aus.");

            using var badNextHttp = new HttpClient(new RecordingHttpHandler(_ => Task.FromResult(Json(HttpStatusCode.OK,
                "{\"value\":[],\"@odata.nextLink\":\"https://attacker.invalid/steal\"}"))));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new GraphApiClient(badNextHttp, "secret").ReadAsync(CancellationToken.None),
                "Graph folgte einem fremden OAuth-Paginationsziel.");
            var pageCalls = 0;
            using var endlessGraphHttp = new HttpClient(new RecordingHttpHandler(_ =>
            {
                pageCalls++;
                return Task.FromResult(Json(HttpStatusCode.OK,
                    "{\"value\":[],\"@odata.nextLink\":\"https://graph.microsoft.com/v1.0/me/contacts?page=next\"}"));
            }));
            await TestAssert.ThrowsAsync<InvalidDataException>(() =>
                    new GraphApiClient(endlessGraphHttp, "secret").ReadAsync(CancellationToken.None),
                "Graph behandelte einen nach 100 Seiten abgeschnittenen Kontaktbestand als vollständig.");
            TestAssert.That(pageCalls == 100, "Die Graph-Seitengrenze wurde nicht deterministisch eingehalten.");

            using var oauthHttp = new HttpClient(new RecordingHttpHandler(async request =>
            {
                var form = await request.Content!.ReadAsStringAsync();
                TestAssert.That(form.Contains("refresh_token=refresh-test", StringComparison.Ordinal) &&
                    form.Contains("Contacts.ReadWrite", StringComparison.Ordinal), "OAuth-Refresh sendete nicht den vereinbarten Scope.");
                return Json(HttpStatusCode.OK, "{\"access_token\":\"access-new\",\"refresh_token\":\"refresh-new\",\"expires_in\":3600}");
            }));
            var token = await new MicrosoftOAuthClient(oauthHttp).RefreshAsync(Guid.Empty.ToString(), "refresh-test", CancellationToken.None);
            TestAssert.That(token.AccessToken == "access-new" && token.RefreshToken == "refresh-new", "OAuth-Refresh-Antwort wurde falsch gelesen.");
            try { OAuthResponseParser.DeviceCode("{\"device_code\":\"x\",\"user_code\":\"y\",\"verification_uri\":\"http://unsafe.test\"}");
                throw new InvalidOperationException("OAuth akzeptierte eine unverschlüsselte Verifikationsadresse."); }
            catch (InvalidDataException) { }
        }
        finally
        {
            try { Directory.Delete(root, true); } catch (Exception) { }
        }
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string value) => new(status)
    {
        Content = new StringContent(value, Encoding.UTF8, "application/json")
    };

    private sealed class RecordingHttpHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request);
    }

    private sealed class FakeContactRemote : IContactRemote
    {
        internal int Deletes { get; private set; }
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>(Array.Empty<RemoteContact>());
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => Task.FromResult(new RemoteContact(Guid.NewGuid().ToString(), "", 1, contact, true));
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken) => Task.FromResult(remote);
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) { Deletes++; return Task.CompletedTask; }
    }

    private sealed class FailingContactRemote : IContactRemote
    {
        internal int Deletes { get; private set; }
        public Task<IReadOnlyList<RemoteContact>> ReadAsync(CancellationToken cancellationToken) => Task.FromResult<IReadOnlyList<RemoteContact>>([
            new RemoteContact("remote", "\"old\"", 1, new JsonObject { ["vorname"] = "Alt" }, true),
            new RemoteContact("delete", "\"delete\"", 1, new JsonObject { ["vorname"] = "Löschen" }, true)]);
        public Task<RemoteContact> CreateAsync(string uid, JsonObject contact, CancellationToken cancellationToken) => throw new IOException("partial");
        public Task<RemoteContact> UpdateAsync(RemoteContact remote, string uid, JsonObject contact, CancellationToken cancellationToken) => throw new IOException("partial");
        public Task DeleteAsync(RemoteContact remote, string uid, CancellationToken cancellationToken) { Deletes++; return Task.CompletedTask; }
    }
}
