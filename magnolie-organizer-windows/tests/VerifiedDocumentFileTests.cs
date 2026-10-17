using System.IO.Compression;
using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class VerifiedDocumentFileTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-document-export-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var profile = Path.Combine(root, "owned-profile.json"); File.WriteAllText(profile, "{\"owned\":true}");
            var bytes = DocumentExportService.CreateSpreadsheet(new[] { new DocumentSheet("Owned planner", new[] { "Owned column" },
                new IReadOnlyList<string>[] { new[] { "Owned entry" } }) });
            var target = Path.Combine(root, "Owned planner.ods");
            var written = VerifiedDocumentFile.Write(target, profile, bytes, overwrite: false);
            TestAssert.That(written.Bytes == bytes.Length && written.Sha256 == Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(target))).ToLowerInvariant(),
                "Actual native document export readback did not match its bytes/hash.");
            using (var archive = ZipFile.OpenRead(target))
            {
                using var mime = new StreamReader(archive.GetEntry("mimetype")!.Open());
                TestAssert.That(mime.ReadToEnd() == "application/vnd.oasis.opendocument.spreadsheet", "Actual native ODS generator did not create the expected document.");
            }
            void MustReject(Action action)
            {
                var rejected = false;
                try { action(); } catch (IOException) { rejected = true; }
                TestAssert.That(rejected, "Document export accepted a protected or non-overwrite target.");
            }
            MustReject(() => VerifiedDocumentFile.Write(target, profile, bytes, overwrite: false));
            VerifiedDocumentFile.Write(target, profile, bytes, overwrite: true);
            MustReject(() => VerifiedDocumentFile.Write(profile, profile, bytes, overwrite: true));
            if (!OperatingSystem.IsWindows())
            {
                var link = Path.Combine(root, "owned-link.ods"); File.CreateSymbolicLink(link, profile);
                MustReject(() => VerifiedDocumentFile.Write(link, profile, bytes, overwrite: true));
            }
            TestAssert.That(File.ReadAllText(profile) == "{\"owned\":true}", "Document export overwrote the profile.");
            TestAssert.That(!Directory.EnumerateFiles(root, "*.tmp").Any(), "Document export left a temporary file behind.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
