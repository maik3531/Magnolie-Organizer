using Windows.Data.Pdf;
using Windows.Storage.Streams;

namespace MagnolieOrganizer.Windows;

internal static class PdfPreview
{
    internal static async Task<(uint Pages, int Page, string Data)> RenderAsync(string dataUrl, int pageNumber)
    {
        var attachment = AttachmentFile.Parse(dataUrl, "drawing.pdf");
        if (attachment.MimeType != "application/pdf" || pageNumber is < 1 or > 1000)
            throw new InvalidDataException("Invalid PDF page.");
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        using var input = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(input))
        {
            writer.WriteBytes(attachment.Bytes);
            await writer.StoreAsync().AsTask(timeout.Token);
            writer.DetachStream();
        }
        input.Seek(0);
        var document = await PdfDocument.LoadFromStreamAsync(input).AsTask(timeout.Token);
        if (document.PageCount is < 1 or > 1000 || pageNumber > document.PageCount)
            throw new InvalidDataException("Invalid PDF page count.");
        using var page = document.GetPage((uint)pageNumber - 1);
        var size = page.Size;
        if (!double.IsFinite(size.Width) || !double.IsFinite(size.Height) || size.Width <= 0 || size.Height <= 0)
            throw new InvalidDataException("Invalid PDF page size.");
        var scale = 2200 / Math.Max(size.Width, size.Height);
        using var output = new InMemoryRandomAccessStream();
        await page.RenderToStreamAsync(output, new PdfPageRenderOptions
        {
            DestinationWidth = (uint)Math.Max(1, Math.Round(size.Width * scale)),
            DestinationHeight = (uint)Math.Max(1, Math.Round(size.Height * scale))
        }).AsTask(timeout.Token);
        if (output.Size is 0 or > AttachmentFile.MaxBytes)
            throw new InvalidDataException("PDF preview is too large.");
        using var reader = new DataReader(output.GetInputStreamAt(0));
        await reader.LoadAsync((uint)output.Size).AsTask(timeout.Token);
        var bytes = new byte[(int)output.Size]; reader.ReadBytes(bytes);
        var encoded = "data:image/png;base64," + Convert.ToBase64String(bytes);
        if (AttachmentFile.Parse(encoded, "page.png").MimeType != "image/png")
            throw new InvalidDataException("Invalid PDF preview.");
        return (document.PageCount, pageNumber, encoded);
    }
}
