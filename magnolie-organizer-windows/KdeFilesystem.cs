using System.Buffers.Binary;
using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal sealed class KdeSftpDescription
{
    internal const string Packet = "kdeconnect.sftp", Request = "kdeconnect.sftp.request";
    internal int Port { get; }
    internal string User { get; }
    internal string Path { get; }
    internal string Password { get; }
    private KdeSftpDescription(int port, string user, string path, string password)
    { Port = port; User = user; Path = path; Password = password; }
    public override string ToString() => "KDE SFTP description (credentials omitted)";

    internal static KdeSftpDescription Parse(JsonObject body)
    {
        var required = new[] { "port", "user", "path", "password" };
        var allowed = required.Concat(new[] { "ip", "multiPaths", "pathNames" }).ToHashSet(StringComparer.Ordinal);
        if (required.Any(key => !body.ContainsKey(key)) || body.Any(pair => !allowed.Contains(pair.Key)) ||
            body["port"] is not JsonValue portValue || !portValue.TryGetValue<int>(out var port) || port is < 1 or > 65535)
            throw new InvalidDataException("invalid_filesystem_description");
        static string Text(JsonNode? node, int max)
        {
            if (node is not JsonValue value || !value.TryGetValue<string>(out var text) || text.Length is < 1 ||
                text.Length > max || text.Any(char.IsControl)) throw new InvalidDataException("invalid_filesystem_description");
            return text;
        }
        static string Root(JsonNode? node)
        {
            var text = Text(node, 4096);
            if (!text.StartsWith('/') || text.Contains('\\') || text.Split('/').Any(part => part is "." or ".."))
                throw new InvalidDataException("invalid_filesystem_description");
            return text;
        }
        var user = Text(body["user"], 64); var password = Text(body["password"], 512); var path = Root(body["path"]);
        if (!Regex.IsMatch(user, "^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")) throw new InvalidDataException("invalid_filesystem_description");
        if (body.ContainsKey("multiPaths"))
        {
            if (body["multiPaths"] is not JsonArray paths || paths.Count is < 1 or > 64)
                throw new InvalidDataException("invalid_filesystem_description");
            foreach (var item in paths) Root(item);
            if (body.ContainsKey("pathNames"))
            {
                if (body["pathNames"] is not JsonArray names || names.Count != paths.Count)
                    throw new InvalidDataException("invalid_filesystem_description");
                foreach (var item in names) Text(item, 256);
            }
            path = "/";
        }
        else if (body.ContainsKey("pathNames")) throw new InvalidDataException("invalid_filesystem_description");
        return new(port, user, path, password);
    }

    internal static string PublicHostKey(X509Certificate2 certificate)
    {
        using var bytes = new MemoryStream();
        void String(byte[] value) { Span<byte> size = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(size, value.Length); bytes.Write(size); bytes.Write(value); }
        void Text(string value) => String(Encoding.ASCII.GetBytes(value));
        void Positive(byte[] value) => String(value.Length > 0 && (value[0] & 128) != 0 ? new byte[] { 0 }.Concat(value).ToArray() : value);
        string algorithm;
        using var rsa = certificate.GetRSAPublicKey();
        if (rsa is not null)
        {
            algorithm = "ssh-rsa"; var key = rsa.ExportParameters(false);
            Text(algorithm); Positive(key.Exponent!); Positive(key.Modulus!);
        }
        else
        {
            using var ec = certificate.GetECDsaPublicKey() ?? throw new CryptographicException("filesystem_host_key_unavailable");
            var key = ec.ExportParameters(false);
            var curve = key.Curve.Oid.Value switch { "1.2.840.10045.3.1.7" => "nistp256", "1.3.132.0.34" => "nistp384", "1.3.132.0.35" => "nistp521", _ => throw new CryptographicException("filesystem_host_key_unavailable") };
            algorithm = "ecdsa-sha2-" + curve; Text(algorithm); Text(curve);
            String(new byte[] { 4 }.Concat(key.Q.X!).Concat(key.Q.Y!).ToArray());
        }
        return algorithm + " " + Convert.ToBase64String(bytes.ToArray());
    }
}

