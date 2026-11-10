using Microsoft.Data.Sqlite;

namespace MagnolieOrganizer.Windows.Tests;

/// <summary>Release only this fixture's exact TelefonStore pool, after its users drain.</summary>
internal sealed class OwnedTelefonPool : IDisposable
{
    private readonly SqliteConnection original;
    private int released;

    internal OwnedTelefonPool(TelefonStore store) => original = store.OpenDatabase();

    public void Dispose()
    {
        if (Interlocked.Exchange(ref released, 1) != 0) return;
        try { SqliteConnection.ClearPool(original); }
        finally { original.Dispose(); }
    }

    internal static void VerifyIsolation()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-owned-pools-" + Guid.NewGuid().ToString("N"));
        try
        {
            var firstPaths = new WindowsPaths(Path.Combine(root, "first"));
            var otherPaths = new WindowsPaths(Path.Combine(root, "other"));
            var first = new TelefonStore(firstPaths, new byte[32]);
            using var firstPool = new OwnedTelefonPool(first);
            var other = new TelefonStore(otherPaths, new byte[32]);
            using var otherPool = new OwnedTelefonPool(other);
            TestAssert.That(File.Exists(firstPaths.TelefonDatabase) && File.Exists(otherPaths.TelefonDatabase),
                "Owned pool fixtures did not create their actual databases.");
            firstPool.Dispose();
            File.Delete(firstPaths.TelefonDatabase);
            if (OperatingSystem.IsWindows())
                TestAssert.Throws<IOException>(() => File.Delete(otherPaths.TelefonDatabase),
                    "Releasing one exact fixture pool also cleared an unrelated live pool.");
            otherPool.Dispose();
            File.Delete(otherPaths.TelefonDatabase);
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
