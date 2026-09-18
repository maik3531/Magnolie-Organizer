using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

internal static class ShellLauncher
{
    internal static bool OpenExternalUri(string target) =>
        TryOpenUri(target, "http", "https", "mailto", "tel");

    internal static bool OpenWebUri(string target) =>
        TryOpenUri(target, "http", "https");

    internal static bool OpenContactUri(string target) =>
        TryOpenUri(target, "http", "https", "mailto", "tel", "sms", "msteams");

    internal static bool OpenLocalFile(string path, string expectedDirectory) =>
        TryGetExistingLocalPath(path, expectedDirectory, directory: false, out var fullPath) &&
        TryStart(fullPath);

    internal static bool OpenLocalDirectory(string path, string expectedDirectory) =>
        TryGetExistingLocalPath(path, expectedDirectory, directory: true, out var fullPath) &&
        TryStart(fullPath);

    internal static bool IsAllowedExternalUri(string target) =>
        IsAllowedUri(target, "http", "https", "mailto", "tel");

    internal static bool IsAllowedContactUri(string target) =>
        IsAllowedUri(target, "http", "https", "mailto", "tel", "sms", "msteams");

    internal static bool TryGetExistingLocalPath(string path, string expectedDirectory,
        bool directory, out string fullPath)
    {
        fullPath = "";
        if (string.IsNullOrWhiteSpace(path) || string.IsNullOrWhiteSpace(expectedDirectory)) return false;
        try
        {
            var candidate = Path.GetFullPath(path);
            var root = Path.GetFullPath(expectedDirectory);
            var relative = Path.GetRelativePath(root, candidate);
            if (Path.IsPathRooted(relative) || relative == ".." ||
                relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
                relative.StartsWith(".." + Path.AltDirectorySeparatorChar, StringComparison.Ordinal)) return false;
            if (directory ? !Directory.Exists(candidate) : !File.Exists(candidate)) return false;
            fullPath = candidate;
            return true;
        }
        catch (Exception error) when (error is ArgumentException or IOException or
                                             NotSupportedException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static bool TryOpenUri(string target, params string[] allowedSchemes)
    {
        if (string.IsNullOrWhiteSpace(target) || !Uri.TryCreate(target, UriKind.Absolute, out var uri) ||
            !allowedSchemes.Contains(uri.Scheme, StringComparer.OrdinalIgnoreCase)) return false;
        return TryStart(uri.AbsoluteUri);
    }

    private static bool IsAllowedUri(string target, params string[] allowedSchemes) =>
        !string.IsNullOrWhiteSpace(target) && Uri.TryCreate(target, UriKind.Absolute, out var uri) &&
        allowedSchemes.Contains(uri.Scheme, StringComparer.OrdinalIgnoreCase);

    private static bool TryStart(string target)
    {
        try
        {
            Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
