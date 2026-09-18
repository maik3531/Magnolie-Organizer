using System.Net;
using System.Globalization;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;

namespace MagnolieOrganizer.Windows;

internal sealed partial class WindowsUpdateService : IDisposable
{
    internal const string ManifestUrl = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/update.xml";
    internal const long MaximumPackageBytes = 512L * 1024 * 1024;
    private const int MaximumManifestBytes = 256 * 1024;
    private const string PublicKey = "8eJWsygSF9wsF22cuf+sChUUV5RtXEZt38Ngcugn/1Y=";
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private readonly HttpClient http;
    private readonly string updateDirectory;
    private readonly bool requireWindowsOwnership;
    private readonly Func<string, bool> startInstaller;
    private ValidatedRelease? lastRelease;
    private ValidatedRelease? preparedRelease;
    private string? preparedPath;

    internal WindowsUpdateService(string dataRoot, HttpMessageHandler? handler = null,
        bool requireWindowsOwnership = true, Func<string, bool>? startInstaller = null,
        ValidatedRelease? initialReleaseForTests = null)
    {
        updateDirectory = Path.Combine(Path.GetFullPath(dataRoot), "updates");
        this.requireWindowsOwnership = requireWindowsOwnership;
        this.startInstaller = startInstaller ?? StartLocalInstaller;
        lastRelease = initialReleaseForTests;
        http = DeadlineHttp.Create(TimeSpan.FromSeconds(30), handler, MaximumPackageBytes);
        http.DefaultRequestHeaders.UserAgent.ParseAdd("Magnolie-Organizer-Windows/2");
    }

    internal ValidatedManualRelease? LastManualRelease { get; private set; }

    internal bool IsValidatedReleaseUrl(string target) => lastRelease is not null &&
        string.Equals(lastRelease.Url, target, StringComparison.Ordinal) &&
        IsExactPackageUrl(target,
            $"Magnolie-Organizer-Windows-{lastRelease.Version}-Setup-x64.exe");

    internal async Task<UpdateCheckResult> CheckAsync(string installedVersion)
    {
        ClearOrganizerState(deletePrepared: true);
        LastManualRelease = null;
        try
        {
            var bytes = await ReadLimitedAsync(ManifestUrl, ManifestUrl, MaximumManifestBytes,
                "application/xml, text/xml, text/plain").ConfigureAwait(false);
            var manifest = ValidateManifest(StrictUtf8.GetString(bytes));
            LastManualRelease = manifest.Manual;
            var current = CompareVersions(manifest.Windows.Version, installedVersion) <= 0;
            if (!current) lastRelease = manifest.Windows;
            return new UpdateCheckResult(true, current, manifest.Windows, manifest.Manual, "");
        }
        catch (Exception)
        {
            ClearOrganizerState(deletePrepared: true);
            LastManualRelease = null;
            return new UpdateCheckResult(false, false, null, null, T("The update check failed."));
        }
    }

    internal async Task<UpdateDownloadResult> DownloadAsync()
    {
        DeletePreparedFile();
        preparedRelease = null;
        var release = lastRelease;
        if (release is null)
            return new UpdateDownloadResult(false, T("The package could not be opened."), "", "windows", false);
        try
        {
            EnsurePrivateDirectory();
            var path = Path.Combine(updateDirectory, $".Magnolie-Organizer-Windows-{release.Version}-{Guid.NewGuid():N}.exe");
            await DownloadToNewFileAsync(release, path).ConfigureAwait(false);
            if (release != lastRelease)
            {
                File.Delete(path);
                throw new InvalidDataException("The validated update changed during the download.");
            }
            preparedRelease = release;
            preparedPath = path;
            return new UpdateDownloadResult(true, "", release.Version, "windows", true);
        }
        catch (Exception)
        {
            DeletePreparedFile();
            preparedRelease = null;
            return new UpdateDownloadResult(false, T("The package could not be opened."), release.Version, "windows", false);
        }
    }

    internal UpdateInstallResult PrepareInstallation()
    {
        var release = preparedRelease;
        var path = preparedPath;
        if (release is null || release != lastRelease || string.IsNullOrEmpty(path))
            return new UpdateInstallResult(false, T("The package could not be opened."), release?.Version ?? "", "windows", false);
        try
        {
            EnsureSafePreparedFile(path);
            StartVerifiedInstaller(release, path);
            preparedPath = null;
            preparedRelease = null;
            return new UpdateInstallResult(true, "", release.Version, "windows", true);
        }
        catch (Exception)
        {
            DeletePreparedFile();
            preparedRelease = null;
            return new UpdateInstallResult(false, T("The package could not be opened."), release.Version, "windows", false);
        }
    }

