using System.Security.Cryptography;
using System.Text.Json;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class RecordExportFileTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-record-export-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var profile = Path.Combine(root, "owned-profile.json"); File.WriteAllText(profile, "{\"owned\":true}");
            var store = new AtomicStore();
            var cases = new Dictionary<string, string> {
                ["ics-termine"] = """[{"id":"event","titel":"Owned 🌸 export","datum":"2030-01-02","zeit":"09:00","endZeit":"10:00"}]""",
                ["csv-termine"] = """[{"id":"event","titel":"Owned 🌸 export","datum":"2030-01-02","zeit":"09:00","endZeit":"10:00"}]""",
                ["ics-aufgaben"] = """[{"id":"task","titel":"Owned task","faellig":"2030-01-02"}]""",
                ["ics-jahrestage"] = """[{"id":"anniversary","name":"Owned anniversary","datum":"2000-01-02","typ":"birthday"}]""",
                ["vcf-adressen"] = """[{"id":"contact","vorname":"Owned","nachname":"Export","email":"owned@example.invalid"}]""",
                ["ldif-adressen"] = """[{"id":"contact","vorname":"Owned","nachname":"Export","email":"owned@example.invalid"}]""" };
            void MustReject(Action action)
            {
                var rejected = false;
                try { action(); } catch (IOException) { rejected = true; }
                TestAssert.That(rejected, "Native exchange export accepted a protected or non-overwrite target.");
            }
            foreach (var (format, text) in cases)
            {
                using var data = JsonDocument.Parse(text);
                var exported = RecordExportFile.Convert(format, data.RootElement);
                TestAssert.That(exported.Count == 1, "Actual native exchange codec did not export the owned fixture.");
                var target = Path.Combine(root, format + ".owned");
                var written = RecordExportFile.WriteVerified(store, target, profile, format, exported, overwrite: false);
                var actual = File.ReadAllBytes(target);
                TestAssert.That(written.Bytes == actual.Length && written.Sha256 == Convert.ToHexString(SHA256.HashData(actual)).ToLowerInvariant(),
                    "Actual exported bytes did not match the native readback proof.");
                TestAssert.That(actual.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) == (format == "csv-termine"), "CSV BOM or UTF-8 exchange encoding changed.");
                MustReject(() => RecordExportFile.WriteVerified(store, target, profile, format, exported, overwrite: false));
                TestAssert.That(File.ReadAllBytes(target).AsSpan().SequenceEqual(actual), "Rejected overwrite changed the old export.");
                RecordExportFile.WriteVerified(store, target, profile, format, exported, overwrite: true);
                MustReject(() => RecordExportFile.WriteVerified(store, profile, profile, format, exported, overwrite: true));
                if (!OperatingSystem.IsWindows())
                {
                    var link = target + ".link"; File.CreateSymbolicLink(link, profile);
                    MustReject(() => RecordExportFile.WriteVerified(store, link, profile, format, exported, overwrite: true));
                }
            }
            TestAssert.That(File.ReadAllText(profile) == "{\"owned\":true}", "Export overwrote the active profile.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
