using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class CycleCalendar
{
    internal sealed record Statistics(string[] Starts, int[] Intervals, int? Length, string? Predicted, int? Baseline, int? Latest);
    private static JsonElement Child(JsonElement obj, string key) => obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(key, out var value) ? value : default;
    private static string Text(JsonElement obj, string key) => Child(obj, key) is var value && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
    private static bool Enabled(JsonElement obj, string key) => Child(obj, key).ValueKind == JsonValueKind.True;
    private static int Number(JsonElement obj, string key, int fallback, int minimum) => Child(obj, key) is var value && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number) && number >= minimum && number <= 30 ? number : fallback;
    private static int? Median(IEnumerable<int> values)
    {
        var valid = values.Where(value => value is >= 14 and <= 60).TakeLast(12).Order().ToArray();
        return valid.Length < 2 ? null : (int)Math.Round((valid[(valid.Length - 1) / 2] + valid[valid.Length / 2]) / 2d, MidpointRounding.AwayFromZero);
    }

    internal static Statistics Estimate(JsonElement root)
    {
        var markers = Child(root, "zyklusmarker");
        var ids = markers.ValueKind == JsonValueKind.Array ? markers.EnumerateArray()
            .Where(marker => Text(marker, "art") is "bleeding-light" or "bleeding-medium" or "bleeding-heavy")
            .Select(marker => Text(marker, "id")).ToHashSet(StringComparer.Ordinal) : [];
        var dates = new SortedSet<DateOnly>();
        var marks = Child(root, "tagmarken");
        if (marks.ValueKind == JsonValueKind.Array) foreach (var mark in marks.EnumerateArray())
        {
            var selected = Child(mark, "zyklusIds");
            if (selected.ValueKind == JsonValueKind.Array && selected.EnumerateArray().Any(value => value.ValueKind == JsonValueKind.String && ids.Contains(value.GetString()!)) &&
                DateOnly.TryParseExact(Text(mark, "datum"), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date)) dates.Add(date);
        }
        var starts = new List<DateOnly>(); DateOnly? previous = null;
        foreach (var day in dates) { if (previous is null || day.DayNumber - previous.Value.DayNumber > 3) starts.Add(day); previous = day; }
        var intervals = starts.Skip(1).Select((day, index) => day.DayNumber - starts[index].DayNumber).ToArray();
        var length = Median(intervals); string? predicted = null;
        if (length is not null) { try { predicted = starts[^1].AddDays(length.Value).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture); } catch (ArgumentOutOfRangeException) { } }
        return new(starts.Select(day => day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).ToArray(), intervals, length, predicted,
            Median(intervals.SkipLast(1)), intervals.Length == 0 ? null : intervals[^1]);
    }

    internal static JsonObject[] Reminders(JsonElement root)
    {
        var calendar = Child(Child(root, "einstellungen"), "kalender");
        if (!Enabled(calendar, "zykluskalenderAn")) return [];
        var options = Child(calendar, "zyklusErinnerungen");
        if (!Enabled(options, "prognose") && !Enabled(options, "abweichung")) return [];
        var stats = Estimate(root); var result = new List<JsonObject>();
        JsonObject Reminder(string id, string date, string title, int lead) => new() {
            ["id"] = id, ["datum"] = date, ["zeit"] = "08:00", ["titel"] = NativeLocalization.Gettext(title),
            ["standardErinnerung"] = false, ["individuelleErinnerungTage"] = lead };
        if (Enabled(options, "prognose") && stats.Predicted is not null)
            result.Add(Reminder("cycle-estimate:" + stats.Starts[^1] + ":" + stats.Predicted, stats.Predicted, "Estimated next period", Number(options, "vorlauf", 1, 0)));
        if (Enabled(options, "abweichung") && stats.Baseline is not null && Math.Abs(stats.Latest!.Value - stats.Baseline.Value) >= Number(options, "abweichungTage", 7, 1))
            result.Add(Reminder("cycle-deviation:" + stats.Starts[^1] + ":" + stats.Latest, stats.Starts[^1], "Cycle interval changed", 0));
        return result.ToArray();
    }
}
