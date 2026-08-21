using System.Globalization;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace MagnolieOrganizer.Windows;

internal static class WindowsSpellChecker
{
    internal static (bool Correct, string[] Suggestions) Check(string word, string language)
    {
        var checker = Create(language);
        object? errors = null;
        object? suggestions = null;
        try
        {
            Throw(checker.Check(word, out var errorEnumerator));
            errors = errorEnumerator;
            var result = errorEnumerator.Next(out var error);
            if (error is null || result != 0) return (true, Array.Empty<string>());
            Marshal.FinalReleaseComObject(error);
            Throw(checker.Suggest(word, out var suggestionEnumerator));
            suggestions = suggestionEnumerator;
            var values = new List<string>();
            var buffer = new string[1];
            while (values.Count < 8 && suggestionEnumerator.Next(1, buffer, nint.Zero) == 0)
                if (!string.IsNullOrWhiteSpace(buffer[0]) && !buffer[0].Equals(word, StringComparison.Ordinal) && !values.Contains(buffer[0], StringComparer.Ordinal))
                    values.Add(buffer[0]);
            return (false, values.ToArray());
        }
        finally
        {
            Release(suggestions); Release(errors); Release(checker);
        }
    }

    internal static void Add(string word, string language)
    {
        var checker = Create(language);
        try { Throw(checker.Add(word)); }
        finally { Release(checker); }
    }

    private static ISpellChecker Create(string language)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Die Windows-Rechtschreibprüfung ist nur unter Windows verfügbar.");
        var factory = (ISpellCheckerFactory)(object)new SpellCheckerFactoryCom();
        try
        {
            foreach (var candidate in LanguageCandidates(language))
            {
                Throw(factory.IsSupported(candidate, out var supported));
                if (!supported) continue;
                Throw(factory.CreateSpellChecker(candidate, out var checker));
                return checker;
            }
            throw new InvalidOperationException("Für diese Sprache ist kein Windows-Wörterbuch installiert.");
        }
        finally { Release(factory); }
    }

    private static IEnumerable<string> LanguageCandidates(string language)
    {
        var basis = language.Equals("de", StringComparison.OrdinalIgnoreCase) ? "de" : "en";
        var current = CultureInfo.CurrentUICulture.Name;
        if (current.StartsWith(basis + "-", StringComparison.OrdinalIgnoreCase)) yield return current;
        yield return basis == "de" ? "de-DE" : "en-US";
        yield return basis;
    }

    private static void Throw(int result) { if (result < 0) Marshal.ThrowExceptionForHR(result); }
    private static void Release(object? value) { if (value is not null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value); }

    [ComImport, Guid("7AB36653-1796-484B-BDFA-E74F1DB7C1DC")]
    private sealed class SpellCheckerFactoryCom { }

    [ComImport, Guid("8E018A9D-2415-4677-BF08-794EA61F94BB"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ISpellCheckerFactory
    {
        [PreserveSig] int get_SupportedLanguages(out IEnumString value);
        [PreserveSig] int IsSupported([MarshalAs(UnmanagedType.LPWStr)] string languageTag, [MarshalAs(UnmanagedType.Bool)] out bool value);
        [PreserveSig] int CreateSpellChecker([MarshalAs(UnmanagedType.LPWStr)] string languageTag, out ISpellChecker value);
    }

    [ComImport, Guid("B6FD0B71-E2BC-4653-8D05-F197E412770B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ISpellChecker
    {
        [PreserveSig] int get_LanguageTag([MarshalAs(UnmanagedType.LPWStr)] out string value);
        [PreserveSig] int Check([MarshalAs(UnmanagedType.LPWStr)] string text, out IEnumSpellingError value);
        [PreserveSig] int Suggest([MarshalAs(UnmanagedType.LPWStr)] string word, out IEnumString value);
        [PreserveSig] int Add([MarshalAs(UnmanagedType.LPWStr)] string word);
    }

    [ComImport, Guid("803E3BD4-2828-4410-8290-418D1D73C762"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IEnumSpellingError
    {
        [PreserveSig] int Next([MarshalAs(UnmanagedType.Interface)] out object? value);
    }
}
