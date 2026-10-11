using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal static class SocialProfileMetadata
{
    private static readonly HashSet<string> Services = new(StringComparer.OrdinalIgnoreCase)
        { "whatsapp", "signal", "telegram", "threema", "facebook", "instagram", "teams", "snapchat", "tiktok", "youtube", "mastodon", "x", "linkedin", "reddit" };
    private static string? Service(string value) => value.Trim().ToLowerInvariant() switch
    { "twitter" => "x", "whatsapp business" => "whatsapp", var name => Services.Contains(name) ? name : null };

    internal static JsonObject? FromProperty(string name, string raw, IEnumerable<string> parameters)
    {
        if (name is not ("URL" or "IMPP" or "X-SOCIALPROFILE" or "X-SOCIAL-PROFILE")) return null;
        var value = raw.Trim();
        if (value.Length is 0 or > 2048 || value.Any(char.IsControl)) return null;
        var fields = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var parameter in parameters)
        {
            var pair = parameter.Split('=', 2);
            if (pair.Length == 2) fields[pair[0]] = pair[1].Trim('"');
        }
        var declared = new[] { fields.GetValueOrDefault("X-SERVICE-TYPE", "") }
            .Concat(fields.GetValueOrDefault("TYPE", "").Split(',')).Select(Service).FirstOrDefault(item => item is not null);
        if (Regex.IsMatch(value, "^https?://", RegexOptions.IgnoreCase)) return ProfileUrl(value, declared);
        if (name == "URL") return null;
        var colon = value.IndexOf(':');
        if (colon >= 0)
        {
            var explicitService = Service(value[..colon]);
            if (explicitService is not null)
            {
                if (declared is not null && declared != explicitService) return null;
                declared = explicitService; value = value[(colon + 1)..].TrimStart('/');
            }
            else value = fields.GetValueOrDefault("X-USER", "");
        }
        return declared is null || value.Length == 0 || value is "/" or "//" ? null :
            new JsonObject { ["dienst"] = declared, ["wert"] = value };
    }

    private static JsonObject? ProfileUrl(string value, string? declared)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") ||
            uri.UserInfo.Length != 0 || uri.Port is not (80 or 443)) return null;
        var host = uri.IdnHost.ToLowerInvariant(); if (host.StartsWith("www.", StringComparison.Ordinal)) host = host[4..];
        var parts = uri.AbsolutePath.Trim('/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        bool Single(string pattern, params string[] excluded) => parts.Length == 1 && Regex.IsMatch(parts[0], "^(?:" + pattern + ")$") && !excluded.Contains(parts[0].ToLowerInvariant());
        string? service = null; var query = ""; var fragment = "";
        if (host == "instagram.com" && Single("[A-Za-z0-9._]{1,30}", "accounts", "explore", "direct", "stories", "reels", "reel", "p", "about")) service = "instagram";
        else if (host is "facebook.com" or "m.facebook.com")
        {
            if (parts.Length == 1 && parts[0] == "profile.php")
            {
                var ids = uri.Query.TrimStart('?').Split('&').Where(part => part.StartsWith("id=", StringComparison.Ordinal)).ToArray();
                if (ids.Length != 1 || !Regex.IsMatch(ids[0], "^id=[0-9]+$")) return null;
                query = ids[0]; service = "facebook";
            }
            else if (Single("[A-Za-z0-9.]+", "login", "help", "pages", "groups", "watch", "share", "sharer", "privacy", "settings", "marketplace", "events", "photo", "photos", "reel") ||
                parts.Length == 3 && parts[0] == "people" && Regex.IsMatch(parts[2], "^[0-9]+$")) service = "facebook";
        }
        else if (host is "twitter.com" or "x.com" && Single("[A-Za-z0-9_]{1,15}", "home", "explore", "search", "settings", "intent", "i", "compose", "messages", "notifications")) service = "x";
        else if (host is "t.me" or "telegram.me" && Single("[A-Za-z][A-Za-z0-9_]{4,31}", "share", "joinchat", "addstickers", "proxy", "login")) service = "telegram";
        else if (host == "wa.me" && Single("[0-9]{5,20}")) service = "whatsapp";
        else if (host == "threema.id" && Single("[A-Za-z0-9]{8}")) service = "threema";
        else if (host == "signal.me" && Regex.IsMatch(uri.Fragment, "^#(p/\\+[0-9]{5,20}|eu/[A-Za-z0-9_-]+)$")) { service = "signal"; fragment = uri.Fragment[1..]; }
        else if (host == "linkedin.com" && parts.Length == 2 && parts[0] is "in" or "company") service = "linkedin";
        else if (host == "youtube.com" && (Single("@[A-Za-z0-9._-]+") || parts.Length == 2 && parts[0] == "channel")) service = "youtube";
        else if (host == "tiktok.com" && Single("@[A-Za-z0-9._]+")) service = "tiktok";
        else if (host == "snapchat.com" && parts.Length == 2 && parts[0] == "add") service = "snapchat";
        else if (host == "reddit.com" && parts.Length == 2 && parts[0] is "u" or "user") service = "reddit";
        else if (declared == "mastodon" && (Single("@[A-Za-z0-9_.-]+") || parts.Length == 2 && parts[0] == "users")) service = "mastodon";
        if (service is null || declared is not null && service != declared) return null;
        return new JsonObject { ["dienst"] = service, ["wert"] = new UriBuilder("https", host) { Path = uri.AbsolutePath, Query = query, Fragment = fragment }.Uri.AbsoluteUri };
    }
}
