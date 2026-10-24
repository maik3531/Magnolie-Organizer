using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record FilesystemPrerequisite(string Kind, string Filename, string Url, string Sha256, string Publisher);

/** Installer/portable utility only; filesystem status and phone requests never install system components. */
internal static class FilesystemRuntimeSetup
{
    internal const string SetupArgument = "--prepare-phone-filesystem";
    internal const string StatusArgument = "--phone-filesystem-runtime-status";
    internal static bool Available => KdeWindowsFilesystemBrowser.WinFspInstalled() && KdeWindowsFilesystemBrowser.SshfsInstalled() is not null;

    internal static IReadOnlyList<FilesystemPrerequisite> Packages()
    {
        using var input = typeof(FilesystemRuntimeSetup).Assembly.GetManifestResourceStream("Magnolie.FilesystemPrerequisites.json") ??
            throw new InvalidDataException("Filesystem prerequisite metadata is missing.");
        using var reader = new StreamReader(input);
        var metadata = JsonNode.Parse(reader.ReadToEnd())!.AsObject();
        if (metadata["schema"]?.GetValue<int>() != 1 || metadata["packages"] is not JsonArray packages || packages.Count != 2)
            throw new InvalidDataException("Filesystem prerequisite metadata is invalid.");
        var values = packages.OfType<JsonObject>().Select(package => new FilesystemPrerequisite(
            package["kind"]!.GetValue<string>(), package["filename"]!.GetValue<string>(), package["url"]!.GetValue<string>(),
            package["sha256"]!.GetValue<string>(), package["publisher"]!.GetValue<string>())).ToArray();
        if (!values.Select(value => value.Kind).Order().SequenceEqual(new[] { "client", "driver" }) ||
            values.Any(value => Path.GetFileName(value.Filename) != value.Filename || !value.Filename.EndsWith(".msi", StringComparison.OrdinalIgnoreCase) ||
                value.Sha256.Length != 64 || !Uri.TryCreate(value.Url, UriKind.Absolute, out var uri) || uri.Scheme != "https"))
            throw new InvalidDataException("Filesystem prerequisite selection is invalid.");
        return values;
    }

    internal static void ValidatePackages(string directory)
    {
        foreach (var package in Packages())
        {
            var path = Path.Combine(directory, package.Filename);
            var file = new FileInfo(path);
            if (!file.Exists || file.Length is < 1 or > 32 * 1024 * 1024 || (file.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("A packaged filesystem prerequisite is missing or invalid.");
            using var stream = file.OpenRead();
            if (!CryptographicOperations.FixedTimeEquals(SHA256.HashData(stream), Convert.FromHexString(package.Sha256)) ||
                !WindowsCodeTrust.IsTrusted(path, package.Publisher))
                throw new InvalidDataException("Filesystem prerequisite signature or checksum changed.");
        }
    }

    internal static async Task<int> RunAsync()
    {
        if (!OperatingSystem.IsWindows()) return 50;
        if (Available) return 0;
        using var identity = WindowsIdentity.GetCurrent();
        if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) return 740;
        var directory = Path.Combine(AppContext.BaseDirectory, "filesystem-runtime");
        ValidatePackages(directory);
        var reboot = false;
        foreach (var package in Packages())
        {
            if (package.Kind == "driver" && KdeWindowsFilesystemBrowser.WinFspInstalled() ||
                package.Kind == "client" && KdeWindowsFilesystemBrowser.SshfsInstalled() is not null) continue;
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
            var start = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "msiexec.exe"))
            { UseShellExecute = false, CreateNoWindow = true };
            foreach (var argument in new[] { "/i", Path.Combine(directory, package.Filename), "/qn", "/norestart" }) start.ArgumentList.Add(argument);
            using var process = Process.Start(start) ?? throw new IOException("Could not start the filesystem prerequisite installer.");
            try { await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false); }
            catch (OperationCanceledException) { if (!process.HasExited) process.Kill(); throw; }
            if (process.ExitCode is not (0 or 3010)) return process.ExitCode;
            reboot |= process.ExitCode == 3010;
        }
        return reboot ? 3010 : Available ? 0 : 1603;
    }
}
