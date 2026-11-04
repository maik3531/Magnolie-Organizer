using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileNativeDirectoryTests
{
    internal static Task GrammarAsync()
    {
        foreach (var valid in new[] { @"C:\", @"C:\Users\Synthetic\Pictures", @"D:\Video-Aufnahmen\", @"E:\Bilder mit Leerzeichen\Magnolie" })
        {
            var expected = valid.Length > 3 ? valid.TrimEnd('\\') : valid;
            TestAssert.That(DeviceFileNativeDirectory.NtDirectoryName(valid) == @"\??\" + expected, "Native path was guessed or reinterpreted.");
        }
        foreach (var invalid in new[] { "", "relative", @"C:relative", @"\root", @"\\server\share", @"\\?\C:\root", @"\\.\C:\root",
            @"C:/root", @"C:\root\..\other", @"C:\root\.\other", @"C:\root\\child", @"C:\\", @"C:\root:stream",
            @"C:\folder\CON", @"C:\NUL.txt", @"C:\conin$", @"C:\LPT1.txt", @"C:\COM².txt", @"C:\tail.", @"C:\tail ",
            @"C:\wild*", @"C:\question?", "C:\\bad\0name", "C:\\bad\nname", "C:\\" + new string('a', 16001) })
            TestAssert.Throws<InvalidDataException>(() => DeviceFileNativeDirectory.NtDirectoryName(invalid), "Unsupported root syntax accepted: " + invalid);
        return Task.CompletedTask;
    }

    internal static Task UnsupportedPlatformAsync()
    {
        if (OperatingSystem.IsWindows()) throw new InvalidOperationException("Non-Windows boundary test registered on Windows.");
        TestAssert.Throws<PlatformNotSupportedException>(() => DeviceFileNativeDirectory.OpenExisting(@"C:\Synthetic"), "Non-Windows host invented a native directory owner.");
        return Task.CompletedTask;
    }

    // Only registered on Windows. Linux codec/build receipts must not count this
    // test as passed, and installed/native acceptance remains separately required.
    internal static Task WindowsHandleAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-native-directory-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var directory = Path.Combine(root, "media"); Directory.CreateDirectory(directory);
            var owner = DeviceFileNativeDirectory.OpenExisting(directory);
            try
            {
                TestAssert.That(owner.CurrentIdentity() == owner.OriginalIdentity, "Live directory handle lost its volume/file ID.");
                TestAssert.Throws<IOException>(() => Directory.Move(directory, Path.Combine(root, "moved")), "Live native owner allowed a root rename.");
            }
            finally { owner.Dispose(); }
            TestAssert.Throws<ObjectDisposedException>(() => owner.CurrentIdentity(), "Closed directory retained native authority.");
            var file = Path.Combine(root, "ordinary-file"); File.WriteAllText(file, "synthetic");
            TestAssert.Throws<IOException>(() => DeviceFileNativeDirectory.OpenExisting(file), "Ordinary file became a directory owner.");
            TestAssert.Throws<IOException>(() => DeviceFileNativeDirectory.OpenExisting(Path.Combine(root, "missing")), "Missing root was created.");
            TestAssert.That(!Directory.Exists(Path.Combine(root, "missing")), "Root observation wrote a directory.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    internal static Task WindowsReparseAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-native-reparse-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var alias = Path.Combine(root, "alias");
        try
        {
            var target = Path.Combine(root, "target"); Directory.CreateDirectory(Path.Combine(target, "child"));
            // This acceptance test intentionally requires Windows symlink rights;
            // an unavailable prerequisite is a failed proof, never a fake pass.
            Directory.CreateSymbolicLink(alias, target);
            TestAssert.Throws<IOException>(() => DeviceFileNativeDirectory.OpenExisting(alias), "Final reparse point was followed.");
            TestAssert.Throws<IOException>(() => DeviceFileNativeDirectory.OpenExisting(Path.Combine(alias, "child")), "Ancestor reparse point was followed.");
        }
        finally
        {
            if (Directory.Exists(alias)) Directory.Delete(alias);
            Directory.Delete(root, true);
        }
        return Task.CompletedTask;
    }
}
