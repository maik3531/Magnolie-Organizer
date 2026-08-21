using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class PhoneUri
{
    internal static string Normalize(string value, string country)
    {
        var candidate = value.Trim();
        if (candidate.StartsWith("tel:", StringComparison.OrdinalIgnoreCase)) candidate = candidate[4..];
        if (candidate.Length is 0 or > 64 || !Regex.IsMatch(candidate, @"^[0-9+()./\s-]+$")) return "";
        if (candidate.Count(character => character == '+') > 1 ||
            (candidate.Contains('+') && !candidate.TrimStart().StartsWith('+'))) return "";
        var number = Regex.Replace(candidate, @"[^\d+]", "");
        if (number.StartsWith("00", StringComparison.Ordinal)) number = "+" + number[2..];
        if (number.StartsWith('0') && !number.StartsWith("00", StringComparison.Ordinal))
            number = (country.Trim().ToUpperInvariant() switch
            {
                "AT" or "ÖSTERREICH" => "+43", "CH" or "SCHWEIZ" => "+41", _ => "+49"
            }) + number[1..];
        var digits = number.Count(char.IsDigit);
        return digits is < 6 or > 15 || (number.Contains('+') && !number.StartsWith('+')) ? "" : number;
    }

    internal static string Build(string service, string value, string country,
        bool teamsAvailable)
    {
        var number = Normalize(value, country);
        if (number.Length == 0) return "";
        return service == "teams-call"
            ? (teamsAvailable ? "msteams:/l/call/0/0?users=" + Uri.EscapeDataString("4:" + number) : "")
            : "tel:" + number;
    }
}
