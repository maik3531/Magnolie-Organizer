using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using PhoneNumbers;

namespace MagnolieOrganizer.Windows;

internal sealed record PhoneOrigin(string Status, string E164, string Region,
    string CountryName, bool? IsForeign, string DisplayHint)
{
    internal static readonly PhoneOrigin Unknown = new("unknown", "", "", "", null, "");
}

internal static class PhoneRegionInfo
{
    private static readonly HashSet<string> IsoCountries = new(
        "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".Split(' '),
        StringComparer.Ordinal);

    internal static string HomeCountry(string? value)
    {
        var candidate = (value ?? "").Trim().ToUpperInvariant();
        return IsoCountries.Contains(candidate) ? candidate : "DE";
    }

    internal static PhoneOrigin Analyze(string? number, string numberStatus = "available",
        string? country = null, string? language = null)
    {
        if (numberStatus != "available" || string.IsNullOrWhiteSpace(number) || number.Length > 128)
            return PhoneOrigin.Unknown;
        try { return AnalyzeWithLibrary(number, HomeCountry(country ?? RegionalSettings.HomeCountry()),
            NormalizeLanguage(language ?? NativeLocalization.Language)); }
        catch (Exception) { return PhoneOrigin.Unknown; }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static PhoneOrigin AnalyzeWithLibrary(string number, string homeCountry, string language)
    {
        var utility = PhoneNumberUtil.GetInstance();
        var parsed = utility.Parse(System.Text.RegularExpressions.Regex.Replace(number.Trim(), @"^\+{2,}(?=\d)", "+"), homeCountry);
        if (!utility.IsValidNumber(parsed)) return PhoneOrigin.Unknown;
        var region = utility.GetRegionCodeForNumber(parsed);
        if (region is null || !IsoCountries.Contains(region)) return PhoneOrigin.Unknown;
        var countryName = new Locale("", region).GetDisplayCountry(language);
        if (string.IsNullOrWhiteSpace(countryName)) return PhoneOrigin.Unknown;
        var e164 = utility.Format(parsed, PhoneNumberFormat.E164);
        var foreign = !StringComparer.Ordinal.Equals(region, homeCountry);
        return new PhoneOrigin("known", e164, region, countryName, foreign,
            $"{countryName} ({homeCountry}{(foreign ? " -> " : " = ")}{region})");
    }

    internal static string MatchKey(string? number, string? country = null) =>
        Analyze(number, country: country, language: "en").E164;

    internal static JsonObject Enrich(JsonObject value, string? country = null, string? language = null)
    {
        var result = value.DeepClone().AsObject();
        var origin = Analyze(result["number"]?.GetValue<string>(),
            result["number_status"]?.GetValue<string>() ?? "unavailable", country, language);
        result["phone_origin_status"] = origin.Status;
        result["phone_e164"] = origin.E164;
        result["phone_region"] = origin.Region;
        result["phone_country_name"] = origin.CountryName;
        result["phone_is_foreign"] = origin.IsForeign;
        result["phone_display_hint"] = origin.DisplayHint;
        return result;
    }

    private static string NormalizeLanguage(string value)
    {
        var language = value.Replace('-', '_').Split('_', 2)[0].ToLowerInvariant();
        return language.Length is 2 or 3 && language.All(char.IsAsciiLetter) ? language : "en";
    }
}
