using System.IO.Compression;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class UnicodeImportTests
{
    private sealed record Fixture(string Kind, string FileName, string Text, bool Contact);

    internal static Task RunAsync()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var checks = 0;
        // A literal replacement character is valid input. Reject broken byte sequences,
        // never legitimate U+FFFD text or non-BMP surrogate pairs (#842).
        const string name = "MARKER Müller 👩‍💻 �";
        foreach (var fixture in Fixtures(name))
        {
            foreach (var encoding in new Encoding[] { new UTF8Encoding(false, true),
                new UTF8Encoding(true, true), new UnicodeEncoding(false, true, true),
                new UnicodeEncoding(true, true, true) })
            {
                var bytes = Encode(fixture.Text, encoding);
                foreach (var zipped in new[] { false, true })
                {
                    CheckParsed(ExchangeCodec.ParseImport(zipped ? Archive((fixture.FileName, bytes)) : bytes,
                        fixture.Kind, zipped ? "unicode.zip" : fixture.FileName), fixture.Contact, name);
                    checks++;
                }
            }
            foreach (var bigEndian in new[] { false, true })
            {
                var valid = Encode(fixture.Text, new UnicodeEncoding(bigEndian, true, true));
                foreach (var broken in Damaged(valid, fixture.Text.IndexOf("MARKER", StringComparison.Ordinal), bigEndian))
                {
                    Invalid(() => ExchangeCodec.ParseImport(broken, fixture.Kind, fixture.FileName), fixture.FileName);
                    // The first entry can parse successfully, but no partial import may
                    // escape when a later supported entry has an invalid encoding.
                    var zipped = Archive(("good/" + fixture.FileName, valid), ("bad/" + fixture.FileName, broken));
                    Invalid(() => ExchangeCodec.ParseImport(zipped, fixture.Kind, "mixed.zip"), "mixed.zip");
                    checks += 2;
                }
            }
        }
        const string legacyName = "MARKER Müller";
        foreach (var fixture in Fixtures(legacyName))
        {
            var bytes = Encode(fixture.Text, Encoding.GetEncoding(1252));
            foreach (var zipped in new[] { false, true })
            {
                CheckParsed(ExchangeCodec.ParseImport(zipped ? Archive((fixture.FileName, bytes)) : bytes,
                    fixture.Kind, zipped ? "legacy.zip" : fixture.FileName), fixture.Contact, legacyName);
                checks++;
            }
        }
        foreach (var (fileName, text, format) in new[] {
            ("waste.csv", "Date,Type\r\n2030-05-10,MARKER\r\n", "csv"),
            ("waste.ics", Fixtures(name).Single(f => f.Kind == "ics").Text, "ics") })
        {
            foreach (var bigEndian in new[] { false, true })
            {
                var bytes = Encode(text, new UnicodeEncoding(bigEndian, true, true));
                TestAssert.That(ExchangeCodec.ParseWasteImport(bytes, fileName)["muellFormat"]!.GetValue<string>() == format,
                    "Valid UTF-16 waste import changed format.");
                checks++;
                foreach (var broken in Damaged(bytes, text.IndexOf("MARKER", StringComparison.Ordinal), bigEndian))
                {
                    Invalid(() => ExchangeCodec.ParseWasteImport(broken, fileName), fileName);
                    checks++;
                }
            }
        }
        Console.WriteLine($"  Unicode import: {checks} file, ZIP and waste-calendar cases passed.");
        return Task.CompletedTask;
    }

    private static Fixture[] Fixtures(string name) => [
        new("lotus", "contacts.csv", $"Vorname,Nachname,E-Mail\r\nAlex,{name},alex@example.test\r\n", true),
        new("vcf", "contacts.csv", $"Vorname,Nachname,E-Mail\r\nAlex,{name},alex@example.test\r\n", true),
        new("vcf", "contacts.vcf", $"BEGIN:VCARD\r\nVERSION:3.0\r\nUID:unicode-fixture\r\nFN:Alex {name}\r\nN:{name};Alex;;;\r\nEND:VCARD\r\n", true),
        new("ics", "calendar.ics", $"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:unicode-fixture\r\nDTSTART:20300510T103000Z\r\nSUMMARY:{name}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", false),
        new("claws", "contacts.ldif", "version: 1\r\n\r\ndn: uid=MARKER\r\nuid: MARKER\r\ngivenName: Alex\r\nsn:: " +
            Convert.ToBase64String(Encoding.UTF8.GetBytes(name)) + "\r\nmail: alex@example.test\r\n\r\n", true),
        new("claws", "contacts.xml", $"<?xml version=\"1.0\"?><address-book><person uid=\"unicode-fixture\" first-name=\"Alex\" last-name=\"{name}\"><address-list><address email=\"alex@example.test\"/></address-list></person></address-book>\n", true)
    ];

    private static byte[] Encode(string text, Encoding encoding) => [.. encoding.GetPreamble(), .. encoding.GetBytes(text)];

    private static IEnumerable<byte[]> Damaged(byte[] valid, int marker, bool bigEndian)
    {
        TestAssert.That(marker >= 0, "Missing byte-corruption fixture marker.");
        foreach (var unit in new ushort[] { 0xd800, 0xdc00 })
        {
            var broken = valid.ToArray();
            var offset = 2 + marker * 2;
            broken[offset] = (byte)(bigEndian ? unit >> 8 : unit & 0xff);
            broken[offset + 1] = (byte)(bigEndian ? unit & 0xff : unit >> 8);
            yield return broken;
        }
        yield return [.. valid, (byte)0x41];
    }

    private static byte[] Archive(params (string Name, byte[] Bytes)[] entries)
    {
        using var output = new MemoryStream();
        using (var archive = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true))
            foreach (var (name, bytes) in entries)
            {
                using var stream = archive.CreateEntry(name, CompressionLevel.NoCompression).Open();
                stream.Write(bytes);
            }
        return output.ToArray();
    }

    private static void CheckParsed(ExchangeImportResult result, bool contact, string name)
    {
        var records = contact ? result.Kontakte : result.Termine;
        TestAssert.That(records.Count == 1 && result.Uebersprungen == 0 &&
            records[0]![contact ? "nachname" : "titel"]!.GetValue<string>() == name,
            "Valid encoded text changed or records were lost at the actual import entry.");
    }

    private static void Invalid(Action action, string fileName)
    {
        try { action(); }
        catch (InvalidDataException error) when (error.InnerException is DecoderFallbackException)
        {
            TestAssert.That(error.Message == NativeLocalization.Gettext("The content is unreadable."),
                "The invalid-encoding error bypassed the localized content message.");
            return;
        }
        throw new InvalidOperationException("Malformed UTF-16 was accepted: " + fileName);
    }
}
