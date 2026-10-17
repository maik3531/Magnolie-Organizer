using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

internal sealed record ImportFileSource(string Path, byte[] Bytes, string Sha256, string Revision)
{
    internal static ImportFileSource Read(string format, string path, string? expectedRevision = null)
    {
        path = System.IO.Path.GetFullPath(path);
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length > ExchangeCodec.MaxImportBytes) throw new IOException("import_file_too_large");
        using var buffer = new MemoryStream();
        var chunk = new byte[64 * 1024];
        int read;
        while ((read = input.Read(chunk)) != 0)
        {
            if (buffer.Length + read > ExchangeCodec.MaxImportBytes) throw new IOException("import_file_too_large");
            buffer.Write(chunk, 0, read);
        }
        var bytes = buffer.ToArray();
        using var revisionHash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        revisionHash.AppendData(Encoding.UTF8.GetBytes(format + "\0" + path + "\0"));
        revisionHash.AppendData(bytes);
        var revision = Convert.ToHexString(revisionHash.GetHashAndReset()).ToLowerInvariant();
        if (!string.IsNullOrEmpty(expectedRevision) && revision != expectedRevision) throw new InvalidOperationException("mcp_conflict");
        return new(path, bytes, Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(), revision);
    }
}
