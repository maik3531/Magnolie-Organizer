using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal static class TelefonDeveloperDiagnostics
{
    internal const int Version = 11;
    internal const int CrashVersion = 13;
    internal static void ValidateRequest(JsonObject body)
    {
        TelefonProtocolContract.ExactObject(body, "version", "request_id");
        if (TelefonProtocolContract.Integer(body["version"]) is not (Version or CrashVersion) ||
            !TelefonProtocolContract.IsUuidV4(body["request_id"]?.GetValue<string>()))
            throw new InvalidDataException("invalid_developer_request");
    }

    internal static void ValidateReport(JsonObject body)
    {
        var reportVersion = TelefonProtocolContract.Integer(body["version"]);
        if (reportVersion == CrashVersion) TelefonProtocolContract.ExactObject(body, "version", "request_id", "format", "app_version", "events", "crash_report");
        else TelefonProtocolContract.ExactObject(body, "version", "request_id", "format", "app_version", "events");
        if (reportVersion is not (Version or CrashVersion) ||
            TelefonProtocolContract.Integer(body["format"]) != 1 ||
            !TelefonProtocolContract.IsUuidV4(body["request_id"]?.GetValue<string>()) ||
            body["app_version"] is not JsonValue app || !app.TryGetValue<string>(out var version) || version.Length is < 1 or > 80 ||
            body["events"] is not JsonArray events || events.Count > 128 || Encoding.UTF8.GetByteCount(body.ToJsonString()) > (reportVersion == CrashVersion ? 131072 : 65536))
            throw new InvalidDataException("invalid_developer_report");
        if (reportVersion == CrashVersion)
        {
            var crash = TelefonProtocolContract.ExactObject(body["crash_report"]!, "available", "text", "truncated");
            if (crash["available"] is not JsonValue available || !available.TryGetValue<bool>(out var hasReport) ||
                crash["truncated"] is not JsonValue truncated || !truncated.TryGetValue<bool>(out var cut) ||
                crash["text"] is not JsonValue text || !text.TryGetValue<string>(out var contents) || Encoding.UTF8.GetByteCount(contents) > 16387 ||
                !hasReport && (contents.Length != 0 || cut)) throw new InvalidDataException("invalid_developer_crash_report");
        }
        foreach (var node in events)
        {
            var entry = TelefonProtocolContract.ExactObject(node!, "time_ms", "stage", "transport", "failure");
            if (!TelefonProtocolContract.TryInteger(entry["time_ms"], out var time) || time is < 0 or > 253402300799999 ||
                entry["stage"] is not JsonValue stage || !stage.TryGetValue<string>(out var stageText) ||
                stageText is not ("pair_begin" or "pair_confirmed" or "authenticating" or "secure_ready" or "online" or "closed" or "failed") ||
                entry["transport"] is not JsonValue transport || !transport.TryGetValue<string>(out var transportText) || transportText is not ("wifi" or "bluetooth") ||
                entry["failure"] is not JsonValue failure || !failure.TryGetValue<bool>(out _))
                throw new InvalidDataException("invalid_developer_event");
        }
    }
}

internal sealed partial class TelefonCoordinator
{
    private sealed record DeveloperReadWait(string PeerId, byte[] PublicKey, TelefonConnection Connection,
        string MessageId, TaskCompletionSource<JsonObject> Completion, long Deadline, CancellationToken Cancellation, int Version);
    private readonly Dictionary<string, DeveloperReadWait> developerReads = new(StringComparer.Ordinal);

