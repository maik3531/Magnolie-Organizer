using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private readonly Dictionary<string, (string Peer, string Message, TaskCompletionSource<bool> Completion)> timeCommits = new(StringComparer.Ordinal);

    internal JsonObject TimeSettings(string id)
    {
        lock (gate)
        {
            try
            {
                var policies = store.TimeSettings(id, allowFailed: true);
                var ready = online.TryGetValue(id, out var connection) && policies["local"] is JsonObject local &&
                    policies["remote"] is JsonObject remote && connection.TimeAllowed(TimeSyncContract.RequestBody(local, remote), true);
                policies["supported"] = store.TimeSupported(id); policies["ready"] = ready;
                return policies;
            }
            catch (InvalidOperationException) { return new JsonObject { ["supported"] = false, ["ready"] = false }; }
        }
    }

    private async Task<string> SendTimeBridgeAsync(string id, string kind, JsonObject body)
    {
        TelefonConnection? connection; var result = "";
        await store.NotePolicyGate.WaitAsync();
        try
        {
            lock (gate)
            {
                RequireSolePeer(id); online.TryGetValue(id, out connection);
                if (kind == TimeSyncContract.Settings)
                {
                    TelefonProtocolContract.ExactObject(body, "enabled");
                    var enabled = body["enabled"]!.GetValue<bool>();
                    if (enabled && (!store.TimeSupported(id) || !store.PersonalSettings(id).OwnDevice))
                        throw new InvalidOperationException("Time synchronization is not permitted.");
                    var local = store.TimeSettings(id, allowFailed: true)["local"] as JsonObject;
                    if (local is null || local["enabled"]!.GetValue<bool>() != enabled || store.TimePolicyFailed(id))
                        store.SetTimeSettings(id, TimeSyncContract.NewSettings(enabled,
                            local is null ? 1 : TelefonProtocolContract.Integer(local["revision"]) + 1));
                }
                else
                {
                    TimeSyncContract.Validate(kind, body, true);
                    if (connection is null || !connection.TimeAllowed(body, true)) throw new InvalidOperationException("Time synchronization is not ready.");
                    var trigger = body["trigger"]!.GetValue<string>();
                    if (kind == TimeSyncContract.Batch && trigger == "manual" && connection.Transport == "bluetooth") store.SupersedeWifiTime(id);
                    result = store.Enqueue(id, kind, body, 86_400_000, Now(), trigger == "auto_wifi" ? "wifi_only" : "any");
                }
            }
        }
        finally { store.NotePolicyGate.Release(); }
        if (connection is not null)
        {
            if (kind == TimeSyncContract.Settings) await connection.SendTimeSettingsAsync(true);
            else await connection.PumpOutboxNowAsync();
        }
        await ReportStatusAsync(); return result;
    }

    private async Task<TelefonAck?> HandleTimeMessageAsync(TelefonPeer peer, JsonObject message, JsonObject body)
    {
        var kind = message["kind"]!.GetValue<string>(); var id = message["message_id"]!.GetValue<string>();
        if (kind == TimeSyncContract.Settings) { await ReportStatusAsync(); return null; }
        JsonObject? staged = null; TaskCompletionSource<bool>? completion = null; string? token = null;
        var cancellation = CancellationToken.None;
        lock (gate)
        {
            var current = Peers.FirstOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !online.TryGetValue(peer.Id, out var connection) || !connection.TimeAllowed(body, false))
                return new TelefonAck(id, "rejected", "not_granted");
            cancellation = connection.TimeCancellation;
            if (kind == TimeSyncContract.Batch)
            {
                staged = store.StageTimeBatch(peer.Id, message, Now()); token = staged["commit_token"]!.GetValue<string>();
                completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                timeCommits[token] = (peer.Id, id, completion);
            }
        }
        if (kind == TimeSyncContract.Request)
        {
            await emit("App.personalTimeRequest", new { device_id = peer.Id, trigger = body["trigger"]!.GetValue<string>() });
            return null;
        }
        try
        {
            await emit("App.personalTimeBatch", staged!);
            return await completion!.Task.WaitAsync(TimeSpan.FromSeconds(30), cancellation) ? null : new TelefonAck(id, "rejected", "temporary_failure");
        }
        finally
        {
            lock (gate) if (timeCommits.TryGetValue(token!, out var pending) && pending.Completion == completion) timeCommits.Remove(token!);
        }
    }

    private bool IsTimeCommit(string peerId, string messageId, string token)
    {
        lock (gate) return store.HasTimeBatch(peerId, messageId) ||
            timeCommits.TryGetValue(token, out var pending) && pending.Peer == peerId && pending.Message == messageId;
    }

    private bool CommitTimeSync(string peerId, string messageId, string token, bool success)
    {
        lock (gate)
        {
            if (!timeCommits.TryGetValue(token, out var pending) || pending.Peer != peerId || pending.Message != messageId) return false;
            var committed = success && online.TryGetValue(peerId, out var connection) &&
                store.CommitTimeBatch(peerId, messageId, token, Now(), message => connection.TimeAllowed(message["body"]!.AsObject(), false));
            pending.Completion.TrySetResult(committed); return committed;
        }
    }
}
