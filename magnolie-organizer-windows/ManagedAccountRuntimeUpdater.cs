using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed class AccountRuntimeUpdatingException() : IOException("The account helper component is being updated. Try again when the update has finished.");

/** Mozilla authenticates the MAR in a disposable staging copy, never in a live installation/profile. */
internal static class ManagedAccountRuntimeUpdater
{
    private static readonly object Gate = new();
    private static CancellationTokenSource lifetime = new();
    private static Task? worker;
    private static string workerKey = "";
    private static DateTimeOffset retryAt;
    private const long MaximumRuntimeBytes = 1500L * 1024 * 1024;

    internal static async Task<AccountRuntimeCandidate> EnsureAvailableAsync(string profile, string packagedRuntime,
        bool preferInstalled, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var cache = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(profile))!, "runtime-cache");
        AccountRuntimeCandidate? Existing() => ManagedAccountRuntimeResolver.SelectExisting(profile, packagedRuntime,
            CompletedDirectories(cache), preferInstalled ? null : []);
        if (Existing() is { } ready) { token.ThrowIfCancellationRequested(); return ready; }
        token.ThrowIfCancellationRequested();
        var key = Path.GetFullPath(packagedRuntime) + "\n" + cache + "\n" + ManagedAccountRuntimePolicy.ProfileRequirement(profile);
        Task pending;
        lock (Gate)
        {
            if (worker is null || worker.IsCompleted && (lifetime.IsCancellationRequested || workerKey != key || DateTimeOffset.UtcNow >= retryAt))
            {
                if (lifetime.IsCancellationRequested) { lifetime.Dispose(); lifetime = new(); }
                workerKey = key;
                retryAt = DateTimeOffset.UtcNow.AddMinutes(10);
                var stopping = lifetime.Token;
                worker = Task.Run(() => StageAsync(profile, packagedRuntime, cache, stopping));
            }
            pending = worker;
        }
        if (!pending.IsCompleted) throw new AccountRuntimeUpdatingException();
        try { await pending.WaitAsync(token).ConfigureAwait(false); }
        catch (Exception error) when (error is not OperationCanceledException)
        { throw new IOException("A compatible account helper could not be prepared.", error); }
        return Existing() ?? throw new IOException("The prepared account helper is not compatible with the profile and providers.");
    }

    internal static async Task StopAsync()
    {
        Task? pending;
        lock (Gate) { lifetime.Cancel(); pending = worker; }
        if (pending is null) return;
        try { await pending.WaitAsync(TimeSpan.FromSeconds(8)).ConfigureAwait(false); }
        catch (Exception) { } // A previously reported update failure must not break application shutdown.
    }

    private static IEnumerable<string> CompletedDirectories(string cache)
    {
        if (!Directory.Exists(cache)) return [];
        if (!Directory.EnumerateFileSystemEntries(cache).Any()) return [];
        CheckCache(cache);
        return Directory.EnumerateDirectories(cache, "tb-*", SearchOption.TopDirectoryOnly).Take(256)
            .Where(IsCompletedDirectory)
            .OrderByDescending(Directory.GetCreationTimeUtc).Take(32).ToArray();
    }

    private static bool IsCompletedDirectory(string path)
    {
        try
        {
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) return false;
            var marker = new FileInfo(Path.Combine(path, "magnolie-runtime.json"));
            if (!marker.Exists || marker.Length is < 1 or > 4096 || (marker.Attributes & FileAttributes.ReparsePoint) != 0) return false;
            var state = JsonNode.Parse(File.ReadAllText(marker.FullName));
            var version = state?["version"]?.GetValue<string>() ?? "";
            var build = state?["build_id"]?.GetValue<long>() ?? 0;
            var prefix = "tb-" + version + "-" + build + "-";
            var name = Path.GetFileName(path);
            return state?["schema"]?.GetValue<int>() == 1 && Regex.IsMatch(version, @"^\d+\.\d+(?:\.\d+){0,2}$") &&
                name.StartsWith(prefix, StringComparison.Ordinal) && Guid.TryParseExact(name[prefix.Length..], "N", out _);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidOperationException or System.Text.Json.JsonException)
        { return false; }
    }

    private static void CheckCache(string cache)
    {
        if ((File.GetAttributes(cache) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Account runtime caches cannot be filesystem links.");
        var marker = Path.Combine(cache, "magnolie-runtime-cache.json");
        if (!File.Exists(marker) || new FileInfo(marker).Length > 4096 ||
            JsonNode.Parse(File.ReadAllText(marker))?["schema"]?.GetValue<int>() != 1)
            throw new InvalidDataException("Refusing to use an unowned account runtime cache.");
    }

    private static void PrepareCache(string cache)
    {
        if (Directory.Exists(cache) && Directory.EnumerateFileSystemEntries(cache).Any()) { CheckCache(cache); return; }
        Directory.CreateDirectory(cache);
        if ((File.GetAttributes(cache) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Account runtime caches cannot be filesystem links.");
        new AtomicStore().Write(Path.Combine(cache, "magnolie-runtime-cache.json"), "{\"schema\":1}");
    }

    internal static async Task StageAsync(string profile, string packagedRuntime, string cache, CancellationToken stopping)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stopping);
        deadline.CancelAfter(TimeSpan.FromMinutes(3));
        var token = deadline.Token;
        var requirement = ManagedAccountRuntimePolicy.ProfileRequirement(profile);
        var providers = ManagedAccountRuntimeResolver.ProviderCompatibility(packagedRuntime);
        var updater = Path.Combine(packagedRuntime, "updater.exe");
        if (!MozillaCodeTrust.IsTrusted(updater)) throw new InvalidDataException("The packaged Mozilla updater could not be verified.");
        using var handler = new HttpClientHandler { AllowAutoRedirect = false, AutomaticDecompression = DecompressionMethods.All };
        using var http = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
        var metadata = JsonNode.Parse(await ReadTextAsync(http,
            new Uri("https://product-details.mozilla.org/1.0/thunderbird_versions.json"), 64 * 1024, token).ConfigureAwait(false));
        var version = metadata?["LATEST_THUNDERBIRD_VERSION"]?.GetValue<string>() ?? throw new InvalidDataException("Mozilla release metadata is incomplete.");
        var packagedBuild = MozillaRuntimeBuild.Parse(ManagedAccountRuntimeResolver.ReadIni(Path.Combine(packagedRuntime, "application.ini"), "App")["Version"]);
        version = ManagedAccountRuntimePolicy.UpdateVersion(version, requirement, packagedBuild, providers);
        var release = MozillaRuntimeBuild.Parse(version);
        var relative = $"update/win64/de/thunderbird-{version}.complete.mar";
        var releaseRoot = new Uri($"https://archive.mozilla.org/pub/thunderbird/releases/{version}/");
        var sums = await ReadTextAsync(http, new Uri(releaseRoot, "SHA512SUMS"), 8 * 1024 * 1024, token).ConfigureAwait(false);
        var hashes = sums.Split('\n').Select(line => line.Trim().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .Where(parts => parts.Length == 2 && parts[1].TrimStart('*') == relative).Select(parts => parts[0]).ToArray();
        if (hashes.Length != 1 || !Regex.IsMatch(hashes[0], "^[a-fA-F0-9]{128}$", RegexOptions.CultureInvariant))
            throw new InvalidDataException("The Mozilla complete-update checksum is missing or ambiguous.");
        PrepareCache(cache);
        var sourceSize = CheckRuntimeSize(packagedRuntime);
        if (new DriveInfo(Path.GetPathRoot(Path.GetFullPath(cache))!).AvailableFreeSpace < sourceSize * 2 + 350L * 1024 * 1024)
            throw new IOException("There is not enough free space to stage the account helper component.");
        var stage = Path.Combine(cache, ".staging-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        try
        {
            var source = Path.Combine(stage, "base");
            CopyRuntime(packagedRuntime, source, token);
            var patch = Path.Combine(stage, "patch"); Directory.CreateDirectory(patch);
            await DownloadMarAsync(http, new Uri(releaseRoot, relative), Path.Combine(patch, "update.mar"), hashes[0], token).ConfigureAwait(false);
            await File.WriteAllTextAsync(Path.Combine(patch, "update.status"), "pending", new UTF8Encoding(false), token).ConfigureAwait(false);
            var updated = Path.Combine(source, "updated");
            await ApplyMozillaStagingAsync(source, patch, token).ConfigureAwait(false);
            var candidate = ManagedAccountRuntimeResolver.ReadCandidate(Path.Combine(updated, "thunderbird.exe"), AccountRuntimeSource.Managed);
            if (candidate is null || candidate.Build.Version != release.Version ||
                ManagedAccountRuntimePolicy.Select([candidate], requirement, providers) is null)
                throw new InvalidDataException("The updated Mozilla application failed compatibility/signature readback.");
            CheckRuntimeSize(updated);
            var description = JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(packagedRuntime, "runtime.json"), token).ConfigureAwait(false))!.AsObject();
            description["thunderbird"] = new JsonObject { ["version"] = version, ["url"] = new Uri(releaseRoot, relative).AbsoluteUri, ["sha512"] = hashes[0].ToLowerInvariant() };
            new AtomicStore().Write(Path.Combine(updated, "runtime.json"), description.ToJsonString());
            new AtomicStore().Write(Path.Combine(updated, "magnolie-runtime.json"), new JsonObject
            { ["schema"] = 1, ["version"] = version, ["build_id"] = candidate.Build.BuildId, ["mar_sha512"] = hashes[0].ToLowerInvariant() }.ToJsonString());
            token.ThrowIfCancellationRequested();
            CheckCache(cache);
            var completed = Path.Combine(cache, "tb-" + version + "-" + candidate.Build.BuildId + "-" + Guid.NewGuid().ToString("N"));
            Directory.Move(updated, completed);
            foreach (var old in CompletedDirectories(cache).Where(path => path != completed).Skip(2))
            {
                try { Directory.Delete(old, true); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            }
        }
        finally
        {
            try { Directory.Delete(stage, true); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        }
    }

    internal static async Task ApplyMozillaStagingAsync(string source, string patch, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var updater = Path.Combine(source, "updater.exe");
        if (!MozillaCodeTrust.IsTrusted(updater)) throw new InvalidDataException("The copied Mozilla updater could not be verified.");
        var start = new ProcessStartInfo(updater)
        { WorkingDirectory = source, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in new[] { "1", patch, source, Path.Combine(source, "updated"), "first", "-1" }) start.ArgumentList.Add(argument);
        start.Environment["MOZ_APP_SILENT_START"] = "1";
        using (var process = Process.Start(start) ?? throw new IOException("Could not start the owned Mozilla staging updater."))
        {
            var output = DrainAsync(process.StandardOutput, token);
            var errors = DrainAsync(process.StandardError, token);
            try
            {
                await process.WaitForExitAsync(token).ConfigureAwait(false);
                await Task.WhenAll(output, errors).ConfigureAwait(false);
                if (process.ExitCode != 0) throw new IOException("The Mozilla staging updater failed.");
            }
            finally
            {
                if (!process.HasExited) { process.Kill(entireProcessTree: true); process.WaitForExit(5000); }
            }
        }
        var status = (await File.ReadAllTextAsync(Path.Combine(patch, "update.status"), token).ConfigureAwait(false)).Trim();
        if (status != "applied") throw new InvalidDataException("Mozilla did not authenticate and apply the staged update.");
    }

    private static async Task<string> ReadTextAsync(HttpClient http, Uri uri, int limit, CancellationToken token)
    {
        using var response = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        using var stream = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        using var bytes = new MemoryStream();
        var buffer = new byte[8192];
        int read;
        while ((read = await stream.ReadAsync(buffer, token).ConfigureAwait(false)) > 0)
        { if (bytes.Length + read > limit) throw new InvalidDataException("Mozilla metadata exceeds its limit."); bytes.Write(buffer, 0, read); }
        return new UTF8Encoding(false, true).GetString(bytes.ToArray());
    }

    private static async Task DownloadMarAsync(HttpClient http, Uri uri, string path, string expected, CancellationToken token)
    {
        using var response = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        using var input = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 128 * 1024, useAsync: true);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA512);
        var buffer = new byte[128 * 1024]; long total = 0; int read;
        while ((read = await input.ReadAsync(buffer, token).ConfigureAwait(false)) > 0)
        {
            total += read; if (total > 300L * 1024 * 1024) throw new InvalidDataException("Mozilla update exceeds its download limit.");
            hash.AppendData(buffer, 0, read);
            await output.WriteAsync(buffer.AsMemory(0, read), token).ConfigureAwait(false);
        }
        if (!CryptographicOperations.FixedTimeEquals(hash.GetHashAndReset(), Convert.FromHexString(expected)))
            throw new InvalidDataException("Mozilla update checksum does not match.");
        await output.FlushAsync(token).ConfigureAwait(false); output.Flush(true);
    }

    internal static void CopyRuntime(string source, string target, CancellationToken token)
    {
        CheckRuntimeSize(source);
        var pending = new Stack<(string Source, string Target)>(); pending.Push((source, target));
        while (pending.TryPop(out var directory))
        {
            Directory.CreateDirectory(directory.Target);
            foreach (var path in Directory.EnumerateFileSystemEntries(directory.Source))
            {
                token.ThrowIfCancellationRequested();
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Runtime components cannot be links.");
                var destination = Path.Combine(directory.Target, Path.GetFileName(path));
                if (Directory.Exists(path)) pending.Push((path, destination)); else File.Copy(path, destination, false);
            }
        }
    }

    private static long CheckRuntimeSize(string path)
    {
        long size = 0; var count = 0;
        var pending = new Stack<string>(); pending.Push(path);
        while (pending.TryPop(out var directory))
        {
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Runtime directories cannot be links.");
            foreach (var entry in Directory.EnumerateFileSystemEntries(directory))
            {
                if (++count > 20_000 || (File.GetAttributes(entry) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Invalid runtime layout.");
                if (Directory.Exists(entry)) pending.Push(entry); else size += new FileInfo(entry).Length;
                if (size > MaximumRuntimeBytes) throw new InvalidDataException("Runtime exceeds its extracted size limit.");
            }
        }
        return size;
    }

    private static async Task DrainAsync(StreamReader reader, CancellationToken token)
    {
        var buffer = new char[4096];
        while (await reader.ReadAsync(buffer, token).ConfigureAwait(false) > 0) { }
    }
}
