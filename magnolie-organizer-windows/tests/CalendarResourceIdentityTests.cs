using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarResourceIdentityTests
{
    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> call) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) => call(request); }
    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] value) => value;
        public byte[] Unprotect(byte[] value) => value;
    }
    internal static async Task RunAsync()
    {
        foreach (var anniversary in new[] { false, true })
            foreach (var binding in new[] { "old-href", "href-only", "missing" })
                await RecoverAsync(anniversary, binding);
    }
    private static async Task RecoverAsync(bool anniversary, string binding)
    {
        const string uid = "identity-fixture";
        var original = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:" + uid +
            "\r\nDTSTAMP:20260801T090000Z\r\nDTSTART;VALUE=DATE:20260803\r\nSUMMARY:Synthetic\r\n" +
            (anniversary ? "X-MAGNOLIE-TYPE-ID:birthday\r\nX-MAGNOLIE-DATE:--08-03\r\nRRULE:FREQ=YEARLY\r\n" : "") +
            "END:VEVENT\r\nEND:VCALENDAR\r\n";
        var calendar = original; var etag = "\"v1\""; var writes = 0;
        var source = new NextcloudDavSource("thunderbird-calendar:managed:fixture:calendar", "Synthetic", "calendar",
            new Uri("https://calendar.example.invalid/events/"), false);
        var href = new Uri(source.Href, uid + ".ics");
        using var http = new HttpClient(new Handler(async request => {
            if (request.Method.Method == "REPORT") return new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new StringContent(
                "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/events/" + uid +
                ".ics</d:href><d:propstat><d:prop><d:getetag>" + System.Security.SecurityElement.Escape(etag) +
                "</d:getetag><c:calendar-data>" + System.Security.SecurityElement.Escape(calendar) +
                "</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>", Encoding.UTF8, "application/xml") };
            writes++;
            // The provider already owns this UID. A second resource with that
            // UID is forbidden, just like the observed Google calendar response.
            if (request.RequestUri != href || request.Headers.IfNoneMatch.Count > 0)
                return new HttpResponseMessage(HttpStatusCode.Forbidden);
            TestAssert.That(request.Method == HttpMethod.Put && request.Headers.IfMatch.Single().Tag == etag,
                "Rebinding lost the existing resource ETag.");
            calendar = await request.Content!.ReadAsStringAsync(); etag = "\"v" + (writes + 1) + "\"";
            return new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue(etag) } };
        }));
        var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false, "https://calendar.example.invalid", "fixture") { AccountType = "generic-dav" }, null);
        using var client = new NextcloudDavClient(context, http,
            new NextcloudSyncJournal(Path.Combine(Path.GetTempPath(), "calendar-identity-" + Guid.NewGuid().ToString("N")), new Protector()), new string('a', 64));
        var engine = new NextcloudCalendarSync(client);
        var parsed = ExchangeCodec.ParseIcs(original);
        var local = (anniversary ? parsed.Jahrestage : parsed.Termine).Single()!.DeepClone().AsObject();
        local["id"] = "local-stable-id";
        if (binding != "missing") {
            var oldId = binding == "href-only" ? href.AbsoluteUri : NextcloudCalendarSync.RemoteKey(new Uri(source.Href, "previous-address.ics"), local);
            NextcloudCalendarSync.SetSource(local, source.Uid, oldId, etag);
        }
        async Task<NextcloudCalendarResult> Sync(JsonObject value) => await engine.SyncAsync(source,
            anniversary ? [] : new JsonArray(value.DeepClone()), anniversary ? new JsonArray(value.DeepClone()) : [], [], 1, false, default);
        JsonObject Single(NextcloudCalendarResult value) => (anniversary ? value.Jahrestage : value.Termine).Single()!.AsObject();
        var result = await Sync(local);
        var rebound = Single(result);
        TestAssert.That(writes == 0 && result.Conflicts == 0 && ContactFields.Text(rebound, "id") == "local-stable-id" &&
            ContactFields.Text(ContactFields.Source(rebound, source.Uid)!, "id") == NextcloudCalendarSync.RemoteKey(href, rebound),
            "An existing identical UID was created again, duplicated or lost its local identity.");
        result = await Sync(JsonNode.Parse(rebound.ToJsonString())!.AsObject());
        TestAssert.That(writes == 0 && result.Conflicts == 0, "Recovered calendar identity did not survive reopening.");
        var edited = Single(result).DeepClone().AsObject(); edited[anniversary ? "name" : "titel"] = "Local changed";
        result = await Sync(edited);
        TestAssert.That(writes == 1 && result.Conflicts == 0, "A real local edit did not update its recovered existing resource exactly once.");
        var competing = Single(result).DeepClone().AsObject(); competing[anniversary ? "name" : "titel"] = "Competing local";
        calendar = calendar.Replace("SUMMARY:Local changed", "SUMMARY:Remote changed", StringComparison.Ordinal); etag = "\"remote\"";
        result = await Sync(competing);
        TestAssert.That(writes == 1 && result.Conflicts == 1 && (anniversary ? result.Jahrestage : result.Termine).Count == 2,
            "A genuine concurrent calendar edit was hidden by UID rebinding.");
    }
}
