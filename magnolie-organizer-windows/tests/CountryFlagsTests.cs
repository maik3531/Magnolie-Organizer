namespace MagnolieOrganizer.Windows.Tests;

internal static class CountryFlagsTests
{
    internal static Task RunAsync()
    {
        TestAssert.That(CountryFlags.TryCell("de", out var x, out var y) && x == 256 && y == 144, "German flag atlas coordinates differ from the shared ISO layout.");
        TestAssert.That(CountryFlags.TryCell("AT", out x, out y) && x == 1216 && y == 0, "Austrian flag atlas coordinates differ from the shared ISO layout.");
        foreach (var value in new string?[] { "", null, "ZZ", "other", "DE-other", "../../DE" })
            TestAssert.That(!CountryFlags.TryCell(value, out _, out _), "Unknown setup country displayed a fallback national flag.");
        var root = TestSource.Root("contracts/kontakt-sync-contract.json");
        var windows = Directory.Exists(Path.Combine(root, "magnolie-organizer-windows"))
            ? Path.Combine(root, "magnolie-organizer-windows") : root;
        var linux = File.Exists(Path.Combine(root, "magnolie-organizer/web/country-flags.png"))
            ? Path.Combine(root, "magnolie-organizer/web/country-flags.png")
            : Path.Combine(windows, "shared/magnolie-organizer/web/country-flags.png");
        TestAssert.That(File.ReadAllBytes(linux).AsSpan().SequenceEqual(
            File.ReadAllBytes(Path.Combine(windows, "app/web/country-flags.png"))), "Desktop/native setup flag artwork is not shared across platforms.");
        return Task.CompletedTask;
    }
}
