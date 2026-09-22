using System.Buffers.Binary;
using System.IO.Compression;
using System.IO.Pipes;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal sealed class ThunderbirdBridgeException : IOException
{
    internal ThunderbirdBridgeException(Exception? inner = null) : base("Thunderbird bridge request failed.", inner) { }
}

// Thunderbird owns authentication. Only selected DAV resources, never tokens or
// account passwords, cross this current-user-only native-messaging channel.
internal static class ThunderbirdBridge
{
    internal const string ExtensionId = "magnolie-bridge@magnolie-organizer.org";
    internal const string HostName = "org.magnolie.thunderbird";
    internal const int MaximumRequestBytes = 1024 * 1024;
    internal const int MaximumResponseBytes = 16 * 1024 * 1024;
    internal static string PipeName => "magnolie-thunderbird-" + Convert.ToHexString(SHA256.HashData(
        Encoding.UTF8.GetBytes(Environment.UserDomainName + "\\" + Environment.UserName)))[..24];
    internal static string ManifestPath => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Magnolie Organizer", "thunderbird", "host.json");
    internal static bool IsSource(string id) => id.StartsWith("thunderbird-calendar:", StringComparison.Ordinal) ||
        id.StartsWith("thunderbird-addressbook:", StringComparison.Ordinal);

    internal static async Task<byte[]> ReadFrameAsync(Stream stream, int maximum, CancellationToken token)
    {
        var header = new byte[4];
        await stream.ReadExactlyAsync(header, token).ConfigureAwait(false);
        var size = BinaryPrimitives.ReadUInt32LittleEndian(header);
        if (size is 0 || size > maximum) throw new InvalidDataException("Invalid Thunderbird message length.");
        var bytes = new byte[(int)size];
        await stream.ReadExactlyAsync(bytes, token).ConfigureAwait(false);
        return bytes;
    }

    internal static async Task WriteFrameAsync(Stream stream, byte[] bytes, int maximum, CancellationToken token)
    {
        if (bytes.Length == 0 || bytes.Length > maximum) throw new InvalidDataException("Thunderbird message exceeds its limit.");
        var header = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(header, (uint)bytes.Length);
        await stream.WriteAsync(header, token).ConfigureAwait(false);
        await stream.WriteAsync(bytes, token).ConfigureAwait(false);
        await stream.FlushAsync(token).ConfigureAwait(false);
    }

    internal static async Task<int> RunHostAsync(Stream input, Stream output, CancellationToken token)
    {
        // One active Thunderbird profile owns the bridge. Source IDs include a
        // persistent profile identity, so switching profiles cannot reinterpret
        // a missing source as an empty address book or calendar.
        try
        {
            while (!token.IsCancellationRequested)
            {
                using var pipe = new NamedPipeServerStream(PipeName, PipeDirection.InOut, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                var incoming = ReadFrameAsync(input, MaximumResponseBytes, token);
                var connected = pipe.WaitForConnectionAsync(token);
                if (await Task.WhenAny(incoming, connected).ConfigureAwait(false) == incoming)
                {
                    await incoming.ConfigureAwait(false); // Detect Thunderbird exit while idle.
                    return 1; // Unsolicited response: protocol violation.
                }
                await connected.ConfigureAwait(false);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
                deadline.CancelAfter(TimeSpan.FromMinutes(2));
                var request = await ReadFrameAsync(pipe, MaximumRequestBytes, deadline.Token).ConfigureAwait(false);
                await WriteFrameAsync(output, request, MaximumRequestBytes, deadline.Token).ConfigureAwait(false);
                var response = await incoming.WaitAsync(deadline.Token).ConfigureAwait(false);
                try { await WriteFrameAsync(pipe, response, MaximumResponseBytes, deadline.Token).ConfigureAwait(false); }
                catch (IOException) { /* Client cancelled; the response has been drained. */ }
            }
            return 0;
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or UnauthorizedAccessException)
        { return 1; } // Never send diagnostics to stdout: it is a framed channel.
    }

    internal static async Task<JsonObject> CallAsync(JsonObject request, CancellationToken token, int connectTimeout = 1500)
    {
        var id = Guid.NewGuid().ToString("N"); request["id"] = id; request["version"] = 1;
        using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        await pipe.ConnectAsync(connectTimeout, token).ConfigureAwait(false);
        await WriteFrameAsync(pipe, JsonSerializer.SerializeToUtf8Bytes(request), MaximumRequestBytes, token).ConfigureAwait(false);
        var bytes = await ReadFrameAsync(pipe, MaximumResponseBytes, token).ConfigureAwait(false);
        var response = JsonNode.Parse(bytes, documentOptions: new JsonDocumentOptions { MaxDepth = 16 }) as JsonObject;
        if (response is null || response["id"]?.GetValue<string>() != id || response["version"]?.GetValue<int>() != 1)
            throw new InvalidDataException("Invalid Thunderbird response.");
        if (response["ok"]?.GetValue<bool>() != true)
            throw new ThunderbirdBridgeException();
        return response;
    }

    internal static async Task<IReadOnlyList<NextcloudDavSource>> SourcesAsync(CancellationToken token)
    {
        JsonObject response;
        try { response = await CallAsync(new JsonObject { ["op"] = "sources" }, token).ConfigureAwait(false); }
        catch (Exception error) when (error is IOException or TimeoutException) { throw new ThunderbirdBridgeException(error); }
        if (response["sources"] is not JsonArray values || values.Count > 1000) throw new InvalidDataException();
        var result = new List<NextcloudDavSource>();
        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var value in values.OfType<JsonObject>())
        {
            var uid = value["uid"]!.GetValue<string>(); var kind = value["kind"]!.GetValue<string>();
            var href = NextcloudMailbox.ValidateServer(value["url"]!.GetValue<string>());
            if (!uid.StartsWith("thunderbird-" + kind + ":", StringComparison.Ordinal) ||
                kind is not ("calendar" or "addressbook") || !ids.Add(uid)) throw new InvalidDataException();
            result.Add(new NextcloudDavSource(uid, value["name"]!.GetValue<string>(), kind, href,
                value["tasks"]?.GetValue<bool>() == true));
        }
        if (result.Count != values.Count) throw new InvalidDataException();
        return result;
    }