    internal async Task<bool> DownloadAndOpenManualAsync(ValidatedManualRelease requested)
    {
        if (requested != LastManualRelease) return false;
        EnsurePrivateDirectory();
        var release = new ValidatedRelease(requested.Version, requested.Url, requested.Sha256, "windows");
        var path = Path.Combine(updateDirectory, $".Magnolie-Handbuch-Windows-{requested.Version}-{Guid.NewGuid():N}.exe");
        try
        {
            await DownloadToNewFileAsync(release, path).ConfigureAwait(false);
            EnsureSafePreparedFile(path);
            StartVerifiedInstaller(release, path);
            path = "";
            return true;
        }
        finally
        {
            if (path.Length > 0) try { File.Delete(path); } catch (Exception) { }
        }
    }

    internal static ValidatedManifest ValidateManifest(string xml)
    {
        if (Regex.IsMatch(xml, @"<!\s*(?:DOCTYPE|ENTITY)\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant))
            throw new InvalidDataException("The update information is unreadable.");
        XDocument document;
        try
        {
            using var reader = XmlReader.Create(new StringReader(xml), new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                MaxCharactersInDocument = MaximumManifestBytes,
                IgnoreProcessingInstructions = true
            });
            document = XDocument.Load(reader, LoadOptions.None);
        }
        catch (XmlException error) { throw new InvalidDataException("The update information is unreadable.", error); }
        var root = document.Root;
        if (root is null || root.Name != "update" || root.HasAttributes)
            throw new InvalidDataException("The update information has an invalid root element.");

        var version = RequiredText(root, "version");
        var deb = RequiredText(root, "deb");
        var debSha = RequiredText(root, "sha256").ToLowerInvariant();
        var signatureText = RequiredText(root, "signature");
        var appImage = OptionalSingle(root, "appimage");
        var manual = RequiredSingle(root, "manual");
        var windows = RequiredSingle(root, "windows");
        EnsureUniqueKnownChildren(root, "name", "version", "deb", "source", "manual", "appimage", "windows", "sha256", "signature");
        EnsureUniqueKnownChildren(manual, "version", "linux", "windows");
        var manualLinux = RequiredSingle(manual, "linux");
        var manualWindows = RequiredSingle(manual, "windows");
        EnsureUniqueKnownChildren(manualLinux, "deb", "sha256");
        EnsureUniqueKnownChildren(manualWindows, "url", "sha256");
        EnsureUniqueKnownChildren(windows, "version", "url", "sha256");
        if (appImage is not null) EnsureUniqueKnownChildren(appImage, "architecture", "url", "sha256");

        var appImageUrl = appImage is null ? "" : RequiredText(appImage, "url");
        var appImageSha = appImage is null ? "" : RequiredText(appImage, "sha256").ToLowerInvariant();
        var manualVersion = RequiredText(manual, "version");
        var manualLinuxUrl = RequiredText(manualLinux, "deb");
        var manualLinuxSha = RequiredText(manualLinux, "sha256").ToLowerInvariant();
        var manualWindowsUrl = RequiredText(manualWindows, "url");
        var manualWindowsSha = RequiredText(manualWindows, "sha256").ToLowerInvariant();
        var windowsVersion = RequiredText(windows, "version");
        var windowsUrl = RequiredText(windows, "url");
        var windowsSha = RequiredText(windows, "sha256").ToLowerInvariant();

        if (!VersionPattern().IsMatch(version) || !VersionPattern().IsMatch(windowsVersion) ||
            !VersionPattern().IsMatch(manualVersion) || !ShaPattern().IsMatch(debSha) ||
            !ShaPattern().IsMatch(windowsSha) || !ShaPattern().IsMatch(manualLinuxSha) ||
            !ShaPattern().IsMatch(manualWindowsSha))
            throw new InvalidDataException("The update information contains invalid release fields.");
        if (windowsVersion != version || manualVersion != version || windowsSha != manualWindowsSha)
            throw new InvalidDataException("The Windows release fields do not describe one exact artifact.");
        if (!IsExactPackageUrl(deb, $"magnolie-organizer_{version}_all.deb") ||
            !IsExactPackageUrl(windowsUrl, $"Magnolie-Organizer-Windows-{windowsVersion}-Setup-x64.exe") ||
            !IsExactPackageUrl(manualLinuxUrl, $"magnolie-handbuch_{manualVersion}_all.deb") ||
            !IsExactPackageUrl(manualWindowsUrl, $"Magnolie-Organizer-Windows-{manualVersion}-Setup-x64.exe"))
            throw new InvalidDataException("The update information refers to an invalid package URL.");
        if (appImage is not null && (RequiredText(appImage, "architecture") != "x86_64" ||
            !ShaPattern().IsMatch(appImageSha) ||
            !IsExactPackageUrl(appImageUrl, $"Magnolie-Organizer-{version}-x86_64.AppImage")))
            throw new InvalidDataException("The update information contains an invalid AppImage entry.");

        var message = CanonicalMessage(version, deb, debSha, appImageUrl, appImageSha,
            manualVersion, manualLinuxUrl, manualLinuxSha, manualWindowsUrl, manualWindowsSha,
            windowsVersion, windowsUrl, windowsSha);
        byte[] signature;
        try { signature = Convert.FromBase64String(signatureText); }
        catch (FormatException error) { throw new InvalidDataException("The update information has an invalid signature.", error); }
        if (signature.Length != 64 || !VerifySignature(message, signature))
            throw new InvalidDataException("The update information has an invalid signature.");

        return new ValidatedManifest(
            new ValidatedRelease(windowsVersion, windowsUrl, windowsSha, "windows"),
            new ValidatedManualRelease(manualVersion, manualWindowsUrl, manualWindowsSha, "windows"));
    }

    internal static byte[] CanonicalMessage(string version, string deb, string debSha,
        string appImage, string appImageSha, string manualVersion, string manualLinux,
        string manualLinuxSha, string manualWindows, string manualWindowsSha,
        string windowsVersion, string windows, string windowsSha) => Encoding.UTF8.GetBytes(
            $"Magnolie Organizer Update\nversion={version.Trim()}\ndeb={deb.Trim()}\nsha256={debSha.Trim().ToLowerInvariant()}\n" +
            $"appimage={appImage.Trim()}\nappimageSha256={appImageSha.Trim().ToLowerInvariant()}\nmanualVersion={manualVersion.Trim()}\n" +
            $"manualLinux={manualLinux.Trim()}\nmanualLinuxSha256={manualLinuxSha.Trim().ToLowerInvariant()}\nmanualWindows={manualWindows.Trim()}\n" +
            $"manualWindowsSha256={manualWindowsSha.Trim().ToLowerInvariant()}\nwindowsVersion={windowsVersion.Trim()}\nwindows={windows.Trim()}\n" +
            $"windowsSha256={windowsSha.Trim().ToLowerInvariant()}\n");

    private async Task DownloadToNewFileAsync(ValidatedRelease release, string path)
    {
        try
        {
            using var response = await SendCheckedAsync(release.Url, release.Url, "application/octet-stream").ConfigureAwait(false);
            if (response.Content.Headers.ContentLength is < 0 or > MaximumPackageBytes)
                throw new InvalidDataException("The update package has an invalid size.");
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            await using var input = await response.Content.ReadAsStreamAsync().ConfigureAwait(false);
            await using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                1024 * 1024, FileOptions.Asynchronous | FileOptions.WriteThrough);
            var buffer = new byte[1024 * 1024];
            long total = 0;
            while (true)
            {
                var count = await input.ReadAsync(buffer).ConfigureAwait(false);
                if (count == 0) break;
                total += count;
                if (total > MaximumPackageBytes) throw new InvalidDataException("The update package is unexpectedly large.");
                hash.AppendData(buffer, 0, count);
                await output.WriteAsync(buffer.AsMemory(0, count)).ConfigureAwait(false);
            }
            await output.FlushAsync().ConfigureAwait(false);
            if (!CryptographicOperations.FixedTimeEquals(hash.GetHashAndReset(), Convert.FromHexString(release.Sha256)))
                throw new InvalidDataException("The update package checksum does not match.");
        }
        catch
        {
            try { File.Delete(path); } catch (Exception) { }
            throw;
        }
    }

