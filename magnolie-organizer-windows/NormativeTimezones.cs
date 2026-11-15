using System.Security.Cryptography;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

// #653: the same byte-bound schema-2 rules as the GUI, not an OS rule snapshot.
// Named rules are deliberately not represented as a lossy CustomTimeZone.
internal static class NormativeTimezones
{
    internal const string PayloadSHA256 = "2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c";
    private const long Second = TimeSpan.TicksPerSecond;
    private const long Day = TimeSpan.TicksPerDay;
    private static readonly Lazy<Database> Rules = new(Load);

    private sealed record Database(Dictionary<string, Zone> Zones);
    private readonly record struct Selector(string Kind, int A, int B, int C, int Seconds);
    private readonly record struct Transition(long At, int Before, int After);

    internal sealed class Zone
    {
        private readonly int initial, standard;
        private readonly int? daylight;
        private readonly Selector? start, end;
        private readonly (long At, int Offset)[] history;
        private readonly int[] offsets;

        internal Zone(JsonElement row)
        {
            var types = row[1].EnumerateArray().Select(type => type[0].GetInt32()).ToArray();
            initial = types[row[0].GetInt32()];
            var values = row[2].EnumerateArray().Select(value => value.GetInt64()).ToArray();
            history = Enumerable.Range(0, values.Length / 2).Select(index =>
                (checked(values[index * 2] * Second), types[checked((int)values[index * 2 + 1])])).ToArray();
            var tail = row[3];
            standard = tail[0].GetInt32();
            daylight = tail[2].ValueKind == JsonValueKind.Null ? null : tail[2].GetInt32();
            start = ReadSelector(tail[4]); end = ReadSelector(tail[5]);
            offsets = types.Append(standard).Concat(daylight is int dst ? [dst] : Array.Empty<int>()).Distinct().ToArray();
        }

        private static Selector? ReadSelector(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null :
            new Selector(value[0].GetString()!, value[1].GetInt32(), value[2].GetInt32(), value[3].GetInt32(), value[4].GetInt32());

        // Evaluate M/J/N selectors in the proleptic Gregorian calendar. Neighbor
        // years 0 and 10000 are necessary even though DateTime results are 1..9999.
        private static long RuleTime(Selector rule, int year)
        {
            long days;
            if (rule.Kind == "M")
            {
                var first = CivilDays(year, rule.A, 1);
                var weekday = (int)((first + 4) % 7 + 7) % 7;
                var day = 1 + (rule.C - weekday + 7) % 7 + (rule.B - 1) * 7;
                var next = rule.A == 12 ? CivilDays(year + 1, 1, 1) : CivilDays(year, rule.A + 1, 1);
                if (first + day - 1 >= next) day -= 7;
                days = first + day - 1;
            }
            else
            {
                var leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
                var index = rule.Kind == "J" ? rule.A - 1 + (leap && rule.A >= 60 ? 1 : 0) : rule.A;
                days = CivilDays(year, 1, 1) + index;
            }
            return checked(days * Day + rule.Seconds * Second);
        }

        private Transition[] Future(int year)
        {
            if (daylight is not int dst) return [];
            var result = new List<Transition>(10);
            for (var neighbor = year - 2; neighbor <= year + 2; neighbor++)
            {
                result.Add(new Transition(RuleTime(start!.Value, neighbor) - standard * Second, standard, dst));
                result.Add(new Transition(RuleTime(end!.Value, neighbor) - dst * Second, dst, standard));
            }
            return result.OrderBy(value => value.At).ToArray();
        }

        private int OffsetAt(long instant)
        {
            if (history.Length == 0 || instant > history[^1].At)
            {
                if (daylight is null) return standard;
                var events = Future(CivilYear(instant));
                var offset = events[0].Before;
                foreach (var value in events) { if (value.At > instant) break; offset = value.After; }
                return offset;
            }
            var lo = 0; var hi = history.Length;
            while (lo < hi) { var middle = (lo + hi) / 2; if (history[middle].At <= instant) lo = middle + 1; else hi = middle; }
            return lo == 0 ? initial : history[lo - 1].Offset;
        }

        private long[] Candidates(long wall) => offsets.Select(offset => wall - offset * Second)
            .Where(instant => instant + OffsetAt(instant) * Second == wall).Distinct().Order().ToArray();

        internal bool IsConstant => offsets.Length == 1;
        internal TimeSpan FoldSpan(DateTime wall)
        {
            var values = Candidates(WallTicks(wall));
            return values.Length < 2 ? TimeSpan.Zero : TimeSpan.FromTicks(values[^1] - values[0]);
        }
        internal bool IsGap(DateTime wall) => Candidates(WallTicks(wall)).Length == 0;
        internal DateTime FromUtc(DateTime utc)
        {
            var instant = WallTicks(utc);
            return CivilResult(instant + OffsetAt(instant) * Second, DateTimeKind.Unspecified);
        }
        internal DateTime ToUtc(DateTime wall)
        {
            var local = WallTicks(wall); var candidates = Candidates(local);
            if (candidates.Length > 0) return CivilResult(candidates[0], DateTimeKind.Utc);
            // RFC 5545 explicit gap: use the offset before the actual transition.
            // Generated recurrence candidates use IsGap and are omitted instead.
            var events = new List<Transition>(); var before = initial;
            foreach (var value in history) { events.Add(new Transition(value.At, before, value.Offset)); before = value.Offset; }
            events.AddRange(Future(wall.Year).Where(value => history.Length == 0 || value.At > history[^1].At));
            foreach (var value in events)
                if (value.After > value.Before && local >= value.At + value.Before * Second && local < value.At + value.After * Second)
                    return CivilResult(local - value.Before * Second, DateTimeKind.Utc);
            throw new InvalidDataException("Unresolved normative timezone wall time.");
        }
    }