internal interface IKdeFilesystemBrowser : IAsyncDisposable
{
    bool Available { get; }
    Task OpenAsync(string token, IPAddress address, KdeSftpDescription report, string publicKey, Func<bool> current, CancellationToken cancellation);
    Task CloseAsync(string? token = null);
}

internal sealed class KdeWindowsFilesystemBrowser : IKdeFilesystemBrowser
{
    private sealed record Mount(Process Process, string Directory, string Point, string KnownHosts, string Label, string Endpoint);
    private readonly string root;
    private readonly SemaphoreSlim gate = new(1, 1);
    private readonly Dictionary<string, Mount> mounts = new(StringComparer.Ordinal);
    private readonly Func<string?> executable;
    private readonly Func<string, string, bool> mounted;
    private readonly Action<string> show;
    private bool disposed;
    internal KdeWindowsFilesystemBrowser(string directory, Func<string?>? executable = null,
        Func<string, string, bool>? mounted = null, Action<string>? show = null)
    {
        root = System.IO.Path.Combine(directory, "filesystem");
        this.executable = executable ?? Installed;
        this.mounted = mounted ?? HasVolumeLabel;
        this.show = show ?? (path => { using var child = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); });
    }
    public bool Available => !disposed && executable() is not null;
    private static string? Installed()
    {
        if (!OperatingSystem.IsWindows()) return null;
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            using var machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, view);
            using var driver = machine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\WinFsp");
            using var client = machine.OpenSubKey(@"SOFTWARE\SSHFS-Win");
            if (driver is null) continue;
            var directory = client?.GetValue("InstallDir") as string ?? System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "SSHFS-Win");
            var wrapper = System.IO.Path.Combine(directory, "bin", "sshfs-win.exe");
            if (File.Exists(wrapper) && File.Exists(System.IO.Path.Combine(directory, "bin", "sshfs.exe"))) return wrapper;
        }
        return null;
    }
    internal static string CygwinPath(string path)
    {
        var full = System.IO.Path.GetFullPath(path);
        if (full.Length < 3 || !char.IsAsciiLetter(full[0]) || full[1] != ':' || full[2] != '\\')
            throw new InvalidDataException("filesystem_path_unavailable");
        return "/cygdrive/" + char.ToLowerInvariant(full[0]) + full[2..].Replace('\\', '/');
    }
    private static bool HasVolumeLabel(string path, string label)
    {
        if (!OperatingSystem.IsWindows()) return false;
        var volume = new StringBuilder(261); var filesystem = new StringBuilder(261);
        return GetVolumeInformation(path.TrimEnd('\\') + "\\", volume, volume.Capacity, out _, out _, out _, filesystem, filesystem.Capacity) && volume.ToString() == label;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetVolumeInformationW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetVolumeInformation(string root, StringBuilder name, int nameSize, out uint serial, out uint maxName, out uint flags, StringBuilder filesystem, int filesystemSize);

    internal static string[] Arguments(IPAddress address, KdeSftpDescription report, string point, string known, string label)
    {
        var host = address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6 ? "[" + address + "]" : address.ToString();
        var knownOption = "UserKnownHostsFile=\"" + known.Replace(",", "\\,", StringComparison.Ordinal) + "\"";
        return ["cmd", report.User + "@" + host + ":" + report.Path, point, "-p", report.Port.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "-f", "-s", "-F", "/dev/null", "-o", "password_stdin", "-o", "StrictHostKeyChecking=yes", "-o", knownOption,
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no",
            "-o", "NumberOfPasswordPrompts=1", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2", "-o", "volname=" + label];
    }
    public async Task OpenAsync(string token, IPAddress address, KdeSftpDescription report, string publicKey, Func<bool> current, CancellationToken cancellation)
    {
        await gate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            var program = executable();
            if (disposed || program is null || !current()) throw new InvalidOperationException("filesystem_source_changed");
            var endpoint = address + "|" + report.Port + "|" + report.User + "|" + report.Path + "|" + publicKey;
            if (mounts.TryGetValue(token, out var previous))
            {
                if (previous.Endpoint == endpoint && !previous.Process.HasExited && mounted(previous.Point, previous.Label))
                { if (!current()) throw new InvalidOperationException("filesystem_source_changed"); show(previous.Point); return; }
                await CleanupAsync(previous).ConfigureAwait(false); mounts.Remove(token);
            }
            Directory.CreateDirectory(root);
            var directory = System.IO.Path.Combine(root, "phone-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var point = System.IO.Path.Combine(directory, "files"); Directory.CreateDirectory(point);
            var known = System.IO.Path.Combine(directory, "known_hosts");
            var host = report.Port == 22 ? address.ToString() : "[" + address + "]:" + report.Port;
            await File.WriteAllTextAsync(known, host + " " + publicKey + "\n", new UTF8Encoding(false), cancellation).ConfigureAwait(false);
            var label = "Magnolie-" + Guid.NewGuid().ToString("N")[..16];
            var start = new ProcessStartInfo(program) { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true,
                RedirectStandardError = true, CreateNoWindow = true, WorkingDirectory = System.IO.Path.GetDirectoryName(program)! };
            foreach (var arg in Arguments(address, report, CygwinPath(point), CygwinPath(known), label)) start.ArgumentList.Add(arg);
            Process? process = null; Mount? entry = null;
            try
            {
                process = Process.Start(start) ?? throw new IOException("filesystem_mount_failed");
                entry = new(process, directory, point, known, label, endpoint);
                // Drain without collecting server-controlled output or credentials in a log.
                _ = process.StandardOutput.BaseStream.CopyToAsync(Stream.Null);
                _ = process.StandardError.BaseStream.CopyToAsync(Stream.Null);
                await process.StandardInput.WriteLineAsync(report.Password.AsMemory(), cancellation).ConfigureAwait(false); process.StandardInput.Close();
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(15));
                while (!mounted(point, label))
                {
                    if (!current()) throw new InvalidOperationException("filesystem_source_changed");
                    if (process.HasExited) throw new IOException("filesystem_mount_failed");
                    await Task.Delay(50, deadline.Token).ConfigureAwait(false);
                }
                if (!current()) throw new InvalidOperationException("filesystem_source_changed");
                show(point); mounts.Add(token, entry);
            }
            catch
            {
                if (entry is not null) await CleanupAsync(entry).ConfigureAwait(false);
                else { try { Directory.Delete(point); File.Delete(known); Directory.Delete(directory); } catch (IOException) { } }
                throw;
            }
        }
        finally { gate.Release(); }
    }
    private async Task CleanupAsync(Mount entry)
    {
        if (!entry.Process.HasExited)
        {
            entry.Process.Kill(entireProcessTree: true);
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            await entry.Process.WaitForExitAsync(deadline.Token).ConfigureAwait(false);
        }
        entry.Process.Dispose();
        if (!mounted(entry.Point, entry.Label))
            try { Directory.Delete(entry.Point); File.Delete(entry.KnownHosts); Directory.Delete(entry.Directory); }
            catch (IOException) { } // No recursive deletion, including after a failed teardown.
    }
    public async Task CloseAsync(string? token = null)
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try
        {
            foreach (var key in mounts.Keys.Where(key => token is null || key == token).ToArray())
            { await CleanupAsync(mounts[key]).ConfigureAwait(false); mounts.Remove(key); }
        }
        finally { gate.Release(); }
    }
    public async ValueTask DisposeAsync() { disposed = true; await CloseAsync().ConfigureAwait(false); }
}
