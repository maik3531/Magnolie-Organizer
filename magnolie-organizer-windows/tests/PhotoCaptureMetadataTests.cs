using System.Buffers.Binary;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhotoCaptureMetadataTests
{
    internal static byte[] Tiff(bool little = true)
    {
        var data = new byte[82]; data[0] = data[1] = (byte)(little ? 'I' : 'M');
        void Short(int offset, ushort value) { if (little) BinaryPrimitives.WriteUInt16LittleEndian(data.AsSpan(offset), value); else BinaryPrimitives.WriteUInt16BigEndian(data.AsSpan(offset), value); }
        void Long(int offset, uint value) { if (little) BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(offset), value); else BinaryPrimitives.WriteUInt32BigEndian(data.AsSpan(offset), value); }
        Short(2, 42); Long(4, 8); Short(8, 2);
        Short(10, 0x010f); Short(12, 2); Long(14, 6); Long(18, 38);
        Short(22, 0x8769); Short(24, 4); Long(26, 1); Long(30, 44);
        Encoding.ASCII.GetBytes("Phone\0").CopyTo(data, 38);
        Short(44, 1); Short(46, 0x9003); Short(48, 2); Long(50, 20); Long(54, 62);
        Encoding.ASCII.GetBytes("2026:11:08 13:14:15\0").CopyTo(data, 62); return data;
    }
    internal static byte[] Jpeg(bool little = true) => new byte[] { 255, 216, 255, 225, 0, 90 }
        .Concat("Exif\0\0"u8.ToArray()).Concat(Tiff(little)).Concat(new byte[] { 255, 217 }).ToArray();

    internal static Task RunAsync()
    {
        foreach (var little in new[] { true, false })
        {
            var tiff = Tiff(little); var jpeg = Jpeg(little);
            var png = new byte[8 + 12 + tiff.Length]; new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }.CopyTo(png, 0);
            BinaryPrimitives.WriteUInt32BigEndian(png.AsSpan(8), (uint)tiff.Length); "eXIf"u8.CopyTo(png.AsSpan(12)); tiff.CopyTo(png, 16);
            TestAssert.That(PhotoCaptureMetadata.Matches(tiff) && PhotoCaptureMetadata.Matches(jpeg) && PhotoCaptureMetadata.Matches(png),
                "Actual camera EXIF was not recognized in both byte orders and metadata containers.");
        }
        TestAssert.That(!PhotoCaptureMetadata.Matches("DCIM/Camera/IMG_camera.jpg Phone 2026:11:08"u8) &&
            !PhotoCaptureMetadata.Matches(new byte[] { 255, 216, 255, 217 }) && !PhotoCaptureMetadata.Matches(new byte[PhotoCaptureMetadata.MaximumBytes + 1]),
            "A filename, stripped metadata or unbounded prefix satisfied capture selection.");
        foreach (var date in new[] { "2026:02:29 12:00:00", "0000:00:00 00:00:00", "2026:11:08 25:00:00" })
        {
            var invalid = Tiff(); Encoding.ASCII.GetBytes(date).CopyTo(invalid, 62);
            TestAssert.That(!PhotoCaptureMetadata.Matches(invalid), "Invalid capture timestamp was admitted.");
        }
        var hostile = Tiff(); hostile.AsSpan(4, 4).Fill(255);
        TestAssert.That(!PhotoCaptureMetadata.Matches(hostile) && !PhotoCaptureMetadata.Matches(Jpeg()[..^8]), "Hostile offsets or truncated EXIF were admitted.");
        return Task.CompletedTask;
    }
}
