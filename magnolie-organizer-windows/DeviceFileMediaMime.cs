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
            if (WebpImage(prefix, totalBytes)) return "image/webp";
            if (BmpImage(prefix, totalBytes)) return "image/bmp";
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
    // Shared #749 diagnostic subset: classic TIFF, one uncompressed RGB strip.
    // Not wired to Identify or to any native publication/capability.
    internal static bool ProbeTiffRgbImage(ReadOnlySpan<byte> prefix, long totalBytes)
    {
        if (prefix.Length is < 8 or > PrefixBytes || totalBytes < prefix.Length) return false;
        var little = prefix[..4].SequenceEqual("II\x2a\0"u8);
        if (!little && !prefix[..4].SequenceEqual("MM\0\x2a"u8)) return false;
        try
        {
            var directory = checked((int)TiffU32(prefix, 4, little));
            if (directory < 8 || (directory & 1) != 0 || directory > prefix.Length - 2) return false;
            var count = TiffU16(prefix, directory, little);
            var end = directory + 2 + 12 * count + 4;
            if (count is < 1 or > 64 || end > prefix.Length || TiffU32(prefix, end - 4, little) != 0) return false;
            ReadOnlySpan<int> sizes = [0,1,1,2,4,8,1,1,2,4,8,4,8];
            var fields = new Dictionary<int, TiffField>();
            var ranges = new List<(long Start, long End)> { (0, 8), (directory, end) };
            var previous = 0;
            for (var position = directory + 2; position < end - 4; position += 12)
            {
                var tag = TiffU16(prefix, position, little);
                var type = TiffU16(prefix, position + 2, little);
                var items = TiffU32(prefix, position + 4, little);
                if (tag <= previous || type < 1 || type >= sizes.Length || items == 0 || tag is 322 or 323 or 324 or 325 or 330 or 338) return false;
                var length = (long)sizes[type] * items;
                var start = position + 8;
                if (length > 4)
                {
                    start = checked((int)TiffU32(prefix, start, little));
                    if (start < 8 || (start & 1) != 0 || start + length > prefix.Length) return false;
                    ranges.Add((start, start + length));
                }
                fields.Add(tag, new(type, items, start));
                previous = tag;
            }
            var width = TiffScalar(prefix, fields, 256, little, allowLong: true);
            var height = TiffScalar(prefix, fields, 257, little, allowLong: true);
            Dimensions(checked((int)width), checked((int)height));
            var bits = fields[258];
            if (bits.Type != 3 || bits.Items != 3 || TiffU16(prefix, bits.Start, little) != 8 ||
                TiffU16(prefix, bits.Start + 2, little) != 8 || TiffU16(prefix, bits.Start + 4, little) != 8) return false;
            if (TiffScalar(prefix, fields, 259, little) != 1 || TiffScalar(prefix, fields, 262, little) != 2 ||
                TiffScalar(prefix, fields, 266, little, fallback: 1) != 1 || TiffScalar(prefix, fields, 277, little) != 3 ||
                TiffScalar(prefix, fields, 284, little, fallback: 1) != 1 || TiffScalar(prefix, fields, 278, little, allowLong: true) < height) return false;
            var strip = TiffScalar(prefix, fields, 273, little, allowLong: true);
            var bytes = TiffScalar(prefix, fields, 279, little, allowLong: true);
            if (strip < 8 || bytes != 3L * width * height || (long)strip + bytes > totalBytes) return false;
            ranges.Add((strip, (long)strip + bytes));
            ranges.Sort((left, right) => left.Start.CompareTo(right.Start));
            for (var i = 1; i < ranges.Count; i++)
                if (ranges[i - 1].End > ranges[i].Start) return false;
            return true;
        }
        catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or OverflowException) { return false; }
    }

    private readonly record struct TiffField(ushort Type, uint Items, int Start);

    private static ushort TiffU16(ReadOnlySpan<byte> prefix, int at, bool little) => little
        ? BinaryPrimitives.ReadUInt16LittleEndian(prefix[at..]) : BinaryPrimitives.ReadUInt16BigEndian(prefix[at..]);

    private static uint TiffU32(ReadOnlySpan<byte> prefix, int at, bool little) => little
        ? BinaryPrimitives.ReadUInt32LittleEndian(prefix[at..]) : BinaryPrimitives.ReadUInt32BigEndian(prefix[at..]);

    private static uint TiffScalar(ReadOnlySpan<byte> prefix, Dictionary<int, TiffField> fields, int tag,
        bool little, bool allowLong = false, uint? fallback = null)
    {
        if (!fields.TryGetValue(tag, out var field)) return fallback ?? throw DeviceFileControl.Error("media_tiff_required_tag");
        if (field.Items != 1 || (field.Type != 3 && !(allowLong && field.Type == 4)))
            throw DeviceFileControl.Error("media_tiff_scalar_type");
        return field.Type == 3 ? TiffU16(prefix, field.Start, little) : TiffU32(prefix, field.Start, little);
    }

    // Probe only. Keep Identify strict until the selected native counterpart
    // verifies the complete file and has permission to publish an original.
    internal static bool ProbeFiniteWebmVideo(ReadOnlySpan<byte> prefix, long totalBytes)
    {
        if (prefix.Length is < 4 or > PrefixBytes || totalBytes < prefix.Length ||
            BinaryPrimitives.ReadUInt32BigEndian(prefix) != 0x1a45dfa3) return false;
        try
        {
            var header = EbmlRead(prefix, 0, totalBytes);
            if (header.End > 1024) return false;
            var document = EbmlWitnesses(prefix, header.Start, header.End, 0x4282);
            if (!EbmlBytes(prefix, document[0x4282]).SequenceEqual("webm"u8)) return false;
            var segment = EbmlRead(prefix, header.End, totalBytes);
            if (segment.Id != 0x18538067 || segment.End != totalBytes) return false;
            var tracksSeen = false; var video = false;
            var offset = segment.Start;
            for (var count = 0; offset < segment.End && count < 1024; count++)
            {
                var box = EbmlRead(prefix, offset, segment.End); offset = box.End;
                if (box.Id == 0x1f43b675) return video && box.Start < Math.Min(box.End, prefix.Length);
                if (box.Id != 0x1654ae6b) continue;
                if (tracksSeen || box.End > prefix.Length) return false;
                tracksSeen = true; var trackOffset = box.Start;
                for (var index = 0; trackOffset < box.End; index++)
                {
                    if (index >= 1024) return false;
                    var entry = EbmlRead(prefix, trackOffset, box.End); trackOffset = entry.End;
                    if (entry.Id != 0xae) continue;
                    var track = EbmlWitnesses(prefix, entry.Start, entry.End, 0x83, 0x86, 0xe0);
                    if (EbmlUInt(prefix, track[0x83]) != 1) continue;
                    var codec = EbmlBytes(prefix, track[0x86]);
                    if (video || (!codec.SequenceEqual("V_VP8"u8) && !codec.SequenceEqual("V_VP9"u8))) return false;
                    var settings = track[0xe0];
                    var dimensions = EbmlWitnesses(prefix, settings.Start, settings.End, 0xb0, 0xba);
                    Dimensions(checked((int)EbmlUInt(prefix, dimensions[0xb0])), checked((int)EbmlUInt(prefix, dimensions[0xba])));
                    video = true;
                }
            }
        }
        catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or OverflowException) { }
        return false;
    }

    private readonly record struct EbmlElement(long Id, long Start, long End);

    private static EbmlElement EbmlRead(ReadOnlySpan<byte> prefix, long offset, long parentEnd)
    {
        var id = EbmlVint(prefix, ref offset, parentEnd, 4, true);
        var size = EbmlVint(prefix, ref offset, parentEnd, 8, false);
        if (size > parentEnd - offset) throw DeviceFileControl.Error("media_ebml_parent_length");
        return new(id, offset, offset + size);
    }

    private static long EbmlVint(ReadOnlySpan<byte> prefix, ref long offset, long parentEnd, int maxWidth, bool identifier)
    {
        var available = Math.Min(parentEnd, prefix.Length) - offset;
        if (available < 1 || prefix[(int)offset] == 0) throw DeviceFileControl.Error("media_ebml_vint");
        var marker = 128; var width = 1;
        while ((prefix[(int)offset] & marker) == 0) { marker >>= 1; width++; }
        if (width > maxWidth || width > available) throw DeviceFileControl.Error("media_ebml_vint");
        long result = 0;
        for (var i = 0; i < width; i++) result = (result << 8) | prefix[(int)offset++];
        if (!identifier)
        {
            var maximum = (1L << (7 * width)) - 1;
            result &= maximum;
            if (result == maximum) throw DeviceFileControl.Error("media_ebml_unknown_length");
        }
        return result;
    }

    private static Dictionary<long, EbmlElement> EbmlWitnesses(ReadOnlySpan<byte> prefix, long start, long end, params long[] wanted)
    {
        if (end > prefix.Length) throw DeviceFileControl.Error("media_ebml_truncated_metadata");
        var witnesses = new Dictionary<long, EbmlElement>();
        for (var count = 0; start < end; count++)
        {
            if (count >= 1024) throw DeviceFileControl.Error("media_ebml_child_bound");
            var element = EbmlRead(prefix, start, end); start = element.End;
            if (wanted.Contains(element.Id) && !witnesses.TryAdd(element.Id, element))
                throw DeviceFileControl.Error("media_ebml_duplicate_metadata");
        }
        return witnesses;
    }

    private static ReadOnlySpan<byte> EbmlBytes(ReadOnlySpan<byte> prefix, EbmlElement item) => prefix[(int)item.Start..(int)item.End];

    private static ulong EbmlUInt(ReadOnlySpan<byte> prefix, EbmlElement item)
    {
        var value = EbmlBytes(prefix, item);
        if (value.Length is < 1 or > 8) throw DeviceFileControl.Error("media_ebml_integer");
        ulong result = 0;
        foreach (var part in value) result = (result << 8) | part;
        return result;
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

    private static bool BmpImage(ReadOnlySpan<byte> prefix, long totalBytes)
    {
        if (prefix.Length < 54 || !prefix[..2].SequenceEqual("BM"u8) ||
            BinaryPrimitives.ReadUInt32LittleEndian(prefix[2..]) != totalBytes ||
            BinaryPrimitives.ReadUInt32LittleEndian(prefix[6..]) != 0 ||
            BinaryPrimitives.ReadUInt32LittleEndian(prefix[14..]) != 40 ||
            BinaryPrimitives.ReadUInt16LittleEndian(prefix[26..]) != 1 ||
            BinaryPrimitives.ReadUInt16LittleEndian(prefix[28..]) != 24 ||
            BinaryPrimitives.ReadUInt32LittleEndian(prefix[30..]) != 0) return false;
        var offset = BinaryPrimitives.ReadUInt32LittleEndian(prefix[10..]);
        if (offset < 54) return false;
        var width = BinaryPrimitives.ReadInt32LittleEndian(prefix[18..]);
        var height = BinaryPrimitives.ReadInt32LittleEndian(prefix[22..]);
        if (height == int.MinValue) throw DeviceFileControl.Error("media_source_mime_dimensions");
        var rows = Math.Abs(height);
        Dimensions(width, rows);
        var pixels = ((width * 24L + 31) / 32) * 4 * rows;
        var declared = BinaryPrimitives.ReadUInt32LittleEndian(prefix[34..]);
        return (declared == 0 || declared == pixels) && offset + pixels <= totalBytes;
    }

    private static bool WebpImage(ReadOnlySpan<byte> prefix, long totalBytes)
    {
        if (prefix.Length < 20 || !prefix[..4].SequenceEqual("RIFF"u8) || !prefix[8..12].SequenceEqual("WEBP"u8) ||
            BinaryPrimitives.ReadUInt32LittleEndian(prefix[4..]) + 8L != totalBytes) return false;
        (int Width, int Height)? canvas = null;
        long offset = 12;
        while (prefix.Length - offset >= 8)
        {
            var chunk = prefix[(int)offset..];
            var kind = chunk[..4];
            var size = BinaryPrimitives.ReadUInt32LittleEndian(chunk[4..]);
            var end = offset + 8 + size + (size & 1);
            if (size == 0 || end > totalBytes) return false;
            var data = chunk[8..];
            if (kind.SequenceEqual("VP8X"u8))
            {
                if (offset != 12 || size != 10 || data.Length < 10 || (data[0] & 0xc3) != 0 ||
                    data[1] != 0 || data[2] != 0 || data[3] != 0) return false;
                canvas = (1 + data[4] + (data[5] << 8) + (data[6] << 16), 1 + data[7] + (data[8] << 8) + (data[9] << 16));
                Dimensions(canvas.Value.Width, canvas.Value.Height);
            }
            else if (kind.SequenceEqual("VP8 "u8))
            {
                if (size <= 10 || data.Length < 10 || (data[0] & 1) != 0 || !data[3..6].SequenceEqual(new byte[] { 0x9d, 1, 0x2a })) return false;
                var dims = (BinaryPrimitives.ReadUInt16LittleEndian(data[6..]) & 0x3fff,
                    BinaryPrimitives.ReadUInt16LittleEndian(data[8..]) & 0x3fff);
                Dimensions(dims.Item1, dims.Item2);
                return canvas is { } bounds ? dims == bounds : offset == 12 && end == totalBytes;
            }
            else if (kind.SequenceEqual("VP8L"u8))
            {
                if (size <= 5 || data.Length < 5 || data[0] != 0x2f) return false;
                var bits = BinaryPrimitives.ReadUInt32LittleEndian(data[1..]);
                if ((bits >> 29) != 0) return false;
                var dims = (1 + (int)(bits & 0x3fff), 1 + (int)((bits >> 14) & 0x3fff));
                Dimensions(dims.Item1, dims.Item2);
                return canvas is { } bounds ? dims == bounds : offset == 12 && end == totalBytes;
            }
            else if (canvas is null || kind.SequenceEqual("ANIM"u8) || kind.SequenceEqual("ANMF"u8)) return false;
            offset = end;
        }
        return false;
    }
}
