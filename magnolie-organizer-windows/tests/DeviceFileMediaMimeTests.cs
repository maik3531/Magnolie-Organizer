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
        var gif = Convert.FromHexString("47494638396101000100800000000000ffffff" +
            "21f90400010000002c0000000001000100000202440100" + "21f90400010000002c0000000001000100000202440100" + "3b");
        TestAssert.That(NativeMediaContentMime.Identify(gif, gif.Length, "images") == "image/gif", "A valid GIF was not identified as a photo.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(gif, gif.Length, "video"), "GIF was relabeled as video.");
        foreach (var invalidGif in new[] { gif[..6], gif[..19].Append((byte)0x3b).ToArray(), gif[..31] })
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(invalidGif, invalidGif.Length, "images"), "Truncated or empty GIF obtained a MIME.");
        foreach (var encoded in new[] {
            "UklGRjAAAABXRUJQVlA4ICQAAABQAQCdASoHAAkAAUAmJQBOgC6gAP77Lkvih5rewdyYwmkjsAA=",
            "UklGRh4AAABXRUJQVlA4TBEAAAAvBgACAAfQj0bUp/+BiOh/AAA=",
            "UklGRlgAAABXRUJQVlA4WAoAAAAIAAAABgAACAAAVlA4ICQAAABQAQCdASoHAAkAAUAmJQBOgC6gAP77Lkvih5rewdyYwmkjsABFWElGDgAAAE1NACoAAAAIAAAAAAAA" })
        {
            var webp = Convert.FromBase64String(encoded);
            TestAssert.That(NativeMediaContentMime.Identify(webp, webp.Length, "images") == "image/webp", "A valid static WebP original was not identified.");
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(webp, webp.Length, "video"), "WebP relabeled as video.");
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(webp[..22], webp.Length, "images"), "A truncated WebP prefix was admitted.");
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(webp, webp.Length + 1, "images"), "Untrusted RIFF length was admitted.");
        }
        var bmp = Convert.FromHexString("424d4e000000000000003600000028000000020000000300000001001800000000001800000000000000000000000000000000000000" +
            "0c22384e5a2000000c22384e5a2000000c22384e5a200000");
        TestAssert.That(NativeMediaContentMime.Identify(bmp, bmp.Length, "images") == "image/bmp", "Uncompressed 24-bit BMP was not recognized.");
        TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(bmp, bmp.Length, "video"), "BMP was relabeled as video.");
        foreach (var (offset, value) in new (int, uint)[] { (2, 79), (10, 53), (10, 56), (14, 12), (18, 100_000), (22, 0x80000000), (30, 1), (34, 1) })
        {
            var broken = bmp.ToArray();
            System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(broken.AsSpan(offset), value);
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(broken, broken.Length, "images"), "Malformed BMP obtained a MIME.");
        }
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

    internal static Task WebmProbeAsync()
    {
        const string relative = "contracts/media-webm-probe-vectors.json";
        var vectors = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!.AsObject();
        byte[] Read(string name)
        {
            var record = vectors[name]!.AsObject(); var bytes = Convert.FromBase64String(record["base64"]!.GetValue<string>());
            TestAssert.That(Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant() ==
                record["sha256"]!.GetValue<string>(), "Original synthetic bytes changed: " + name);
            return bytes;
        }
        var webm = Read("webm"); var mkv = Read("matroska");
        TestAssert.That(NativeMediaContentMime.ProbeFiniteWebmVideo(webm, webm.Length) &&
            NativeMediaContentMime.ProbeFiniteWebmVideo(webm.AsSpan(0, 407), webm.Length), "Actual finite WebM not found in its bounded prefix.");
        TestAssert.That(!NativeMediaContentMime.ProbeFiniteWebmVideo(mkv, mkv.Length), "Matroska with VP8 mislabeled as WebM.");
        foreach (var cutoff in new[] { 0, 4, 17, 52, 250, 315, 406 })
            TestAssert.That(!NativeMediaContentMime.ProbeFiniteWebmVideo(webm.AsSpan(0, cutoff), webm.Length), "Truncated probe accepted: " + cutoff);
        foreach (var (oldBytes, newBytes) in new[] {
            ("webm"u8.ToArray(), "mkv "u8.ToArray()), (new byte[] { 0x83, 0x81, 1 }, new byte[] { 0x83, 0x81, 2 }),
            ("V_VP8"u8.ToArray(), "V_AV1"u8.ToArray()), (new byte[] { 0xb0, 0x81, 16 }, new byte[] { 0xb0, 0x81, 0 }),
            (new byte[] { 0xba, 0x81, 16 }, new byte[] { 0xb0, 0x81, 16 }),
            (new byte[] { 0x18, 0x53, 0x80, 0x67, 1 }, new byte[] { 0x18, 0x53, 0x80, 0x67, 0xff }) })
        {
            var changed = webm.ToArray(); var offset = changed.AsSpan().IndexOf(oldBytes);
            TestAssert.That(offset >= 0, "Mutation no longer matches the source fixture.");
            newBytes.CopyTo(changed, offset);
            TestAssert.That(!NativeMediaContentMime.ProbeFiniteWebmVideo(changed, changed.Length), "Mutated WebM probe passed.");
        }
        foreach (var delta in new[] { -1, 1 })
            TestAssert.That(!NativeMediaContentMime.ProbeFiniteWebmVideo(webm, webm.Length + delta), "Wrong saved file size was accepted.");
        foreach (var kind in new[] { "images", "video" })
            TestAssert.Throws<InvalidDataException>(() => NativeMediaContentMime.Identify(webm, webm.Length, kind), "Probe changed the transport capability.");
        return Task.CompletedTask;
    }
}
