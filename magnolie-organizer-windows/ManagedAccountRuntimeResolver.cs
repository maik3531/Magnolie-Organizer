using System.Diagnostics;
using System.IO.Compression;
using System.Text.Json.Nodes;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal static class ManagedAccountRuntimeResolver
{
    private const string ThunderbirdId = "{3550f703-e582-4d05-9a08-453d09bdfdc6}";

    internal static IEnumerable<string> InstalledExecutables()
    {
        if (!OperatingSystem.IsWindows()) return [];
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
            foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
            {
                try
                {
                    using var registry = RegistryKey.OpenBaseKey(hive, view);
                    using var key = registry.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\thunderbird.exe");
                    if (key?.GetValue("") is string path && Path.IsPathFullyQualified(path.Trim('"')))
                        paths.Add(Path.GetFullPath(path.Trim('"')));
                }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException or ArgumentException) { }
            }
        foreach (var folder in new[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86,
            Environment.SpecialFolder.LocalApplicationData })
        {
            var root = Environment.GetFolderPath(folder);
            if (root.Length != 0) paths.Add(Path.Combine(root, "Mozilla Thunderbird", "thunderbird.exe"));
        }
        return paths;
    }

    internal static AccountRuntimeCandidate? ReadCandidate(string executable, AccountRuntimeSource source)
    {
        try
        {
            executable = Path.GetFullPath(executable);
            var directory = Path.GetDirectoryName(executable)!;
            if (!File.Exists(executable) || (File.GetAttributes(executable) & FileAttributes.ReparsePoint) != 0 ||
                (File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0 || !IsX64(executable) || !MozillaCodeTrust.IsTrusted(executable)) return null;
            var application = ReadIni(Path.Combine(directory, "application.ini"), "App");
            if (application.GetValueOrDefault("ID") != ThunderbirdId || application.GetValueOrDefault("Name") != "Thunderbird" ||
                FileVersionInfo.GetVersionInfo(executable).ProductName?.Contains("Thunderbird", StringComparison.OrdinalIgnoreCase) != true) return null;
            var build = MozillaRuntimeBuild.Parse(application["Version"] + "_" + application["BuildID"]);
            var binary = MozillaRuntimeBuild.Parse(FileVersionInfo.GetVersionInfo(executable).ProductVersion ?? "");
            if (binary.Version != build.Version) return null;
            return new(executable, build, source, true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException or InvalidDataException or KeyNotFoundException)
        { return null; }
    }

    internal static IReadOnlyList<AccountAddonCompatibility> ProviderCompatibility(string runtime)
    {
        var result = new List<AccountAddonCompatibility>();
        foreach (var id in new[] { "tbsync@jobisoft.de", "eas4tbsync@jobisoft.de" })
        {
            var path = Path.Combine(runtime, "magnolie-extensions", id + ".xpi");
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Account extensions cannot be links.");
            using var archive = ZipFile.OpenRead(path);
            var manifest = archive.GetEntry("manifest.json") ?? throw new InvalidDataException("Account extension manifest is missing.");
            if (manifest.Length is < 1 or > 256 * 1024) throw new InvalidDataException("Account extension manifest is invalid.");
            using var reader = new StreamReader(manifest.Open());
            var gecko = JsonNode.Parse(reader.ReadToEnd())?["browser_specific_settings"]?["gecko"] as JsonObject ??
                throw new InvalidDataException("Account extension compatibility is missing.");
            if (gecko["id"]?.GetValue<string>() != id) throw new InvalidDataException("Account extension identity changed.");
            result.Add(AccountAddonCompatibility.Parse(gecko["strict_min_version"]?.GetValue<string>() ?? throw new InvalidDataException(),
                gecko["strict_max_version"]?.GetValue<string>() ?? throw new InvalidDataException()));
        }
        return result;
    }

    internal static AccountRuntimeCandidate? SelectExisting(string profile, string packagedRuntime,
        IEnumerable<string> managedRuntimes, IEnumerable<string>? installedExecutables = null)
    {
        var requirement = ManagedAccountRuntimePolicy.ProfileRequirement(profile);
        var extensions = ProviderCompatibility(packagedRuntime);
        var candidates = new List<AccountRuntimeCandidate>();
        foreach (var executable in (installedExecutables ?? InstalledExecutables()).Distinct(StringComparer.OrdinalIgnoreCase).Take(32))
            if (ReadCandidate(executable, AccountRuntimeSource.Installed) is { } candidate) candidates.Add(candidate);
        foreach (var directory in managedRuntimes.Prepend(packagedRuntime).Distinct(StringComparer.OrdinalIgnoreCase).Take(32))
            if (ReadCandidate(Path.Combine(directory, "thunderbird.exe"), AccountRuntimeSource.Managed) is { } candidate) candidates.Add(candidate);
        return ManagedAccountRuntimePolicy.Select(candidates, requirement, extensions);
    }

    internal static Dictionary<string, string> ReadIni(string path, string requestedSection)
    {
        var file = new FileInfo(path);
        if (!file.Exists || file.Length is < 1 or > 256 * 1024 || (file.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Invalid Mozilla application metadata.");
        var section = "";
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var line in File.ReadLines(path))
        {
            var text = line.Trim();
            if (text.StartsWith('[') && text.EndsWith(']')) { section = text[1..^1]; continue; }
            var separator = text.IndexOf('=');
            if (section != requestedSection || separator < 1 || text.StartsWith(';') || text.StartsWith('#')) continue;
            if (!values.TryAdd(text[..separator], text[(separator + 1)..])) throw new InvalidDataException("Duplicate Mozilla metadata.");
        }
        return values;
    }

    private static bool IsX64(string path)
    {
        using var stream = File.OpenRead(path);
        using var reader = new BinaryReader(stream);
        if (stream.Length < 64 || reader.ReadUInt16() != 0x5A4D) return false;
        stream.Position = 0x3C;
        var offset = reader.ReadInt32();
        if (offset < 64 || offset > stream.Length - 6) return false;
        stream.Position = offset;
        return reader.ReadUInt32() == 0x00004550 && reader.ReadUInt16() == 0x8664;
    }
}
