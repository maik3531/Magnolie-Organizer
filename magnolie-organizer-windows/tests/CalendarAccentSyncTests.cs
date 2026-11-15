using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarAccentSyncTests
{
    private sealed class Protector : ISecretProtector
    {
        public byte[] Protect(byte[] value) => value.Prepend((byte)39).ToArray();
        public byte[] Unprotect(byte[] value) => value.Skip(1).ToArray();
    }

    private sealed class Fixture(bool tasks) : HttpMessageHandler
    {
        internal string Calendar = tasks ?
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:synthetic-task\r\nSUMMARY:Synthetic task\r\nEND:VTODO\r\nEND:VCALENDAR\r\n" :
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:synthetic-event\r\nDTSTART;VALUE=DATE:20260813\r\nSUMMARY:Synthetic event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        internal string ETag = "\"v1\"";
        internal int Writes;
        internal bool Reject;
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method.Method == "REPORT")
                return new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new StringContent(
                    "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/events/synthetic.ics</d:href><d:propstat><d:prop><d:getetag>" +
                    System.Security.SecurityElement.Escape(ETag) + "</d:getetag><c:calendar-data>" + System.Security.SecurityElement.Escape(Calendar) +
                    "</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>", Encoding.UTF8, "application/xml") };
            TestAssert.That(request.Method == HttpMethod.Put && request.Headers.IfMatch.Single().Tag == ETag,
                "Colour edit attempted creation/deletion or lost the exact conditional ETag");
            Writes++;
            if (Reject) return new HttpResponseMessage(HttpStatusCode.PreconditionFailed);
            Calendar = await request.Content!.ReadAsStringAsync(cancellationToken); ETag = "\"saved-" + Writes + "\"";
            return new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue(ETag) } };
        }
    }

    internal static async Task RunAsync()
    {
        foreach (var tasks in new[] { false, true })
        {
            await CheckAsync(tasks, legacy: false, rejected: false);
            await CheckAsync(tasks, legacy: true, rejected: false);
            await CheckAsync(tasks, legacy: true, rejected: false, remoteChanged: true);
            await CheckAsync(tasks, legacy: false, rejected: true);
            ParameterizedProperty(tasks);
        }
    }

    private static async Task CheckAsync(bool tasks, bool legacy, bool rejected, bool remoteChanged = false)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-accent-fixture-" + Guid.NewGuid().ToString("N"));
        try
        {
            using var fixture = new Fixture(tasks);
            using var http = new HttpClient(fixture);
            var source = new NextcloudDavSource("generic-dav-calendar:synthetic-accent", "Synthetic", "calendar", new Uri("https://calendar.example.invalid/events/"));
            var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false, "https://calendar.example.invalid", "synthetic") { AccountType = "generic-dav" }, null);
            using var client = new NextcloudDavClient(context, http, new NextcloudSyncJournal(root, new Protector()), new string('b', 64));
            async Task<(JsonArray Items, int Conflicts)> Run(JsonArray values, bool first = false)
            {
                if (tasks)
                {
                    var result = await new NextcloudTaskSync(client).SyncAsync(source, values, [], 1, first, default);
                    return (result.Tasks, result.Conflicts);
                }
                var calendar = await new NextcloudCalendarSync(client).SyncAsync(source, values, [], [], 1, first, default);
                return (calendar.Termine, calendar.Conflicts);
            }
            var (items, _) = await Run([], first: true);
            TestAssert.That(items.Count == 1 && fixture.Writes == 0, "First import wrote to the provider");
            var item = items[0]!.AsObject();
            var baseline = ContactFields.Source(item, source.Uid)!;
            var before = baseline.DeepClone();
            var fields = tasks ? (string[])typeof(NextcloudTaskSync).GetField("Fields", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!.GetValue(null)! : NextcloudCalendarSync.Fields;
            var oldHash = SyncBaseline.Hash(item, fields);
            TestAssert.That(SyncBaseline.Hash(new JsonObject(), fields) == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
                "Published windows-1 empty-record vector changed");
            if (legacy) { baseline["inhaltFormat"] = "windows-1"; baseline["inhaltSha256"] = oldHash; }
            if (remoteChanged) fixture.ETag = "\"v2\"";
            foreach (var colour in new[] { "#112233", "#abcdef", "" })
            {
                item = items[0]!.AsObject(); item["akzentFarbe"] = colour;
                if (legacy)
                    TestAssert.That(SyncBaseline.Hash(item, fields) == oldHash,
                        "Shipped windows-1 vectors were silently redefined to cover colour");
                fixture.Reject = rejected;
                var writes = fixture.Writes;
                if (rejected)
                {
                    var rejectedWrite = false;
                    try { await Run(items); }
                    catch (Exception) { rejectedWrite = true; }
                    TestAssert.That(rejectedWrite && fixture.Writes == writes + 1 && JsonNode.DeepEquals(before, ContactFields.Source(item, source.Uid)),
                        "A rejected colour PUT advanced the caller's baseline or was skipped");
                    break;
                }
                var result = await Run(items); items = result.Items;
                if (legacy)
                {
                    TestAssert.That(result.Conflicts == 1 && items.Count == 2 && fixture.Writes == 0 &&
                        items.OfType<JsonObject>().Any(value => ContactFields.Text(value, "akzentFarbe") == colour),
                        "Legacy baseline hid an unrepresented local colour or overwrote its original provider");
                    break;
                }
                TestAssert.That(fixture.Writes == writes + 1 && result.Conflicts == 0 && items.Count == 1,
                    "Colour-only set/change/remove did not make exactly one conditional PUT");
                var parsed = ExchangeCodec.ParseIcs(fixture.Calendar);
                var remote = (tasks ? parsed.Aufgaben : parsed.Termine)[0]!.AsObject();
                TestAssert.That(ContactFields.Text(remote, "akzentFarbe") == colour, "Provider colour differs after native export/reimport");
                TestAssert.That(ContactFields.Text(ContactFields.Source(items[0]!.AsObject(), source.Uid)!, "inhaltFormat") == CalendarSyncBaseline.Format(tasks),
                    "Confirmed colour write was mislabeled as the old baseline format");
                for (var repeat = 0; repeat < 3; repeat++)
                {
                    (items, _) = await Run(items);
                    TestAssert.That(fixture.Writes == writes + 1 && items.Count == 1, "Own native readback caused a repeated colour PUT");
                }
            }
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static void ParameterizedProperty(bool tasks)
    {
        using var fixture = new Fixture(tasks);
        var end = tasks ? "END:VTODO" : "END:VEVENT";
        const string raw = "X-MAGNOLIE-ACCENT-COLOR;X-SYNTHETIC=keep:#112233";
        var parsed = ExchangeCodec.ParseIcs(fixture.Calendar.Replace(end, raw + "\r\n" + end, StringComparison.Ordinal));
        var item = (tasks ? parsed.Aufgaben : parsed.Termine)[0]!.AsObject();
        ExchangeExportResult Export() => ExchangeCodec.WriteIcs(tasks ? "ics-aufgaben" : "ics-termine", JsonSerializer.SerializeToElement(new JsonArray(item.DeepClone())));
        TestAssert.That(Export().Text.Contains(raw, StringComparison.Ordinal), "Unchanged colour export dropped unknown property parameters");
        foreach (var colour in new[] { "#abcdef", "" })
        {
            item["akzentFarbe"] = colour;
            TestAssert.Throws<InvalidOperationException>(() => Export(), "Protected colour edit was silently exported or skipped");
        }
    }
}