    internal async Task<JsonObject> ReadDeveloperDiagnosticsAsync(string id, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        var requestId = Guid.NewGuid().ToString("D");
        DeveloperReadWait pending;
        lock (gate)
        {
            if (developerReads.Count >= 8 || !online.TryGetValue(id, out var connection) || !connection.DeveloperReadReady)
                throw new InvalidOperationException("developer_diagnostics_unavailable");
            var peer = Peers.Single(value => value.Id == id);
            var version = connection.DeveloperReadVersion;
            if (version == 0) throw new InvalidOperationException("developer_diagnostics_unavailable");
            pending = new DeveloperReadWait(id, peer.PublicKey.ToArray(), connection, Guid.NewGuid().ToString("D"),
                new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously), Environment.TickCount64 + 10000, cancellation, version);
            developerReads.Add(requestId, pending);
        }
        try
        {
            await pending.Connection.SendMessageAsync("device_status.request",
                new JsonObject { ["version"] = pending.Version, ["request_id"] = requestId }, 10000, pending.MessageId);
            var result = await pending.Completion.Task.WaitAsync(TimeSpan.FromSeconds(10), cancellation);
            lock (gate)
            {
                if (!online.TryGetValue(id, out var current) || !ReferenceEquals(current, pending.Connection) || current.DeveloperReadVersion != pending.Version ||
                    Environment.TickCount64 >= pending.Deadline || !Peers.Any(peer => peer.Id == id && peer.PublicKey.SequenceEqual(pending.PublicKey)))
                    throw new InvalidOperationException("developer_diagnostics_source_changed");
            }
            var safe = result.DeepClone().AsObject();
            if (pending.Version == TelefonDeveloperDiagnostics.CrashVersion && safe["crash_report"] is JsonObject crash && crash["available"]?.GetValue<bool>() == true)
            {
                var masked = LogPresentation.MaskSensitive(crash["text"]!.GetValue<string>());
                var output = new StringBuilder(); var budget = 16384;
                foreach (var rune in masked.EnumerateRunes())
                {
                    if (rune.Utf8SequenceLength > budget) break;
                    output.Append(rune); budget -= rune.Utf8SequenceLength;
                }
                crash["text"] = output.ToString();
                crash["truncated"] = crash["truncated"]!.GetValue<bool>() || Encoding.UTF8.GetByteCount(masked) > 16384;
            }
            return safe;
        }
        finally { lock (gate) developerReads.Remove(requestId); }
    }

    private bool RejectDeveloperRead(TelefonConnection source, TelefonPeer peer, TelefonAck ack)
    {
        lock (gate)
        {
            var pending = developerReads.Values.FirstOrDefault(value => value.PeerId == peer.Id && value.MessageId == ack.MessageId);
            if (ack.Status != "rejected" || pending is null || pending.Completion.Task.IsCompleted ||
                !ReferenceEquals(source, pending.Connection) || !pending.PublicKey.SequenceEqual(peer.PublicKey) ||
                !online.TryGetValue(peer.Id, out var current) || !ReferenceEquals(source, current) ||
                !Peers.Any(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(pending.PublicKey)) ||
                pending.Cancellation.IsCancellationRequested || Environment.TickCount64 >= pending.Deadline) return false;
            return pending.Completion.TrySetException(new IOException("developer_diagnostics_" + ack.Error));
        }
    }

    private TelefonAck AcceptDeveloperRead(TelefonConnection source, TelefonPeer peer, JsonObject message)
    {
        var messageId = message["message_id"]!.GetValue<string>();
        try
        {
            var body = message["body"]!.AsObject();
            TelefonDeveloperDiagnostics.ValidateReport(body);
            lock (gate)
            {
                if (!developerReads.TryGetValue(body["request_id"]!.GetValue<string>(), out var pending) || pending.Completion.Task.IsCompleted ||
                    pending.PeerId != peer.Id || !pending.PublicKey.SequenceEqual(peer.PublicKey) || !ReferenceEquals(source, pending.Connection) ||
                    !online.TryGetValue(peer.Id, out var current) || !ReferenceEquals(source, current) || source.DeveloperReadVersion != pending.Version ||
                    TelefonProtocolContract.Integer(body["version"]) != pending.Version)
                    return new TelefonAck(messageId, "rejected", "not_granted");
                if (pending.Cancellation.IsCancellationRequested || Environment.TickCount64 >= pending.Deadline || Now() >= TelefonProtocolContract.Integer(message["expires_ms"]))
                    return new TelefonAck(messageId, "rejected", "expired");
                pending.Completion.TrySetResult(body.DeepClone().AsObject());
                return new TelefonAck(messageId, "accepted", "none");
            }
        }
        catch (Exception error) when (error is InvalidDataException or InvalidOperationException or FormatException)
        { return new TelefonAck(messageId, "rejected", "invalid_schema"); }
    }
}

internal sealed partial class TelefonConnection
{
    internal int DeveloperReadVersion => !DeveloperReadReady ? 0 :
        store.LoadPeers().Single(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey)).Capabilities["device_status"]?["versions"] is JsonArray versions &&
        versions.Any(value => value?.GetValue<int>() == TelefonDeveloperDiagnostics.CrashVersion) ? TelefonDeveloperDiagnostics.CrashVersion : TelefonDeveloperDiagnostics.Version;
    private async Task HandleDeveloperReportAsync(JsonObject plain)
    {
        TelefonAck ack;
        try
        {
            TelefonMessageContract.ValidateMessage(plain, Now(), true);
            ack = TelefonProtocolContract.Integer(plain["expires_ms"]) - TelefonProtocolContract.Integer(plain["created_ms"]) > 60000
                ? new TelefonAck(plain["message_id"]!.GetValue<string>(), "rejected", "invalid_schema")
                : receiveDeveloper?.Invoke(this, peer, plain) ?? new TelefonAck(plain["message_id"]!.GetValue<string>(), "rejected", "not_granted");
        }
        catch (TelefonMessageException error) { ack = new TelefonAck(error.MessageId, "rejected", error.Error); }
        catch (InvalidDataException) { ack = new TelefonAck(plain["message_id"]!.GetValue<string>(), "rejected", "invalid_schema"); }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
    }

    internal bool DeveloperReadReady
    {
        get
        {
            if (disposed || transport != "wifi" || cancellation.IsCancellationRequested || store.RestoreFenced ||
                !freshCapabilities || !freshGrants || !freshOwnSettings) return false;
            var peers = store.LoadPeers();
            var current = peers.SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (peers.Count != 1 || current is null || current.State != "paired" ||
                current.Grants["device_status"]?.GetValue<bool>() != true || store.LocalGrants()["device_status"]?.GetValue<bool>() != true ||
                !TelefonCoordinator.RemoteCapability(current, "device_status") ||
                current.Capabilities["device_status"]?["versions"] is not JsonArray versions || !versions.Any(value => value?.GetValue<int>() == 11)) return false;
            var own = store.PersonalSettings(peer.Id);
            return own.OwnDevice && own.RemoteOwnDevice;
        }
    }
}
