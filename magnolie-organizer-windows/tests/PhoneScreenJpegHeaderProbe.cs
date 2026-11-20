#if MAGNOLIE_PHONE_SCREEN_JPEG_PROBE
using System;
using System.IO;

namespace MagnolieOrganizer.Windows;

internal static class PhoneScreenJpegHeaderProbe
{
    // Minimal baseline marker fixture; decoding the actual picture is a separate GDI+ test.
    private const string Shape = "ffc00011080010001103011100021101031101";
    private const string Scan = "ffda000c03010002110311003f00";
    private const string Jpeg = "ffd8" + Shape + Scan + "12ff0034ffd056ffd9";

    public static void Main()
    {
        PhoneScreenJpegHeader.Require(Convert.FromHexString(Jpeg), 17, 16);
        CheckBad(Jpeg, 18, 16);
        CheckBad(Jpeg.Replace("ffc0", "ffc2"));
        CheckBad(Jpeg.Replace(Shape, Shape + Shape));
        CheckBad(Jpeg.Replace("ff0034", "ffd834"));
        CheckBad(Jpeg.Replace("ff0034", "ffd934"));
        CheckBad(Jpeg.Replace("ff0034", "ffda34"));
        CheckBad(Jpeg[..^4]);
        CheckBad(Jpeg + "ffd9");
        try { PhoneScreenJpegHeader.Require(new byte[PhoneScreenJpegHeader.MaxBytes + 1], 17, 16); }
        catch (InvalidDataException) { Console.WriteLine("10/10 bounded Windows JPEG-header checks (managed Linux)"); return; }
        throw new Exception("Accepted oversized JPEG");
    }

    private static void CheckBad(string hex, int width = 17, int height = 16)
    {
        try { PhoneScreenJpegHeader.Require(Convert.FromHexString(hex), width, height); }
        catch (InvalidDataException) { return; }
        throw new Exception("Accepted invalid JPEG envelope");
    }
}
#endif
