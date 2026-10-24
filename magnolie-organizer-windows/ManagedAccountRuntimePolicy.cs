using System.Globalization;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record MozillaRuntimeBuild(Version Version, long BuildId) : IComparable<MozillaRuntimeBuild>
{
    internal static MozillaRuntimeBuild Parse(string value)
    {
        var match = Regex.Match(value, @"^(?<version>\d+\.\d+(?:\.\d+){0,2})(?:esr)?(?:_(?<build>\d{14}))?$",
            RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(100));
        if (!match.Success || !Version.TryParse(match.Groups["version"].Value, out var version))
            throw new InvalidDataException("Unsupported Thunderbird version metadata.");
        var build = match.Groups["build"].Success
            ? long.Parse(match.Groups["build"].Value, CultureInfo.InvariantCulture) : 0;
        return new(new Version(version.Major, version.Minor, Math.Max(0, version.Build), Math.Max(0, version.Revision)), build);
    }

    public int CompareTo(MozillaRuntimeBuild? other)
    {
        if (other is null) return 1;
        var version = Version.CompareTo(other.Version);
        return version != 0 ? version : BuildId.CompareTo(other.BuildId);
    }
}

internal sealed record AccountAddonCompatibility(Version Minimum, Version? Maximum, bool MaximumExclusive)
{
    internal static AccountAddonCompatibility Parse(string? minimum, string? maximum)
    {
        var min = MozillaRuntimeBuild.Parse(minimum ?? "0.0").Version;
        if (maximum is null or "*") return new(min, null, false);
        if (!maximum.EndsWith(".*", StringComparison.Ordinal))
            return new(min, MozillaRuntimeBuild.Parse(maximum).Version, false);
        var prefix = maximum[..^2].Split('.');
        if (prefix.Length is < 1 or > 3 || prefix.Any(part => !int.TryParse(part, NumberStyles.None, CultureInfo.InvariantCulture, out var number) || number < 0 || number == int.MaxValue))
            throw new InvalidDataException("Unsupported Thunderbird extension version range.");
        var parts = prefix.Select(part => int.Parse(part, CultureInfo.InvariantCulture)).ToArray();
        parts[^1]++;
        var limit = new Version(parts[0], parts.Length > 1 ? parts[1] : 0, parts.Length > 2 ? parts[2] : 0, 0);
        return new(min, limit, true);
    }

    internal bool Supports(Version version) => version >= Minimum &&
        (Maximum is null || (MaximumExclusive ? version < Maximum : version <= Maximum));
}

internal enum AccountRuntimeSource { Installed, Managed }
internal sealed record AccountRuntimeCandidate(string Executable, MozillaRuntimeBuild Build, AccountRuntimeSource Source, bool Trusted);

/** Selection only: never start a process, reset a profile or relax an extension manifest. */
internal static class ManagedAccountRuntimePolicy
{
    internal static string UpdateVersion(string latest, MozillaRuntimeBuild? profile, MozillaRuntimeBuild packaged,
        IReadOnlyList<AccountAddonCompatibility> extensions)
    {
        if (extensions.Count == 0 || !Regex.IsMatch(latest, @"^\d+\.\d+(?:\.\d+){0,2}$", RegexOptions.CultureInvariant))
            throw new InvalidDataException("Mozilla release compatibility is missing or invalid.");
        var release = MozillaRuntimeBuild.Parse(latest).Version;
        var minimum = profile is not null && profile.Version > packaged.Version ? profile.Version : packaged.Version;
        var selected = release >= minimum && extensions.All(extension => extension.Supports(release)) ? release : minimum;
        if (extensions.Any(extension => !extension.Supports(selected)))
            throw new InvalidDataException("No supported Mozilla release can satisfy the account profile and providers.");
        // A newer unsupported system/release major must not block repair of the
        // exact known supported profile version from Mozilla's signed archive.
        return selected.ToString(selected.Revision > 0 ? 4 : selected.Build > 0 ? 3 : 2);
    }

    internal static MozillaRuntimeBuild? ProfileRequirement(string profile)
    {
        var path = Path.Combine(profile, "compatibility.ini");
        if (!File.Exists(path)) return null;
        var file = new FileInfo(path);
        if (file.Length is < 1 or > 64 * 1024 || (file.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Invalid account-profile compatibility metadata.");
        var section = "";
        string? lastVersion = null;
        foreach (var line in File.ReadLines(path))
        {
            var text = line.Trim();
            if (text.StartsWith('[') && text.EndsWith(']')) { section = text[1..^1]; continue; }
            if (section == "Compatibility" && text.StartsWith("LastVersion=", StringComparison.Ordinal))
            {
                if (lastVersion is not null) throw new InvalidDataException("Ambiguous account-profile compatibility metadata.");
                lastVersion = text["LastVersion=".Length..];
            }
        }
        return MozillaRuntimeBuild.Parse(lastVersion ?? throw new InvalidDataException("Account-profile compatibility version is missing."));
    }

    internal static AccountRuntimeCandidate? Select(IEnumerable<AccountRuntimeCandidate> candidates,
        MozillaRuntimeBuild? profile, IReadOnlyList<AccountAddonCompatibility> extensions)
    {
        if (extensions.Count == 0) throw new InvalidDataException("Account-provider compatibility is missing.");
        var compatible = candidates.Where(candidate => candidate.Trusted && extensions.All(extension => extension.Supports(candidate.Build.Version)) &&
            (profile is null || candidate.Build.CompareTo(profile) >= 0)).ToArray();
        // Prefer an already installed compatible application; a newer but
        // incompatible system upgrade must not upgrade the isolated profile.
        return compatible.Where(candidate => candidate.Source == AccountRuntimeSource.Installed)
            .OrderByDescending(candidate => candidate.Build).FirstOrDefault() ??
            compatible.Where(candidate => candidate.Source == AccountRuntimeSource.Managed)
                .OrderByDescending(candidate => candidate.Build).FirstOrDefault();
    }
}
