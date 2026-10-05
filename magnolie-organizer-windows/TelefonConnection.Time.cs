using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private JsonObject? sentTimePolicy, receivedTimePolicy;
    internal CancellationToken TimeCancellation => cancellation;

    internal bool TimeControlsReady
    {
        get
        {
            if (disposed || cancellation.IsCancellationRequested || store.RestoreFenced || store.TimePolicyFailed(peer.Id) ||
                !freshCapabilities || !freshGrants || !freshOwnSettings) return false;
            var current = store.LoadPeers().FirstOrDefault(value => value.Id == peer.Id &&
                value.State == "paired" && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !store.TimeSupported(peer.Id)) return false;
            var personal = store.PersonalSettings(peer.Id);
            return personal.OwnDevice && personal.RemoteOwnDevice;
        }
    }

    internal bool TimeAllowed(JsonObject body, bool outgoing)
    {
        if (!TimeControlsReady) return false;
        try
        {
            var policies = store.TimeSettings(peer.Id);
            if (sentTimePolicy is null || receivedTimePolicy is null ||
                !JsonNode.DeepEquals(sentTimePolicy, policies["local"]) ||
                !JsonNode.DeepEquals(receivedTimePolicy, policies["remote"])) return false;
            if (body["trigger"]?.GetValue<string>() == "auto_wifi" && transport != "wifi") return false;
            return store.TimePolicyAllowed(peer.Id, body, outgoing);
        }
        catch (InvalidOperationException) { return false; }
    }

    internal async Task SendTimeSettingsAsync(bool force = false)
    {
        var queued = false;
        await store.NotePolicyGate.WaitAsync(cancellation);
        try
        {
            if (!TimeControlsReady) return;
            var settings = store.TimeSettings(peer.Id);
            var local = settings["local"] as JsonObject ?? TimeSyncContract.NewSettings();
            if (settings["local"] is null) store.SetTimeSettings(peer.Id, local);
            if (force || !JsonNode.DeepEquals(sentTimePolicy, local))
            {
                store.Enqueue(peer.Id, TimeSyncContract.Settings, local, 86_400_000, Now());
                queued = true;
            }
        }
        finally { store.NotePolicyGate.Release(); }
        if (queued) await PumpOutboxAsync();
    }

    private async Task HandleTimeMessageAsync(JsonObject message)
    {
        var now = Now();
        TelefonMessageContract.ValidateMessage(message, now, true);
        var kind = message["kind"]!.GetValue<string>(); var body = message["body"]!.AsObject();
        var ack = store.CommitIncoming(peer.Id, message, now,
            (_, value) => TimeControlsReady && (kind == TimeSyncContract.Settings || TimeAllowed(value, false))
                ? null : "not_granted", deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        try
        {
            if (kind == TimeSyncContract.Settings && ack.Status is "accepted" or "duplicate")
            {
                await store.NotePolicyGate.WaitAsync(cancellation);
                try
                {
                    if (!TimeControlsReady) throw new InvalidOperationException("not_granted");
                    store.SetTimeSettings(peer.Id, body, true);
                    receivedTimePolicy = body.DeepClone().AsObject();
                }
                finally { store.NotePolicyGate.Release(); }
                await SendTimeSettingsAsync();
                if (ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
                await receive(peer, message);
            }
            else if (ack.Process)
            {
                var result = await receive(peer, message);
                if (result is not null) ack = result;
                if (ack.Status == "accepted" && ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
            }
        }
        catch (TimeoutException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (IOException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (InvalidOperationException) { ack = new TelefonAck(ack.MessageId, "rejected", "not_granted"); }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId,
            ["status"] = ack.Status, ["error"] = ack.Error });
    }
}
