using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ImportFileSourceTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-import-preview-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            using var events = JsonDocument.Parse("""[{"id":"owned-event","titel":"Owned preview","datum":"2030-01-02","zeit":"09:00"}]""");
            using var contacts = JsonDocument.Parse("""[{"id":"owned-contact","vorname":"Owned","nachname":"Preview","email":"owned@example.invalid"}]""");
            var cases = new Dictionary<string, (string Name, string Text, bool Contacts)> {
                ["ics"] = ("Owned import.ics", ExchangeCodec.WriteIcs("ics-termine", events.RootElement).Text, false),
                ["lotus"] = ("Owned import.csv", ExchangeCodec.WriteLotusCsv(events.RootElement).Text, false),
                ["vcf"] = ("Owned import.vcf", ExchangeCodec.WriteVCard(contacts.RootElement).Text, true),
                ["ldif"] = ("Owned import.ldif", ExchangeCodec.WriteLdif(contacts.RootElement).Text, true),
                ["claws"] = ("Owned import.xml", """<?xml version="1.0"?><address-book><person uid="owned" first-name="Owned" last-name="Preview"><address-list><address email="owned@example.invalid"/></address-list></person></address-book>""", true) };
            foreach (var (format, fixture) in cases)
            {
                var path = Path.Combine(root, fixture.Name); File.WriteAllText(path, fixture.Text, new UTF8Encoding(false));
                var source = ImportFileSource.Read(format, path);
                TestAssert.That(source.Bytes.AsSpan().SequenceEqual(File.ReadAllBytes(path)) && source.Sha256 == Convert.ToHexString(SHA256.HashData(source.Bytes)).ToLowerInvariant(), "Import source bytes/digest differ from the actual file.");
                var parsed = ExchangeCodec.ParseImport(source.Bytes, format == "ldif" ? "claws" : format, source.Path);
                TestAssert.That((fixture.Contacts ? parsed.Kontakte.Count : parsed.Termine.Count) == 1, "Actual native import reader did not parse the owned fixture.");
                ImportFileSource.Read(format, path, source.Revision);
                TestAssert.That(ImportFileSource.Read(format + "-different", path).Revision != source.Revision, "Import revision ignored selected reader identity.");
                var copiedPath = path + ".copy"; File.Copy(path, copiedPath);
                TestAssert.That(ImportFileSource.Read(format, copiedPath).Revision != source.Revision, "Import revision ignored file identity.");
                File.AppendAllText(path, "\n");
                var rejected = false;
                try { ImportFileSource.Read(format, path, source.Revision); } catch (InvalidOperationException error) when (error.Message == "mcp_conflict") { rejected = true; }
                TestAssert.That(rejected, "Changed import bytes accepted an obsolete source revision.");
            }
            var archivePath = Path.Combine(root, "owned.zip");
            using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
                foreach (var name in new[] { "one.ics", "two.ics" })
                {
                    using var writer = new StreamWriter(archive.CreateEntry(name, CompressionLevel.NoCompression).Open());
                    writer.Write(cases["ics"].Text.Replace("owned-event", "owned-" + name, StringComparison.Ordinal));
                }
            var zipped = ImportFileSource.Read("ics", archivePath);
            TestAssert.That(ExchangeCodec.ParseImport(zipped.Bytes, "ics", zipped.Path).Termine.Count == 2, "Supported bounded ZIP import was not read by the product parser.");
            var oversized = Path.Combine(root, "oversized.ics");
            using (var file = File.Create(oversized)) file.SetLength(ExchangeCodec.MaxImportBytes + 1);
            var tooLarge = false;
            try { ImportFileSource.Read("ics", oversized); } catch (IOException) { tooLarge = true; }
            TestAssert.That(tooLarge, "Import source exceeded the product byte bound.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
