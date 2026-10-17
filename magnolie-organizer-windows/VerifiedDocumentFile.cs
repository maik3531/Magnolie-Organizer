using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed record VerifiedDocumentFile(string Path, int Bytes, string Sha256)
{
    internal static VerifiedDocumentFile Write(string path, string profilePath, byte[] bytes, bool overwrite)
    {
        path = System.IO.Path.GetFullPath(path);
        if (bytes.LongLength > AtomicStore.MaxDataBytes) throw new IOException("export_file_too_large");
        if (string.Equals(path, System.IO.Path.GetFullPath(profilePath), StringComparison.OrdinalIgnoreCase) || new FileInfo(path).LinkTarget is not null)
            throw new IOException("invalid_export_target");
        var parent = System.IO.Path.GetDirectoryName(path) ?? throw new IOException("invalid_export_target");
        if (!Directory.Exists(parent)) throw new DirectoryNotFoundException();
        for (var directory = new DirectoryInfo(parent); directory is not null; directory = directory.Parent)
            if ((directory.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("invalid_export_target");
        if (File.Exists(path) && (!overwrite || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0))
            throw new IOException("export_target_exists");
        var temporary = System.IO.Path.Combine(parent, "." + System.IO.Path.GetFileName(path) + "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 64 * 1024, FileOptions.WriteThrough))
            { output.Write(bytes); output.Flush(true); }
            // The atomic move also enforces the no-overwrite choice if a target
            // appeared after the initial inspection.
            File.Move(temporary, path, overwrite);
            using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (input.Length != bytes.Length) throw new IOException("export_verification_failed");
            var actual = new byte[bytes.Length]; input.ReadExactly(actual);
            if (!actual.AsSpan().SequenceEqual(bytes)) throw new IOException("export_verification_failed");
            return new(path, actual.Length, Convert.ToHexString(SHA256.HashData(actual)).ToLowerInvariant());
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
