using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhotoDestinationPathsTests
{
    internal static Task RunAsync()
    {
        var parent = Path.Combine(Path.GetTempPath(), "magnolie-native-pictures-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(parent);
        try
        {
            var requested = new List<Environment.SpecialFolder>();
            TestAssert.That(PhotoDestinationPaths.NativePicturesDirectory(kind => { requested.Add(kind); return parent; }) == parent &&
                requested.SequenceEqual([Environment.SpecialFolder.MyPictures]), "Pictures resolver guessed a directory instead of native MyPictures.");
            TestAssert.Throws<InvalidDataException>(() => PhotoDestinationPaths.NativePicturesDirectory(_ => ""), "Missing native pictures path fell back silently.");
            TestAssert.Throws<InvalidDataException>(() => PhotoDestinationPaths.NativePicturesDirectory(_ => "relative"), "Relative native pictures path accepted.");
            foreach (var name in new[] { "../.config/Telefon", "CON.foo", "Phone: Photos\\Downloads", "📱", "Maiks  Telefon", "Müllers Telefon" })
            {
                var component = PhotoDestinationPaths.FolderComponent(name);
                TestAssert.That(Path.GetFileName(component) == component && component.EndsWith("-Fotos", StringComparison.Ordinal) &&
                    component.IndexOfAny(['/', '\\', ':', '.']) < 0 && !component.StartsWith('.'), "Raw native phone name became a path.");
            }
            TestAssert.That(PhotoDestinationPaths.FolderComponent("Müllers Telefon") == "Müllers Telefon-Fotos" &&
                PhotoDestinationPaths.FolderComponent("📱") == "Telefon-Fotos", "Native destination name projection mismatch.");
            TestAssert.That(!Directory.EnumerateFileSystemEntries(parent).Any(), "Native path projection created a folder without an explicit user choice.");
        }
        finally { Directory.Delete(parent); }
        return Task.CompletedTask;
    }
}
