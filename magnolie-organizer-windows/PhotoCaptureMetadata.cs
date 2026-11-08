using System.Buffers.Binary;
using System.Globalization;
using System.Text;

namespace MagnolieOrganizer.Windows;

// Bounded selection criterion only, never media-format or provenance authority.
internal static class PhotoCaptureMetadata
{
    internal const int MaximumBytes = 1024 * 1024;
    private readonly record struct Tag(ushort Kind, uint Count, int Value);

    internal static bool Matches(ReadOnlySpan<byte> data)
    {
        if (data.Length > MaximumBytes) return false;
        try
        {
            if (data.StartsWith("II"u8) || data.StartsWith("MM"u8)) return Tiff(data);
            if (data.StartsWith(new byte[] { 255, 216 }))
            {
                var offset = 2;
                while (offset + 4 <= data.Length)
                {
                    if (data[offset] != 255) return false;
                    while (offset < data.Length && data[offset] == 255) offset++;
                    if (offset + 3 > data.Length || data[offset] is 0 or 217 or 218) return false;
                    var marker = data[offset++]; var size = BinaryPrimitives.ReadUInt16BigEndian(data.Slice(offset, 2));
                    if (size < 2 || offset + size > data.Length) return false;
                    var payload = data.Slice(offset + 2, size - 2);
                    if (marker == 225 && payload.StartsWith("Exif\0\0"u8)) return Tiff(payload[6..]);
                    offset += size;
                }
            }
            else if (data.StartsWith(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }))
            {
                var offset = 8;
                while (offset + 12 <= data.Length)
                {
                    var size = BinaryPrimitives.ReadUInt32BigEndian(data.Slice(offset, 4));
                    if ((long)offset + size + 12 > data.Length) return false;
                    var kind = data.Slice(offset + 4, 4);
                    if (kind.SequenceEqual("eXIf"u8)) return Tiff(data.Slice(offset + 8, (int)size));
                    if (kind.SequenceEqual("IEND"u8)) return false;
                    offset += (int)size + 12;
                }
            }
        }
        catch (ArgumentOutOfRangeException) { }
        catch (OverflowException) { }
        catch (InvalidDataException) { }
        return false;
    }

    private static ushort U16(ReadOnlySpan<byte> data, int offset, bool little) => little
        ? BinaryPrimitives.ReadUInt16LittleEndian(data.Slice(offset, 2)) : BinaryPrimitives.ReadUInt16BigEndian(data.Slice(offset, 2));
    private static uint U32(ReadOnlySpan<byte> data, int offset, bool little) => little
        ? BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(offset, 4)) : BinaryPrimitives.ReadUInt32BigEndian(data.Slice(offset, 4));
    private static Dictionary<ushort, Tag> Directory(ReadOnlySpan<byte> data, int offset, bool little)
    {
        if (offset < 8) throw new InvalidDataException("photo_metadata_directory_invalid");
        var count = U16(data, offset, little);
        if (count > 256 || (long)offset + 2 + count * 12 + 4 > data.Length) throw new InvalidDataException("photo_metadata_directory_invalid");
        var result = new Dictionary<ushort, Tag>();
        for (var index = 0; index < count; index++)
        {
            var item = offset + 2 + index * 12;
            if (!result.TryAdd(U16(data, item, little), new(U16(data, item + 2, little), U32(data, item + 4, little), item + 8)))
                throw new InvalidDataException("photo_metadata_ambiguous_tag");
        }
        return result;
    }
    private static string? Text(ReadOnlySpan<byte> data, Dictionary<ushort, Tag> tags, ushort id, int maximum, bool little)
    {
        if (!tags.TryGetValue(id, out var tag) || tag.Kind != 2 || tag.Count < 2 || tag.Count > maximum + 1) return null;
        var offset = tag.Count <= 4 ? tag.Value : checked((int)U32(data, tag.Value, little));
        if ((long)offset + tag.Count > data.Length) return null;
        var raw = data.Slice(offset, (int)tag.Count);
        if (raw[^1] != 0) return null;
        foreach (var value in raw[..^1]) if (value is < 32 or > 126) return null;
        return Encoding.ASCII.GetString(raw[..^1]);
    }
    private static bool Tiff(ReadOnlySpan<byte> data)
    {
        if (data.Length < 8 || !data.StartsWith("II"u8) && !data.StartsWith("MM"u8)) return false;
        var little = data[0] == 73;
        if (U16(data, 2, little) != 42) return false;
        var tags = Directory(data, checked((int)U32(data, 4, little)), little);
        if (string.IsNullOrWhiteSpace(Text(data, tags, 0x010f, 128, little)) && string.IsNullOrWhiteSpace(Text(data, tags, 0x0110, 128, little))) return false;
        if (!tags.TryGetValue(0x8769, out var pointer) || pointer.Kind != 4 || pointer.Count != 1) return false;
        var capture = Directory(data, checked((int)U32(data, pointer.Value, little)), little);
        var taken = Text(data, capture, 0x9003, 19, little);
        return taken?.Length == 19 && DateTime.TryParseExact(taken, "yyyy:MM:dd HH:mm:ss", CultureInfo.InvariantCulture,
            DateTimeStyles.None, out var date) && date.Year >= 1900;
    }
}
