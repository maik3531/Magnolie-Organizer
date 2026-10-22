using System.Text.Json;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private async Task DetectTimeZoneAsync(JsonElement message)
    {
        var requestId = Text(message, "requestId");
        if (!Guid.TryParse(requestId, out _)) return;
        try
        {
            if (!currentPlainTextAvailable || disposed || restoreInProgress) throw new InvalidOperationException("locked");
            var result = await TimeZoneManagement.RefreshAsync(paths.RegionalSettings, message.GetProperty("expectedRegional"),
                ct => telefon.ReadOwnTimeZoneAsync(ct), () => currentPlainTextAvailable && !disposed && !restoreInProgress, backgroundLifetime.Token).ConfigureAwait(false);
            result["ok"] = true; result["requestId"] = requestId;
            await form.SendAsync("App.zeitzonenErgebnis", result).ConfigureAwait(false);
        }
        catch (Exception error)
        {
            await form.SendAsync("App.zeitzonenErgebnis", new { ok = false, requestId,
                code = error.Message == "regional_conflict" ? "conflict" : error.Message == "time_zone_busy" ? "native_busy" : error.Message == "locked" ? "locked" : "native_operation_failed" }).ConfigureAwait(false);
        }
    }
}
