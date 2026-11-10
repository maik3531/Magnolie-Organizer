using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Original publisher archive only. No installer execution, elevation, endpoint
/// readiness or capture authority. The elevated caller creates its protected
/// fixed staging directory before extraction; the native helper verifies again.
/// </summary>
internal sealed class PhoneCameraAudioPackage
{
    internal const string DriverName = "VB-CABLE (VB-Audio Virtual Cable)";
    internal const string Url = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack46.zip";
    internal const string Sha256 = "bc44e8974191a5a2427d6c979e2dab08dbb09925f3f435dfa2f0ba3e45b6eb90";
    internal const string ManualUrl = "https://vb-audio.com/Cable/";
    internal const string LicenseUrl = "https://vb-audio.com/Services/licensing.htm";
    private const int MaxArchiveBytes = 4 * 1024 * 1024;
    private readonly byte[] original;
    private readonly Dictionary<string, byte[]> members;
    internal int FileCount => members.Count;
    private PhoneCameraAudioPackage(byte[] original, Dictionary<string, byte[]> members)
    { this.original = original; this.members = members; }

    internal static PhoneCameraAudioPackage Verify(ReadOnlySpan<byte> archive)
    {
        if (archive.Length is < 1 or > MaxArchiveBytes) throw new InvalidDataException("webcam_audio_archive_size_invalid");
        // Take ownership before hashing/decompression; caller mutation cannot
        // replace the checked archive between these two operations.
        var bytes = archive.ToArray();
        if (!CryptographicOperations.FixedTimeEquals(SHA256.HashData(bytes), Convert.FromHexString(Sha256)))
            throw new CryptographicException("webcam_audio_archive_checksum_changed");
        var files = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        using var input = new MemoryStream(bytes, writable: false);
        using var zip = new ZipArchive(input, ZipArchiveMode.Read);
        if (zip.Entries.Count is < 4 or > 64) throw new InvalidDataException("webcam_audio_archive_members_invalid");
        long total = 0;
        foreach (var entry in zip.Entries)
        {
            var name = entry.FullName;
            if (!Regex.IsMatch(name, "\\A[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\\z") || name is "." or ".." ||
                name.EndsWith('.') || !string.Equals(Path.GetFileName(name), name, StringComparison.Ordinal) ||
                files.ContainsKey(name) || entry.Length is < 1 or > 32 * 1024 * 1024 || (total += entry.Length) > 64 * 1024 * 1024)
                throw new InvalidDataException("webcam_audio_archive_path_invalid");
            var stem = name.Split('.')[0];
            if (Regex.IsMatch(stem, "\\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\\z", RegexOptions.IgnoreCase))
                throw new InvalidDataException("webcam_audio_archive_path_invalid");
            using var member = entry.Open();
            var data = new byte[checked((int)entry.Length)]; member.ReadExactly(data);
            if (member.ReadByte() != -1) throw new InvalidDataException("webcam_audio_archive_member_size_changed");
            files.Add(name, data);
        }
        foreach (var name in new[] { "vbMmeCable64_win10.inf", "vbaudio_cable64_win10.cat", "vbaudio_cable64_win10.sys", "vbaudio_cable64arm_win10.sys", "readme.txt" })
            if (!files.ContainsKey(name)) throw new InvalidDataException("webcam_audio_archive_incomplete");
        return new PhoneCameraAudioPackage(bytes, files);
    }

    internal static async Task<PhoneCameraAudioPackage> DownloadAsync(CancellationToken cancellation)
    {
        using var handler = new HttpClientHandler { AllowAutoRedirect = false };
        using var http = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
        return await DownloadAsync(http, cancellation);
    }
    // Native test seam only; there is intentionally no caller-supplied URL.
    internal static async Task<PhoneCameraAudioPackage> DownloadAsync(HttpClient http, CancellationToken cancellation)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromMinutes(2));
        var uri = new Uri(Url);
        for (int redirect = 0; redirect <= 3; ++redirect)
        {
            deadline.Token.ThrowIfCancellationRequested();
            if (uri.Scheme != "https" || uri.Host != "download.vb-audio.com" || !uri.IsDefaultPort || uri.UserInfo.Length != 0)
                throw new InvalidDataException("webcam_audio_download_origin_changed");
            using var response = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, deadline.Token);
            if (response.StatusCode is HttpStatusCode.MovedPermanently or HttpStatusCode.Redirect or HttpStatusCode.TemporaryRedirect or HttpStatusCode.PermanentRedirect)
            {
                var location = response.Headers.Location ?? throw new InvalidDataException("webcam_audio_download_redirect_invalid");
                uri = location.IsAbsoluteUri ? location : new Uri(uri, location);
                continue;
            }
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is > MaxArchiveBytes or < 1) throw new InvalidDataException("webcam_audio_archive_size_invalid");
            await using var input = await response.Content.ReadAsStreamAsync(deadline.Token);
            using var output = new MemoryStream(); var buffer = new byte[16384];
            while (true)
            {
                var read = await input.ReadAsync(buffer, deadline.Token); if (read == 0) break;
                if (output.Length + read > MaxArchiveBytes) throw new InvalidDataException("webcam_audio_archive_size_invalid");
                output.Write(buffer, 0, read);
            }
            var package = Verify(output.GetBuffer().AsSpan(0, checked((int)output.Length)));
            deadline.Token.ThrowIfCancellationRequested(); return package;
        }
        throw new InvalidDataException("webcam_audio_download_redirect_limit");
    }

    internal void WriteOriginalArchive(Stream output) => output.Write(original);
    internal IReadOnlyDictionary<string, string> ExtractIntoEmptyDirectory(string ownedDirectory)
    {
        var root = Path.GetFullPath(ownedDirectory);
        if (!Directory.Exists(root) || (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0 || Directory.EnumerateFileSystemEntries(root).Any())
            throw new InvalidDataException("webcam_audio_empty_owned_staging_required");
        var hashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (name, bytes) in members)
        {
            var path = Path.Combine(root, name);
            using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 16384, FileOptions.WriteThrough);
            output.Write(bytes); output.Flush(flushToDisk: true);
            hashes[name] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        }
        return hashes;
    }
}
