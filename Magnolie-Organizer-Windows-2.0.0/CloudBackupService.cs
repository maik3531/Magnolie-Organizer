using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record CloudBackupSettings(bool Enabled, string Interval, int Retention,
    string LastSuccess, string Folder);

internal sealed class CloudBackupSecretStore
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes(
        "io.gitlab.maik3531.MagnolieOrganizer.AutomaticBackup/v1");
    private readonly string path;
    private readonly AtomicStore files;

    internal CloudBackupSecretStore(string path, AtomicStore? files = null)
    {
        this.path = path;
        this.files = files ?? new AtomicStore();
    }

    internal void Store(string password)
    {
        if (password.Length is < 4 or > 4096) throw new InvalidDataException("invalid_password");
        var plain = Encoding.UTF8.GetBytes(password);
        try
        {
            var protectedData = ProtectedData.Protect(plain, Entropy,
                DataProtectionScope.CurrentUser);
            try { files.Write(path, Convert.ToBase64String(protectedData), 32 * 1024); }
            finally { CryptographicOperations.ZeroMemory(protectedData); }
        }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    internal string? Lookup()
    {
        try
        {
            var stored = files.Read(path, 32 * 1024);
            if (string.IsNullOrWhiteSpace(stored)) return null;
            var protectedData = Convert.FromBase64String(stored);
            try
            {
                var plain = ProtectedData.Unprotect(protectedData, Entropy,
                    DataProtectionScope.CurrentUser);
                try
                {
                    var password = Encoding.UTF8.GetString(plain);
                    return password.Length is >= 4 and <= 4096 ? password : null;
                }
                finally { CryptographicOperations.ZeroMemory(plain); }
            }
            finally { CryptographicOperations.ZeroMemory(protectedData); }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                      CryptographicException or FormatException or PlatformNotSupportedException)
        {
            return null;
        }
    }
}

internal sealed partial class CloudBackupService
{
    internal const int ListingLimit = 1000;
    private readonly CloudBackupSecretStore secrets;
    private readonly AtomicStore files;

    internal CloudBackupService(string secretPath, AtomicStore? files = null)
    {
        this.files = files ?? new AtomicStore();
        secrets = new CloudBackupSecretStore(secretPath, this.files);
    }

    internal bool PasswordAvailable => secrets.Lookup() is not null;
    internal void StorePassword(string password) => secrets.Store(password);

    internal static bool IsDue(bool enabled, string interval, string lastSuccess,
        DateTimeOffset now)
    {
        if (!enabled || interval is not ("daily" or "weekly")) return false;
        if (!DateTimeOffset.TryParse(lastSuccess, out var last)) return true;
        return now >= last.ToUniversalTime() + (interval == "daily" ? TimeSpan.FromDays(1) : TimeSpan.FromDays(7));
    }

    internal static int BoundRetention(int value) => Math.Clamp(value, 2, 30);

    internal static CloudBackupSettings Settings(JsonObject data)
    {
        var general = data["einstellungen"]?["allgemein"] as JsonObject;
        var cloud = general?["cloudSicherung"] as JsonObject;
        var interval = cloud?["intervall"]?.GetValue<string>() ?? "daily";
        if (interval is not ("daily" or "weekly")) interval = "daily";
        return new CloudBackupSettings(cloud?["aktiv"]?.GetValue<bool>() ?? false,
            interval, BoundRetention(cloud?["aufbewahrung"]?.GetValue<int>() ?? 7),
            cloud?["letzterErfolg"]?.GetValue<string>() ?? "",
            general?["sicherungsordner"]?.GetValue<string>()?.Trim() ?? "");
    }

    internal string CreateVerified(JsonObject data, CloudBackupSettings settings,
        string appVersion, DateTimeOffset? now = null)
    {
        if (string.IsNullOrWhiteSpace(settings.Folder)) throw new InvalidOperationException("folder_missing");
        var password = secrets.Lookup() ?? throw new InvalidOperationException("secret_unavailable");
        var instant = (now ?? DateTimeOffset.UtcNow).ToUniversalTime();
        Directory.CreateDirectory(settings.Folder);
        var target = Path.Combine(settings.Folder,
            $"magnolie-auto-{instant:yyyyMMdd-HHmmss-ffffff}-{Guid.NewGuid():N}.magnolie");
        try
        {
            files.Write(target, GesamtarchivService.Create(data, "windows", appVersion, password),
                AtomicStore.MaxArchiveBytes);
            var stored = files.Read(target, AtomicStore.MaxArchiveBytes)
                ?? throw new IOException("automatic_backup_verification_failed");
            _ = GesamtarchivService.Read(stored, password);
        }
        catch
        {
            try
            {
                if (File.Exists(target) && (File.GetAttributes(target) & FileAttributes.ReparsePoint) == 0)
                    File.Delete(target);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            throw;
        }
        ApplyRetention(settings.Folder, settings.Retention, target);
        return target;
    }

    internal static IReadOnlyList<string> ApplyRetention(string directory, int keep,
        string verifiedPath)
    {
        var listed = Directory.EnumerateFileSystemEntries(directory).Take(ListingLimit + 1).ToArray();
        if (listed.Length > ListingLimit) throw new IOException("backup_listing_limit");
        var owned = listed.Where(path => OwnedName().IsMatch(Path.GetFileName(path)))
            .Where(path => (File.GetAttributes(path) & FileAttributes.ReparsePoint) == 0)
            .Where(File.Exists)
            .OrderBy(path => File.GetLastWriteTimeUtc(path)).ThenBy(path => path, StringComparer.Ordinal)
            .ToList();
        var verified = Path.GetFullPath(verifiedPath);
        if (!owned.Any(path => string.Equals(Path.GetFullPath(path), verified,
                StringComparison.OrdinalIgnoreCase)))
            throw new IOException("verified_backup_not_owned");
        var remove = Math.Max(0, owned.Count - BoundRetention(keep));
        var deleted = new List<string>();
        foreach (var path in owned)
        {
            if (remove == 0) break;
            if (string.Equals(Path.GetFullPath(path), verified, StringComparison.OrdinalIgnoreCase)) continue;
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0 || !File.Exists(path)) continue;
            File.Delete(path); deleted.Add(path); remove--;
        }
        return deleted;
    }

    [GeneratedRegex("^magnolie-auto-[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]{32}\\.magnolie$",
        RegexOptions.CultureInvariant)]
    private static partial Regex OwnedName();
}
