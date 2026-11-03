using System.Globalization;
using System.Text;

namespace MagnolieOrganizer.Windows;

// Native path/name projection only. It grants no directory write, file consent,
// publication or synchronization permission and creates no folder itself.
internal static class PhotoDestinationPaths
{
    internal static string NativePicturesDirectory() => NativePicturesDirectory(Environment.GetFolderPath);

    internal static string NativePicturesDirectory(Func<Environment.SpecialFolder, string> provider)
    {
        var path = provider(Environment.SpecialFolder.MyPictures);
        if (string.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path) || !Directory.Exists(path))
            throw new InvalidDataException("photo_destination_native_pictures_unavailable");
        return path; // No guessed HOME/Pictures/localized literal or Create option.
    }

    internal static string FolderComponent(string name, string fallbackUserName = "")
        => MediaFolderComponent(name, "-Fotos", fallbackUserName);

    internal static string NativeFolderComponent(string phoneName) => FolderComponent(phoneName, Environment.UserName);

    internal static string MediaFolderComponent(string name, string suffix, string fallbackUserName = "")
    {
        if (name is null) throw new InvalidDataException("photo_destination_native_name_required");
        var safe = new StringBuilder();
        foreach (var rune in name.Normalize(NormalizationForm.FormC).EnumerateRunes())
        {
            var category = Rune.GetUnicodeCategory(rune);
            var allowed = category is UnicodeCategory.UppercaseLetter or UnicodeCategory.LowercaseLetter or UnicodeCategory.TitlecaseLetter or
                UnicodeCategory.ModifierLetter or UnicodeCategory.OtherLetter or UnicodeCategory.DecimalDigitNumber or UnicodeCategory.LetterNumber or UnicodeCategory.OtherNumber;
            safe.Append(allowed || rune.Value is 32 or 45 or 95 ? rune.ToString() : "_");
        }
        var words = string.Join(" ", safe.ToString().Split(' ', StringSplitOptions.RemoveEmptyEntries)).Trim(' ', '_');
        var limited = string.Concat(words.EnumerateRunes().Take(60).Select(rune => rune.ToString())).TrimEnd(' ', '_');
        if (limited.Length == 0 && fallbackUserName.Length != 0) return MediaFolderComponent(fallbackUserName, suffix);
        return (limited.Length == 0 ? "Telefon" : limited) + suffix;
    }
}

// Independent video path projection; no video consent, source scan or folder I/O.
internal static class VideoDestinationPaths
{
    internal static string NativeVideosDirectory() => NativeVideosDirectory(Environment.GetFolderPath);

    internal static string NativeVideosDirectory(Func<Environment.SpecialFolder, string> provider)
    {
        var path = provider(Environment.SpecialFolder.MyVideos);
        if (string.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path) || !Directory.Exists(path))
            throw new InvalidDataException("video_destination_native_videos_unavailable");
        return path;
    }

    internal static string FolderComponent(string name, string fallbackUserName = "") => PhotoDestinationPaths.MediaFolderComponent(name, "-Videos", fallbackUserName);
    internal static string NativeFolderComponent(string phoneName) => FolderComponent(phoneName, Environment.UserName);
}