    internal static bool TryGet(string id, out Zone? zone) => Rules.Value.Zones.TryGetValue(id, out zone);

    private static byte[] Resource(string name, string digest)
    {
        using var stream = typeof(NormativeTimezones).Assembly.GetManifestResourceStream("Magnolie.Timezones." + name)
            ?? throw new InvalidDataException("Bound normative timezone resource is missing.");
        if (stream.Length > 4 * 1024 * 1024) throw new InvalidDataException("Normative timezone resource is too large.");
        using var buffer = new MemoryStream(); stream.CopyTo(buffer); var bytes = buffer.ToArray();
        if (!Convert.ToHexString(SHA256.HashData(bytes)).Equals(digest, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Normative timezone resource identity differs.");
        return bytes;
    }

    private static Database Load()
    {
        var bytes = Resource("tzdb-2026egtz.json", PayloadSHA256);
        _ = Resource("LICENSE-tzdb.txt", "0613408568889f5739e5ae252b722a2659c02002839ad970a63dc5e9174b27cf");
        using var provenance = JsonDocument.Parse(Resource("provenance.json", "b6b926b73620b3ab9ba477195041e52925ee6b12376791e647f70beba6bcc2a0"));
        using var document = JsonDocument.Parse(bytes);
        var root = document.RootElement; var manifest = provenance.RootElement;
        if (root.GetProperty("schema").GetInt32() != 2 || root.GetProperty("tzdbVersion").GetString() != "2026egtz" ||
            manifest.GetProperty("payloadSHA256").GetString() != PayloadSHA256 || manifest.GetProperty("payloadBytes").GetInt32() != bytes.Length ||
            root.GetProperty("sourceArchiveSHA256").GetString() != manifest.GetProperty("archiveSHA256").GetString())
            throw new InvalidDataException("Normative timezone provenance differs.");
        // Hash verification precedes parsing: no untrusted/imported rule registry.
        var rules = root.GetProperty("rules").EnumerateArray().Select(row => new Zone(row)).ToArray();
        return new Database(root.GetProperty("zones").EnumerateObject().ToDictionary(value => value.Name,
            value => rules[value.Value.GetInt32()], StringComparer.Ordinal));
    }

    private static long WallTicks(DateTime value) => value.Ticks - DateTime.UnixEpoch.Ticks;
    private static DateTime CivilResult(long ticks, DateTimeKind kind)
    {
        var value = ticks + DateTime.UnixEpoch.Ticks;
        if (value < DateTime.MinValue.Ticks || value > DateTime.MaxValue.Ticks)
            throw new InvalidDataException("Normative timezone result is outside the supported calendar range.");
        return new DateTime(value, kind);
    }
    private static long Floor(long value, long divisor) => value >= 0 ? value / divisor : (value - divisor + 1) / divisor;
    private static long CivilDays(int year, int month, int day)
    {
        year -= month <= 2 ? 1 : 0;
        var era = Floor(year, 400); var y = year - era * 400;
        var doy = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
        return era * 146097 + y * 365 + y / 4 - y / 100 + doy - 719468;
    }
    private static int CivilYear(long ticks)
    {
        var day = Floor(ticks, Day); var low = -2; var high = 10003;
        while (low + 1 < high) { var mid = (low + high) / 2; if (CivilDays(mid, 1, 1) <= day) low = mid; else high = mid; }
        return low;
    }
}
