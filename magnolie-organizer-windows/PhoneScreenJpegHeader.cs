using System;
using System.Buffers.Binary;
using System.IO;

namespace MagnolieOrganizer.Windows;

internal static class PhoneScreenJpegHeader
{
    internal const int MaxBytes = 1_048_576;

    internal static bool ValidSize(int width, int height) =>
        width is >= 2 and <= 1920 && height is >= 2 and <= 1920 && width * height <= 1920 * 1080;

    internal static void Require(ReadOnlySpan<byte> jpeg, int width, int height)
    {
        if (!ValidSize(width, height) || jpeg.Length is < 14 or > MaxBytes ||
            jpeg[0] != 0xff || jpeg[1] != 0xd8 || jpeg[^2] != 0xff || jpeg[^1] != 0xd9)
            throw new InvalidDataException("screen_jpeg_envelope_invalid");
        var at = 2;
        var shape = false;
        while (at < jpeg.Length - 4 && jpeg[at++] == 0xff)
        {
            while (at < jpeg.Length && jpeg[at] == 0xff) at++;
            if (at + 3 > jpeg.Length - 2) break;
            byte marker = jpeg[at++];
            int length = BinaryPrimitives.ReadUInt16BigEndian(jpeg[at..]);
            if (length < 2 || length > jpeg.Length - 2 - at) break;
            var field = jpeg.Slice(at + 2, length - 2);
            at += length;
            if (marker == 0xc0)
            {
                if (shape || field.Length != 15 || field[0] != 8 || field[5] != 3 ||
                    BinaryPrimitives.ReadUInt16BigEndian(field[1..]) != height ||
                    BinaryPrimitives.ReadUInt16BigEndian(field[3..]) != width) break;
                shape = true;
            }
            else if (marker == 0xda)
            {
                if (shape && field.Length == 10 && field[0] == 3 && field[^3] == 0 && field[^2] == 63 && field[^1] == 0 &&
                    at < jpeg.Length - 2 && SingleScan(jpeg[at..])) return;
                break;
            }
            else if (marker is not (0xc4 or 0xdb or 0xdd or 0xfe) && marker is not (>= 0xe0 and <= 0xef)) break;
        }
        throw new InvalidDataException("screen_jpeg_baseline_required");
    }

    private static bool SingleScan(ReadOnlySpan<byte> scan)
    {
        for (int at = 0; at < scan.Length - 1;)
        {
            if (scan[at++] != 0xff) continue;
            while (at < scan.Length && scan[at] == 0xff) at++;
            if (at == scan.Length) return false;
            var marker = scan[at++];
            if (marker == 0xd9) return at == scan.Length;
            if (marker != 0 && marker is not (>= 0xd0 and <= 0xd7)) return false;
        }
        return false;
    }
}
