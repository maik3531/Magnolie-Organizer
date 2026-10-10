using System.Net;
using System.Security;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class CalendarBirthdayCleanupTests
{
    private static readonly NextcloudDavSource Source = new("nextcloud-calendar:synthetic", "Synthetic", "calendar", new Uri("https://cloud.example/nc/calendar/"), false);
    private static string Event(string uid, string extra = "", string trigger = "-PT10M", string start = "19800510", string end = "19800511") =>
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:" + uid + "\r\nDTSTART;VALUE=DATE:" + start + "\r\nDTEND;VALUE=DATE:" + end +
        "\r\nRRULE:FREQ=YEARLY\r\nSUMMARY:Synthetic\r\nX-MAGNOLIE-TYPE-ID:birthday\r\nCREATED:" + (uid == "original" ? "20200101" : "20260101") +
        "T000000Z\r\n" + extra + "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Synthetic reminder\r\nTRIGGER:" + trigger + "\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
    private static NextcloudDavObject Resource(string uid, string? text = null) => new(new Uri(Source.Href, uid + ".ics"), "\"" + uid + "-1\"", text ?? Event(uid));
    private static JsonObject Local(NextcloudDavObject resource, string contact = "contact")
    {
        var item = ExchangeCodec.ParseIcs(resource.Text).Jahrestage[0]!.DeepClone().AsObject();
        item["kontaktId"] = contact; item["id"] = "local-" + ContactFields.Text(item, "uid");
        NextcloudCalendarSync.SetSource(item, Source.Uid, NextcloudCalendarSync.RemoteKey(resource.Href, item), resource.ETag);
        item["syncQuellen"]!["eds:other"] = new JsonObject { ["id"] = "keep-other-" + ContactFields.Text(item, "uid") };
        return item;
    }
    internal static async Task RunAsync()
    {
        var resources = new[] { Resource("original"), Resource("copy") };
        var local = new JsonArray(Local(resources[0]), Local(resources[1]));
        var plans = CalendarBirthdayCleanup.PlanCleanup(local, resources, Source.Uid);
        TestAssert.That(plans.Count == 1 && plans[0].KeepUid == "original" && plans[0].RemoveUid == "copy", "No exact bound birthday plan.");
        TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(local, [resources[0] with { ETag = "\"new-revision\"" }, resources[1]], Source.Uid).Count == 0,
            "Cleanup consumed a remote revision before the ordinary merge imported it.");
        foreach (var text in new[] { Event("copy", trigger: "-PT30M"), Event("copy", "DESCRIPTION:Different\r\n"),
                     Event("copy", "EXDATE;VALUE=DATE:20270510\r\n"), Event("copy", "RECURRENCE-ID;VALUE=DATE:20260510\r\n"),
                     Event("copy", "ATTENDEE:mailto:fixture@example.invalid\r\n"), Event("copy", "X-LIC-ERROR:Unknown detail\r\n"),
                     Event("copy").Replace("FREQ=YEARLY", "FREQ=YEARLY;COUNT=2"),
                     Event("copy").Replace("END:VCALENDAR", "BEGIN:VTODO\r\nUID:task\r\nEND:VTODO\r\nEND:VCALENDAR") })
            TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(local, [resources[0], Resource("copy", text)], Source.Uid).Count == 0, "Protected calendar detail was discarded.");
        foreach (var field in new[] { "kontaktId", "datum", "syncKalenderUid", "notiz" })
        {
            var changed = local.DeepClone().AsArray(); changed[1]![field] = "changed";
            TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(changed, resources, Source.Uid).Count == 0, "Unbound or changed local data entered cleanup.");
        }
        var unknownResources = new[] { Resource("original", Event("original", start: "20260510", end: "20260511")), Resource("copy", Event("copy", "X-MAGNOLIE-DATE:--05-10\r\n", start: "20000510", end: "20000511")) };
        var unknown = new JsonArray(Local(unknownResources[0]), Local(unknownResources[1]));
        unknown[0]!["datum"] = "--05-10";
        NextcloudCalendarSync.SetSource(unknown[0]!.AsObject(), Source.Uid, NextcloudCalendarSync.RemoteKey(unknownResources[0].Href, unknown[0]!.AsObject()), unknownResources[0].ETag);
        TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(unknown, unknownResources, Source.Uid).Single().KeepUid == "copy", "Unknown-year annotation was not retained.");
        await RuntimeAsync(crash: false);
        await RuntimeAsync(crash: true);
        await RuntimeAsync(conflict: true);
        await RuntimeAsync(weakEtag: true);
        if (OperatingSystem.IsWindows())
        {
            var root = Path.Combine(Path.GetTempPath(), "magnolie-birthday135-dpapi-" + Guid.NewGuid().ToString("N"));
            try
            {
                var journal = new NextcloudSyncJournal(Path.Combine(root, "sync"));
                var archive = journal.BirthdayArchive(Source.Uid, "native-epoch");
                using (archive.Acquire()) archive.Save(new JsonObject { ["proof"] = "synthetic birthday" });
                TestAssert.That(journal.BirthdayArchive(Source.Uid, "native-epoch").Load()["proof"]?.GetValue<string>() == "synthetic birthday", "Native DPAPI cleanup archive did not survive reopen.");
                TestAssert.That(Directory.GetFiles(root).Where(path => !path.EndsWith(".lock", StringComparison.Ordinal))
                    .All(path => !File.ReadAllText(path).Contains("synthetic birthday", StringComparison.Ordinal)), "Native archive exposed cleartext.");
            }
            finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        }
    }

    private static async Task RuntimeAsync(bool crash = false, bool conflict = false, bool weakEtag = false)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-birthday135-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var protector = new Protector();
            var journal = new NextcloudSyncJournal(Path.Combine(root, "sync"), protector);
            var archive = journal.BirthdayArchive(Source.Uid, "epoch");
            var remote = new Dictionary<string, NextcloudDavObject> { ["original"] = Resource("original"), ["copy"] = Resource("copy") };
            if (weakEtag) remote["copy"] = remote["copy"] with { ETag = "W/\"weak\"" };
            var items = new JsonArray(Local(remote["original"]), Local(remote["copy"]));
            var deletes = 0;
            var settings = new NextcloudMailboxSettingsStore(Path.Combine(root, "settings"), Path.Combine(root, "secret"), protector);
            settings.Save(new NextcloudMailboxSettings(true, "https://cloud.example/nc", "synthetic")); settings.SetApplicationPassword("fixture");
            using var http = new HttpClient(new Handler(request =>
            {
                if (request.Method.Method == "REPORT") return new HttpResponseMessage(HttpStatusCode.MultiStatus) { Content = new StringContent(
                    "<d:multistatus xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\">" + string.Join("", remote.Values.Select(resource =>
                    "<d:response><d:href>" + resource.Href.AbsolutePath + "</d:href><d:propstat><d:prop><d:getetag>" + SecurityElement.Escape(resource.ETag) +
                    "</d:getetag><c:calendar-data>" + SecurityElement.Escape(resource.Text) + "</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")) + "</d:multistatus>", Encoding.UTF8, "application/xml") };
                TestAssert.That(request.Method == HttpMethod.Delete && request.RequestUri == remote["copy"].Href && request.Headers.IfMatch.Single().Tag == remote["copy"].ETag, "Unexpected write or missing conditional deletion.");
                TestAssert.That(archive.Load()["operations"]?["copy"]?["phase"]?.GetValue<string>() == "prepared", "DELETE preceded the durable archive.");
                if (conflict) return new HttpResponseMessage(HttpStatusCode.PreconditionFailed);
                remote.Remove("copy"); deletes++;
                if (crash) throw new IOException("Synthetic interruption after DELETE");
                return new HttpResponseMessage(HttpStatusCode.NoContent);
            }));
            using var client = new NextcloudDavClient(settings, http);
            var engine = new NextcloudCalendarSync(client, archive);
            var first = await engine.SyncAsync(Source, [], items, [], 0, true, CancellationToken.None);
            TestAssert.That(deletes == 0 && !archive.Exists && first.Jahrestage.Count == 2, "Additive first run deleted birthdays.");
            NextcloudCalendarResult? result = null;
            try { result = await engine.SyncAsync(Source, [], items, [], 1, false, CancellationToken.None); }
            catch (Exception error) when ((crash && error is IOException) || (conflict && error is InvalidOperationException) || (weakEtag && error is InvalidDataException)) { }
            if (conflict || weakEtag)
            {
                TestAssert.That(result is null && deletes == 0 && remote.Count == 2, "Unsafe DAV deletion succeeded.");
                return;
            }
            if (crash)
            {
                TestAssert.That(result is null && archive.Load()["operations"]!["copy"]!["phase"]!.GetValue<string>() == "prepared", "Interrupted deletion lost its recovery plan.");
                crash = false;
                engine = new NextcloudCalendarSync(client, journal.BirthdayArchive(Source.Uid, "epoch"));
                result = await engine.SyncAsync(Source, [], items, [], 1, false, CancellationToken.None);
            }
            TestAssert.That(result is not null && deletes == 1 && remote.Count == 1 && result.Jahrestage.Count == 2 &&
                result.Jahrestage.OfType<JsonObject>().All(item => ContactFields.Text(item, "uid") == "original"), "Cleanup did not retain the original series and rebind both local aliases.");
            TestAssert.That(ContactFields.Source(result!.Jahrestage[1]!.AsObject(), "eds:other")?["id"]?.GetValue<string>() == "keep-other-copy", "Cleanup changed another source.");
            journal.Delete();
            TestAssert.That(archive.Exists, "Ordinary transaction completion removed cleanup proof.");
            var replay = await engine.SyncAsync(Source, [], result.Jahrestage, [], 2, false, CancellationToken.None);
            TestAssert.That(deletes == 1 && replay.Exported == 0 && replay.Updated == 0, "Replay recreated or rewrote a birthday.");
            remote["original"] = remote["original"] with { Text = remote["original"].Text.Replace("SUMMARY:Synthetic", "SUMMARY:Remote changed"), ETag = "\"v2\"" };
            var updated = await engine.SyncAsync(Source, [], replay.Jahrestage, [], 3, false, CancellationToken.None);
            TestAssert.That(updated.Jahrestage.OfType<JsonObject>().All(item => ContactFields.Text(item, "name") == "Remote changed"), "Remote survivor update did not reach both aliases.");
            using (archive.Acquire())
            {
                var rejected = false;
                try { using var second = archive.Acquire(); } catch (IOException) { rejected = true; }
                TestAssert.That(rejected, "Cleanup allowed concurrent archive owners.");
            }
            TestAssert.That(!journal.BirthdayArchive(Source.Uid, "other-epoch").Exists, "Restore epoch reused a cleanup archive.");
        }
        finally { Directory.Delete(root, true); }
    }
    private sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> reply) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) => Task.FromResult(reply(request));
    }
    private sealed class Protector : ISecretProtector
    {
        private readonly byte[] key = RandomNumberGenerator.GetBytes(32);
        public byte[] Protect(byte[] plain)
        {
            var result = new byte[28 + plain.Length]; RandomNumberGenerator.Fill(result.AsSpan(0, 12));
            using var aes = new AesGcm(key, 16); aes.Encrypt(result.AsSpan(0, 12), plain, result.AsSpan(28), result.AsSpan(12, 16)); return result;
        }
        public byte[] Unprotect(byte[] encrypted)
        {
            var plain = new byte[encrypted.Length - 28]; using var aes = new AesGcm(key, 16);
            aes.Decrypt(encrypted.AsSpan(0, 12), encrypted.AsSpan(28), encrypted.AsSpan(12, 16), plain); return plain;
        }
    }
}
