using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TimeZoneManagementTests
{
    private static JsonObject Settings() => new()
    {
        ["timeZoneManagement"] = "automatic", ["timeZoneDetection"] = "auto",
        ["timeZone"] = "Europe/Berlin", ["timeZoneManual"] = "America/New_York"
    };

    private static void VerifyCalendarRoundtrips()
    {
        var zone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
        foreach (var task in new[] { false, true })
        foreach (var shape in new[] { "utc-fold", "tzid", "floating", "date", "series" })
        {
            var component = task ? "VTODO" : "VEVENT";
            var ending = task ? "DUE" : "DTEND";
            var start = shape switch
            {
                "utc-fold" => "DTSTART:20261101T063047Z",
                "tzid" or "series" => "DTSTART;TZID=America/New_York:20261022T013047",
                "floating" => "DTSTART:20261022T013047",
                _ => "DTSTART;VALUE=DATE:20261022"
            };
            var end = shape switch
            {
                "utc-fold" => ending + ":20261101T073047Z",
                "tzid" or "series" => ending + ";TZID=America/New_York:20261022T023047",
                "floating" => ending + ":20261022T023047",
                _ => ending + ";VALUE=DATE:20261023"
            };
            var recurrence = shape == "series" ? "\r\nRRULE:FREQ=DAILY;COUNT=3\r\nEXDATE;TZID=America/New_York:20261023T013047" : "";
            var text = $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:{component}\r\nUID:owned-{shape}\r\nSUMMARY:Owned zone fixture\r\n{start}\r\n{end}{recurrence}\r\nX-OWNED:keep\r\nEND:{component}\r\nEND:VCALENDAR\r\n";
            for (var round = 0; round < 3; round++)
            {
                var imported = ExchangeCodec.ParseIcs(text, "owned-zone-source", zone);
                var items = task ? imported.Aufgaben : imported.Termine;
                TestAssert.That(items.Count == 1 && items[0]!["icsAnzeigeZeitzone"]!.GetValue<string>() == "America/New_York",
                    "Native import did not store a portable IANA projection zone.");
                using var data = JsonDocument.Parse(items.ToJsonString());
                var exported = ExchangeCodec.WriteIcs(task ? "ics-aufgaben" : "ics-termine", data.RootElement);
                TestAssert.That(exported.Skipped == 0 && exported.Text.Contains(start, StringComparison.Ordinal) &&
                    exported.Text.Contains(end, StringComparison.Ordinal) && exported.Text.Contains("UID:owned-" + shape, StringComparison.Ordinal) &&
                    exported.Text.Contains("X-OWNED:keep", StringComparison.Ordinal) &&
                    (shape != "series" || exported.Text.Contains("EXDATE;TZID=America/New_York:20261023T013047", StringComparison.Ordinal)),
                    "Repeated native ICS roundtrip changed a fold, seconds, floating/DATE semantics, identity or recurrence exclusion.");
                text = exported.Text;
            }
        }
    }

    internal static async Task RunAsync()
    {
        VerifyCalendarRoundtrips();
        using (var envelope = BridgeDispatcherContract.Parse(new JsonObject { ["cmd"] = "zeitzone_erkennen", ["requestId"] = Guid.NewGuid().ToString("D"), ["expectedRegional"] = new JsonObject() }.ToJsonString())) { }
        TestAssert.Throws<InvalidDataException>(() => BridgeDispatcherContract.Parse(new JsonObject { ["cmd"] = "zeitzone_erkennen", ["requestId"] = Guid.NewGuid().ToString("D") }.ToJsonString()),
            "Timezone detection omitted its native-preference source snapshot.");
        var calls = new List<string>();
        foreach (var mode in new[] { "off", "manual" })
        {
            var settings = Settings(); settings["timeZoneManagement"] = mode;
            var sources = new[] { "phone", "gps", "ip", "system" }.ToDictionary(name => name,
                name => (Func<CancellationToken, Task<TimeZoneCandidate?>>)(_ => { calls.Add(name); return Task.FromResult<TimeZoneCandidate?>(new("Asia/Tokyo")); }));
            var observation = await TimeZoneManagement.DetectAsync(settings, sources, CancellationToken.None, 1000000);
            TestAssert.That(calls.Count == 0 && !observation.Automatic && observation.Zone == (mode == "off" ? "Europe/Berlin" : "America/New_York"), "Disabled/manual timezone management queried an automatic source or changed the current zone.");
        }
        var config = Settings(); var before = config.ToJsonString();
        var priority = new Dictionary<string, Func<CancellationToken, Task<TimeZoneCandidate?>>>
        {
            ["phone"] = _ => Task.FromResult<TimeZoneCandidate?>(new("Asia/Tokyo", 999000)),
            ["gps"] = _ => Task.FromResult<TimeZoneCandidate?>(new("Europe/London", 999999)),
            ["ip"] = _ => { calls.Add("ip"); return Task.FromResult<TimeZoneCandidate?>(new("Europe/Berlin")); }
        };
        var phone = await TimeZoneManagement.DetectAsync(config, priority, CancellationToken.None, 1000000);
        TestAssert.That(phone.Source == "phone" && phone.Zone == "Asia/Tokyo" && calls.Count == 0 && config.ToJsonString() == before,
            "An IP/VPN location overrode the fresh own-phone source or detection modified preferences.");
        priority["phone"] = _ => Task.FromResult<TimeZoneCandidate?>(new("Asia/Tokyo", 0));
        var location = await TimeZoneManagement.DetectAsync(config, priority, CancellationToken.None, 1000000);
        TestAssert.That(location.Source == "gps" && location.Zone == "Europe/London", "Stale phone observations overrode a fresh position.");
        config["timeZoneDetection"] = "gps"; priority["gps"] = _ => Task.FromResult<TimeZoneCandidate?>(null);
        var fallback = await TimeZoneManagement.DetectAsync(config, priority, CancellationToken.None, 1000000);
        TestAssert.That(fallback.Fallback && fallback.Source == "manual" && fallback.Zone == "America/New_York" && calls.Count == 0,
            "Selected-source failure used an unselected IP source instead of the manual fallback.");
        var missing = await TimeZoneManagement.FromIpAsync((_, _) => Task.FromResult(JsonNode.Parse("""{"country_code":"US","utc_offset":"-0500"}""")!.AsObject()), CancellationToken.None);
        TestAssert.That(missing is null && TimeZoneManagement.ZoneId("Mars/Olympus") is null && TimeZoneManagement.ZoneId("../../etc/passwd") is null,
            "A country/offset or invalid ID invented an unambiguous IANA zone.");
        var culture = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
            var fetched = new List<string>();
            Task<JsonObject> Fetch(string url, CancellationToken _) { fetched.Add(url); return Task.FromResult(JsonNode.Parse("""{"timezone":"Europe/London"}""")!.AsObject()); }
            var point = await TimeZoneManagement.FromCoordinatesAsync(new(51.5, -.1, 999000), Fetch, CancellationToken.None, 1000000);
            TestAssert.That(point is { Zone: "Europe/London", CapturedMs: 999000 } && fetched.Single().Contains("latitude=51.5&longitude=-0.1", StringComparison.Ordinal),
                "Location lookup lost its observation time or used locale-dependent coordinates.");
            foreach (var invalid in new[] { new TimeZoneLocation(91, 0, 999000), new TimeZoneLocation(51, double.NaN, 999000), new TimeZoneLocation(51, 0, 0) })
            {
                var rejected = false;
                try { await TimeZoneManagement.FromCoordinatesAsync(invalid, Fetch, CancellationToken.None, 1000000); }
                catch (InvalidDataException) { rejected = true; }
                TestAssert.That(rejected && fetched.Count == 1, "Invalid or stale coordinates were sent to the network.");
            }
        }
        finally { CultureInfo.CurrentCulture = culture; }
        var root = Path.Combine(Path.GetTempPath(), "magnolie-timezone-preview-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "regional.json"); var saved = Settings(); saved["timeZoneDetection"] = "phone";
            RegionalSettings.Write(path, JsonSerializer.SerializeToElement(saved));
            var original = RegionalSettings.ReadVerified(path); var image = File.ReadAllBytes(path);
            Task<JsonObject?> Phone(CancellationToken _) => Task.FromResult<JsonObject?>(new JsonObject
            { ["zone"] = "Asia/Tokyo", ["captured_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() });
            var preview = await TimeZoneManagement.RefreshAsync(path, JsonSerializer.SerializeToElement(original), Phone,
                () => true, CancellationToken.None, apply: false);
            TestAssert.That(preview["time_zone"]!.GetValue<string>() == "Asia/Tokyo" && preview["native_changed"]!.GetValue<bool>() == false &&
                JsonNode.DeepEquals(preview["regional"], original) && File.ReadAllBytes(path).AsSpan().SequenceEqual(image),
                "Detection changed the native zone before durable book anchoring.");
            var permitted = true;
            Task<JsonObject?> ChangedSource(CancellationToken token) { permitted = false; return Phone(token); }
            var revoked = false;
            try { await TimeZoneManagement.RefreshAsync(path, JsonSerializer.SerializeToElement(original), ChangedSource,
                () => permitted, CancellationToken.None, apply: false); }
            catch (InvalidOperationException error) when (error.Message == "locked") { revoked = true; }
            TestAssert.That(revoked && File.ReadAllBytes(path).AsSpan().SequenceEqual(image), "Detection ignored the changed native book source.");
        }
        finally { Directory.Delete(root, true); }
    }
}
