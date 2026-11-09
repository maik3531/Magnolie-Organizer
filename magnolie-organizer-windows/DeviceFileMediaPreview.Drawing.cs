using System.Drawing.Imaging;
using System.Drawing.Drawing2D;

namespace MagnolieOrganizer.Windows;

internal static class NativeMediaPreviewDrawing
{
    internal static NativeMediaPreviewRaster Render(byte[] bytes, string kind, int side, Action current)
    {
        current();
        // No filename/extension inference and no shell thumbnail provider.
        if (kind is not ("images" or "video") || bytes.Length > NativeMediaPreviewBytes.MaximumBytes || side is not (192 or 1024))
            throw DeviceFileControl.Error("media_preview_decoder_unavailable");
        if (kind == "video")
        {
            using var frame = NativeMediaPreviewVideo.Decode(bytes, current);
            using var bitmap = new Bitmap(frame.Width, frame.Height, PixelFormat.Format32bppRgb);
            var held = bitmap.LockBits(new Rectangle(0, 0, bitmap.Width, bitmap.Height), ImageLockMode.WriteOnly, PixelFormat.Format32bppRgb);
            try
            {
                for (var row = 0; row < frame.Height; row++)
                    System.Runtime.InteropServices.Marshal.Copy(frame.Pixels, row * frame.Width * 4,
                        IntPtr.Add(held.Scan0, row * held.Stride), frame.Width * 4);
            }
            finally { bitmap.UnlockBits(held); }
            bitmap.RotateFlip(frame.Rotation switch {
                90 => RotateFlipType.Rotate90FlipNone, 180 => RotateFlipType.Rotate180FlipNone,
                270 => RotateFlipType.Rotate270FlipNone, _ => RotateFlipType.RotateNoneFlipNone });
            current(); return Raster(bitmap, side, current);
        }
        // Parse dimensions BEFORE invoking the platform image decoder.
        var (width, height) = Dimensions(bytes);
        using var input = new MemoryStream(bytes, writable: false);
        using var image = Image.FromStream(input, useEmbeddedColorManagement: false, validateImageData: true);
        current();
        if (image.Width != width || image.Height != height) throw DeviceFileControl.Error("media_preview_dimensions");
        if (image.PropertyIdList.Contains(0x112))
        {
            var value = image.GetPropertyItem(0x112)?.Value;
            var orientation = value is { Length: >= 2 } ? BitConverter.ToUInt16(value) : 1;
            image.RotateFlip(orientation switch {
                2 => RotateFlipType.RotateNoneFlipX, 3 => RotateFlipType.Rotate180FlipNone, 4 => RotateFlipType.Rotate180FlipX,
                5 => RotateFlipType.Rotate90FlipX, 6 => RotateFlipType.Rotate90FlipNone, 7 => RotateFlipType.Rotate270FlipX,
                8 => RotateFlipType.Rotate270FlipNone, _ => RotateFlipType.RotateNoneFlipNone });
        }
        return Raster(image, side, current);
    }

    private static NativeMediaPreviewRaster Raster(Image image, int side, Action current)
    {
        var scale = Math.Min(1.0, (double)side / Math.Max(image.Width, image.Height));
        using var raster = new Bitmap(Math.Max(1, (int)(image.Width * scale)), Math.Max(1, (int)(image.Height * scale)), PixelFormat.Format24bppRgb);
        using (var graphics = Graphics.FromImage(raster))
        {
            graphics.Clear(Color.White); graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
            graphics.DrawImage(image, 0, 0, raster.Width, raster.Height);
        }
        current(); using var output = new MemoryStream(); raster.Save(output, ImageFormat.Jpeg); current();
        if (output.Length > 512 * 1024) throw DeviceFileControl.Error("media_preview_raster_bound");
        return new("image/jpeg", raster.Width, raster.Height, Convert.ToBase64String(output.GetBuffer(), 0, (int)output.Length));
    }

    private static (int Width, int Height) Dimensions(byte[] bytes)
    {
        int width = 0, height = 0;
        if (bytes.Length >= 24 && bytes.AsSpan(0, 16).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82 }))
        {
            width = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(16, 4));
            height = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(20, 4));
        }
        else if (bytes.Length >= 4 && bytes[0] == 255 && bytes[1] == 216)
        {
            var offset = 2;
            while (offset < Math.Min(bytes.Length, 1024 * 1024))
            {
                if (bytes[offset] != 255) break;
                while (offset < bytes.Length && bytes[offset] == 255) offset++;
                if (offset >= bytes.Length) break;
                var marker = bytes[offset++];
                if (marker is 0 or 0xd9 or 0xda) break;
                if (marker == 1 || marker is >= 0xd0 and <= 0xd8) continue;
                if (offset + 2 > bytes.Length) break;
                var size = (bytes[offset] << 8) | bytes[offset + 1];
                if (size < 2 || size > bytes.Length - offset) break;
                if ((marker is >= 0xc0 and <= 0xc3 or >= 0xc5 and <= 0xc7 or >= 0xc9 and <= 0xcb or >= 0xcd and <= 0xcf) && size >= 8)
                { height = (bytes[offset + 3] << 8) | bytes[offset + 4]; width = (bytes[offset + 5] << 8) | bytes[offset + 6]; break; }
                offset += size;
            }
        }
        if (width is < 1 or > 32768 || height is < 1 or > 32768 || (long)width * height > 24000000)
            throw DeviceFileControl.Error("media_preview_dimensions");
        return (width, height);
    }
}
