using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly object drawingGate = new();
    private readonly Queue<KdeDigitizerFrame> drawingFrames = new();
    private bool drawingDraining;

    private async Task ConfigureDrawingInputAsync(JsonElement message)
    {
        var token = Text(message, "token");
        try
        {
            var enabled = message.GetProperty("enabled").GetBoolean();
            if (enabled && !currentPlainTextAvailable) throw new InvalidOperationException("locked");
            kdeConnectSms.SetDigitizerTarget(Text(message, "device_id"), token, enabled);
            lock (drawingGate) drawingFrames.Clear();
            await form.SendAsync("App.zeichenEingabeStand", new { ok = true, token, enabled });
        }
        catch (Exception)
        {
            await form.SendAsync("App.zeichenEingabeStand", new { ok = false, token, enabled = false });
        }
    }

    private void HandleKdeDigitizer(KdeDigitizerFrame frame)
    {
        if (disposed || !currentPlainTextAvailable) { kdeInstance?.StopDigitizer(); return; }
        var start = false;
        lock (drawingGate)
        {
            if (drawingFrames.Count >= 128)
            {
                drawingFrames.Clear(); kdeInstance?.StopDigitizer();
                frame = frame with { Stopped = true, Sample = new JsonObject { ["active"] = false, ["touching"] = false } };
            }
            drawingFrames.Enqueue(frame);
            if (!drawingDraining) { drawingDraining = true; start = true; }
        }
        if (start) _ = SafeBackgroundAsync(DrainDrawingInputAsync);
    }

    private async Task DrainDrawingInputAsync()
    {
        try
        {
            while (!disposed && !backgroundLifetime.IsCancellationRequested)
            {
                await Task.Delay(16, backgroundLifetime.Token);
                KdeDigitizerFrame[] frames;
                lock (drawingGate)
                {
                    if (drawingFrames.Count == 0) { drawingDraining = false; return; }
                    frames = drawingFrames.ToArray(); drawingFrames.Clear();
                }
                if (!currentPlainTextAvailable) { kdeInstance?.StopDigitizer(); continue; }
                foreach (var group in frames.GroupBy(frame => (frame.DeviceId, frame.Token)))
                {
                    var payload = new
                    {
                        device_id = group.Key.DeviceId, token = group.Key.Token,
                        stopped = group.Any(frame => frame.Stopped), events = group.Select(frame => frame.Sample).ToArray()
                    };
                    await form.SendAsync("App.zeichenEingabe", payload, () =>
                    {
                        if (currentPlainTextAvailable && form.Visible && form.WindowState != FormWindowState.Minimized) return payload;
                        kdeInstance?.StopDigitizer();
                        return new { device_id = group.Key.DeviceId, token = group.Key.Token, stopped = true, events = Array.Empty<JsonObject>() };
                    });
                }
            }
        }
        catch (Exception) { kdeInstance?.StopDigitizer(); }
        lock (drawingGate) { drawingFrames.Clear(); drawingDraining = false; }
    }
}
