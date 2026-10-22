using System.Globalization;
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

    internal static async Task RunAsync()
    {
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
    }
}
