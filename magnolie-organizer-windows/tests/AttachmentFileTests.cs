using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class AttachmentFileTests
{
    internal static Task RunAsync()
    {
        var samples = new[]
        {
            ("image/jpeg", ".jpg", new byte[] { 0xff, 0xd8, 0xff, 0xdb }),
            ("image/png", ".png", new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a }),
            ("image/webp", ".webp", new byte[] { 0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50 }),
            ("image/gif", ".gif", "GIF89a"u8.ToArray()),
            ("application/pdf", ".pdf", "%PDF-1.7"u8.ToArray())
        };
        foreach (var (mime, extension, bytes) in samples)
        {
            var parsed = AttachmentFile.Parse($"data:{mime};base64,{Convert.ToBase64String(bytes)}", "Probe.exe");
            TestAssert.That(parsed.MimeType == mime && parsed.Extension == extension &&
                parsed.FileName == "Probe" + extension && parsed.Bytes.SequenceEqual(bytes),
                $"{mime} wurde nicht kanonisch dekodiert.");
        }

        Reject("data:image/png;base64," + Convert.ToBase64String("%PDF-1.7"u8.ToArray()));
        Reject("data:image/png;base64,AA ==");
        Reject("data:image/jpeg;base64,/9j/2x==");
        Reject("data:image/png;charset=utf-8;base64,AAAA");
        Reject("data:image/PNG;base64,AAAA");
        Reject("data:text/plain;base64,QQ==");
        Reject("data:image/png;base64,");
        Reject("data:image/png;base64," + Convert.ToBase64String(new byte[AttachmentFile.MaxBytes + 1]));
        Reject(new string('x', AttachmentFile.MaxDataUrlLength + 1));

        TestAssert.That(AttachmentFile.SafeFileName(@"..\boese.pdf", ".pdf") == "Anhang.pdf" &&
            AttachmentFile.SafeFileName("CON.jpg", ".jpg") == "Anhang.jpg" &&
            AttachmentFile.SafeFileName("na\0me.png", ".png") == "name.png" &&
            AttachmentFile.SafeFileName("na<me>:*.pdf", ".pdf") == "name.pdf" &&
            AttachmentFile.SafeFileName(new string('a', 300) + ".gif", ".gif").Length == 180,
            "Unsichere oder überlange Anhangnamen wurden nicht kanonisiert.");
        return Task.CompletedTask;
    }

    private static void Reject(string value)
    {
        try { _ = AttachmentFile.Parse(value, "probe.bin"); }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("Manipulierte Anhangdaten wurden akzeptiert.");
    }
}
