using System.Net;
using System.IO.Pipes;
using System.Security;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
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
    private static JsonObject Local(NextcloudDavObject resource, string contact = "contact", string? sourceUid = null)
    {
        var item = ExchangeCodec.ParseIcs(resource.Text).Jahrestage[0]!.DeepClone().AsObject();
        item["kontaktId"] = contact; item["id"] = "local-" + ContactFields.Text(item, "uid");
        NextcloudCalendarSync.SetSource(item, sourceUid ?? Source.Uid, NextcloudCalendarSync.RemoteKey(resource.Href, item), resource.ETag);
        item["syncQuellen"]!["eds:other"] = new JsonObject { ["id"] = "keep-other-" + ContactFields.Text(item, "uid") };
        return item;
    }
    internal static async Task RunAsync()
    {
        var resources = new[] { Resource("original"), Resource("copy") };
        var local = new JsonArray(Local(resources[0]), Local(resources[1]));
        var plans = CalendarBirthdayCleanup.PlanCleanup(local, resources, Source.Uid);
        TestAssert.That(plans.Count == 1 && plans[0].KeepUid == "original" && plans[0].RemoveUid == "copy", "No exact bound birthday plan.");
        var unicode = new[] { Resource("\U00010000"), Resource("\uE000") };
        var unicodePlan = CalendarBirthdayCleanup.PlanCleanup(new JsonArray(Local(unicode[0]), Local(unicode[1])), unicode, Source.Uid).Single();
        TestAssert.That(unicodePlan.KeepUid == "\uE000" && unicodePlan.RemoveUid == "\U00010000", "Unicode survivor choice differs from Python/UTF-8 order.");
        var kde = resources.Select(item => item with { Text = item.Text.Replace("VERSION:2.0\r\n", "VERSION:2.0\r\nX-KDE-ICAL-IMPLEMENTATION-VERSION:1.0\r\n") }).ToArray();
        TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(local, kde, Source.Uid).Count == 1, "Known KCalendarCore serializer marker blocked cleanup.");
        TestAssert.That(CalendarBirthdayCleanup.PlanCleanup(local, [kde[0], kde[1] with { Text = kde[1].Text.Replace("IMPLEMENTATION-VERSION:1.0", "IMPLEMENTATION-VERSION:2.0") }], Source.Uid).Count == 0, "Unknown serializer semantics were discarded.");
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
        await RuntimeAsync(bridge: true);
        await RuntimeAsync(bridge: true, conflict: true);
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

    private static async Task RuntimeAsync(bool crash = false, bool conflict = false, bool weakEtag = false, bool bridge = false)
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-birthday135-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var protector = new Protector();
            var source = bridge ? Source with { Uid = "thunderbird-calendar:synthetic-profile:calendar" } : Source;
            var journal = new NextcloudSyncJournal(Path.Combine(root, "sync"), protector);
            var archive = journal.BirthdayArchive(source.Uid, "epoch");
            var remote = new Dictionary<string, NextcloudDavObject> { ["original"] = Resource("original"), ["copy"] = Resource("copy") };
            if (weakEtag) remote["copy"] = remote["copy"] with { ETag = "W/\"weak\"" };
            var items = new JsonArray(Local(remote["original"], sourceUid: source.Uid), Local(remote["copy"], sourceUid: source.Uid));
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
            await using var relay = bridge ? new BridgeRelay(source, http) : null;
            using var client = bridge ? ThunderbirdBridge.CreateClient(source, journal, new string('b', 64), relay!.Name)
                : new NextcloudDavClient(settings, http);
            var engine = new NextcloudCalendarSync(client, archive);
            var first = await engine.SyncAsync(source, [], items, [], 0, true, CancellationToken.None);
            TestAssert.That(deletes == 0 && !archive.Exists && first.Jahrestage.Count == 2, "Additive first run deleted birthdays.");
            NextcloudCalendarResult? result = null;
            try { result = await engine.SyncAsync(source, [], items, [], 1, false, CancellationToken.None); }
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
                engine = new NextcloudCalendarSync(client, journal.BirthdayArchive(source.Uid, "epoch"));
                result = await engine.SyncAsync(source, [], items, [], 1, false, CancellationToken.None);
            }
            TestAssert.That(result is not null && deletes == 1 && remote.Count == 1 && result.Jahrestage.Count == 2 &&
                result.Jahrestage.OfType<JsonObject>().All(item => ContactFields.Text(item, "uid") == "original"), "Cleanup did not retain the original series and rebind both local aliases.");
            TestAssert.That(ContactFields.Source(result!.Jahrestage[1]!.AsObject(), "eds:other")?["id"]?.GetValue<string>() == "keep-other-copy", "Cleanup changed another source.");
            journal.Delete();
            TestAssert.That(archive.Exists, "Ordinary transaction completion removed cleanup proof.");
            var replay = await engine.SyncAsync(source, [], result.Jahrestage, [], 2, false, CancellationToken.None);
            TestAssert.That(deletes == 1 && replay.Exported == 0 && replay.Updated == 0, "Replay recreated or rewrote a birthday.");
            remote["original"] = remote["original"] with { Text = remote["original"].Text.Replace("SUMMARY:Synthetic", "SUMMARY:Remote changed"), ETag = "\"v2\"" };
            var updated = await engine.SyncAsync(source, [], replay.Jahrestage, [], 3, false, CancellationToken.None);
            TestAssert.That(updated.Jahrestage.OfType<JsonObject>().All(item => ContactFields.Text(item, "name") == "Remote changed"), "Remote survivor update did not reach both aliases.");
            using (archive.Acquire())
            {
                var rejected = false;
                try { using var second = archive.Acquire(); } catch (IOException) { rejected = true; }
                TestAssert.That(rejected, "Cleanup allowed concurrent archive owners.");
            }
            TestAssert.That(!journal.BirthdayArchive(source.Uid, "other-epoch").Exists, "Restore epoch reused a cleanup archive.");
            if (bridge)
            {
                var other = source.Uid.Replace("synthetic-profile", "other-profile");
                TestAssert.That(!journal.BirthdayArchive(other, "epoch").Exists &&
                    CalendarBirthdayCleanup.PlanCleanup(items, remote.Values.ToArray(), other).Count == 0,
                    "Another Thunderbird profile adopted the cleanup binding.");
            }
        }
        finally { Directory.Delete(root, true); }
    }

    internal static async Task<int> RunBridgeLiveAsync()
    {
        var pipe = Environment.GetEnvironmentVariable("MAGNOLIE_BIRTHDAY_TEST_PIPE") ?? "";
        var expected = new Uri(Environment.GetEnvironmentVariable("MAGNOLIE_BIRTHDAY_TEST_CALENDAR") ?? "");
        if (!pipe.StartsWith("magnolie-bridge137-", StringComparison.Ordinal) || expected.Scheme != "https" ||
            expected.IdnHost != "magnolie-nextcloud-test.invalid" ||
            !expected.AbsolutePath.StartsWith("/remote.php/dav/calendars/magnolie-test-", StringComparison.Ordinal) ||
            !expected.Segments[^1].StartsWith("birthday137-", StringComparison.Ordinal))
            throw new InvalidOperationException("An isolated bridge and disposable test calendar are required.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-birthday137-live-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(2));
        try
        {
            NextcloudDavSource? source = null;
            for (var attempt = 0; attempt < 20 && source is null; attempt++)
            {
                try
                {
                    var sources = await ThunderbirdBridge.SourcesAsync(timeout.Token, testPipeName: pipe);
                    source = sources.SingleOrDefault(item => item.Kind == "calendar" && item.Href == expected);
                }
                catch (ThunderbirdBridgeException) when (!timeout.IsCancellationRequested) { }
                if (source is null) await Task.Delay(750, timeout.Token);
            }
            if (source is null) throw new InvalidOperationException("The isolated browser source did not become ready.");
            var journal = new NextcloudSyncJournal(Path.Combine(root, "journal"));
            var archive = journal.BirthdayArchive(source.Uid, "synthetic-live-epoch");
            using var client = ThunderbirdBridge.CreateClient(source, journal, new string('c', 64), pipe);
            TestAssert.That((await client.ReadCalendarAsync(source, timeout.Token)).Count == 0, "The test calendar was not empty.");
            var prefix = "birthday137-" + Guid.NewGuid().ToString("N") + "-";
            try
            {
                foreach (var suffix in new[] { "original", "copy", "distinct-a", "distinct-b" })
                {
                    var text = Event(suffix, trigger: suffix == "distinct-b" ? "-PT30M" : "-PT10M")
                        .Replace("UID:" + suffix + "\r\n", "UID:" + prefix + suffix + "\r\n")
                        .Replace("BEGIN:VEVENT\r\n", "BEGIN:VEVENT\r\nDTSTAMP:20261010T000000Z\r\n");
                    await client.CreateAsync(source, prefix + suffix, ".ics", "text/calendar", text, timeout.Token);
                }
                var before = await client.ReadCalendarAsync(source, timeout.Token);
                var local = new JsonArray(before.Select(resource => (JsonNode)Local(resource,
                    CalendarBirthdayCleanup.Index([resource]).Keys.Single().Contains("distinct-", StringComparison.Ordinal) ? "two" : "one", source.Uid)).ToArray());
                var writes = 0;
                client.BeforeMutation = () => { writes++; TestAssert.That(archive.Exists, "Live DELETE preceded the protected archive."); return Task.CompletedTask; };
                var engine = new NextcloudCalendarSync(client, archive);
                var result = await engine.SyncAsync(source, [], local, [], 1, false, timeout.Token);
                var after = await client.ReadCalendarAsync(source, timeout.Token);
                TestAssert.That(writes == 1 && after.Count == 3 && before.Count == 4 && after.All(resource => before.Contains(resource)),
                    "Live bridge changed unrelated bytes/ETags or did not delete exactly one duplicate.");
                TestAssert.That(result.Jahrestage.OfType<JsonObject>().Where(item => ContactFields.Text(item, "kontaktId") == "one")
                    .All(item => ContactFields.Text(item, "uid") == prefix + "original"), "Live bridge lost survivor identity.");
                writes = 0;
                var replay = await engine.SyncAsync(source, [], result.Jahrestage, [], 2, false, timeout.Token);
                var repeated = await client.ReadCalendarAsync(source, timeout.Token);
                TestAssert.That(writes == 0 && repeated.Count == 3 && repeated.All(after.Contains), "Live bridge replay rewrote the calendar.");
                Console.WriteLine("THUNDERBIRD BIRTHDAY137 LIVE PASS: 4 created, 1 duplicate removed, 3 unchanged survivors, aliases rebound, replay 0 writes");
                return 0;
            }
            finally
            {
                client.BeforeMutation = null;
                using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                foreach (var resource in await client.ReadCalendarAsync(source, cleanup.Token))
                {
                    var uids = CalendarBirthdayCleanup.Index([resource]).Keys;
                    if (uids.Count == 1 && uids.Single().StartsWith(prefix, StringComparison.Ordinal))
                        await client.DeleteAsync(resource.Href, resource.ETag, cleanup.Token);
                }
            }
        }
        finally
        {
            using var shutdown = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            try { await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "shutdown" }, shutdown.Token, managed: true, testPipeName: pipe); }
            catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException) { }
            Directory.Delete(root, true);
        }
    }

    private sealed class BridgeRelay : IAsyncDisposable
    {
        internal string Name { get; } = "magnolie-birthday-bridge-" + Guid.NewGuid().ToString("N");
        private readonly CancellationTokenSource stop = new();
        private readonly Task run;
        internal BridgeRelay(NextcloudDavSource source, HttpClient provider)
        {
            run = Task.Run(async () =>
            {
                while (!stop.IsCancellationRequested)
                {
                    using var pipe = new NamedPipeServerStream(Name, PipeDirection.InOut, 1,
                        PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                    await pipe.WaitForConnectionAsync(stop.Token);
                    var request = JsonNode.Parse(await ThunderbirdBridge.ReadFrameAsync(pipe, ThunderbirdBridge.MaximumRequestBytes, stop.Token))!.AsObject();
                    TestAssert.That(request["source"]?.GetValue<string>() == source.Uid && request["op"]?.GetValue<string>() == "http", "Bridge lost its profile-bound source.");
                    using var message = new HttpRequestMessage(new HttpMethod(request["method"]!.GetValue<string>()), request["url"]!.GetValue<string>());
                    foreach (var header in request["headers"]!.AsObject())
                    {
                        TestAssert.That(header.Key is "Depth" or "If-Match" or "If-None-Match", "Credentials crossed the bridge.");
                        message.Headers.TryAddWithoutValidation(header.Key, header.Value!.GetValue<string>());
                    }
                    message.Content = new StringContent(request["body"]!.GetValue<string>());
                    using var response = await provider.SendAsync(message, stop.Token);
                    var reply = new JsonObject { ["version"] = 1, ["id"] = request["id"]!.DeepClone(), ["ok"] = true,
                        ["status"] = (int)response.StatusCode, ["body"] = await response.Content.ReadAsStringAsync(stop.Token),
                        ["etag"] = response.Headers.ETag?.ToString() ?? "" };
                    await ThunderbirdBridge.WriteFrameAsync(pipe, JsonSerializer.SerializeToUtf8Bytes(reply), ThunderbirdBridge.MaximumResponseBytes, stop.Token);
                }
            });
        }
        public async ValueTask DisposeAsync()
        {
            stop.Cancel();
            try { await run; } catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
            stop.Dispose();
        }
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
