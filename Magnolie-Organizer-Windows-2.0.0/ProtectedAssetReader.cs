using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Web.WebView2.Core;

namespace MagnolieOrganizer.Windows;

internal static class ProtectedAssetReader
{
    private const int MaxContainer = 2 * 1024 * 1024;
    private const int MaxPlaintext = 1024 * 1024;

    private sealed class ClearingMemoryStream : MemoryStream
    {
        private readonly byte[] data;

        internal ClearingMemoryStream(byte[] data) : base(data, writable: false)
        {
            this.data = data;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) CryptographicOperations.ZeroMemory(data);
            base.Dispose(disposing);
        }
    }

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
        IReadOnlyDictionary<string, (string Container, byte Id, byte Mime, string ContentType)> assets)
    {
        foreach (var logicalPath in assets.Keys)
            core.AddWebResourceRequestedFilter($"https://{host}{logicalPath}", CoreWebView2WebResourceContext.Image);
        core.WebResourceRequested += (_, eventArgs) =>
        {
            if (!Uri.TryCreate(eventArgs.Request.Uri, UriKind.Absolute, out var uri) ||
                !uri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase) ||
                !uri.Host.Equals(host, StringComparison.OrdinalIgnoreCase) ||
                !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment) ||
                !assets.TryGetValue(uri.AbsolutePath, out var asset) ||
                !eventArgs.Request.Uri.Equals($"https://{host}{uri.AbsolutePath}", StringComparison.Ordinal)) return;
            try
            {
                var data = Read(Path.Combine(root, asset.Container), asset.Id, asset.Mime);
                eventArgs.Response = core.Environment.CreateWebResourceResponse(
                    new ClearingMemoryStream(data), 200, "OK",
                    $"Content-Type: {asset.ContentType}\r\nCache-Control: no-store");
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or CryptographicException)
            {
                eventArgs.Response = core.Environment.CreateWebResourceResponse(
                    Stream.Null, 404, "Not Found", "Cache-Control: no-store");
            }
        };
    }
}
