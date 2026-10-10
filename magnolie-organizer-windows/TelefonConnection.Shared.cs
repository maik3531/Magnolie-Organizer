using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private JsonObject? sentSharedSettings, receivedSharedSettings;
    internal Func<JsonObject> SharedLocalCapabilities { get; set; } = () => TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject();

    private bool SharedControlsReady
    {
        get
        {
            if (disposed || cancellation.IsCancellationRequested || store.RestoreFenced ||
                !freshCapabilities || !freshGrants || !freshOwnSettings) return false;
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id &&
                value.State == "paired" && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !SharedSyncSettings.Supported(SharedLocalCapabilities(), current.Capabilities)) return false;
            var settings = store.PersonalSettings(peer.Id);
            return settings.OwnDevice && settings.RemoteOwnDevice;
        }
    }

    internal bool SharedSettingsReady
    {
        get
        {
            if (!SharedControlsReady) return false;
            var current = store.SharedSettings(peer.Id, peer.PublicKey);
            return current is not null && JsonNode.DeepEquals(current, sentSharedSettings) && JsonNode.DeepEquals(current, receivedSharedSettings);
        }
    }

    internal async Task SendSharedSettingsAsync()
    {
        var queued = false;
        await store.NotePolicyGate.WaitAsync(cancellation);
        try
        {
            if (!SharedControlsReady) return;
            var current = store.SharedSettings(peer.Id, peer.PublicKey);
            // The UI/controller must initialize current choices explicitly; do not
            // silently replace existing preferences with defaults on connection.
            if (current is null || JsonNode.DeepEquals(current, sentSharedSettings)) return;
            store.Enqueue(peer.Id, SharedSyncSettings.Kind, current, 86_400_000, Now()); queued = true;
        }
        finally { store.NotePolicyGate.Release(); }
        if (queued) await PumpOutboxAsync();
    }

    private async Task HandleSharedSettingsAsync(JsonObject message)
    {
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var body = message["body"]!.AsObject();
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => SharedControlsReady ? null : "not_granted",
            deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        try
        {
            if (ack.Status is "accepted" or "duplicate")
            {
                await store.NotePolicyGate.WaitAsync(cancellation);
                try
                {
                    if (!SharedControlsReady) throw new InvalidOperationException("not_granted");
                    if (store.SharedSettings(peer.Id, peer.PublicKey) is null)
                        throw new IOException("Local shared preferences have not been initialized.");
                    store.MergeSharedSettings(peer.Id, peer.PublicKey, body);
                    receivedSharedSettings = body.DeepClone().AsObject();
                    if (ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
                }
                finally { store.NotePolicyGate.Release(); }
                await SendSharedSettingsAsync();
            }
        }
        catch (InvalidDataException) { ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema"); }
        catch (IOException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (InvalidOperationException) { ack = new TelefonAck(ack.MessageId, "rejected", "not_granted"); }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
    }
}
