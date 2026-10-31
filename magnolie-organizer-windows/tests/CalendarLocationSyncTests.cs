using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarLocationSyncTests
{
    private const string Initial = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:location-fixture\r\n" +
        "DTSTAMP:20260801T090000Z\r\nDTSTART;VALUE=DATE:20260803\r\nDTEND;VALUE=DATE:20260816\r\n" +
        "STATUS:CONFIRMED\r\nSUMMARY:Fixture\r\nLOCATION;LANGUAGE=en:Zone\\, Hall\\nLevel\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
    private const string Location = "Zone, Hall\nLevel";

    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> call) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation) => call(request); }
    private sealed class FixtureProtector : ISecretProtector
    {
        public byte[] Protect(byte[] value) => value.Prepend((byte)31).ToArray();
        public byte[] Unprotect(byte[] value) => value.Skip(1).ToArray();
    }

    internal static async Task RunAsync()
    {
        var parsed = ExchangeCodec.ParseIcs(Initial).Termine.Single()!.AsObject();
        TestAssert.That(ContactFields.Text(parsed, "ort") == Location, "Native ICS parsing does not project LOCATION like the frontend.");
        foreach (var hashed in new[] { false, true }) await ConvergesAsync(hashed);
        var cancelled = ExchangeCodec.ParseIcs(Initial.Replace("STATUS:CONFIRMED", "STATUS:CANCELLED", StringComparison.Ordinal)).Termine;
        using var document = JsonDocument.Parse(cancelled.ToJsonString());
        TestAssert.That(ExchangeCodec.WriteIcs("ics-termine", document.RootElement).Text.Contains("STATUS:CANCELLED\r\n", StringComparison.Ordinal),
            "Exporting an imported cancelled event silently drops its status.");
    }

    private static async Task ConvergesAsync(bool hashed)
    {
        var calendar = Initial; var etag = "\"v1\""; var writes = 0; var allowWrites = false;
        var source = new NextcloudDavSource("thunderbird-calendar:managed:fixture:calendar", "Fixture", "calendar", new Uri("https://calendar.example.invalid/events/"), false);
        var href = new Uri(source.Href, "location-fixture.ics");
        using var http = new HttpClient(new Handler(async request =>
        {
            if (request.Method.Method == "REPORT")
                return new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new StringContent(
                    "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/events/location-fixture.ics</d:href><d:propstat><d:prop><d:getetag>" +
                    System.Security.SecurityElement.Escape(etag) + "</d:getetag><c:calendar-data>" + System.Security.SecurityElement.Escape(calendar) +
                    "</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>", Encoding.UTF8, "application/xml") };
            writes++;
            if (!allowWrites) return new HttpResponseMessage(HttpStatusCode.Forbidden);
            TestAssert.That(request.Method == HttpMethod.Put && request.Headers.IfMatch.Single().Tag == etag,
                "A real location change lost its provider ETag.");
            calendar = await request.Content!.ReadAsStringAsync(); etag = "\"v" + (writes + 1) + "\"";
            return new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue(etag) } };
        }));
        var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false, "https://calendar.example.invalid", "fixture") { AccountType = "generic-dav" }, null);
        using var client = new NextcloudDavClient(context, http,
            new NextcloudSyncJournal(Path.Combine(Path.GetTempPath(), "calendar-location-fixture-" + Guid.NewGuid().ToString("N")), new FixtureProtector()), new string('a', 64));
        var engine = new NextcloudCalendarSync(client);
        JsonObject Local()
        {
            var legacy = ExchangeCodec.ParseIcs(Initial).Termine.Single()!.DeepClone().AsObject(); legacy.Remove("ort");
            var mapping = new JsonObject { ["id"] = NextcloudCalendarSync.RemoteKey(href, legacy), ["etag"] = "\"v1\"" };
            if (hashed) { mapping["inhaltFormat"] = "windows-1"; mapping["inhaltSha256"] = SyncBaseline.Hash(legacy, NextcloudCalendarSync.Fields); }
            legacy["id"] = "local"; legacy["ort"] = Location;
            legacy["syncQuellen"] = new JsonObject { [source.Uid] = mapping };
            return legacy;
        }
        var result = await engine.SyncAsync(source, new JsonArray(Local()), [], [], 1, false, default);
        TestAssert.That(writes == 0 && result.Conflicts == 0 && result.Termine.Count == 1, "A frontend-only LOCATION projection wrote an unchanged event.");
        var reopened = JsonNode.Parse(result.Termine.ToJsonString())!.AsArray();
        result = await engine.SyncAsync(source, reopened, [], [], 1, false, default);
        TestAssert.That(writes == 0 && result.Conflicts == 0, "A reopened projected calendar keeps rewriting the same record.");
        if (hashed)
        {
            calendar = Initial.Replace("SUMMARY:Fixture", "SUMMARY:Remote changed", StringComparison.Ordinal); etag = "\"v9\"";
            result = await engine.SyncAsync(source, new JsonArray(Local()), [], [], 1, false, default);
            TestAssert.That(result.Conflicts == 0 && ContactFields.Text(result.Termine.Single()!.AsObject(), "titel") == "Remote changed" && writes == 0,
                "An old location-less baseline became a false competing edit after a real remote update.");
            calendar = Initial; etag = "\"v1\"";
            var competing = Local(); competing["ort"] = "User room";
            calendar = Initial.Replace("SUMMARY:Fixture", "SUMMARY:Remote changed", StringComparison.Ordinal); etag = "\"v9\"";
            var conflict = await engine.SyncAsync(source, new JsonArray(competing), [], [], 1, false, default);
            TestAssert.That(conflict.Conflicts == 1 && conflict.Termine.Count == 2 && writes == 0, "A genuine local location edit was hidden by baseline migration.");
            calendar = Initial; etag = "\"v1\"";
        }
        var edited = result.Termine.Single()!.DeepClone().AsObject();
        if (hashed) edited = Local();
        edited["ort"] = "New room"; allowWrites = true;
        result = await engine.SyncAsync(source, new JsonArray(edited), [], [], 1, false, default);
        TestAssert.That(writes == 1 && ContactFields.Text(ExchangeCodec.ParseIcs(calendar).Termine.Single()!.AsObject(), "ort") == "New room" &&
            calendar.Contains("STATUS:CONFIRMED\r\n", StringComparison.Ordinal), "A real edit lost its new location or existing confirmed status.");
        var clear = result.Termine.Single()!.DeepClone().AsObject(); clear["ort"] = "";
        await engine.SyncAsync(source, new JsonArray(clear), [], [], 1, false, default);
        TestAssert.That(writes == 2 && !calendar.Contains("LOCATION", StringComparison.Ordinal), "Clearing a location resurrected its old opaque ICS line.");
    }
}
