using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private async Task KdeInputAsync(JsonElement message)
    {
        var requestId = Text(message, "requestId");
        if (!Guid.TryParse(requestId, out _)) return;
        try
        {
            if (!currentPlainTextAvailable) throw new InvalidOperationException("locked");
            var command = Text(message, "cmd");
            JsonObject result;
            if (command == "kde_input_stand") result = kdeConnectSms.InputStatus();
            else if (command == "kde_input_einstellungen")
            {
                kdeConnectSms.ConfigureInput(message.GetProperty("enabled").GetBoolean(), Text(message, "device_id"));
                result = kdeConnectSms.InputStatus();
            }
            else
            {
                var body = JsonNode.Parse(message.GetProperty("body").GetRawText())!.AsObject();
                await kdeConnectSms.InputSendAsync(Text(message, "device_id"), Text(message, "token"), body, backgroundLifetime.Token);
                result = new JsonObject { ["state"] = "queued" };
            }
            if (!currentPlainTextAvailable) throw new InvalidOperationException("locked");
            result["ok"] = true; result["requestId"] = requestId;
            await form.SendAsync("App.kdeInput", result);
        }
        catch (Exception error)
        {
            await form.SendAsync("App.kdeInput", new { ok = false, requestId, error = error.Message });
        }
    }
}
