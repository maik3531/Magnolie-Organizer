namespace MagnolieOrganizer.Windows.Tests;

internal static class WebViewStartupSourceTests
{
    internal static Task RunAsync()
    {
        var provider = File.ReadAllText("WebViewEnvironmentProvider.cs");
        var main = File.ReadAllText("MainForm.cs");
        var handbook = File.ReadAllText("HandbookForm.cs");
        var uiSelfTest = File.ReadAllText("UiSelfTest.cs");

        TestAssert.That(provider.Contains("Dictionary<string, Task<CoreWebView2Environment>>", StringComparison.Ordinal) &&
                        provider.Contains("CoreWebView2Environment.CreateAsync", StringComparison.Ordinal),
            "WebView2-Umgebungen werden nicht pro Datenordner serialisiert.");
        TestAssert.That(main.Contains("WebViewEnvironmentProvider.GetAsync(paths)", StringComparison.Ordinal) &&
                        handbook.CountText("WebViewEnvironmentProvider.GetAsync(paths)") == 2 &&
                        !main.Contains("CoreWebView2Environment.CreateAsync", StringComparison.Ordinal) &&
                        !handbook.Contains("CoreWebView2Environment.CreateAsync", StringComparison.Ordinal),
            "Main, Handbuch und Druckansicht verwenden nicht dieselbe WebView2-Umgebung.");
        TestAssert.That(handbook.Contains("eventArgs.IsSuccess && IsInternal(source)", StringComparison.Ordinal) &&
                        handbook.Contains("IsTransientStartupFailure", StringComparison.Ordinal) &&
                         handbook.Contains("ShellLauncher.OpenExternalUri(eventArgs.Uri)", StringComparison.Ordinal) &&
                         main.Contains("ShellLauncher.OpenExternalUri(eventArgs.Uri)", StringComparison.Ordinal),
            "Handbuch-Readiness, Startwiederholung oder externe Navigationssperre fehlt.");
        TestAssert.That(uiSelfTest.IndexOf("timer.Stop();", StringComparison.Ordinal) <
                        uiSelfTest.IndexOf("OpenHandbookAsync", StringComparison.Ordinal),
            "Der UI-Selbsttest verhindert keine Timer-Reentranz vor dem Handbuchtest.");
        TestAssert.That(uiSelfTest.Contains("document.fonts.check", StringComparison.Ordinal) &&
                        uiSelfTest.Contains("WINDOWS-BUNDLED-FONT-OK", StringComparison.Ordinal) &&
                        uiSelfTest.Contains("ClientSize.Width >= 1200", StringComparison.Ordinal),
            "Der echte Windows-UI-Selbsttest prüft Schriftladung oder Startgröße nicht.");
        return Task.CompletedTask;
    }

    private static int CountText(this string source, string value) =>
        source.Split(value, StringSplitOptions.None).Length - 1;
}
