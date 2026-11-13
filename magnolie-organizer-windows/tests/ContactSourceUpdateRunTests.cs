using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ContactSourceUpdateRunTests
{
    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] plain) => plain.Select(value => (byte)(value ^ 0x5a)).ToArray();
        public byte[] Unprotect(byte[] encrypted) => Protect(encrypted);
    }
    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handle) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) => handle(request);
    }
    private sealed class Source : IDisposable
    {
        private readonly string root = Path.Combine(Path.GetTempPath(), "magnolie-contact-source-" + Guid.NewGuid().ToString("N"));
        private readonly HttpClient http;
        internal readonly NextcloudDavClient Client;
        internal readonly string WireUid;
        internal NextcloudDavSource Catalog = null!;
        internal string Wire, ETag = "\"v1\"";
        internal bool? Permission = true;
        internal bool FailWrite, BadReadback, RequireSaved, Saved;
        internal int Writes, Reads;
        private readonly string origin;
        internal Source(string name, string accountType, JsonObject data)
        {
            Directory.CreateDirectory(root); WireUid = "provider-original-" + name; origin = "https://" + name + ".invalid";
            var card = data.DeepClone().AsObject(); card["uid"] = WireUid;
            using var input = JsonDocument.Parse(new JsonArray(card).ToJsonString());
            Wire = ExchangeCodec.WriteVCard(input.RootElement).Text;
            var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"), Path.Combine(root, "secret.dat"), new Protector());
            settings.SaveConfiguration(new NextcloudMailboxSettings(true, false, origin + "/nc", "synthetic") { AccountType = accountType }, "synthetic-only", false);
            http = new HttpClient(new Handler(Handle)); Client = new NextcloudDavClient(settings, http);
        }
        private static HttpResponseMessage Xml(string text) => new(HttpStatusCode.MultiStatus) { Content = new StringContent(text) };
        private async Task<HttpResponseMessage> Handle(HttpRequestMessage request)
        {
            if (request.Method.Method == "PROPFIND")
            {
                if (!request.Headers.TryGetValues("Depth", out var depths) || depths.Single() != "1")
                    return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/</d:href><d:propstat><d:prop><c:addressbook-home-set><d:href>/nc/books/</d:href></c:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                var privilege = Permission is null ? "" : "<d:current-user-privilege-set><d:privilege><d:" + (Permission == true ? "write-content" : "read") + "/></d:privilege></d:current-user-privilege-set>";
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/original/</d:href><d:propstat><d:prop><d:displayname>Original</d:displayname><d:resourcetype><c:addressbook/></d:resourcetype>" + privilege + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
            }
            TestAssert.That(!RequireSaved || Saved, "Provider IO preceded the original durable SaveACK");
            if (request.Method.Method == "REPORT")
            {
                Reads++;
                return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/books/original/person.vcf</d:href><d:propstat><d:prop><d:getetag>" + SecurityElement.Escape(ETag) + "</d:getetag><c:address-data>" + SecurityElement.Escape(Wire) + "</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
            }
            TestAssert.That(request.Method == HttpMethod.Put && request.RequestUri!.AbsoluteUri == origin + "/nc/books/original/person.vcf" &&
                request.Headers.IfMatch.Single().ToString() == ETag, "Original provider resource/revision lost or create/delete attempted");
            if (FailWrite) throw new HttpRequestException("controlled provider failure");
            var text = await request.Content!.ReadAsStringAsync();
            TestAssert.That(text.Contains("UID:" + WireUid + "\r\n", StringComparison.Ordinal) && !text.Contains("UID:canonical-person", StringComparison.Ordinal),
                "Provider's original vCard UID was overwritten by canonical UID");
            Wire = BadReadback ? text.Replace("Canonical note", "Independent change", StringComparison.Ordinal) : text;
            Writes++; ETag = "\"write-" + Writes + "\"";
            return new(HttpStatusCode.NoContent) { Headers = { ETag = new EntityTagHeaderValue(ETag) } };
        }
        internal async Task<RemoteContact> OriginalAsync()
        {
            Catalog = (await Client.ListSourcesAsync(default, calendars: false)).AddressBooks.Single();
            return (await new NextcloudCardDavRemote(Client, Catalog).ReadAsync(default)).Single();
        }
        internal ContactSourceAdmission Admit() => new(Catalog.Uid, new NextcloudCardDavRemote(Client, Catalog), Catalog.CanUpdate, async token => {
            var current = (await Client.ListSourcesAsync(token, calendars: false)).AddressBooks.SingleOrDefault(source => source.Uid == Catalog.Uid);
            if (current?.CanUpdate != true || current.Href != Catalog.Href) throw new UnauthorizedAccessException("Original source permission withdrawn");
        });
        public void Dispose()
        { Client.Dispose(); http.Dispose(); Directory.Delete(root, recursive: true); }
    }
    internal static async Task RunAsync()
    {
        foreach (var mode in new[] { "success", "failure", "readback", "readonly", "unknown", "revoked", "conflict", "ambiguous", "save-failed", "book-changed" })
        {
            var original = new JsonObject { ["id"] = "local", ["uid"] = "canonical-person", ["sync"] = true,
                ["vorname"] = "Alex", ["nachname"] = "Fixture", ["notiz"] = "Original", ["geaendert"] = 1000L };
            using var first = new Source("first", "generic-dav", original);
            using var second = new Source("second", "nextcloud", original);
            var a = await first.OriginalAsync(); var b = await second.OriginalAsync();
            var local = original.DeepClone().AsObject();
            ContactFields.SetSource(local, first.Catalog.Uid, a, remoteBaseline: true);
            ContactFields.SetSource(local, second.Catalog.Uid, b, remoteBaseline: true);
            local["notiz"] = "Canonical note"; local["geaendert"] = 2000L;
            var unrelated = new JsonObject { ["id"] = "unbound", ["uid"] = "unbound", ["sync"] = true, ["notiz"] = "Do not export" };
            var contacts = new JsonArray(local, unrelated); var before = contacts.ToJsonString();
            if (mode == "ambiguous")
            {
                var duplicate = local.DeepClone().AsObject(); duplicate["id"] = "duplicate"; duplicate["uid"] = "other-canonical";
                duplicate["syncQuellen"]!.AsObject().Remove(second.Catalog.Uid); contacts.Add(duplicate);
                before = contacts.ToJsonString();
            }
            var admission = first.Admit();
            if (mode is "readonly" or "unknown") admission = admission with { CanUpdate = mode == "readonly" ? false : null };
            first.FailWrite = mode == "failure"; first.BadReadback = mode == "readback";
            if (mode == "revoked") first.Permission = false;
            if (mode == "conflict") { first.Wire = first.Wire.Replace("NOTE:Original", "NOTE:Concurrent source edit", StringComparison.Ordinal); first.ETag = "\"concurrent\""; }
            first.RequireSaved = second.RequireSaved = true;
            var saved = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var aReads = first.Reads; var bReads = second.Reads;
            var current = true;
            var running = ContactSourceUpdateRun.RunAsync(contacts, [admission, second.Admit()], () => saved.Task,
                () => { if (!current) throw new InvalidOperationException("Original book changed"); });
            TestAssert.That(!running.IsCompleted && first.Reads == aReads && second.Reads == bReads && first.Writes + second.Writes == 0,
                "Two-source planner bypassed SaveACK before provider IO");
            if (mode is "save-failed" or "book-changed")
            {
                if (mode == "save-failed") saved.TrySetException(new IOException("Controlled durable save failure"));
                else { current = false; saved.TrySetResult(); }
                try { await running; throw new Exception("Unconfirmed/stale original save reached provider execution"); }
                catch (Exception error) when (mode == "save-failed" && error is IOException || mode == "book-changed" && error is InvalidOperationException) { }
                TestAssert.That(first.Writes + second.Writes == 0 && first.Reads == aReads && second.Reads == bReads && contacts.ToJsonString() == before,
                    "Missing SaveACK/changed original book performed provider IO or changed contacts");
                continue;
            }
            first.Saved = second.Saved = true; saved.TrySetResult();
            var result = await running;
            TestAssert.That(contacts.ToJsonString() == before && result.Contacts.Count == contacts.Count &&
                result.Contacts[0]!["uid"]!.GetValue<string>() == "canonical-person" && JsonNode.DeepEquals(result.Contacts[1], unrelated),
                "Source run changed input, canonical identity or unbound contact");
            TestAssert.That(second.Writes == 1 && result.Sources[second.Catalog.Uid].Errors == 0 && second.Wire.Contains("NOTE:Canonical note", StringComparison.Ordinal),
                "Independent authorized second provider was skipped after first-provider hold/conflict/failure");
            if (mode == "success") TestAssert.That(first.Writes == 1 && result.Sources[first.Catalog.Uid].Errors == 0, "Both bound providers did not receive canonical update");
            else if (mode == "conflict") TestAssert.That(first.Writes == 0 && result.Sources[first.Catalog.Uid].Conflicts == 1,
                "Concurrent source value was overwritten");
            else TestAssert.That(result.Sources[first.Catalog.Uid].Errors > 0 &&
                JsonNode.DeepEquals(result.Contacts[0]!["syncQuellen"]![first.Catalog.Uid], local["syncQuellen"]![first.Catalog.Uid]),
                "Failed/unknown/read-only source acquired a successful baseline");
            if (mode is "readonly" or "unknown" or "revoked") TestAssert.That(first.Writes == 0 && first.Reads == aReads, "Unadmitted source received content IO");
            if (mode == "success")
            {
                var writes = first.Writes + second.Writes;
                await ContactSourceUpdateRun.RunAsync(result.Contacts, [first.Admit(), second.Admit()], () => Task.CompletedTask, () => { });
                TestAssert.That(first.Writes + second.Writes == writes, "Already acknowledged sources were rewritten on repeat");
            }
        }
    }
}
