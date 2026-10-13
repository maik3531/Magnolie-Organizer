using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private async Task KdeMediaAsync(JsonElement message)
    {
        var requestId = Text(message, "requestId");
        if (!Guid.TryParse(requestId, out _)) return;
        try
        {
            if (!currentPlainTextAvailable) throw new InvalidOperationException("locked");
            JsonObject result;
            var command = Text(message, "cmd");
            if (command == "kde_medien_geraete") result = kdeConnectSms.MediaDevices();
            else if (command == "kde_medien_stand") result = kdeConnectSms.MediaStatus(Text(message, "device_id"));
            else
            {
                long? value = message.TryGetProperty("value", out var number) ? number.GetInt64() : null;
                await kdeConnectSms.MediaCommandAsync(Text(message, "device_id"), Text(message, "token"),
                    Text(message, "player"), Text(message, "action"), value, backgroundLifetime.Token);
                result = new JsonObject { ["state"] = "queued", ["device_id"] = Text(message, "device_id") };
            }
            if (!currentPlainTextAvailable) throw new InvalidOperationException("locked");
            result["ok"] = true; result["requestId"] = requestId;
            await form.SendAsync("App.kdeMedien", result);
        }
        catch (Exception error)
        {
            await form.SendAsync("App.kdeMedien", new { ok = false, requestId, error = error.Message });
        }
    }
}
