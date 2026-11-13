using System.Buffers.Binary;
using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

/// <summary>Read-only, bounded ccSTR reader. Freed allocations are never imported.</summary>
internal static class Or6Codec
{
    private const int MaxBlocks = 250000, MaxFields = 512;
    private const uint RepeatTag = 0xfefffff2;
    // Original-program UI slots and all15 saved event fills, not guessed RGBs.
    private static readonly string[] PlannerColors = ["#ff0000", "#00c200", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
        "#800000", "#008000", "#000080", "#808000", "#800080", "#008080", "#808080", "#c0c0c0", "#000000"];
    private sealed record Entry(uint Tag, Dictionary<ushort, byte[]> Fields, string Uid,
        (uint, uint) Object, (uint, uint) Schema);
    private static readonly Encoding Wide = new UnicodeEncoding(false, false, true);
    private static readonly Regex Control = new(@"\G([a-zA-Z]+)(-?\d{1,10})? ?", RegexOptions.CultureInvariant);
    private static InvalidDataException Invalid() => new(NativeLocalization.Gettext("The content is unreadable."));
    internal static bool HasMagic(ReadOnlySpan<byte> bytes) => bytes.StartsWith(new byte[] { 0x30, 0x4b, 0x04, 0xb3 });

    private sealed class Document
    {
        private readonly byte[] data;
        private readonly Dictionary<int, (uint Tag, int Size)> blocks = new();
        private readonly Dictionary<(uint, uint), (uint Tag, HashSet<ushort> Fields)> schemas = new();
        private readonly Dictionary<(uint, uint), string> schemaNames = new();
        private readonly HashSet<(uint, uint)> plannerZeroDefaults = new();
        private readonly HashSet<(uint, uint)> calendarIndexDefaults = new();
        internal bool CalendarIndexDeclared(Entry entry) => calendarIndexDefaults.Contains(entry.Schema);
        private uint U32(int offset) => BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4));
        private ushort U16(int offset) => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(offset, 2));
        private (uint, uint) Reference(int offset) => (U32(offset), U32(offset + 4));
        private int Address(uint value) => value <= data.Length ? (int)value : throw Invalid();

        internal Document(byte[] raw)
        {
            if (raw.Length < 1024 || raw.LongLength > ExchangeCodec.MaxImportBytes || raw.Length % 4 != 0 || !HasMagic(raw)) throw Invalid();
            data = new byte[raw.Length];
            for (var offset = 0; offset < raw.Length; offset += 2)
            {
                var word = BinaryPrimitives.ReadUInt16LittleEndian(raw.AsSpan(offset, 2));
                BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(offset, 2), (ushort)((word << 1) | (word >> 15)));
            }
            for (var offset = 0; offset < data.Length;)
            {
                if (offset > data.Length - 12 || blocks.Count >= MaxBlocks) throw Invalid();
                var tag = U32(offset); var sizeValue = U32(offset + 8);
                if (U32(offset + 4) != offset || sizeValue < 12 || sizeValue % 4 != 0 || sizeValue > data.Length - offset) throw Invalid();
                var size = (int)sizeValue;
                blocks.Add(offset, (tag, size)); offset += size;
            }
            if (blocks[0] != (0x66099660U, 1024)) throw Invalid();
            foreach (var (offset, block) in blocks)
            {
                if (block.Tag != uint.MaxValue) continue;
                if (block.Size < 0x48 || schemas.ContainsKey(Reference(offset + 12))) throw Invalid();
                var fields = new HashSet<ushort>(); var seen = new HashSet<int>();
                var next = Address(U32(offset + 0x28));
                while (next != 0)
                {
                    if (!seen.Add(next) || seen.Count > MaxFields || !blocks.TryGetValue(next, out var field) ||
                        field.Tag != 0xfffffffd || field.Size < 0x32 || Reference(next + 0x18) != Reference(offset + 12) ||
                        !fields.Add(U16(next + 0x24))) throw Invalid();
                    if (U32(offset + 0x2c) == 0x200 && U16(next + 0x24) == 19 && U16(next + 0x26) == 2)
                        plannerZeroDefaults.Add(Reference(offset + 12));
                    if (U32(offset + 0x2c) == 0x100 && U16(next + 0x24) == 14 && U16(next + 0x26) == 0x2003)
                        calendarIndexDefaults.Add(Reference(offset + 12));
                    next = Address(U32(next + 0x20));
                }
                schemas.Add(Reference(offset + 12), (U32(offset + 0x2c), fields));
                if (U32(offset + 0x2c) == 0x200 && block.Size >= 0xc8)
                    try { schemaNames[Reference(offset + 12)] = Wide.GetString(data, offset + 0x48, 128).Split('\0')[0]; }
                    catch (DecoderFallbackException) { }
            }
        }

        internal IEnumerable<Entry> Entries(bool repeats = false, bool plannerSections = false)
        {
            foreach (var (offset, block) in blocks)
            {
                if (plannerSections)
                {
                    if (block.Tag != 0xfeffffff || block.Size < 0x34) continue;
                    var rootCount = U32(offset + 0x28);
                    if (rootCount > MaxFields || 0x34 + rootCount * 8 > block.Size) continue;
                    var planner = false;
                    // Only inspect the inline kind enum before reading a name;
                    // unrelated/notebook section roots are not reconstructed.
                    for (var i = 0; i < rootCount; i++)
                    {
                        var field = offset + 0x34 + i * 8;
                        if (U16(field) == 5 && U16(field + 2) == 4 && U32(field + 4) == 0x200) planner = true;
                    }
                    if (!planner) continue;
                }
                else if (offset == 0 || block.Tag >= 0x80000000 && !(repeats && block.Tag == RepeatTag)) continue;
                if (block.Size < 0x34 || !schemas.TryGetValue(Reference(offset + 0x18), out var schema) || schema.Tag != block.Tag) throw Invalid();
                var count = U32(offset + 0x28);
                if (count > MaxFields || 0x34 + count * 8 > block.Size) throw Invalid();
                var minimum = 0x34 + (int)count * 8;
                var fields = new Dictionary<ushort, byte[]>();
                for (var index = 0; index < count; index++)
                {
                    var entry = offset + 0x34 + index * 8; var id = U16(entry); var length = U16(entry + 2); var value = U32(entry + 4);
                    if (!schema.Fields.Contains(id) || fields.ContainsKey(id)) throw Invalid();
                    if (length <= 4) fields.Add(id, data.AsSpan(entry + 4, length).ToArray());
                    else
                    {
                        if (value < minimum || length > block.Size || value > block.Size - length) throw Invalid();
                        fields.Add(id, data.AsSpan(offset + (int)value, length).ToArray());
                    }
                }
                var (idValue, origin) = Reference(offset + 12);
                yield return new(block.Tag, fields, $"or6:{origin:x8}:{idValue:x8}", (idValue, origin), Reference(offset + 0x18));
            }
        }

        internal bool PlannerZeroDefault((uint, uint) schema) => plannerZeroDefaults.Contains(schema);

        internal Dictionary<(uint, uint), string[]> PlannerKeys(List<Entry> entries)
        {
            var roots = Entries(plannerSections: true).ToArray();
            var rootCounts = roots.GroupBy(root => root.Object).ToDictionary(group => group.Key, group => group.Count());
            var schemaIndex = schemaNames.Where(pair => pair.Value.Length > 0)
                .GroupBy(pair => (pair.Key.Item2, pair.Value)).ToDictionary(group => group.Key, group => group.Select(pair => pair.Key).ToArray());
            var bindings = new Dictionary<(uint, uint), List<(uint, uint)>>();
            foreach (var root in roots)
            {
                if (rootCounts[root.Object] != 1 || !schemaIndex.TryGetValue((root.Object.Item2, Text(root.Fields, 3)), out var matches) || matches.Length != 1) continue;
                if (!bindings.TryGetValue(matches[0], out var targets)) bindings[matches[0]] = targets = [];
                targets.Add(root.Object);
            }
            var configs = new Dictionary<(uint, uint), List<string[]>>();
            foreach (var entry in entries.Where(entry => entry.Tag == 0x201))
            {
                var reference = Bytes(entry.Fields, 3); var encoded = Bytes(entry.Fields, 10);
                if (reference.Length != 8 || encoded.Length % 2 != 0) continue;
                string[] names;
                try { names = Wide.GetString(encoded).Split('\0'); }
                catch (DecoderFallbackException) { continue; }
                if (names.Length < 15 || names.Skip(15).Any(name => name.Length > 0)) continue;
                var target = (BinaryPrimitives.ReadUInt32LittleEndian(reference), BinaryPrimitives.ReadUInt32LittleEndian(reference.AsSpan(4)));
                if (!configs.TryGetValue(target, out var options)) configs[target] = options = [];
                options.Add(names.Take(15).ToArray());
            }
            // Config records share an options schema across sections: only
            // their explicit Section ID owns the labels. Native schema/root
            // name+namespace must resolve uniquely; never use OID arithmetic.
            return bindings.Where(pair => pair.Value.Count == 1 && configs.TryGetValue(pair.Value[0], out var values) && values.Count == 1)
                .ToDictionary(pair => pair.Key, pair => configs[pair.Value[0]][0]);
        }

        internal Dictionary<string, (Entry Definition, List<Entry> Members)> RepeatGroups(List<Entry> entries)
        {
            var byKey = new Dictionary<((uint, uint), (uint, uint)), Entry>();
            foreach (var entry in entries) if (!byKey.TryAdd((entry.Object, entry.Schema), entry)) throw Invalid();
            var groups = new Dictionary<string, (Entry Definition, Dictionary<string, Entry> Members)>();
            var assigned = new Dictionary<string, string>();
            foreach (var (offset, block) in blocks)
            {
                if (block.Tag != 0xfffffffb || block.Size < 0x58) continue;
                if (!byKey.TryGetValue((Reference(offset + 0x20), Reference(offset + 0x28)), out var source) ||
                    !byKey.TryGetValue((Reference(offset + 0x30), Reference(offset + 0x38)), out var target) ||
                    source.Tag is not (0x100 or 0x300) || target.Tag != RepeatTag) continue;
                if (assigned.TryGetValue(source.Uid, out var previous) && previous != target.Uid) throw Invalid();
                assigned[source.Uid] = target.Uid;
                if (!groups.TryGetValue(target.Uid, out var group)) groups[target.Uid] = group = (target, new());
                group.Members[source.Uid] = source;
            }
            var result = new Dictionary<string, (Entry, List<Entry>)>();
            foreach (var group in groups.Values)
            {
                var shared = (group.Definition, group.Members.Values.ToList());
                foreach (var member in group.Members.Keys) result[member] = shared;
            }
            return result;
        }

        internal (Dictionary<string, SortedSet<string>> Memberships, HashSet<string> Represented) ContactGroups(List<Entry> entries)
        {
            var byKey = entries.ToDictionary(entry => (entry.Object, entry.Schema));
            var memberships = new Dictionary<string, SortedSet<string>>(); var represented = new HashSet<string>();
            foreach (var (offset, block) in blocks)
            {
                if (block.Tag != 0xfffffffb || block.Size < 0x58 || U32(offset + 0x50) != 0x40000) continue;
                if (!byKey.TryGetValue((Reference(offset + 0x20), Reference(offset + 0x28)), out var source) ||
                    !byKey.TryGetValue((Reference(offset + 0x30), Reference(offset + 0x38)), out var target) ||
                    source.Tag != 0x400 || target.Tag != 0x400 || Number(source.Fields, 13) != 1 || Number(target.Fields, 13) != 0) continue;
                var name = Text(source.Fields, 19);
                if (name.Length == 0) continue;
                if (!memberships.TryGetValue(target.Uid, out var names)) memberships[target.Uid] = names = new(StringComparer.Ordinal);
                names.Add(name); represented.Add(source.Uid);
            }
            return (memberships, represented);
        }
    }

    private static byte[] Bytes(Dictionary<ushort, byte[]> fields, ushort id) => fields.GetValueOrDefault(id) ?? Array.Empty<byte>();
    private static uint Number(Dictionary<ushort, byte[]> fields, ushort id, uint fallback = 0)
    {
        var bytes = Bytes(fields, id);
        if (bytes.Length is 0 or > 4) return fallback;
        uint value = 0;
        for (var index = 0; index < bytes.Length; index++) value |= (uint)bytes[index] << (8 * index);
        return value;
    }
    private static string[] Strings(Dictionary<ushort, byte[]> fields, ushort id)
    {
        var bytes = Bytes(fields, id);
        if (bytes.Length % 2 != 0) throw Invalid();
        try { return Wide.GetString(bytes).TrimEnd('\0').Split('\0').Select(value => value.Trim()).ToArray(); }
        catch (DecoderFallbackException) { throw Invalid(); }
    }
    private static string Text(Dictionary<ushort, byte[]> fields, ushort id) => Strings(fields, id)[0];
    private static string[]? PlannerSourceClock(Dictionary<ushort, byte[]> fields)
    {
        var first = Bytes(fields, 7); var last = Bytes(fields, 8);
        if (first.Length != 8 || last.Length != 8 || first[7] != 0 || last[7] != 0) return null;
        var start = Stamp(first); var end = Stamp(last);
        if (start is not { } begin || end is not { } finish || finish < begin) return null;
        var midnights = begin.TimeOfDay == TimeSpan.Zero && finish.TimeOfDay == TimeSpan.Zero;
        var sameDayHours = begin.Date == finish.Date && begin.Minute == 0 && begin.Second == 0 && finish.Minute == 0 && finish.Second == 0;
        if (!midnights && !sameDayHours) return null;
        // Original UI shows inclusive dates, but the original local clocks
        // are retained verbatim. These X properties are not recurrence/TZ rules.
        return ["X-MAGNOLIE-OR6-PLANNER-LOCAL-START:" + begin.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture),
            "X-MAGNOLIE-OR6-PLANNER-LOCAL-END:" + finish.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture)];
    }
    private static DateTime? Stamp(byte[] value)
    {
        if (value.Length == 0 || value.AsSpan().SequenceEqual(new byte[] { 2, 0, 2, 2, 2, 2, 2, 2 })) return null;
        if (value.Length != 8) throw Invalid();
        try
        {
            return new DateTime(BinaryPrimitives.ReadUInt16LittleEndian(value), value[2], value[3], value[4], value[5], value[6]);
        }
        catch (ArgumentOutOfRangeException) { throw Invalid(); }
    }

    private static (string Date, string Time) Date(Dictionary<ushort, byte[]> fields, ushort id) => Stamp(Bytes(fields, id)) is { } when
        ? (when.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), when.ToString("HH:mm", CultureInfo.InvariantCulture)) : ("", "");

    private static JsonObject Common(Dictionary<ushort, byte[]> fields, string uid)
    {
        // Only the human-readable description's line endings, not opaque IDs
        // or contact fields. Match the existing Python splitlines behavior for
        // native CRLF/CR/LF without leaving a CR in titles or note paragraphs.
        var lines = Text(fields, 9).Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n').Split('\n');
        var note = string.Join('\n', lines.Skip(1)); var body = Text(fields, 16);
        if (body.Length > 0) note += (note.Length > 0 ? "\n" : "") + body;
        return new() { ["titel"] = lines[0], ["notiz"] = note, ["uid"] = uid,
            ["geaendert"] = 0, ["vertraulich"] = Number(fields, 1) != 0 };
    }

    private static JsonObject? FiniteSeries((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned, bool taskStates = false)
    {
        if (group.Members.Count == 0 || group.Members.Select(member => member.Tag).Distinct().Count() != 1) return null;
        var metadata = group.Definition.Fields;
        DateTime[]? Dates(ushort id)
        {
            var raw = Bytes(metadata, id);
            if (raw.Length == 0 || raw.Length % 8 != 0) return null;
            var values = new List<DateTime>();
            for (var offset = 0; offset < raw.Length; offset += 8)
            { if (Stamp(raw.AsSpan(offset, 8).ToArray()) is not { } stamp) return null; values.Add(stamp); }
            return values.ToArray();
        }
        var starts = Dates(12); var ends = Dates(13);
        if (starts is null || ends is null || starts.Length != ends.Length || starts.Length < group.Members.Count ||
            !starts.SequenceEqual(starts.OrderBy(value => value).Distinct())) return null;
        var ordered = group.Members.OrderBy(member => Number(member.Fields, 14)).ToArray();
        var basis = ordered[0].Fields;
        bool CompareField(ushort field) => field is not (7 or 8 or 14) && (!taskStates || field is not (3 or 19 or 20));
        var comparable = basis.Where(pair => CompareField(pair.Key)).ToDictionary(pair => pair.Key, pair => pair.Value);
        var indices = ordered.Select(member => (long)Number(member.Fields, 14)).ToArray();
        if (indices.Distinct().Count() != indices.Length || indices.Any(index => index >= starts.Length)) return null;
        var missing = Enumerable.Range(0, starts.Length).Except(indices.Select(index => (int)index)).ToArray();
        var missingSet = missing.ToHashSet();
        if (missing.Any(index => orphaned.Contains((ordered[0].Schema, (uint)index, starts[index])))) return null;
        for (var position = 0; position < ordered.Length; position++)
        {
            var fields = ordered[position].Fields; var index = (int)indices[position];
            var other = fields.Where(pair => CompareField(pair.Key)).ToDictionary(pair => pair.Key, pair => pair.Value);
            if (Number(fields, 10) != 1 || comparable.Count != other.Count ||
                comparable.Any(pair => !other.TryGetValue(pair.Key, out var value) || !pair.Value.AsSpan().SequenceEqual(value)) ||
                Stamp(Bytes(fields, 7)) != starts[index] || Stamp(Bytes(fields, 8)) != ends[index] || ends[index] < starts[index]) return null;
        }
        var first = starts[0]; var end = ends[0]; var duration = end - first;
        if (starts.Where((start, index) => start.TimeOfDay != first.TimeOfDay || ends[index] - start != duration).Any() ||
            Text(basis, 9).Length == 0) return null;
        string Day(DateTime value) => value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        string Compact(DateTime value) => value.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture);
        var result = Common(basis, group.Definition.Uid);
        if (!taskStates && Categories(basis) is { Length: > 0 } category) result["kategorien"] = category;
        result["datum"] = Day(first); result["zeit"] = first.ToString("HH:mm", CultureInfo.InvariantCulture);
        result["endDatum"] = end.Date != first.Date ? Day(end) : "";
        result["endZeit"] = end.ToString("HH:mm", CultureInfo.InvariantCulture); result["vorlaeufig"] = Number(basis, 18) != 0;
        var rawLines = new JsonArray("DTSTART:" + Compact(first), "DTEND:" + Compact(end));
        var recurrence = new JsonObject { ["art"] = "custom", ["bis"] = "", ["intervall"] = 1, ["ordinal"] = 0,
            ["wochentag"] = "", ["rruleForm"] = "", ["daten"] = new JsonArray(starts.Where((value, index) => !missingSet.Contains(index)).Select(value => (JsonNode?)Day(value)).ToArray()) };
        var selected = Bytes(metadata, 5); var until = Stamp(Bytes(metadata, 7)); var interval = (long)Number(metadata, 4) + 1;
        if (Number(metadata, 3) == 1 && Number(metadata, 8) == 0 && Number(metadata, 11) == 0 &&
            selected.Length is > 0 and <= 14 && selected.Length % 2 == 0 && until is not null && interval is >= 1 and <= 3660)
        {
            var weekdays = Enumerable.Range(0, selected.Length / 2)
                .Select(index => (int)BinaryPrimitives.ReadUInt16LittleEndian(selected.AsSpan(index * 2, 2))).ToArray();
            if (weekdays.Distinct().Count() == weekdays.Length && weekdays.All(value => value <= 6))
            {
                var initial = DateOnly.FromDateTime(first).DayNumber;
                var week = initial - (int)first.DayOfWeek; var limit = DateOnly.FromDateTime(until.Value).DayNumber;
                var expected = new List<int>();
                while (week <= limit && expected.Count <= starts.Length)
                {
                    foreach (var weekday in weekdays.OrderBy(value => value))
                        if (week + weekday >= initial && week + weekday <= limit) expected.Add(week + weekday);
                    week += 7 * (int)interval;
                }
                if (expected.SequenceEqual(starts.Select(value => DateOnly.FromDateTime(value).DayNumber)))
                {
                    var tokens = new[] { "SU", "MO", "TU", "WE", "TH", "FR", "SA" };
                    rawLines.Add($"RRULE:FREQ=WEEKLY;INTERVAL={interval};BYDAY={string.Join(',', weekdays.OrderBy(value => value).Select(day => tokens[day]))};WKST=SU;UNTIL={until.Value.ToString("yyyyMMdd", CultureInfo.InvariantCulture)}T235959");
                    if (weekdays.SequenceEqual(new[] { (int)first.DayOfWeek }))
                        recurrence = new() { ["art"] = "weekly", ["bis"] = Day(until.Value), ["intervall"] = (int)interval,
                            ["ordinal"] = 0, ["wochentag"] = "", ["rruleForm"] = "" };
                    else { result["icsKomplex"] = true; result["icsSerienUid"] = group.Definition.Uid; }
                }
            }
        }
        if (rawLines.Count == 2) rawLines.Add("RDATE:" + string.Join(',', starts.Select(Compact)));
        if (missing.Length > 0)
        {
            rawLines.Add("EXDATE:" + string.Join(',', missing.Select(index => Compact(starts[index]))));
            result["icsKomplex"] = true; result["icsSerienUid"] = group.Definition.Uid;
            result["icsAusnahmeTermine"] = new JsonArray(missing.Select(index => (JsonNode)new JsonObject {
                ["datum"] = Day(starts[index]), ["zeit"] = starts[index].ToString("HH:mm", CultureInfo.InvariantCulture) }).ToArray());
        }
        result["wiederholung"] = recurrence; result["icsRoundtrip"] = rawLines;
        return result;
    }

    private static List<JsonObject>? CalendarHistorySeries((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned, Document document)
    {
        if (group.Members.Count == 0 || group.Members.Any(member => member.Tag != 0x100 || !document.CalendarIndexDeclared(member) ||
            member.Fields.ContainsKey(14) && Bytes(member.Fields, 14).Length != 4) || group.Members.Select(member => member.Schema).Distinct().Count() != 1) return null;
        var arrays = new List<DateTime[]>();
        foreach (ushort fid in new ushort[] { 12, 13 })
        {
            var raw = Bytes(group.Definition.Fields, fid);
            if (raw.Length == 0 || raw.Length % 8 != 0) return null;
            var values = Enumerable.Range(0, raw.Length / 8).Select(i => Stamp(raw.AsSpan(i * 8, 8).ToArray())).ToArray();
            if (values.Any(value => value is null)) return null;
            arrays.Add(values.Select(value => value!.Value).ToArray());
        }
        var starts = arrays[0]; var ends = arrays[1]; var anchor = Stamp(Bytes(group.Definition.Fields, 6));
        if (anchor is null || starts.Length != ends.Length || !starts.SequenceEqual(starts.Distinct().Order())) return null;
        var history = new List<Entry>(); var current = new List<Entry>(); var seen = new HashSet<DateTime>();
        var basis = group.Members[0].Fields;
        foreach (var member in group.Members)
        {
            var fields = member.Fields; var start = Stamp(Bytes(fields, 7)); var end = Stamp(Bytes(fields, 8));
            if (start is not { } begin || end is not { } finish || finish < begin || !seen.Add(begin) || begin.Date < anchor.Value.Date ||
                basis.Keys.Concat(fields.Keys).Distinct().Any(fid => fid is not (7 or 8 or 14) &&
                    (basis.ContainsKey(fid) != fields.ContainsKey(fid) || !Bytes(basis, fid).AsSpan().SequenceEqual(Bytes(fields, fid))))) return null;
            if (begin < starts[0]) history.Add(member);
            else
            {
                var index = Number(fields, 14);
                if (index >= starts.Length || begin != starts[index] || finish != ends[index]) return null;
                current.Add(member);
            }
        }
        history = history.OrderBy(member => Stamp(Bytes(member.Fields, 7))).ToList();
        if (history.Count == 0 || current.Count == 0 || !history.Select(member => Number(member.Fields, 14)).SequenceEqual(Enumerable.Range(0, history.Count).Select(i => (uint)i))) return null;
        var indices = current.Select(member => Number(member.Fields, 14)).ToHashSet();
        if (indices.Count != current.Count || Enumerable.Range(0, starts.Length).Any(i => !indices.Contains((uint)i) && orphaned.Contains((group.Members[0].Schema, (uint)i, starts[i])))) return null;
        var metadata = new Dictionary<ushort, byte[]>(group.Definition.Fields);
        foreach (var (fid, source) in new[] { ((ushort)12, (ushort)7), ((ushort)13, (ushort)8) })
            metadata[fid] = history.SelectMany(member => Bytes(member.Fields, source)).Concat(Bytes(metadata, fid)).ToArray();
        var projected = new List<Entry>();
        foreach (var member in history.Concat(current))
        {
            var index = projected.Count < history.Count ? (uint)projected.Count : (uint)history.Count + Number(member.Fields, 14);
            var fields = new Dictionary<ushort, byte[]>(member.Fields) { [14] = new byte[4] };
            BinaryPrimitives.WriteUInt32LittleEndian(fields[14], index); projected.Add(member with { Fields = fields });
        }
        // Exact observed historical clocks plus exact current arrays only; no
        // extrapolated old rule dates or generic task index recovery.
        var master = FiniteSeries((group.Definition with { Fields = metadata }, projected), orphaned);
        if (master is null) return null;
        foreach (var (fid, name) in new[] { ((ushort)12, "STARTS"), ((ushort)13, "ENDS") })
        {
            var raw = Bytes(group.Definition.Fields, fid);
            master["icsRoundtrip"]!.AsArray().Add("X-MAGNOLIE-OR6-CALENDAR-TEMPLATE-" + name + ":" + string.Join(',',
                Enumerable.Range(0, raw.Length / 8).Select(i => Stamp(raw.AsSpan(i * 8, 8).ToArray())!.Value.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture))));
        }
        return [master];
    }

    private static List<JsonObject>? FiniteCalendarSeries((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned, Document document)
    {
        var ordinary = FiniteSeries(group, orphaned);
        if (ordinary is not null) return [ordinary];
        var historical = CalendarHistorySeries(group, orphaned, document);
        if (historical is not null) return historical;
        if (group.Members.Count == 0 || group.Members.Any(member => member.Tag != 0x100)) return null;
        var arrays = new List<DateTime[]>();
        foreach (ushort fid in new ushort[] { 12, 13 })
        {
            var raw = Bytes(group.Definition.Fields, fid);
            if (raw.Length == 0 || raw.Length % 8 != 0) return null;
            var dates = Enumerable.Range(0, raw.Length / 8).Select(i => Stamp(raw.AsSpan(i * 8, 8).ToArray())).ToArray();
            if (dates.Any(date => date is null)) return null;
            arrays.Add(dates.Select(date => date!.Value).ToArray());
        }
        var starts = arrays[0]; var ends = arrays[1];
        if (starts.Length != ends.Length || group.Members.Any(member => !document.CalendarIndexDeclared(member) ||
            member.Fields.ContainsKey(14) && Bytes(member.Fields, 14).Length != 4)) return null;
        var ordered = group.Members.OrderBy(member => Number(member.Fields, 14)).ToArray();
        var indices = ordered.Select(member => Number(member.Fields, 14)).ToArray();
        if (indices.Distinct().Count() != indices.Length || indices.Any(index => index >= starts.Length)) return null;
        var basis = ordered[0].Fields;
        bool Known(ushort fid) => fid is 3 or 7 or 8 or 9 or 14;
        var projected = new List<Entry>();
        foreach (var member in ordered)
        {
            var fields = member.Fields; var index = Number(fields, 14);
            var start = Stamp(Bytes(fields, 7)); var end = Stamp(Bytes(fields, 8));
            if (start is null || end is null || end < start || Text(fields, 9).Length == 0 ||
                basis.Keys.Concat(fields.Keys).Distinct().Any(fid => !Known(fid) &&
                    (basis.ContainsKey(fid) != fields.ContainsKey(fid) || !Bytes(basis, fid).AsSpan().SequenceEqual(Bytes(fields, fid)))) ||
                Categories(basis).Length > 0 && Categories(fields).Length == 0) return null;
            var canonical = new Dictionary<ushort, byte[]>(basis) {
                [7] = Bytes(group.Definition.Fields, 12).AsSpan((int)index * 8, 8).ToArray(),
                [8] = Bytes(group.Definition.Fields, 13).AsSpan((int)index * 8, 8).ToArray(), [14] = new byte[4] };
            BinaryPrimitives.WriteUInt32LittleEndian(canonical[14], index);
            projected.Add(member with { Fields = canonical });
        }
        var master = FiniteSeries((group.Definition, projected), orphaned);
        if (master is null) return null;
        var converted = new List<JsonObject> { master };
        string Compact(DateTime value) => value.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture);
        string Day(DateTime value) => value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        foreach (var member in ordered)
        {
            var fields = member.Fields; var index = Number(fields, 14);
            var start = Stamp(Bytes(fields, 7))!.Value; var end = Stamp(Bytes(fields, 8))!.Value;
            if (start == starts[index] && end == ends[index] && Bytes(fields, 9).AsSpan().SequenceEqual(Bytes(basis, 9)) && Categories(fields) == Categories(basis)) continue;
            master["icsRoundtrip"]!.AsArray().Add("EXDATE:" + Compact(starts[index]));
            master["icsKomplex"] = true; master["icsSerienUid"] = group.Definition.Uid;
            var child = Common(fields, member.Uid);
            child["datum"] = Day(start); child["zeit"] = start.ToString("HH:mm", CultureInfo.InvariantCulture);
            child["endDatum"] = end.Date != start.Date ? Day(end) : ""; child["endZeit"] = end.ToString("HH:mm", CultureInfo.InvariantCulture);
            child["kategorien"] = Categories(fields); child["vorlaeufig"] = Number(fields, 18) != 0; child["icsSerienUid"] = group.Definition.Uid;
            child["icsRoundtrip"] = new JsonArray("RECURRENCE-ID:" + Compact(starts[index]), "DTSTART:" + Compact(start), "DTEND:" + Compact(end),
                "X-MAGNOLIE-OR6-OBJECT-UID:" + member.Uid);
            converted.Add(child);
        }
        return converted;
    }

    private static (Entry Definition, List<Entry> Members)? TaskSegmentMembers((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned)
    {
        var arrays = new List<DateTime[]>();
        foreach (ushort fid in new ushort[] { 12, 13 })
        {
            var raw = Bytes(group.Definition.Fields, fid);
            if (raw.Length == 0 || raw.Length % 8 != 0) return null;
            var values = Enumerable.Range(0, raw.Length / 8).Select(i => Stamp(raw.AsSpan(i * 8, 8).ToArray())).ToArray();
            if (values.Any(value => value is null)) return null;
            arrays.Add(values.Select(value => value!.Value).ToArray());
        }
        var starts = arrays[0]; var ends = arrays[1];
        if (starts.Length != ends.Length || !starts.SequenceEqual(starts.Distinct().Order()) || starts.Where((start, i) => ends[i] < start).Any()) return null;
        var history = new List<Entry>(); var current = new List<Entry>(); var seen = new HashSet<DateTime>();
        foreach (var member in group.Members)
        {
            var start = Stamp(Bytes(member.Fields, 7)); var end = Stamp(Bytes(member.Fields, 8));
            if (start is not { } begin || end is not { } finish || finish < begin || !seen.Add(begin)) return null;
            if (begin < starts[0])
            {
                var anchor = Stamp(Bytes(group.Definition.Fields, 6));
                if (anchor is null || begin.Date < anchor.Value.Date) return null;
                history.Add(member);
            }
            else
            {
                var index = Number(member.Fields, 14);
                if (index >= starts.Length) return null;
                current.Add(member);
            }
        }
        if (current.Count == 0 || group.Members.Select(member => member.Schema).Distinct().Count() != 1) return null;
        var indices = current.Select(member => Number(member.Fields, 14)).ToHashSet();
        var recovered = current.Any(member => Stamp(Bytes(member.Fields, 7)) != starts[Number(member.Fields, 14)] || Stamp(Bytes(member.Fields, 8)) != ends[Number(member.Fields, 14)]);
        if (recovered)
        {
            // Original All edits can copy index0 to every live linked task and
            // leave template dates stale. Only a complete uniquely dated set,
            // zero-copy indices or a full unique slot set, can recover this form.
            if (current.Count != starts.Length || !(indices.SetEquals(new uint[] { 0 }) || indices.SetEquals(Enumerable.Range(0, starts.Length).Select(i => (uint)i)))) return null;
            var actual = current.Select(member => Stamp(Bytes(member.Fields, 7))!.Value).Concat(starts).ToHashSet();
            if (orphaned.Any(value => value.Schema == current[0].Schema && value.Start is { } start && actual.Contains(start))) return null;
            current = current.OrderBy(member => Stamp(Bytes(member.Fields, 7))).ToList();
        }
        if (history.Count == 0 && !recovered) return group;
        if (Enumerable.Range(0, starts.Length).Any(i => !indices.Contains((uint)i) && orphaned.Contains((current[0].Schema, (uint)i, starts[i])))) return null;
        history = history.OrderBy(member => Stamp(Bytes(member.Fields, 7))).ToList();
        // Exact observed linked clocks only; no old template dates are invented
        // as live occurrences. FiniteSeries must still independently match the
        // entire actual date set before emitting a rule, otherwise uses RDATE.
        var metadata = new Dictionary<ushort, byte[]>(group.Definition.Fields);
        foreach (ushort fid in new ushort[] { 12, 13 })
        {
            ushort source = fid == 12 ? (ushort)7 : (ushort)8;
            metadata[fid] = history.SelectMany(member => Bytes(member.Fields, source))
                .Concat(recovered ? current.SelectMany(member => Bytes(member.Fields, source)) : Bytes(metadata, fid)).ToArray();
        }
        var projected = new List<Entry>();
        foreach (var member in history.Concat(current))
        {
            var index = recovered || projected.Count < history.Count ? (uint)projected.Count : (uint)history.Count + Number(member.Fields, 14);
            var fields = new Dictionary<ushort, byte[]>(member.Fields); var encoded = new byte[4];
            BinaryPrimitives.WriteUInt32LittleEndian(encoded, index); fields[14] = encoded;
            projected.Add(member with { Fields = fields });
        }
        return (group.Definition with { Fields = metadata }, projected);
    }

    private static string Categories(Dictionary<ushort, byte[]> fields) => string.Join(", ", Strings(fields, 3).Where(value => value.Length > 0).Distinct());

    private static List<JsonObject>? FiniteTaskSeries((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned)
    {
        // Validate the same original native links/arrays/finite expansion as
        // appointments, but retain one task series rather than loose tasks.
        if (group.Members.Any(member => Number(member.Fields, 20) is not (1 or 2 or 4))) return null;
        foreach (var member in group.Members) _ = Date(member.Fields, 19);
        var templates = new Dictionary<ushort, byte[]> { [12] = Bytes(group.Definition.Fields, 12), [13] = Bytes(group.Definition.Fields, 13) };
        var projected = TaskSegmentMembers(group, orphaned);
        if (projected is null) return null;
        group = projected.Value;
        var series = FiniteSeries(group, orphaned, taskStates: true);
        if (series is null) return null;
        var fields = group.Members[0].Fields;
        var allDone = group.Members.All(member => Number(member.Fields, 20) == 4);
        var priority = Number(fields, 18, 3);
        var result = Common(fields, group.Definition.Uid);
        var categories = Categories(fields);
        if (categories.Length > 0) result["kategorien"] = categories;
        result["startDatum"] = series["datum"]!.DeepClone(); result["startZeit"] = series["zeit"]!.DeepClone();
        result["faellig"] = series["endDatum"]!.GetValue<string>() is { Length: > 0 } end ? end : series["datum"]!.GetValue<string>();
        result["faelligZeit"] = series["endZeit"]!.DeepClone(); result["prio"] = priority < 3 ? priority + 1 : 2;
        result["erledigt"] = allDone;
        result["icsSerienUid"] = group.Definition.Uid;
        result["icsRoundtrip"] = new JsonArray(series["icsRoundtrip"]!.AsArray().Select(value => {
            var line = value!.GetValue<string>();
            return (JsonNode?)JsonValue.Create(line.StartsWith("DTEND:", StringComparison.Ordinal) ? "DUE:" + line[6..] : line);
        }).ToArray());
        foreach (var (fid, name) in new[] { ((ushort)12, "STARTS"), ((ushort)13, "DUES") })
            if (!templates[fid].AsSpan().SequenceEqual(Bytes(group.Definition.Fields, fid)))
                result["icsRoundtrip"]!.AsArray().Add("X-MAGNOLIE-OR6-TASK-TEMPLATE-" + name + ":" + string.Join(',',
                    Enumerable.Range(0, templates[fid].Length / 8).Select(i => Stamp(templates[fid].AsSpan(i * 8, 8).ToArray())!.Value.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture))));
        var converted = new List<JsonObject> { result };
        foreach (var member in group.Members.OrderBy(value => Number(value.Fields, 14)))
            {
                var completed = Number(member.Fields, 20) == 4; var memberCategories = Categories(member.Fields);
                if (completed == allDone && memberCategories == categories) continue;
                var start = Stamp(Bytes(member.Fields, 7))!.Value; var due = Stamp(Bytes(member.Fields, 8))!.Value;
                string Compact(DateTime value) => value.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture);
                result["icsRoundtrip"]!.AsArray().Add("EXDATE:" + Compact(start));
                var done = Common(member.Fields, member.Uid);
                done["startDatum"] = start.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture); done["startZeit"] = start.ToString("HH:mm", CultureInfo.InvariantCulture);
                done["faellig"] = due.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture); done["faelligZeit"] = due.ToString("HH:mm", CultureInfo.InvariantCulture);
                done["prio"] = result["prio"]!.DeepClone(); done["erledigt"] = completed; done["kategorien"] = memberCategories; done["icsSerienUid"] = group.Definition.Uid;
                done["icsRoundtrip"] = new JsonArray("RECURRENCE-ID:" + Compact(start), "DTSTART:" + Compact(start), "DUE:" + Compact(due),
                    "STATUS:" + (completed ? "COMPLETED" : "NEEDS-ACTION"), "PERCENT-COMPLETE:" + (completed ? "100" : "0"));
                converted.Add(done);
            }
        return converted;
    }

    internal static ExchangeImportResult Read(byte[] raw)
    {
        var appointments = new JsonArray(); var tasks = new JsonArray(); var contacts = new JsonArray(); var notes = new JsonArray(); var anniversaries = new JsonArray();
        var skipped = 0; var recurring = 0;
        var document = new Document(raw); var entries = document.Entries(repeats: true).ToList();
        var plannerKeys = document.PlannerKeys(entries);
        var groups = document.RepeatGroups(entries); var consumed = new HashSet<string>();
        var (memberships, representedGroups) = document.ContactGroups(entries);
        var orphaned = entries.Where(entry => (entry.Tag is 0x100 or 0x300) && Number(entry.Fields, 10) != 0 && !groups.ContainsKey(entry.Uid))
            .Select(entry => (entry.Schema, Number(entry.Fields, 14), Stamp(Bytes(entry.Fields, 7)))).ToHashSet();
        var evaluated = new Dictionary<string, List<JsonObject>?>();
        foreach (var entry in entries)
        {
            var (tag, fields, uid) = (entry.Tag, entry.Fields, entry.Uid);
            if (consumed.Contains(uid)) continue;
            if (tag is 0x100 or 0x300)
            {
                var title = Text(fields, 9); if (title.Length == 0) continue;
                // Converted sets are expandable; skipped native sets are not
                // retained as unresolved source-calendar rules.
                if (Number(fields, 10) != 0)
                {
                    if (groups.TryGetValue(uid, out var group))
                    {
                        if (!evaluated.TryGetValue(group.Definition.Uid, out var series))
                        {
                            if (tag == 0x300) evaluated[group.Definition.Uid] = series = FiniteTaskSeries(group, orphaned);
                            else
                            {
                                evaluated[group.Definition.Uid] = series = FiniteCalendarSeries(group, orphaned, document);
                            }
                        }
                        if (series is not null)
                        { foreach (var value in series) (tag == 0x300 ? tasks : appointments).Add(value); foreach (var member in group.Members) consumed.Add(member.Uid); continue; }
                    }
                    skipped++; continue;
                }
                var start = Date(fields, 7); var end = Date(fields, 8);
                var common = Common(fields, uid);
                if (tag == 0x100)
                {
                    if (start.Date.Length == 0 || end.Date.Length == 0 || string.CompareOrdinal(end.Date + end.Time, start.Date + start.Time) < 0) { skipped++; continue; }
                    if (Categories(fields) is { Length: > 0 } category) common["kategorien"] = category;
                    common["datum"] = start.Date; common["zeit"] = start.Time; common["endDatum"] = end.Date != start.Date ? end.Date : "";
                    common["endZeit"] = end.Time; common["vorlaeufig"] = Number(fields, 18) != 0; appointments.Add(common);
                }
                else
                {
                    var priority = Number(fields, 18, 3);
                    common["startDatum"] = start.Date; common["startZeit"] = start.Time;
                    common["faellig"] = end.Date; common["faelligZeit"] = end.Time; common["prio"] = priority < 3 ? priority + 1 : 2;
                    var completed = Date(fields, 19).Date.Length > 0;
                    // Independently toggled original-program states: an open
                    // task (1/2) can retain a completion stamp after reexport.
                    // Preserve the existing fallback for unverified layouts.
                    var status = Number(fields, 20);
                    common["erledigt"] = status is 1 or 2 or 4 ? status == 4 : completed; tasks.Add(common);
                }
            }
            else if (tag == 0x400)
            {
                var first = Text(fields, 17); var last = Text(fields, 19); var company = Text(fields, 23);
                if (first.Length + last.Length + company.Length + Text(fields, 33).Length + Text(fields, 35).Length == 0) continue;
                if (Number(fields, 13) != 0) { if (!representedGroups.Contains(uid)) skipped++; continue; }
                var phoneEntries = new JsonArray(Strings(fields, 33).Select((value, index) => (value, index))
                    .Where(pair => pair.value.Length > 0).Select(pair => (JsonNode)new JsonObject {
                        ["wert"] = pair.value, ["typen"] = pair.index switch {
                            0 => new JsonArray("WORK", "VOICE"), 3 => new JsonArray("HOME", "VOICE"),
                            6 => new JsonArray("WORK", "FAX"), _ => new JsonArray("VOICE") } }).ToArray());
                var emails = Strings(fields, 35).Where(value => value.Length > 0).Distinct(StringComparer.Ordinal).ToArray();
                var addresses = new JsonArray(); var columns = new[] { Strings(fields, 28), Strings(fields, 31), Strings(fields, 29), Strings(fields, 32), Strings(fields, 30) };
                var keys = new[] { "strasse", "plz", "ort", "land", "region" };
                for (var index = 0; index < columns.Max(column => column.Length); index++)
                {
                    var address = new JsonObject(); var nonempty = false;
                    for (var column = 0; column < columns.Length; column++)
                    {
                        var value = index < columns[column].Length ? columns[column][index] : "";
                        if (keys[column] != "region" || value.Length > 0) address[keys[column]] = value;
                        nonempty |= value.Length > 0;
                    }
                    if (!nonempty) continue;
                    address["typen"] = index == 0 ? new JsonArray("WORK") : index == 1 ? new JsonArray("HOME") : new JsonArray(); addresses.Add(address);
                }
                var contact = new JsonObject { ["vorname"] = first, ["nachname"] = last, ["firma"] = company, ["uid"] = uid, ["geaendert"] = 0,
                    ["telefon"] = phoneEntries.FirstOrDefault()?["wert"]?.GetValue<string>() ?? "", ["mobil"] = "", ["telefone"] = phoneEntries,
                    ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(value => (JsonNode)JsonValue.Create(value)!).ToArray()),
                    ["anschriften"] = addresses, ["notiz"] = Text(fields, 39) };
                var categories = Strings(fields, 3).Where(value => value.Length > 0)
                    .Concat(memberships.GetValueOrDefault(uid) ?? new SortedSet<string>(StringComparer.Ordinal))
                    .Distinct(StringComparer.Ordinal).ToArray();
                if (categories.Length > 0)
                {
                    string Escape(string value) => value.Replace("\r\n", "\n").Replace("\r", "\n").Replace("\\", "\\\\").Replace(";", "\\;").Replace(",", "\\,").Replace("\n", "\\n");
                    contact["vcardRoundtrip"] = new JsonArray("CATEGORIES:" + string.Join(',', categories.Select(Escape)));
                }
                if (addresses.Count > 0) foreach (var key in keys.Where(key => key != "region")) contact[key] = addresses[0]![key]!.DeepClone();
                var birthday = Date(fields, 41).Date; if (birthday.Length > 0) contact["geburtstag"] = birthday;
                var note = Text(fields, 39);
                foreach (var (id, label) in new (ushort, string)[] { (16, "Title"), (18, "Middle name"), (20, "Suffix"), (22, "Position"),
                    (25, "Department"), (27, "Assistant"), (30, "State"), (37, "URL"), (40, "Mail merge name"), (43, "Spouse"), (44, "Children") })
                {
                    var value = string.Join("; ", Strings(fields, id).Where(value => value.Length > 0));
                    if (value.Length > 0) note += (note.Length > 0 ? "\n" : "") + label + ": " + value;
                }
                // Opaque source slots, not guessed phone labels or dialable suffixes.
                var extensions = Strings(fields, 34);
                for (int index = 0; index < extensions.Length; index++)
                    if (extensions[index].Length > 0) note += (note.Length > 0 ? "\n" : "") + $"Lotus Extn slot {index + 1}: {extensions[index]}";
                for (ushort id = 46; id < 66; id++) { var value = Text(fields, id); if (value.Length > 0) note += $"\nCustom {id - 45}: {value}"; }
                contact["notiz"] = note; contacts.Add(contact);
            }
            else if (tag == 0x510)
            {
                var title = Text(fields, 7); var body = Bytes(fields, 8);
                // Unknown body format: omit/count the whole note, not an empty
                // title-only approximation or guessed plaintext. The existing
                // import preview reports omissions. Known malformed RTF remains
                // a strict error; structural validation above is unchanged.
                if (body.Length <= 1024 * 1024 && body.AsSpan().IndexOf("{\\rtf"u8) < 0 && body.Any(value => value is not (0 or 255 or 2)))
                { skipped++; continue; }
                var text = RtfText(body);
                if (title.Length + text.Length > 0) notes.Add(new JsonObject { ["titel"] = title, ["text"] = text, ["uid"] = uid });
            }
            else if (tag is 0x200 or 0x600)
            {
                if (Text(fields, 9).Length == 0) continue;
                var start = Date(fields, 7); var end = Date(fields, 8);
                if (start.Date.Length == 0 || end.Date.Length == 0 || string.CompareOrdinal(end.Date, start.Date) < 0 ||
                    Number(fields, 10) != 0 || Number(fields, 1) != 0)
                { skipped++; continue; }
                string[]? sourceClock = null;
                if (start.Time != "00:00" || end.Time != "23:59")
                {
                    sourceClock = tag == 0x200 ? PlannerSourceClock(fields) : null;
                    if (sourceClock is null) { skipped++; continue; }
                }
                var common = Common(fields, uid);
                if (sourceClock is not null) common["icsRoundtrip"] = new JsonArray(sourceClock.Select(value => JsonValue.Create(value)).ToArray());
                if (tag == 0x600 && Number(fields, 19) == 1 && (Number(fields, 18) & 0x10000) == 0 && start.Date == end.Date)
                    anniversaries.Add(new JsonObject { ["name"] = common["titel"]!.DeepClone(), ["datum"] = start.Date,
                        ["typ"] = "anniversary", ["notiz"] = common["notiz"]!.DeepClone(), ["uid"] = uid, ["geaendert"] = 0 });
                else if (tag == 0x200 || (Number(fields, 19) == 0 && (Number(fields, 18) & 0x10000) != 0 && start.Date == end.Date))
                {
                    if (tag == 0x200)
                    {
                        // Actual first-slot entries omit native KeyID19. Only
                        // the declared uint16 field has this verified default;
                        // absent source fields are not invented in notes below.
                        var keyId = document.PlannerZeroDefault(entry.Schema) && (!fields.ContainsKey(19) || Bytes(fields, 19).Length == 2)
                            ? Number(fields, 19) : uint.MaxValue;
                        if (plannerKeys.TryGetValue(entry.Schema, out var names) && keyId < PlannerColors.Length)
                        {
                            common["kategorien"] = names[(int)keyId];
                            common["akzentFarbe"] = PlannerColors[(int)keyId];
                        }
                        // Native schema names Row and KeyID are distinct. Do
                        // not present either number as a verified type/color.
                        foreach (var (field, label) in new[] { ((ushort)18, "Row"), ((ushort)19, "KeyID") })
                        {
                            if (!fields.ContainsKey(field)) continue;
                            var note = common["notiz"]!.GetValue<string>();
                            common["notiz"] = note + (note.Length > 0 ? "\n" : "") + "Lotus planner " + label + ": " + Number(fields, field).ToString(CultureInfo.InvariantCulture);
                        }
                    }
                    common["datum"] = start.Date; common["zeit"] = ""; common["endDatum"] = end.Date != start.Date ? end.Date : "";
                    common["endZeit"] = ""; common["vorlaeufig"] = false; appointments.Add(common);
                }
                else skipped++;
            }
            else if (tag is 0x700 or 0x900)
            {
                var title = Text(fields, tag == 0x900 ? (ushort)12 : (ushort)9);
                var ids = tag == 0x900 ? new ushort[] { 12, 14, 15 } : new ushort[] { 9, 18, 19, 20, 21 };
                if (!ids.Any(id => Text(fields, id).Length > 0)) continue;
                // Preserve basic records as text, without a callable contact or
                // bookmark action. Unsupported confidentiality/repeats stay out.
                if (Number(fields, 1) != 0 || (tag == 0x700 && Number(fields, 10) != 0)) { skipped++; continue; }
                string text;
                if (tag == 0x900) text = "Lotus Organizer: Web\nURL: " + Text(fields, 14) + "\n" + Text(fields, 15);
                else
                {
                    var start = Date(fields, 7); var end = Date(fields, 8);
                    if (start.Date.Length == 0 || end.Date.Length == 0 || string.CompareOrdinal(end.Date + end.Time, start.Date + start.Time) < 0)
                    { skipped++; continue; }
                    text = string.Join('\n', new[] { "Lotus Organizer: Calls", "Start: " + start.Date + " " + start.Time,
                        "End: " + end.Date + " " + end.Time, "Contact: " + string.Join(' ', new[] { Text(fields, 19), Text(fields, 20) }.Where(value => value.Length > 0)),
                        "Company: " + Text(fields, 21), "Phone: " + Text(fields, 18), "Status: " + Text(fields, 22),
                        "Completed: " + (Number(fields, 24) != 0 ? "true" : "false"), title });
                }
                notes.Add(new JsonObject { ["titel"] = title.Length > 0 ? title.Split('\n')[0].TrimEnd('\r') : "Lotus Organizer", ["text"] = text, ["uid"] = uid });
            }
        }
        return new(appointments, anniversaries, new JsonArray(), tasks, contacts, skipped, recurring,
            NativeLocalization.Gettext("OR6 import: appointments, tasks, contacts and plain-text notes. Verified finite appointment series, contact group memberships and known phone contexts are retained. Basic planner spans and annual anniversaries are retained; one-off anniversaries become all-day appointments, call and web records become text notes. Unsupported entries, layout, attachments and alarms are not transferred."), notes);
    }

    private static string RtfText(byte[] bytes)
    {
        var start = bytes.AsSpan().IndexOf("{\\rtf"u8);
        if (start < 0) { if (bytes.Any(value => value is not (0 or 255 or 2))) throw Invalid(); return ""; }
        if (bytes.Length - start > 1024 * 1024) throw Invalid();
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var source = Encoding.GetEncoding(1252).GetString(bytes, start, bytes.Length - start).TrimEnd('\0');
        var stack = new Stack<(bool Skip, int Fallback)>(); var output = new StringBuilder();
        var skip = false; var fallback = 1; var pending = 0; var position = 0;
        var destinations = new HashSet<string> { "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "objdata", "filetbl", "header", "footer", "fldinst", "datastore" };
        while (position < source.Length)
        {
            var ch = source[position++];
            if (ch == '{') { if (stack.Count >= 64) throw Invalid(); stack.Push((skip, fallback)); }
            else if (ch == '}')
            {
                if (stack.Count == 0) throw Invalid(); (skip, fallback) = stack.Pop();
                if (stack.Count == 0) { if (source[position..].Trim('\r', '\n', '\0').Length > 0) throw Invalid(); break; }
            }
            else if (ch == '\\')
            {
                if (position >= source.Length) throw Invalid(); var symbol = source[position];
                if (symbol is '\\' or '{' or '}') { position++; if (pending > 0) pending--; else if (!skip) output.Append(symbol); }
                else if (symbol == '\'')
                {
                    if (position + 3 > source.Length || !byte.TryParse(source.AsSpan(position + 1, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var value)) throw Invalid();
                    position += 3; if (pending > 0) pending--; else if (!skip) output.Append(Encoding.GetEncoding(1252).GetString(new[] { value }));
                }
                else if (symbol == '*') { skip = true; position++; }
                else if (!char.IsAsciiLetter(symbol)) { position++; if (!skip && symbol is '~' or '_') output.Append(symbol == '~' ? ' ' : '-'); }
                else
                {
                    var match = Control.Match(source, position); if (!match.Success) throw Invalid(); position += match.Length;
                    var word = match.Groups[1].Value; var number = match.Groups[2].Value;
                    if (destinations.Contains(word)) skip = true;
                    else if (word == "bin") { if (!int.TryParse(number, out var count) || count < 0 || count > source.Length - position) throw Invalid(); position += count; }
                    else if (word == "ansicpg" && number != "1252") throw Invalid();
                    else if (word == "uc") { if (!int.TryParse(number.Length > 0 ? number : "1", out fallback) || fallback is < 0 or > 16) throw Invalid(); }
                    else if (word == "u" && !skip)
                    {
                        if (!int.TryParse(number.Length > 0 ? number : "0", out var value) || value is < -32768 or > 65535) throw Invalid();
                        output.Append((char)(value & 65535)); pending = fallback;
                    }
                    else if (!skip) output.Append(word switch { "par" or "line" => "\n", "tab" => "\t", "emdash" => "—", "endash" => "–", "bullet" => "•", _ => "" });
                }
            }
            else if (ch is not ('\r' or '\n')) { if (pending > 0) pending--; else if (!skip) output.Append(ch); }
        }
        if (stack.Count > 0) throw Invalid();
        var result = output.ToString().TrimEnd('\n');
        try { Wide.GetByteCount(result); } catch (EncoderFallbackException) { throw Invalid(); }
        return result;
    }
}
