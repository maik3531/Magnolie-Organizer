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

    internal static Task CollectionKindsAsync()
    {
        var png = DeviceFileSourceSendTests.PaddedPng(length: 256);
        var video = new byte[] { 0,0,0,16,102,116,121,112,105,115,111,109,0,0,0,0 };
        TestAssert.That(NativeMediaContentMime.IdentifyCollection(png, png.Length, "images") == "image/png" &&
            NativeMediaContentMime.IdentifyCollection(video, video.Length, "video") == "video/mp4", "Selected collection type no longer uses actual bytes.");
        foreach (var (kind, bytes) in new[] { ("images", video), ("video", png) })
        {
            try { NativeMediaContentMime.IdentifyCollection(bytes, bytes.Length, kind); throw new Exception("Opposite container obtained expected type."); }
            catch (InvalidDataException error) { TestAssert.That(error.Message == "media_collection_known_other_type", "Opposite container was conflated with unknown bytes."); }
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(bytes, bytes.Length, kind), "Real sender relaxed kind matching.");
        }
        foreach (var (kind, bytes) in new[] { ("images", "not-media"u8.ToArray()), ("video", png[..25]), ("bad-kind", png) })
        {
            try { NativeMediaContentMime.IdentifyCollection(bytes, bytes.Length, kind); throw new Exception("Unknown container became a positive exclusion."); }
            catch (InvalidDataException error) { TestAssert.That(error.Message == "media_source_mime_unknown", "Unknown bytes bypassed original MIME gate."); }
        }
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.IdentifyCollection(png, 1, "images"), "Collection relaxed actual prefix bound.");
        return Task.CompletedTask;
    }
}
