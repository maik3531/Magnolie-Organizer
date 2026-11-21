using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private sealed record FileMetadataAttempt(string Kind, JsonObject Message);
    private readonly object fileMetadataGate = new();
    private readonly Dictionary<string, FileMetadataAttempt> fileMetadataAttempts = new(StringComparer.Ordinal);
    private readonly Dictionary<string, JsonObject> fileMetadataReceipts = new(StringComparer.Ordinal);
    private bool fileMetadataRevoked;
    private JsonObject? fileOwnMetadataHistory;

    private const string NativeMediaSupportKind = "media_support.hello";
    internal bool NativeMediaSupportChecked { get; set; } // Private tests only; no setting or advertisement.
    private volatile bool mediaSupportReaderActive;
    private volatile bool mediaSupportRetired;
    private string? mediaSupportId;
    private long mediaSupportStarted;
    private bool mediaSupportOppositeAckWritten;
    private bool mediaSupportAccepted;

    partial void SetNativeMediaSupportReader(bool active)
    {
        if (!active) RetireNativeMediaSupport();
        mediaSupportReaderActive = active;
    }

    private void RetireNativeMediaSupport()
    {
        if (mediaSupportId is not null) mediaSupportRetired = true;
    }

    private bool NativeMediaSupportLifetime => NativeMediaSupportChecked && mediaSupportReaderActive && !mediaSupportRetired &&
        !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 && transport == "wifi" &&
        (mediaSupportAccepted || Environment.TickCount64 - mediaSupportStarted is >= 0 and < 10_000);

    internal bool NativeMediaSupportEstablished => mediaSupportAccepted && NativeMediaSupportLifetime && FileMetadataReady();

    private static bool ValidNativeMediaHello(JsonObject plain, long now)
    {
        if (plain.Count != 7 || plain["type"] is not JsonValue type || !type.TryGetValue<string>(out var frameType) || frameType != "message" ||
            !TelefonProtocolContract.TryInteger(plain["v"], out var version) || version != 1 ||
            plain["message_id"] is not JsonValue idValue || !idValue.TryGetValue<string>(out var id) ||
            !Guid.TryParseExact(id, "D", out var parsed) || id != parsed.ToString("D") || id[14] != '4' || "89ab".IndexOf(id[19]) < 0 ||
            !TelefonProtocolContract.TryInteger(plain["created_ms"], out var created) ||
            !TelefonProtocolContract.TryInteger(plain["expires_ms"], out var expires) || created < 0 || created > now ||
            expires <= now || expires > 253_402_300_799_999L || expires - created > 10_000 || plain["body"] is not JsonObject body ||
            body.Count != 2 || !TelefonProtocolContract.TryInteger(body["format"], out var format) || format != 1) return false;
        return body["feature"] is JsonValue feature && feature.TryGetValue<string>(out var name) && name == "shared_settings";
    }

    partial void RouteNativeMediaSupport(JsonObject plain, ref Task? handling)
    {
        if (NativeMediaSupportChecked && plain["kind"] is JsonValue kind && kind.TryGetValue<string>(out var name) && name == NativeMediaSupportKind)
        {
            handling = ReceiveNativeMediaHelloAsync(plain);
            return;
        }
        if (ConsumePrivateMediaSettingsAck(plain))
        {
            handling = Task.CompletedTask;
            return;
        }
        if (mediaSupportId is null || !JsonNode.DeepEquals(plain["type"], JsonValue.Create("ack")) ||
            !JsonNode.DeepEquals(plain["message_id"], JsonValue.Create(mediaSupportId))) return;
        // Even late receipts belong only to this attempt, never the outbox.
        handling = Task.CompletedTask;
        if (!NativeMediaSupportLifetime || !mediaSupportOppositeAckWritten || !FileMetadataReady() ||
            plain.Count != 4 || !JsonNode.DeepEquals(plain["status"], JsonValue.Create("accepted")) ||
            !JsonNode.DeepEquals(plain["error"], JsonValue.Create("none"))) RetireNativeMediaSupport();
        else mediaSupportAccepted = true;
    }

    private async Task ReceiveNativeMediaHelloAsync(JsonObject plain)
    {
        var now = Now();
        if (!mediaSupportReaderActive || transport != "wifi" || mediaSupportId is not null ||
            !ValidNativeMediaHello(plain, now) || !FileMetadataReady()) return;
        mediaSupportStarted = Environment.TickCount64;
        mediaSupportId = Guid.NewGuid().ToString("D");
        var offer = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = mediaSupportId,
            ["kind"] = NativeMediaSupportKind, ["created_ms"] = now, ["expires_ms"] = now + 10_000,
            ["body"] = new JsonObject { ["format"] = 1, ["feature"] = "shared_settings" } };
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = plain["message_id"]!.DeepClone(),
            ["status"] = "accepted", ["error"] = "none" };
        try
        {
            if (await SendNativeMediaSupportFrameAsync(offer) && FileMetadataReady() && await SendNativeMediaSupportFrameAsync(ack) &&
                NativeMediaSupportLifetime && FileMetadataReady()) mediaSupportOppositeAckWritten = true;
            else RetireNativeMediaSupport();
        }
        catch { RetireNativeMediaSupport(); throw; }
    }

    private async Task<bool> SendNativeMediaSupportFrameAsync(JsonObject frame)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(10));
        await writer.WaitAsync(deadline.Token);
        try
        {
            // Check native metadata before acquiring the writer, never from
            // its gate. Retirement/connection lifetime can only deny here.
            if (!NativeMediaSupportLifetime) return false;
            await TelefonCoordinator.WriteFrameAsync(stream, Seal(frame), deadline.Token);
            lastSentMs = Now();
            return true;
        }
        catch { stream.Dispose(); throw; }
        finally { writer.Release(); }
    }

    private static bool IsFileMetadata(string? kind) => kind is
        "capabilities.update" or "grants.update" or "personal_sync.settings";

    partial void BeginFileMetadataReceipt(JsonObject message, ref object? attempt)
    {
        var kind = message["kind"]?.GetValue<string>();
        if (!IsFileMetadata(kind)) return;
        RetireNativeMediaSupport();
        InvalidateMediaSharedReceipts();
        var current = new FileMetadataAttempt(kind!, message.DeepClone().AsObject());
        lock (fileMetadataGate)
        {
            // Invalidate BEFORE processing or attempting the secure ACK. A
            // failed write must not leave a previous positive receipt current.
            fileMetadataReceipts.Remove(kind!);
            fileMetadataAttempts[kind!] = current;
        }
        attempt = current;
        CloseNativeSourceStatus("file_sources_native_metadata_changed");
        CloseNativeSourceCommands("file_sources_native_metadata_changed");
        CloseNativeMediaData("file_receive_native_metadata_changed");
    }

    private bool FileMetadataChannelCurrent(TelefonPeer? current)
    {
        var valid = !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 &&
            store.Enabled && !store.RestoreFenced && current is not null && current.State == "paired" && current.Id == peer.Id &&
            current.PublicKey.SequenceEqual(peer.PublicKey) &&
            current.FilePairingEpoch == peer.FilePairingEpoch && transport is "wifi" or "bluetooth";
        lock (fileMetadataGate)
        {
            if (!valid) { fileMetadataRevoked = true; fileMetadataReceipts.Clear(); }
            return valid && !fileMetadataRevoked;
        }
    }

    private static bool FileMetadataMatches(string kind, JsonObject body, TelefonPeer current) => kind switch
    {
        "capabilities.update" => TelefonProtocolContract.Integer(body["revision"]) == current.CapabilityRevision &&
            JsonNode.DeepEquals(body["items"], current.Capabilities),
        "grants.update" => TelefonProtocolContract.Integer(body["revision"]) == current.GrantRevision &&
            JsonNode.DeepEquals(body["grants"], current.Grants),
        "personal_sync.settings" => body.Count == 2 && body["format"]?.GetValue<int>() == 1 &&
            body["own_device"]?.GetValue<bool>() == true,
        _ => false
    };

    partial void ObserveFileMetadataWithdrawal(JsonObject message, TelefonAck ack, object? attempt)
    {
        if (attempt is not FileMetadataAttempt captured || captured.Kind != "personal_sync.settings" ||
            ack.Status is not ("accepted" or "duplicate") || ack.Error != "none" ||
            !JsonNode.DeepEquals(captured.Message, message) || !store.ReceivedMatches(peer.Id, message) ||
            captured.Message["body"]?["own_device"]?.GetValue<bool>() != false) return;
        lock (fileMetadataGate)
        {
            // A validated withdrawal takes effect even when secure ACK output
            // fails. A replay of an older positive own-device message cannot
            // undo it; reconsent must be a fresh native control message.
            fileOwnMetadataHistory = captured.Message;
            fileMetadataReceipts.Remove(captured.Kind);
        }
    }

    partial void CompleteFileMetadataReceipt(JsonObject message, TelefonAck ack, object? attempt)
    {
        if (attempt is not FileMetadataAttempt captured || ack.Status is not ("accepted" or "duplicate") ||
            ack.Error != "none" || ack.MessageId != captured.Message["message_id"]?.GetValue<string>() ||
            !JsonNode.DeepEquals(captured.Message, message) || !store.ReceivedMatches(peer.Id, message)) return;
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(current) ||
            !FileMetadataMatches(captured.Kind, captured.Message["body"]!.AsObject(), current!)) return;
        lock (fileMetadataGate)
        {
            if (captured.Kind == "personal_sync.settings" && !ack.Process && fileOwnMetadataHistory is not null &&
                !JsonNode.DeepEquals(fileOwnMetadataHistory, captured.Message)) return;
            if (!fileMetadataRevoked && fileMetadataAttempts.TryGetValue(captured.Kind, out var latest) && ReferenceEquals(latest, captured))
            {
                fileMetadataReceipts[captured.Kind] = captured.Message["body"]!.DeepClone().AsObject();
                if (captured.Kind == "personal_sync.settings") fileOwnMetadataHistory = captured.Message;
            }
        }
    }

    // Read-only current-channel metadata witness. Neither data handlers, local
    // consent, OS READ nor a file-control echo is supplied by this predicate.
    internal bool FileMetadataReady(bool videos = false, bool forLegacyActivation = false)
    {
        KeyValuePair<string, JsonObject>[] receipts;
        lock (fileMetadataGate) receipts = fileMetadataReceipts.ToArray();
        if (receipts.Length != 3) return false;
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(current)) return false;
        if (!forLegacyActivation && !NativeFilePairingIdentity.Hash(current!.FilePairingEpoch)) return false;
        var personal = store.PersonalSettings(peer.Id);
        if (!personal.OwnDevice || !personal.RemoteOwnDevice) return false;
        foreach (var receipt in receipts)
            if (!FileMetadataMatches(receipt.Key, receipt.Value, current!))
            {
                lock (fileMetadataGate)
                    if (fileMetadataReceipts.TryGetValue(receipt.Key, out var actual) && ReferenceEquals(actual, receipt.Value))
                        fileMetadataReceipts.Remove(receipt.Key);
                return false;
            }
        var status = current!.Capabilities["device_status"] as JsonObject;
        if (status?["available"]?.GetValue<bool>() != true || status["versions"] is not JsonArray versions ||
            !versions.Any(value => TelefonProtocolContract.TryInteger(value, out var number) && number == 21) ||
            videos && !versions.Any(value => TelefonProtocolContract.TryInteger(value, out var number) && number == 22)) return false;
        // Protected I/O above does not hold this monitor. Recheck exact receipt
        // objects and session lifetime so a concurrent withdrawal wins.
        var after = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(after) || receipts.Any(value => !FileMetadataMatches(value.Key, value.Value, after!))) return false;
        lock (fileMetadataGate)
            return !fileMetadataRevoked && !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 &&
                receipts.All(value => fileMetadataReceipts.TryGetValue(value.Key, out var actual) && ReferenceEquals(actual, value.Value));
    }
}
