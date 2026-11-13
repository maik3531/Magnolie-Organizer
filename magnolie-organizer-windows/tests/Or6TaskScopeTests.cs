using System.Buffers.Binary;
using System.Globalization;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6TaskScopeTests
{
    private const string Title = "OR6-567 Variants";
    private static JsonObject[] Selected(ExchangeImportResult result) => result.Aufgaben.OfType<JsonObject>().Where(item => ContactFields.Text(item, "titel") == Title).ToArray();
    internal static byte[] Fixture(JsonNode meta)
    {
        using var input = new MemoryStream(Convert.FromBase64String(meta["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var raw = output.ToArray();
        TestAssert.That(raw.Length == meta["bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() == meta["sha256"]!.GetValue<string>(), "Independent scoped task source changed");
        return raw;
    }
    internal static Dictionary<string, (bool Completed, string Category)> Occurrences(IEnumerable<JsonObject> tasks)
    {
        var result = new Dictionary<string, (bool, string)>();
        foreach (var task in tasks)
        {
            using var input = JsonDocument.Parse(task.ToJsonString());
            foreach (var value in CalendarRecurrence.Expand(input.RootElement, new DateTime(2026, 12, 1), new DateTime(2027, 1, 1), TimeZoneInfo.Utc, task: true))
                TestAssert.That(result.TryAdd(value.Start.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                    (task["erledigt"]!.GetValue<bool>(), ContactFields.Text(task, "kategorien"))), "Linked history duplicated by native relative index");
        }
        return result;
    }
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-task-scopes.json"), "contracts/or6-native-task-scopes.json")))!;
        foreach (var pair in contract["files"]!.AsObject())
        {
            var raw = Fixture(pair.Value!); var imported = Or6Codec.Read(raw); var tasks = Selected(imported);
            TestAssert.That(imported.Uebersprungen == 0 && tasks.Length == 3, "Original scoped series was held or flattened");
            var values = Occurrences(tasks);
            var dates = contract["expected"]!["datesByFile"]![pair.Key]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
            TestAssert.That(values.Keys.Order().SequenceEqual(dates), "Original scoped task date lost");
            foreach (var (date, state) in values)
                TestAssert.That(state.Completed == (date == "2026-12-01") && state.Category == contract["expected"]!["categoryByDate"]![date]!.GetValue<string>(), "Scoped category or completion spread to other occurrences");
            var basis = tasks.Single(item => !item["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>().StartsWith("RECURRENCE-ID:", StringComparison.Ordinal)));
            TestAssert.That(ContactFields.Text(basis, "uid") == "or6:0001b2d5:0000040e" && tasks.Select(item => ContactFields.Text(item, "uid")).Distinct().Count() == 3, "Native definition/exception identity lost");
            using var input = JsonDocument.Parse(new JsonArray(tasks.Select(item => item.DeepClone()).ToArray()).ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-aufgaben", input.RootElement);
            var roundtrip = Occurrences(Selected(ExchangeCodec.ParseIcs(export.Text)));
            TestAssert.That(export.Count == 3 && export.Skipped == 0 && values.Count == roundtrip.Count && values.All(pair => roundtrip.TryGetValue(pair.Key, out var value) && value == pair.Value), "Actual VTODO roundtrip lost historical state/category");
        }
        var decoded = Rotate(Fixture(contract["files"]!["task-scoped-reopened4-567.or6"]!), true);
        var owners = Blocks(decoded).Where(at => U32(decoded, at) == 0x300 && FieldTextIfPresent(decoded, at, 9) == Title)
            .OrderBy(at => decoded[Field(decoded, at, 7).Value + 3]).ToArray();
        TestAssert.That(owners.Length == 4 && owners.Select(at => { try { return U32(decoded, Field(decoded, at, 14).Value); } catch { return 0U; } }).SequenceEqual(new uint[] { 0, 1, 0, 1 }), "Fixture no longer checks independently reused native indices");
        foreach (var mutation in new[] { "duplicate-date", "current-index", "historical-before-anchor", "history-title", "history-duration", "unknown-state" })
        {
            var data = decoded.ToArray(); var first = owners[0]; var last = owners[^1];
            if (mutation == "duplicate-date")
                foreach (var fid in new[] { 7, 8 }) data.AsSpan(Field(data, first, fid).Value, 8).CopyTo(data.AsSpan(Field(data, owners[1], fid).Value));
            else if (mutation == "current-index") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(Field(data, last, 14).Value), 99);
            else if (mutation == "historical-before-anchor") foreach (var fid in new[] { 7, 8 }) data[Field(data, first, fid).Value + 2] = 11;
            else if (mutation == "history-title") data[Field(data, first, 9).Value] = (byte)'X';
            else if (mutation == "history-duration") data[Field(data, first, 8).Value + 4] = 19;
            else BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(Field(data, first, 20).Value), 99);
            var held = Or6Codec.Read(Rotate(data, false));
            TestAssert.That(Selected(held).Length == 0 && held.Uebersprungen == 4, "Ambiguous history/source guard guessed: " + mutation);
        }
    }
}
