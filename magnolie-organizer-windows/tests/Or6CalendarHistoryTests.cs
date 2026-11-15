using System.Buffers.Binary;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6CalendarHistoryTests
{
    private static string[] Dates(JsonObject item)
    {
        using var input = JsonDocument.Parse(item.ToJsonString());
        return CalendarRecurrence.Expand(input.RootElement, new DateTime(2026, 10, 1), new DateTime(2026, 12, 1), TimeZoneInfo.Utc)
            .Select(value => value.Start.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).ToArray();
    }
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-calendar-history.json"), "contracts/or6-native-calendar-history.json")))!;
        var raw = Or6TaskScopeTests.Fixture(contract["files"]!.AsObject().First().Value!); var result = Or6Codec.Read(raw);
        var expected = contract["expected"]!; var dates = expected["dates"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
        TestAssert.That(result.Uebersprungen == 0 && result.Termine.Count == 1, "Native linked Calendar history still held or flattened");
        var item = result.Termine.Single()!.AsObject();
        TestAssert.That(Dates(item).SequenceEqual(dates) && ContactFields.Text(item, "uid") == expected["definitionUid"]!.GetValue<string>() &&
            ContactFields.Text(item, "kategorien") == expected["category"]!.GetValue<string>() && ContactFields.Text(item, "zeit") == "10:15" && ContactFields.Text(item, "endZeit") == "11:45", "Original Calendar history values lost");
        var property = "X-MAGNOLIE-OR6-CALENDAR-TEMPLATE-STARTS:" + string.Join(',', expected["currentTemplateStarts"]!.AsArray().Select(value => value!.GetValue<string>()));
        TestAssert.That(item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == property), "Current native template provenance discarded");
        using var input = JsonDocument.Parse(result.Termine.ToJsonString());
        var export = ExchangeCodec.WriteIcs("ics-termine", input.RootElement); var imported = ExchangeCodec.ParseIcs(export.Text).Termine.Single()!.AsObject();
        TestAssert.That(export.Skipped == 0 && Dates(imported).SequenceEqual(dates) && imported["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == property), "Calendar history ICS roundtrip changed dates/provenance");
        var decoded = Rotate(raw, true);
        var owners = Blocks(decoded).Where(at => U32(decoded, at) == 0x100 && FieldTextIfPresent(decoded, at, 9) == "APPT-OR6-212 Besprechung")
            .OrderBy(at => decoded[Field(decoded, at, 7).Value + 2]).ThenBy(at => decoded[Field(decoded, at, 7).Value + 3]).ToArray();
        uint Index(int at) { try { return U32(decoded, Field(decoded, at, 14).Value); } catch { return 0; } }
        TestAssert.That(owners.Select(Index).SequenceEqual(new uint[] { 0, 1, 0, 1 }), "Fixture no longer proves native reused segment indices");
        foreach (var mutation in new[] { "history-index", "current-index", "history-busy", "duplicate-date", "before-anchor", "different-duration", "freed-current" })
        {
            var data = decoded.ToArray();
            if (mutation is "history-index" or "current-index") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(Field(data, mutation == "history-index" ? owners[1] : owners[^1], 14).Value), 99);
            else if (mutation == "history-busy") data[Field(data, owners[0], 15).Value] ^= 1;
            else if (mutation == "duplicate-date") foreach (var fid in new[] { 7, 8 }) data.AsSpan(Field(data, owners[0], fid).Value, 8).CopyTo(data.AsSpan(Field(data, owners[1], fid).Value));
            else if (mutation == "before-anchor") foreach (var fid in new[] { 7, 8 }) data[Field(data, owners[0], fid).Value + 3] = 23;
            else if (mutation == "different-duration") data[Field(data, owners[0], 8).Value + 4] = 12;
            else BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(owners[^1]), 0xfffffffc);
            var changed = Or6Codec.Read(Rotate(data, false));
            if (mutation == "freed-current") TestAssert.That(changed.Uebersprungen == 0 && Dates(changed.Termine.Single()!.AsObject()).SequenceEqual(dates[..^1]), "Deleted current slot reconstructed from native template");
            else TestAssert.That(changed.Termine.Count == 0 && changed.Uebersprungen == 4, "Ambiguous or unknown native Calendar history guessed: " + mutation);
        }
    }
}