    internal static NextcloudDavClient CreateClient(NextcloudDavSource source, NextcloudSyncJournal journal, string transactionId)
    {
        var context = new NextcloudMailboxContext(new NextcloudMailboxSettings(true, false,
            source.Href.GetLeftPart(UriPartial.Authority), "Thunderbird") { AccountType = "generic-dav" }, null);
        return new NextcloudDavClient(context, new HttpClient(new ThunderbirdHttpHandler(source))
            { Timeout = TimeSpan.FromSeconds(90) }, journal, transactionId);
    }

    internal static string InstallHost()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var executable = Environment.ProcessPath ?? throw new InvalidOperationException();
        var directory = Path.GetDirectoryName(ManifestPath)!; Directory.CreateDirectory(directory);
        new AtomicStore().Write(ManifestPath, JsonSerializer.Serialize(new
        {
            name = HostName, description = "Magnolie Thunderbird bridge", path = executable,
            type = "stdio", allowed_extensions = new[] { ExtensionId }
        }));
        using var key = Registry.CurrentUser.CreateSubKey(@"Software\Mozilla\NativeMessagingHosts\" + HostName);
        key.SetValue("", ManifestPath);
        var xpi = Path.Combine(directory, "Magnolie-Thunderbird.xpi");
        using var memory = new MemoryStream();
        using (var zip = new ZipArchive(memory, ZipArchiveMode.Create, true))
            foreach (var name in new[] { "manifest.json", "background.js", "api.js", "schema.json" })
            {
                var entry = zip.CreateEntry(name);
                using var output = entry.Open();
                using var input = File.OpenRead(Path.Combine(AppContext.BaseDirectory, "thunderbird", name));
                input.CopyTo(output);
            }
        File.WriteAllBytes(xpi, memory.ToArray());
        return xpi;
    }

    internal static void UnregisterHost()
    {
        if (!OperatingSystem.IsWindows() || !File.Exists(ManifestPath)) return;
        var text = new AtomicStore().Read(ManifestPath, 64 * 1024);
        if (text is null) return;
        JsonNode? manifest;
        try { manifest = JsonNode.Parse(text); }
        catch (JsonException) { return; }
        if (manifest is not JsonObject entry || entry["path"] is not JsonValue value || !value.TryGetValue<string>(out var executable) ||
            !string.Equals(executable, Environment.ProcessPath, StringComparison.OrdinalIgnoreCase)) return;
        const string registryPath = @"Software\Mozilla\NativeMessagingHosts\org.magnolie.thunderbird";
        using (var key = Registry.CurrentUser.OpenSubKey(registryPath))
            if (!string.Equals(key?.GetValue("") as string, ManifestPath, StringComparison.OrdinalIgnoreCase)) return;
        Registry.CurrentUser.DeleteSubKey(registryPath, false);
        File.Delete(ManifestPath);
    }

    private sealed class ThunderbirdHttpHandler(NextcloudDavSource source) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var headers = new JsonObject();
            foreach (var name in new[] { "Depth", "If-Match", "If-None-Match" })
                if (request.Headers.TryGetValues(name, out var values)) headers[name] = values.Single();
            var response = await CallAsync(new JsonObject
            {
                ["op"] = "http", ["source"] = source.Uid, ["url"] = request.RequestUri!.AbsoluteUri,
                ["method"] = request.Method.Method, ["headers"] = headers,
                ["body"] = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false),
                ["contentType"] = request.Content?.Headers.ContentType?.MediaType ?? "application/xml"
            }, cancellationToken).ConfigureAwait(false);
            var status = response["status"]!.GetValue<int>();
            if (status is < 200 or > 599) throw new InvalidDataException();
            var result = new HttpResponseMessage((HttpStatusCode)status)
            { Content = new StringContent(response["body"]?.GetValue<string>() ?? "", Encoding.UTF8) };
            var etag = response["etag"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(etag)) result.Headers.TryAddWithoutValidation("ETag", etag);
            if (response["location"]?.GetValue<string>() is { Length: > 0 } location)
            {
                var target = new Uri(location);
                if (!target.AbsoluteUri.StartsWith(source.Href.AbsoluteUri.TrimEnd('/') + "/", StringComparison.Ordinal))
                    throw new InvalidDataException("Thunderbird returned a resource outside the selected collection.");
                result.Content.Headers.ContentLocation = target;
            }
            return result;
        }
    }
}
