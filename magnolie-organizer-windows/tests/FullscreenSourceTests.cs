namespace MagnolieOrganizer.Windows.Tests;

internal static class FullscreenSourceTests
{
    internal static Task RunAsync()
    {
        var source = File.ReadAllText("MainForm.cs");
        var hook = Section(source, "var controller = typeof(WebView2).GetField", "var language =");
        var enter = Section(source, "private void EnterFullscreen()", "private void ExitFullscreen()");
        var exit = Section(source, "private void ExitFullscreen()", "private void RestoreWindowState()");
        var save = Section(source, "private void SaveWindowState()", "private sealed record SavedWindowState");

        TestAssert.That(hook.Contains("as CoreWebView2Controller", StringComparison.Ordinal) &&
                        hook.Contains("controller.AcceleratorKeyPressed", StringComparison.Ordinal) &&
                        hook.Contains("Keys.F11", StringComparison.Ordinal) &&
                        hook.Contains("CoreWebView2KeyEventKind.KeyDown", StringComparison.Ordinal) &&
                        hook.Contains("CoreWebView2KeyEventKind.SystemKeyDown", StringComparison.Ordinal) &&
                        hook.Contains("eventArgs.Handled = true", StringComparison.Ordinal) &&
                        hook.Contains("BeginInvoke(ToggleFullscreen)", StringComparison.Ordinal),
            "Der WebView2-Controller fängt F11 nicht vollständig und asynchron ab.");
        TestAssert.That(hook.IndexOf("eventArgs.Handled = true", StringComparison.Ordinal) <
                        hook.IndexOf("PhysicalKeyStatus.WasKeyDown", StringComparison.Ordinal) &&
                        hook.Contains("if (eventArgs.PhysicalKeyStatus.WasKeyDown != 0) return;", StringComparison.Ordinal),
            "F11-Autorepeat wird nicht nach dem Handled-Marker unterdrückt.");
        TestAssert.That(!source.Contains("Keys.Escape", StringComparison.Ordinal) &&
                        !source.Contains("ConsoleKey.Escape", StringComparison.Ordinal),
            "Ein nativer Escape-Handler darf Vollbild nicht verlassen.");
        TestAssert.That(source.Contains("bool Fullscreen = false", StringComparison.Ordinal) &&
                        source.Contains("restoreFullscreen = state.Fullscreen", StringComparison.Ordinal) &&
                        save.Contains("fullscreenRestoreClientSize", StringComparison.Ordinal) &&
                        save.Contains("fullscreenRestoreWindowState == FormWindowState.Maximized", StringComparison.Ordinal),
            "Das rückwärtskompatible Vollbildfeld oder seine Persistenz fehlt.");
        TestAssert.That(enter.Contains("fullscreenRestoreBorderStyle = FormBorderStyle", StringComparison.Ordinal) &&
                        enter.Contains("fullscreenRestoreWindowState = WindowState", StringComparison.Ordinal) &&
                        enter.Contains("fullscreenRestoreBounds", StringComparison.Ordinal) &&
                        enter.Contains("fullscreenRestoreClientSize = ClientSize", StringComparison.Ordinal) &&
                        enter.Contains("FormBorderStyle = FormBorderStyle.None", StringComparison.Ordinal) &&
                        enter.Contains("Screen.FromControl(this).Bounds", StringComparison.Ordinal) &&
                        exit.Contains("FormBorderStyle = fullscreenRestoreBorderStyle", StringComparison.Ordinal) &&
                        exit.Contains("Bounds = fullscreenRestoreBounds", StringComparison.Ordinal) &&
                        exit.Contains("ClientSize = fullscreenRestoreClientSize", StringComparison.Ordinal) &&
                        exit.Contains("WindowState = fullscreenRestoreWindowState", StringComparison.Ordinal) &&
                        !enter.Contains("TopMost", StringComparison.Ordinal),
            "Rahmen, normale Geometrie oder vorheriger Fensterzustand werden nicht sauber wiederhergestellt.");
        TestAssert.That(source.Contains("if (!fullscreen && !fullscreenTransition", StringComparison.Ordinal) &&
                        source.Contains("if (fullscreen) ExitFullscreen();", StringComparison.Ordinal),
            "Resize-Transitionsschutz oder explizites Verlassen per Tray-Öffnungsart fehlt.");
        return Task.CompletedTask;
    }

    private static string Section(string source, string start, string end)
    {
        var startIndex = source.IndexOf(start, StringComparison.Ordinal);
        var endIndex = source.IndexOf(end, startIndex + start.Length, StringComparison.Ordinal);
        TestAssert.That(startIndex >= 0 && endIndex > startIndex, $"Quellabschnitt fehlt: {start}");
        return source[startIndex..endIndex];
    }
}
