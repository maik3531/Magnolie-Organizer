using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed record VerifiedRecordExport(string Path, int Bytes, string Sha256);

internal static class RecordExportFile
{
    internal static ExchangeExportResult Convert(string format, JsonElement data) => format switch
    {
        "vcf-adressen" => ExchangeCodec.WriteVCard(data),
        "ldif-adressen" => ExchangeCodec.WriteLdif(data),
        "csv-termine" => ExchangeCodec.WriteLotusCsv(data),
        "ics-termine" or "ics-jahrestage" or "ics-aufgaben" => ExchangeCodec.WriteIcs(format, data),
        _ => throw new InvalidDataException("unsupported_export_format")
    };

    internal static VerifiedRecordExport WriteVerified(AtomicStore store, string path, string profilePath,
        string format, ExchangeExportResult result, bool overwrite)
    {
        path = System.IO.Path.GetFullPath(path);
        if (File.Exists(path) && !overwrite) throw new IOException("export_target_exists");
        if (string.Equals(path, System.IO.Path.GetFullPath(profilePath), StringComparison.OrdinalIgnoreCase) || new FileInfo(path).LinkTarget is not null)
            throw new IOException("invalid_export_target");
        var text = (format == "csv-termine" ? "\ufeff" : "") + result.Text;
        var expected = Encoding.UTF8.GetBytes(text);
        store.Write(path, text);
        var actual = new byte[expected.Length];
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length != actual.Length) throw new IOException("export_verification_failed");
        input.ReadExactly(actual);
        if (!actual.AsSpan().SequenceEqual(expected)) throw new IOException("export_verification_failed");
        return new(path, actual.Length, System.Convert.ToHexString(SHA256.HashData(actual)).ToLowerInvariant());
    }
}
