using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileVideoPreviewTests
{
    internal static byte[] Fixture()
    {
        const string marker = "tests/fixtures/native-video-preview.mp4";
        var bytes = File.ReadAllBytes(Path.Combine(TestSource.Root(marker), marker));
        // Synthetic 64x48, red upper half/blue lower half, one H.264 baseline
        // frame, no sound. FFmpeg lavfi color+drawbox, libx264, faststart.
        TestAssert.That(Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() ==
            "87233672839f433fa666cdd5a26e35d604fb18182443f0a770147111e039b2f0", "Video preview fixture changed.");
        return bytes;
    }

    internal static Task ContainerAsync()
    {
        var bytes = Fixture(); NativeMediaVideoContainer.RequireLocalMp4(bytes);
        TestAssert.Throws<InvalidDataException>(() => NativeMediaVideoContainer.RequireLocalMp4(bytes[..^1]), "Truncated MP4 reached native decoder.");
        var dref = bytes.AsSpan().IndexOf("dref"u8); TestAssert.That(dref > 0, "Fixture has no data-reference table.");
        var external = bytes.ToArray(); external[dref + 23] = 0;
        TestAssert.Throws<InvalidDataException>(() => NativeMediaVideoContainer.RequireLocalMp4(external), "External MP4 URL reached native decoder.");
        var alias = bytes.ToArray(); "alis"u8.CopyTo(alias.AsSpan(dref + 16, 4));
        TestAssert.Throws<InvalidDataException>(() => NativeMediaVideoContainer.RequireLocalMp4(alias), "QuickTime external alias reached native decoder.");
        var referenceMovie = bytes.Concat(new byte[] { 0, 0, 0, 8, (byte)'r', (byte)'m', (byte)'r', (byte)'a' }).ToArray();
        TestAssert.Throws<InvalidDataException>(() => NativeMediaVideoContainer.RequireLocalMp4(referenceMovie), "QuickTime reference movie reached native decoder.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaVideoContainer.RequireLocalMp4(new byte[32]), "Filename-free video decoder accepted an arbitrary container.");
        return Task.CompletedTask;
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static Task WindowsFrameAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var bytes = Fixture(); var original = SHA256.HashData(bytes); var checks = 0;
        var frame = NativeMediaPreviewVideo.Decode(bytes, () => checks++);
        try
        {
            TestAssert.That(frame.Width == 64 && frame.Height == 48 && frame.Pixels.Length == 64 * 48 * 4 && checks >= 6,
                "Actual memory-only Media Foundation frame has wrong dimensions or bypassed current-owner checks.");
            var top = (4 * frame.Width + 4) * 4; var bottom = (40 * frame.Width + 4) * 4;
            TestAssert.That(frame.Pixels[top + 2] > 180 && frame.Pixels[top] < 60 &&
                frame.Pixels[bottom] > 180 && frame.Pixels[bottom + 2] < 60,
                "Actual Media Foundation BGR frame swapped channels or vertical orientation.");
            TestAssert.That(SHA256.HashData(bytes).SequenceEqual(original), "Preview decoder changed verified original bytes.");
        }
        finally { frame.Dispose(); }
        TestAssert.That(frame.Pixels.All(value => value == 0), "Decoded private frame survived disposal.");
        checks = 0;
        TestAssert.Throws<InvalidDataException>(() => NativeMediaPreviewVideo.Decode(bytes, () => {
            if (++checks == 6) throw DeviceFileControl.Error("synthetic_preview_owner_revoked");
        }), "Native decode published a frame after actual current-owner withdrawal.");
        TestAssert.That(checks == 6 && SHA256.HashData(bytes).SequenceEqual(original), "Withdrawal changed original bytes or did not reach actual decoding.");
        return Task.CompletedTask;
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static Task WindowsProductRotationAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        const string marker = "tests/fixtures/native-video-preview-rotated.mp4";
        var bytes = File.ReadAllBytes(Path.Combine(TestSource.Root(marker), marker));
        TestAssert.That(Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() ==
            "4078cc8290cfa19ac6e7952558d2c6bf921dae4b8290b81a3a18882b637041bd", "Rotated video fixture changed.");
        using (var frame = NativeMediaPreviewVideo.Decode(bytes, () => { }))
            TestAssert.That(frame.Rotation == 270, "Native clockwise display rotation was not 270: " + frame.Rotation);
        // Same encoded frame, display matrix is 90 degrees counter-clockwise.
        foreach (var side in new[] { 192, 1024 })
        {
            var raster = DeviceFileMediaTrashTests.RenderActualProduct(bytes, "video", side, () => { });
            TestAssert.That(raster.Width == 48 && raster.Height == 64, "Actual product video preview ignored the native display rotation.");
            var drawing = System.Reflection.Assembly.Load("System.Drawing.Common");
            var imageType = drawing.GetType("System.Drawing.Image", true)!;
            using var stream = new MemoryStream(Convert.FromBase64String(raster.DataBase64));
            using var image = (IDisposable)imageType.GetMethod("FromStream", new[] { typeof(Stream) })!.Invoke(null, new object[] { stream })!;
            var getPixel = image.GetType().GetMethod("GetPixel")!;
            var left = getPixel.Invoke(image, new object[] { 4, 4 })!; var right = getPixel.Invoke(image, new object[] { 40, 4 })!;
            static int Channel(object color, string channel) => (byte)color.GetType().GetProperty(channel)!.GetValue(color)!;
            TestAssert.That(Channel(left, "R") > 180 && Channel(left, "B") < 60 && Channel(right, "B") > 180 && Channel(right, "R") < 60,
                "Actual product JPEG applied video rotation in the wrong direction or swapped channels.");
        }
        return Task.CompletedTask;
    }
}
