using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;

namespace MagnolieOrganizer.Windows.Tests;

// Owned synthetic file boundary only; no book, keyring, provider or device IO.
internal static class ContactSourcePrivateFilesTests
{
    internal static void Run()
    {
        var modes = new List<string> { "default-no-files", "empty-existing-root", "roundtrip", "unknown-leaf", "write-too-large", "read-too-large",
            "invalid-utf8", "contended-lock", "disposed", "state-directory", "lock-directory", "root-reparse", "parent-reparse",
            "shared-root", "shared-file" };
        if (OperatingSystem.IsWindows()) modes.AddRange(["hardlink-key", "hardlink-state", "hardlink-lock"]);
        else modes.AddRange(["no-unix-production-fallback", "symlink-state"]);
        foreach (var mode in modes)
        {
            var parent = Path.Combine(Path.GetTempPath(), "magnolie-contact-private-files-" + Guid.NewGuid().ToString("N"));
            var root = Path.Combine(parent, "consent");
            var boundary = new ContactSourcePrivateFiles(root, controlledUnix: !OperatingSystem.IsWindows());
            ContactSourcePrivateFiles.Session? session = null;
            try
            {
                if (mode == "default-no-files")
                {
                    TestAssert.That(boundary.Open() is null && !Directory.Exists(parent), "Default consent file read created directories/lock files");
                }
                else if (mode == "empty-existing-root")
                {
                    using (boundary.Open(create: true)) { }
                    File.Delete(Path.Combine(root, ".lock"));
                    TestAssert.That(boundary.Open() is null && !Directory.EnumerateFileSystemEntries(root).Any(),
                        "Empty existing native root created default lock or metadata files");
                }
                else if (mode == "no-unix-production-fallback")
                {
                    TestAssert.Throws<PlatformNotSupportedException>(() => new ContactSourcePrivateFiles(root), "Windows private storage silently enabled a Unix production fallback");
                }
                else
                {
                    session = boundary.Open(create: true) ?? throw new IOException("Controlled private fixture not created");
                    session.Write("approval.json", "{\"syntheticOnly\":true}", 1024);
                    if (mode == "roundtrip")
                    {
                        TestAssert.That(session.Read("approval.json", 1024) == "{\"syntheticOnly\":true}", "Private state bytes did not roundtrip");
                        session.Write(".key.dpapi", "synthetic-protected-key-placeholder", 1024);
                        session.Delete(".key.dpapi");
                        TestAssert.That(session.Read(".key.dpapi", 1024) is null && !File.Exists(Path.Combine(root, "approval.json.bak")),
                            "Private key deletion or no-old-backup boundary failed");
                    }
                    if (mode == "unknown-leaf")
                    {
                        TestAssert.Throws<ArgumentException>(() => session.Read("../foreign", 10), "Private read accepted a caller path");
                        TestAssert.Throws<ArgumentException>(() => session.Write("foreign", "x", 10), "Private write accepted an unknown leaf");
                        TestAssert.Throws<ArgumentException>(() => session.Delete(".lock"), "Private delete accepted its live lock");
                    }
                    if (mode == "write-too-large")
                        TestAssert.Throws<IOException>(() => session.Write("approval.json", new string('x', 100), 10), "Private write exceeded the bounded payload");
                    if (mode == "read-too-large")
                        TestAssert.Throws<IOException>(() => session.Read("approval.json", 10), "Private read exceeded the bounded payload");
                    if (mode == "invalid-utf8")
                    {
                        var file = Path.Combine(root, "approval.json"); File.WriteAllBytes(file, [0xff, 0xff]);
                        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(file, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                        TestAssert.Throws<System.Text.DecoderFallbackException>(() => session.Read("approval.json", 1024), "Private metadata silently replaced invalid UTF-8");
                    }
                    if (mode == "contended-lock")
                    {
                        var watch = Stopwatch.StartNew();
                        TestAssert.Throws<IOException>(() => boundary.Open(), "A second private consent writer acquired the same live lock");
                        TestAssert.That(watch.Elapsed < TimeSpan.FromSeconds(2), "Private consent lock waited instead of failing bounded");
                    }
                    if (mode == "disposed")
                    {
                        session.Dispose();
                        TestAssert.Throws<ObjectDisposedException>(() => session.Read("approval.json", 1024), "Disposed private session remained usable");
                    }
                    if (mode == "state-directory")
                    {
                        File.Delete(Path.Combine(root, "approval.json")); Directory.CreateDirectory(Path.Combine(root, "approval.json"));
                        TestAssert.Throws<IOException>(() => session.Read("approval.json", 1024), "State directory became a private data file");
                    }
                    if (mode == "lock-directory")
                    {
                        session.Dispose(); File.Delete(Path.Combine(root, ".lock")); Directory.CreateDirectory(Path.Combine(root, ".lock"));
                        TestAssert.Throws<IOException>(() => boundary.Open(), "Lock directory became a native consent lock");
                    }
                    if (mode is "root-reparse" or "parent-reparse")
                    {
                        session.Dispose();
                        var linked = Path.Combine(parent, "linked");
                        LinkDirectory(linked, root);
                        var alias = mode == "root-reparse" ? linked : Path.Combine(linked, "child-must-not-exist");
                        var redirected = new ContactSourcePrivateFiles(alias, controlledUnix: !OperatingSystem.IsWindows());
                        TestAssert.Throws<IOException>(() => redirected.Open(create: true), "Linked root/ancestor granted private consent storage");
                        TestAssert.That(!Directory.Exists(Path.Combine(root, "child-must-not-exist")), "Rejected linked parent still created data");
                        Directory.Delete(linked);
                    }
                    if (mode is "shared-root" or "shared-file")
                    {
                        var path = mode == "shared-root" ? root : Path.Combine(root, "approval.json");
                        if (OperatingSystem.IsWindows()) AddWorldWrite(path, mode == "shared-root");
                        else File.SetUnixFileMode(path, File.GetUnixFileMode(path) | UnixFileMode.OtherWrite);
                        TestAssert.Throws<UnauthorizedAccessException>(() => session.Read("approval.json", 1024), "Shared native consent state was trusted as private");
                    }
                    if (mode == "symlink-state")
                    {
                        var original = Path.Combine(parent, "untouched"); File.WriteAllText(original, "synthetic-original-must-stay");
                        File.Delete(Path.Combine(root, "approval.json")); File.CreateSymbolicLink(Path.Combine(root, "approval.json"), original);
                        TestAssert.Throws<IOException>(() => session.Read("approval.json", 1024), "Linked private state was followed");
                        TestAssert.Throws<IOException>(() => session.Write("approval.json", "replace", 1024), "Linked private state was replaced");
                        TestAssert.That(File.ReadAllText(original) == "synthetic-original-must-stay", "Rejected link changed the original fixture");
                    }
                    if (mode.StartsWith("hardlink-", StringComparison.Ordinal))
                    {
                        var name = mode == "hardlink-key" ? ".key.dpapi" : mode == "hardlink-lock" ? ".lock" : "approval.json";
                        if (name == ".key.dpapi") session.Write(name, "synthetic-protected-key-placeholder", 1024);
                        if (name == ".lock") session.Dispose();
                        if (!CreateHardLink(Path.Combine(parent, "other-owned-link"), Path.Combine(root, name), IntPtr.Zero))
                            throw new IOException("Could not create owned hardlink counterexample: " + Marshal.GetLastWin32Error());
                        if (name == ".lock") TestAssert.Throws<IOException>(() => boundary.Open(), "Hardlinked lock was trusted");
                        else
                        {
                            TestAssert.Throws<IOException>(() => session.Read(name, 1024), "Hardlinked key/state was trusted");
                            TestAssert.Throws<IOException>(() => session.Write(name, "replace", 1024), "Hardlinked key/state was overwritten");
                        }
                    }
                }
                Console.WriteLine("CONTACT SOURCE PRIVATE FILES PASS " + mode);
            }
            finally { session?.Dispose(); if (Directory.Exists(parent)) Directory.Delete(parent, true); }
        }
    }

    private static void LinkDirectory(string path, string target)
    {
        if (!OperatingSystem.IsWindows()) { Directory.CreateSymbolicLink(path, target); return; }
        var start = new ProcessStartInfo("cmd.exe", $"/c mklink /J \"{path}\" \"{target}\"")
            { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        using var process = Process.Start(start) ?? throw new IOException("Could not start bounded owned junction fixture");
        if (!process.WaitForExit(5000)) { process.Kill(true); process.WaitForExit(); throw new IOException("Owned junction fixture deadline"); }
        TestAssert.That(process.ExitCode == 0, "Owned junction fixture failed; no privilege escalation is permitted");
    }

    [SupportedOSPlatform("windows")]
    private static void AddWorldWrite(string path, bool directory)
    {
        var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
        FileSystemSecurity security = directory ? new DirectoryInfo(path).GetAccessControl() : new FileInfo(path).GetAccessControl();
        security.AddAccessRule(new FileSystemAccessRule(everyone, FileSystemRights.Write, AccessControlType.Allow));
        if (directory) new DirectoryInfo(path).SetAccessControl((DirectorySecurity)security);
        else new FileInfo(path).SetAccessControl((FileSecurity)security);
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateHardLinkW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateHardLink(string fileName, string existingFileName, IntPtr securityAttributes);
}
