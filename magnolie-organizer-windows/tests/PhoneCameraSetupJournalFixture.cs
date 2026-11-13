namespace MagnolieOrganizer.Windows;

// Test-host-only partial. Product has no arbitrary journal path/hash factory or
// way to replace the protected CreateCurrent route with an unprotected fixture.
internal sealed partial class PhoneCameraSetupJournal
{
    internal static PhoneCameraSetupJournal JournalFixtureCreate(string path) => new(
        new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 4096, FileOptions.WriteThrough),
        [], Guid.NewGuid(), new string('a', 64), new string('b', 64));
    internal void JournalFixtureBreakWriter() => file.Dispose();
}
