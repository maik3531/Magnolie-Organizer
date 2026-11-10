using System.Diagnostics;
using System.IO.Compression;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using Microsoft.Win32;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace MagnolieOrganizer.Windows.Tests;

// Separately approved host probe, NEVER an ordinary test registration. It
// writes protected staging and executes ONLY the native read-only plan.
[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioProtectedPreparationTests
{
    internal static async Task<int> RunAsync()
    {
        if (Environment.GetEnvironmentVariable("MAGNOLIE_AUDIO_PROTECTED_PREP_APPROVED") != "1") return 77;
        var packageFile = Environment.GetEnvironmentVariable("MAGNOLIE_CABLE_PACKAGE_FIXTURE") ?? throw new InvalidOperationException("Explicit package fixture required");
        var helperRoot = Environment.GetEnvironmentVariable("MAGNOLIE_AUDIO_HELPER_FIXTURE") ?? throw new InvalidOperationException("Explicit source-bound helper fixture required");
        var expectedHelperHash = Environment.GetEnvironmentVariable("MAGNOLIE_AUDIO_HELPER_SHA256") ?? throw new InvalidOperationException("Exact approved helper hash required");
        var helper = PhoneCameraAudioHelperPayload.VerifyEmbeddedSnapshot(
            File.ReadAllBytes(Path.Combine(helperRoot, PhoneCameraAudioHelperPayload.Filename)), File.ReadAllBytes(Path.Combine(helperRoot, "phone-audio-helper.manifest")));
        TestAssert.That(helper.Sha256 == expectedHelperHash, "Approved helper bytes changed");
        var archive = File.ReadAllBytes(packageFile); var package = PhoneCameraAudioPackage.Verify(archive);
        var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Magnolie-Webcam-Driver-Setup");
        TestAssert.That(!Directory.Exists(root) && !File.Exists(root), "Preserve existing protected staging; probe refused");
        using (var journal = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Magnolie Organizer\WebcamDriver\VB-CABLE-Pack46"))
            TestAssert.That(journal is null, "Existing setup transaction; probe refused");
        var expected = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        using (var zip = new ZipArchive(new MemoryStream(archive), ZipArchiveMode.Read))
            foreach (var member in zip.Entries)
            {
                using var contents = member.Open(); expected.Add(member.FullName, Convert.ToHexString(SHA256.HashData(contents)).ToLowerInvariant());
            }
        expected.Add(PhoneCameraAudioHelperPayload.Filename, helper.Sha256);
        string directory;
        using (var prepared = PhoneCameraAudioStaging.Prepare(package, helper))
        {
            directory = prepared.Directory;
            TestAssert.That(prepared.RootCreated, "Concurrent existing root preserved; probe refused");
            using (var changedParent = CreateFile(Path.GetDirectoryName(root)!, 0x40000000, 7, IntPtr.Zero, 3, 0x02000000 | 0x00200000, IntPtr.Zero))
                TestAssert.That(changedParent.IsInvalid && Marshal.GetLastWin32Error() == 32, "Held ProgramData allowed direct data-write/reparse access");
            TestAssert.That(Path.GetDirectoryName(directory) == root && Guid.TryParseExact(Path.GetFileName(directory), "B", out _), "Unexpected staging scope");
            CheckContents();
            TestAssert.Throws<IOException>(() => { using var changed = new FileStream(prepared.Executable, FileMode.Open, FileAccess.Write, FileShare.Read); },
                "Held helper allowed replacement/write");
            var start = new ProcessStartInfo(prepared.Executable) { UseShellExecute = false, CreateNoWindow = true,
                WorkingDirectory = directory, RedirectStandardOutput = true, RedirectStandardError = true };
            start.ArgumentList.Add("--plan"); start.ArgumentList.Add(directory); // NO install path in this probe.
            using var process = Process.Start(start) ?? throw new IOException("Read-only helper did not start");
            var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(45));
            try { await process.WaitForExitAsync(timeout.Token); }
            catch { if (!process.HasExited) process.Kill(); await process.WaitForExitAsync(); throw; } // This child is READ-ONLY, never SetupAPI install.
            var plan = await output; var stderr = await errors;
            TestAssert.That(process.ExitCode == 0 && stderr.Length == 0 && PhoneCameraAudioSetupWire.IsOriginalPlan(plan, out _), "Protected original package/helper plan refused");
            Console.WriteLine(plan.Trim()); CheckContents();
            prepared.RemoveKnownUninstalledPreparation();
            TestAssert.Throws<InvalidOperationException>(prepared.MarkInstallationStarted, "Cleaned original preparation could be installed/reused");
            TestAssert.Throws<InvalidOperationException>(prepared.RemoveKnownUninstalledPreparation, "Cleaned original preparation was silently retried");
        }
        TestAssert.That(!Directory.Exists(root), "Own uninstalled preparation cleanup not confirmed");
        using (var journal = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Magnolie Organizer\WebcamDriver\VB-CABLE-Pack46"))
            TestAssert.That(journal is null, "Read-only plan created an install transaction");
        Console.WriteLine("PASS protected package/helper publication, held-byte protection, read-only plan and exact own cleanup; no driver installation");
        return 0;

        void CheckContents()
        {
            TestAssert.That((File.GetAttributes(directory) & FileAttributes.ReparsePoint) == 0 &&
                Directory.EnumerateFileSystemEntries(directory).Select(Path.GetFileName).Order(StringComparer.Ordinal).SequenceEqual(expected.Keys.Order(StringComparer.Ordinal)),
                "Unexpected staging contents; preserve for review");
            foreach (var (name, hash) in expected)
            {
                var path = Path.Combine(directory, name);
                using var file = File.OpenRead(path);
                TestAssert.That((File.GetAttributes(path) & FileAttributes.ReparsePoint) == 0 && Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant() == hash,
                    "Unexpected staging bytes/reparse; preserve for review");
            }
        }
    }
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string path, uint access, uint sharing, IntPtr security, uint creation, uint flags, IntPtr template);
}
