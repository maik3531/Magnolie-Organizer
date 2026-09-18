namespace MagnolieOrganizer.Windows;

internal sealed record WeatherLocation(string SearchLocation, string Source)
{
    internal bool ShouldFetch => Source != "none";
}

internal static class WeatherLocationSelector
{
    internal static WeatherLocation Select(string? savedLocation, bool allowApproximate,
        Func<LibreOfficeUserDataResult?>? libreOfficeLoader = null)
    {
        var location = Usable(savedLocation);
        if (location.Length > 0) return new WeatherLocation(location, "adresse");

        try
        {
            var fields = (libreOfficeLoader ?? (() => LibreOfficeUserData.Read()))()?.Felder;
            if (fields is not null)
            {
                fields.TryGetValue("postalcode", out var postalCode);
                fields.TryGetValue("l", out var city);
                location = Usable(string.Join(' ', new[] { postalCode, city }
                    .Where(value => !string.IsNullOrWhiteSpace(value))));
                if (location.Length > 0) return new WeatherLocation(location, "libreoffice");
            }
        }
        catch (Exception)
        {
            // LibreOffice is an optional local fallback; its failures must not break weather handling.
        }

        return allowApproximate
            ? new WeatherLocation("", "ip")
            : new WeatherLocation("", "none");
    }

    private static string Usable(string? value)
    {
        var location = (value ?? "").Trim();
        if (!location.Any(char.IsLetterOrDigit)) return "";
        return location[..Math.Min(120, location.Length)];
    }
}
