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

    // Original private reader only; this does not publish an intent to any
    // gallery worker, UI, personal outbox or legacy media composition.
    private readonly Dictionary<string, JsonObject> privateMediaIncoming = new(StringComparer.Ordinal);
    private readonly HashSet<string> privateMediaOutgoing = new(StringComparer.Ordinal);
    private (string Id, JsonObject Body)? privateMediaPending;
    private JsonObject? privateMediaSent, privateMediaAcknowledged, privateMediaReceived;
    private bool privateMediaSettingsFailed;
    private const int PrivateMediaMaxMessages = 128;

    private bool PrivateMediaSettingsSelected => NativeMediaSupportChecked && !LegacyMediaSettingsAdvertised;
    private bool PrivateMediaSettingsReady => !privateMediaSettingsFailed && NativeMediaSupportEstablished && PrivateMediaSettingsSelected;

    internal bool PrivateMediaSettingsMatched => PrivateMediaSettingsReady &&
        store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey) is { } local &&
        JsonNode.DeepEquals(local, privateMediaSent) && JsonNode.DeepEquals(local, privateMediaReceived) &&
        JsonNode.DeepEquals(local, privateMediaAcknowledged);

    private bool ConsumePrivateMediaSettingsAck(JsonObject plain)
    {
        if (!JsonNode.DeepEquals(plain["type"], JsonValue.Create("ack")) || plain["message_id"] is not JsonValue idValue ||
            !idValue.TryGetValue<string>(out var id) || !privateMediaOutgoing.Contains(id)) return false;
        TelefonProtocolContract.ValidateAck(plain);
        if (privateMediaPending is { } attempted && attempted.Id == id && PrivateMediaSettingsReady)
        {
            privateMediaPending = null;
            privateMediaAcknowledged = plain["status"]?.GetValue<string>() is "accepted" or "duplicate" &&
                plain["error"]?.GetValue<string>() == "none" ? attempted.Body : null;
        }
        return true;
    }

    private async Task ReceivePrivateMediaSettingsAsync(JsonObject message)
    {
        TelefonMessageContract.ValidateMessage(message, Now(), true);
        var id = message["message_id"]!.GetValue<string>();
        var body = message["body"]!.AsObject();
        var status = "accepted";
        var error = "none";
        try
        {
            if (!PrivateMediaSettingsReady) return;
            if (privateMediaIncoming.TryGetValue(id, out var previous))
            {
                if (!JsonNode.DeepEquals(previous, message)) throw new InvalidDataException("media_shared_equivocation");
                status = "duplicate";
            }
            else if (privateMediaIncoming.Count >= PrivateMediaMaxMessages) throw new InvalidOperationException("media_shared_session_capacity");
            store.MergeNativeMediaSharedSettings(peer.Id, peer.PublicKey, body);
        }
        catch (InvalidDataException) { error = "invalid_schema"; }
        catch (Exception ex) when (ex is IOException or CryptographicException) { error = "temporary_failure"; }
        catch (PlatformNotSupportedException) { error = "not_granted"; }
        catch (InvalidOperationException) { error = "not_granted"; }
        if (!PrivateMediaSettingsReady) return;
        try
        {
            if (!await SendNativeMediaSupportFrameAsync(new JsonObject { ["type"] = "ack", ["message_id"] = id,
                ["status"] = error == "none" ? status : "rejected", ["error"] = error }) || error != "none" || !PrivateMediaSettingsReady)
            { privateMediaSettingsFailed = true; return; }
            privateMediaIncoming[id] = message.DeepClone().AsObject();
            privateMediaReceived = body.DeepClone().AsObject();
            var current = store.ReadNativeMediaSharedSettings(peer.Id, peer.PublicKey);
            if (current is null || JsonNode.DeepEquals(current, privateMediaSent)) return;
            if (privateMediaOutgoing.Count >= PrivateMediaMaxMessages) { privateMediaSettingsFailed = true; return; }
            var now = Now();
            var outgoingId = Guid.NewGuid().ToString("D");
            var echo = new JsonObject { ["type"] = "message", ["v"] = 1, ["kind"] = MediaSyncSettings.Kind,
                ["message_id"] = outgoingId, ["created_ms"] = now, ["expires_ms"] = now + 86_400_000, ["body"] = current.DeepClone() };
            privateMediaOutgoing.Add(outgoingId);
            if (!PrivateMediaSettingsReady || !await SendNativeMediaSupportFrameAsync(echo) || !PrivateMediaSettingsReady)
            { privateMediaSettingsFailed = true; return; }
            privateMediaPending = (outgoingId, current);
            privateMediaSent = current;
            privateMediaAcknowledged = null;
        }
        catch { privateMediaSettingsFailed = true; throw; }
    }

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

    private bool LegacyMediaSettingsAdvertised => MediaSettingsAdvertised(SharedLocalCapabilities()) &&
        MediaSettingsAdvertised(store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id)?.Capabilities);

    internal bool MediaSharedControlsReady => FileMetadataReady() && LegacyMediaSettingsAdvertised;

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
