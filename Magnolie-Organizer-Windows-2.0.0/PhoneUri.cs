using System.Text.RegularExpressions;
using PhoneNumbers;

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
        var utility = PhoneNumberUtil.GetInstance();
        candidate = Regex.Replace(candidate, @"^\+(\d{1,3})\s*\(0\)", match =>
            utility.GetSupportedRegions().Any(region => utility.GetCountryCodeForRegion(region).ToString() == match.Groups[1].Value &&
                utility.GetNddPrefixForRegion(region, true) == "0") ? "+" + match.Groups[1].Value : match.Value);
        var number = Regex.Replace(candidate, @"[^\d+]", "");
        if (number.StartsWith("00", StringComparison.Ordinal)) number = "+" + number[2..];
        if (number.StartsWith('+'))
            return Regex.IsMatch(number, @"^\+[1-9][0-9]{5,14}$") ? number : "";
        var region = country.Trim().ToUpperInvariant() switch {
            "DEUTSCHLAND" or "GERMANY" => "DE", "ÖSTERREICH" or "AUSTRIA" => "AT",
            "SCHWEIZ" or "SWITZERLAND" => "CH", var code => code };
        if (!utility.GetSupportedRegions().Contains(region)) return "";
        try
        {
            var parsed = utility.Parse(candidate, region);
            return utility.IsPossibleNumber(parsed) ? utility.Format(parsed, PhoneNumberFormat.E164) : "";
        }
        catch (NumberParseException) { return ""; }
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
