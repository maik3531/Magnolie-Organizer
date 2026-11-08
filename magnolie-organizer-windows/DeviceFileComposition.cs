using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Refs #433: optional media code joins the ordinary connection only when this
// composition is compiled. Without it, reserved frames stay reserved and queued
// settings stay queued; no legacy receive path or permission is substituted.
internal sealed partial class TelefonCoordinator
{
    partial void ConfigureNativeMediaConnection(TelefonPeer peer, TelefonConnection connection)
    {
        connection.MediaPreferencesChanged = () => NativeMediaSharedPreferencesChangedAsync(peer.Id, connection);
        connection.MediaManualRequested = (settings, requestId, deadline, token) =>
            StartNativeMediaManualRequest(peer.Id, connection, settings, requestId, deadline, token);
    }
}

internal sealed partial class TelefonConnection
{
    partial void ReceiveNativeMediaSettings(JsonObject message, ref Task? handling)
        => handling = message["kind"]?.GetValue<string>() == MediaSyncSettings.StartKind
            ? HandleMediaManualRequestAsync(message) : HandleMediaSharedSettingsAsync(message);

    partial void ObserveNativeMediaAck(string id, string status, string error, JsonObject? queued, ref Task? handling)
    {
        ObserveMediaSharedAck(id, status, error, queued);
        if (queued?["kind"]?.GetValue<string>() == MediaSyncSettings.Kind && MediaPreferencesChanged is not null)
            handling = MediaPreferencesChanged();
    }

    partial void SendNativeMediaSettings(ref Task? handling) => handling = SendMediaSharedSettingsAsync();
    partial void SendNativeMediaQueuedSettings(TelefonQueuedMessage item, JsonObject body, long now, ref Task? handling)
        => handling = SendQueuedMediaSettingsAsync(item, body, now);
}
