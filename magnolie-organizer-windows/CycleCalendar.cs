using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Personal planning rules, not clinical limits. See contracts/cycle-calendar.md.
internal static class CycleCalendar
{
    internal sealed record Statistics(string AsOf, string[] Starts, int[] Intervals, int? Length, string? Predicted,
        int? Baseline, int? Latest, int[] UsedIntervals, int ExcludedIntervals, int FutureIgnored,
        string? LastBleeding, int RecordedRun, string? WindowStart, string? WindowEnd,
        int OverdueDays, bool Stale, string Reason, bool Paused, string? PauseReason,
        string? PauseStart, string? PauseUntil, string? ResumedOn, string? RestartFrom);

    private sealed record PauseContext(bool Paused, string? Reason = null, DateOnly? Start = null,
        DateOnly? Until = null, DateOnly? Resumed = null, DateOnly? Restart = null);

    private static JsonElement Child(JsonElement obj, string key) => obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(key, out var value) ? value : default;
    private static string Text(JsonElement obj, string key) => Child(obj, key) is var value && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
    private static bool Enabled(JsonElement obj, string key) => Child(obj, key).ValueKind == JsonValueKind.True;
    private static int Number(JsonElement obj, string key, int fallback, int minimum) => Child(obj, key) is var value && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) && number >= minimum && number <= 30 ? number : fallback;
    private static string Iso(DateOnly day) => day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    private static bool TryDay(string text, out DateOnly day) => DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out day) && Iso(day) == text;

    internal static string OrganizerToday(JsonElement root, DateTimeOffset? now = null)
    {
        var id = Text(Child(Child(root, "einstellungen"), "regional"), "timeZone");
        if (id == "Z") id = "UTC";
        if (id is "" or "system") id = TimeZoneInfo.Local.Id;
        if (!NormativeTimezones.TryGet(id, out var zone) && TimeZoneInfo.TryConvertWindowsIdToIanaId(id, out var iana))
            _ = NormativeTimezones.TryGet(iana, out zone);
        if (zone is null) throw new TimeZoneNotFoundException("Cycle calendar timezone is unavailable in the bound normative rules.");
        return Iso(DateOnly.FromDateTime(zone.FromUtc((now ?? DateTimeOffset.UtcNow).UtcDateTime)));
    }

    private static int[] RecentIntervals(IEnumerable<int> values) => values.Reverse()
        .TakeWhile(value => value is >= 14 and <= 60).Take(12).Reverse().ToArray();

    private static int? Median(int[] values)
    {
        var sorted = values.Order().ToArray();
        return sorted.Length < 2 ? null : (int)Math.Round((sorted[(sorted.Length - 1) / 2] + sorted[sorted.Length / 2]) / 2d, MidpointRounding.AwayFromZero);
    }

    private static PauseContext ReadPause(JsonElement root, DateOnly today)
    {
        var pause = Child(Child(Child(Child(root, "einstellungen"), "kalender"), "zyklusErinnerungen"), "pause");
        var reason = Text(pause, "reason");
        if (reason is not ("pregnancy" or "breastfeeding" or "medication" or "menopause" or "other") ||
            !TryDay(Text(pause, "startedOn"), out var start) || today < start) return new(false);
        DateOnly? until = null;
        if (Child(pause, "until").ValueKind is not (JsonValueKind.Undefined or JsonValueKind.Null))
        {
            if (!TryDay(Text(pause, "until"), out var end) || end < start) return new(false);
            until = end;
        }
        DateOnly? resumed = TryDay(Text(pause, "resumedOn"), out var day) && day >= start && day <= today ? day : null;
        DateOnly? restart = resumed;
        if (restart is null && until is not null && until != DateOnly.MaxValue) restart = until.Value.AddDays(1);
        return new(resumed is null && (until is null || today <= until.Value), reason, start, until, resumed, restart);
    }

    internal static Statistics Estimate(JsonElement root, string? asOf = null)
    {
        if (!TryDay(asOf ?? OrganizerToday(root), out var today)) throw new ArgumentException("invalid_cycle_date", nameof(asOf));
        var pause = ReadPause(root, today);
        var markers = Child(root, "zyklusmarker");
        var ids = markers.ValueKind == JsonValueKind.Array ? markers.EnumerateArray()
            .Where(marker => Text(marker, "art") is "bleeding-light" or "bleeding-medium" or "bleeding-heavy")
            .Select(marker => Text(marker, "id")).Where(id => id.Length != 0).ToHashSet(StringComparer.Ordinal) : [];
        var dates = new SortedSet<DateOnly>();
        var future = new HashSet<DateOnly>();
        var marks = Child(root, "tagmarken");
        if (marks.ValueKind == JsonValueKind.Array) foreach (var mark in marks.EnumerateArray())
        {
            var selected = Child(mark, "zyklusIds");
            if (selected.ValueKind != JsonValueKind.Array || !selected.EnumerateArray().Any(value => value.ValueKind == JsonValueKind.String && ids.Contains(value.GetString()!)) ||
                !TryDay(Text(mark, "datum"), out var day)) continue;
            if (pause.Reason is not null && (pause.Restart is null || day < pause.Restart.Value)) continue;
            if (day > today) future.Add(day); else dates.Add(day);
        }
        var starts = new List<DateOnly>();
        DateOnly? previous = null;
        var run = 0; var recordedRun = 0;
        foreach (var day in dates)
        {
            var gap = previous is null ? (int?)null : day.DayNumber - previous.Value.DayNumber;
            if (gap is null or > 3) { starts.Add(day); run = recordedRun = 1; }
            else { run = gap == 1 ? run + 1 : 1; recordedRun = Math.Max(recordedRun, run); }
            previous = day;
        }
        var intervals = starts.Skip(1).Select((day, index) => day.DayNumber - starts[index].DayNumber).ToArray();
        var used = RecentIntervals(intervals);
        var length = Median(used);
        var excluded = intervals.Count(value => value is < 14 or > 60);
        var reason = excluded != 0 ? "gap" : pause.Reason is not null ? "restart" : "insufficient";
        string? predicted = null, windowStart = null, windowEnd = null;
        var overdue = 0;
        if (length is not null)
        {
            try
            {
                var prediction = starts[^1].AddDays(length.Value);
                var lower = starts[^1].AddDays(Math.Max(1, used.Min() - 2));
                var upper = starts[^1].AddDays(used.Max() + 2);
                if (previous!.Value >= lower) reason = "ongoing";
                else
                {
                    reason = "ready"; predicted = Iso(prediction); windowStart = Iso(lower); windowEnd = Iso(upper);
                    overdue = Math.Max(0, today.DayNumber - upper.DayNumber);
                }
            }
            catch (ArgumentOutOfRangeException) { reason = "range"; }
        }
        var staleAfter = Math.Max(120, 2 * (used.Length != 0 ? used.Max() + 2 : 60));
        var stale = starts.Count != 0 && today.DayNumber - starts[^1].DayNumber > staleAfter;
        if (pause.Paused) reason = "paused";
        return new(Iso(today), starts.Select(Iso).ToArray(), intervals, length, predicted,
            Median(RecentIntervals(intervals.SkipLast(1))), intervals.Length == 0 ? null : intervals[^1],
            used, excluded, future.Count, previous is null ? null : Iso(previous.Value), recordedRun,
            windowStart, windowEnd, overdue, stale, reason, pause.Paused, pause.Reason,
            pause.Start is null ? null : Iso(pause.Start.Value), pause.Until is null ? null : Iso(pause.Until.Value),
            pause.Resumed is null ? null : Iso(pause.Resumed.Value), pause.Restart is null ? null : Iso(pause.Restart.Value));
    }

    internal static JsonObject[] Reminders(JsonElement root, string? asOf = null)
    {
        var calendar = Child(Child(root, "einstellungen"), "kalender");
        if (!Enabled(calendar, "zykluskalenderAn")) return [];
        var options = Child(calendar, "zyklusErinnerungen");
        if (!Enabled(options, "prognose") && !Enabled(options, "abweichung")) return [];
        var stats = Estimate(root, asOf);
        if (stats.Paused) return [];
        var result = new List<JsonObject>();
        JsonObject Reminder(string id, string date, string title, int lead) => new() {
            ["id"] = id, ["datum"] = date, ["zeit"] = "08:00", ["titel"] = NativeLocalization.Gettext(title),
            ["standardErinnerung"] = false, ["individuelleErinnerungTage"] = lead };
        if (Enabled(options, "prognose") && stats.Predicted is not null && !stats.Stale)
            result.Add(Reminder("cycle-estimate:" + stats.Starts[^1] + ":" + stats.Predicted, stats.Predicted, "Estimated next period", Number(options, "vorlauf", 1, 0)));
        if (Enabled(options, "abweichung") && stats.Baseline is not null && Math.Abs(stats.Latest!.Value - stats.Baseline.Value) >= Number(options, "abweichungTage", 7, 1))
            result.Add(Reminder("cycle-deviation:" + stats.Starts[^1] + ":" + stats.Latest, stats.Starts[^1], "Cycle interval changed", 0));
        return result.ToArray();
    }
}
