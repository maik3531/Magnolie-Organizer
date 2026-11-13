using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6TaskSeriesTests
{
    private const string Title = "OR6-567 Weekly";
    private static readonly string[] ExpectedDates = ["2026-12-01", "2026-12-08", "2026-12-15"];
    private static byte[] Fixture()
    {
        var path = Path.Combine(TestSource.Root("contracts/or6-native-tasks.json"), "contracts/or6-native-tasks.json");
        var contract = JsonNode.Parse(File.ReadAllText(path))!;
        var item = contract["files"]!["task-weekly-567.or6"]!;
        using var input = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var bytes = output.ToArray();
        TestAssert.That(bytes.Length == item["bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == item["sha256"]!.GetValue<string>(), "Independent Task fixture changed");
        return bytes;
    }
    private static uint U32(byte[] data, int offset) => BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
    private static ushort U16(byte[] data, int offset) => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(offset));
    private static IEnumerable<int> Blocks(byte[] data)
    {
        for (int offset = 0; offset < data.Length; offset += checked((int)U32(data, offset + 8))) yield return offset;
    }
    private static IEnumerable<int> Fields(byte[] data, int owner) => Enumerable.Range(0, checked((int)U32(data, owner + 0x28))).Select(index => owner + 0x34 + index * 8);
    private static uint FieldNumber(byte[] data, int owner, ushort id)
    {
        var prop = Fields(data, owner).FirstOrDefault(offset => U16(data, offset) == id, -1);
        if (prop < 0) return 0;
        var length = U16(data, prop + 2);
        return length == 2 ? U16(data, prop + 4) : U32(data, prop + 4);
    }
    private static JsonObject TaskSeries(ExchangeImportResult result)
    {
        var selected = result.Aufgaben.OfType<JsonObject>().Where(value => value["titel"]!.GetValue<string>() == Title &&
            !value["icsRoundtrip"]!.AsArray().Any(line => line!.GetValue<string>().StartsWith("RECURRENCE-ID:", StringComparison.Ordinal))).ToArray();
        TestAssert.That(selected.Length == 1, "Original linked task series was omitted or flattened into loose tasks");
        return selected.Single();
    }
    private static string[] Dates(JsonObject task)
    {
        using var document = JsonDocument.Parse(task.ToJsonString());
        return CalendarRecurrence.Expand(document.RootElement, new DateTime(2026, 12, 1), new DateTime(2027, 1, 1), TimeZoneInfo.Utc, task: true)
            .Select(value => value.Start.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture)).ToArray();
    }
    internal static void Run()
    {
        var raw = Fixture(); var decoded = Or6UnsupportedNoteTests.Rotate(raw, true);
        var members = Blocks(decoded).Where(offset => U32(decoded, offset) == 0x300 && FieldNumber(decoded, offset, 10) == 1).ToArray();
        TestAssert.That(members.Length == 3, "Independent native task occurrences changed");
        var result = ExchangeCodec.ParseImport(raw, "lotus", "original-synthetic-task.or6");
        var task = TaskSeries(result);
        TestAssert.That(result.Aufgaben.Count == 2 && result.Uebersprungen == 0 && Dates(task).SequenceEqual(ExpectedDates) &&
            !task["erledigt"]!.GetValue<bool>() && task["startDatum"]!.GetValue<string>() == "2026-12-01" && task["faellig"]!.GetValue<string>() == "2026-12-01",
            "Native Task dates/status were lost");
        var definition = Blocks(decoded).Single(offset => U32(decoded, offset) == 0xfefffff2);
        TestAssert.That(task["uid"]!.GetValue<string>() == $"or6:{U32(decoded, definition + 16):x8}:{U32(decoded, definition + 12):x8}", "Native definition identity lost");
        var lines = task["icsRoundtrip"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
        TestAssert.That(lines.Any(line => line.StartsWith("RRULE:FREQ=WEEKLY;", StringComparison.Ordinal)) &&
            lines.Any(line => line.StartsWith("DUE:", StringComparison.Ordinal)) && !lines.Any(line => line.StartsWith("DTEND:", StringComparison.Ordinal)), "Task series became an appointment wire model");
        var basis = Or6Codec.Read(Or6CodecTests.Fixture());
        TestAssert.That(JsonNode.DeepEquals(result.Termine, basis.Termine) && JsonNode.DeepEquals(result.Kontakte, basis.Kontakte) &&
            JsonNode.DeepEquals(result.Notizen, basis.Notizen), "Task conversion changed unrelated native collections");
        using var input = JsonDocument.Parse(new JsonArray(task.DeepClone()).ToJsonString());
        var exported = ExchangeCodec.WriteIcs("ics-aufgaben", input.RootElement);
        TestAssert.That(exported.Count == 1 && exported.Skipped == 0 && exported.Text.Contains("BEGIN:VTODO", StringComparison.Ordinal) &&
            !exported.Text.Contains("BEGIN:VEVENT", StringComparison.Ordinal), "Native task series could not export as one VTODO");
        TestAssert.That(Dates(TaskSeries(ExchangeCodec.ParseIcs(exported.Text))).SequenceEqual(ExpectedDates), "Task export/reimport lost occurrences");
        foreach (var mutation in new[] { "unknown_rule", "freed_member", "orphaned_member", "unknown_status", "conflicting_content", "completed_member" })
        {
            var data = decoded.ToArray();
            var last = members.MaxBy(offset => FieldNumber(data, offset, 14));
            if (mutation == "freed_member") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(last), 0xfffffffc);
            else if (mutation == "orphaned_member")
            {
                foreach (var offset in Blocks(data).Where(offset => U32(data, offset) == 0xfffffffb && U32(data, offset + 8) >= 0x58))
                    if (U32(data, offset + 0x20) == U32(data, last + 12) && U32(data, offset + 0x24) == U32(data, last + 16) &&
                        U32(data, offset + 0x30) == U32(data, definition + 12) && U32(data, offset + 0x34) == U32(data, definition + 16))
                    { BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(offset + 0x38), uint.MaxValue); BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(offset + 0x3c), uint.MaxValue); }
            }
            else
            {
                var owner = mutation == "unknown_rule" ? definition : last;
                var prop = Fields(data, owner).Single(offset => U16(data, offset) == (mutation == "unknown_rule" ? 3 : mutation == "conflicting_content" ? 9 : 20));
                if (mutation == "unknown_rule") BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(prop + 4), 99);
                else if (mutation == "conflicting_content") data[owner + checked((int)U32(data, prop + 4))] = (byte)'X';
                else BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(prop + 4), mutation == "completed_member" ? 4U : 99U);
            }
            var changed = Or6Codec.Read(Or6UnsupportedNoteTests.Rotate(data, false));
            if (mutation is "orphaned_member" or "unknown_status" or "conflicting_content")
                TestAssert.That(changed.Aufgaben.Count == 1 && changed.Uebersprungen == 3,
                    "Unlinked occurrence or differing task status was flattened/merged away");
            else
            {
                var converted = TaskSeries(changed);
                TestAssert.That(Dates(converted).SequenceEqual(mutation is "freed_member" or "completed_member" ? ExpectedDates.Take(2) : ExpectedDates), "Finite Task set changed or resurrected deleted/completed occurrence");
                TestAssert.That(converted["icsRoundtrip"]!.AsArray().Any(line => line!.GetValue<string>().StartsWith(mutation == "unknown_rule" ? "RDATE:" : "EXDATE:", StringComparison.Ordinal)),
                    "Exact finite Task fallback/deletion/completion exception missing: " + mutation);
                if (mutation == "completed_member")
                {
                    var done = changed.Aufgaben.OfType<JsonObject>().Single(value => value["erledigt"]!.GetValue<bool>());
                    TestAssert.That(done["uid"]!.GetValue<string>() == $"or6:{U32(data, last + 16):x8}:{U32(data, last + 12):x8}" &&
                        JsonNode.DeepEquals(done["icsSerienUid"], converted["uid"]) && Dates(done).SequenceEqual(new[] { "2026-12-15" }),
                        "Native completed instance identity/status/date was lost");
                    using var mixedInput = JsonDocument.Parse(new JsonArray(converted.DeepClone(), done.DeepClone()).ToJsonString());
                    var mixedExport = ExchangeCodec.WriteIcs("ics-aufgaben", mixedInput.RootElement);
                    var reread = ExchangeCodec.ParseIcs(mixedExport.Text);
                    TestAssert.That(mixedExport.Count == 2 && mixedExport.Skipped == 0 && Dates(TaskSeries(reread)).SequenceEqual(ExpectedDates.Take(2)) &&
                        reread.Aufgaben.OfType<JsonObject>().Count(value => value["erledigt"]!.GetValue<bool>()) == 1,
                        "Task export/reimport reopened a completed original instance or lost future dates");
                }
            }
        }
    }
}
