namespace MagnolieOrganizer.Windows.Tests;

internal static class NativeLocalizationTests
{
    internal static Task RunAsync()
    {
        var cultures = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["en-US"] = "en", ["de-DE"] = "de", ["fr-FR"] = "fr", ["es-ES"] = "es",
            ["it-IT"] = "it", ["nl-NL"] = "nl", ["pt-BR"] = "pt", ["ru-RU"] = "ru",
            ["cs-CZ"] = "cs", ["pl-PL"] = "pl", ["hsb-DE"] = "hsb", ["da-DK"] = "da",
            ["nb-NO"] = "nb", ["hi-IN"] = "hi", ["zh-Hans-CN"] = "zh_CN", ["ja-JP"] = "ja",
            ["ar-SA"] = "ar", ["uk-UA"] = "uk", ["be-BY"] = "be", ["tr-TR"] = "tr"
        };
        foreach (var (culture, expected) in cultures)
        {
            var actual = NativeLocalization.ResolveLanguage(culture);
            TestAssert.That(actual == expected, $"{culture} wurde als {actual} statt {expected} aufgelöst.");
            var open = NativeLocalization.Gettext("Open", actual);
            TestAssert.That(actual == "en" ? open == "Open" : open != "Open",
                $"Der native Katalog für {actual} wurde nicht angewendet.");
        }
        TestAssert.That(NativeLocalization.ResolveLanguage("de-AT") == "de", "Deutscher Regional-Fallback fehlt.");
        TestAssert.That(NativeLocalization.ResolveLanguage("zh-Hans") == "zh_CN",
            "Vereinfachtes Chinesisch aus der Systemauswahl geht verloren.");
        TestAssert.That(NativeLocalization.ResolveLanguage("xx-ZZ") == "en", "Englischer Fallback fehlt.");
        TestAssert.That(NativeLocalization.Gettext("Missing native key", "de") == "Missing native key",
            "Fehlende deutsche Schlüssel müssen sauber auf den englischen msgid zurückfallen.");
        return Task.CompletedTask;
    }
}
