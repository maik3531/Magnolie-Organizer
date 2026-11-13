using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6PlannerTests
{
    internal static uint U32(byte[] data, int at) => BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(at, 4));
    private static ushort U16(byte[] data, int at) => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(at, 2));
    internal static IEnumerable<int> Blocks(byte[] data) { for (var at = 0; at < data.Length; at += (int)U32(data, at + 8)) yield return at; }
    internal static (int Entry, int Length, int Value) Field(byte[] data, int owner, int id)
    {
        for (var i = 0; i < U32(data, owner + 0x28); i++)
        {
            var at = owner + 0x34 + i * 8; var length = U16(data, at + 2);
            if (U16(data, at) == id) return (at, length, length <= 4 ? at + 4 : owner + (int)U32(data, at + 4));
        }
        throw new Exception("Independent native field missing");
    }
    private static string FieldText(byte[] data, int owner, int id)
    { var field = Field(data, owner, id); return Encoding.Unicode.GetString(data, field.Value, field.Length).TrimEnd('\0'); }
    internal static byte[] Rotate(byte[] raw, bool decode)
    {
        var data = raw.ToArray();
        for (var at = 0; at < data.Length; at += 2)
        { var n = U16(data, at); BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(at), (ushort)(decode ? n << 1 | n >> 15 : n >> 1 | n << 15)); }
        return data;
    }
    private static Dictionary<string, JsonObject> Selected(byte[] raw) => Or6Codec.Read(raw).Termine.OfType<JsonObject>()
        .Where(item => ContactFields.Text(item, "titel").StartsWith("OR6-568 ", StringComparison.Ordinal)).ToDictionary(item => ContactFields.Text(item, "titel"));
    internal static void Run()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-planner.json"), "contracts/or6-native-planner.json")))!;
        var meta = contract["file"]!;
        using var compressed = new MemoryStream(Convert.FromBase64String(meta["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(compressed, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var raw = output.ToArray();
        TestAssert.That(raw.Length == meta["bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() == meta["sha256"]!.GetValue<string>(), "Independent planner source changed");
        var result = Selected(raw);
        TestAssert.That(result.Count == 17, "Original planner events lost");
        foreach (var expected in contract["expected"]!.AsArray().OfType<JsonObject>())
        {
            var item = result[ContactFields.Text(expected, "title")];
            TestAssert.That(ContactFields.Text(item, "kategorien") == ContactFields.Text(expected, "category") &&
                ContactFields.Text(item, "akzentFarbe") == ContactFields.Text(expected, "color") &&
                ContactFields.Text(item, "datum") == ContactFields.Text(expected, "date"), "Scoped planner name/color/date differs");
            using var input = JsonDocument.Parse(new JsonArray(item.DeepClone()).ToJsonString());
            var export = ExchangeCodec.WriteIcs("ics-termine", input.RootElement);
            var imported = ExchangeCodec.ParseIcs(export.Text).Termine.Single()!;
            TestAssert.That(export.Count == 1 && export.Skipped == 0 && JsonNode.DeepEquals(item["kategorien"], imported["kategorien"]) &&
                JsonNode.DeepEquals(item["akzentFarbe"], imported["akzentFarbe"]), "Actual calendar export lost planner category/color");
        }
        TestAssert.That(!ContactFields.Text(result["OR6-568 B00 palette"], "notiz").Contains("Lotus planner KeyID", StringComparison.Ordinal),
            "Implicit original first slot was invented as a present source field");
        var decoded = Rotate(raw, true); var configs = Blocks(decoded).Where(at => U32(decoded, at) == 0x201).ToArray();
        TestAssert.That(configs.Length == 2 && decoded.AsSpan(configs[0] + 0x18, 8).SequenceEqual(decoded.AsSpan(configs[1] + 0x18, 8)),
            "Fixture no longer checks shared options schema across distinct sections");
        foreach (var mutation in new[] { "swap", "duplicate-config", "missing-config", "schema-name", "duplicate-root", "unknown-key", "malformed-key", "unrelated-root" })
        {
            var data = decoded.ToArray(); var x = Field(data, configs[0], 3).Value; var y = Field(data, configs[1], 3).Value;
            if (mutation == "swap") { var saved = data.AsSpan(x, 8).ToArray(); data.AsSpan(y, 8).CopyTo(data.AsSpan(x)); saved.CopyTo(data, y); }
            else if (mutation == "duplicate-config") data.AsSpan(x, 8).CopyTo(data.AsSpan(y));
            else if (mutation == "missing-config") BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(configs[1]), 0x80000201);
            else if (mutation == "schema-name")
            {
                var record = Blocks(data).First(at => U32(data, at) == 0x200 && FieldTextIfPresent(data, at, 9) == "OR6-568 B04 original");
                var schema = Blocks(data).Single(at => U32(data, at) == uint.MaxValue && data.AsSpan(at + 12, 8).SequenceEqual(data.AsSpan(record + 0x18, 8)));
                data.AsSpan(schema + 0x48, 128).Clear(); Encoding.Unicode.GetBytes("Detached").CopyTo(data, schema + 0x48);
            }
            else if (mutation == "duplicate-root")
            {
                var root = Blocks(data).Single(at => U32(data, at) == 0xfeffffff && data.AsSpan(at + 12, 8).SequenceEqual(data.AsSpan(y, 8)));
                data.AsSpan(x, 8).CopyTo(data.AsSpan(root + 12));
            }
            else if (mutation is "unknown-key" or "malformed-key")
            {
                var record = Blocks(data).First(at => U32(data, at) == 0x200 && FieldTextIfPresent(data, at, 9) == "OR6-568 B04 original");
                var field = Field(data, record, 19);
                if (mutation == "unknown-key") BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(field.Value), 99);
                else BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(field.Entry + 2), 1);
            }
            else
            {
                var root = Blocks(data).First(at => U32(data, at) == 0xfeffffff && FieldNumberIfPresent(data, at, 5) == 0x510);
                var field = Field(data, root, 3); TestAssert.That(field.Length > 4, "Unrelated root name is not indirect");
                BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(field.Entry + 4), uint.MaxValue);
            }
            var changed = Selected(Rotate(data, false)); TestAssert.That(changed.Count == 17, "Metadata ambiguity discarded content");
            if (mutation == "swap") TestAssert.That(ContactFields.Text(changed["OR6-568 A04 original"], "kategorien") == "B04" &&
                ContactFields.Text(changed["OR6-568 B04 original"], "kategorien") == "A04", "Names followed shared options schema instead of exact Section ID");
            else if (mutation == "unrelated-root") TestAssert.That(ContactFields.Text(changed["OR6-568 B04 original"], "kategorien") == "B04", "Unrelated notebook root was reconstructed");
            else TestAssert.That(changed["OR6-568 B04 original"]["kategorien"] is null && changed["OR6-568 B04 original"]["akzentFarbe"] is null, "Ambiguous/missing metadata or unknown KeyID was guessed");
        }
    }
    internal static string FieldTextIfPresent(byte[] data, int owner, int id)
    { try { return FieldText(data, owner, id); } catch (Exception error) when (error.Message == "Independent native field missing") { return ""; } }
    private static uint FieldNumberIfPresent(byte[] data, int owner, int id)
    { try { var field = Field(data, owner, id); return field.Length == 4 ? U32(data, field.Value) : 0; } catch (Exception error) when (error.Message == "Independent native field missing") { return 0; } }
}
