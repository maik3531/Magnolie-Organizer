using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal readonly record struct CalendarOccurrence(DateTime Start, DateTime End, DateTime StartUtc, DateTime EndUtc, bool AllDay, string? Summary = null, string? Location = null);

// The raw RFC recurrence set is authoritative for imported entries. The small
// native recurrence model retains its deliberately different month-end policy.
internal static class CalendarRecurrence
{
    // Codec entry points are synchronous. Keep wire dates Gregorian without
    // changing the UI language or leaking a culture change back to their caller.
    internal sealed class WireCulture : IDisposable
    {
        private readonly CultureInfo previous = CultureInfo.CurrentCulture;
        internal WireCulture() => CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;
        public void Dispose() => CultureInfo.CurrentCulture = previous;
    }
    internal readonly record struct Property(string Name, string Value, string[] Parameters)
    {
        internal string Parameter(string name) => Parameters.FirstOrDefault(value => value.StartsWith(name + "=", StringComparison.OrdinalIgnoreCase))?
            [(name.Length + 1)..].Trim('"') ?? "";
    }
    internal readonly record struct Stamp(DateTime Wall, bool AllDay, SourceZone? Zone);
    // TimeZoneInfo is sealed and restricts offsets to whole minutes and +/-14h.
    // Keep embedded observances as transitions instead of approximating them.
    internal sealed record SourceZone(TimeZoneInfo? System, Lazy<EmbeddedZone>? Definition = null)
    {
        public static implicit operator SourceZone(TimeZoneInfo zone) => new(zone);
        internal EmbeddedZone? Embedded => Definition?.Value;
    }
    internal sealed class EmbeddedZone
    {
        private readonly List<(DateTime Start, TimeSpan Before, TimeSpan After, Rule[] Rules, DateTime[] Dates)> observances = new();
        private readonly TimeSpan[] offsets;
        private readonly TimeSpan initial;
        private readonly object gate = new();
        private (DateTime At, TimeSpan Before, TimeSpan After)[] transitions = [];
        private int through;
        internal EmbeddedZone(string[] lines)
        {
            foreach (Match match in Regex.Matches(string.Join("\n", lines), @"(?ims)^BEGIN:(STANDARD|DAYLIGHT)\n(.*?)^END:\1\s*$"))
            {
                var props = match.Groups[2].Value.Split('\n').Select(ParseProperty).OfType<Property>().ToArray();
                Property Get(string name) => props.First(value => value.Name == name);
                TimeSpan Offset(string text)
                {
                    var m = Regex.Match(text, @"^([+-])(\d{2})(\d{2})(\d{2})?$");
                    if (!m.Success) throw new InvalidDataException("Invalid timezone offset.");
                    var h = int.Parse(m.Groups[2].Value); var min = int.Parse(m.Groups[3].Value); var sec = m.Groups[4].Success ? int.Parse(m.Groups[4].Value) : 0;
                    if (h > 23 || min > 59 || sec > 59) throw new InvalidDataException("Invalid timezone offset.");
                    return TimeSpan.FromSeconds((m.Groups[1].Value == "+" ? 1 : -1) * (h * 3600 + min * 60 + sec));
                }
                var start = ParseStamp(Get("DTSTART")).Wall;
                var before = Offset(Get("TZOFFSETFROM").Value); var after = Offset(Get("TZOFFSETTO").Value);
                var rules = props.Where(value => value.Name == "RRULE").Select(value => new Rule(
                    Regex.Replace(value.Value.ToUpperInvariant(), @"UNTIL=(\d{8}T\d{6}Z)", m => "UNTIL=" + ParseStamp(new Property("UNTIL", m.Groups[1].Value, [])).Wall.Add(before).ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture)),
                    new Stamp(start, false, null))).ToArray();
                var dates = props.Where(value => value.Name == "RDATE").SelectMany(value => value.Value.Split(',').Select(text => ParseStamp(value with { Value = text }).Wall)).Append(start).Distinct().ToArray();
                observances.Add((start, before, after, rules, dates));
            }
            if (observances.Count == 0) throw new InvalidDataException("Missing timezone observance.");
            offsets = observances.SelectMany(value => new[] { value.Before, value.After }).Distinct().OrderDescending().ToArray();
            initial = observances.MinBy(value => value.Start - value.Before).Before;
        }
        private void Ensure(int year)
        {
            lock (gate)
            {
                if (year <= through) return;
                var endYear = Math.Min(9999, year + 4); var end = new DateTime(endYear, 12, 31, 23, 59, 59);
                var values = new SortedDictionary<DateTime, (TimeSpan Before, TimeSpan After)>();
                foreach (var o in observances)
                    foreach (var wall in o.Dates.Concat(o.Rules.SelectMany(rule => rule.Between(o.Start, end))).Distinct())
                    {
                        var at = wall - o.Before;
                        if (values.TryGetValue(at, out var existing) && existing != (o.Before, o.After)) throw new InvalidDataException("Conflicting timezone transitions.");
                        values[at] = (o.Before, o.After);
                        if (values.Count > MaximumOccurrences) throw new InvalidDataException("Timezone transition limit exceeded.");
                    }
                transitions = values.Select(value => (value.Key, value.Value.Before, value.Value.After)).ToArray(); through = endYear;
            }
        }
        private TimeSpan OffsetAt(DateTime utc)
        {
            Ensure(utc.Year);
            var low = 0; var high = transitions.Length;
            while (low < high) { var mid = (low + high) / 2; if (transitions[mid].At <= utc) low = mid + 1; else high = mid; }
            return low == 0 ? initial : transitions[low - 1].After;
        }
        internal DateTime FromUtc(DateTime utc) => DateTime.SpecifyKind(utc.Add(OffsetAt(utc)), DateTimeKind.Unspecified);
        internal TimeSpan FoldSpan(DateTime wall)
        {
            var valid = offsets.Where(offset => OffsetAt(wall - offset) == offset).ToArray();
            return valid.Length > 1 ? valid.Max() - valid.Min() : TimeSpan.Zero;
        }
        internal DateTime ToUtc(DateTime wall)
        {
            foreach (var offset in offsets)
                if (OffsetAt(wall - offset) == offset) return DateTime.SpecifyKind(wall - offset, DateTimeKind.Utc);
            foreach (var t in transitions)
                if (t.After > t.Before && wall >= t.At + t.Before && wall < t.At + t.After) return DateTime.SpecifyKind(wall - t.Before, DateTimeKind.Utc);
            throw new InvalidDataException("Unresolved timezone wall time.");
        }
    }
    private static readonly Dictionary<string, SourceZone> EmbeddedZones = new(StringComparer.Ordinal);
    internal static Dictionary<string, SourceZone> CalendarZones(IEnumerable<string[]> blocks)
    {
        var result = new Dictionary<string, SourceZone>(StringComparer.Ordinal);
        foreach (var block in blocks)
        {
            var id = block.Select(ParseProperty).OfType<Property>().First(value => value.Name == "TZID").Value;
            var signature = string.Join("\n", block);
            lock (EmbeddedZones)
            {
                if (!EmbeddedZones.TryGetValue(signature, out var zone))
                {
                    zone = new SourceZone(null, new Lazy<EmbeddedZone>(() => new EmbeddedZone(block)));
                    if (EmbeddedZones.Count >= 32) EmbeddedZones.Remove(EmbeddedZones.Keys.First());
                    EmbeddedZones[signature] = zone;
                }
                if (!result.TryAdd(id, zone)) throw new InvalidDataException("Duplicate calendar timezone.");
            }
        }
        return result;
    }
    internal static Dictionary<string, SourceZone> CalendarZones(JsonElement item) => CalendarZones(
        item.TryGetProperty("icsTimezones", out var zones) && zones.ValueKind == JsonValueKind.Array ? zones.EnumerateArray()
            .Where(value => value.ValueKind == JsonValueKind.Array).Select(value => value.EnumerateArray().Select(line => line.GetString()!).ToArray()) : []);
    internal static IEnumerable<string> ExportCalendar(List<(string[] Component, string[][] Zones)> records)
    {
        string Id(string[] block) => block.Select(ParseProperty).OfType<Property>().First(value => value.Name == "TZID").Value;
        var reserved = records.SelectMany(record => record.Component.Select(ParseProperty).OfType<Property>().Select(value => value.Parameter("TZID"))
            .Where(id => id.Length > 0 && !record.Zones.Any(block => Id(block) == id))).ToHashSet(StringComparer.Ordinal);
        var defined = new Dictionary<string, string>(StringComparer.Ordinal);
        var sourceIds = records.SelectMany(record => record.Zones.Select(Id)).ToHashSet(StringComparer.Ordinal);
        foreach (var record in records)
        {
            var aliases = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var block in record.Zones)
            {
                var id = Id(block); var signature = string.Join("\n", block); var alias = id;
                if (reserved.Contains(id) || defined.TryGetValue(id, out var existing) && existing != signature)
                {
                    var basis = "Magnolie/" + Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(signature))).ToLowerInvariant();
                    alias = basis; var suffix = 0;
                    while (reserved.Contains(alias) || sourceIds.Contains(alias) || defined.TryGetValue(alias, out existing) && existing != signature) alias = basis + "-" + ++suffix;
                }
                aliases[id] = alias;
                if (!defined.TryAdd(alias, signature)) continue;
                foreach (var line in block) yield return ParseProperty(line) is { Name: "TZID" } ? "TZID:" + alias : line;
            }
            foreach (var line in record.Component)
            {
                if (ParseProperty(line) is { } property && aliases.TryGetValue(property.Parameter("TZID"), out var alias) && alias != property.Parameter("TZID"))
                    yield return property.Name + string.Concat(property.Parameters.Select(value => ";" + (value.StartsWith("TZID=", StringComparison.OrdinalIgnoreCase) ? "TZID=" + alias : value))) + ":" + property.Value;
                else yield return line;
            }
        }
    }
    private const int MaximumPeriods = 146097;
    private const int MaximumOccurrences = 100000;
    private static readonly string[] Weekdays = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];
    private static readonly Dictionary<(string, Stamp), SortedDictionary<long, long>> Prefixes = new();
    private static readonly object PrefixGate = new();

    internal static Property? ParseProperty(string line)
    {
        var quoted = false; var pieces = new List<string>(); var begin = 0;
        for (var index = 0; index < line.Length; index++)
        {
            if (line[index] == '"') quoted = !quoted;
            if (quoted) continue;
            if (line[index] == ';') { pieces.Add(line[begin..index]); begin = index + 1; }
            if (line[index] != ':') continue;
            pieces.Add(line[begin..index]);
            return new Property(pieces[0].ToUpperInvariant(), line[(index + 1)..], pieces.Skip(1).ToArray());
        }
        return null;
    }

    internal static List<Property> Properties(JsonElement item)
    {
        var result = new List<Property>(); var depth = 0;
        if (!item.TryGetProperty("icsRoundtrip", out var raw) || raw.ValueKind != JsonValueKind.Array) return result;
        foreach (var line in raw.EnumerateArray())
        {
            if (line.ValueKind != JsonValueKind.String || ParseProperty(line.GetString()!) is not { } property) continue;
            if (property.Name == "BEGIN") { if (property.Value is not ("VEVENT" or "VTODO")) depth++; continue; }
            if (property.Name == "END") { if (property.Value is not ("VEVENT" or "VTODO")) depth = Math.Max(0, depth - 1); continue; }
            if (depth == 0) result.Add(property);
        }
        return result;
    }

    internal static Stamp ParseStamp(Property property, IReadOnlyDictionary<string, SourceZone>? zones = null)
    {
        var allDay = property.Parameter("VALUE").Equals("DATE", StringComparison.OrdinalIgnoreCase) || property.Value.Length == 8;
        var text = property.Value.Trim();
        var formats = allDay ? new[] { "yyyyMMdd" } : new[] { "yyyyMMdd'T'HHmmss'Z'", "yyyyMMdd'T'HHmmss", "yyyyMMdd'T'HHmm" };
        if (!DateTime.TryParseExact(text, formats, CultureInfo.InvariantCulture, DateTimeStyles.None, out var wall)) throw new InvalidDataException(NativeLocalization.Gettext("Invalid calendar date."));
        SourceZone? zone = allDay ? null : text.EndsWith('Z') ? (SourceZone)TimeZoneInfo.Utc : property.Parameter("TZID") is { Length: > 0 } id ?
            zones is not null && zones.TryGetValue(id, out var embedded) ? embedded : (SourceZone)Zone(id) : null;
        return new Stamp(DateTime.SpecifyKind(wall, DateTimeKind.Unspecified), allDay, allDay ? null : zone);
    }

    internal static TimeZoneInfo Zone(string id) => id is "" or "system" ? TimeZoneInfo.Local : TimeZoneInfo.FindSystemTimeZoneById(id);
    internal static string TextValue(string text) => Regex.Replace(text, @"\\([nN,;\\])", m => m.Groups[1].Value is "n" or "N" ? "\n" : m.Groups[1].Value);
    internal static TimeZoneInfo OrganizerZone(JsonElement root) => Zone(root.TryGetProperty("einstellungen", out var settings) &&
        settings.TryGetProperty("regional", out var regional) ? Text(regional, "timeZone") : "");
    internal static DateTime ToUtc(DateTime wall, SourceZone source)
    {
        wall = DateTime.SpecifyKind(wall, DateTimeKind.Unspecified);
        if (source.Embedded is { } embedded) return embedded.ToUtc(wall);
        var zone = source.System!;
        if (zone.IsAmbiguousTime(wall)) return DateTime.SpecifyKind(wall - zone.GetAmbiguousTimeOffsets(wall).Max(), DateTimeKind.Utc);
        // RFC 5545: an explicitly supplied gap time uses the offset before the gap.
        var before = wall;
        for (var minutes = 0; zone.IsInvalidTime(before) && minutes < 2880; minutes++) before = before.AddMinutes(-1);
        return DateTime.SpecifyKind(wall - zone.GetUtcOffset(before), DateTimeKind.Utc);
    }
    internal static DateTime NowUtc(DateTime now) => now.Kind == DateTimeKind.Utc ? now :
        now.Kind == DateTimeKind.Local ? now.ToUniversalTime() : ToUtc(now, TimeZoneInfo.Local);
    internal static DateTime FromUtc(DateTime utc, SourceZone zone) => zone.Embedded is { } embedded ? embedded.FromUtc(utc) : TimeZoneInfo.ConvertTimeFromUtc(utc, zone.System!);
    private static TimeSpan FoldSpan(DateTime wall, SourceZone zone) => zone.Embedded is { } embedded ? embedded.FoldSpan(wall) :
        zone.System!.IsAmbiguousTime(wall) ? zone.System.GetAmbiguousTimeOffsets(wall).Max() - zone.System.GetAmbiguousTimeOffsets(wall).Min() : TimeSpan.Zero;
    internal static DateTime InZone(Stamp stamp, SourceZone target) => stamp.AllDay ? stamp.Wall :
        FromUtc(ToUtc(stamp.Wall, stamp.Zone ?? target), target);

    internal static TimeSpan Duration(string value)
    {
        if (!Regex.IsMatch(value, @"^\+?P(?:\d+W|(?=\d+D|T)(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+S)?)?)$", RegexOptions.IgnoreCase))
            throw new InvalidDataException("Invalid calendar duration.");
        var matches = Regex.Matches(value, @"(\d+)([WDHMS])", RegexOptions.IgnoreCase);
        double seconds = 0;
        foreach (Match match in matches) seconds += double.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture) *
            (match.Groups[2].Value.ToUpperInvariant() switch { "W" => 604800, "D" => 86400, "H" => 3600, "M" => 60, _ => 1 });
        if (!double.IsFinite(seconds) || seconds > TimeSpan.MaxValue.TotalSeconds) throw new InvalidDataException("Invalid calendar duration.");
        return TimeSpan.FromSeconds(seconds);
    }

    internal static DateTime DurationEndUtc(Stamp start, string specification, TimeZoneInfo fallback)
    {
        var span = Duration(specification);
        var days = Regex.Matches(specification, @"(\d+)([WD])", RegexOptions.IgnoreCase).Cast<Match>()
            .Sum(match => double.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture) * (match.Groups[2].Value.Equals("W", StringComparison.OrdinalIgnoreCase) ? 7 : 1));
        return ToUtc(start.Wall.AddDays(days), start.Zone ?? fallback).Add(span - TimeSpan.FromDays(days));
    }

    internal static bool SupportsRules(IEnumerable<string> lines)
    {
        try
        {
            foreach (var line in lines)
                if (ParseProperty(line) is { } property && property.Name is "RRULE" or "EXRULE")
                    _ = new Rule(property.Value, new Stamp(new DateTime(2000, 1, 1), false, null));
            return true;
        }
        catch (Exception error) when (error is InvalidDataException or FormatException or OverflowException) { return false; }
    }

    internal static IReadOnlyList<CalendarOccurrence> Expand(JsonElement item, DateTime lower, DateTime upper, TimeZoneInfo target, bool task = false, bool overlap = false)
    {
        var properties = Properties(item);
        var zones = CalendarZones(item);
        Stamp Parse(Property property) => ParseStamp(property, zones);
        if (properties.Any(value => value.Name == "RECURRENCE-ID" && value.Parameter("RANGE") is not ("" or "THISANDFUTURE")))
            throw new InvalidDataException("Unsupported recurrence range.");
        if (Text(item, "icsStatus").Equals("CANCELLED", StringComparison.OrdinalIgnoreCase) ||
            properties.Any(property => property.Name == "STATUS" && property.Value.Equals("CANCELLED", StringComparison.OrdinalIgnoreCase))) return [];
        var dateField = task ? "startDatum" : "datum"; var timeField = task ? "startZeit" : "zeit";
        var startProperty = properties.FirstOrDefault(property => property.Name == "DTSTART");
        Stamp first;
        if (startProperty.Name is not null) first = Parse(startProperty);
        else
        {
            var date = Text(item, dateField); var time = Text(item, timeField);
            if (date.Length == 0 && task) { date = Text(item, "faellig"); time = Text(item, "faelligZeit"); }
            if (!DateTime.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day)) return [];
            if (time.Length > 0 && !TimeOnly.TryParseExact(time, "HH:mm", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)) return [];
            first = new Stamp(day.Add(time.Length == 0 ? TimeSpan.Zero : TimeOnly.ParseExact(time, "HH:mm", CultureInfo.InvariantCulture).ToTimeSpan()), time.Length == 0, null);
        }
        var sourceZone = first.Zone ?? target;
        var endProperty = properties.FirstOrDefault(property => property.Name == (task ? "DUE" : "DTEND"));
        var durationProperty = properties.FirstOrDefault(property => property.Name == "DURATION");
        TimeSpan duration;
        if (durationProperty.Name is not null) duration = Duration(durationProperty.Value);
        else if (endProperty.Name is not null)
        {
            var end = Parse(endProperty);
            duration = end.AllDay ? end.Wall - first.Wall : ToUtc(end.Wall, end.Zone ?? target) - ToUtc(first.Wall, sourceZone);
        }
        else
        {
            var endDate = Text(item, task ? "faellig" : "endDatum"); var endTime = Text(item, task ? "faelligZeit" : "endZeit");
            var end = DateTime.TryParseExact(endDate, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day) ? day : first.Wall.Date;
            end = end.Add(TimeOnly.TryParseExact(endTime, "HH:mm", CultureInfo.InvariantCulture, DateTimeStyles.None, out var time) ? time.ToTimeSpan() : first.Wall.TimeOfDay);
            if (first.AllDay && !task) end = end.AddDays(1);
            duration = end >= first.Wall ? end - first.Wall : TimeSpan.Zero;
        }
        if (duration < TimeSpan.Zero) throw new InvalidDataException("Invalid calendar end.");
        var ranges = new List<(DateTime Cutoff, TimeSpan Shift, TimeSpan Duration, string? Specification, bool Cancelled, string? Summary, string? Location, bool HasDuration)>();
        if (item.TryGetProperty("icsRangeOverrides", out var rangeValues) && rangeValues.ValueKind == JsonValueKind.Array)
            foreach (var range in rangeValues.EnumerateArray())
            {
                if (range.ValueKind != JsonValueKind.Array) continue;
                var definition = range.EnumerateArray().Where(line => line.ValueKind == JsonValueKind.String).Select(line => ParseProperty(line.GetString()!)).OfType<Property>().ToArray();
                var id = definition.FirstOrDefault(property => property.Name == "RECURRENCE-ID");
                if (id.Name is null || !id.Parameter("RANGE").Equals("THISANDFUTURE", StringComparison.OrdinalIgnoreCase)) continue;
                var original = Parse(id);
                var replacement = definition.FirstOrDefault(property => property.Name == "DTSTART");
                var shifted = replacement.Name is null ? original : Parse(replacement);
                var end = definition.FirstOrDefault(property => property.Name == (task ? "DUE" : "DTEND"));
                var specification = definition.FirstOrDefault(property => property.Name == "DURATION").Value;
                var span = duration;
                if (specification is not null) span = Duration(specification);
                else if (end.Name is not null)
                {
                    var endStamp = Parse(end);
                    span = endStamp.AllDay ? endStamp.Wall - shifted.Wall : ToUtc(endStamp.Wall, endStamp.Zone ?? target) - ToUtc(shifted.Wall, shifted.Zone ?? target);
                }
                ranges.Add((first.AllDay ? original.Wall : ToUtc(original.Wall, original.Zone ?? target), InZone(shifted, sourceZone) - InZone(original, sourceZone), span, specification,
                    definition.Any(property => property.Name == "STATUS" && property.Value.Equals("CANCELLED", StringComparison.OrdinalIgnoreCase)),
                    definition.FirstOrDefault(property => property.Name == "SUMMARY").Value, definition.FirstOrDefault(property => property.Name == "LOCATION").Value, end.Name is not null || specification is not null));
            }
        ranges.Sort((left, right) => left.Cutoff.CompareTo(right.Cutoff));
        for (var i = 0; i < ranges.Count; i++)
        {
            var r = ranges[i];
            if (i > 0) { r.Summary ??= ranges[i - 1].Summary; r.Location ??= ranges[i - 1].Location; }
            if (!r.HasDuration) { r.Duration = i > 0 ? ranges[i - 1].Duration : duration; r.Specification = i > 0 ? ranges[i - 1].Specification : durationProperty.Value; }
            ranges[i] = r;
        }
        var from = lower.Kind == DateTimeKind.Utc ? lower : ToUtc(lower, target);
        var through = upper.Kind == DateTimeKind.Utc ? upper : ToUtc(upper, target);
        var padding = ranges.Count == 0 ? TimeSpan.Zero : TimeSpan.FromDays(ranges.Max(range => Math.Abs(range.Shift.TotalDays)) + 2);
        var lookback = overlap ? TimeSpan.FromDays(Math.Max(duration.TotalDays, ranges.Count == 0 ? 0 : ranges.Max(range => range.Duration.TotalDays))) : TimeSpan.Zero;
        if (overlap && !first.AllDay && ranges.Select(value => value.Specification).Append(durationProperty.Value).Any(value => value is not null && Regex.IsMatch(value, "[WD]"))) lookback += TimeSpan.FromDays(2);
        var sourceLower = FromUtc(from.Subtract(padding).Subtract(lookback), sourceZone);
        var sourceUpper = FromUtc(through.Add(padding), sourceZone);
        if (!first.AllDay)
        {
            if (sourceLower > sourceUpper) sourceLower = sourceUpper;
            sourceUpper += FoldSpan(sourceUpper, sourceZone);
        }
        var occurrences = new SortedDictionary<DateTime, CalendarOccurrence>();
        void Add(Stamp stamp, TimeSpan span, string? durationText = null)
        {
            var instant = ToUtc(stamp.Wall, stamp.Zone ?? target);
            var endWall = stamp.Wall.Add(span);
            var endUtc = stamp.AllDay ? ToUtc(endWall, target) : durationText is not null ? DurationEndUtc(stamp, durationText, target) : instant.Add(span);
            if (stamp.AllDay ? stamp.Wall > sourceUpper || stamp.Wall < sourceLower && !(overlap && endWall >= sourceLower.Add(padding).Add(lookback)) : instant > through.Add(padding) || instant < from.Subtract(padding).Subtract(lookback) && !(overlap && endUtc >= from)) return;
            occurrences[stamp.AllDay ? stamp.Wall : instant] = new CalendarOccurrence(stamp.AllDay ? stamp.Wall : TimeZoneInfo.ConvertTimeFromUtc(instant, target),
                stamp.AllDay ? endWall : TimeZoneInfo.ConvertTimeFromUtc(endUtc, target), instant, endUtc, stamp.AllDay);
            if (occurrences.Count > MaximumOccurrences) throw new InvalidDataException("Calendar recurrence window is too large.");
        }
        Add(first, duration, durationProperty.Value);
        var rules = properties.Where(property => property.Name == "RRULE").ToArray();
        if (!properties.Any(property => property.Name == "RECURRENCE-ID"))
        {
            foreach (var property in rules)
                foreach (var occurrence in new Rule(property.Value, first with { Zone = first.Zone ?? target }).Between(sourceLower, sourceUpper)) Add(first with { Wall = occurrence }, duration, durationProperty.Value);
            if (rules.Length == 0 && item.TryGetProperty("wiederholung", out var recurrence) && recurrence.ValueKind == JsonValueKind.Object)
                foreach (var occurrence in Native(recurrence, first.Wall, sourceLower, sourceUpper)) Add(first with { Wall = occurrence }, duration, durationProperty.Value);
        }
        var rawAdditionDates = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in properties.Where(property => property.Name == "RDATE"))
            foreach (var value in property.Value.Split(','))
            {
                var period = value.Split('/', 2); var stamp = Parse(property with { Value = period[0] }); var span = duration;
                var specification = durationProperty.Value;
                if (period.Length > 1)
                {
                    specification = period[1].StartsWith('P') ? period[1] : null;
                    var periodEnd = specification is null ? Parse(property with { Value = period[1] }) : stamp;
                    span = specification is not null ? Duration(specification) : ToUtc(periodEnd.Wall, periodEnd.Zone ?? target) - ToUtc(stamp.Wall, stamp.Zone ?? target);
                }
                if (span < TimeSpan.Zero) throw new InvalidDataException("Invalid recurrence period.");
                Add(stamp, span, specification); rawAdditionDates.Add(InZone(stamp, target).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
            }
        var timedAdditionDates = new HashSet<string>(rawAdditionDates, StringComparer.Ordinal);
        if (item.TryGetProperty("icsZusatzTermine", out var timed) && timed.ValueKind == JsonValueKind.Array)
            foreach (var value in timed.EnumerateArray())
            {
                var date = Text(value, "datum"); if (rawAdditionDates.Contains(date)) continue;
                if (!DateTime.TryParseExact(date, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day)) continue;
                var time = TimeOnly.TryParseExact(Text(value, "zeit"), "HH:mm", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsedTime) ? parsedTime.ToTimeSpan() : first.Wall.TimeOfDay;
                Add(new Stamp(day.Add(time), first.AllDay, null), duration, durationProperty.Value); timedAdditionDates.Add(date);
            }
        if (item.TryGetProperty("icsZusatzDaten", out var dates) && dates.ValueKind == JsonValueKind.Array)
            foreach (var value in dates.EnumerateArray())
                if (value.ValueKind == JsonValueKind.String && !timedAdditionDates.Contains(value.GetString()!) &&
                    DateTime.TryParseExact(value.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var day))
                    Add(new Stamp(day.Add(first.Wall.TimeOfDay), first.AllDay, null), duration, durationProperty.Value);
        var preciseDates = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in properties.Where(property => property.Name == "EXDATE"))
            foreach (var value in property.Value.Split(','))
            {
                var stamp = Parse(property with { Value = value });
                var date = InZone(stamp, target).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                if (!stamp.AllDay) { occurrences.Remove(ToUtc(stamp.Wall, stamp.Zone ?? target)); preciseDates.Add(date); }
                else foreach (var key in occurrences.Where(pair => pair.Value.Start.Date == stamp.Wall.Date).Select(pair => pair.Key).ToArray()) occurrences.Remove(key);
            }
        var rawPreciseDates = new HashSet<string>(preciseDates, StringComparer.Ordinal);
        if (item.TryGetProperty("icsAusnahmeTermine", out var excludedTimes) && excludedTimes.ValueKind == JsonValueKind.Array)
            foreach (var value in excludedTimes.EnumerateArray())
                if (!rawPreciseDates.Contains(Text(value, "datum")) && DateTime.TryParseExact(Text(value, "datum") + " " + Text(value, "zeit"), "yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture, DateTimeStyles.None, out var stamp))
                { occurrences.Remove(ToUtc(stamp, target)); preciseDates.Add(Text(value, "datum")); }
        if (item.TryGetProperty("icsAusnahmen", out var excluded) && excluded.ValueKind == JsonValueKind.Array)
            foreach (var value in excluded.EnumerateArray())
                if (value.ValueKind == JsonValueKind.String && !preciseDates.Contains(value.GetString()!))
                    foreach (var key in occurrences.Where(pair => pair.Value.Start.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) == value.GetString()).Select(pair => pair.Key).ToArray()) occurrences.Remove(key);
        foreach (var property in properties.Where(property => property.Name == "EXRULE"))
        {
            var rule = new Rule(property.Value, first with { Zone = first.Zone ?? target });
            foreach (var key in occurrences.Keys.ToArray())
            {
                var wall = first.AllDay ? key : FromUtc(key, sourceZone);
                if (wall < sourceLower && rule.Between(wall, wall).Any(value => first.AllDay ? value == key : ToUtc(value, sourceZone) == key))
                    occurrences.Remove(key);
            }
            foreach (var occurrence in rule.Between(sourceLower, sourceUpper)) occurrences.Remove(first.AllDay ? occurrence : ToUtc(occurrence, sourceZone));
        }
        foreach (var key in occurrences.Keys.ToArray())
        {
            var range = ranges.LastOrDefault(value => value.Cutoff <= key);
            if (range == default) continue;
            if (range.Cancelled) { occurrences.Remove(key); continue; }
            var wall = (first.AllDay ? key : FromUtc(key, sourceZone)).Add(range.Shift);
            var instant = ToUtc(wall, sourceZone);
            var endInstant = range.Specification is not null ? DurationEndUtc(new Stamp(wall, first.AllDay, sourceZone), range.Specification, target) :
                first.AllDay ? ToUtc(wall.Add(range.Duration), target) : instant.Add(range.Duration);
            occurrences[key] = new CalendarOccurrence(first.AllDay ? wall : TimeZoneInfo.ConvertTimeFromUtc(instant, target), first.AllDay ? wall.Add(range.Duration) : TimeZoneInfo.ConvertTimeFromUtc(endInstant, target), instant, endInstant, first.AllDay, range.Summary, range.Location);
        }
        return occurrences.Values.Where(value => value.AllDay ? (overlap ? value.End : value.Start) >= sourceLower.Add(padding).Add(lookback) && value.Start <= sourceUpper.Subtract(padding) : (overlap ? value.EndUtc : value.StartUtc) >= from && value.StartUtc <= through).OrderBy(value => value.Start).ToArray();
    }

    private static IEnumerable<DateTime> Native(JsonElement recurrence, DateTime anchor, DateTime lower, DateTime upper)
    {
        var kind = Text(recurrence, "art"); var interval = Math.Clamp(Number(recurrence, "intervall", 1), 1, 3660);
        var until = DateTime.TryParseExact(Text(recurrence, "bis"), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var end) ? end.AddDays(1).AddTicks(-1) : DateTime.MaxValue;
        if (kind == "custom")
        {
            if (recurrence.TryGetProperty("daten", out var dates) && dates.ValueKind == JsonValueKind.Array)
                foreach (var value in dates.EnumerateArray())
                    if (value.ValueKind == JsonValueKind.String && DateTime.TryParseExact(value.GetString(), "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) && date > anchor.Date)
                        yield return date.Add(anchor.TimeOfDay);
            yield break;
        }
        if (kind is not ("daily" or "weekly" or "monthly" or "monthly_weekday" or "yearly")) yield break;
        var distance = kind is "daily" or "weekly" ? (lower.Date - anchor.Date).Days / ((kind == "weekly" ? 7 : 1) * interval) :
            kind == "yearly" ? (lower.Year - anchor.Year) / interval : ((lower.Year - anchor.Year) * 12 + lower.Month - anchor.Month) / interval;
        for (var index = Math.Max(0, distance); ; index++)
        {
            DateTime current;
            try { current = kind switch { "daily" => anchor.AddDays((long)index * interval), "weekly" => anchor.AddDays((long)index * interval * 7),
                "yearly" => anchor.AddYears(checked(index * interval)), _ => anchor.AddMonths(checked(index * interval)) }; }
            catch (ArgumentOutOfRangeException) { yield break; }
            if (kind is "monthly" or "monthly_weekday" && Number(recurrence, "ordinal", 0) is var ordinal && ordinal is >= -5 and <= 5 and not 0 &&
                Array.IndexOf(Weekdays, Text(recurrence, "wochentag")) is var weekday && weekday >= 0)
            {
                var first = new DateTime(current.Year, current.Month, 1).Add(anchor.TimeOfDay);
                if (first > upper) yield break;
                var last = first.AddDays(DateTime.DaysInMonth(first.Year, first.Month) - 1);
                current = ordinal > 0 ? first.AddDays((weekday - (int)first.DayOfWeek + 7) % 7 + (ordinal - 1) * 7) :
                    last.AddDays(-((int)last.DayOfWeek - weekday + 7) % 7 + (ordinal + 1) * 7);
                if (current.Month != first.Month) continue;
            }
            if (current > upper || current > until) yield break;
            if (current > anchor && current >= lower) yield return current;
        }
    }

    private sealed class Rule
    {
        private readonly Dictionary<string, string> fields;
        private readonly Stamp start;
        private readonly string frequency;
        private readonly int interval;
        private readonly long count;
        private readonly DateTime periodStart;
        private readonly int weekStart;
        private readonly Dictionary<string, int[]> numbers = new(StringComparer.Ordinal);
        private readonly (string, Stamp) prefixKey;
        private int candidateWork;
        private bool Subdaily => frequency is "HOURLY" or "MINUTELY" or "SECONDLY";
        private long UnitTicks => frequency == "HOURLY" ? TimeSpan.TicksPerHour : frequency == "MINUTELY" ? TimeSpan.TicksPerMinute : TimeSpan.TicksPerSecond;
        internal Rule(string rule, Stamp first)
        {
            fields = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var part in rule.ToUpperInvariant().Split(';'))
            {
                var pair = part.Split('=', 2);
                if (pair.Length != 2 || !fields.TryAdd(pair[0], pair[1]) || pair[1].Length == 0) throw new InvalidDataException("Invalid recurrence rule.");
            }
            if (fields.Keys.Any(key => key is not ("FREQ" or "INTERVAL" or "COUNT" or "UNTIL" or "WKST" or "BYDAY" or "BYMONTHDAY" or "BYMONTH" or "BYYEARDAY" or "BYWEEKNO" or "BYSETPOS" or "BYHOUR" or "BYMINUTE" or "BYSECOND"))) throw new InvalidDataException("Unsupported recurrence rule.");
            frequency = Get("FREQ"); start = first;
            prefixKey = (string.Join(";", fields.OrderBy(value => value.Key).Select(value => value.Key + "=" + value.Value)), first);
            if (frequency is not ("SECONDLY" or "MINUTELY" or "HOURLY" or "DAILY" or "WEEKLY" or "MONTHLY" or "YEARLY")) throw new InvalidDataException("Unsupported recurrence frequency.");
            interval = Get("INTERVAL").Length == 0 ? 1 : int.Parse(Get("INTERVAL"), CultureInfo.InvariantCulture);
            count = Get("COUNT").Length == 0 ? long.MaxValue : long.Parse(Get("COUNT"), CultureInfo.InvariantCulture);
            if (interval < 1 || count < 1 || fields.ContainsKey("COUNT") && fields.ContainsKey("UNTIL")) throw new InvalidDataException("Invalid recurrence limit.");
            weekStart = Get("WKST").Length == 0 ? 1 : Array.IndexOf(Weekdays, Get("WKST"));
            if (weekStart < 0) throw new InvalidDataException("Invalid week start.");
            foreach (var (name, min, max, zero) in new[] { ("BYMONTH", 1, 12, false), ("BYMONTHDAY", -31, 31, false), ("BYYEARDAY", -366, 366, false),
                ("BYWEEKNO", -53, 53, false), ("BYSETPOS", -366, 366, false), ("BYHOUR", 0, 23, true), ("BYMINUTE", 0, 59, true), ("BYSECOND", 0, 59, true) })
            {
                var values = Get(name).Length == 0 ? [] : Get(name).Split(',').Select(value => int.Parse(value, CultureInfo.InvariantCulture)).Distinct().Order().ToArray();
                if (values.Any(value => value < min || value > max || !zero && value == 0)) throw new InvalidDataException("Invalid recurrence selector.");
                numbers[name] = values;
            }
            if (Get("BYDAY").Length > 0 && Get("BYDAY").Split(',').Any(value => !Regex.IsMatch(value, @"^(?:[+-]?[1-9]\d?)?(?:SU|MO|TU|WE|TH|FR|SA)$"))) throw new InvalidDataException("Invalid recurrence weekday.");
            if (first.AllDay && Subdaily || numbers["BYWEEKNO"].Length > 0 && frequency != "YEARLY" ||
                numbers["BYYEARDAY"].Length > 0 && frequency is "DAILY" or "WEEKLY" or "MONTHLY" ||
                numbers["BYMONTHDAY"].Length > 0 && frequency == "WEEKLY" ||
                numbers["BYSETPOS"].Length > 0 && !fields.Keys.Any(key => key.StartsWith("BY", StringComparison.Ordinal) && key != "BYSETPOS") ||
                Get("BYDAY").Split(',').Any(value => value.Length > 2 && (frequency is not ("MONTHLY" or "YEARLY") || numbers["BYWEEKNO"].Length > 0 || Math.Abs(int.Parse(value[..^2], CultureInfo.InvariantCulture)) > 53)))
                throw new InvalidDataException("Invalid recurrence selector combination.");
            if (Get("UNTIL").Length > 0) _ = ParseStamp(new Property("UNTIL", Get("UNTIL"), []));
            periodStart = frequency switch { "HOURLY" => first.Wall.Date.AddHours(first.Wall.Hour), "MINUTELY" => first.Wall.AddTicks(-(first.Wall.Ticks % TimeSpan.TicksPerMinute)),
                "SECONDLY" => first.Wall.AddTicks(-(first.Wall.Ticks % TimeSpan.TicksPerSecond)), "DAILY" => first.Wall.Date, "WEEKLY" => first.Wall.Date.AddDays(-((int)first.Wall.DayOfWeek - weekStart + 7) % 7),
                "MONTHLY" => new DateTime(first.Wall.Year, first.Wall.Month, 1), _ => new DateTime(first.Wall.Year, 1, 1) };
        }
        private string Get(string name) => fields.GetValueOrDefault(name, "");
        private DateTime Period(long index) => Subdaily ? periodStart.AddTicks(checked(index * interval * UnitTicks)) : frequency switch { "DAILY" => periodStart.AddDays(index * interval),
            "WEEKLY" => periodStart.AddDays(index * interval * 7), "MONTHLY" => periodStart.AddMonths(checked((int)(index * interval))), _ => periodStart.AddYears(checked((int)(index * interval))) };
        private long Index(DateTime date) => Math.Max(0, Subdaily ? (date.Ticks - periodStart.Ticks) / UnitTicks / interval : frequency switch { "DAILY" => (date.Date - periodStart).Days / interval,
            "WEEKLY" => (date.Date - periodStart).Days / (7 * (long)interval),
            "MONTHLY" => ((date.Year - periodStart.Year) * 12 + date.Month - periodStart.Month) / interval, _ => (date.Year - periodStart.Year) / interval });
        internal IEnumerable<DateTime> Between(DateTime lower, DateTime upper)
        {
            candidateWork = 0;
            var first = Math.Max(0, Index(lower) - 1); long seen = 0;
            if (count != long.MaxValue && first > 0)
            {
                if ((Subdaily || frequency is "DAILY" or "WEEKLY") && fields.Keys.All(key => key is "FREQ" or "INTERVAL" or "COUNT" or "WKST") &&
                     (start.Zone is null || start.Zone.System?.GetAdjustmentRules().Length == 0 || start.AllDay)) seen = first;
                else
                {
                // Shared exact prefix checkpoints survive windows and budget errors.
                // Do not extrapolate historical timezone transitions as Gregorian cycles.
                lock (PrefixGate)
                {
                    if (!Prefixes.TryGetValue(prefixKey, out var prefix))
                    {
                        if (Prefixes.Count >= 32) Prefixes.Remove(Prefixes.Keys.First());
                        Prefixes[prefixKey] = prefix = new SortedDictionary<long, long> { [0] = 0 };
                    }
                    var checkpoint = prefix.Last(value => value.Key <= first);
                    var cursor = checkpoint.Key; seen = checkpoint.Value; var scanned = 0;
                    var initial = cursor;
                    try
                    {
                        while (cursor < first && seen < count)
                        {
                            if (++scanned > MaximumPeriods)
                            {
                                var error = new InvalidDataException("Recurrence count window is too large.");
                                error.Data["recurrenceResource"] = "work";
                                throw error;
                            }
                            seen += Candidates(cursor).Count(value => value >= start.Wall);
                            cursor++;
                            if (cursor % 128 == 0 || cursor == first) prefix[cursor] = seen;
                            if (prefix.Count > 4096) foreach (var key in prefix.Keys.Where((_, index) => index % 2 == 1).ToArray()) prefix.Remove(key);
                        }
                    }
                    catch (InvalidDataException error)
                    {
                        prefix[cursor] = seen;
                        error.Data["retryable"] = cursor > initial && error.Data["recurrenceResource"] is "work";
                        throw;
                    }
                    if (prefix.Count > 4096) foreach (var key in prefix.Keys.Where((_, index) => index % 2 == 1).ToArray()) prefix.Remove(key);
                }
                }
                if (seen >= count) yield break;
            }
            var checkedPeriods = 0;
            for (var index = first; index <= Index(upper) + 1; index++)
            {
                if (++checkedPeriods > MaximumPeriods) throw new InvalidDataException("Recurrence window is too large.");
                List<DateTime> candidates;
                try { candidates = Candidates(index); }
                catch (ArgumentOutOfRangeException) { yield break; }
                foreach (var candidate in candidates)
                {
                    if (candidate < start.Wall) continue;
                    if (++seen > count) yield break;
                    if (!BeforeUntil(candidate)) yield break;
                    if (candidate >= lower && candidate <= upper) yield return candidate;
                }
            }
        }
        private bool BeforeUntil(DateTime candidate)
        {
            var until = Get("UNTIL"); if (until.Length == 0) return true;
            var parsed = ParseStamp(new Property("UNTIL", until, []));
            if (parsed.AllDay) return candidate.Date <= parsed.Wall;
            return parsed.Zone is null ? candidate <= parsed.Wall : ToUtc(candidate, start.Zone ?? TimeZoneInfo.Local) <= ToUtc(parsed.Wall, parsed.Zone);
        }
        private List<DateTime> Candidates(long index)
        {
            var period = Period(index);
            var days = frequency switch { "SECONDLY" or "MINUTELY" or "HOURLY" or "DAILY" => 1, "WEEKLY" => 7, "MONTHLY" => DateTime.DaysInMonth(period.Year, period.Month), _ => DateTime.IsLeapYear(period.Year) ? 366 : 365 };
            var firstDay = period.Date;
            if (frequency == "YEARLY" && numbers["BYWEEKNO"].Length > 0)
            { firstDay = WeekOne(period.Year); days = (WeekOne(period.Year + 1) - firstDay).Days; }
            var result = new List<DateTime>();
            var hours = start.AllDay ? [0] : Subdaily ? [period.Hour] : numbers["BYHOUR"].Length > 0 ? numbers["BYHOUR"] : [start.Wall.Hour];
            var minutes = start.AllDay ? [0] : frequency is "MINUTELY" or "SECONDLY" ? [period.Minute] : numbers["BYMINUTE"].Length > 0 ? numbers["BYMINUTE"] : [start.Wall.Minute];
            var seconds = start.AllDay ? [0] : frequency == "SECONDLY" ? [period.Second] : numbers["BYSECOND"].Length > 0 ? numbers["BYSECOND"] : [start.Wall.Second];
            if (Subdaily && numbers["BYHOUR"].Length > 0 && !numbers["BYHOUR"].Contains(period.Hour) ||
                frequency is "MINUTELY" or "SECONDLY" && numbers["BYMINUTE"].Length > 0 && !numbers["BYMINUTE"].Contains(period.Minute) ||
                frequency == "SECONDLY" && numbers["BYSECOND"].Length > 0 && !numbers["BYSECOND"].Contains(period.Second)) return [];
            for (var day = 0; day < days; day++)
            {
                var date = firstDay.AddDays(day);
                if (!MatchesDate(date, period.Year)) continue;
                foreach (var hour in hours) foreach (var minute in minutes) foreach (var second in seconds)
                {
                    if (++candidateWork > 2000000)
                    {
                        var error = new InvalidDataException("Recurrence window is too large.");
                        error.Data["recurrenceResource"] = "work";
                        throw error;
                    }
                    var candidate = date.AddHours(hour).AddMinutes(minute).AddSeconds(second);
                    if (!start.AllDay && start.Zone is { } zone && FromUtc(ToUtc(candidate, zone), zone) != candidate) continue;
                    result.Add(candidate);
                    if (result.Count > MaximumOccurrences) throw new InvalidDataException("Recurrence period is too large.");
                }
            }
            return numbers["BYSETPOS"].Length == 0 ? result : numbers["BYSETPOS"].Select(position => position > 0 ? position - 1 : result.Count + position)
                .Where(position => position >= 0 && position < result.Count).Select(position => result[position]).Distinct().Order().ToList();
        }
        private DateTime WeekOne(int year)
        {
            var fourth = new DateTime(year, 1, 4);
            return fourth.AddDays(-((int)fourth.DayOfWeek - weekStart + 7) % 7);
        }
        private bool MatchesDate(DateTime date, int year)
        {
            bool Contains(string name, int positive, int total) => numbers[name].Length == 0 || numbers[name].Any(value => value > 0 ? value == positive : total + value + 1 == positive);
            if (!Contains("BYMONTH", date.Month, 12) || !Contains("BYMONTHDAY", date.Day, DateTime.DaysInMonth(date.Year, date.Month)) ||
                !Contains("BYYEARDAY", date.DayOfYear, DateTime.IsLeapYear(date.Year) ? 366 : 365)) return false;
            if (numbers["BYWEEKNO"].Length > 0 && !Contains("BYWEEKNO", (date - WeekOne(year)).Days / 7 + 1, (WeekOne(year + 1) - WeekOne(year)).Days / 7)) return false;
            var byDay = Get("BYDAY");
            if (byDay.Length > 0)
            {
                if (!byDay.Split(',').Any(value =>
                {
                    if (value[^2..] != Weekdays[(int)date.DayOfWeek]) return false;
                    if (value.Length == 2) return true;
                    var ordinal = int.Parse(value[..^2], CultureInfo.InvariantCulture);
                    var position = frequency == "YEARLY" && numbers["BYMONTH"].Length == 0 ? date.DayOfYear : date.Day;
                    var total = frequency == "YEARLY" && numbers["BYMONTH"].Length == 0 ? (DateTime.IsLeapYear(date.Year) ? 366 : 365) : DateTime.DaysInMonth(date.Year, date.Month);
                    return ordinal > 0 ? (position - 1) / 7 + 1 == ordinal : -((total - position) / 7 + 1) == ordinal;
                })) return false;
            }
            else if (frequency == "WEEKLY" && date.DayOfWeek != start.Wall.DayOfWeek) return false;
            var daySelected = byDay.Length > 0 || numbers["BYMONTHDAY"].Length > 0 || numbers["BYYEARDAY"].Length > 0 || numbers["BYWEEKNO"].Length > 0;
            if (frequency is "MONTHLY" or "YEARLY" && !daySelected && date.Day != start.Wall.Day) return false;
            if (frequency == "YEARLY" && numbers["BYMONTH"].Length == 0 && !daySelected && date.Month != start.Wall.Month) return false;
            return true;
        }
    }
    private static long Gcd(long left, long right) { while (right != 0) (left, right) = (right, left % right); return left; }
    private static string Text(JsonElement item, string name) => item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
    private static int Number(JsonElement item, string name, int fallback) => item.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : fallback;
}
