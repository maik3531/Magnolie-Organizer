using System.Buffers.Binary;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6UnsupportedNoteTests
{
    private static byte[] Rotate(byte[] bytes, bool left)
    {
        var copy = bytes.ToArray();
        for (int offset = 0; offset < copy.Length; offset += 2)
        {
            var value = BinaryPrimitives.ReadUInt16LittleEndian(copy.AsSpan(offset));
            BinaryPrimitives.WriteUInt16LittleEndian(copy.AsSpan(offset), (ushort)(left ? value << 1 | value >> 15 : value >> 1 | value << 15));
        }
        return copy;
    }
    internal static byte[] WithNoteBody(byte[] body)
    {
        var data = Rotate(Or6CodecTests.Fixture(), true);
        for (int offset = 0; offset < data.Length;)
        {
            var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
            var size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8)));
            if (tag == 0x510)
            {
                var count = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 0x28));
                for (int index = 0; index < count; ++index)
                {
                    int entry = offset + 0x34 + index * 8;
                    if (BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry)) != 8) continue;
                    var length = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry + 2));
                    TestAssert.That(body.Length <= length, "Synthetic replacement exceeds owned field");
                    var address = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(entry + 4)));
                    BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(entry + 2), checked((ushort)body.Length));
                    if (body.Length <= 4) { data.AsSpan(entry + 4, 4).Clear(); body.CopyTo(data.AsSpan(entry + 4)); }
                    else body.CopyTo(data.AsSpan(offset + address));
                    return Rotate(data, false);
                }
            }
            offset += size;
        }
        throw new Exception("Synthetic note body missing");
    }
    internal static Task UnknownBodyDoesNotBlockCollectionsAsync()
    {
        var original = Or6Codec.Read(Or6CodecTests.Fixture());
        var result = Or6Codec.Read(WithNoteBody("fixture"u8.ToArray()));
        TestAssert.That(result.Notizen!.Count == 0 && result.Uebersprungen == original.Uebersprungen + 1,
            "Unsupported note was silently imported or failed to report omission");
        foreach (var pair in new[] { (result.Kontakte, original.Kontakte), (result.Termine, original.Termine), (result.Aufgaben, original.Aufgaben), (result.Jahrestage, original.Jahrestage) })
            TestAssert.That(JsonNode.DeepEquals(pair.Item1, pair.Item2), "Unsupported note changed unrelated supported records");
        return Task.CompletedTask;
    }
    internal static Task EmptyAndMalformedStayDistinctAsync()
    {
        foreach (var body in new byte[][] { [], [0, 255, 2] })
        {
            var result = Or6Codec.Read(WithNoteBody(body));
            TestAssert.That(result.Notizen!.Count == 1 && result.Notizen[0]!["text"]!.GetValue<string>() == "" && result.Uebersprungen == 0,
                "Known empty note was confused with unsupported format");
        }
        TestAssert.Throws<InvalidDataException>(() => Or6Codec.Read(WithNoteBody("{\\rtf1 incomplete"u8.ToArray())),
            "Malformed recognized RTF was downgraded to unsupported instead of refused");
        return Task.CompletedTask;
    }
}
