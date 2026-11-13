using System.Buffers.Binary;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6ContactSourceTextTests
{
    private static byte[] Fixture()
    {
        var data = Or6UnsupportedNoteTests.Rotate(Or6CodecTests.Fixture(), true);
        var alias = Encoding.Unicode.GetBytes("FixtureAlias"); var extension = Encoding.Unicode.GetBytes("42\0\0X\0");
        for (int offset = 0; offset < data.Length;)
        {
            var tag = BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset));
            int size = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8)));
            if (tag == 0x400)
            {
                int count = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 0x28)));
                var entries = Enumerable.Range(0, count).Select(i => offset + 0x34 + i * 8)
                    .ToDictionary(e => BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(e)));
                if (entries.TryGetValue(39, out int note) && BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(note + 2)) >= alias.Length)
                {
                    int destination = entries.GetValueOrDefault((ushort)40, note);
                    int address = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(note + 4)));
                    if (destination != note) data.AsSpan(note + 2, 6).Clear();
                    BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(destination), 40);
                    BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(destination + 2), checked((ushort)alias.Length));
                    BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(destination + 4), checked((uint)address));
                    alias.CopyTo(data.AsSpan(offset + address));
                    int entry = entries[34];
                    TestAssert.That(BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(entry + 2)) >= extension.Length, "Owned synthetic field too small");
                    address = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(entry + 4)));
                    BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(entry + 2), checked((ushort)extension.Length));
                    extension.CopyTo(data.AsSpan(offset + address));
                    return Or6UnsupportedNoteTests.Rotate(data, false);
                }
            }
            offset += size;
        }
        throw new Exception("Synthetic owned contact fields missing");
    }
    internal static Task PreserveSourceTextAsync()
    {
        var original = Or6Codec.Read(Or6CodecTests.Fixture()); var result = Or6Codec.Read(Fixture());
        var contact = result.Kontakte.Single()!; var note = contact["notiz"]!.GetValue<string>();
        TestAssert.That(note.Contains("Mail merge name: FixtureAlias", StringComparison.Ordinal) && note.Contains("Lotus Extn slot 1: 42", StringComparison.Ordinal) &&
            note.Contains("Lotus Extn slot 3: X", StringComparison.Ordinal) && !note.Contains("Lotus Extn slot 2:", StringComparison.Ordinal),
            "Allocated extra contact source text was silently omitted");
        foreach (var key in new[] { "uid", "telefone", "telefon", "emails", "anschriften" })
            TestAssert.That(JsonNode.DeepEquals(contact[key], original.Kontakte.Single()![key]), "Source text guessed a phone value or changed contact identity");
        TestAssert.That(JsonNode.DeepEquals(result.Termine, original.Termine) && JsonNode.DeepEquals(result.Aufgaben, original.Aufgaben) &&
            JsonNode.DeepEquals(result.Notizen, original.Notizen) && JsonNode.DeepEquals(result.Jahrestage, original.Jahrestage) && result.Uebersprungen == original.Uebersprungen,
            "Contact source text changed other collections or omission accounting");
        return Task.CompletedTask;
    }
}
