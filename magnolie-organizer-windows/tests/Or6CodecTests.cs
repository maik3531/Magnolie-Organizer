using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class Or6CodecTests
{
    private static JsonNode Contract() => JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root("contracts/or6-native-fixtures.json"), "contracts/or6-native-fixtures.json")))!;
    internal static byte[] Fixture(string name = "known-values.or6")
    {
        var item = Contract()["files"]![name]!;
        using var compressed = new MemoryStream(Convert.FromBase64String(item["gzip_base64"]!.GetValue<string>()));
        using var gzip = new GZipStream(compressed, CompressionMode.Decompress); using var plain = new MemoryStream(); gzip.CopyTo(plain);
        var bytes = plain.ToArray();
        TestAssert.That(bytes.Length == item["bytes"]!.GetValue<int>() && Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == item["sha256"]!.GetValue<string>(), "Native OR6 fixture changed.");
        return bytes;
    }
    private static byte[] Rotate(byte[] raw, bool left)
    {
        var output = raw.ToArray();
        for (var offset = 0; offset < output.Length; offset += 2)
        {
            var word = BinaryPrimitives.ReadUInt16LittleEndian(output.AsSpan(offset, 2));
            BinaryPrimitives.WriteUInt16LittleEndian(output.AsSpan(offset, 2), (ushort)(left ? (word << 1) | (word >> 15) : (word >> 1) | (word << 15)));
        }
        return output;
    }
    private static List<(int Offset, uint Tag, int Size)> Blocks(byte[] data)
    {
        var result = new List<(int, uint, int)>();
        for (var offset = 0; offset < data.Length;)
        {
            var size = (int)BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset + 8));
            result.Add((offset, BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset)), size)); offset += size;
        }
        return result;
    }
    internal static Task RunAsync()
    {
        var raw = Fixture(); var result = ExchangeCodec.ParseImport(raw, "lotus", "owned.or6"); var expected = Contract()["expected"]!;
        foreach (var (kind, collection) in new[] { ("contact", result.Kontakte), ("appointment", result.Termine), ("task", result.Aufgaben), ("note", result.Notizen!) })
        {
            TestAssert.That(collection.Count == 1, "Native OR6 record count differs from known values.");
            foreach (var pair in expected[kind]!.AsObject()) TestAssert.That(JsonNode.DeepEquals(collection[0]![pair.Key], pair.Value), "OR6 known value differs: " + kind + "/" + pair.Key);
            TestAssert.That(collection[0]!["uid"]!.GetValue<string>().StartsWith("or6:", StringComparison.Ordinal), "OR6 record identity missing.");
        }
        var empty = Or6Codec.Read(Fixture("empty.or6")); var deleted = Or6Codec.Read(Fixture("deleted-values.or6"));
        TestAssert.That(empty.Kontakte.Count + empty.Termine.Count + empty.Aufgaben.Count + empty.Notizen!.Count + empty.Uebersprungen == 0, "Alphabet placeholders became imported records.");
        TestAssert.That(deleted.Kontakte.Count == 0 && JsonNode.DeepEquals(deleted.Termine, result.Termine) && JsonNode.DeepEquals(deleted.Notizen, result.Notizen) && JsonNode.DeepEquals(deleted.Aufgaben, result.Aufgaben), "Freed contact was resurrected or unrelated content changed.");
        TestAssert.That(result.Bericht == NativeLocalization.Gettext("OR6 import: appointments, tasks, contacts and plain-text notes. Verified finite appointment series, contact group memberships and known phone contexts are retained. Recurrences with unsupported changes and other sections are skipped; layout, attachments and alarms are not transferred."), "Localized OR6 limitation report missing.");
        foreach (var corruption in new[] { "truncated", "signature", "zero_size", "self", "field_pointer", "duplicate_field", "schema_cycle", "wrong_parent", "rtf" })
        {
            byte[] broken;
            if (corruption == "truncated") broken = raw[..^4];
            else if (corruption == "signature") { broken = raw.ToArray(); broken[0] = 0; }
            else
            {
                var data = Rotate(raw, true); var blocks = Blocks(data);
                var contact = blocks.First(block => block.Tag == 0x400 && BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(block.Offset + 0x28)) == 34).Offset;
                void Put(int offset, uint value) => BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(offset, 4), value);
                switch (corruption)
                {
                    case "zero_size": Put(8, 0); break;
                    case "self": Put(contact + 4, (uint)contact + 4); break;
                    case "field_pointer": Put(contact + 0x34 + 8 + 4, uint.MaxValue); break;
                    case "duplicate_field": data.AsSpan(contact + 0x34, 2).CopyTo(data.AsSpan(contact + 0x34 + 8, 2)); break;
                    case "wrong_parent": Put(contact + 0x18, uint.MaxValue); break;
                    case "schema_cycle": var field = blocks.First(block => block.Tag == 0xfffffffd).Offset; Put(field + 0x20, (uint)field); break;
                    default:
                        var note = blocks.First(block => block.Tag == 0x510); var end = Array.LastIndexOf(data, (byte)'}', note.Offset + note.Size - 1, note.Size);
                        TestAssert.That(end >= note.Offset, "Native RTF fixture missing."); data[end] = 32; break;
                }
                broken = Rotate(data, false);
            }
            var refused = false;
            try { Or6Codec.Read(broken); } catch (InvalidDataException) { refused = true; }
            TestAssert.That(refused, "Corrupt OR6 accepted: " + corruption);
        }
        using var zipBytes = new MemoryStream();
        var series = Rotate(raw, true); var appointmentOffset = Blocks(series).First(block => block.Tag == 0x100).Offset;
        var properties = BinaryPrimitives.ReadUInt32LittleEndian(series.AsSpan(appointmentOffset + 0x28)); var changed = false;
        for (var index = 0; index < properties; index++)
        {
            var entryOffset = appointmentOffset + 0x34 + index * 8;
            if (BinaryPrimitives.ReadUInt16LittleEndian(series.AsSpan(entryOffset)) != 15) continue;
            BinaryPrimitives.WriteUInt16LittleEndian(series.AsSpan(entryOffset), 10);
            BinaryPrimitives.WriteUInt32LittleEndian(series.AsSpan(entryOffset + 4), 1); changed = true; break;
        }
        TestAssert.That(changed, "Native appointment busy field missing.");
        var skippedSeries = Or6Codec.Read(Rotate(series, false));
        TestAssert.That(skippedSeries.Termine.Count == 0 && skippedSeries.Uebersprungen == 1 && skippedSeries.Wiederholend == 0, "Skipped OR6 series falsely claimed preserved ICS originals.");
        using (var zip = new ZipArchive(zipBytes, ZipArchiveMode.Create, true))
        using (var entry = zip.CreateEntry("owned.or6", CompressionLevel.NoCompression).Open()) entry.Write(raw);
        TestAssert.That(ExchangeCodec.ParseImport(zipBytes.ToArray(), "lotus", "owned.zip").Kontakte.Count == 1, "OR6 ZIP native dispatch missing.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-or6-source-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, "Owned source.or6"); File.WriteAllBytes(path, raw);
            var source = ImportFileSource.Read("lotus", path);
            TestAssert.That(source.Bytes.AsSpan().SequenceEqual(raw) && ExchangeCodec.ParseImport(source.Bytes, "lotus", source.Path).Notizen!.Count == 1, "OR6 native file source changed bytes or reader.");
            ImportFileSource.Read("lotus", path, source.Revision);
            var secondPath = path + ".copy"; File.Copy(path, secondPath);
            TestAssert.That(ImportFileSource.Read("lotus", secondPath).Revision != source.Revision, "OR6 revision ignored source path.");
            File.WriteAllBytes(path, raw.Concat(new byte[4]).ToArray());
            var refused = false;
            try { ImportFileSource.Read("lotus", path, source.Revision); } catch (InvalidOperationException error) when (error.Message == "mcp_conflict") { refused = true; }
            TestAssert.That(refused, "OR6 source mutation accepted a stale revision.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
