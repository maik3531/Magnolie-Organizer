using System.Globalization;
using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal static class NativeLocalization
{
    private static readonly string[] SupportedLocales =
    [
        "de", "fr", "es", "it", "nl", "pt", "ru", "cs", "pl", "hsb", "da", "nb",
        "hi", "zh_CN", "ja", "ar", "uk", "be", "tr"
    ];
    private static readonly Lazy<IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>>> Catalogs =
        new(LoadCatalogs);

    internal static string Language { get; } = ResolveLanguage(CultureInfo.CurrentUICulture.Name);

    internal static string Gettext(string message) => Gettext(message, Language);

    internal static string Gettext(string message, string language)
    {
        if (language == "en") return message;
        return Catalogs.Value.TryGetValue(language, out var catalog) &&
               catalog.TryGetValue(message, out var translation) && !string.IsNullOrWhiteSpace(translation)
            ? translation
            : message;
    }

    internal static string ResolveLanguage(string? cultureName)
    {
        var normalized = (cultureName ?? "").Replace('-', '_');
        if (normalized.Equals("zh", StringComparison.OrdinalIgnoreCase) ||
            normalized.StartsWith("zh_", StringComparison.OrdinalIgnoreCase)) return "zh_CN";
        foreach (var locale in SupportedLocales)
            if (normalized.Equals(locale, StringComparison.OrdinalIgnoreCase) ||
                normalized.StartsWith(locale + "_", StringComparison.OrdinalIgnoreCase)) return locale;
        return "en";
    }

    private static IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>> LoadCatalogs()
    {
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "native-i18n.json");
            using var stream = File.OpenRead(path);
            using var document = JsonDocument.Parse(stream);
            var result = new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.Ordinal);
            foreach (var locale in document.RootElement.GetProperty("locales").EnumerateObject())
            {
                var messages = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var message in locale.Value.EnumerateObject())
                    messages[message.Name] = message.Value.GetString() ?? "";
                result[locale.Name] = messages;
            }
            return result;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            return new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.Ordinal);
        }
    }
}
