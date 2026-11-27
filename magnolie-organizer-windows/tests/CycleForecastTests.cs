using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

// Pure production-estimator checks also runnable without the Windows GUI/installer.
internal static class CycleForecastTests
{
    internal static int Checks { get; private set; }
    private static void Check(bool condition, string message) { Checks++; TestAssert.That(condition, message); }
    private static string Iso(DateOnly day) => day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    private static JsonObject Profile(IEnumerable<string> dates) => new() {
        ["zyklusmarker"] = new JsonArray(new JsonObject { ["id"] = "light", ["art"] = "bleeding-light", ["name"] = "Renamed" },
            new JsonObject { ["id"] = "other", ["art"] = "ovulation", ["name"] = "Bleeding" }),
        ["tagmarken"] = new JsonArray(dates.Select(day => (JsonNode)new JsonObject { ["datum"] = day, ["zyklusIds"] = new JsonArray("light") }).ToArray()),
        ["einstellungen"] = new JsonObject { ["regional"] = new JsonObject { ["timeZone"] = "UTC" },
            ["kalender"] = new JsonObject { ["zykluskalenderAn"] = true, ["zyklusErinnerungen"] = new JsonObject {
                ["prognose"] = true, ["abweichung"] = true, ["vorlauf"] = 2, ["abweichungTage"] = 7 } } } };
    private static string[] Dates(int[] intervals, string start = "2026-01-01")
    {
        var days = new List<DateOnly> { DateOnly.ParseExact(start, "yyyy-MM-dd", CultureInfo.InvariantCulture) };
        foreach (var interval in intervals) days.Add(days[^1].AddDays(interval));
        return days.Select(Iso).ToArray();
    }
    private static CycleCalendar.Statistics Estimate(JsonNode? root, string asOf)
    {
        using var doc = JsonDocument.Parse(root?.ToJsonString() ?? "null");
        return CycleCalendar.Estimate(doc.RootElement, asOf);
    }
    private static JsonObject[] Reminders(JsonNode? root, string asOf)
    {
        using var doc = JsonDocument.Parse(root?.ToJsonString() ?? "null");
        return CycleCalendar.Reminders(doc.RootElement, asOf);
    }

