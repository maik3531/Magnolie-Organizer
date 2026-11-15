using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;
using static MagnolieOrganizer.Windows.Tests.Or6TaskScopeTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6TaskBindingTests
{
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-task-bindings.json"), "contracts/or6-native-task-bindings.json")))!;
        foreach (var expected in contract["expected"]!.AsArray().OfType<JsonObject>())
        {
            var title = ContactFields.Text(expected, "title"); var result = Or6Codec.Read(Fixture(contract["files"]![ContactFields.Text(expected, "file")]!));
            var items = result.Aufgaben.OfType<JsonObject>().Where(item => ContactFields.Text(item, "titel") == title).ToArray();
            TestAssert.That(result.Uebersprungen == 0 && items.Length > 0, "Genuine moved/bulk task edits remain omitted");
            var values = Occurrences(items);
            TestAssert.That(values.Keys.Order().SequenceEqual(expected["dates"]!.AsArray().Select(value => value!.GetValue<string>())), "Stale template dates invented tasks or hid actual moved dates");
            foreach (var (date, state) in values)
                TestAssert.That(state.Completed == expected["completedDates"]!.AsArray().Any(value => value!.GetValue<string>() == date) &&
                    state.Category == (expected["categories"]![date]?.GetValue<string>() ?? ""), "Original scoped state/category lost");
            var master = items.Single(item => !item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>().StartsWith("RECURRENCE-ID:", StringComparison.Ordinal)));
            var lines = master["icsRoundtrip"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
            TestAssert.That(lines.Any(line => line.StartsWith("RRULE:", StringComparison.Ordinal)) == expected["ruleExpected"]!.GetValue<bool>(), "Rule inferred despite unequal actual date expansion");
            if (!expected["ruleExpected"]!.GetValue<bool>())
            {
                TestAssert.That(lines.Any(line => line.StartsWith("RDATE:", StringComparison.Ordinal)), "Actual linked dates not retained as finite RDATE");
                foreach (var (key, suffix) in new[] { ("templateStarts", "STARTS"), ("templateDues", "DUES") })
                    TestAssert.That(lines.Contains("X-MAGNOLIE-OR6-TASK-TEMPLATE-" + suffix + ":" + string.Join(',', expected[key]!.AsArray().Select(value => value!.GetValue<string>()))), "Original template clocks discarded");
            }
            using var input = JsonDocument.Parse(new JsonArray(items.Select(item => item.DeepClone()).ToArray()).ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-aufgaben", input.RootElement); var imported = ExchangeCodec.ParseIcs(export.Text).Aufgaben.OfType<JsonObject>().Where(item => ContactFields.Text(item, "titel") == title).ToArray();
            var reread = Occurrences(imported);
            TestAssert.That(export.Skipped == 0 && reread.Count == values.Count && values.All(pair => reread.TryGetValue(pair.Key, out var value) && value == pair.Value), "Actual VTODO roundtrip changed moved dates or states");
            foreach (var line in lines.Where(line => line.StartsWith("X-MAGNOLIE-OR6-TASK-TEMPLATE-", StringComparison.Ordinal)))
                TestAssert.That(imported.Any(item => item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == line)), "Actual VTODO roundtrip lost template provenance");
        }
        var decoded = Rotate(Fixture(contract["files"]!["task-bindings-all-dates-reopened-610.or6"]!), true);
        var owners = Blocks(decoded).Where(at => U32(decoded, at) == 0x300 && FieldTextIfPresent(decoded, at, 9) == "OR6-610 All")
            .OrderBy(at => decoded[Field(decoded, at, 7).Value + 3]).ToArray();
        foreach (var mutation in new[] { "missing-member", "unknown-index", "mixed-indices", "duplicate-date", "changed-duration", "changed-title", "unknown-state" })
        {
            var data = decoded.ToArray(); var owner = owners[^1];
            if (mutation == "missing-member") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(owner), 0xfffffffc);
            else if (mutation is "unknown-index" or "mixed-indices")
            {
                var field = Field(data, owner, 18).Entry;
                BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(field), 14); BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(field + 2), 4);
                BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(field + 4), mutation == "unknown-index" ? 99U : 1U);
            }
            else if (mutation == "duplicate-date") foreach (var fid in new[] { 7, 8 }) data.AsSpan(Field(data, owners[0], fid).Value, 8).CopyTo(data.AsSpan(Field(data, owner, fid).Value));
            else if (mutation == "changed-duration") data[Field(data, owner, 8).Value + 4] = 19;
            else if (mutation == "changed-title") data[Field(data, owner, 9).Value] = (byte)'X';
            else BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(Field(data, owner, 20).Value), 99);
            var held = Or6Codec.Read(Rotate(data, false));
            TestAssert.That(!held.Aufgaben.OfType<JsonObject>().Any(item => ContactFields.Text(item, "titel").Contains("R6-610", StringComparison.Ordinal)) &&
                held.Uebersprungen == (mutation == "missing-member" ? 2 : 3), "Incomplete/ambiguous task set guessed: " + mutation);
        }
    }
}
