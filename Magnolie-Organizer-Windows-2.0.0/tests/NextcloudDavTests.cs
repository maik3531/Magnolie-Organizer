using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class NextcloudDavTests
{
    internal static async Task RunAsync()
    {
        var calendar = "nextcloud-calendar:" + new string('a', 64);
        var addressBook = "nextcloud-addressbook:" + new string('b', 64);
        TestAssert.That(NextcloudDavSelection.IsSupported("", [calendar]),
            "Reiner Nextcloud-Kalendersync mit leerer Adressbuch-UID wird abgewiesen.");
        TestAssert.That(NextcloudDavSelection.IsSupported(addressBook, []),
            "Reiner Nextcloud-Kontaktsync wird abgewiesen.");
        TestAssert.That(NextcloudDavSelection.IsSupported(addressBook, [calendar]),
            "Kombinierter Nextcloud-Kalender-/Kontaktsync wird abgewiesen.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-dav-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"), Path.Combine(root, "password.dpapi"), new Protector());
            settings.Save(new NextcloudMailboxSettings(true, "https://cloud.example/nc", "a user")); settings.SetApplicationPassword("app-secret");
            var requests = new List<Request>();
            using var http = new HttpClient(new Handler(async request =>
            {
                requests.Add(new Request(request.Method.Method, request.RequestUri!.AbsoluteUri,
                    request.Headers.Authorization?.ToString() ?? "", request.Headers.TryGetValues("Depth", out var depth) ? depth.Single() : "",
                    request.Headers.TryGetValues("If-Match", out var match) ? match.Single() : "", request.Content is null ? "" : await request.Content.ReadAsStringAsync()));
                var path = request.RequestUri.AbsolutePath;
                if (path.EndsWith("/.well-known/caldav", StringComparison.Ordinal)) return Xml("<d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>/nc/.well-known/caldav</d:href><d:propstat><d:prop><d:current-user-principal><d:href>/nc/principals/users/a%20user/</d:href></d:current-user-principal></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                if (path.EndsWith("/principals/users/a%20user/", StringComparison.Ordinal)) return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/principals/users/a%20user/</d:href><d:propstat><d:prop><c:calendar-home-set><d:href>/nc/calendars/a%20user/</d:href></c:calendar-home-set><card:addressbook-home-set><d:href>/nc/addressbooks/a%20user/</d:href></card:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                if (request.Method.Method == "PROPFIND" && path.EndsWith("/calendars/a%20user/", StringComparison.Ordinal)) return Xml(Collections("calendar", "urn:ietf:params:xml:ns:caldav", "/nc/calendars/a%20user/work/", "Arbeit"));
                if (request.Method.Method == "PROPFIND" && path.EndsWith("/addressbooks/a%20user/", StringComparison.Ordinal)) return Xml(Collections("addressbook", "urn:ietf:params:xml:ns:carddav", "/nc/addressbooks/a%20user/contacts/", "Kontakte"));
                if (request.Method.Method == "REPORT" && path.EndsWith("/work/", StringComparison.Ordinal)) return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/calendars/a%20user/work/series.ics</d:href><d:propstat><d:prop><d:getetag>&quot;c1&quot;</d:getetag><c:calendar-data>BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:series\r\nDTSTART;VALUE=DATE:20260817\r\nSUMMARY:Serie\r\nRRULE:FREQ=MONTHLY;BYDAY=-1MO\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                if (request.Method.Method == "REPORT" && path.EndsWith("/contacts/", StringComparison.Ordinal)) return Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/addressbooks/a%20user/contacts/a.vcf</d:href><d:propstat><d:prop><d:getetag>&quot;v1&quot;</d:getetag><card:address-data>BEGIN:VCARD\r\nVERSION:3.0\r\nUID:u1\r\nN:Probe;Änne;;;\r\nFN:Änne Probe\r\nTEL;TYPE=CELL:+49123\r\nEMAIL:a@example.test\r\nEND:VCARD\r\n</card:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
                return new HttpResponseMessage(HttpStatusCode.Created) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"v2\"") } };
            }));
            using var client = new NextcloudDavClient(settings, http);
            var sources = await client.ListSourcesAsync(CancellationToken.None);
            TestAssert.That(sources.Calendars.Count == 1 && sources.AddressBooks.Count == 1 && sources.Calendars[0].Uid.StartsWith("nextcloud-calendar:", StringComparison.Ordinal) && sources.AddressBooks[0].Uid.StartsWith("nextcloud-addressbook:", StringComparison.Ordinal), "DAV-Discovery lieferte keine stabilen Quellen-IDs.");
            var contacts = await new NextcloudCardDavRemote(client, sources.AddressBooks[0]).ReadAsync(CancellationToken.None);
            var calendarObjects = await client.ReadCalendarAsync(sources.Calendars[0], CancellationToken.None);
            TestAssert.That(contacts.Count == 1 && contacts[0].ETag == "\"v1\"" && contacts[0].Data["mobil"]?.GetValue<string>() == "+49123", "CardDAV REPORT verlor ETag oder Mehrfachwerte.");
            TestAssert.That(calendarObjects.Count == 1 && calendarObjects[0].ETag == "\"c1\"" && calendarObjects[0].Text.Contains("BYDAY=-1MO", StringComparison.Ordinal), "CalDAV REPORT verlor ETag oder ordinale Monatsregel.");
            var changed = await new NextcloudCardDavRemote(client, sources.AddressBooks[0]).UpdateAsync(contacts[0], "u1", contacts[0].Data, CancellationToken.None);
            TestAssert.That(changed.ETag == "\"v2\"" && requests.Last().IfMatch == "\"v1\"" && requests.All(value => value.Authorization == Basic("a user", "app-secret")) && requests.All(value => !value.Uri.Contains("app-secret", StringComparison.Ordinal)), "CardDAV-Update verlor If-Match oder sichere Basic Auth.");
            TestAssert.That(requests.Where(value => value.Method == "PROPFIND").Any(value => value.Depth == "1") && requests.Any(value => value.Method == "REPORT" && value.Depth == "1"), "DAV-Quellenliste/REPORT verwendete keine begrenzte Tiefe.");
            var unprotected = contacts[0] with { ETag = "" };
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => new NextcloudCardDavRemote(client, sources.AddressBooks[0]).UpdateAsync(
                unprotected, "u1", unprotected.Data, CancellationToken.None), "CardDAV-Update ohne ETag wurde ungeschützt gesendet.");
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => new NextcloudCardDavRemote(client, sources.AddressBooks[0]).DeleteAsync(
                unprotected, "u1", CancellationToken.None), "CardDAV-Löschung ohne ETag wurde ungeschützt gesendet.");

            await TestHostileServers(settings);
            TestRoundtrips();
            TestSyncJournal(root);
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static async Task TestHostileServers(NextcloudMailboxSettingsStore settings)
    {
        var calls = 0;
        using (var http = new HttpClient(new Handler(_ =>
               {
                   calls++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Redirect) { Headers = { Location = new Uri("https://attacker.invalid/steal") } });
               })))
        using (var client = new NextcloudDavClient(settings, http))
            await TestAssert.ThrowsAsync<InvalidDataException>(() => client.ListSourcesAsync(CancellationToken.None), "DAV-Discovery folgte einem fremden Origin.");
        TestAssert.That(calls == 1, "Fremder Redirect löste weitere authentisierte Aufrufe aus.");

        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml("<?xml version=\"1.0\"?><!DOCTYPE x [<!ENTITY e SYSTEM \"file:///etc/passwd\">]><d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>&e;</d:href></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
            await TestAssert.ThrowsAsync<System.Xml.XmlException>(() => client.ListSourcesAsync(CancellationToken.None), "DAV-Discovery erlaubte DTD/Entities.");

        foreach (var status in new[] { HttpStatusCode.Unauthorized, HttpStatusCode.Forbidden, HttpStatusCode.InsufficientStorage })
        {
            using var http = new HttpClient(new Handler(_ => Task.FromResult(new HttpResponseMessage(status)))); using var client = new NextcloudDavClient(settings, http);
            await TestAssert.ThrowsAsync<HttpRequestException>(() => client.ListSourcesAsync(CancellationToken.None), $"DAV-Status {(int)status} wurde verschluckt.");
        }

        using (var http = new HttpClient(new Handler(_ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new ByteArrayContent(new byte[16 * 1024 * 1024 + 1]) }))))
        using (var client = new NextcloudDavClient(settings, http))
            await TestAssert.ThrowsAsync<InvalidDataException>(() => client.ListSourcesAsync(CancellationToken.None), "Übergroße DAV-Antwort wurde akzeptiert.");

        using (var http = new HttpClient(new CancellableHandler()))
        using (var client = new NextcloudDavClient(settings, http))
        using (var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(20)))
            await TestAssert.ThrowsAsync<TaskCanceledException>(() => client.ListSourcesAsync(cancellation.Token), "DAV-Abbruch wurde nicht an den Aufrufer gemeldet.");

        var localAttachmentCalls = 0;
        using (var http = new HttpClient(new Handler(_ =>
               {
                   localAttachmentCalls++;
                   return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Created));
               })))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:local", "local", "calendar", new Uri("https://cloud.example/nc/book/"));
            const string localIcs = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:local\r\nATTACH;X-REF=\"urn:test\":file:///C:/Users/Mia/geheim.pdf\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => client.CreateAsync(calendar, "local", ".ics", "text/calendar", localIcs, CancellationToken.None),
                "CalDAV-PUT akzeptierte einen lokalen ATTACH-Pfad.");
            TestAssert.That(localAttachmentCalls == 0 && localIcs.Contains("file:///C:/Users/Mia/geheim.pdf", StringComparison.Ordinal),
                "Die lokale ATTACH-Sperre griff erst nach einem Netzwerkaufruf oder veränderte Rohdaten.");
        }

        foreach (var responseXml in new[]
        {
            "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/book/a.ics</d:href><d:propstat><d:prop><c:calendar-data>BEGIN:VCALENDAR&#13;&#10;END:VCALENDAR</c:calendar-data></d:prop><d:status>HTTP/1.1 507 Insufficient Storage</d:status></d:propstat></d:response></d:multistatus>",
            "<d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>/nc/book/a.ics</d:href></d:response></d:multistatus>"
        })
        {
            using var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(responseXml))));
            using var client = new NextcloudDavClient(settings, http);
            var calendar = new NextcloudDavSource("nextcloud-calendar:x", "x", "calendar", new Uri("https://cloud.example/nc/book/"));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => client.ReadCalendarAsync(calendar, CancellationToken.None),
                "Partieller oder statusloser HTTP 207 wurde als vollständiger REPORT akzeptiert.");
        }

        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(
                   "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/book/a.ics</d:href><d:propstat><d:prop><d:getetag>&quot;x&quot;</d:getetag><c:calendar-data>unlesbar</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:x", "x", "calendar", new Uri("https://cloud.example/nc/book/"));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new NextcloudCalendarSync(client).SyncAsync(calendar,
                new JsonArray(), new JsonArray(), new JsonArray(), 0, true, CancellationToken.None),
                "Unlesbare ICS-Payload wurde als leerer Kalender interpretiert.");
        }

        const string mixedCards = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:u1\r\nFN:Valid\r\nEND:VCARD\r\nBEGIN:VCARD\r\nVERSION:3.0\r\nUID:bad\r\nEND:VCARD\r\n";
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(
                   $"<d:multistatus xmlns:d=\"DAV:\" xmlns:card=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>/nc/book/mixed.vcf</d:href><d:propstat><d:prop><d:getetag>&quot;x&quot;</d:getetag><card:address-data>{mixedCards}</card:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var book = new NextcloudDavSource("nextcloud-addressbook:mixed", "mixed", "addressbook", new Uri("https://cloud.example/nc/book/"));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new NextcloudCardDavRemote(client, book).ReadAsync(CancellationToken.None),
                "Gemischte gültige/ungültige vCard-Payload wurde teilweise übernommen.");
        }

        var deletes = 0;
        const string mixedCalendar = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:valid\r\nDTSTART:20260817T100000Z\r\nSUMMARY:Valid\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:bad\r\nSUMMARY:Invalid\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        using (var http = new HttpClient(new Handler(request =>
               {
                   if (request.Method == HttpMethod.Delete) deletes++;
                   return Task.FromResult(Xml($"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/calendar/mixed.ics</d:href><d:propstat><d:prop><d:getetag>&quot;x&quot;</d:getetag><c:calendar-data>{mixedCalendar}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
               })))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:mixed", "mixed", "calendar", new Uri("https://cloud.example/nc/calendar/"));
            var tombstones = new JsonArray(new JsonObject { ["uid"] = "valid", ["syncQuellen"] = new JsonObject
                { [calendar.Uid] = new JsonObject { ["id"] = "https://cloud.example/nc/calendar/mixed.ics" } } });
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new NextcloudCalendarSync(client).SyncAsync(calendar,
                new JsonArray(), new JsonArray(), tombstones, 1, false, CancellationToken.None),
                "Gemischte gültige/ungültige ICS-Payload wurde teilweise übernommen.");
            TestAssert.That(deletes == 0, "Aus einer unvollständig geparsten DAV-Payload wurde eine Löschung abgeleitet.");
        }

        var source = new NextcloudDavSource("nextcloud-addressbook:x", "x", "addressbook", new Uri("https://cloud.example/nc/book/"));
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.PreconditionFailed)))))
        using (var client = new NextcloudDavClient(settings, http))
            await TestAssert.ThrowsAsync<InvalidOperationException>(() => client.UpdateAsync(new Uri("https://cloud.example/nc/book/a.vcf"), "\"old\"", "text/vcard", "BEGIN:VCARD\r\nEND:VCARD\r\n", CancellationToken.None), "HTTP 412 wurde nicht als ETag-Konflikt gemeldet.");
        var resumeCalls = 0;
        const string resumedCard = "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:u1\r\nFN:Probe\r\nEND:VCARD\r\n";
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(++resumeCalls == 1
                   ? new HttpResponseMessage(HttpStatusCode.PreconditionFailed)
                   : new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(resumedCard),
                       Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"resumed\"") } }))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var resumed = await client.CreateAsync(source, "u1", ".vcf", "text/vcard", resumedCard, CancellationToken.None);
            TestAssert.That(resumed.ETag == "\"resumed\"" && resumeCalls == 2,
                "Ein bereits erfolgreicher deterministischer PUT blieb nach HTTP 412 dauerhaft blockiert.");
        }
        _ = source;
    }

    private static void TestRoundtrips()
    {
        const string ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:series\r\nDTSTART;TZID=Europe/Berlin:20260817T100000\r\nDTEND;TZID=Europe/Berlin:20260817T110000\r\nSUMMARY:Serie\r\nRRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1\r\nEXDATE;TZID=Europe/Berlin:20260928T100000\r\nRECURRENCE-ID;TZID=Europe/Berlin:20261031T100000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var parsed = ExchangeCodec.ParseIcs(ics); using var calendar = JsonDocument.Parse(parsed.Termine.ToJsonString()); var written = ExchangeCodec.WriteIcs("ics-termine", calendar.RootElement).Text;
        TestAssert.That(written.Contains("RRULE:FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1", StringComparison.Ordinal) && written.Contains("EXDATE;TZID=Europe/Berlin:20260928T100000", StringComparison.Ordinal) && written.Contains("RECURRENCE-ID;TZID=Europe/Berlin:20261031T100000", StringComparison.Ordinal), "CalDAV-ICS-Roundtrip verlor RRULE/EXDATE/RECURRENCE-ID.");

        var seriesResource = File.ReadAllText(Path.Combine("tests", "fixtures", "caldav-series-resource.ics"));
        var series = ExchangeCodec.ParseIcs(seriesResource);
        var master = series.Termine.OfType<JsonObject>().Single(value =>
            !value["icsRoundtrip"]!.AsArray().Any(line => line!.GetValue<string>().StartsWith("RECURRENCE-ID", StringComparison.Ordinal)));
        master["titel"] = "Lokal geänderte Serienrunde";
        var merged = ExchangeCodec.ReplaceCalendarEvent(seriesResource, master);
        var moved = series.Termine.OfType<JsonObject>().Single(value => !ReferenceEquals(value, master));
        moved["titel"] = "Lokal verschobene Instanz";
        merged = ExchangeCodec.ReplaceCalendarEvent(merged, moved);
        TestAssert.That(merged.StartsWith("BEGIN:VCALENDAR", StringComparison.Ordinal) &&
            merged.Count("BEGIN:VEVENT") == 2 && merged.Contains("SUMMARY:Lokal geänderte Serienrunde", StringComparison.Ordinal) &&
            merged.Contains("SUMMARY:Lokal verschobene Instanz", StringComparison.Ordinal) &&
            merged.Contains("RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000", StringComparison.Ordinal) &&
            merged.Contains("EXDATE;TZID=Europe/Berlin:20261026T100000", StringComparison.Ordinal) &&
            merged.Contains("BEGIN:VTIMEZONE", StringComparison.Ordinal) && merged.Count("BEGIN:VALARM") == 2 &&
            merged.Count("DESCRIPTION:Reminder") == 1 &&
            merged.Contains("X-EXAMPLE-META;X-TOKEN=alpha:opaque-value", StringComparison.Ordinal),
            "CalDAV-Serien-PUT zerlegte die Ressource oder verlor Zeitzone, Override, Ausnahme, Alarm oder unbekannte Parameter.");

        using (var seriesDocument = JsonDocument.Parse(series.Termine.ToJsonString()))
        {
            var seriesRoundtrip = ExchangeCodec.WriteIcs("ics-termine", seriesDocument.RootElement).Text;
            TestAssert.That(seriesRoundtrip.Contains("X-EXAMPLE-META;X-TOKEN=alpha:opaque-value", StringComparison.Ordinal) &&
                seriesRoundtrip.Contains("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC", StringComparison.Ordinal),
                "ICS-Roundtrip verlor unbekannte unterstützbare Eigenschaften oder Parameter.");
        }

        var photo = Convert.ToBase64String(new byte[] { 0xff, 0xd8, 0xff, 0xd9 });
        var vcf = $"BEGIN:VCARD\r\nVERSION:3.0\r\nN:Probe;Änne;;;\r\nFN:Änne Probe\r\nTEL;TYPE=HOME:1\r\nTEL;TYPE=CELL:2\r\nEMAIL:a@example.test\r\nEMAIL:b@example.test\r\nPHOTO;ENCODING=b;TYPE=JPEG:{photo}\r\nEND:VCARD\r\n";
        var contact = ExchangeCodec.ParseVCard(vcf); using var cards = JsonDocument.Parse(contact.Kontakte.ToJsonString()); var roundtrip = ExchangeCodec.WriteVCard(cards.RootElement).Text;
        TestAssert.That(roundtrip.Count(value => value == '\n') >= 8 && roundtrip.Contains(photo, StringComparison.Ordinal) && roundtrip.Contains("b@example.test", StringComparison.Ordinal), "CardDAV-vCard-Roundtrip verlor Foto oder Mehrfachwerte.");

        var providers = ExchangeCodec.ParseVCard(File.ReadAllText(Path.Combine("tests", "fixtures", "provider-vcards.vcf")));
        using var providerDocument = JsonDocument.Parse(providers.Kontakte.ToJsonString());
        var providerRoundtrip = ExchangeCodec.WriteVCard(providerDocument.RootElement).Text;
        TestAssert.That(providers.Kontakte.Select(item => item?["uid"]?.ToString()).SequenceEqual(
                new[] { "thunderbird-original-uid", "apple-original-uid", "nextcloud-original-uid" }) &&
            providerRoundtrip.Contains("X-MOZILLA-HTML:TRUE", StringComparison.Ordinal) &&
            providerRoundtrip.Contains("X-ABRELATEDNAMES;TYPE=friend:Grace Hopper", StringComparison.Ordinal) &&
            providerRoundtrip.Contains("KIND:individual", StringComparison.Ordinal) &&
            providerRoundtrip.Contains("IMPP;PREF=1:xmpp:nora@example.test", StringComparison.Ordinal) &&
            providerRoundtrip.Contains(";PREF=1:ada@example.test", StringComparison.Ordinal) &&
            providerRoundtrip.Contains(";X-SERVICE-TYPE=signal:0203 1", StringComparison.Ordinal),
            "vCard 2.1/3.0/4.0 verlor Anbieterfelder, Parameter oder Original-UIDs.");
    }

    private static int Count(this string text, string value) =>
        Regex.Matches(text, Regex.Escape(value), RegexOptions.CultureInvariant).Count;

    private static void TestSyncJournal(string root)
    {
        using var commitContract = BridgeDispatcherContract.Parse("{\"cmd\":\"sync_commit\",\"transactionId\":\"" + new string('a', 64) + "\"}");
        using var syncContract = BridgeDispatcherContract.Parse("{\"cmd\":\"sync\",\"transactionId\":\"" + new string('b', 64) + "\",\"wahl\":{},\"daten\":{}}");
        var path = Path.Combine(root, "sync-journal.dpapi");
        var journal = new NextcloudSyncJournal(path, new Protector());
        var id = new string('c', 64);
        var payload = new JsonObject { ["kontakte"] = new JsonArray(new JsonObject
            { ["uid"] = "u1", ["syncQuellen"] = new JsonObject { ["nextcloud-addressbook:x"] = new JsonObject { ["id"] = "remote" } } }) };
        journal.Save(id, "contacts", payload);
        var raw = File.ReadAllText(path);
        TestAssert.That(!raw.Contains("remote", StringComparison.Ordinal) && journal.Load() is { } loaded &&
            loaded.Id == id && loaded.Phase == "contacts" && loaded.Payload["kontakte"]?[0]?["uid"]?.GetValue<string>() == "u1",
            "Das atomare DPAPI-Synchronisationsjournal verlor den Provider-Zwischenstand oder blieb im Klartext.");
        journal.Delete();
        TestAssert.That(!File.Exists(path), "Das abgeschlossene Synchronisationsjournal blieb liegen.");

        var phases = new[] { "contacts:nextcloud-addressbook:x", "calendar:nextcloud-calendar:y" };
        foreach (var phase in phases)
        {
            journal.Save(id, phase, payload);
            var restarted = new NextcloudSyncJournal(path, new Protector());
            TestAssert.That(restarted.LoadFor(id, phases) is { Phase: var loadedPhase } && loadedPhase == phase,
                $"Crash-Zwischenstand {phase} wurde beim Neustart nicht phasengenau fortgesetzt.");
            TestAssert.That(restarted.Commit(id) && restarted.LoadFor(id, phases) is null,
                $"Bestätigter Zwischenstand {phase} wurde beim Folgesync mit gleicher Epoch restauriert.");
        }
        journal.Save(id, "complete", payload);
        TestAssert.That(journal.LoadFor(id, phases) is null && !File.Exists(path),
            "Eine nicht konkrete oder bereits abgeschlossene Phase wurde als Resume verwendet.");
        journal.Save(id, phases[0], payload);
        var followingTransaction = new string('d', 64);
        TestAssert.That(journal.LoadFor(followingTransaction, phases) is null && !File.Exists(path),
            "Ein erfolgreicher Folgesync mit gleicher Sync-Epoch restaurierte Daten einer alten Transaktion.");
        TestAssert.Throws<InvalidDataException>(() => journal.Save(id, phases[0], new JsonObject
            { ["einstellungen"] = new JsonObject { ["anwendungskennwort"] = "secret" } }),
            "Zugangsdaten wurden im Synchronisationsjournal akzeptiert.");
    }

    private static string Collections(string type, string ns, string href, string name) => $"<d:multistatus xmlns:d=\"DAV:\" xmlns:x=\"{ns}\"><d:response><d:href>{href}</d:href><d:propstat><d:prop><d:displayname>{name}</d:displayname><d:resourcetype><d:collection/><x:{type}/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>";
    private static HttpResponseMessage Xml(string xml) => new(HttpStatusCode.MultiStatus) { Content = new StringContent(xml, Encoding.UTF8, "application/xml") };
    private static string Basic(string user, string password) => "Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes(user + ":" + password));
    private sealed record Request(string Method, string Uri, string Authorization, string Depth, string IfMatch, string Body);
    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request); }
    private sealed class CancellableHandler : HttpMessageHandler { protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); return new HttpResponseMessage(HttpStatusCode.OK); } }
    private sealed class Protector : ISecretProtector { public byte[] Protect(byte[] plain) => plain.Select(value => (byte)(value ^ 0x5a)).Prepend((byte)1).ToArray(); public byte[] Unprotect(byte[] encrypted) => encrypted.Skip(1).Select(value => (byte)(value ^ 0x5a)).ToArray(); }
}
