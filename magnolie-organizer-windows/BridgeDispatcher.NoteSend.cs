using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private NoteSendJobs? noteSendJobs;
    private NoteSendSettings ReadNoteSendSettings()
    {
        if (disposed || !currentPlainTextAvailable || (!string.IsNullOrEmpty(currentEnvelope) && encryption.Session is null))
            throw new NoteSendException("locked");
        using var document = JsonDocument.Parse(Volatile.Read(ref currentPlainText));
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("einstellungen", out var settings) ||
            settings.ValueKind != JsonValueKind.Object || !settings.TryGetProperty("versand", out var sending)) return new(false, "");
        return NoteSendTransport.Settings(sending);
    }
    private async Task NoteSendAsync(JsonElement message)
    {
        var requestId = Text(message, "requestId");
        try
        {
            if (!Guid.TryParseExact(requestId, "D", out _)) throw new NoteSendException("invalid_selection");
            var request = message.GetProperty("request");
            if (request.ValueKind != JsonValueKind.Object) throw new NoteSendException("invalid_selection");
            noteSendJobs ??= new NoteSendJobs(Path.Combine(paths.Root, "Versand"), ReadNoteSendSettings, form.CreateNotePdfAsync);
            var result = new JsonObject { ["ok"] = true, ["requestId"] = requestId };
            switch (Text(request, "action"))
            {
                case "read": result["state"] = noteSendJobs.Read(); break;
                case "begin":
                    result["job"] = noteSendJobs.Begin(Text(request, "html"), Text(request, "kind"), Text(request, "recipient"),
                        Text(request, "subject"), Text(request, "expectedRevision"), Text(request, "operationId")); break;
                case "status": result["job"] = noteSendJobs.Status(Text(request, "operationId")); break;
                case "cancel": result["job"] = noteSendJobs.Cancel(Text(request, "operationId")); break;
                default: throw new NoteSendException("invalid_selection");
            }
            await form.SendAsync("App.noteSendErgebnis", result);
        }
        catch (NoteSendException error)
        {
            await form.SendAsync("App.noteSendErgebnis", new { requestId, ok = false, code = error.Code, nativeOutcomeUnknown = error.Dispatched });
        }
        catch (Exception)
        {
            await form.SendAsync("App.noteSendErgebnis", new { requestId, ok = false, code = "native_operation_failed", nativeOutcomeUnknown = true });
        }
    }
}
