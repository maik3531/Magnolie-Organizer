using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private sealed record FileMetadataAttempt(string Kind, JsonObject Message, JsonObject? Previous);
    private readonly object fileMetadataGate = new();
    private readonly Dictionary<string, FileMetadataAttempt> fileMetadataAttempts = new(StringComparer.Ordinal);
    private readonly Dictionary<string, JsonObject> fileMetadataReceipts = new(StringComparer.Ordinal);
    private bool fileMetadataRevoked;
    private JsonObject? fileOwnMetadataHistory;

    private const string NativeMediaSupportKind = "media_support.hello";
    private const string PcImageBatchSupport = "pc_image_batch_v3";
    internal bool NativeMediaSupportChecked { get; set; } // Explicit native composition.
    internal bool NativePcImageBatchChecked { get; set; } // Set only alongside the native sender.
    private sealed class PcImageBatchProbe(string id, long started, long expires)
    {
        internal readonly string Id = id;
        internal readonly long Started = started, Expires = expires;
        internal bool OppositeAckWritten;
        internal volatile bool Accepted, Retired;
    }
    private volatile PcImageBatchProbe? pcImageBatchProbe;
    private volatile bool mediaSupportReaderActive;
    private volatile bool mediaSupportRetired;
    private string? mediaSupportId;
    private long mediaSupportStarted, mediaSupportExpires;
    private (JsonObject Frame, long Received)? earlyMediaHello;
    private bool mediaSupportOppositeAckWritten;
    private volatile bool mediaSupportAccepted;

    partial void SetNativeMediaSupportReader(bool active)
    {
        if (!active) { earlyMediaHello = null; RetireNativeMediaSupport(); }
        mediaSupportReaderActive = active;
    }

    private void RetireNativeMediaSupport()
    {
        if (mediaSupportId is not null) mediaSupportRetired = true;
    }

    private bool NativeMediaSupportLifetime => NativeMediaSupportChecked && mediaSupportReaderActive && !mediaSupportRetired &&
        !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 && transport == "wifi" &&
        (mediaSupportAccepted || Now() < mediaSupportExpires && Environment.TickCount64 - mediaSupportStarted is >= 0 and < 10_000);

    internal bool NativeMediaSupportEstablished => mediaSupportAccepted && NativeMediaSupportLifetime && FileMetadataReady();

    private bool PcImageBatchLifetime(PcImageBatchProbe probe) =>
        NativePcImageBatchChecked && mediaSupportAccepted && NativeMediaSupportLifetime && !probe.Retired &&
        (probe.Accepted || Now() < probe.Expires && Environment.TickCount64 - probe.Started is >= 0 and < 10_000);

    internal Func<bool>? CapturePrivatePcImageDiscovery()
    {
        if (pcImageBatchProbe is not { Accepted: true } probe) return null;
        bool Current() => ReferenceEquals(pcImageBatchProbe, probe) && PcImageBatchLifetime(probe) && FileMetadataReady();
        return Current() ? Current : null;
    }

    private static bool ValidNativeMediaHello(JsonObject plain, long now, string expectedFeature = "shared_settings")
    {
        if (plain.Count != 7 || plain["type"] is not JsonValue type || !type.TryGetValue<string>(out var frameType) || frameType != "message" ||
            !TelefonProtocolContract.TryInteger(plain["v"], out var version) || version != 1 ||
            plain["message_id"] is not JsonValue idValue || !idValue.TryGetValue<string>(out var id) ||
            !Guid.TryParseExact(id, "D", out var parsed) || id != parsed.ToString("D") || id[14] != '4' || "89ab".IndexOf(id[19]) < 0 ||
            !TelefonProtocolContract.TryInteger(plain["created_ms"], out var created) ||
            !TelefonProtocolContract.TryInteger(plain["expires_ms"], out var expires) || created < 0 || created - now > 250 || created >= expires ||
            expires <= now || expires > 253_402_300_799_999L || expires - created > 10_000 || plain["body"] is not JsonObject body ||
            body.Count != 2 || !TelefonProtocolContract.TryInteger(body["format"], out var format) || format != 1) return false;
        return body["feature"] is JsonValue feature && feature.TryGetValue<string>(out var name) && name == expectedFeature;
    }

    partial void RouteNativeMediaSupport(JsonObject plain, ref Task? handling)
    {
        if (NativeMediaSupportChecked && plain["kind"] is JsonValue kind && kind.TryGetValue<string>(out var name) && name == NativeMediaSupportKind)
        {
            handling = plain["body"] is JsonObject body && JsonNode.DeepEquals(body["feature"], JsonValue.Create(PcImageBatchSupport))
                ? ReceivePcImageBatchHelloAsync(plain) : ReceiveNativeMediaHelloAsync(plain);
            return;
        }
        if (ConsumePrivateMediaSettingsAck(plain) is { } settingsAck)
        {
            handling = settingsAck;
            return;
        }
        if (pcImageBatchProbe is { } imageProbe &&
            JsonNode.DeepEquals(plain["type"], JsonValue.Create("ack")) &&
            JsonNode.DeepEquals(plain["message_id"], JsonValue.Create(imageProbe.Id)))
        {
            handling = Task.CompletedTask; // This ACK must never reach the ordinary outbox.
            if (imageProbe.Accepted) return;
            if (imageProbe.OppositeAckWritten && PcImageBatchLifetime(imageProbe) && FileMetadataReady() &&
                plain.Count == 4 && JsonNode.DeepEquals(plain["status"], JsonValue.Create("accepted")) &&
                JsonNode.DeepEquals(plain["error"], JsonValue.Create("none")))
            {
                imageProbe.Accepted = true;
                handling = MediaPreferencesChanged?.Invoke() ?? Task.CompletedTask;
            }
            else imageProbe.Retired = true;
            return;
        }
        if (mediaSupportId is null || !JsonNode.DeepEquals(plain["type"], JsonValue.Create("ack")) ||
            !JsonNode.DeepEquals(plain["message_id"], JsonValue.Create(mediaSupportId))) return;
        // Even late receipts belong only to this attempt, never the outbox.
        handling = Task.CompletedTask;
        if (!NativeMediaSupportLifetime || !mediaSupportOppositeAckWritten || !FileMetadataReady() ||
            plain.Count != 4 || !JsonNode.DeepEquals(plain["status"], JsonValue.Create("accepted")) ||
            !JsonNode.DeepEquals(plain["error"], JsonValue.Create("none"))) RetireNativeMediaSupport();
        else
        {
            mediaSupportAccepted = true;
            handling = RestoreOriginalMediaSettingsAsync();
        }
    }

    private async Task ReceivePcImageBatchHelloAsync(JsonObject plain)
    {
        var now = Now();
        if (!NativePcImageBatchChecked || LegacyMediaSettingsAdvertised || pcImageBatchProbe is not null ||
            !NativeMediaSupportEstablished || !ValidNativeMediaHello(plain, now, PcImageBatchSupport)) return;
        var probe = new PcImageBatchProbe(Guid.NewGuid().ToString("D"), Environment.TickCount64,
            Math.Min(now + 10_000, plain["expires_ms"]!.GetValue<long>()));
        pcImageBatchProbe = probe;
        var offer = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = probe.Id,
            ["kind"] = NativeMediaSupportKind, ["created_ms"] = now, ["expires_ms"] = probe.Expires,
            ["body"] = new JsonObject { ["format"] = 1, ["feature"] = PcImageBatchSupport } };
        var ack = new JsonObject { ["type"] = "ack", ["message_id"] = plain["message_id"]!.DeepClone(),
            ["status"] = "accepted", ["error"] = "none" };
        bool Current() => PcImageBatchLifetime(probe);
        try
        {
            probe.OppositeAckWritten = await SendNativeMediaSupportFrameAsync(offer, Current) && FileMetadataReady() &&
                await SendNativeMediaSupportFrameAsync(ack, Current) && Current() && FileMetadataReady();
        }
        finally { if (!probe.OppositeAckWritten) probe.Retired = true; }
    }

    private async Task ReceiveNativeMediaHelloAsync(JsonObject plain)
    {
        var now = Now();
        if (!mediaSupportReaderActive || transport != "wifi" || mediaSupportId is not null ||
            !ValidNativeMediaHello(plain, now)) return;
        if (!FileMetadataReady())
        {
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
            if (FileMetadataChannelCurrent(current) && store.PersonalSettings(peer.Id).OwnDevice &&
                current!.Capabilities["device_status"]?["versions"] is JsonArray versions &&
                versions.Any(value => TelefonProtocolContract.TryInteger(value, out var version) && version == DeviceFileControl.DiscoveryVersion) &&
                fileOwnMetadataHistory?["body"]?["own_device"]?.GetValue<bool>() != false)
                earlyMediaHello ??= (plain.DeepClone().AsObject(), Environment.TickCount64);
            return;
        }
        await AnswerNativeMediaHelloAsync(plain, Environment.TickCount64);
    }

    private async Task ReplayEarlyNativeMediaHelloAsync()
    {
        if (earlyMediaHello is not { } pending) return;
        if (!mediaSupportReaderActive || mediaSupportId is not null || !ValidNativeMediaHello(pending.Frame, Now()) ||
            Environment.TickCount64 - pending.Received is < 0 or >= 10_000)
        { earlyMediaHello = null; return; }
        if (!FileMetadataReady()) return;
        earlyMediaHello = null;
        await AnswerNativeMediaHelloAsync(pending.Frame, pending.Received);
    }

    private async Task AnswerNativeMediaHelloAsync(JsonObject plain, long received)
    {
        var now = Now();
        if (!ValidNativeMediaHello(plain, now) || Environment.TickCount64 - received is < 0 or >= 10_000) return;
        mediaSupportStarted = received;
        mediaSupportExpires = Math.Min(now + 10_000, plain["expires_ms"]!.GetValue<long>());
        mediaSupportId = Guid.NewGuid().ToString("D");
        var offer = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = mediaSupportId,
            ["kind"] = NativeMediaSupportKind, ["created_ms"] = now, ["expires_ms"] = mediaSupportExpires,
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

    private async Task<bool> SendNativeMediaSupportFrameAsync(JsonObject frame, Func<bool>? attemptCurrent = null)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(10));
        await writer.WaitAsync(deadline.Token);
        try
        {
            // Check native metadata before acquiring the writer, never from
            // its gate. Retirement/connection lifetime can only deny here.
            if (!NativeMediaSupportLifetime || attemptCurrent?.Invoke() == false) return false;
            await TelefonCoordinator.WriteFrameAsync(stream, Seal(frame), deadline.Token);
            lastSentMs = Now();
            return true;
        }
        catch { stream.Dispose(); throw; }
        finally { writer.Release(); }
    }

    private static bool IsFileMetadata(string? kind) => kind is
        "capabilities.update" or "grants.update" or "personal_sync.settings";

    private static bool EquivalentFileMetadata(string kind, JsonObject before, JsonObject after)
    {
        var field = kind switch { "capabilities.update" => "items", "grants.update" => "grants", _ => null };
        return field is not null && before.Count == 2 && after.Count == 2 &&
            TelefonProtocolContract.TryInteger(before["revision"], out var oldRevision) &&
            TelefonProtocolContract.TryInteger(after["revision"], out var newRevision) && newRevision > oldRevision &&
            before[field] is JsonObject && JsonNode.DeepEquals(before[field], after[field]);
    }

    partial void BeginFileMetadataReceipt(JsonObject message, ref object? attempt)
    {
        var kind = message["kind"]?.GetValue<string>();
        if (!IsFileMetadata(kind)) return;
        var preserveOriginal = mediaSupportAccepted && NativeMediaSupportLifetime && OriginalMediaReceiveSelected;
        JsonObject? previous = null;
        lock (fileMetadataGate)
        {
            if (preserveOriginal && fileMetadataReceipts.TryGetValue(kind!, out var receipt) &&
                message["body"] is JsonObject body && EquivalentFileMetadata(kind!, receipt, body))
                previous = receipt;
            // Retire changed authority before processing or attempting output.
            // An equivalent higher revision retains the last actual ACK.
            if (previous is null)
            {
                RetireNativeMediaSupport();
                fileMetadataReceipts.Remove(kind!);
            }
            var current = new FileMetadataAttempt(kind!, message.DeepClone().AsObject(), previous);
            fileMetadataAttempts[kind!] = current;
            attempt = current;
        }
        if (previous is not null) return;
        InvalidateNativeFileMetadataAuthority();
    }

    private void InvalidateNativeFileMetadataAuthority()
    {
        InvalidateMediaSharedReceipts();
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
            earlyMediaHello = null;
            fileOwnMetadataHistory = captured.Message;
            fileMetadataReceipts.Remove(captured.Kind);
        }
    }

    partial void CompleteFileMetadataReceipt(JsonObject message, TelefonAck ack, object? attempt)
    {
        if (attempt is not FileMetadataAttempt captured) return;
        if (ack.Status is not ("accepted" or "duplicate") || ack.Error != "none" ||
            ack.MessageId != captured.Message["message_id"]?.GetValue<string>() ||
            !JsonNode.DeepEquals(captured.Message, message) || !store.ReceivedMatches(peer.Id, message))
        { InvalidateFailedEquivalentMetadata(captured); return; }
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(current) ||
            !FileMetadataMatches(captured.Kind, captured.Message["body"]!.AsObject(), current!))
        { InvalidateFailedEquivalentMetadata(captured); return; }
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

    private void InvalidateFailedEquivalentMetadata(FileMetadataAttempt attempt)
    {
        if (attempt.Previous is null) return;
        lock (fileMetadataGate)
        {
            if (!fileMetadataAttempts.TryGetValue(attempt.Kind, out var latest) || !ReferenceEquals(latest, attempt)) return;
            RetireNativeMediaSupport();
            fileMetadataReceipts.Remove(attempt.Kind);
            fileMetadataAttempts.Remove(attempt.Kind);
        }
        InvalidateNativeFileMetadataAuthority();
    }

    private bool FileMetadataMatchesCurrentOrEquivalent(KeyValuePair<string, JsonObject> receipt, TelefonPeer current)
    {
        if (FileMetadataMatches(receipt.Key, receipt.Value, current)) return true;
        lock (fileMetadataGate)
            return fileMetadataAttempts.TryGetValue(receipt.Key, out var pending) && ReferenceEquals(pending.Previous, receipt.Value) &&
                FileMetadataMatches(receipt.Key, pending.Message["body"]!.AsObject(), current);
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
            if (!FileMetadataMatchesCurrentOrEquivalent(receipt, current!))
            {
                lock (fileMetadataGate)
                    if (fileMetadataReceipts.TryGetValue(receipt.Key, out var actual) && ReferenceEquals(actual, receipt.Value))
                        fileMetadataReceipts.Remove(receipt.Key);
                return false;
            }
        var status = current!.Capabilities["device_status"] as JsonObject;
        if (status?["available"]?.GetValue<bool>() != true || status["versions"] is not JsonArray versions ||
            !versions.Any(value => TelefonProtocolContract.TryInteger(value, out var number) && number == DeviceFileControl.DiscoveryVersion) ||
            videos && !versions.Any(value => TelefonProtocolContract.TryInteger(value, out var number) && number == DeviceFileControl.VideoDiscoveryVersion)) return false;
        // Protected I/O above does not hold this monitor. Recheck exact receipt
        // objects and session lifetime so a concurrent withdrawal wins.
        var after = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id);
        if (!FileMetadataChannelCurrent(after) || receipts.Any(value => !FileMetadataMatchesCurrentOrEquivalent(value, after!))) return false;
        lock (fileMetadataGate)
            return !fileMetadataRevoked && !disposed && !cancellation.IsCancellationRequested && RemoteCloseReason.Length == 0 &&
                receipts.All(value => fileMetadataReceipts.TryGetValue(value.Key, out var actual) &&
                    (ReferenceEquals(actual, value.Value) || EquivalentFileMetadata(value.Key, value.Value, actual)));
    }
}
