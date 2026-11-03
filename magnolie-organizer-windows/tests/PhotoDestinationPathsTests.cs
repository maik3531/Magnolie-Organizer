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
            requested.Clear();
            TestAssert.That(VideoDestinationPaths.NativeVideosDirectory(kind => { requested.Add(kind); return parent; }) == parent &&
                requested.SequenceEqual([Environment.SpecialFolder.MyVideos]), "Videos resolver did not use independent native MyVideos.");
            TestAssert.Throws<InvalidDataException>(() => VideoDestinationPaths.NativeVideosDirectory(_ => ""), "Missing videos path fell back silently.");
            TestAssert.Throws<InvalidDataException>(() => VideoDestinationPaths.NativeVideosDirectory(_ => "relative"), "Relative videos path accepted.");
            TestAssert.Throws<InvalidDataException>(() => VideoDestinationPaths.NativeVideosDirectory(_ => Path.Combine(parent, "missing")), "Videos resolver created a missing native parent.");
            foreach (var name in new[] { "../.config/Telefon", "CON.foo", "Phone: Photos\\Downloads", "📱", "Maiks  Telefon", "Müllers Telefon" })
            {
                var component = PhotoDestinationPaths.FolderComponent(name);
                TestAssert.That(Path.GetFileName(component) == component && component.EndsWith("-Fotos", StringComparison.Ordinal) &&
                    component.IndexOfAny(['/', '\\', ':', '.']) < 0 && !component.StartsWith('.'), "Raw native phone name became a path.");
                var video = VideoDestinationPaths.FolderComponent(name);
                TestAssert.That(Path.GetFileName(video) == video && video.EndsWith("-Videos", StringComparison.Ordinal) &&
                    video.IndexOfAny(['/', '\\', ':', '.']) < 0 && !video.StartsWith('.'), "Raw native phone name became a video path.");
            }
            TestAssert.That(PhotoDestinationPaths.FolderComponent("Müllers Telefon") == "Müllers Telefon-Fotos" &&
                PhotoDestinationPaths.FolderComponent("📱") == "Telefon-Fotos", "Native destination name projection mismatch.");
            TestAssert.That(VideoDestinationPaths.FolderComponent("Müllers Telefon") == "Müllers Telefon-Videos" &&
                VideoDestinationPaths.FolderComponent("📱") == "Telefon-Videos", "Video destination name projection mismatch.");
            TestAssert.That(PhotoDestinationPaths.FolderComponent("Pixel 9", "Maik") == "Pixel 9-Fotos" &&
                VideoDestinationPaths.FolderComponent("Pixel 9", "Maik") == "Pixel 9-Videos", "Username replaced a known phone name.");
            TestAssert.That(PhotoDestinationPaths.FolderComponent("", "Maik") == "Maik-Fotos" &&
                VideoDestinationPaths.FolderComponent("", "../Maik/Downloads") == "Maik_Downloads-Videos", "Missing phone-name fallback was unsafe or ignored.");
            TestAssert.That(!Directory.EnumerateFileSystemEntries(parent).Any(), "Native path projection created a folder without an explicit user choice.");
        }
        finally { Directory.Delete(parent); }
        return Task.CompletedTask;
    }
}
