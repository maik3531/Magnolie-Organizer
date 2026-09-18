using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Web.WebView2.Core;

namespace MagnolieOrganizer.Windows;

internal static class ProtectedAssetReader
{
    private const int MaxContainer = 2 * 1024 * 1024;
    private const int MaxPlaintext = 1024 * 1024;

    internal static byte[] Read(string path, byte expectedId, byte expectedMime)
    {
        if (!((expectedId == 1 && expectedMime == 1) ||
              (expectedId == 2 && expectedMime == 2)))
            throw new InvalidDataException("Asset request is not allowlisted.");
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is < 40 or > MaxContainer)
            throw new InvalidDataException("Invalid asset container size.");
        var container = new byte[checked((int)stream.Length)];
        stream.ReadExactly(container);
        var header = container.AsSpan(0, 24);
        if (!header[..4].SequenceEqual("MGA1"u8) || header[4] != 1 ||
            header[5] != expectedId || header[6] != expectedMime || header[7] != 0)
            throw new InvalidDataException("Invalid asset container header.");
        var ciphertextLength = BinaryPrimitives.ReadUInt32BigEndian(header[20..24]);
        if (ciphertextLength is < 16 or > MaxPlaintext + 16 ||
            container.Length != 24L + ciphertextLength)
            throw new InvalidDataException("Invalid asset ciphertext length.");
        var plaintext = new byte[checked((int)ciphertextLength - 16)];
        var keyMaterial = Encoding.ASCII.GetBytes(
            "Magnolie/native-personal-assets/" + "2026/" + "MGA-v1");
        var key = SHA256.HashData(keyMaterial);
        CryptographicOperations.ZeroMemory(keyMaterial);
        try
        {
            using var aes = new AesGcm(key, 16);
            aes.Decrypt(header[8..20], container.AsSpan(24, (int)ciphertextLength - 16),
                container.AsSpan(container.Length - 16, 16), plaintext, header);
        }
        catch
        {
            CryptographicOperations.ZeroMemory(plaintext);
            throw;
        }
        finally
        {
            CryptographicOperations.ZeroMemory(key);
            CryptographicOperations.ZeroMemory(container);
        }
        byte[] signature = expectedMime == 1
            ? new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a }
            : new byte[] { 0xff, 0xd8, 0xff };
        if (plaintext.Length > MaxPlaintext || !plaintext.AsSpan().StartsWith(signature))
        {
            CryptographicOperations.ZeroMemory(plaintext);
            throw new InvalidDataException("Invalid decrypted asset type.");
        }
        return plaintext;
    }

    internal static void Register(CoreWebView2 core, string host, string root,
        IReadOnlyDictionary<string, (string Container, byte Id, byte Mime, string ContentType)> assets,
        Action<string>? diagnostic = null)
    {
        var allowedPaths = assets.Keys.ToHashSet(StringComparer.Ordinal);
        core.AddWebResourceRequestedFilter($"https://{host}/*", CoreWebView2WebResourceContext.All);
        diagnostic?.Invoke($"Protected asset host registered: {host}; WebView2={core.Environment.BrowserVersionString}");
        if (diagnostic is not null)
            core.WebResourceResponseReceived += (_, eventArgs) =>
            {
                if (!ProtectedAssetPolicy.TryGetAllowedPath(eventArgs.Request.Uri, host, allowedPaths,
                        out var absolutePath)) return;
                diagnostic($"Protected asset response received: {host}{absolutePath}; " +
                    $"status={eventArgs.Response.StatusCode}");
            };
        core.WebResourceRequested += (_, eventArgs) =>
        {
            if (!ProtectedAssetPolicy.TryGetAllowedPath(eventArgs.Request.Uri, host, allowedPaths,
                    out var absolutePath) || !assets.TryGetValue(absolutePath, out var asset)) return;
            try
            {
                var data = Read(Path.Combine(root, asset.Container), asset.Id, asset.Mime);
                // WebView2 reads the response after this callback; do not dispose or clear its stream here.
                eventArgs.Response = core.Environment.CreateWebResourceResponse(
                    new MemoryStream(data, writable: false), 200, "OK",
                    ProtectedAssetPolicy.ResponseHeaders(asset.ContentType, data.Length));
                diagnostic?.Invoke($"Geschütztes Asset {absolutePath} wurde mit {data.Length} Bytes bereitgestellt.");
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                          CryptographicException or InvalidDataException)
            {
                diagnostic?.Invoke($"Geschütztes Asset {absolutePath} konnte nicht geladen werden: " +
                    $"{error.GetType().Name}: {error.Message}");
                eventArgs.Response = core.Environment.CreateWebResourceResponse(
                    Stream.Null, 404, "Not Found", ProtectedAssetPolicy.EmptyResponseHeaders);
            }
        };
    }
}
