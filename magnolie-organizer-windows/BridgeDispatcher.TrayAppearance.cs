using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly TrayVisualTest trayVisualTest = new();
    private string? trayDeveloperSnapshot;
    private bool trayDeveloperSaved;
    private bool SavedTrayDeveloperMode()
    {
        if (!currentPlainTextAvailable || disposed) return false;
        if (!ReferenceEquals(trayDeveloperSnapshot, currentPlainText))
        {
            trayDeveloperSnapshot = currentPlainText;
            trayDeveloperSaved = TrayVisualTest.SavedDeveloperMode(currentPlainText, currentPlainTextAvailable);
        }
        return trayDeveloperSaved;
    }
    internal bool TrayVisualTestActive => trayVisualTest.HasLease;
    internal TrayAppearanceState? CurrentTrayVisualTest()
        => trayVisualTest.Current(SavedTrayDeveloperMode(), currentPlainText, Environment.TickCount64);
    private async Task HandleTrayVisualTestAsync(JsonElement message, bool clear)
    {
        var ok = false;
        try
        {
            if (clear) trayVisualTest.Clear();
            else trayVisualTest.Start(message, SavedTrayDeveloperMode(), currentPlainText, Environment.TickCount64);
            ok = true;
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or KeyNotFoundException) { trayVisualTest.Clear(); }
        form.QueueTrayAppearanceRefresh();
        await form.SendAsync("App.trayDarstellungTestStand", new { ok, active = !clear && ok, seconds = !clear && ok ? 60 : 0 });
    }
}