    private static void SetPause(JsonObject data, string reason, string start, string? until, string? resumed = null)
    {
        var pause = new JsonObject { ["reason"] = reason, ["startedOn"] = start, ["until"] = until };
        if (resumed is not null) pause["resumedOn"] = resumed;
        data["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!["pause"] = pause;
    }

    private static void PauseChecks()
    {
        var data = Profile(["2026-01-01", "2026-01-29", "2026-02-26", "2026-04-09"]);
        SetPause(data, "pregnancy", "2026-03-01", "2026-12-01");
        foreach (var today in new[] { "2026-03-01", "2026-05-01", "2026-12-01" })
        {
            var result = Estimate(data, today);
            Check(result.Paused && result.Reason == "paused" && result.PauseReason == "pregnancy", "Bounded pause active " + today);
            Check(result.PauseStart == "2026-03-01" && result.PauseUntil == "2026-12-01" && result.RestartFrom == "2026-12-02", "Bounded pause metadata " + today);
            Check(result.Starts.Length == 0 && result.Predicted is null && result.Baseline is null && Reminders(data, today).Length == 0, "Pause suppresses history and reminders " + today);
        }
        var expired = Estimate(data, "2026-12-02");
        Check(!expired.Paused && expired.Reason == "restart" && !expired.Stale && Reminders(data, "2026-12-02").Length == 0, "No stale pre-pause alarms after expiry");
        foreach (var reason in new[] { "pregnancy", "breastfeeding", "medication", "menopause", "other" })
        foreach (var omitUntil in new[] { false, true })
        {
            data = Profile(["2026-01-01", "2026-01-29", "2026-02-26", "9999-12-31"]);
            SetPause(data, reason, "2026-03-01", null);
            if (omitUntil) data["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!["pause"]!.AsObject().Remove("until");
            var result = Estimate(data, "2026-11-26");
            Check(result.Paused && result.Reason == "paused" && result.PauseReason == reason && result.PauseUntil is null && result.RestartFrom is null, "Indefinite pause " + reason + omitUntil);
            Check(result.Starts.Length == 0 && result.FutureIgnored == 0 && Reminders(data, "2026-11-26").Length == 0, "Indefinite pause ignores all history/future dates " + reason + omitUntil);
        }
        data = Profile(["2026-01-01", "2026-01-29", "2026-02-26", "2026-04-09", "2026-04-10", "2026-05-08", "2026-06-05"]);
        SetPause(data, "pregnancy", "2026-03-01", "2026-12-01", "2026-04-10");
        var first = Estimate(data, "2026-04-10");
        Check(!first.Paused && first.Reason == "restart" && first.Starts.SequenceEqual(["2026-04-10"]) && first.RestartFrom == "2026-04-10" && first.ResumedOn == "2026-04-10", "Manual resume day included, prior observations excluded");
        Check(first.FutureIgnored == 2 && first.Baseline is null, "Post-resume future count and empty baseline");
        var ready = Estimate(data, "2026-06-05");
        Check(ready.Starts.SequenceEqual(["2026-04-10", "2026-05-08", "2026-06-05"]) && ready.Predicted == "2026-07-03" && ready.Reason == "ready" && ready.Baseline is null && Reminders(data, "2026-06-05").Length == 1, "Three new starts establish independent history");
        SetPause(data, "menopause", "2026-03-01", null, "2026-04-10");
        Check(Estimate(data, "2026-06-05").Predicted == "2026-07-03", "Indefinite pause can be manually resumed");
        foreach (var value in new[] { "2026-05-01", "2026-02-28", "2026-02-30", "" })
        {
            SetPause(data, "medication", "2026-03-01", null, value);
            var result = Estimate(data, "2026-04-10");
            Check(result.Paused && result.ResumedOn is null && result.RestartFrom is null && result.Starts.Length == 0, "Future/invalid resume is ignored " + value);
        }
        foreach (var value in new JsonNode?[] { JsonValue.Create(true), new JsonObject(), null })
        {
            SetPause(data, "medication", "2026-03-01", null);
            data["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!["pause"]!["resumedOn"] = value;
            Check(Estimate(data, "2026-04-10").Paused, "Wrong-type resume is ignored");
        }
        data = Profile(["2026-01-01", "2026-01-29", "2026-02-26", "2026-03-01", "2026-12-01", "2026-12-02", "2026-12-30", "2027-01-27"]);
        SetPause(data, "pregnancy", "2026-03-01", "2026-12-01");
        ready = Estimate(data, "2027-01-27");
        Check(ready.Starts.SequenceEqual(["2026-12-02", "2026-12-30", "2027-01-27"]) && ready.Predicted == "2027-02-24" && ready.ExcludedIntervals == 0 && ready.Baseline is null && Reminders(data, "2027-01-27").Length == 1, "Expired pause never compares against pre-pause cycles");
        data["tagmarken"] = Profile(["2026-12-02", "2026-12-12"])["tagmarken"]!.DeepClone();
        Check(Estimate(data, "2026-12-12").Reason == "gap", "Post-restart gap reason remains specific");
        data = Profile(["2026-01-01", "2026-01-29", "2026-02-26"]);
        var baseline = JsonSerializer.Serialize(Estimate(data, "2026-03-01"));
        foreach (var invalid in new JsonNode?[] {
            null, new JsonArray(), JsonValue.Create("pause"),
            new JsonObject { ["reason"] = "unknown", ["startedOn"] = "2026-01-01" },
            new JsonObject { ["reason"] = "hormonal-treatment", ["startedOn"] = "2026-01-01" },
            new JsonObject { ["reason"] = "pregnancy", ["startedOn"] = "2026-02-30" },
            new JsonObject { ["reason"] = "pregnancy", ["startedOn"] = "2026-01-01", ["until"] = "" },
            new JsonObject { ["reason"] = "pregnancy", ["startedOn"] = "2026-01-01", ["until"] = true },
            new JsonObject { ["reason"] = "pregnancy", ["startedOn"] = "2026-01-01", ["until"] = "2025-12-31" },
            new JsonObject { ["reason"] = "pregnancy", ["startedOn"] = "2026-04-01", ["until"] = null } })
        {
            data["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!["pause"] = invalid;
            Check(JsonSerializer.Serialize(Estimate(data, "2026-03-01")) == baseline, "Invalid/not-started pause has no effect");
        }
        var empty = Estimate(Profile([]), "2026-03-01");
        Check(!empty.Paused && empty.PauseReason is null && empty.PauseStart is null && empty.PauseUntil is null && empty.ResumedOn is null && empty.RestartFrom is null, "Unpaused fields always exist");
        data = Profile(["9999-11-02", "9999-11-30", "9999-12-28"]);
        SetPause(data, "other", "9999-12-01", "9999-12-31");
        var edge = Estimate(data, "9999-12-31");
        Check(edge.Paused && edge.RestartFrom is null && edge.Starts.Length == 0, "Pause end overflow suppressed");
        SetPause(data, "other", "9999-12-01", "9999-12-31", "9999-12-28");
        edge = Estimate(data, "9999-12-31");
        Check(!edge.Paused && edge.RestartFrom == "9999-12-28" && edge.Starts.SequenceEqual(["9999-12-28"]) && edge.Reason == "restart", "Year-edge resume uses explicit observed date");
    }

    internal static Task RunAsync()
    {
        Checks = 0;
        var data = Profile(Dates([28, 28]));
        var stats = Estimate(data, "2026-03-01");
        Check(stats.Length == 28 && stats.Predicted == "2026-03-26" && stats.WindowStart == "2026-03-24" && stats.WindowEnd == "2026-03-28", "Regular range/median");
        Check(stats.Reason == "ready" && stats.UsedIntervals.SequenceEqual([28, 28]), "Usable interval history");
        Check(Reminders(data, "2026-03-01")[0]["id"]!.GetValue<string>() == "cycle-estimate:2026-02-26:2026-03-26", "Stable previous reminder identity");
        foreach (var interval in new[] { 14, 24, 28, 35, 45, 60 })
        {
            var dates = Dates([interval, interval]);
            stats = Estimate(Profile(dates), dates[^1]);
            Check(stats.Length == interval && stats.Predicted == Iso(DateOnly.Parse(dates[^1], CultureInfo.InvariantCulture).AddDays(interval)), "Individual start-to-start length " + interval);
        }
        foreach (var gap in new[] { 4, 13, 61, 365 })
        {
            var dates = Dates([28, 28, gap]);
            stats = Estimate(Profile(dates), dates[^1]);
            Check(stats.Length is null && stats.UsedIntervals.Length == 0 && stats.Reason == "gap" && stats.ExcludedIntervals == 1 && stats.Baseline == 28, "Do not bridge discontinuity " + gap);
            dates = Dates([28, 28, gap, 30, 32]);
            stats = Estimate(Profile(dates), dates[^1]);
            Check(stats.Length == 31 && stats.UsedIntervals.SequenceEqual([30, 32]) && stats.Baseline is null && stats.Reason == "ready", "Fresh history after discontinuity " + gap);
        }
        var recent = Dates(new[] { 14, 14, 14 }.Concat(Enumerable.Range(0, 6).SelectMany(_ => new[] { 28, 29 })).ToArray(), "2024-01-01");
        stats = Estimate(Profile(recent), recent[^1]);
        Check(stats.Length == 29 && stats.UsedIntervals.Length == 12 && stats.Intervals.Length == 15, "Half-up rounding and latest twelve only");
        foreach (var (day, overdue) in new[] { ("2026-03-23", 0), ("2026-03-24", 0), ("2026-03-26", 0), ("2026-03-28", 0), ("2026-03-29", 1), ("2026-04-28", 31) })
        {
            stats = Estimate(data, day);
            Check(stats.Predicted == "2026-03-26" && stats.WindowEnd == "2026-03-28" && stats.OverdueDays == overdue, "Do not roll estimate forward " + day);
        }
        Check(!Estimate(data, "2026-06-26").Stale && Estimate(data, "2026-06-27").Stale, "Exact stale boundary");
        Check(Estimate(data, "2026-06-27").Predicted == "2026-03-26" && Reminders(data, "2026-06-27").Length == 0, "Keep past estimate, suppress stale notice");
        var longDates = Dates([60, 60]); var anchor = DateOnly.Parse(longDates[^1], CultureInfo.InvariantCulture);
        Check(!Estimate(Profile(longDates), Iso(anchor.AddDays(124))).Stale && Estimate(Profile(longDates), Iso(anchor.AddDays(125))).Stale, "Long interval stale boundary");
        var future = Profile(Dates([28, 28]).Concat(new[] { "2026-03-26", "2026-03-26", "2027-01-01" }));
        stats = Estimate(future, "2026-03-01");
        Check(stats.FutureIgnored == 2 && stats.Starts[^1] == "2026-02-26" && stats.Predicted == "2026-03-26", "Future dates ignored and deduplicated");
        stats = Estimate(future, "2026-03-26");
        Check(stats.FutureIgnored == 1 && stats.Predicted == "2026-04-23" && stats.OverdueDays == 0, "New documented start replaces overdue estimate");
        foreach (var bad in new[] { "", "2026-2-01", "2026-02-30", "2026-13-01", "0000-01-01", "20260101", "2026-W01-1", "2026-01-01T00:00:00Z", "２０２６-01-01", "2026-01-01\n" })
        {
            Check(Estimate(Profile([bad]), "2026-03-01").Starts.Length == 0, "Invalid marked date " + bad);
            using var doc = JsonDocument.Parse("{}");
            TestAssert.Throws<ArgumentException>(() => CycleCalendar.Estimate(doc.RootElement, bad), "Invalid as-of should throw " + bad);
            Checks++;
        }
        foreach (var text in new[] { "null", "[]", "1", "true", "\"bad\"", "{\"zyklusmarker\":{}}", "{\"tagmarken\":[null,[],1]}",
            "{\"zyklusmarker\":[null,{\"id\":\"\",\"art\":\"bleeding-light\"},{\"id\":\"x\",\"art\":[]}],\"tagmarken\":[{\"datum\":\"2026-01-01\",\"zyklusIds\":[\"\",\"x\"]}]}",
            "{\"einstellungen\":{\"kalender\":{\"zyklusErinnerungen\":[]}}}" })
        {
            var malformed = JsonNode.Parse(text);
            Check(Estimate(malformed, "2026-03-01").Predicted is null && Reminders(malformed, "2026-03-01").Length == 0, "Malformed container");
        }
        var bridged = Profile(Dates([28, 28]).Concat(new[] { "2026-02-27", "2026-03-01", "2026-03-02" }));
        stats = Estimate(bridged, "2026-03-02");
        Check(stats.Starts.Length == 3 && stats.RecordedRun == 2 && stats.LastBleeding == "2026-03-02", "Missing day is not a recorded bleeding day");
        var eight = Profile(Dates([28, 28]).Concat(Enumerable.Range(0, 8).Select(n => Iso(new DateOnly(2026, 2, 26).AddDays(n)))));
        Check(Estimate(eight, "2026-03-05").RecordedRun == 8, "Eight consecutive recorded days");
        eight["tagmarken"]!.AsArray().Add(new JsonObject { ["datum"] = "2026-03-26", ["zyklusIds"] = new JsonArray("light") });
        Check(Estimate(eight, "2026-03-26").RecordedRun == 1, "Latest episode resets recorded run");
        var ongoing = Profile(Dates([14, 14]).Concat(Enumerable.Range(1, 12).Select(n => Iso(new DateOnly(2026, 1, 29).AddDays(n)))));
        stats = Estimate(ongoing, "2026-02-10");
        Check(stats.Reason == "ongoing" && stats.Length == 14 && stats.Predicted is null && stats.WindowStart is null && stats.WindowEnd is null && Reminders(ongoing, "2026-02-10").Length == 0, "Do not forecast over observed bleeding");
        foreach (var (dates, expected) in new[] {
            (new[] { "2028-01-01", "2028-01-29", "2028-02-26" }, "2028-03-25"),
            (new[] { "2100-01-01", "2100-01-29", "2100-02-26" }, "2100-03-26"),
            (new[] { "2026-11-10", "2026-12-08", "2027-01-05" }, "2027-02-02"),
            (new[] { "0001-01-01", "0001-01-29", "0001-02-26" }, "0001-03-26") })
            Check(Estimate(Profile(dates), dates[^1]).Predicted == expected, "Gregorian boundary " + expected);
        stats = Estimate(Profile(["9999-11-02", "9999-11-30", "9999-12-28"]), "9999-12-31");
        Check(stats.Reason == "range" && stats.Predicted is null && stats.WindowStart is null && stats.WindowEnd is null, "Upper calendar boundary");
        foreach (var (zone, expected) in new[] { ("UTC", "2026-11-26"), ("Europe/Berlin", "2026-11-26"), ("America/Los_Angeles", "2026-11-25"), ("Pacific/Apia", "2026-11-26"), ("Pacific/Kiritimati", "2026-11-26"), ("Z", "2026-11-26") })
        {
            using var doc = JsonDocument.Parse(new JsonObject { ["einstellungen"] = new JsonObject { ["regional"] = new JsonObject { ["timeZone"] = zone } } }.ToJsonString());
            Check(CycleCalendar.OrganizerToday(doc.RootElement, new DateTimeOffset(2026, 11, 26, 0, 30, 0, TimeSpan.Zero)) == expected, "Book-local date " + zone);
        }
        using (var winnipeg = JsonDocument.Parse("{\"einstellungen\":{\"regional\":{\"timeZone\":\"America/Winnipeg\"}}}"))
            Check(CycleCalendar.OrganizerToday(winnipeg.RootElement, new DateTimeOffset(2026, 11, 26, 5, 30, 0, TimeSpan.Zero)) == "2026-11-26", "Use bound 2026egtz date, not host Winnipeg rules");
        foreach (var zone in new[] { "UTC", "Europe/Berlin", "America/New_York", "Pacific/Apia" })
        {
            var spring = Profile(["2026-02-01", "2026-03-01", "2026-03-29"]);
            spring["einstellungen"]!["regional"]!["timeZone"] = zone;
            Check(Estimate(spring, "2026-04-01").Predicted == "2026-04-26", "Spring calendar days " + zone);
            var autumn = Profile(["2026-08-30", "2026-09-27", "2026-10-25"]);
            autumn["einstellungen"]!["regional"]!["timeZone"] = zone;
            Check(Estimate(autumn, "2026-10-26").Predicted == "2026-11-22", "Autumn calendar days " + zone);
        }
        foreach (var (length, expected) in new[] { (34, 1), (35, 2) })
        {
            var dates = Dates([28, 28, length]);
            Check(Reminders(Profile(dates), dates[^1]).Length == expected, "Prior baseline threshold " + length);
        }
        foreach (var raw in new[] { "\"true\"", "1", "{}", "[]", "null" })
        {
            var options = data["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!.AsObject();
            options["prognose"] = JsonNode.Parse(raw); options["abweichung"] = JsonNode.Parse(raw); options["anzeige"] = true;
            Check(Reminders(data, "2026-03-01").Length == 0, "Strict notification opt-in " + raw);
        }
        foreach (var raw in new[] { "true", "-1", "31", "\"7\"", "3.5", "null", "[]", "{}" })
        {
            var optionsRoot = Profile(Dates([28, 28, 35]));
            var options = optionsRoot["einstellungen"]!["kalender"]!["zyklusErinnerungen"]!.AsObject();
            options["vorlauf"] = JsonNode.Parse(raw); options["abweichungTage"] = JsonNode.Parse(raw);
            var notices = Reminders(optionsRoot, "2026-04-02");
            Check(notices.Length == 2 && notices[0]["individuelleErinnerungTage"]!.GetValue<int>() == 1, "Safe numeric fallback " + raw);
        }
        var rng = new Random(803);
        for (var iteration = 0; iteration < 250; iteration++)
        {
            var intervals = Enumerable.Range(0, rng.Next(2, 23)).Select(_ => rng.Next(14, 61)).ToArray();
            var dates = Dates(intervals, "2000-01-01");
            var generated = Profile(dates); var before = generated.ToJsonString();
            stats = Estimate(generated, dates[^1]);
            var shuffled = Profile(dates.Concat(dates).OrderBy(_ => rng.Next()));
            shuffled["tagmarken"]!.AsArray().Add(new JsonObject { ["datum"] = "1999-01-01", ["zyklusIds"] = new JsonArray("other") });
            Check(generated.ToJsonString() == before && JsonSerializer.Serialize(Estimate(shuffled, dates[^1])) == JsonSerializer.Serialize(stats), "Permutation, duplication, irrelevant markers, immutability " + iteration);
            Check(string.CompareOrdinal(stats.WindowStart, stats.Predicted) <= 0 && string.CompareOrdinal(stats.Predicted, stats.WindowEnd) <= 0 && stats.UsedIntervals.SequenceEqual(intervals.TakeLast(12)), "Range/history invariant " + iteration);
        }
        PauseChecks();
        var vectorPath = Path.Combine(TestSource.Root("contracts/cycle-forecast-vectors.json"), "contracts/cycle-forecast-vectors.json");
        var vectors = JsonNode.Parse(File.ReadAllText(vectorPath))!["cases"]!.AsArray();
        var camelCase = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
        foreach (var item in vectors)
        {
            var result = JsonSerializer.SerializeToNode(Estimate(item!["data"], item["asOf"]!.GetValue<string>()), camelCase)!.AsObject();
            foreach (var expected in item["expected"]!.AsObject())
                Check(JsonNode.DeepEquals(result[expected.Key], expected.Value), "Shared golden vector " + item["name"] + ": " + expected.Key);
        }
        Console.WriteLine($"Cycle forecast: {Checks} assertions, including 250 generated histories, passed.");
        return Task.CompletedTask;
    }
}
