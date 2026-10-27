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
                    next = Address(U32(next + 0x20));
                }
                schemas.Add(Reference(offset + 12), (U32(offset + 0x2c), fields));
            }
        }

        internal IEnumerable<Entry> Entries(bool repeats = false)
        {
            foreach (var (offset, block) in blocks)
            {
                if (offset == 0 || block.Tag >= 0x80000000 && !(repeats && block.Tag == RepeatTag)) continue;
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
                    source.Tag != 0x100 || target.Tag != RepeatTag) continue;
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
        var lines = Text(fields, 9).Split('\n'); var note = string.Join('\n', lines.Skip(1)); var body = Text(fields, 16);
        if (body.Length > 0) note += (note.Length > 0 ? "\n" : "") + body;
        return new() { ["titel"] = lines[0], ["notiz"] = note, ["uid"] = uid,
            ["geaendert"] = 0, ["vertraulich"] = Number(fields, 1) != 0 };
    }

    private static JsonObject? FiniteSeries((Entry Definition, List<Entry> Members) group,
        HashSet<((uint, uint) Schema, uint Index, DateTime? Start)> orphaned)
    {
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
        var comparable = basis.Where(pair => pair.Key is not (7 or 8 or 14)).ToDictionary(pair => pair.Key, pair => pair.Value);
        var indices = ordered.Select(member => (long)Number(member.Fields, 14)).ToArray();
        if (indices.Distinct().Count() != indices.Length || indices.Any(index => index >= starts.Length)) return null;
        var missing = Enumerable.Range(0, starts.Length).Except(indices.Select(index => (int)index)).ToArray();
        var missingSet = missing.ToHashSet();
        if (missing.Any(index => orphaned.Contains((ordered[0].Schema, (uint)index, starts[index])))) return null;
        for (var position = 0; position < ordered.Length; position++)
        {
            var fields = ordered[position].Fields; var index = (int)indices[position];
            var other = fields.Where(pair => pair.Key is not (7 or 8 or 14)).ToDictionary(pair => pair.Key, pair => pair.Value);
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

    internal static ExchangeImportResult Read(byte[] raw)
    {
        var appointments = new JsonArray(); var tasks = new JsonArray(); var contacts = new JsonArray(); var notes = new JsonArray();
        var skipped = 0; var recurring = 0;
        var document = new Document(raw); var entries = document.Entries(repeats: true).ToList();
        var groups = document.RepeatGroups(entries); var consumed = new HashSet<string>();
        var (memberships, representedGroups) = document.ContactGroups(entries);
        var orphaned = entries.Where(entry => entry.Tag == 0x100 && Number(entry.Fields, 10) != 0 && !groups.ContainsKey(entry.Uid))
            .Select(entry => (entry.Schema, Number(entry.Fields, 14), Stamp(Bytes(entry.Fields, 7)))).ToHashSet();
        var evaluated = new Dictionary<string, JsonObject?>();
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
                    if (tag == 0x100 && groups.TryGetValue(uid, out var group))
                    {
                        if (!evaluated.TryGetValue(group.Definition.Uid, out var series))
                            evaluated[group.Definition.Uid] = series = FiniteSeries(group, orphaned);
                        if (series is not null)
                        { appointments.Add(series); foreach (var member in group.Members) consumed.Add(member.Uid); continue; }
                    }
                    skipped++; continue;
                }
                var start = Date(fields, 7); var end = Date(fields, 8);
                var common = Common(fields, uid);
                if (tag == 0x100)
                {
                    if (start.Date.Length == 0 || end.Date.Length == 0 || string.CompareOrdinal(end.Date + end.Time, start.Date + start.Time) < 0) { skipped++; continue; }
                    common["datum"] = start.Date; common["zeit"] = start.Time; common["endDatum"] = end.Date != start.Date ? end.Date : "";
                    common["endZeit"] = end.Time; common["vorlaeufig"] = Number(fields, 18) != 0; appointments.Add(common);
                }
                else
                {
                    var priority = Number(fields, 18, 3);
                    common["faellig"] = end.Date; common["prio"] = priority < 3 ? priority + 1 : 2;
                    common["erledigt"] = Date(fields, 19).Date.Length > 0; tasks.Add(common);
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
                var addresses = new JsonArray(); var columns = new[] { Strings(fields, 28), Strings(fields, 31), Strings(fields, 29), Strings(fields, 32) };
                var keys = new[] { "strasse", "plz", "ort", "land" };
                for (var index = 0; index < columns.Max(column => column.Length); index++)
                {
                    var address = new JsonObject(); var nonempty = false;
                    for (var column = 0; column < columns.Length; column++)
                    {
                        var value = index < columns[column].Length ? columns[column][index] : "";
                        address[keys[column]] = value; nonempty |= value.Length > 0;
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
                if (addresses.Count > 0) foreach (var key in keys) contact[key] = addresses[0]![key]!.DeepClone();
                var birthday = Date(fields, 41).Date; if (birthday.Length > 0) contact["geburtstag"] = birthday;
                var note = Text(fields, 39);
                foreach (var (id, label) in new (ushort, string)[] { (16, "Title"), (18, "Middle name"), (20, "Suffix"), (22, "Position"),
                    (25, "Department"), (27, "Assistant"), (30, "State"), (37, "URL"), (43, "Spouse"), (44, "Children") })
                {
                    var value = string.Join("; ", Strings(fields, id).Where(value => value.Length > 0));
                    if (value.Length > 0) note += (note.Length > 0 ? "\n" : "") + label + ": " + value;
                }
                for (ushort id = 46; id < 66; id++) { var value = Text(fields, id); if (value.Length > 0) note += $"\nCustom {id - 45}: {value}"; }
                contact["notiz"] = note; contacts.Add(contact);
            }
            else if (tag == 0x510)
            {
                var title = Text(fields, 7); var text = RtfText(Bytes(fields, 8));
                if (title.Length + text.Length > 0) notes.Add(new JsonObject { ["titel"] = title, ["text"] = text, ["uid"] = uid });
            }
            else if (tag is 0x200 or 0x600 or 0x700 or 0x900)
            {
                var ids = tag == 0x900 ? new ushort[] { 12, 14, 15 } : new ushort[] { 9 };
                if (ids.Any(id => Text(fields, id).Length > 0)) skipped++;
            }
        }
        return new(appointments, new JsonArray(), new JsonArray(), tasks, contacts, skipped, recurring,
            NativeLocalization.Gettext("OR6 import: appointments, tasks, contacts and plain-text notes. Verified finite appointment series, contact group memberships and known phone contexts are retained. Recurrences with unsupported changes and other sections are skipped; layout, attachments and alarms are not transferred."), notes);
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
