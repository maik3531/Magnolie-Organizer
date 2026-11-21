using System.Buffers.Binary;

namespace MagnolieOrganizer.Windows;

// Bounded container identification from authenticated cache bytes, never from
// filenames. This is not pixel validation; the native receiving decoder still
// validates the complete hash-verified file before publication.
internal static class NativeMediaContentMime
{
    internal const int PrefixBytes = 1024 * 1024;
    // Only an independently admitted collection source may use this deny-only
    // distinction. Unknown/broken bytes still HOLD; the real sender stays strict.
    internal static string IdentifyCollection(ReadOnlySpan<byte> prefix, long totalBytes, string kind)
    {
        if (kind is not ("images" or "video")) throw DeviceFileControl.Error("media_source_mime_unknown");
        try { return Identify(prefix, totalBytes, kind); }
        catch (InvalidDataException error) when (error.Message == "media_source_mime_unknown") { }
        _ = Identify(prefix, totalBytes, kind == "images" ? "video" : "images");
        throw DeviceFileControl.Error("media_collection_known_other_type");
    }
    internal static string Identify(ReadOnlySpan<byte> prefix, long totalBytes, string kind)
    {
        if (prefix.Length > PrefixBytes || totalBytes < prefix.Length || totalBytes < 1)
            throw DeviceFileControl.Error("media_source_mime_bound");
        if (kind == "images")
        {
            if (prefix.Length >= 6 && (prefix[..6].SequenceEqual("GIF87a"u8) || prefix[..6].SequenceEqual("GIF89a"u8)) &&
                GifImage(prefix)) return "image/gif";
            if (prefix.Length >= 33 && prefix[..16].SequenceEqual(new byte[] { 137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82 }))
            {
                Dimensions(BinaryPrimitives.ReadInt32BigEndian(prefix[16..20]), BinaryPrimitives.ReadInt32BigEndian(prefix[20..24]));
                if (prefix[24] is not (1 or 2 or 4 or 8 or 16) || prefix[25] is not (0 or 2 or 3 or 4 or 6) ||
                    prefix[26] != 0 || prefix[27] != 0 || prefix[28] > 1) throw DeviceFileControl.Error("media_source_mime_unknown");
                return "image/png";
            }
            if (prefix.Length >= 4 && prefix[0] == 255 && prefix[1] == 216)
            {
                var offset = 2;
                while (offset < prefix.Length)
                {
                    if (prefix[offset] != 255) break;
                    while (offset < prefix.Length && prefix[offset] == 255) offset++;
                    if (offset >= prefix.Length) break;
                    var marker = prefix[offset++];
                    if (marker is 0 or 0xd9 or 0xda) break;
                    if (marker == 1 || marker is >= 0xd0 and <= 0xd8) continue;
                    if (offset + 2 > prefix.Length) break;
                    var length = BinaryPrimitives.ReadUInt16BigEndian(prefix[offset..]);
                    if (length < 2 || length > prefix.Length - offset) break;
                    if (marker is >= 0xc0 and <= 0xc3 or >= 0xc5 and <= 0xc7 or >= 0xc9 and <= 0xcb or >= 0xcd and <= 0xcf)
                    {
                        if (length < 8 || prefix[offset + 2] is not (8 or 12)) break;
                        Dimensions(BinaryPrimitives.ReadUInt16BigEndian(prefix[(offset + 5)..]), BinaryPrimitives.ReadUInt16BigEndian(prefix[(offset + 3)..]));
                        return "image/jpeg";
                    }
                    offset += length;
                }
            }
        }
        else if (kind == "video" && prefix.Length >= 16 && prefix[4..8].SequenceEqual("ftyp"u8))
        {
            var length = BinaryPrimitives.ReadUInt32BigEndian(prefix);
            if (length is >= 16 and <= 1024 && length <= prefix.Length && (length - 16) % 4 == 0)
            {
                var brand = prefix[8..12];
                if (brand.SequenceEqual("qt  "u8)) return "video/quicktime";
                if (brand.SequenceEqual("isom"u8) || brand.SequenceEqual("iso2"u8) || brand.SequenceEqual("mp41"u8) ||
                    brand.SequenceEqual("mp42"u8) || brand.SequenceEqual("avc1"u8) || brand.SequenceEqual("M4V "u8)) return "video/mp4";
            }
        }
        throw DeviceFileControl.Error("media_source_mime_unknown");
    }
    private static bool GifImage(ReadOnlySpan<byte> prefix)
    {
        if (prefix.Length < 13) return false;
        var width = BinaryPrimitives.ReadUInt16LittleEndian(prefix[6..]);
        var height = BinaryPrimitives.ReadUInt16LittleEndian(prefix[8..]);
        Dimensions(width, height);
        var globalTable = (prefix[10] & 128) != 0 ? 3 * (2 << (prefix[10] & 7)) : 0;
        var offset = 13 + globalTable;
        while (offset < prefix.Length)
        {
            var marker = prefix[offset++];
            if (marker == 0x2c)
            {
                if (prefix.Length - offset < 9) return false;
                var left = BinaryPrimitives.ReadUInt16LittleEndian(prefix[offset..]);
                var top = BinaryPrimitives.ReadUInt16LittleEndian(prefix[(offset + 2)..]);
                var columns = BinaryPrimitives.ReadUInt16LittleEndian(prefix[(offset + 4)..]);
                var rows = BinaryPrimitives.ReadUInt16LittleEndian(prefix[(offset + 6)..]);
                Dimensions(columns, rows);
                if (left + columns > width || top + rows > height) return false;
                var flags = prefix[offset + 8];
                var localTable = (flags & 128) != 0 ? 3 * (2 << (flags & 7)) : 0;
                if (globalTable == 0 && localTable == 0) return false;
                offset += 9 + localTable;
                return prefix.Length - offset >= 3 && prefix[offset] is >= 2 and <= 8 &&
                    prefix[offset + 1] > 0 && prefix[offset + 1] <= prefix.Length - offset - 2;
            }
            if (marker != 0x21 || offset >= prefix.Length) return false;
            offset++; // Extension label, followed by length-delimited sub-blocks.
            while (true)
            {
                if (offset >= prefix.Length) return false;
                var size = prefix[offset++];
                if (size == 0) break;
                offset += size;
            }
        }
        return false;
    }
    private static void Dimensions(int width, int height)
    {
        if (width is < 1 or > 32768 || height is < 1 or > 32768 || (long)width * height > 24000000)
            throw DeviceFileControl.Error("media_source_mime_dimensions");
    }
}
