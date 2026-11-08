using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMediaMimeTests
{
    internal static Task ByteDerivedMimeAsync()
    {
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC");
        TestAssert.That(NativeMediaContentMime.Identify(png, png.Length, "images") == "image/png", "Actual PNG was not identified independently of a filename.");
        var jpeg = new byte[] { 255,216,255,224,0,4,0,0,255,192,0,8,8,0,10,0,20,1 };
        TestAssert.That(NativeMediaContentMime.Identify(jpeg, jpeg.Length, "images") == "image/jpeg", "Bounded JPEG frame dimensions were not identified.");
        var video = new byte[] { 0,0,0,20,102,116,121,112,109,112,52,50,0,0,0,0,105,115,111,109 };
        TestAssert.That(NativeMediaContentMime.Identify(video, video.Length, "video") == "video/mp4", "MP4 ftyp was not identified.");
        "qt  "u8.CopyTo(video.AsSpan(8));
        TestAssert.That(NativeMediaContentMime.Identify(video, video.Length, "video") == "video/quicktime", "QuickTime was relabeled MP4.");
        foreach (var bytes in new[] { "<svg/>"u8.ToArray(), "#EXTM3U\nhttps://invalid/"u8.ToArray(), new byte[] { 255,216,255,224,255,255 }, Array.Empty<byte>() })
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(bytes, Math.Max(1, bytes.Length), "images"), "Unknown/active/truncated format obtained a MIME.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(png, png.Length, "video"), "Image bytes were relabeled video.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(video, video.Length, "images"), "Video bytes were relabeled image.");
        var bomb = png.ToArray(); System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(bomb.AsSpan(16), 40000);
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(bomb, bomb.Length, "images"), "Unbounded pixel metadata passed MIME identification.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(png, 1, "images"), "Prefix exceeded actual source bytes.");
        return Task.CompletedTask;
    }
}
