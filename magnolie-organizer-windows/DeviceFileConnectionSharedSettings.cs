using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private readonly object mediaSharedGate = new();
    private readonly Dictionary<string, JsonObject> mediaSharedAttempts = new(StringComparer.Ordinal);
    private JsonObject? mediaSharedSent, mediaSharedAcknowledged, mediaSharedReceived;
    private long mediaSharedGeneration;
    internal Func<Task>? MediaPreferencesChanged { get; set; }
    internal Action<JsonObject, string, long, CancellationToken>? MediaManualRequested { get; set; }

    private async Task HandleMediaManualRequestAsync(JsonObject message)
    {
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var settings = message["body"]!["settings"]!.AsObject();
        var deadline = message["expires_ms"]!.GetValue<long>();
        var startWorker = MediaManualRequested;
        bool Ready() => startWorker is not null && MediaSharedSettingsReady &&
            deadline > Now() &&
            JsonNode.DeepEquals(settings, store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey)) &&
            (MediaSyncSettings.RequestedFor(settings, "images") || MediaSyncSettings.RequestedFor(settings, "video"));
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => Ready() ? null : "not_granted",
            deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        if (ack.Status is "accepted" or "duplicate" && !Ready()) ack = new TelefonAck(ack.MessageId, "rejected", "not_granted");
        var start = ack.Process && ack.Status == "accepted";
        if (start) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
        // Schedule only after successful secure ACK. The receive loop must stay
        // free to process the real source controls/data/Saved/END responses.
        if (start)
        {
            if (deadline <= Now()) await SendMediaManualResultAsync(ack.MessageId, "held");
            else startWorker!(settings.DeepClone().AsObject(), ack.MessageId, deadline, cancellation);
        }
    }

    internal Task SendMediaManualResultAsync(string requestId, string state)
    {
        var body = new JsonObject { ["format"] = 1, ["request_id"] = requestId, ["state"] = state };
        MediaSyncSettings.ValidateResult(body);
        var now = Now();
        return SendPlainAsync(new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = MediaSyncSettings.ResultKind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body });
    }

    private static bool MediaSettingsAdvertised(JsonObject? capabilities) =>
        capabilities?["device_status"] is JsonObject status && status["available"]?.GetValue<bool>() == true &&
        status["versions"] is JsonArray versions && versions.Any(value => TelefonProtocolContract.Integer(value) == MediaSyncSettings.DiscoveryVersion);

    internal bool MediaSharedControlsReady => FileMetadataReady() &&
        MediaSettingsAdvertised(SharedLocalCapabilities()) &&
        MediaSettingsAdvertised(store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id)?.Capabilities);

    private void InvalidateMediaSharedReceipts()
    {
        lock (mediaSharedGate)
        {
            mediaSharedGeneration++;
            mediaSharedAttempts.Clear(); mediaSharedSent = null;
            mediaSharedAcknowledged = null; mediaSharedReceived = null;
        }
        CheckNativeMediaSendControl();
    }

    internal bool MediaSharedSettingsReady
    {
        get
        {
            if (!MediaSharedControlsReady) return false;
            var body = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
            lock (mediaSharedGate) return body is not null && JsonNode.DeepEquals(body, mediaSharedSent) &&
                JsonNode.DeepEquals(body, mediaSharedAcknowledged) && JsonNode.DeepEquals(body, mediaSharedReceived);
        }
    }

    internal async Task SendMediaSharedSettingsAsync()
    {
        if (!MediaSharedControlsReady) return;
        var current = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
        if (current is null) return;
        lock (mediaSharedGate) if (JsonNode.DeepEquals(current, mediaSharedSent)) return;
        store.Enqueue(peer.Id, MediaSyncSettings.Kind, current, 86_400_000, Now());
        await PumpOutboxAsync();
    }

    private async Task SendQueuedMediaSettingsAsync(TelefonQueuedMessage item, JsonObject body, long now)
    {
        if (!MediaSharedControlsReady) return;
        if (!JsonNode.DeepEquals(body, store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey)))
        { store.CompleteOutbox(peer.Id, item.Id); return; }
        long generation;
        lock (mediaSharedGate)
        {
            generation = mediaSharedGeneration;
            // Outbox replacement permits only one current snapshot per peer.
            mediaSharedAttempts.Clear(); mediaSharedAttempts[item.Id] = body.DeepClone().AsObject();
        }
        try
        {
            await SendPlainAsync(item.Message);
            if (!MediaSharedControlsReady) { InvalidateMediaSharedReceipts(); return; }
            lock (mediaSharedGate)
                if (generation == mediaSharedGeneration) mediaSharedSent = body.DeepClone().AsObject();
            store.MarkAttempt(item.Id, item.Attempts, now);
        }
        catch { InvalidateMediaSharedReceipts(); throw; }
    }

    private void ObserveMediaSharedAck(string id, string status, string error, JsonObject? queued)
    {
        if (queued?["kind"]?.GetValue<string>() != MediaSyncSettings.Kind) return;
        if (!MediaSharedControlsReady) { InvalidateMediaSharedReceipts(); return; }
        lock (mediaSharedGate)
        {
            if (!mediaSharedAttempts.Remove(id, out var attempted)) return;
            mediaSharedAcknowledged = status is "accepted" or "duplicate" && error == "none" &&
                JsonNode.DeepEquals(attempted, queued["body"]) ? attempted : null;
        }
    }

    private async Task HandleMediaSharedSettingsAsync(JsonObject message)
    {
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var body = message["body"]!.AsObject();
        long generation;
        lock (mediaSharedGate) generation = mediaSharedGeneration;
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => MediaSharedControlsReady ? null : "not_granted",
            deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        try
        {
            if (ack.Status is "accepted" or "duplicate")
            {
                if (!MediaSharedControlsReady) throw new InvalidOperationException("not_granted");
                // Protected merge and readback precede the echo and secure ACK.
                store.MergeNativeMediaSharedSettings(peer.Id, peer.PublicKey, body);
                if (!MediaSharedControlsReady) throw new InvalidOperationException("not_granted");
                if (ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
            }
        }
        catch (InvalidDataException) { ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema"); }
        catch (CryptographicException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (IOException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (InvalidOperationException) { ack = new TelefonAck(ack.MessageId, "rejected", "not_granted"); }
        try
        {
            await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
            if (ack.Status is "accepted" or "duplicate" && MediaSharedControlsReady)
            {
                lock (mediaSharedGate)
                    if (generation == mediaSharedGeneration) mediaSharedReceived = body.DeepClone().AsObject();
                await SendMediaSharedSettingsAsync();
                if (MediaPreferencesChanged is not null) await MediaPreferencesChanged();
            }
            else InvalidateMediaSharedReceipts();
        }
        catch { InvalidateMediaSharedReceipts(); throw; }
    }
}
