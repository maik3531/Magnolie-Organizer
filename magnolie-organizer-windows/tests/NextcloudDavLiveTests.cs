using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Opt-in integration probe. Use a disposable Nextcloud account only.
internal static class NextcloudDavLiveTests
{
    internal static async Task<int> RunAsync()
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
            using var client = new NextcloudDavClient(settings);
            var sources = await client.ListSourcesAsync(timeout.Token);
            TestAssert.That(sources.Calendars.Count > 0 && sources.AddressBooks.Count > 0 && sources.Error == "", "Nextcloud discovery failed.");
            var calendar = sources.Calendars[0]; var book = sources.AddressBooks[0];
            var uid = "magnolie-probe-" + Guid.NewGuid().ToString("N");
            var eventText = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:20260922T080000Z\r\nDTSTART:20261001T090000Z\r\nDTEND:20261001T100000Z\r\nSUMMARY:Magnolie DAV probe\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
            NextcloudDavObject? eventObject = null, contactObject = null;
            try
            {
                eventObject = await client.CreateAsync(calendar, uid, ".ics", "text/calendar", eventText, timeout.Token);
                contactObject = await client.CreateAsync(book, uid, ".vcf", "text/vcard",
                    $"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:{uid}\r\nFN:Magnolie DAV probe\r\nN:Probe;Magnolie;;;\r\nEND:VCARD\r\n", timeout.Token);
                var contacts = new ContactSyncEngine();
                var remote = new NextcloudCardDavRemote(client, book);
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
                Console.WriteLine("Live DAV: discovery, CalDAV/CardDAV import, local edits, server readback and repeat without duplicates passed.");
            }
            finally
            {
                // Read the current ETag; never delete a fixture unconditionally.
                if (eventObject is not null)
                    foreach (var item in (await client.ReadCalendarAsync(calendar, timeout.Token)).Where(item => item.Href == eventObject.Href))
                        await client.DeleteAsync(item.Href, item.ETag, timeout.Token);
                if (contactObject is not null)
                    foreach (var item in (await client.ReadAddressBookAsync(book, timeout.Token)).Where(item => item.Href == contactObject.Href))
                        await client.DeleteAsync(item.Href, item.ETag, timeout.Token);
            }
            return 0;
        }
        finally { Directory.Delete(root, true); }
    }
}
