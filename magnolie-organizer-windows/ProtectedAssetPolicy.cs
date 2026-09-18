using System.Globalization;

namespace MagnolieOrganizer.Windows;

internal static class ProtectedAssetPolicy
{
    internal static bool TryGetAllowedPath(string target, string host,
        IReadOnlySet<string> allowedPaths, out string absolutePath)
    {
        absolutePath = "";
        if (!Uri.TryCreate(target, UriKind.Absolute, out var uri) ||
            !uri.Scheme.Equals(Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase) ||
            !uri.Host.Equals(host, StringComparison.OrdinalIgnoreCase) || uri.Port != 443 ||
            !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) ||
            !string.IsNullOrEmpty(uri.Fragment) || !allowedPaths.Contains(uri.AbsolutePath)) return false;
        absolutePath = uri.AbsolutePath;
        return true;
    }

    internal static string ResponseHeaders(string contentType, int contentLength)
    {
        if (contentType is not ("image/png" or "image/jpeg") || contentLength < 0)
            throw new InvalidDataException("Invalid protected asset response metadata.");
        return $"Content-Type: {contentType}\r\nContent-Length: {contentLength.ToString(CultureInfo.InvariantCulture)}\r\n" +
               "X-Content-Type-Options: nosniff\r\nCache-Control: no-store";
    }

    internal const string EmptyResponseHeaders =
        "Content-Length: 0\r\nX-Content-Type-Options: nosniff\r\nCache-Control: no-store";
}
