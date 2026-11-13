using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6LineEndingTests
{
    private static byte[] AnnualFixture()
    {
        var contract = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-extensions.json"), "contracts/or6-native-extensions.json")))!;
        var item = contract["files"]!["sections-corrected-222.or6"]!;
        using var input = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(input, CompressionMode.Decompress); using var output = new MemoryStream(); gzip.CopyTo(output);
        var bytes = output.ToArray();
        TestAssert.That(Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == item["sha256"]!.GetValue<string>(), "Synthetic annual fixture changed");
        return bytes;
    }
    private static byte[] Description(byte[] raw, uint kind, string value)
    {
        var data = Or6UnsupportedNoteTests.Rotate(raw, true); var text = Encoding.Unicode.GetBytes(value);
        for (int offset = 0; offset < data.Length;)
        {
            var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8)));
            if (tag == kind)
            {
                int count = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 0x28)));
                var entries = Enumerable.Range(0, count).Select(i => offset + 0x34 + i * 8).ToArray();
                int entry = entries.FirstOrDefault(e => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(e)) == 9 &&
                    BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(e + 2)) >= text.Length, -1);
                if (entry >= 0)
                {
                    int address = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(entry + 4)));
                    BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(entry + 2), checked((ushort)text.Length));
                    text.CopyTo(data.AsSpan(offset + address));
                    foreach (var body in entries.Where(e => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(e)) == 16))
                    { BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(body + 2), 0); data.AsSpan(body + 4, 4).Clear(); }
                    return Or6UnsupportedNoteTests.Rotate(data, false);
                }
            }
            offset += size;
        }
        throw new Exception("Synthetic description field missing");
    }
    private static Task CheckDescriptions(bool annual)
    {
        var raw = annual ? AnnualFixture() : Or6CodecTests.Fixture(); var original = Or6Codec.Read(raw);
        foreach (var ending in new[] { "\r\n", "\n", "\r" })
        {
            var result = Or6Codec.Read(Description(raw, annual ? 0x600U : 0x100U, "A" + ending + "B" + ending + "C"));
            var entry = (annual ? result.Jahrestage : result.Termine).Single()!.AsObject();
            var basis = (annual ? original.Jahrestage : original.Termine).Single()!.AsObject();
            TestAssert.That(entry[annual ? "name" : "titel"]!.GetValue<string>() == "A" && entry["notiz"]!.GetValue<string>() == "B\nC",
                "Description line endings leaked into title/name or changed note text");
            TestAssert.That(JsonNode.DeepEquals(entry["uid"], basis["uid"]) && JsonNode.DeepEquals(result.Kontakte, original.Kontakte) &&
                JsonNode.DeepEquals(result.Notizen, original.Notizen), "Description normalization changed opaque UID or unrelated records");
        }
        return Task.CompletedTask;
    }
    internal static Task AppointmentDescriptionsAsync() => CheckDescriptions(false);
    internal static Task AnniversaryDescriptionsAsync() => CheckDescriptions(true);
}
