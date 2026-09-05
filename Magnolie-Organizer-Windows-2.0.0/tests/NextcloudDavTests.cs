using System.Net;
using System.Security.Cryptography;
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
        var partition = NextcloudDavSelection.SplitCalendarItems(new JsonArray
        {
            new JsonObject { ["id"] = "local" },
            new JsonObject { ["id"] = "work", ["syncKalenderUid"] = calendar },
            new JsonObject { ["id"] = "private", ["syncKalenderUid"] = "other" }
        }, calendar, true);
        TestAssert.That(partition.Selected.Count == 2 && partition.Remaining.Count == 1 &&
            partition.Selected.OfType<JsonObject>().All(item =>
                item["syncKalenderUid"]?.GetValue<string>() == calendar) &&
            partition.Remaining[0]?["id"]?.GetValue<string>() == "private",
            "Kalenderpartition vermischt Einträge verschiedener CalDAV-Kalender.");
        var secondCalendar = "nextcloud-calendar:" + new string('c', 64);
        var tombstonePartition = NextcloudDavSelection.SplitCalendarTombstones(new JsonArray(new JsonObject
        {
            ["syncKalenderUid"] = calendar,
            ["syncQuellen"] = new JsonObject { [calendar] = new JsonObject(), [secondCalendar] = new JsonObject() }
        }), secondCalendar, false);
        TestAssert.That(tombstonePartition.Selected.Count == 1 && tombstonePartition.Remaining.Count == 0 &&
            tombstonePartition.Selected[0]?["syncKalenderUid"]?.GetValue<string>() == secondCalendar,
            "Kalenderpartition übersprang eine sekundäre CalDAV-Löschzuordnung.");
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
                if (path.EndsWith("/.well-known/carddav", StringComparison.Ordinal)) return Xml("<d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>/nc/.well-known/carddav</d:href><d:propstat><d:prop><d:current-user-principal><d:href>/nc/principals/users/a%20user/</d:href></d:current-user-principal></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>");
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
            await TestGenericBaikalDiscovery(root);
            await TestGenericConfiguredBaseDiscovery(root);
            await TestTaskTwoRunSafety(settings);
            TestRoundtrips();
            TestDispatcherTaskStateAndBudget();
            TestSyncJournal(root);
        }
        finally { try { Directory.Delete(root, true); } catch (Exception) { } }
    }

    private static async Task TestGenericBaikalDiscovery(string root)
    {
        var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "generic.json"), Path.Combine(root, "generic-password.dpapi"), new Protector());
        settings.Save(new NextcloudMailboxSettings(true, false, "https://dav.example/dav.php/", "alice") { AccountType = "generic-dav" });
        settings.SetApplicationPassword("generic-secret");
        TestAssert.That(settings.Load()?.AccountType == "generic-dav" && !File.ReadAllText(Path.Combine(root, "generic.json")).Contains("generic-secret", StringComparison.Ordinal) &&
            !File.ReadAllText(Path.Combine(root, "generic-password.dpapi")).Contains("generic-secret", StringComparison.Ordinal),
            "Generische DAV-Konfiguration verlor die Kontoart oder speicherte das Kennwort im Klartext.");
        var requests = new List<string>();
        using var http = new HttpClient(new Handler(request =>
        {
            var path = request.RequestUri!.AbsolutePath; requests.Add(path);
            if (path == "/.well-known/caldav") return Task.FromResult(new HttpResponseMessage(HttpStatusCode.MovedPermanently)
                { Headers = { Location = new Uri("/dav.php/", UriKind.Relative) } });
            if (path == "/dav.php/") return Task.FromResult(Xml("<d:multistatus xmlns:d=\"DAV:\"><d:response><d:href>dav.php/</d:href><d:propstat><d:prop><d:current-user-principal><d:href>principals/alice/</d:href></d:current-user-principal></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
            if (path == "/dav.php/principals/alice/") return Task.FromResult(Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>.</d:href><d:propstat><d:prop><c:calendar-home-set><d:href>../../calendars/alice/</d:href></c:calendar-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
            if (path == "/.well-known/carddav") return Task.FromResult(Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:a=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>.</d:href><d:propstat><d:prop><a:addressbook-home-set><d:href>/dav.php/addressbooks/alice/</d:href></a:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
            if (path == "/dav.php/calendars/alice/") return Task.FromResult(Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>work/</d:href><d:propstat><d:prop><d:displayname>Work</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/></c:supported-calendar-component-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
            if (path == "/dav.php/addressbooks/alice/") return Task.FromResult(Xml(Collections("addressbook", "urn:ietf:params:xml:ns:carddav", "contacts/", "Contacts")));
            throw new InvalidOperationException("Unexpected DAV request: " + path);
        }));
        using var client = new NextcloudDavClient(settings, http);
        var sources = await client.ListSourcesAsync(CancellationToken.None);
        TestAssert.That(sources.Calendars.Count == 1 && sources.AddressBooks.Count == 1 &&
            sources.Calendars[0].Uid.StartsWith("generic-dav-calendar:", StringComparison.Ordinal) &&
            sources.AddressBooks[0].Uid.StartsWith("generic-dav-addressbook:", StringComparison.Ordinal) &&
            !sources.Calendars[0].SupportsVTodo && requests.All(path => !path.Contains("remote.php", StringComparison.Ordinal)),
            "Generische Baïkal-Discovery erzwang Nextcloud-Pfade oder verlor getrennte Quellen/VTODO-Fähigkeit.");
        const string expected = "generic-dav-calendar:ff15e1cb495b36c977ba783d0848a6845514d25b04d0bfc5cadcff6a6c86c014";
        TestAssert.That(sources.Calendars[0].Uid == expected && requests.Count(path => path == "/dav.php/") == 1,
            "Relative DAV-Weiterleitung/Hrefs oder stabile plattformgleiche Quellen-ID sind fehlerhaft.");
    }

    private static async Task TestGenericConfiguredBaseDiscovery(string root)
    {
        var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "generic-base.json"), Path.Combine(root, "generic-base-password.dpapi"), new Protector());
        settings.Save(new NextcloudMailboxSettings(true, false, "https://dav.example/baikal/dav.php/", "alice") { AccountType = "generic-dav" });
        settings.SetApplicationPassword("generic-secret");
        var requests = new List<string>();
        using var http = new HttpClient(new Handler(request =>
        {
            var path = request.RequestUri!.AbsolutePath; requests.Add(path);
            if (path is "/.well-known/caldav" or "/.well-known/carddav")
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
            if (path == "/baikal/dav.php/") return Task.FromResult(Xml("<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\" xmlns:a=\"urn:ietf:params:xml:ns:carddav\"><d:response><d:href>.</d:href><d:propstat><d:prop><c:calendar-home-set><d:href>calendars/alice/</d:href></c:calendar-home-set><a:addressbook-home-set><d:href>addressbooks/alice/</d:href></a:addressbook-home-set></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
            if (path == "/baikal/dav.php/calendars/alice/") return Task.FromResult(Xml(Collections("calendar", "urn:ietf:params:xml:ns:caldav", "work/", "Work")));
            if (path == "/baikal/dav.php/addressbooks/alice/") return Task.FromResult(Xml(Collections("addressbook", "urn:ietf:params:xml:ns:carddav", "contacts/", "Contacts")));
            throw new InvalidOperationException("Unexpected DAV request: " + path);
        }));
        using var client = new NextcloudDavClient(settings, http);
        var sources = await client.ListSourcesAsync(CancellationToken.None);
        TestAssert.That(sources.Calendars.Count == 1 && sources.AddressBooks.Count == 1 &&
            requests.Count(path => path == "/baikal/dav.php/") == 2 && requests.All(path => path.StartsWith("/baikal/", StringComparison.Ordinal) || path.StartsWith("/.well-known/", StringComparison.Ordinal)),
            "Generische DAV-Discovery versuchte nach fehlendem Origin-Well-known nicht sicher die konfigurierte Basis-URL.");
    }

    private static async Task TestTaskTwoRunSafety(NextcloudMailboxSettingsStore settings)
    {
        var putBodies = new List<string>();
        using var http = new HttpClient(new Handler(async request =>
        {
            if (request.Method.Method == "REPORT")
                return Xml("<d:multistatus xmlns:d=\"DAV:\"/>");
            if (request.Method == HttpMethod.Put)
            {
                putBodies.Add(await request.Content!.ReadAsStringAsync());
                return new HttpResponseMessage(HttpStatusCode.Created) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"t1\"") } };
            }
            throw new InvalidOperationException("Unexpected task sync request: " + request.Method);
        }));
        using var client = new NextcloudDavClient(settings, http);
        var source = new NextcloudDavSource("nextcloud-calendar:tasks", "tasks", "calendar", new Uri("https://cloud.example/nc/tasks/"));
        var local = new JsonArray(new JsonObject { ["id"] = "local", ["uid"] = "local-task", ["titel"] = "Local", ["geaendert"] = 10L });
        var first = await new NextcloudTaskSync(client).SyncAsync(source, local, new JsonArray(), 0, true, CancellationToken.None);
        TestAssert.That(first.Tasks.Count == 1 && first.Exported == 0 && putBodies.Count == 0,
            "Erster Aufgabenlauf war nicht sicher additiv.");
        var second = await new NextcloudTaskSync(client).SyncAsync(source, first.Tasks, first.Tombstones, 20, false, CancellationToken.None);
        TestAssert.That(second.Exported == 1 && putBodies.Count == 1 && putBodies[0].Contains("UID:local-task", StringComparison.Ordinal),
            "Zweiter Aufgabenlauf führte den ausgehenden Create nicht aus.");

        const string remoteTask = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:remote-task\r\nSUMMARY:Remote\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
        var updates = 0;
        using (var updateHttp = new HttpClient(new Handler(request =>
               {
                   if (request.Method.Method == "REPORT") return Task.FromResult(Xml(
                       $"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/tasks/remote.ics</d:href><d:propstat><d:prop><d:getetag>&quot;r1&quot;</d:getetag><c:calendar-data>{remoteTask}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
                   if (request.Method == HttpMethod.Put)
                   {
                       updates++;
                       return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"r2\"") } });
                   }
                   throw new InvalidOperationException("Unexpected task update request: " + request.Method);
               })))
        using (var updateClient = new NextcloudDavClient(settings, updateHttp))
        {
            var localMatch = new JsonArray(new JsonObject { ["id"] = "matched", ["uid"] = "remote-task", ["titel"] = "Local", ["geaendert"] = 10L });
            var initialized = await new NextcloudTaskSync(updateClient).SyncAsync(source, localMatch, new JsonArray(), 0, true, CancellationToken.None);
            initialized.Tasks[0]!["titel"] = "Changed"; initialized.Tasks[0]!["geaendert"] = 30L;
            var established = await new NextcloudTaskSync(updateClient).SyncAsync(source, initialized.Tasks, initialized.Tombstones, 20, false, CancellationToken.None);
            TestAssert.That(initialized.Exported == 0 && established.Updated == 1 && updates == 1,
                "Zweiter Aufgabenlauf führte ein ausgehendes Update nicht aus.");
        }

        var deletes = 0;
        using (var deleteHttp = new HttpClient(new Handler(request =>
               {
                   if (request.Method.Method == "REPORT") return Task.FromResult(Xml(
                       $"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/tasks/remote.ics</d:href><d:propstat><d:prop><d:getetag>&quot;r1&quot;</d:getetag><c:calendar-data>{remoteTask}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
                   if (request.Method == HttpMethod.Delete) { deletes++; return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent)); }
                   throw new InvalidOperationException("Unexpected task delete request: " + request.Method);
               })))
        using (var deleteClient = new NextcloudDavClient(settings, deleteHttp))
        {
            var initialized = await new NextcloudTaskSync(deleteClient).SyncAsync(source, new JsonArray(), new JsonArray(), 0, true, CancellationToken.None);
            var tombstone = initialized.Tasks[0]!.DeepClone().AsObject();
            var established = await new NextcloudTaskSync(deleteClient).SyncAsync(source, new JsonArray(), new JsonArray(tombstone), 20, false, CancellationToken.None);
            TestAssert.That(initialized.Imported == 1 && established.Deleted == 1 && deletes == 1,
                "Zweiter Aufgabenlauf führte ein ausgehendes Delete nicht aus.");
        }
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

        const string ownedCalendar = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:owned\r\nDTSTART;VALUE=DATE:20260817\r\nSUMMARY:Owned\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(
                   $"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/book/owned.ics</d:href><d:propstat><d:prop><d:getetag>&quot;o1&quot;</d:getetag><c:calendar-data>{ownedCalendar}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:owned", "owned", "calendar",
                new Uri("https://cloud.example/nc/book/"));
            var imported = await new NextcloudCalendarSync(client).SyncAsync(calendar,
                new JsonArray(), new JsonArray(), new JsonArray(), 1, false, CancellationToken.None);
            TestAssert.That(imported.Termine.Single()?["syncKalenderUid"]?.GetValue<string>() == calendar.Uid,
                "Importierter CalDAV-Termin besitzt seinen Quellkalender nicht.");
        }

        var calendarDeletes = 0; var calendarPuts = 0;
        const string deletedUid = "delete-from-both";
        const string firstCalendar = "nextcloud-calendar:first";
        const string secondDeleteCalendar = "nextcloud-calendar:second";
        using (var http = new HttpClient(new Handler(request =>
               {
                    if (request.Method == HttpMethod.Delete)
                   {
                       calendarDeletes++;
                        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent));
                    }
                    if (request.Method == HttpMethod.Put)
                    {
                        calendarPuts++;
                        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent) { Headers = { ETag = new System.Net.Http.Headers.EntityTagHeaderValue("\"d2\"") } });
                    }
                    var collection = request.RequestUri!.AbsolutePath.EndsWith("/first/", StringComparison.Ordinal) ? "first" : "second";
                    var href = $"/nc/calendar/{collection}/item.ics";
                    var task = collection == "first" ? "BEGIN:VTODO\r\nUID:keep-task\r\nSUMMARY:Keep\r\nEND:VTODO\r\n" : "";
                    var body = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{deletedUid}\r\nDTSTART;VALUE=DATE:20260817\r\nSUMMARY:Delete\r\nEND:VEVENT\r\n{task}END:VCALENDAR\r\n";
                   return Task.FromResult(Xml($"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>{href}</d:href><d:propstat><d:prop><d:getetag>&quot;d1&quot;</d:getetag><c:calendar-data>{body}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>"));
               })))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var first = new NextcloudDavSource(firstCalendar, "first", "calendar", new Uri("https://cloud.example/nc/calendar/first/"));
            var second = new NextcloudDavSource(secondDeleteCalendar, "second", "calendar", new Uri("https://cloud.example/nc/calendar/second/"));
            var suffix = "#" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(deletedUid))).ToLowerInvariant();
            var tombstones = new JsonArray(new JsonObject
            {
                ["uid"] = deletedUid, ["syncKalenderUid"] = first.Uid,
                ["syncQuellen"] = new JsonObject
                {
                    [first.Uid] = new JsonObject { ["id"] = "https://cloud.example/nc/calendar/first/item.ics" + suffix },
                    [second.Uid] = new JsonObject { ["id"] = "https://cloud.example/nc/calendar/second/item.ics" + suffix }
                }
            });
            var afterFirst = await new NextcloudCalendarSync(client).SyncAsync(first,
                new JsonArray(), new JsonArray(), tombstones, 1, false, CancellationToken.None);
            TestAssert.That(afterFirst.Deleted == 1 && afterFirst.Tombstones.Count == 1 &&
                ContactFields.Source(afterFirst.Tombstones[0]!.AsObject(), first.Uid) is null &&
                ContactFields.Source(afterFirst.Tombstones[0]!.AsObject(), second.Uid) is not null &&
                afterFirst.Tombstones[0]?["syncKalenderUid"]?.GetValue<string>() == second.Uid,
                "Erste CalDAV-Löschung verwarf die noch offene zweite Kalenderzuordnung.");
            var afterSecond = await new NextcloudCalendarSync(client).SyncAsync(second,
                new JsonArray(), new JsonArray(), afterFirst.Tombstones, 1, false, CancellationToken.None);
            TestAssert.That(afterSecond.Deleted == 1 && afterSecond.Tombstones.Count == 0 && calendarDeletes == 1 && calendarPuts == 1,
                "Terminlöschung bewahrte eine co-lokalisierte Aufgabe nicht per PUT oder löschte eine leere Ressource nicht per DELETE.");
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

        const string irrelevantCalendar = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:UTC\r\nEND:VTIMEZONE\r\nBEGIN:VJOURNAL\r\nUID:journal\r\nEND:VJOURNAL\r\nBEGIN:VFREEBUSY\r\nUID:busy\r\nEND:VFREEBUSY\r\nEND:VCALENDAR\r\n";
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(
                   $"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/calendar/irrelevant.ics</d:href><d:propstat><d:prop><d:getetag>&quot;i1&quot;</d:getetag><c:calendar-data>{irrelevantCalendar}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:irrelevant", "irrelevant", "calendar", new Uri("https://cloud.example/nc/calendar/"));
            var appointments = await new NextcloudCalendarSync(client).SyncAsync(calendar, new JsonArray(), new JsonArray(), new JsonArray(), 1, true, CancellationToken.None);
            var tasks = await new NextcloudTaskSync(client).SyncAsync(calendar, new JsonArray(), new JsonArray(), 1, true, CancellationToken.None);
            TestAssert.That(appointments.Imported == 0 && tasks.Imported == 0,
                "VJOURNAL/VFREEBUSY/VTIMEZONE-only Ressourcen wurden nicht als irrelevant übersprungen.");
        }

        const string malformedTask = "BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:bad-task\r\nDUE:not-a-date\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
        using (var http = new HttpClient(new Handler(_ => Task.FromResult(Xml(
                   $"<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\"><d:response><d:href>/nc/calendar/bad-task.ics</d:href><d:propstat><d:prop><d:getetag>&quot;b1&quot;</d:getetag><c:calendar-data>{malformedTask}</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>")))))
        using (var client = new NextcloudDavClient(settings, http))
        {
            var calendar = new NextcloudDavSource("nextcloud-calendar:bad-task", "bad-task", "calendar", new Uri("https://cloud.example/nc/calendar/"));
            await TestAssert.ThrowsAsync<InvalidDataException>(() => new NextcloudTaskSync(client).SyncAsync(calendar,
                new JsonArray(), new JsonArray(), 1, true, CancellationToken.None),
                "Ein genuinely malformed VTODO wurde als irrelevante Komponente übersprungen.");
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

        const string mixedTask = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:event\r\nDTSTART;VALUE=DATE:20260817\r\nSUMMARY:Termin\r\nEND:VEVENT\r\nBEGIN:VTODO\r\nUID:child\r\nSUMMARY:Kind\r\nRELATED-TO;RELTYPE=PARENT:parent\r\nRELATED-TO;RELTYPE=SIBLING:foreign\r\nX-MAGNOLIE-REIHENFOLGE:7\r\nEND:VTODO\r\nEND:VCALENDAR\r\n";
        var task = ExchangeCodec.ParseIcs(mixedTask).Aufgaben.Single()!.AsObject();
        task["titel"] = "Geändert";
        var changedTask = ExchangeCodec.ReplaceCalendarTask(mixedTask, task);
        TestAssert.That(task["elternUid"]?.GetValue<string>() == "parent" && task["reihenfolge"]?.GetValue<int>() == 7 &&
            changedTask.Contains("BEGIN:VEVENT", StringComparison.Ordinal) && changedTask.Contains("SUMMARY:Termin", StringComparison.Ordinal) &&
            changedTask.Count("RELATED-TO;RELTYPE=PARENT:parent") == 1 && changedTask.Contains("RELATED-TO;RELTYPE=SIBLING:foreign", StringComparison.Ordinal),
            "Gemischter CalDAV-VTODO-Roundtrip verlor Hierarchie, fremde Beziehung oder VEVENT.");
        var withoutTask = ExchangeCodec.RemoveCalendarTask(changedTask, "child");
        TestAssert.That(withoutTask is not null && withoutTask.Contains("BEGIN:VEVENT", StringComparison.Ordinal) && !withoutTask.Contains("BEGIN:VTODO", StringComparison.Ordinal),
            "VTODO-Löschung beschädigte eine gemischte Kalenderressource.");
        var withoutEvent = ExchangeCodec.RemoveCalendarEvent(changedTask, "event");
        TestAssert.That(withoutEvent is not null && withoutEvent.Contains("BEGIN:VTODO", StringComparison.Ordinal) && !withoutEvent.Contains("BEGIN:VEVENT", StringComparison.Ordinal) &&
            ExchangeCodec.RemoveCalendarEvent("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:event\r\nDTSTART;VALUE=DATE:20260817\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", "event") is null,
            "VEVENT-Löschung beschädigte eine gemischte Ressource oder behielt eine leere VCALENDAR-Hülle.");

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

        const string anniversaryResource = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:birthday\r\nDTSTART;VALUE=DATE:19800403\r\nRRULE:FREQ=YEARLY\r\nCATEGORIES:Geburtstag\r\nX-MAGNOLIE-TYPE-ID:birthday\r\nSUMMARY:Alt\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:other\r\nDTSTART;VALUE=DATE:20260904\r\nSUMMARY:Unberührt\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
        var anniversary = ExchangeCodec.ParseIcs(anniversaryResource).Jahrestage.Single()!.AsObject();
        anniversary["name"] = "Neu";
        var changedAnniversary = ExchangeCodec.ReplaceCalendarAnniversary(anniversaryResource, anniversary);
        TestAssert.That(changedAnniversary.Count("BEGIN:VEVENT") == 2 && changedAnniversary.Contains("SUMMARY:Neu", StringComparison.Ordinal) &&
            changedAnniversary.Contains("UID:other", StringComparison.Ordinal) && changedAnniversary.Contains("SUMMARY:Unberührt", StringComparison.Ordinal),
            "Ein Jahrestags-PUT überschrieb benachbarte Ereignisse derselben CalDAV-Ressource.");

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

    private static void TestDispatcherTaskStateAndBudget()
    {
        var source = File.ReadAllText("BridgeDispatcher.Sync.cs");
        TestAssert.That(source.Contains("sourceCursors[\"aufgaben\"]", StringComparison.Ordinal) &&
            source.Contains("[\"aufgabenInitialisiert\"] = true", StringComparison.Ordinal) &&
            source.Contains("taskCursors[calendarId] = now", StringComparison.Ordinal),
            "Aufgaben besitzen keinen separat persistierten Initialisierungscursor.");
        var taskTimeout = source.IndexOf("using var taskTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));", StringComparison.Ordinal);
        var taskCall = source.IndexOf("additiveOnly || firstTaskRun, taskTimeout.Token", StringComparison.Ordinal);
        TestAssert.That(taskTimeout >= 0 && taskCall > taskTimeout && !source.Contains("additiveOnly || firstTaskRun, calendarTimeout.Token", StringComparison.Ordinal),
            "Aufgabensync teilt weiterhin das 12-Sekunden-Budget des Terminsyncs.");
    }

    private static string Collections(string type, string ns, string href, string name) => $"<d:multistatus xmlns:d=\"DAV:\" xmlns:x=\"{ns}\"><d:response><d:href>{href}</d:href><d:propstat><d:prop><d:displayname>{name}</d:displayname><d:resourcetype><d:collection/><x:{type}/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>";
    private static HttpResponseMessage Xml(string xml) => new(HttpStatusCode.MultiStatus) { Content = new StringContent(xml, Encoding.UTF8, "application/xml") };
    private static string Basic(string user, string password) => "Basic " + Convert.ToBase64String(Encoding.UTF8.GetBytes(user + ":" + password));
    private sealed record Request(string Method, string Uri, string Authorization, string Depth, string IfMatch, string Body);
    private sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> response) : HttpMessageHandler { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => response(request); }
    private sealed class CancellableHandler : HttpMessageHandler { protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) { await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken); return new HttpResponseMessage(HttpStatusCode.OK); } }
    private sealed class Protector : ISecretProtector { public byte[] Protect(byte[] plain) => plain.Select(value => (byte)(value ^ 0x5a)).Prepend((byte)1).ToArray(); public byte[] Unprotect(byte[] encrypted) => encrypted.Skip(1).Select(value => (byte)(value ^ 0x5a)).ToArray(); }
}
