using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using static MagnolieOrganizer.Windows.Tests.Or6PlannerTests;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6PlannerBoundaryTests
{
    private const string Prefix = "X-MAGNOLIE-OR6-PLANNER-LOCAL-";
    private static JsonNode Contract(string name) => JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/" + name), "contracts", name)))!;
    private static byte[] Fixture(JsonNode meta)
    {
        using var input = new MemoryStream(Convert.FromBase64String(meta["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var raw = output.ToArray();
        TestAssert.That(raw.Length == meta["bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() == meta["sha256"]!.GetValue<string>(), "Independent planner boundary source changed");
        return raw;
    }
    private static Dictionary<string, JsonObject> Selected(byte[] raw) => Or6Codec.Read(raw).Termine.OfType<JsonObject>()
        .Where(item => ContactFields.Text(item, "titel").StartsWith("OR6-568 ", StringComparison.Ordinal)).ToDictionary(item => ContactFields.Text(item, "titel"));
    internal static void Run()
    {
        var contract = Contract("or6-native-planner-boundaries.json"); var raw = Fixture(contract["file"]!);
        var result = Or6Codec.Read(raw); var items = Selected(raw); var affected = new HashSet<string>();
        TestAssert.That(items.Count == 17 && result.Uebersprungen == 0, "Verified zero/midnight/timed planner records still omitted");
        foreach (var expected in contract["expected"]!.AsArray().OfType<JsonObject>())
        {
            var title = ContactFields.Text(expected, "title"); affected.Add(title); var item = items[title];
            var properties = new[] { Prefix + "START:" + ContactFields.Text(expected, "sourceStart"), Prefix + "END:" + ContactFields.Text(expected, "sourceEnd") };
            TestAssert.That(ContactFields.Text(item, "datum") == ContactFields.Text(expected, "date") && ContactFields.Text(item, "endDatum") == ContactFields.Text(expected, "endDate") &&
                ContactFields.Text(item, "zeit") == "" && ContactFields.Text(item, "endZeit") == "" &&
                ContactFields.Text(item, "kategorien") == ContactFields.Text(expected, "category") && ContactFields.Text(item, "akzentFarbe") == ContactFields.Text(expected, "color"),
                "Planner inclusive date presentation or scoped category/color differs");
            TestAssert.That(item["icsRoundtrip"]!.AsArray().Select(value => value!.GetValue<string>()).SequenceEqual(properties),
                "Original local clock was discarded, timezone-guessed or turned into a scheduling rule");
            using var input = JsonDocument.Parse(new JsonArray(item.DeepClone()).ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-termine", input.RootElement);
            var imported = ExchangeCodec.ParseIcs(export.Text).Termine.Single()!.AsObject();
            TestAssert.That(ContactFields.Text(imported, "datum") == ContactFields.Text(expected, "date") && ContactFields.Text(imported, "endDatum") == ContactFields.Text(expected, "endDate") &&
                ContactFields.Text(imported, "zeit") == "" && ContactFields.Text(imported, "endZeit") == "" &&
                properties.All(property => imported["icsRoundtrip"]!.AsArray().Any(value => value!.GetValue<string>() == property)),
                "Actual calendar export changed inclusive days or lost raw source clock properties");
        }
        var basis = Or6Codec.Read(Fixture(Contract("or6-native-planner.json")["file"]!));
        foreach (var item in basis.Termine.OfType<JsonObject>().Where(item => !affected.Contains(ContactFields.Text(item, "titel"))))
            TestAssert.That(JsonNode.DeepEquals(item, result.Termine.OfType<JsonObject>().Single(value => ContactFields.Text(value, "titel") == ContactFields.Text(item, "titel"))), "Clock conversion changed another appointment");
        TestAssert.That(JsonNode.DeepEquals(basis.Kontakte, result.Kontakte) && JsonNode.DeepEquals(basis.Aufgaben, result.Aufgaben) &&
            JsonNode.DeepEquals(basis.Notizen, result.Notizen) && JsonNode.DeepEquals(basis.Jahrestage, result.Jahrestage), "Planner clock conversion changed unrelated collections");
        var decoded = Rotate(raw, true);
        var owner = Blocks(decoded).First(at => U32(decoded, at) == 0x200 && FieldTextIfPresent(decoded, at, 9) == "OR6-568 B01 palette");
        foreach (var mutation in new[] { "reversed-clock", "reversed-date", "reserved-start", "reserved-end", "fractional-hour", "repeat", "confidential" })
        {
            var data = decoded.ToArray(); var first = Field(data, owner, 7).Value; var last = Field(data, owner, 8).Value;
            if (mutation == "reversed-clock") data[last + 4] = 7;
            else if (mutation == "reversed-date") data[last + 3] = 3;
            else if (mutation == "reserved-start") data[first + 7] = 1;
            else if (mutation == "reserved-end") data[last + 7] = 1;
            else if (mutation == "fractional-hour") data[first + 5] = 15;
            else BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(Field(data, owner, 19).Entry), (ushort)(mutation == "repeat" ? 10 : 1));
            var encoded = Rotate(data, false); var held = Or6Codec.Read(encoded);
            TestAssert.That(held.Uebersprungen == 1 && Selected(encoded).Count == 16 && !Selected(encoded).ContainsKey("OR6-568 B01 palette"),
                "Planner clock support bypassed a source safety guard: " + mutation);
        }
        var annual = Rotate(Fixture(Contract("or6-native-extensions.json")["files"]!["sections-corrected-222.or6"]!), true);
        var anniversary = Blocks(annual).First(at => U32(annual, at) == 0x600 && FieldTextIfPresent(annual, at, 9).Length > 0);
        var start = Field(annual, anniversary, 7).Value; var end = Field(annual, anniversary, 8).Value;
        annual[start + 4] = 8; annual[end + 4] = 18; annual[start + 5] = annual[end + 5] = annual[start + 6] = annual[end + 6] = 0;
        var unsupported = Or6Codec.Read(Rotate(annual, false));
        TestAssert.That(unsupported.Jahrestage.Count == 0 && unsupported.Uebersprungen == 1, "Anniversary acquired planner-only clock semantics");
    }
}