    private async Task<byte[]> ReadLimitedAsync(string url, string exactUrl, int maximum, string accept)
    {
        using var response = await SendCheckedAsync(url, exactUrl, accept).ConfigureAwait(false);
        if (response.Content.Headers.ContentLength is < 0 || response.Content.Headers.ContentLength > maximum)
            throw new InvalidDataException("The update information is unexpectedly large.");
        await using var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false);
        using var memory = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var count = await stream.ReadAsync(buffer).ConfigureAwait(false);
            if (count == 0) break;
            if (memory.Length + count > maximum) throw new InvalidDataException("The update information is unexpectedly large.");
            memory.Write(buffer, 0, count);
        }
        return memory.ToArray();
    }

    private async Task<HttpResponseMessage> SendCheckedAsync(string url, string exactUrl, string accept)
    {
        var current = url;
        for (var redirects = 0; redirects <= 8; redirects++)
        {
            if (!IsExactSignedUrl(current, exactUrl)) throw new InvalidDataException("The update redirect target is not allowed.");
            using var request = new HttpRequestMessage(HttpMethod.Get, current);
            request.Headers.Accept.ParseAdd(accept);
            var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead).ConfigureAwait(false);
            if ((int)response.StatusCode is >= 300 and <= 399)
            {
                var location = response.Headers.Location;
                if (location is null) { response.Dispose(); throw new HttpRequestException("The update redirect has no target."); }
                var next = location.IsAbsoluteUri ? location : new Uri(new Uri(current), location);
                response.Dispose();
                current = next.AbsoluteUri;
                continue;
            }
            try { response.EnsureSuccessStatusCode(); return response; }
            catch { response.Dispose(); throw; }
        }
        throw new HttpRequestException("The update service returned too many redirects.");
    }

    private void EnsurePrivateDirectory()
    {
        Directory.CreateDirectory(updateDirectory);
        if ((File.GetAttributes(updateDirectory) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("The private update directory is not safe.");
        if (requireWindowsOwnership)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows ownership checks are required.");
            ApplyPrivateWindowsAcl(updateDirectory, directory: true);
        }
    }

    private void EnsureSafePreparedFile(string path)
    {
        var full = Path.GetFullPath(path);
        if (!string.Equals(Path.GetDirectoryName(full), Path.GetFullPath(updateDirectory),
                OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal) || !File.Exists(full) ||
            (File.GetAttributes(full) & (FileAttributes.Directory | FileAttributes.ReparsePoint)) != 0)
            throw new IOException("The prepared update file is not safe.");
        if (requireWindowsOwnership)
        {
            if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows ownership checks are required.");
            ApplyPrivateWindowsAcl(full, directory: false);
        }
    }

    private void StartVerifiedInstaller(ValidatedRelease release, string path)
    {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
            1024 * 1024, FileOptions.SequentialScan);
        if (input.Length < 0 || input.Length > MaximumPackageBytes)
            throw new InvalidDataException("The prepared update package has an invalid size.");
        var actual = SHA256.HashData(input);
        if (!CryptographicOperations.FixedTimeEquals(actual, Convert.FromHexString(release.Sha256)))
            throw new InvalidDataException("The prepared update checksum does not match.");
        if (!startInstaller(path)) throw new IOException("The verified installer could not be started.");
    }

    [SupportedOSPlatform("windows")]
    private static void ApplyPrivateWindowsAcl(string path, bool directory)
    {
        using var identity = WindowsIdentity.GetCurrent();
        var sid = identity.User?.Value ?? throw new IOException("The Windows user identity is unavailable.");
        var inheritance = directory ? "OICI" : "";
        var sddl = $"O:{sid}D:P(A;{inheritance};FA;;;SY)(A;{inheritance};FA;;;{sid})";
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1, out var descriptor, out _))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            if (!GetSecurityDescriptorOwner(descriptor, out var owner, out _) ||
                !GetSecurityDescriptorDacl(descriptor, out _, out var dacl, out _))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            const uint ownerAndProtectedDacl = 0x00000001 | 0x80000004;
            var result = SetNamedSecurityInfo(path, 1, ownerAndProtectedDacl, owner,
                IntPtr.Zero, dacl, IntPtr.Zero);
            if (result != 0) throw new Win32Exception((int)result);
        }
        finally { _ = LocalFree(descriptor); }
    }

    private static bool VerifySignature(byte[] message, byte[] signature)
    {
        var signer = new Ed25519Signer();
        signer.Init(false, new Ed25519PublicKeyParameters(Convert.FromBase64String(PublicKey), 0));
        signer.BlockUpdate(message, 0, message.Length);
        return signer.VerifySignature(signature);
    }

    private static XElement RequiredSingle(XElement parent, XName name)
    {
        var values = parent.Elements(name).ToArray();
        if (values.Length != 1 || values[0].HasAttributes) throw new InvalidDataException($"The update field {name} is not unique.");
        return values[0];
    }

    private static XElement? OptionalSingle(XElement parent, XName name)
    {
        var values = parent.Elements(name).ToArray();
        if (values.Length > 1 || values.Any(value => value.HasAttributes)) throw new InvalidDataException($"The update field {name} is not unique.");
        return values.SingleOrDefault();
    }

    private static string RequiredText(XElement parent, XName name)
    {
        var element = RequiredSingle(parent, name);
        if (element.HasElements) throw new InvalidDataException($"The update field {name} is invalid.");
        var value = element.Value.Trim();
        if (value.Length == 0) throw new InvalidDataException($"The update field {name} is empty.");
        return value;
    }

    private static void EnsureUniqueKnownChildren(XElement parent, params string[] names)
    {
        var allowed = names.ToHashSet(StringComparer.Ordinal);
        if (parent.Elements().Any(element => element.Name.NamespaceName.Length > 0 || !allowed.Contains(element.Name.LocalName)) ||
            parent.Elements().GroupBy(element => element.Name).Any(group => group.Count() > 1))
            throw new InvalidDataException("The update information contains ambiguous XML fields.");
    }

    internal static bool IsExactPackageUrl(string target, string fileName) =>
        Uri.TryCreate(target, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps &&
        uri.Host.Equals("gitlab.com", StringComparison.OrdinalIgnoreCase) && uri.Port == 443 &&
        string.IsNullOrEmpty(uri.UserInfo) && string.IsNullOrEmpty(uri.Query) && string.IsNullOrEmpty(uri.Fragment) &&
        uri.AbsolutePath == "/maik3531/mint-forgs/-/raw/main/Magnolie-Organitzer/" + fileName;

    private static bool IsExactSignedUrl(string target, string exact) =>
        Uri.TryCreate(target, UriKind.Absolute, out var uri) && uri.Scheme == Uri.UriSchemeHttps &&
        uri.Host.Equals("gitlab.com", StringComparison.OrdinalIgnoreCase) && uri.Port == 443 &&
        string.IsNullOrEmpty(uri.UserInfo) && string.IsNullOrEmpty(uri.Query) && string.IsNullOrEmpty(uri.Fragment) &&
        string.Equals(uri.AbsoluteUri, exact, StringComparison.Ordinal);

    private static int CompareVersions(string left, string right)
    {
        var a = Regex.Matches(left.TrimStart('v', 'V'), @"\d+").Select(match => int.Parse(match.Value, CultureInfo.InvariantCulture)).ToArray();
        var b = Regex.Matches(right.TrimStart('v', 'V'), @"\d+").Select(match => int.Parse(match.Value, CultureInfo.InvariantCulture)).ToArray();
        for (var index = 0; index < Math.Max(a.Length, b.Length); index++)
        {
            var result = (index < a.Length ? a[index] : 0).CompareTo(index < b.Length ? b[index] : 0);
            if (result != 0) return result;
        }
        return 0;
    }

    private static bool StartLocalInstaller(string path)
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = path,
                UseShellExecute = true
            });
            return true;
        }
        catch (Exception) { return false; }
    }

    private static string T(string message) => NativeLocalization.Gettext(message);

    private void ClearOrganizerState(bool deletePrepared)
    {
        lastRelease = null;
        preparedRelease = null;
        if (deletePrepared) DeletePreparedFile();
    }

    private void DeletePreparedFile()
    {
        var path = preparedPath;
        preparedPath = null;
        if (!string.IsNullOrEmpty(path)) try { File.Delete(path); } catch (Exception) { }
    }

    public void Dispose()
    {
        DeletePreparedFile();
        http.Dispose();
    }

    [GeneratedRegex(@"^[vV]?\d+(?:\.\d+)*(?:-\d+)?$", RegexOptions.CultureInvariant)]
    private static partial Regex VersionPattern();
    [GeneratedRegex(@"^[0-9a-f]{64}$", RegexOptions.CultureInvariant)]
    private static partial Regex ShaPattern();

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl,
        uint revision, out IntPtr descriptor, out uint descriptorSize);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSecurityDescriptorOwner(IntPtr descriptor, out IntPtr owner,
        [MarshalAs(UnmanagedType.Bool)] out bool ownerDefaulted);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetSecurityDescriptorDacl(IntPtr descriptor,
        [MarshalAs(UnmanagedType.Bool)] out bool daclPresent, out IntPtr dacl,
        [MarshalAs(UnmanagedType.Bool)] out bool daclDefaulted);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode)]
    private static extern uint SetNamedSecurityInfo(string objectName, uint objectType,
        uint securityInformation, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);
}

internal sealed record ValidatedRelease(string Version, string Url, string Sha256, string Artifact);
internal sealed record ValidatedManualRelease(string Version, string Url, string Sha256, string Platform);
internal sealed record ValidatedManifest(ValidatedRelease Windows, ValidatedManualRelease Manual);
internal sealed record UpdateCheckResult(bool Ok, bool Current, ValidatedRelease? Release,
    ValidatedManualRelease? Manual, string Error);
internal sealed record UpdateDownloadResult(bool Ok, string Error, string Version, string Artifact, bool Ready);
internal sealed record UpdateInstallResult(bool Ok, string Error, string Version, string Artifact, bool ReadyToExit);
