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
            var source = NativeActorBookSource() ?? throw new InvalidOperationException("locked");
            if (message.TryGetProperty("expectedBookSource", out var expectedSource) && expectedSource.GetString() != source)
                throw new InvalidOperationException("source_changed");
            // Detection only proposes a zone. The shared regional writer applies it
            // after the GUI/MCP path has anchored existing timed records durably.
            var result = await TimeZoneManagement.RefreshAsync(paths.RegionalSettings, message.GetProperty("expectedRegional"),
                ct => telefon.ReadOwnTimeZoneAsync(ct), () => NativeActorBookSource() == source,
                backgroundLifetime.Token, apply: false).ConfigureAwait(false);
            result["ok"] = true; result["requestId"] = requestId; result["book_source"] = source;
            await form.SendAsync("App.zeitzonenErgebnis", result).ConfigureAwait(false);
        }
        catch (Exception error)
        {
            await form.SendAsync("App.zeitzonenErgebnis", new { ok = false, requestId,
                code = error.Message == "regional_conflict" ? "conflict" : error.Message == "time_zone_busy" ? "native_busy" : error.Message == "source_changed" ? "source_changed" : error.Message == "locked" ? "locked" : "native_operation_failed" }).ConfigureAwait(false);
        }
    }
}
