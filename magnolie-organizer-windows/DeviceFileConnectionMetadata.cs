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

    private static bool IsFileMetadata(string? kind) => kind is
        "capabilities.update" or "grants.update" or "personal_sync.settings";

    partial void BeginFileMetadataReceipt(JsonObject message, ref object? attempt)
    {
        var kind = message["kind"]?.GetValue<string>();
        if (!IsFileMetadata(kind)) return;
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
    }

    private bool FileMetadataChannelCurrent(TelefonPeer? current)
    {
        var valid = !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 &&
            store.Enabled && !store.RestoreFenced && current is not null && current.State == "paired" && current.Id == peer.Id &&
            current.PublicKey.SequenceEqual(peer.PublicKey) && NativeFilePairingIdentity.Hash(peer.FilePairingEpoch) &&
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
    internal bool FileMetadataReady(bool videos = false)
    {
        KeyValuePair<string, JsonObject>[] receipts;
        lock (fileMetadataGate) receipts = fileMetadataReceipts.ToArray();
        if (receipts.Length != 3) return false;
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(current)) return false;
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
