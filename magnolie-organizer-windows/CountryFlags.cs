namespace MagnolieOrganizer.Windows;

internal static class CountryFlags
{
    internal const int CellWidth = 64, CellHeight = 48;
    internal static bool TryCell(string? value, out int x, out int y)
    {
        var code = value?.Trim().ToUpperInvariant() ?? "";
        x = y = 0;
        if (code.Length != 2 || code.Any(ch => ch is < 'A' or > 'Z') || PhoneRegionInfo.HomeCountry(code) != code) return false;
        x = (code[1] - 'A') * CellWidth; y = (code[0] - 'A') * CellHeight;
        return true;
    }
#if WINDOWS
    private static readonly Lazy<System.Drawing.Bitmap?> Atlas = new(() =>
    {
        try
        {
            using var source = System.Drawing.Image.FromFile(Path.Combine(AppContext.BaseDirectory, "web", "country-flags.png"));
            return source.Width == 26 * CellWidth && source.Height == 26 * CellHeight ? new System.Drawing.Bitmap(source) : null;
        }
        catch (Exception error) when (error is IOException or ArgumentException or OutOfMemoryException) { return null; }
    });
    internal static System.Drawing.Bitmap? Image(string? value)
    {
        if (!TryCell(value, out var x, out var y) || Atlas.Value is not { } atlas) return null;
        return atlas.Clone(new System.Drawing.Rectangle(x, y, CellWidth, CellHeight), System.Drawing.Imaging.PixelFormat.Format32bppArgb);
    }
#endif
}
