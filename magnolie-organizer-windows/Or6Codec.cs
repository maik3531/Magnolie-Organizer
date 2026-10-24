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

        internal IEnumerable<(uint Tag, Dictionary<ushort, byte[]> Fields, string Uid)> Records()
        {
            foreach (var (offset, block) in blocks)
            {
                if (offset == 0 || block.Tag >= 0x80000000) continue;
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
                yield return (block.Tag, fields, $"or6:{origin:x8}:{idValue:x8}");
            }
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
    private static (string Date, string Time) Date(Dictionary<ushort, byte[]> fields, ushort id)
    {
        var value = Bytes(fields, id);
        if (value.Length == 0 || value.AsSpan().SequenceEqual(new byte[] { 2, 0, 2, 2, 2, 2, 2, 2 })) return ("", "");
        if (value.Length != 8) throw Invalid();
        try
        {
            var when = new DateTime(BinaryPrimitives.ReadUInt16LittleEndian(value), value[2], value[3], value[4], value[5], value[6]);
            return (when.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), when.ToString("HH:mm", CultureInfo.InvariantCulture));
        }
        catch (ArgumentOutOfRangeException) { throw Invalid(); }
    }

    internal static ExchangeImportResult Read(byte[] raw)
    {
        var appointments = new JsonArray(); var tasks = new JsonArray(); var contacts = new JsonArray(); var notes = new JsonArray();
        var skipped = 0; var recurring = 0;
        foreach (var (tag, fields, uid) in new Document(raw).Records())
        {
            if (tag is 0x100 or 0x300)
            {
                var title = Text(fields, 9); if (title.Length == 0) continue;
                // The shared recurrence counter means retained ICS rules, not skipped OR6 series.
                if (Number(fields, 10) != 0) { skipped++; continue; }
                var start = Date(fields, 7); var end = Date(fields, 8);
                var lines = title.Split('\n'); var note = string.Join('\n', lines.Skip(1)); var body = Text(fields, 16);
                if (body.Length > 0) note += (note.Length > 0 ? "\n" : "") + body;
                var common = new JsonObject { ["titel"] = lines[0], ["notiz"] = note, ["uid"] = uid,
                    ["geaendert"] = 0, ["vertraulich"] = Number(fields, 1) != 0 };
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
                if (Number(fields, 13) != 0) { skipped++; continue; }
                var phones = Strings(fields, 33).Where(value => value.Length > 0).ToArray();
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
                    ["telefon"] = phones.FirstOrDefault() ?? "", ["mobil"] = "", ["telefone"] = new JsonArray(phones.Select(value => (JsonNode)new JsonObject { ["wert"] = value, ["typen"] = new JsonArray("VOICE") }).ToArray()),
                    ["email"] = emails.FirstOrDefault() ?? "", ["emails"] = new JsonArray(emails.Select(value => (JsonNode)JsonValue.Create(value)!).ToArray()),
                    ["anschriften"] = addresses, ["notiz"] = Text(fields, 39) };
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
            NativeLocalization.Gettext("OR6 import: appointments, tasks, contacts and plain-text notes. Recurrences, groups and other sections are skipped; layout, attachments, categories and alarms are not transferred."), notes);
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
