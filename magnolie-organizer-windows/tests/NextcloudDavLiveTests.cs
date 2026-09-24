using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Opt-in integration probe. Use a disposable Nextcloud account only.
internal static class NextcloudDavLiveTests
{
    // Explicit diagnostic for already connected accounts. Never synchronize,
    // upload, delete, or print account identifiers or remote object contents.
    internal static async Task<int> ReadOnlyAsync(bool managed = false)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(2));
        var root = Path.Combine(Path.GetTempPath(), "magnolie-readonly-dav-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var sources = await ThunderbirdBridge.SourcesAsync(timeout.Token, managed);
            Console.WriteLine($"Read-only bridge discovery: {sources.Count} sources.");
            var failed = false;
            foreach (var source in sources)
            {
                try
                {
                    using var client = ThunderbirdBridge.CreateClient(source, new NextcloudSyncJournal(Path.Combine(root, "journal")), new string('a', 64));
                    if (source.Kind == "addressbook")
                    {
                        var contacts = await new NextcloudCardDavRemote(client, source).ReadAsync(timeout.Token);
                        Console.WriteLine($"Read-only addressbook: {contacts.Count} contacts; response, vCards and identities accepted.");
                    }
                    else
                    {
                        var objects = await client.ReadCalendarAsync(source, timeout.Token);
                        var parsed = objects.Select(item => ExchangeCodec.ParseIcs(item.Text)).ToArray();
                        var events = parsed.SelectMany(item => item.Termine.Concat(item.Jahrestage)).OfType<JsonObject>().ToArray();
                        var tasks = parsed.SelectMany(item => item.Aufgaben).OfType<JsonObject>().ToArray();
                        var malformedEvents = parsed.Sum(item => item.FehlerhafteTermine);
                        var malformedTasks = parsed.Sum(item => item.FehlerhafteAufgaben);
                        var invalidIdentities = new[] { events, tasks }.Sum(items => items.Count(item => ContactFields.Text(item, "uid").Length == 0) +
                            items.GroupBy(item => ContactFields.Text(item, "uid"), StringComparer.Ordinal).Sum(group => group.Count() - 1));
                        failed |= malformedEvents + malformedTasks + invalidIdentities > 0;
                        Console.WriteLine($"Read-only calendar: {objects.Count} objects; {events.Length} events; {tasks.Length} tasks; " +
                            $"malformed events={malformedEvents}, malformed tasks={malformedTasks}, invalid identities={invalidIdentities}.");
                    }
                }
                catch (Exception error)
                {
                    failed = true;
                    var frames = new System.Diagnostics.StackTrace(error, true).GetFrames()
                        .Select(frame => $"{frame.GetMethod()?.DeclaringType?.Name}.{frame.GetMethod()?.Name}:{frame.GetFileLineNumber()}");
                    Console.WriteLine($"Read-only {source.Kind}: {error.GetType().Name}; {string.Join(" > ", frames)}");
                }
            }
            return sources.Count == 0 || failed ? 1 : 0;
        }
        catch (Exception error)
        {
            var frames = new System.Diagnostics.StackTrace(error, true).GetFrames()
                .Select(frame => $"{frame.GetMethod()?.DeclaringType?.Name}.{frame.GetMethod()?.Name}:{frame.GetFileLineNumber()}");
            Console.WriteLine($"Read-only discovery failed: {error.GetType().Name}; {string.Join(" > ", frames)}");
            return 1;
        }
        finally { Directory.Delete(root, true); }
    }

    internal static async Task<int> RunAsync(bool thunderbird = false)
    {
        var server = Environment.GetEnvironmentVariable("MAGNOLIE_DAV_TEST_SERVER");
        var user = Environment.GetEnvironmentVariable("MAGNOLIE_DAV_TEST_USER");
        var password = Environment.GetEnvironmentVariable("MAGNOLIE_DAV_TEST_PASSWORD");
        if (string.IsNullOrEmpty(server) || string.IsNullOrEmpty(password) ||
            user is null || !user.StartsWith("magnolie-test-", StringComparison.Ordinal))
            throw new InvalidOperationException("Set MAGNOLIE_DAV_TEST_SERVER, MAGNOLIE_DAV_TEST_USER (magnolie-test-*), and MAGNOLIE_DAV_TEST_PASSWORD for a disposable account.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-live-dav-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings.json"), Path.Combine(root, "password.dat"));
            settings.SaveConfiguration(new NextcloudMailboxSettings(true, false, server, user), password, false);
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(2));
            using var discovery = new NextcloudDavClient(settings);
            var tbSources = thunderbird ? await ThunderbirdBridge.SourcesAsync(timeout.Token) : [];
            var sources = thunderbird ? new NextcloudDavSources(tbSources.Where(item => item.Kind == "calendar").ToArray(),
                tbSources.Where(item => item.Kind == "addressbook").ToArray()) : await discovery.ListSourcesAsync(timeout.Token);
            TestAssert.That(sources.Calendars.Count > 0 && sources.AddressBooks.Count > 0 && sources.Error == "", "Nextcloud discovery failed.");
            // Never write fixtures into the server-generated system address
            // book. Provision these two collections on the disposable account.
            var calendar = sources.Calendars.Single(source => source.Href.AbsolutePath.TrimEnd('/').EndsWith("/MagnolieProbe", StringComparison.Ordinal));
            var book = sources.AddressBooks.Single(source => source.Href.AbsolutePath.TrimEnd('/').EndsWith("/MagnolieProbe", StringComparison.Ordinal));
            var journal = new NextcloudSyncJournal(Path.Combine(root, "journal"));
            var transaction = new string('a', 64);
            using var client = thunderbird ? ThunderbirdBridge.CreateClient(calendar, journal, transaction) : new NextcloudDavClient(settings);
            using var bookClient = thunderbird ? ThunderbirdBridge.CreateClient(book, journal, transaction) : new NextcloudDavClient(settings);
            var uid = "magnolie-probe-" + Guid.NewGuid().ToString("N");
            var eventText = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260922T080000Z\r\nDTSTART:20261001T090000Z\r\nDTEND:20261001T100000Z\r\nSUMMARY:Magnolie DAV probe\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
            NextcloudDavObject? eventObject = null, contactObject = null, taskObject = null;
            try
            {
                eventObject = await client.CreateAsync(calendar, uid, ".ics", "text/calendar", eventText, timeout.Token);
                contactObject = await bookClient.CreateAsync(book, uid, ".vcf", "text/vcard",
                    $"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:Magnolie DAV probe\r\nN:Probe;Magnolie;;;\r\nEND:VCARD\r\n", timeout.Token);
                var contacts = new ContactSyncEngine();
                var remote = new NextcloudCardDavRemote(bookClient, book);
                var first = await contacts.SyncAsync(book.Uid, [], [], 0, remote, timeout.Token, true);
                var card = first.Contacts.OfType<JsonObject>().Single(item => item["uid"]?.GetValue<string>() == uid);
                card["vorname"] = "Changed"; card["geaendert"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1;
                var second = await contacts.SyncAsync(book.Uid, first.Contacts, first.Tombstones, 1, remote, timeout.Token, false);
                TestAssert.That(second.Counts.Errors == 0, "CardDAV change failed.");
                var third = await contacts.SyncAsync(book.Uid, second.Contacts, second.Tombstones, 1, remote, timeout.Token, false);
                TestAssert.That(third.Counts.Errors == 0 && third.Contacts.Count == second.Contacts.Count, "CardDAV repeat failed or duplicated contacts.");
                var calendarSync = new NextcloudCalendarSync(client);
                var imported = await calendarSync.SyncAsync(calendar, [], [], [], 0, true, timeout.Token);
                var item = imported.Termine.OfType<JsonObject>().Single(item => item["uid"]?.GetValue<string>() == uid);
                item["titel"] = "Changed DAV probe"; item["geaendert"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1;
                var changed = await calendarSync.SyncAsync(calendar, imported.Termine, imported.Jahrestage, imported.Tombstones, 1, false, timeout.Token);
                var repeat = await calendarSync.SyncAsync(calendar, changed.Termine, changed.Jahrestage, changed.Tombstones, 1, false, timeout.Token);
                TestAssert.That(repeat.Termine.Count == changed.Termine.Count, "CalDAV repeat duplicated appointments.");
                TestAssert.That((await client.ReadCalendarAsync(calendar, timeout.Token)).Any(item => item.Text.Contains("Changed DAV probe")), "CalDAV edit did not reach the server.");
                TestAssert.That((await remote.ReadAsync(timeout.Token)).Any(item => item.Data["vorname"]?.GetValue<string>() == "Changed"), "CardDAV edit did not reach the server.");
                TestAssert.That(calendar.SupportsVTodo, "The disposable test calendar must support VTODO.");
                var taskUid = uid + "-task";
                taskObject = await client.CreateAsync(calendar, taskUid, ".ics", "text/calendar",
                    $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:{taskUid}\r\nDTSTAMP:20260922T080000Z\r\nDUE;VALUE=DATE:20261002\r\nSUMMARY:Magnolie DAV task probe\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n", timeout.Token);
                var taskSync = new NextcloudTaskSync(client);
                var importedTasks = await taskSync.SyncAsync(calendar, [], [], 0, true, timeout.Token);
                var task = importedTasks.Tasks.OfType<JsonObject>().Single(item => item["uid"]?.GetValue<string>() == taskUid);
                task["titel"] = "Changed DAV task probe"; task["erledigt"] = true;
                task["geaendert"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1;
                var changedTasks = await taskSync.SyncAsync(calendar, importedTasks.Tasks, importedTasks.Tombstones, 1, false, timeout.Token);
                var repeatedTasks = await taskSync.SyncAsync(calendar, changedTasks.Tasks, changedTasks.Tombstones, 1, false, timeout.Token);
                TestAssert.That(repeatedTasks.Tasks.Count == changedTasks.Tasks.Count && repeatedTasks.Tasks.OfType<JsonObject>()
                    .Single(item => item["uid"]?.GetValue<string>() == taskUid)["erledigt"]?.GetValue<bool>() == true,
                    "VTODO repeat duplicated tasks or lost completion.");
                TestAssert.That((await client.ReadCalendarAsync(calendar, timeout.Token)).Any(item => item.Href == taskObject.Href &&
                    item.Text.Contains("Changed DAV task probe", StringComparison.Ordinal) && item.Text.Contains("STATUS:COMPLETED", StringComparison.Ordinal)),
                    "VTODO edit did not reach the server.");
                Console.WriteLine((thunderbird ? "Thunderbird bridge" : "Live DAV") + ": discovery, CalDAV/CardDAV/VTODO import, local edits, server readback and repeat without duplicates passed.");
            }
            finally
            {
                // Read the current ETag; never delete a fixture unconditionally.
                if (eventObject is not null)
                    foreach (var item in (await client.ReadCalendarAsync(calendar, timeout.Token)).Where(item => item.Href == eventObject.Href))
                        await client.DeleteAsync(item.Href, item.ETag, timeout.Token);
                if (taskObject is not null)
                    foreach (var item in (await client.ReadCalendarAsync(calendar, timeout.Token)).Where(item => item.Href == taskObject.Href))
                        await client.DeleteAsync(item.Href, item.ETag, timeout.Token);
                if (contactObject is not null)
                    foreach (var item in (await bookClient.ReadAddressBookAsync(book, timeout.Token)).Where(item => item.Href == contactObject.Href))
                        await bookClient.DeleteAsync(item.Href, item.ETag, timeout.Token);
            }
            return 0;
        }
        finally { Directory.Delete(root, true); }
    }
}
