using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class TelefonCoordinator : IDisposable
{
    internal const int Port = 8741;
    internal const string ServiceType = "_magnolie-phone._tcp.local.";
    internal static readonly Guid BluetoothService = Guid.Parse("7b1d9e2a-5c43-4f68-a172-9d30e6b4c851");
    private readonly object gate = new();
    private readonly TelefonStore store;
    private readonly PersonalSyncStore personalSync;
    private readonly TelefonIdentity identity;
    private readonly ITelefonBluetoothClient? bluetoothClient;
    private readonly bool localOnly;
    private readonly Func<string, object, Task> emit;
    private readonly Func<Task<object>> kdeStatus;
    private readonly Dictionary<string, TaskCompletionSource<bool>> confirmations = new(StringComparer.Ordinal);
    private readonly Dictionary<string, TelefonConnection> online = new(StringComparer.Ordinal);
    private readonly Dictionary<string, JsonObject> calls = new(StringComparer.Ordinal);
    // Immutable runtime snapshots: authorization from inside the store must not take gate
    // (store -> coordinator would invert the send/revocation lock order).
    private sealed record PendingDial(string PeerId, string Identity, string CallRef, long Deadline,
        bool Scoped, bool Sent = false, long StartedMs = 0, bool Ended = false);
    private PendingDial? pendingDial;
    private sealed record CallCommand(string PeerId, string Identity, string Kind, string CallRef, long Deadline, bool Sent = false);
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, CallCommand> callCommands = new(StringComparer.Ordinal);
    private readonly TelefonCallActions callActions = new();
    private readonly Dictionary<string, (string PeerId, TaskCompletionSource<string> Completion)> personalCommits = new(StringComparer.Ordinal);
    private readonly System.Threading.Timer cleanupTimer;
    private readonly System.Threading.Timer dialCleanupTimer;
    private CancellationTokenSource? serviceCancellation;
    private TcpListener? listener;
    private TelefonMdnsPublisher? mdns;
    private byte[]? pairingToken;
    private long pairingUntil;
    private sealed record SetupPairing(string Target, string Address, string Token, CancellationTokenSource Deadline);
    private SetupPairing? setupPairing;
    private string error = "";
    private bool disposed;
    private bool foregroundEnabled;
    private readonly string logPath;
    /* Genau eine Paarung darf gleichzeitig laufen: jeder Paarungsversuch
       erzeugt einen eigenen Bestätigungscode, und zwei gleichzeitige Versuche
       würden im Paarungsfenster einander überschreiben. Der Benutzer sähe dann
       einen anderen Code als das Telefon. */
    private int pairingBusy;
    private readonly SemaphoreSlim streamSlots = new(16, 16);
    private readonly System.Collections.Concurrent.ConcurrentDictionary<Task, byte> workers = new();
    private readonly SemaphoreSlim lifecycle = new(1, 1);

    private void Track(Task task)
    {
        workers.TryAdd(task, 0);
        _ = task.ContinueWith(done => { _ = done.Exception; workers.TryRemove(done, out _); },
            CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }

    internal async Task FenceForRestoreAsync(string? token = null)
    {
        try { store.BeginRestore(token); }
        finally { await StopAsync().ConfigureAwait(false); }
    }

    internal JsonObject? PendingRestore => store.PendingRestore;
    internal void PrepareRestoreCommit(string token, string stored, string epoch) => store.PrepareRestoreCommit(token, stored, epoch);
    internal void SetRestoreSnapshot(string token, string snapshot) => store.SetRestoreSnapshot(token, snapshot);
    internal void AbortRestore(string token) => store.AbortRestore(token);
    internal void ReleaseRestore(string token) => store.ReleaseRestore(token);

    internal Task CompleteRestoreAsync(string epoch, string? token = null, bool releaseFence = true)
    {
        store.CompleteRestore(epoch, token, releaseFence);
        return Task.CompletedTask;
    }

    /// <summary>
    /// Sorgt dafür, dass der Bluetooth-Funk während eines Gesprächs an ist.
    /// Den Ton legt das Telefon selbst über das Freisprechprofil dorthin; der
    /// Organizer steuert nur. Siehe <see cref="BluetoothRadioSwitch"/>.
    /// </summary>
    private readonly BluetoothRadioSwitch radioSwitch;

    internal BluetoothRadioSwitch RadioSwitch => radioSwitch;

    internal TelefonCoordinator(WindowsPaths paths, Func<string, object, Task> emit,
        Func<Task<object>>? kdeStatus = null, IBluetoothRadio? bluetoothRadio = null, TelefonStore? dataStore = null,
        ITelefonBluetoothClient? bluetoothClient = null, bool foregroundEnabled = false, bool localOnly = false)
    {
        this.foregroundEnabled = foregroundEnabled;
        this.localOnly = localOnly;
        this.bluetoothClient = bluetoothClient ?? (localOnly ? null : TelefonBluetoothClient.Create());
        radioSwitch = new BluetoothRadioSwitch(bluetoothRadio);
        logPath = Path.Combine(paths.Logs, "telefon.log");
        store = dataStore ?? new TelefonStore(paths); personalSync = new PersonalSyncStore(store); identity = store.LoadOrCreateIdentity(); this.emit = emit;
        this.kdeStatus = kdeStatus ?? (() => Task.FromResult<object>(new { available = false }));
        cleanupTimer = new System.Threading.Timer(_ => { try { var now = Now(); store.Cleanup(now); personalSync.CleanupExpiredRuns(now); } catch (Exception) { } }, null, TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(15));
        dialCleanupTimer = new System.Threading.Timer(_ => { try { lock (gate) if (pendingDial is { } pending && pending.Deadline <= Environment.TickCount64) RevokeDial(pending.PeerId); } catch (Exception) { } }, null, 1000, 1000);
    }

    internal bool Enabled => foregroundEnabled || store.Enabled;
    internal bool IsRunning { get { lock (gate) return serviceCancellation is not null; } }
    internal TelefonPeer[] Peers => store.LoadPeers().Where(peer => peer.State == "paired").ToArray();
    internal TelefonPeer[] StatusPeers { get { store.Cleanup(Now()); return store.LoadPeers().ToArray(); } }
    internal JsonObject LocalGrants() => store.LocalGrants();
    internal void ClearDeviceIdentifiers(string id) => store.PurgeIdentifiers(id);
    internal JsonObject CurrentDeviceStatus(JsonObject status)
    {
        lock (gate)
        {
            var id = status["kennung"]?.GetValue<string>() ?? "";
            var peer = Peers.FirstOrDefault(p => p.Id == id);
            return peer is not null && online.ContainsKey(id) ? store.CurrentIdentifierStatus(peer, status)
                : TelefonDeviceStatusContract.WithoutIdentifiers(status);
        }
    }
    internal JsonArray RecentNotifications(string id) => store.LoadRecent(id, "selected_notifications_readonly.event");
    internal JsonObject? PersonalRunRequest(string id, string runId) => personalSync.LoadRun(id, runId, Now())?.Request.DeepClone().AsObject();

    internal Task ResumeAsync() => Enabled ? StartAsync() : Task.CompletedTask;

    internal Task StartSetupAsync()
    {
        foregroundEnabled = true;
        return StartAsync();
    }

    internal async Task SwitchAsync(bool enabled)
    {
        foregroundEnabled = false;
        store.Enabled = enabled;
        if (enabled) await StartAsync(); else await StopAsync();
        await ReportStatusAsync();
    }

    internal async Task StartPairingAsync()
    {
        store.Cleanup(Now());
        if (!Enabled) throw new InvalidOperationException(T("The Magnolie Notes phone connection is switched off."));
        if (store.LoadPeers().Count != 0) throw new InvalidOperationException(T("Only one Magnolie Notes phone can be paired. Remove the existing phone before changing devices."));
        await StartAsync();
        lock (gate)
        {
            setupPairing?.Deadline.Cancel(); setupPairing?.Deadline.Dispose(); setupPairing = null;
            pairingToken = RandomNumberGenerator.GetBytes(16); pairingUntil = long.MaxValue;
        }
        if (mdns is not null) try { await mdns.AnnounceNowAsync(); } catch (SocketException) { }
        await emit("App.telefonPaarung", new { offen = true, code = "", name = "", fingerabdruck = "", fehler = "", sekunden = 120 });
    }

    internal void ConfirmPairing(string peerId, bool accepted)
    { lock (gate) if (confirmations.Remove(peerId, out var completion)) completion.TrySetResult(accepted); }

    internal JsonObject OpenSetupPairing(string target, IPAddress address)
    {
        if (!Guid.TryParseExact(target, "D", out _) || !TelefonInvitation.Local(address)) throw new InvalidDataException();
        return OpenBoundSetupPairing(target, address.ToString());
    }

    internal void PauseUnpairedWindow()
    {
        lock (gate)
        {
            if (pairingBusy != 0 || store.LoadPeers().Count != 0) throw new InvalidOperationException(T("Another phone is already paired. Remove it first."));
            pairingUntil = 0;
        }
    }

    internal JsonObject OpenBluetoothSetupPairing(string target, string address)
    {
        if (!Guid.TryParseExact(target, "D", out _) || !TelefonBluetoothClient.ValidAddress(address)) throw new InvalidDataException();
        return OpenBoundSetupPairing(target, "bluetooth:" + address);
    }

    private JsonObject OpenBoundSetupPairing(string target, string address)
    {
        if (target == identity.Id) throw new InvalidDataException();
        lock (gate)
        {
            if (!IsRunning || store.LoadPeers().Count != 0 || pairingBusy != 0) throw new InvalidOperationException(T("Another phone is already paired. Remove it first."));
            setupPairing?.Deadline.Cancel();
            setupPairing?.Deadline.Dispose();
            pairingToken = RandomNumberGenerator.GetBytes(16);
            pairingUntil = DateTimeOffset.UtcNow.AddSeconds(120).ToUnixTimeMilliseconds();
            var token = Convert.ToBase64String(pairingToken);
            var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(120));
            setupPairing = new(target, address, token, deadline);
            return new JsonObject { ["device_id"] = identity.Id, ["name"] = identity.Name, ["token"] = token };
        }
    }

    internal void EndSetupPairing(string token)
    {
        lock (gate)
        {
            if (setupPairing?.Token != token) return;
            pairingUntil = 0;
            setupPairing.Deadline.Cancel();
            if (confirmations.Remove(setupPairing.Target, out var pending)) pending.TrySetResult(false);
        }
    }

    internal async Task RemoveAsync(string id)
    {
        TelefonConnection? connection;
        lock (gate)
        {
            online.Remove(id, out connection); calls.Remove(id); RevokeDial(id);
            if (confirmations.Remove(id, out var confirmation)) confirmation.TrySetResult(false);
            foreach (var token in personalCommits.Where(item => item.Value.PeerId == id).Select(item => item.Key).ToArray())
                if (personalCommits.Remove(token, out var pending)) pending.Completion.TrySetResult("temporary");
            store.RemovePeer(id);
        }
        connection?.Dispose();
        await radioSwitch.ReleaseAllAsync(id).ConfigureAwait(false);
        lock (gate)
        {
            if (store.LoadPeers().Count == 0)
            {
                setupPairing?.Deadline.Cancel(); setupPairing?.Deadline.Dispose(); setupPairing = null;
            }
            EnsurePairingAvailableLocked();
        }
        if (mdns is not null) try { await mdns.AnnounceNowAsync(); } catch (SocketException) { }
        await ReportStatusAsync();
    }

    internal async Task RequestDeviceStatusAsync(string id, string? requestId = null)
    {
        store.PurgeIdentifiers(id);
        TelefonConnection? connection;
        lock (gate) online.TryGetValue(id, out connection);
        if (connection is null) { await emit("App.telefonFehler", new { fehler = T("The phone is not connected via WLAN.") }); return; }
        var peer = Peers.FirstOrDefault(value => value.Id == id);
        if (peer is null || !RemoteCapability(peer, "device_status") || peer.Grants["device_status"]?.GetValue<bool>() != true)
        { await emit("App.telefonFehler", new { fehler = T("Device status is not permitted or available on the phone.") }); return; }
        requestId ??= Guid.NewGuid().ToString("D");
        var versions = peer.Capabilities["device_status"]?["versions"] as JsonArray;
        var body = DeviceStatusRequest(requestId, versions, store.IdentifiersAllowed(peer));
        await connection.SendMessageAsync("device_status.request", body, 60_000);
    }

    internal static JsonObject DeviceStatusRequest(string requestId, JsonArray? versions, bool includeIdentifiers = false)
    {
        var body = new JsonObject { ["request_id"] = requestId };
        if (includeIdentifiers && versions?.Any(value => value?.GetValue<int>() == 4) == true)
        { body["version"] = 4; body["include_identifiers"] = true; }
        else if (versions?.Any(value => value?.GetValue<int>() == 3) == true) body["version"] = 3;
        else if (versions?.Any(value => value?.GetValue<int>() == 2) == true) body["version"] = 2;
        TelefonDeviceStatusContract.ValidateRequest(body);
        return body;
    }

    internal async Task SetLocalGrantsAsync(bool smsReceived, bool notifications)
    {
        store.SetLocalGrants(smsReceived, notifications);
        var revision = store.NextOwnRevision("grants");
        TelefonConnection[] connections; lock (gate) connections = online.Values.ToArray();
        foreach (var connection in connections) await connection.SendGrantsAsync(revision, store.LocalGrants());
        await ReportStatusAsync();
    }

    internal async Task SetGrantAsync(string id, string name, bool enabled)
    {
        if (Peers.All(peer => peer.Id != id)) throw new InvalidOperationException(T("The phone is not paired."));
        if (!enabled && name == "personal_notes_sync") personalSync.PurgeModules(id, new HashSet<string>(StringComparer.Ordinal) { "notes" });
        if (!enabled && name == "personal_tasks_sync") personalSync.PurgeModules(id, new HashSet<string>(StringComparer.Ordinal) { "tasks" });
        if (!enabled && name == "personal_deletions_sync") personalSync.PurgeDeletionProtocol(id);
        long revision; TelefonConnection? connection;
        lock (gate)
        {
            callActions.Clear();
            if (!enabled && name is "dial_request" or "incoming_call_state" or "end_call") RevokeDial(id);
            store.SetLocalGrant(name, enabled); revision = store.NextOwnRevision("grants"); online.TryGetValue(id, out connection);
        }
        if (connection is not null) await connection.SendGrantsAsync(revision, store.LocalGrants()); await ReportStatusAsync();
    }

    internal async Task SendSmsAsync(string id, string number, string text, string clientRef)
    {
        _ = (id, number, text, clientRef); await Task.CompletedTask;
        throw new NotSupportedException(T("Magnolie SMS is no longer part of the current Magnolie Notes phone protocol."));
    }

    internal async Task<string> RequestDialAsync(string id, string number, string clientRef)
    {
        var body = new JsonObject { ["to"] = number, ["client_ref"] = clientRef }; TelefonCallContract.Validate("dial_request.command", body);
        TelefonConnection connection;
        lock (gate)
        {
            connection = RequireOnline(id, "dial_request", true);
            var peer = RequireSolePeer(id);
            if (store.HasCommand(id, clientRef) || pendingDial is { Ended: false } pending && pending.Deadline > Environment.TickCount64 ||
                calls.GetValueOrDefault(id)?["state"]?.GetValue<string>() is "ringing" or "offhook")
                throw new InvalidOperationException(T("This dial request has already been queued."));
            store.RememberCommand(id, clientRef, Now());
            pendingDial = new(id, Convert.ToBase64String(peer.PublicKey), clientRef, Environment.TickCount64 + 60_000, SupportsScopedDial(peer));
        }
        try { await connection.SendMessageAsync("dial_request.command", body, 60_000); }
        catch { lock (gate) if (pendingDial?.CallRef == clientRef) RevokeDial(id); throw; }
        lock (gate) if (pendingDial?.CallRef != clientRef || !pendingDial.Sent)
            throw new InvalidOperationException(T("The phone function is not permitted or available."));
        await emit("App.telefonWaehlstatus", new { device_id = id, client_ref = clientRef, state = "queued", error = "none", occurred_ms = Now() }); return clientRef;
    }

    internal async Task<string> RequestAnswerAsync(string id, string callRef, string commandRef)
    {
        var connection = RequireOnline(id, "answer_call", true); JsonObject current; lock (gate) current = calls.GetValueOrDefault(id)?.DeepClone().AsObject() ?? throw new InvalidOperationException(T("The call is no longer ringing."));
        if (current["call_ref"]?.GetValue<string>() != callRef || current["state"]?.GetValue<string>() != "ringing" || current["direction"]?.GetValue<string>() != "incoming") throw new InvalidOperationException(T("The call is no longer ringing or is outdated."));
        var body = new JsonObject { ["command_ref"] = commandRef, ["call_ref"] = callRef, ["expected_state"] = "ringing" }; TelefonCallContract.Validate("answer_call.command", body);
        if (store.HasCommand(id, commandRef)) throw new InvalidOperationException(T("This answer request has already been queued.")); store.RememberCommand(id, commandRef, Now());
        RememberCallCommand(id, commandRef, "answer_call", callRef);
        await connection.SendMessageAsync("answer_call.command", body, 10_000); return commandRef;
    }

    internal async Task<string> RequestEndCallAsync(string id, string callRef, long expectedRevision, string commandRef)
    {
        TelefonConnection connection; JsonObject body;
        lock (gate)
        {
        var current = calls.GetValueOrDefault(id) ?? throw new InvalidOperationException(T("The call is no longer active."));
        var peer = RequireSolePeer(id);
        var scoped = OutgoingCallAllowed(peer, current) && current["state"]?.GetValue<string>() == "offhook";
        connection = scoped ? online.GetValueOrDefault(id) ?? throw new InvalidOperationException(T("The phone is not paired.")) : RequireOnline(id, "end_call", true);
        if (!RemoteCapability(peer, "end_call")) throw new InvalidOperationException(T("The phone function is not permitted or available."));
        var state = current["state"]?.GetValue<string>() ?? "";
        var rejecting = state == "ringing" && current["direction"]?.GetValue<string>() == "incoming" && store.LocalGrants()["answer_call"]?.GetValue<bool>() == true &&
            Peers.FirstOrDefault(peer => peer.Id == id)?.Capabilities["end_call"]?["versions"] is JsonArray versions && versions.Any(value => value?.GetValue<int>() == 2);
        if (current["call_ref"]?.GetValue<string>() != callRef || state != "offhook" && !rejecting || current["revision"]?.GetValue<long>() != expectedRevision) throw new InvalidOperationException(T("The call is no longer active or has been updated."));
        body = new JsonObject { ["command_ref"] = commandRef, ["call_ref"] = callRef, ["expected_revision"] = expectedRevision, ["expected_state"] = state }; TelefonCallContract.Validate("end_call.command", body);
        if (store.HasCommand(id, commandRef)) throw new InvalidOperationException(T("This end-call request has already been queued.")); store.RememberCommand(id, commandRef, Now());
        RememberCallCommand(id, commandRef, "end_call", callRef);
        }
        await connection.SendMessageAsync("end_call.command", body, 10_000);
        if (callCommands.TryGetValue(commandRef, out var unsent) && !unsent.Sent)
            throw new InvalidOperationException(T("The call is no longer active or has been updated."));
        return commandRef;
    }

    private static bool SupportsScopedDial(TelefonPeer peer) => RemoteCapability(peer, "dial_request") &&
        peer.Capabilities["dial_request"]?["versions"] is JsonArray versions && versions.Any(v => v?.GetValue<int>() == 2);

    private void RevokeDial(string id)
    {
        if (pendingDial is { } pending && pending.PeerId == id)
        {
            pendingDial = null;
            if (calls.GetValueOrDefault(id)?["call_ref"]?.GetValue<string>() == pending.CallRef) calls.Remove(id);
            if (!pending.Ended && !disposed) Track(emit("App.telefonWaehlstatus", new {
                device_id = id, client_ref = pending.CallRef, state = "failed", error = "not_granted", occurred_ms = Now() }));
        }
        foreach (var item in callCommands.Where(item => item.Value.PeerId == id)) callCommands.TryRemove(item.Key, out _);
    }

    private void RememberCallCommand(string id, string commandRef, string kind, string callRef)
    {
        lock (gate)
        {
            foreach (var item in callCommands.Where(item => item.Value.Deadline <= Environment.TickCount64)) callCommands.TryRemove(item.Key, out _);
            callCommands[commandRef] = new(id, Convert.ToBase64String(RequireSolePeer(id).PublicKey), kind, callRef, Environment.TickCount64 + 60_000);
        }
    }

    private bool OutgoingCallAllowed(TelefonPeer peer, JsonObject body, bool requireScoped = true)
    {
        var pending = Volatile.Read(ref pendingDial);
        return pending is { Sent: true, Ended: false } && pending.Deadline > Environment.TickCount64 &&
            pending.PeerId == peer.Id && pending.Identity == Convert.ToBase64String(peer.PublicKey) &&
            (!requireScoped || pending.Scoped && SupportsScopedDial(peer)) && peer.Grants["dial_request"]?.GetValue<bool>() == true &&
            body["call_ref"]?.GetValue<string>() == pending.CallRef && body["direction"]?.GetValue<string>() == "outgoing" &&
            body["control_origin"]?.GetValue<string>() == "desktop" &&
            (pending.StartedMs == 0 || body["started_ms"]?.GetValue<long>() == pending.StartedMs);
    }

    private string? AuthorizeCall(TelefonPeer sessionPeer, string kind, JsonObject body)
    {
        var peer = Peers.FirstOrDefault(p => p.Id == sessionPeer.Id && p.PublicKey.SequenceEqual(sessionPeer.PublicKey));
        if (peer is null || store.RestoreFenced) return "not_granted";
        var local = store.LocalGrants();
        if (kind == "dial_request.result")
        {
            var pending = Volatile.Read(ref pendingDial);
            return pending is { Sent: true } && pending.Deadline > Environment.TickCount64 && pending.PeerId == peer.Id &&
                pending.Identity == Convert.ToBase64String(peer.PublicKey) && body["client_ref"]?.GetValue<string>() == pending.CallRef &&
                local["dial_request"]?.GetValue<bool>() == true && peer.Grants["dial_request"]?.GetValue<bool>() == true ? null : "not_granted";
        }
        if (kind is "answer_call.result" or "end_call.result")
            return callCommands.TryGetValue(body["command_ref"]!.GetValue<string>(), out var command) && command.Sent &&
                command.Deadline > Environment.TickCount64 && command.PeerId == peer.Id && command.Kind + ".result" == kind &&
                command.Identity == Convert.ToBase64String(peer.PublicKey) && command.CallRef == body["call_ref"]?.GetValue<string>() ? null : "not_granted";
        var stateGranted = local["incoming_call_state"]?.GetValue<bool>() == true && peer.Grants["incoming_call_state"]?.GetValue<bool>() == true;
        var scoped = local["dial_request"]?.GetValue<bool>() == true && OutgoingCallAllowed(peer, body);
        if (!stateGranted && !scoped || body["number_status"]?.GetValue<string>() == "available" &&
            (local["incoming_call_number"]?.GetValue<bool>() != true || peer.Grants["incoming_call_number"]?.GetValue<bool>() != true)) return "not_granted";
        return IncomingCallDisposition(store.LoadRecent(peer.Id, kind, 1).FirstOrDefault() as JsonObject, body) == "conflict" ? "conflict" : null;
    }

    // Called with the connection writer held; final check + actual write is serialized
    // with revocation/unpair. Queued/replayed commands alone never mint authority.
    private bool SendCall(TelefonConnection connection, TelefonPeer sessionPeer, JsonObject message, Action write)
    {
        lock (gate)
        {
            var peer = Peers.FirstOrDefault(p => p.Id == sessionPeer.Id && p.PublicKey.SequenceEqual(sessionPeer.PublicKey));
            if (peer is null || online.GetValueOrDefault(peer.Id) != connection || store.RestoreFenced) return false;
            var kind = message["kind"]!.GetValue<string>(); var body = message["body"]!.AsObject();
            if (Now() >= message["expires_ms"]!.GetValue<long>()) return false;
            if (kind == "dial_request.command")
            {
                var pending = pendingDial;
                if (pending is null || pending.Sent || pending.Ended || pending.Deadline <= Environment.TickCount64 || pending.PeerId != peer.Id ||
                    pending.Identity != Convert.ToBase64String(peer.PublicKey) || pending.CallRef != body["client_ref"]?.GetValue<string>() ||
                    !RemoteCapability(peer, "dial_request") || peer.Grants["dial_request"]?.GetValue<bool>() != true ||
                    store.LocalGrants()["dial_request"]?.GetValue<bool>() != true) return false;
                // Arm before writing: Android may reply before the write task resumes.
                pendingDial = pending with { Sent = true };
                try { write(); } catch { RevokeDial(peer.Id); throw; }
                return true;
            }
            var reference = body["command_ref"]!.GetValue<string>();
            if (!callCommands.TryGetValue(reference, out var command) || command.Sent || command.Kind + ".command" != kind ||
                command.PeerId != peer.Id || command.Identity != Convert.ToBase64String(peer.PublicKey) || command.Deadline <= Environment.TickCount64 ||
                command.CallRef != body["call_ref"]?.GetValue<string>()) return false;
            var current = calls.GetValueOrDefault(peer.Id);
            if (current is null || current["call_ref"]?.GetValue<string>() != command.CallRef ||
                current["state"]?.GetValue<string>() != body["expected_state"]?.GetValue<string>()) return false;
            var capability = command.Kind;
            var scoped = kind == "end_call.command" && current["state"]?.GetValue<string>() == "offhook" && OutgoingCallAllowed(peer, current);
            if (!RemoteCapability(peer, capability) || !scoped && (peer.Grants[capability]?.GetValue<bool>() != true ||
                store.LocalGrants()[capability]?.GetValue<bool>() != true) ||
                kind == "end_call.command" && current["revision"]?.GetValue<long>() != body["expected_revision"]?.GetValue<long>()) return false;
            callCommands[reference] = command with { Sent = true };
            try { write(); } catch { callCommands.TryRemove(reference, out _); throw; }
            return true;
        }
    }

    internal Dictionary<string, string> CallActionTokens(string id, string callRef, long revision)
    {
        lock (gate)
        {
            var peer = Peers.FirstOrDefault(value => value.Id == id && value.State == "paired");
            var current = calls.GetValueOrDefault(id);
            var local = store.LocalGrants();
            if (peer is null || !online.TryGetValue(id, out var connection) || current is null ||
                !IncomingCallCurrent(id, callRef, revision) ||
                current["call_ref"]?.GetValue<string>() != callRef || current["revision"]?.GetValue<long>() != revision ||
                !TelefonCallActions.IsRinging(current) || local["incoming_call_state"]?.GetValue<bool>() != true ||
                peer.Grants["incoming_call_state"]?.GetValue<bool>() != true || local["answer_call"]?.GetValue<bool>() != true) return [];
            var result = new Dictionary<string, string>();
            foreach (var (action, capability, version) in new[] { ("answer", "answer_call", 1), ("reject", "end_call", 2) })
                if (RemoteCapability(peer, capability) && peer.Grants[capability]?.GetValue<bool>() == true &&
                    local[capability]?.GetValue<bool>() == true && peer.Capabilities[capability]?["versions"] is JsonArray versions &&
                    versions.Any(value => value?.GetValue<int>() == version))
                    result[action] = callActions.Issue(id, Convert.ToBase64String(peer.PublicKey), connection, current, action);
            return result;
        }
    }

    internal bool CallEventCurrent(JsonObject payload)
    {
        lock (gate)
        {
            var current = calls.GetValueOrDefault(payload["device_id"]?.GetValue<string>() ?? "");
            return current is not null && current["call_ref"]?.GetValue<string>() == payload["call_ref"]?.GetValue<string>() &&
                current["revision"]?.GetValue<long>() == payload["revision"]?.GetValue<long>() &&
                current["state"]?.GetValue<string>() == payload["state"]?.GetValue<string>();
        }
    }

    internal bool IncomingCallCurrent(string id, string callRef, long revision)
    {
        lock (gate)
        {
            var peer = Peers.FirstOrDefault(p => p.Id == id);
            var current = calls.GetValueOrDefault(id);
            return peer is not null && peer.State == "paired" && online.ContainsKey(id) && current is not null &&
                current["call_ref"]?.GetValue<string>() == callRef && current["revision"]?.GetValue<long>() == revision &&
                TelefonCallActions.IsRinging(current) && Now() - (current["occurred_ms"]?.GetValue<long>() ?? 0) is >= 0 and <= 60_000 &&
                store.LocalGrants()["incoming_call_state"]?.GetValue<bool>() == true &&
                peer.Grants["incoming_call_state"]?.GetValue<bool>() == true &&
                peer.Capabilities["incoming_call_state"]?["available"]?.GetValue<bool>() == true &&
                peer.Capabilities["incoming_call_state"]?["versions"] is JsonArray versions && versions.Any(v => v?.GetValue<int>() == 2);
        }
    }

    internal async Task<bool> ExecuteCallActionAsync(string token)
    {
        TelefonCallActions.Ticket? ticket;
        Task<string> submission;
        lock (gate)
        {
            ticket = callActions.Take(token);
            if (ticket is null) return false;
            var peer = Peers.FirstOrDefault(value => value.Id == ticket.PeerId);
            if (peer is null || Convert.ToBase64String(peer.PublicKey) != ticket.Identity ||
                online.GetValueOrDefault(ticket.PeerId) != ticket.Connection ||
                !CallActionTokens(ticket.PeerId, ticket.CallRef, ticket.Revision).ContainsKey(ticket.Action)) return false;
            callActions.Invalidate(ticket.PeerId, ticket.CallRef);
            submission = ticket.Action == "answer"
                ? RequestAnswerAsync(ticket.PeerId, ticket.CallRef, Guid.NewGuid().ToString("D"))
                : RequestEndCallAsync(ticket.PeerId, ticket.CallRef, ticket.Revision, Guid.NewGuid().ToString("D"));
        }
        await submission;
        return true;
    }

    internal async Task<string> SendPersonalSyncAsync(string id, string kind, JsonObject body)
    {
        if (kind.StartsWith("personal_sync.custom_", StringComparison.Ordinal))
        {
            PersonalSyncContract.ValidateCustomBody(kind, body); RequireSolePeer(id);
            if (kind == "personal_sync.custom_settings") store.SetCustomSettings(id, body, false);
            else if (kind != "personal_sync.custom_batch" || !store.CustomAllowed(id, kind, body, true))
                throw new InvalidOperationException(T("Personal synchronization is not permitted on both devices."));
            var queued = store.Enqueue(id, kind, body, 86_400_000, Now(), body["trigger"]?.GetValue<string>() == "auto_wifi" ? "wifi_only" : "any");
            TelefonConnection? customConnection; lock (gate) online.TryGetValue(id, out customConnection);
            if (customConnection is not null) await customConnection.PumpOutboxNowAsync();
            await ReportStatusAsync(); return queued;
        }
        PersonalSyncContract.ValidateBody(kind, body); var peer = RequireSolePeer(id); var now = Now(); PersonalSyncRun? run = null;
        if (kind != "personal_sync.request") run = personalSync.LoadRun(id, body["run_id"]!.GetValue<string>(), now) ?? throw new InvalidOperationException(T("The personal synchronization request is missing."));
        if (kind is "personal_sync.batch" or "personal_sync.report" && body["format"]!.GetValue<int>() != run!.Request["format"]!.GetValue<int>())
            throw new InvalidDataException(T("The personal synchronization run does not match."));
        var needed = PersonalGrants(kind, body, run?.Request);
        var settings = store.PersonalSettings(id);
        if (!settings.OwnDevice || !settings.RemoteOwnDevice || needed.Count == 0 || needed.Any(name => store.LocalGrants()[name]?.GetValue<bool>() != true || peer.Grants[name]?.GetValue<bool>() != true)) throw new InvalidOperationException(T("Personal synchronization is not permitted on both devices."));
        if (body["format"]?.GetValue<int>() == 2 && !SupportsPersonalFormat2(peer)) throw new InvalidOperationException(T("Personal synchronization format 2 was not negotiated."));
        if (body["format"]?.GetValue<int>() == 3 && needed.Any(name => !SupportsPersonalFormat(peer, name, 3))) throw new InvalidOperationException(T("Personal synchronization format 3 was not negotiated."));
        string policy;
        if (kind == "personal_sync.request") { personalSync.RememberRun(id, body, now); policy = body["trigger"]?.GetValue<string>() == "auto_wifi" ? "wifi_only" : "any"; }
        else { if (run!.Expired) throw new InvalidOperationException(T("The personal synchronization run has expired.")); policy = run.Policy; }
        TelefonConnection? connection; lock (gate) online.TryGetValue(id, out connection); var ttl = kind == "personal_sync.request" ? 3_600_000 : 86_400_000; var messageId = store.Enqueue(id, kind, body, ttl, now, policy);
        if (connection is not null) await connection.PumpOutboxNowAsync(); return messageId;
    }

    internal JsonObject CustomSettings(string id) => store.CustomSettings(id);

    internal async Task SetPersonalSyncAsync(string id, bool ownDevice, bool autoWifi)
    {
        RequireSolePeer(id); if (!ownDevice) personalSync.PurgeProtocol(id); store.SetPersonalSettings(id, ownDevice: ownDevice, autoWifi: ownDevice && autoWifi);
        TelefonConnection? connection; lock (gate) online.TryGetValue(id, out connection); if (connection is not null) await connection.SendMessageAsync("personal_sync.settings", new JsonObject { ["format"] = 1, ["own_device"] = ownDevice }, 86_400_000); await ReportStatusAsync();
    }

    internal bool CommitPersonalSync(string id, string messageId, string commitToken, string outcome)
    {
        if (outcome is not ("applied" or "conflict" or "restore_unavailable" or "invalid" or "temporary" or "timeout")) throw new InvalidDataException(T("The personal synchronization result is invalid."));
        if (outcome == "timeout") outcome = "temporary";
        var decisionHandled = personalSync.CommitDecisionIntent(id, messageId, commitToken, outcome, Now());
        var committed = outcome == "applied" && (decisionHandled || personalSync.CommitBatch(id, messageId, commitToken, Now(), out _));
        lock (gate) if (personalCommits.Remove(commitToken, out var pending) && pending.PeerId == id) pending.Completion.TrySetResult(committed ? "applied" : outcome);
        return committed;
    }

    internal async Task ReplayPersonalSyncAsync()
    {
        if (store.RestoreFenced) return;
        personalSync.CleanupExpiredRuns(Now());
        foreach (var batch in personalSync.ReadyBatches(Now())) await CompleteOrRequestAttachmentsAsync(batch, true);
        foreach (var peer in Peers) foreach (var run in personalSync.CurrentRuns(peer.Id, Now())) await ReleasePersonalReportAsync(peer.Id, run.RunId);
        foreach (var intent in personalSync.DecisionIntents(Now())) await EmitPersonalIntentAsync(intent, "wifi");
    }

    internal async Task StagePersonalReportAsync(string id, JsonObject body)
    {
        var run = personalSync.LoadRun(id, body["run_id"]!.GetValue<string>(), Now()) ?? throw new InvalidDataException(T("The personal synchronization request is missing."));
        if (run.Expired) throw new InvalidDataException(T("The personal synchronization run has expired."));
        personalSync.StageReport(id, body); await ReleasePersonalReportAsync(id, run.RunId);
    }

    internal void StagePersonalAttachment(string id, string runId, bool reply, string recordsHash,
        JsonObject descriptor, string direction, long expiresMs, IEnumerable<(int Index, byte[] Data)> chunks)
    {
        var run = personalSync.LoadRun(id, runId, Now()) ?? throw new InvalidDataException(T("The personal synchronization request is missing."));
        if (run.Expired) throw new InvalidDataException(T("The personal synchronization run has expired."));
        personalSync.StageAttachment(id, runId, reply, recordsHash, descriptor, direction, run.Policy, Math.Min(expiresMs, run.ExpiresMs), chunks);
    }

    internal void StagePersonalAttachmentChunk(string id, JsonObject body, byte[] data, long expiresMs) =>
        personalSync.StageAttachmentChunk(id, body["run_id"]!.GetValue<string>(), body["reply"]!.GetValue<bool>(),
            body["records_hash"]!.GetValue<string>(), body["sha256"]!.GetValue<string>(), "incoming",
            body["index"]!.GetValue<int>(), data, expiresMs);

    internal byte[] ReadPersonalAttachment(string id, string runId, bool reply, string recordsHash,
        string hash, string direction, string transport) => personalSync.ReadVerifiedAttachment(id, runId, reply,
            recordsHash, hash, direction, transport, Now());

    internal IReadOnlyList<(int Start, int End)> MissingPersonalAttachmentRanges(string id, string runId,
        bool reply, string recordsHash, string hash, string direction) => personalSync.MissingAttachmentRanges(
            id, runId, reply, recordsHash, hash, direction, Now());

    internal JsonObject? CachedDeviceStatus(string id)
    {
        var status = store.LoadStatus(id); if (status is null) return null;
        lock (gate) status["online"] = online.ContainsKey(id);
        return status;
    }

    internal async Task ReportStatusAsync()
    {
        store.Cleanup(Now());
        var peers = store.LoadPeers().Select(peer => new
        {
            kennung = peer.Id, name = peer.Name, fingerabdruck = TelefonCrypto.Fingerprint(peer.PublicKey),
            state = peer.State,
            online = IsOnline(peer.Id), transport = OnlineTransport(peer.Id),
            dial_request = IsOnline(peer.Id) && RemoteCapability(peer, "dial_request") && peer.Grants["dial_request"]?.GetValue<bool>() == true,
            bluetooth_address = store.BluetoothAddress(peer.Id),
            zuletzt = peer.LastSeenMs, bluetooth = new { available = TelefonBluetoothSupport.Available,
                reason = TelefonBluetoothSupport.Reason, blocker = TelefonBluetoothSupport.Blocker }
        }).ToArray();
        byte[]? token; long until;
        lock (gate) { token = pairingToken; until = pairingUntil; }
        await emit("App.telefonVerbindungStand", new { moeglich = true, an = Enabled, laeuft = IsRunning,
            port = Port, dienst = ServiceType, name = identity.Name, kennung = identity.Id,
            fingerabdruck = TelefonCrypto.Fingerprint(identity.PublicKey), paarungOffen = token is not null,
            paarungBis = until, telefone = peers, fehler = error,
            binding_conflict = store.LoadPeers().Count > 1, capabilities = TelefonProtocolContract.DesktopCapabilities()["items"],
            grants = store.LocalGrants(), kdeconnect = await kdeStatus(),
            bluetooth = new { available = TelefonBluetoothSupport.Available, reason = TelefonBluetoothSupport.Reason,
                blocker = TelefonBluetoothSupport.Blocker } });
    }

    private bool IsOnline(string id) { lock (gate) return online.ContainsKey(id); }
    private string OnlineTransport(string id) { lock (gate) return online.TryGetValue(id, out var connection) ? connection.Transport : "offline"; }

    private async Task StartAsync()
    {
        await lifecycle.WaitAsync().ConfigureAwait(false);
        try
        {
        lock (gate)
        {
            if (disposed || serviceCancellation is not null || !Enabled) return;
            if (store.RestoreFenced) { error = T("Restore failed."); return; }
            try
            {
                serviceCancellation = new CancellationTokenSource();
                listener = localOnly ? new TcpListener(IPAddress.Loopback, 0) : new TcpListener(IPAddress.IPv6Any, Port);
                if (!localOnly) listener.Server.DualMode = true;
                listener.Start(8); error = "";
                EnsurePairingAvailableLocked();
                var bluetoothCancellation = serviceCancellation.Token;
                var currentListener = listener;
                Track(Task.Run(() => AcceptLoopAsync(currentListener, bluetoothCancellation)));
                if (bluetoothClient is not null) Track(Task.Run(() => BluetoothReconnectLoopAsync(bluetoothCancellation)));
                try
                {
                    if (!localOnly)
                    {
                        mdns = new TelefonMdnsPublisher(identity.Id, identity.Name, CurrentPairingToken, serviceCancellation.Token);
                        Track(Task.Run(mdns.RunAsync));
                    }
                }
                catch (SocketException) { mdns = null; }
            }
            catch (Exception exception) { listener?.Stop(); listener = null; serviceCancellation?.Dispose(); serviceCancellation = null; error = string.Format(T("TCP port {0} could not be opened: {1}"), Port, exception.Message); }
        }
        if (!localOnly) StartBluetooth();
        }
        finally { lifecycle.Release(); }
    }

    private async Task BluetoothReconnectLoopAsync(CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                foreach (var peer in StatusPeers)
                {
                    var address = store.BluetoothAddress(peer.Id);
                    if (Volatile.Read(ref pairingBusy) != 0 || !TelefonBluetoothClient.ValidAddress(address) || IsOnline(peer.Id)) continue;
                    using var link = await bluetoothClient!.ConnectAsync(address, cancellation);
                    using var registration = cancellation.Register(link.Dispose);
                    if (link.Address != address || IsOnline(peer.Id)) continue;
                    await HandleLimitedStreamAsync(link.Stream, cancellation, "bluetooth", "bluetooth:" + address, peer.Id);
                }
            }
            catch (Exception) when (!cancellation.IsCancellationRequested) { }
            try { await Task.Delay(1000, cancellation); } catch (OperationCanceledException) { return; }
        }
    }

#if WINDOWS
    private TelefonBluetoothTransport? bluetooth;

    /// <summary>
    /// Veröffentlicht denselben Rahmenverkehr zusätzlich über Bluetooth-RFCOMM.
    /// Der Start läuft im Hintergrund; das Ergebnis wird als Capability und in
    /// der Oberfläche gemeldet, damit ein fehlendes oder gesperrtes Funkgerät
    /// sichtbar wird statt stillschweigend zu scheitern.
    /// </summary>
    private void StartBluetooth()
    {
        TelefonBluetoothTransport transport;
        lock (gate)
        {
            if (serviceCancellation is null || bluetooth is not null) return;
            transport = bluetooth = new TelefonBluetoothTransport(BluetoothService,
                (stream, token) => HandleLimitedStreamAsync(stream, token, "bluetooth"));
        }
        Track(Task.Run(async () =>
        {
            var (reason, message) = await transport.StartAsync();
            TelefonBluetoothSupport.Report(reason == "available", reason, message);
            /* Das Ergebnis gehört ins Protokoll. Bisher ging es ausschließlich an
               die Oberfläche, wo ein fehlgeschlagener Start nur als abgeschalteter
               Schalter erschien – ohne Grund und ohne Spur in telefon.log. Damit
               war von außen nicht zu unterscheiden, ob Bluetooth fehlt, gesperrt
               ist oder der Dienst schlicht nicht veröffentlicht werden konnte. */
            Log("bluetooth", "start", reason == "available"
                ? "RFCOMM-Dienst veröffentlicht."
                : $"RFCOMM-Dienst nicht veröffentlicht ({reason}): {message}");
            try { await ReportStatusAsync(); } catch (Exception) { }
        }));
    }

    private async Task StopBluetoothAsync()
    {
        TelefonBluetoothTransport? current;
        lock (gate) { current = bluetooth; bluetooth = null; }
        if (current is null) return;
        await current.ShutdownAsync().ConfigureAwait(false);
        TelefonBluetoothSupport.Report(false, "disabled",
            "Die Magnolie-Telefonverbindung ist ausgeschaltet; der Bluetooth-Dienst wird nicht veröffentlicht.");
    }
#else
    private static void StartBluetooth() { }
    private static Task StopBluetoothAsync() => Task.CompletedTask;
#endif

    private async Task StopAsync()
    {
        await lifecycle.WaitAsync().ConfigureAwait(false);
        try
        {
        CancellationTokenSource? cancellation; TelefonConnection[] connections;
        lock (gate)
        {
            cancellation = serviceCancellation; serviceCancellation = null; listener?.Stop(); listener = null; mdns?.Dispose(); mdns = null;
            pairingToken = null; pairingUntil = 0; connections = online.Values.ToArray(); online.Clear();
            if (pendingDial is { } pendingCall) RevokeDial(pendingCall.PeerId);
            pendingDial = null; callCommands.Clear(); calls.Clear(); callActions.Clear();
            setupPairing?.Deadline.Cancel(); setupPairing?.Deadline.Dispose(); setupPairing = null;
            foreach (var confirmation in confirmations.Values) confirmation.TrySetResult(false); confirmations.Clear();
            foreach (var pending in personalCommits.Values) pending.Completion.TrySetResult("temporary"); personalCommits.Clear();
        }
        cancellation?.Cancel(); foreach (var connection in connections) connection.Dispose();
        await StopBluetoothAsync().ConfigureAwait(false);
        while (!workers.IsEmpty)
        {
            try { await Task.WhenAll(workers.Keys).ConfigureAwait(false); } catch (Exception) { }
        }
        cancellation?.Dispose();
        await radioSwitch.ReleaseAllAsync().ConfigureAwait(false);
        }
        finally { lifecycle.Release(); }
    }

    private async Task AcceptLoopAsync(TcpListener currentListener, CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                var client = await currentListener.AcceptTcpClientAsync(cancellation); client.ReceiveTimeout = 75_000; client.SendTimeout = 75_000;
                Track(Task.Run(() => HandleClientAsync(client, cancellation), CancellationToken.None));
            }
            catch (OperationCanceledException) { break; }
            catch (Exception) when (cancellation.IsCancellationRequested) { break; }
        }
    }

    private byte[]? CurrentPairingToken()
    {
        lock (gate) return pairingToken is not null && pairingUntil >= DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            ? pairingToken.ToArray() : null;
    }

    private void EnsurePairingAvailableLocked()
    {
        if (Enabled && serviceCancellation is not null && store.LoadPeers().Count == 0 && pairingToken is null)
        {
            pairingToken = RandomNumberGenerator.GetBytes(16);
            pairingUntil = long.MaxValue;
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken cancellation)
    {
        using (client) await HandleLimitedStreamAsync(client.GetStream(), cancellation, "wifi",
            (client.Client.RemoteEndPoint as IPEndPoint)?.Address.MapToIPv4().ToString());
    }

    private async Task HandleLimitedStreamAsync(Stream stream, CancellationToken cancellation, string transport, string? source = null, string? expectedPeer = null)
    {
        if (!await streamSlots.WaitAsync(0, cancellation)) return;
        try { await HandleStreamAsync(stream, cancellation, transport, source, expectedPeer); }
        finally { streamSlots.Release(); }
    }

    /// <summary>
    /// Führt einen eingehenden Datenstrom durch Paarung oder Sitzung. Der
    /// Transport bleibt dabei offen: WLAN liefert einen
    /// <see cref="NetworkStream"/>, die Bluetooth-RFCOMM-Anbindung einen
    /// Socket-Datenstrom. Beide tragen dieselben verschlüsselten Rahmen.
    /// </summary>
    internal async Task HandleStreamAsync(Stream stream, CancellationToken cancellation,
        string transport = "wifi", string? source = null, string? expectedPeer = null)
    {
        var type = "";
        try
        {
            JsonObject first;
            using (var handshake = CancellationTokenSource.CreateLinkedTokenSource(cancellation))
            {
                handshake.CancelAfter(TimeSpan.FromSeconds(15));
                first = await ReadFrameAsync(stream, 65_536, handshake.Token);
            }
            type = first["type"]?.GetValue<string>() ?? "";
            if (type == "pair_init")
            {
                /* Ein zweiter gleichzeitiger Versuch wird ohne Antwort beendet.
                   Der laufende behält damit seinen angezeigten Code; das Telefon
                   sieht einen Verbindungsabbruch und kann erneut versuchen. */
                if (Interlocked.CompareExchange(ref pairingBusy, 1, 0) != 0)
                {
                    Log(transport, "pair_init", "Abgewiesen: es läuft bereits eine Paarung.");
                    return;
                }
                try { await PairAsync(stream, first, cancellation, source); }
                finally { Interlocked.Exchange(ref pairingBusy, 0); }
            }
            else if (type == "pair_finish") await RetryPairFinishAsync(stream, first, cancellation);
            else if (type == "session_start")
            {
                if (expectedPeer is not null && first["from"]?.GetValue<string>() != expectedPeer) throw new CryptographicException("Wrong Bluetooth peer.");
                await SessionAsync(stream, first, cancellation, transport);
            }
            else Log(transport, type, "Unbekannter Rahmentyp.");
        }
        catch (OperationCanceledException) { }
        catch (Exception failure)
        {
            /* Bisher blieb hier jeder Fehler stumm. Eine gescheiterte Paarung
               war dadurch weder im Programm noch im Protokoll nachvollziehbar. */
            var reason = PairingReason(failure);
            Log(transport, type, $"{failure.GetType().Name}: {failure.Message}");
            if (type is "pair_init" or "pair_finish")
                try { await emit("App.telefonFehler", new { fehler = reason }); } catch (Exception) { }
        }
    }

    /// <summary>Übersetzt einen Paarungsfehler in einen für den Benutzer brauchbaren Satz.</summary>
    private static string PairingReason(Exception failure) => failure switch
    {
        CryptographicException { Message: "binding_conflict" } =>
            T("Another phone is already paired. Remove it first."),
        CryptographicException =>
            T("Pairing was rejected cryptographically. The confirmation code, pairing code, or phone key does not match. Restart pairing on both devices."),
        InvalidOperationException invalid => invalid.Message,
        InvalidDataException =>
            T("The phone sent a message unknown to this phone protocol. Organizer and Magnolie Notes must use the same protocol version."),
        IOException or System.Net.Sockets.SocketException =>
            T("The connection to the phone was interrupted during pairing."),
        _ => T("Pairing failed:") + " " + failure.Message
    };

    private void Log(string transport, string stage, string message)
    {
        RotatingLog.Append(logPath, $"{DateTimeOffset.Now:O} transport={transport} stage={stage} {message}");
    }

    private async Task PairAsync(Stream stream, JsonObject init, CancellationToken cancellation, string? source)
    {
        byte[] expectedToken;
        SetupPairing? setup;
        lock (gate)
        {
            if (pairingToken is null || pairingUntil < DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()) throw new InvalidOperationException();
            expectedToken = pairingToken.ToArray();
            setup = setupPairing;
        }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellation, setup?.Deadline.Token ?? CancellationToken.None);
        cancellation = lifetime.Token;
        cancellation.ThrowIfCancellationRequested();
        Require(init, "p", "type", "pairing_token", "device_id", "role", "display_name", "static_public", "ephemeral_public", "nonce", "versions");
        if (init["p"]?.GetValue<string>() != TelefonCrypto.Protocol || init["role"]?.GetValue<string>() != "phone" ||
            init["type"]?.GetValue<string>() != "pair_init" || init["versions"] is not JsonArray versions ||
            versions.Count is < 1 or > 16 || versions.Select(ProtocolVersion).Distinct().Count() != versions.Count ||
            !versions.Any(value => ProtocolVersion(value) == 1)) throw new InvalidDataException();
        var sentToken = TelefonCrypto.StrictBase64(init, "pairing_token", 16);
        if (!CryptographicOperations.FixedTimeEquals(sentToken, expectedToken)) throw new CryptographicException();
        var peerId = CanonicalUuid(init, "device_id"); var peerName = DisplayName(init, "display_name");
        if (setup is not null && (setup.Target != peerId || setup.Address != source)) throw new CryptographicException("Wrong setup target.");
        var peerStatic = TelefonCrypto.StrictBase64(init, "static_public", 32); var peerEphemeral = TelefonCrypto.StrictBase64(init, "ephemeral_public", 32);
        _ = TelefonCrypto.StrictBase64(init, "nonce", 32);
        var existing = store.LoadPeers().FirstOrDefault(peer => peer.Id == peerId);
        if (store.LoadPeers().Any(peer => peer.Id != peerId)) throw new CryptographicException("binding_conflict");
        if (existing is not null && !existing.PublicKey.SequenceEqual(peerStatic)) throw new CryptographicException("Schlüsselwechsel abgewiesen.");
        var ephemeral = TelefonCrypto.GenerateX25519();
        var response = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_response", ["device_id"] = identity.Id,
            ["role"] = "desktop", ["display_name"] = identity.Name, ["static_public"] = Convert.ToBase64String(identity.PublicKey),
            ["ephemeral_public"] = Convert.ToBase64String(ephemeral.Public), ["nonce"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)), ["version"] = 1 };
        await WriteFrameAsync(stream, response, cancellation);
        using var secrets = TelefonCrypto.Pairing(ephemeral.Private, peerEphemeral, identity.PrivateKey, peerStatic, init, response);
        CryptographicOperations.ZeroMemory(ephemeral.Private);
        var confirmation = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (gate) confirmations[peerId] = confirmation;
        Log("", "pair_init", $"Paarung begonnen mit {peerId}; Code angezeigt.");
        await emit("App.telefonPaarung", new { offen = true, code = secrets.Code, kennung = peerId, name = peerName,
            fingerabdruck = TelefonCrypto.Fingerprint(peerStatic), fehler = "", sekunden = 120 });
        var phoneConfirm = await ReadFrameWithinAsync(stream, 65_536, TimeSpan.FromSeconds(30), cancellation);
        ValidateProof(phoneConfirm, "pair_confirm", "phone", "confirm", secrets);
        Log("", "pair_confirm", "Bestätigung des Telefons geprüft; warte auf Bestätigung am Rechner.");
        bool accepted;
        try { accepted = await confirmation.Task.WaitAsync(TimeSpan.FromSeconds(120), cancellation); }
        catch (TimeoutException) { await WriteFrameAsync(stream, new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_abort", ["reason"] = "timeout" }, cancellation); return; }
        if (!accepted) { await WriteFrameAsync(stream, new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_abort", ["reason"] = "user_cancelled" }, cancellation); return; }
        lock (gate)
        {
        cancellation.ThrowIfCancellationRequested();
        var bluetoothAddress = setup?.Address.StartsWith("bluetooth:", StringComparison.Ordinal) == true ? setup.Address[10..] : "";
        store.SavePending(new TelefonPeer(peerId, peerName, peerStatic, BluetoothAddress: bluetoothAddress), secrets.Transcript,
            TelefonCrypto.PairProof(secrets.Key, "finish", "phone", secrets.Transcript),
            TelefonCrypto.PairProof(secrets.Key, "finish", "desktop", secrets.Transcript),
            DateTimeOffset.UtcNow.AddMinutes(10).ToUnixTimeMilliseconds());
        }
        Log("", "pair_confirm", "Am Rechner bestätigt und vorgemerkt.");
        await WriteFrameAsync(stream, Proof("pair_confirm", "desktop", "confirm", secrets), cancellation);
        var phoneFinish = await ReadFrameWithinAsync(stream, 65_536, TimeSpan.FromSeconds(15), cancellation);
        ValidateProof(phoneFinish, "pair_finish", "phone", "finish", secrets);
        if (!store.TryFinishPending(peerId, TelefonCrypto.StrictBase64(phoneFinish, "transcript", 32), TelefonCrypto.StrictBase64(phoneFinish, "proof", 32),
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), out _, out var desktopFinish))
            throw new CryptographicException("Der Abschlussnachweis des Telefons passt nicht zur vorgemerkten Paarung.");
        await WriteFrameAsync(stream, desktopFinish, cancellation);
        Log("", "pair_finish", $"Paarung mit {peerId} abgeschlossen.");
        lock (gate) { pairingToken = null; pairingUntil = 0; }
        await emit("App.telefonPaarung", new { offen = false, fertig = true, code = "", kennung = peerId, name = peerName, fehler = "" });
        await ReportStatusAsync();
    }

    private async Task RetryPairFinishAsync(Stream stream, JsonObject value, CancellationToken cancellation)
    {
        Require(value, "p", "type", "side", "transcript", "proof");
        if (value["p"]?.GetValue<string>() != TelefonCrypto.Protocol || value["type"]?.GetValue<string>() != "pair_finish" || value["side"]?.GetValue<string>() != "phone") throw new InvalidDataException();
        if (!store.TryFinishPending(TelefonCrypto.StrictBase64(value, "transcript", 32), TelefonCrypto.StrictBase64(value, "proof", 32),
            DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), out var peer, out var finish)) throw new CryptographicException();
        await WriteFrameAsync(stream, finish, cancellation);
        await emit("App.telefonPaarung", new { offen = false, fertig = true, code = "", kennung = peer.Id, name = peer.Name, fehler = "" });
        await ReportStatusAsync();
    }

    private async Task SessionAsync(Stream stream, JsonObject start, CancellationToken cancellation, string transport)
    {
        Require(start, "p", "type", "sid", "from", "to", "initiator_role", "ephemeral_public", "nonce", "versions", "mac");
        var peerId = CanonicalUuid(start, "from"); var peer = Peers.FirstOrDefault(value => value.Id == peerId) ?? throw new CryptographicException();
        if (start["p"]?.GetValue<string>() != TelefonCrypto.Protocol || start["type"]?.GetValue<string>() != "session_start" ||
            start["to"]?.GetValue<string>() != identity.Id || start["initiator_role"]?.GetValue<string>() != "phone" ||
            start["versions"] is not JsonArray versions || versions.Count is < 1 or > 16 ||
            versions.Select(ProtocolVersion).Distinct().Count() != versions.Count || !versions.Any(value => ProtocolVersion(value) == 1))
            throw new CryptographicException();
        var shared = Array.Empty<byte>(); var root = Array.Empty<byte>(); var auth = Array.Empty<byte>();
        var ephemeralPrivate = Array.Empty<byte>(); var sessionShared = Array.Empty<byte>(); var material = Array.Empty<byte>();
        TelefonConnection? connection = null;
        try
        {
            var sid = TelefonCrypto.StrictBase64(start, "sid", 16); var peerEphemeral = TelefonCrypto.StrictBase64(start, "ephemeral_public", 32); _ = TelefonCrypto.StrictBase64(start, "nonce", 32);
            var ids = Encoding.UTF8.GetBytes(new[] { identity.Id, peer.Id }.Order(StringComparer.Ordinal).Aggregate((left, right) => left + "\0" + right));
            shared = TelefonCrypto.X25519(identity.PrivateKey, peer.PublicKey);
            root = TelefonCrypto.Hkdf(shared, SHA256.HashData(Encoding.UTF8.GetBytes("magnolie-phone-fs1/static-salt\0").Concat(ids).ToArray()), Encoding.UTF8.GetBytes("magnolie-phone-fs1/static-root\0").Concat(ids).ToArray(), 32);
            auth = TelefonCrypto.Hkdf(root, null, Encoding.UTF8.GetBytes("magnolie-phone-fs1/auth\0"), 32);
            VerifyMac(auth, "magnolie-phone-fs1/start\0", start);
            var ephemeral = TelefonCrypto.GenerateX25519(); ephemeralPrivate = ephemeral.Private;
            var response = new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "session_response", ["sid"] = Convert.ToBase64String(sid),
                ["from"] = identity.Id, ["to"] = peer.Id, ["ephemeral_public"] = Convert.ToBase64String(ephemeral.Public),
                ["nonce"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)), ["version"] = 1 };
            response["mac"] = Convert.ToBase64String(Hmac(auth, "magnolie-phone-fs1/response\0", TelefonCrypto.Canonical(start).Concat(TelefonCrypto.Canonical(response)).ToArray()));
            await WriteFrameAsync(stream, response, cancellation);
            var transcript = SHA256.HashData(TelefonCrypto.Canonical(start).Concat(TelefonCrypto.Canonical(response)).ToArray());
            sessionShared = TelefonCrypto.X25519(ephemeralPrivate, peerEphemeral);
            var salt = Hmac(root, "magnolie-phone-fs1/session-salt\0", transcript);
            material = TelefonCrypto.Hkdf(sessionShared, salt, Encoding.UTF8.GetBytes("magnolie-phone-fs1/session-keys\0").Concat(transcript).ToArray(), 72);
            connection = new TelefonConnection(peer, stream, sid, material, store,
                (source, message) => HandleMessageAsync(source, message, transport), cancellation, transport,
                body => emit("App.personalCustomAck", new { device_id = peer.Id, body }), AuthorizeCall, SendCall);
            var capabilityRevision = store.NextOwnRevision("capabilities"); var grantRevision = store.NextOwnRevision("grants");
            await connection.InitializeAsync(capabilityRevision);
            lock (gate)
            {
                if (store.RestoreFenced || !Peers.Any(p => p.Id == peer.Id && p.PublicKey.SequenceEqual(peer.PublicKey))) return;
                if (transport == "bluetooth" && online.TryGetValue(peer.Id, out var wifi) && wifi.Transport == "wifi") return;
                if (online.Remove(peer.Id, out var previous)) previous.Dispose();
                if (pendingDial?.PeerId != peer.Id || pendingDial.Identity != Convert.ToBase64String(peer.PublicKey)) calls.Remove(peer.Id);
                online[peer.Id] = connection;
            }
            await connection.SendCapabilitiesAsync(capabilityRevision);
            await connection.SendGrantsAsync(grantRevision, store.LocalGrants());
            if (store.CustomSupported(peer.Id) && store.CustomSettings(peer.Id)["local"] is JsonObject customSettings)
                await connection.SendMessageAsync("personal_sync.custom_settings", customSettings, 86_400_000);
            await ReportStatusAsync();
            await connection.RunAsync();
        }
        finally
        {
            var unpaired = connection?.RemoteCloseReason == "unpaired";
            var removedConnection = false;
            lock (gate) if (connection is not null && online.TryGetValue(peer.Id, out var current) &&
                ReferenceEquals(current, connection)) removedConnection = online.Remove(peer.Id);
            connection?.Dispose();
            if (removedConnection) await radioSwitch.ReleaseAllAsync(peer.Id).ConfigureAwait(false);
            foreach (var secret in new[] { shared, root, auth, ephemeralPrivate, sessionShared, material })
                CryptographicOperations.ZeroMemory(secret);
            try
            {
                if (unpaired) await RemoveAsync(peer.Id);
                else if (connection is not null) await ReportStatusAsync();
            }
            catch (Exception) { }
        }
    }

    private async Task<TelefonAck?> HandleMessageAsync(TelefonPeer peer, JsonObject message, string transport)
    {
        if (message["type"]?.GetValue<string>() != "message") return null;
        var kind = message["kind"]?.GetValue<string>() ?? "";
        if (kind is "capabilities.update" or "grants.update") { lock (gate) callActions.Clear(); }
        if (kind == "capabilities.update" && message["body"] is JsonObject capabilities)
        {
            var revision = TelefonProtocolContract.ValidateCapabilities(capabilities);
            lock (gate)
            {
                store.UpdatePeerProtocol(peer.Id, revision, capabilities["items"]!.AsObject(), 0, null);
                if (Peers.FirstOrDefault(p => p.Id == peer.Id) is not { } current || !RemoteCapability(current, "dial_request") ||
                    pendingDial is { Scoped: true } && !SupportsScopedDial(current)) RevokeDial(peer.Id);
            }
            await ReportStatusAsync(); return null;
        }
        if (kind == "grants.update" && message["body"] is JsonObject grants)
        {
            var revision = TelefonProtocolContract.ValidateGrants(grants); var values = grants["grants"]!.AsObject();
            if (values["personal_notes_sync"]?.GetValue<bool>() != true) personalSync.PurgeModules(peer.Id, new HashSet<string>(StringComparer.Ordinal) { "notes" });
            if (values["personal_tasks_sync"]?.GetValue<bool>() != true) personalSync.PurgeModules(peer.Id, new HashSet<string>(StringComparer.Ordinal) { "tasks" });
            if (values["personal_deletions_sync"]?.GetValue<bool>() != true) personalSync.PurgeDeletionProtocol(peer.Id);
            lock (gate)
            {
                store.UpdatePeerProtocol(peer.Id, 0, null, revision, values);
                if (values["dial_request"]?.GetValue<bool>() != true) RevokeDial(peer.Id);
            }
            await ReportStatusAsync(); return null;
        }
        if (message["body"] is not JsonObject body) return null;
        if (kind.StartsWith("personal_sync.custom_", StringComparison.Ordinal))
        {
            if (!store.CustomAllowed(peer.Id, kind, body, false) || kind == "personal_sync.custom_batch" ||
                (body["trigger"]?.GetValue<string>() == "auto_wifi" && transport != "wifi"))
                return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", "not_granted");
            if (kind == "personal_sync.custom_settings")
            {
                store.SetCustomSettings(peer.Id, body, true);
                if (store.CustomSettings(peer.Id)["local"] is null)
                    await SendPersonalSyncAsync(peer.Id, kind, TelefonStore.NewCustomSettings(false, 1));
                await ReportStatusAsync();
            }
            else await emit("App.personalCustomRequest", new { device_id = peer.Id, trigger = body["trigger"]!.GetValue<string>() });
            return null;
        }
        if (kind == "selected_notifications_readonly.event")
        { var copy = body.DeepClone().AsObject(); copy["kennung"] = peer.Id; copy["telefonName"] = peer.Name; await emit("App.telefonBenachrichtigung", copy); return null; }
        if (kind == "dial_request.result")
        {
            lock (gate)
            {
                if (AuthorizeCall(peer, kind, body) is { } denial) return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", denial);
                if (!store.UpdateCommand(peer.Id, body["client_ref"]!.GetValue<string>(), body["state"]!.GetValue<string>())) throw new InvalidDataException("Unbekannter Wählauftrag.");
                if (body["state"]?.GetValue<string>() == "failed" && pendingDial is { } pending)
                    pendingDial = pending with { Ended = true, Deadline = Environment.TickCount64 + 60_000 };
            }
            await emit("App.telefonWaehlstatus", WithPeer(body, peer)); return null;
        }
        if (kind is "answer_call.result" or "end_call.result")
        {
            lock (gate)
            {
                if (AuthorizeCall(peer, kind, body) is { } denial) return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", denial);
                var reference = body["command_ref"]!.GetValue<string>();
                if (!store.UpdateCommand(peer.Id, reference, body["state"]!.GetValue<string>())) throw new InvalidDataException("Unbekannter Anrufauftrag.");
                callCommands.TryRemove(reference, out _);
            }
            await emit(kind == "answer_call.result" ? "App.telefonAnnehmstatus" : "App.telefonAuflegestatus", WithPeer(body, peer)); return null;
        }
        if (kind == "incoming_call_state.event")
        {
            JsonObject payload;
            lock (gate)
            {
                if (AuthorizeCall(peer, kind, body) is { } denial) return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", denial);
                var disposition = IncomingCallDisposition(CurrentCall(peer.Id), body);
                if (disposition == "duplicate") return new TelefonAck(message["message_id"]!.GetValue<string>(), "duplicate", "none");
                if (disposition == "conflict") return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", "invalid_schema");
                calls[peer.Id] = body.DeepClone().AsObject();
                payload = WithPeer(body, peer);
                if (OutgoingCallAllowed(Peers.First(p => p.Id == peer.Id), body, requireScoped: false) && pendingDial is { } pending)
                {
                    payload["outgoing_authorized"] = pending.Scoped;
                    payload["end_authorized"] = pending.Scoped && body["state"]?.GetValue<string>() == "offhook" && RemoteCapability(Peers.First(p => p.Id == peer.Id), "end_call");
                    pendingDial = pending with { StartedMs = body["started_ms"]!.GetValue<long>(),
                        Ended = body["state"]?.GetValue<string>() == "idle",
                        Deadline = body["state"]?.GetValue<string>() == "idle" ? Environment.TickCount64 + 60_000 :
                            pending.StartedMs == 0 ? Environment.TickCount64 + 4 * 60 * 60_000 : pending.Deadline };
                }
            }
            /* Klingelt es oder wird gesprochen, muss der Bluetooth-Funk an
               sein, damit das Telefon den Ton hierher legen kann. Bei „idle“
               wird der vorherige Zustand wiederhergestellt. Ein etwaiger
               Wählauftrag desselben Telefons ist damit ebenfalls erledigt. */
            var callState = body["state"]?.GetValue<string>() ?? "";
            if (callState is "ringing" or "offhook")
            {
                await radioSwitch.RequestAsync("anruf/" + peer.Id);
                await radioSwitch.ReleaseAsync("waehlen/" + peer.Id);
            }
            else if (callState == "idle") await radioSwitch.ReleaseAllAsync(peer.Id);
            Task delivery;
            lock (gate)
            {
                if (!online.ContainsKey(peer.Id) || !CallEventCurrent(payload) ||
                    payload["outgoing_authorized"]?.GetValue<bool>() == true && pendingDial?.CallRef != body["call_ref"]?.GetValue<string>()) return null;
                delivery = emit("App.telefonEingehenderAnruf", PhoneRegionInfo.Enrich(payload));
            }
            await delivery; return null;
        }
        if (TelefonProtocolContract.PersonalKinds.Contains(kind)) return await HandlePersonalMessageAsync(peer, message, body, transport);
        if (kind != "device_status.report") return null;
        TelefonDeviceStatusContract.ValidateReport(body); var status = body.DeepClone().AsObject();
        if (body.ContainsKey("identifiers"))
        {
            if (!store.AcceptIdentifiers(peer, body, Now(), TelefonProtocolContract.Integer(message["expires_ms"])))
                return new TelefonAck(message["message_id"]!.GetValue<string>(), "rejected", "not_granted");
        }
        // UI queues carry a request reference, never identifier values.
        status = TelefonDeviceStatusContract.WithoutIdentifiers(status);
        store.CompleteStatusRequest(peer.Id, body["request_id"]!.GetValue<string>());
        status["kennung"] = peer.Id; status["name"] = peer.Name; status["online"] = true; status["letzterKontakt"] = DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss");
        store.SaveStatus(peer.Id, status); await emit("App.telefonStatus", status); return null;
    }

    private async Task<TelefonAck?> HandlePersonalMessageAsync(TelefonPeer peer, JsonObject message, JsonObject body, string transport)
    {
        var kind = message["kind"]!.GetValue<string>(); var id = message["message_id"]!.GetValue<string>(); var now = Now();
        if (kind == "personal_sync.settings") { var own = body["own_device"]!.GetValue<bool>(); if (!own) personalSync.PurgeProtocol(peer.Id); store.SetPersonalSettings(peer.Id, remoteOwnDevice: own); await emit("App.telefonPersonalSyncEinstellungen", new { device_id = peer.Id, own_device = own }); return null; }
        var run = kind == "personal_sync.request" ? null : personalSync.LoadRun(peer.Id, body["run_id"]!.GetValue<string>(), now);
        var grants = PersonalGrants(kind, body, run?.Request); if (grants.Count == 0 || grants.Any(name => store.LocalGrants()[name]?.GetValue<bool>() != true || peer.Grants[name]?.GetValue<bool>() != true)) return new TelefonAck(id, "rejected", "not_granted");
        var settings = store.PersonalSettings(peer.Id); if (!settings.OwnDevice || !settings.RemoteOwnDevice) return new TelefonAck(id, "rejected", "not_granted");
        if (body["format"]?.GetValue<int>() == 2 && !SupportsPersonalFormat2(peer)) return new TelefonAck(id, "rejected", "invalid_schema");
        if (body["format"]?.GetValue<int>() == 3 && grants.Any(name => !SupportsPersonalFormat(peer, name, 3))) return new TelefonAck(id, "rejected", "invalid_schema");
        if (kind == "personal_sync.request") { personalSync.RememberRun(peer.Id, body, now, message["expires_ms"]!.GetValue<long>()); await emit("App.telefonPersonalSync", new { device_id = peer.Id, transport, kind, body }); return null; }
        if (kind == "personal_sync.batch")
        {
            var staged = personalSync.StageBatch(peer.Id, message, transport, now);
            var complete = staged is not null && await CompleteOrRequestAttachmentsAsync(staged, true, transport);
            return new TelefonAck(id, "accepted", "none", complete);
        }
        if (kind is "personal_sync.deletion_proposals" or "personal_sync.deletion_decision")
        {
            var intent = personalSync.StageDecisionIntent(peer.Id, message, transport, now);
            var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (gate) personalCommits[intent.CommitToken] = (peer.Id, completion);
            string outcome;
            try
            {
                await EmitPersonalIntentAsync(intent, transport);
                outcome = await completion.Task.WaitAsync(TimeSpan.FromSeconds(30));
            }
            catch (TimeoutException) { outcome = "temporary"; }
            finally { lock (gate) personalCommits.Remove(intent.CommitToken); }
            return outcome == "applied" ? new TelefonAck(id, "accepted", "none") : new TelefonAck(id, "rejected", outcome switch
            { "conflict" => "conflict", "restore_unavailable" => "restore_unavailable", "invalid" => "invalid_schema", "temporary" => "temporary_failure", _ => "permanent_failure" });
        }
        if (kind == "personal_sync.attachment_chunk")
        {
            var raw = Convert.FromBase64String(body["data"]!.GetValue<string>());
            try { StagePersonalAttachmentChunk(peer.Id, body, raw, Math.Min(message["expires_ms"]!.GetValue<long>(), personalSync.LoadRun(peer.Id, body["run_id"]!.GetValue<string>(), now)!.ExpiresMs)); }
            finally { CryptographicOperations.ZeroMemory(raw); }
            foreach (var staged in personalSync.ReadyBatches(now).Where(item => item.PeerId == peer.Id && item.RunId == body["run_id"]!.GetValue<string>() && item.Reply == body["reply"]!.GetValue<bool>() && item.RecordsHash == body["records_hash"]!.GetValue<string>())) await CompleteOrRequestAttachmentsAsync(staged, false, transport);
            return new TelefonAck(id, "accepted", "none", true);
        }
        if (kind == "personal_sync.attachment_result")
        {
            personalSync.CompleteOutgoingAttachment(peer.Id, body["run_id"]!.GetValue<string>(), body["reply"]!.GetValue<bool>(), body["records_hash"]!.GetValue<string>(), body["sha256"]!.GetValue<string>(), now);
            await ReleasePersonalReportAsync(peer.Id, body["run_id"]!.GetValue<string>()); return new TelefonAck(id, "accepted", "none", true);
        }
        await emit("App.telefonPersonalSync", new { device_id = peer.Id, transport, kind, body }); return null;
    }

    private async Task<bool> CompleteOrRequestAttachmentsAsync(PersonalSyncStagedBatch staged, bool requestMissing,
        string transport = "wifi")
    {
        if (staged.RecordsHash.Length == 64)
        {
            var run = personalSync.LoadRun(staged.PeerId, staged.RunId, Now()) ?? throw new InvalidDataException("Personal-Sync-Request fehlt.");
            var descriptors = staged.Records.OfType<JsonObject>().SelectMany(record => (record["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).GroupBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal).Select(group => group.First()).OrderBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal).ToArray();
            var wants = new JsonArray();
            foreach (var descriptor in descriptors)
            {
                personalSync.StageAttachment(staged.PeerId, staged.RunId, staged.Reply, staged.RecordsHash, descriptor, "incoming", run.Policy, run.ExpiresMs, []);
                var ranges = personalSync.MissingAttachmentRanges(staged.PeerId, staged.RunId, staged.Reply, staged.RecordsHash, descriptor["sha256"]!.GetValue<string>(), "incoming", Now());
                if (ranges.Count != 0) wants.Add(new JsonObject { ["sha256"] = descriptor["sha256"]!.GetValue<string>(), ["ranges"] = new JsonArray(ranges.Select(range => (JsonNode)new JsonArray(range.Start, range.End)).ToArray()) });
            }
            if (wants.Count != 0)
            {
                if (requestMissing) await SendPersonalSyncAsync(staged.PeerId, "personal_sync.attachment_request", new JsonObject { ["format"] = 2, ["run_id"] = staged.RunId, ["reply"] = staged.Reply, ["records_hash"] = staged.RecordsHash, ["wants"] = wants });
                return false;
            }
        }
        await emit("App.telefonPersonalSync", new { device_id = staged.PeerId, transport, kind = "personal_sync.batch", pending_message_id = staged.PendingMessageId, commit_token = staged.CommitToken, body = new { format = staged.Format, run_id = staged.RunId, reply = staged.Reply, records = staged.Records, records_hash = staged.RecordsHash } });
        if (staged.RecordsHash.Length == 64)
            foreach (var hash in staged.Records.OfType<JsonObject>().SelectMany(record => (record["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).Select(value => value["sha256"]!.GetValue<string>()).Distinct(StringComparer.Ordinal))
                await SendPersonalSyncAsync(staged.PeerId, "personal_sync.attachment_result", new JsonObject { ["format"] = 2, ["run_id"] = staged.RunId, ["reply"] = staged.Reply, ["records_hash"] = staged.RecordsHash, ["sha256"] = hash, ["state"] = "complete", ["error"] = "none" });
        return true;
    }

    private async Task ReleasePersonalReportAsync(string peerId, string runId)
    {
        if (personalSync.ReadyReport(peerId, runId, Now()) is not { } report) return;
        _ = await SendPersonalSyncAsync(peerId, "personal_sync.report", report);
        personalSync.DeleteReport(peerId, runId);
    }

    private Task EmitPersonalIntentAsync(PersonalSyncDecisionIntent intent, string transport) => emit("App.telefonPersonalSync", new { device_id = intent.PeerId, transport, kind = intent.Kind, pending_message_id = intent.PendingMessageId, commit_token = intent.CommitToken, body = intent.Body });

    private TelefonConnection RequireOnline(string id, string capability, bool localGrant)
    {
        var peer = Peers.FirstOrDefault(value => value.Id == id) ?? throw new InvalidOperationException(T("The phone is not paired.")); TelefonConnection? connection; lock (gate) online.TryGetValue(id, out connection);
        if (connection is null || !RemoteCapability(peer, capability) || peer.Grants[capability]?.GetValue<bool>() != true || localGrant && store.LocalGrants()[capability]?.GetValue<bool>() != true) throw new InvalidOperationException(T("The phone function is not permitted or available.")); return connection;
    }
    private TelefonPeer RequireSolePeer(string id) { var peers = Peers; return peers.Length == 1 && peers[0].Id == id ? peers[0] : throw new InvalidOperationException("binding_conflict"); }

    private static string T(string message) => NativeLocalization.Gettext(message);
    internal static HashSet<string> PersonalGrants(string kind, JsonObject body, JsonObject? durableRequest = null)
    {
        if (kind is "personal_sync.deletion_proposals" or "personal_sync.deletion_decision") return new HashSet<string>(StringComparer.Ordinal) { "personal_deletions_sync" };
        if (kind is "personal_sync.attachment_request" or "personal_sync.attachment_chunk" or "personal_sync.attachment_result") return durableRequest?["modules"] is JsonArray attachmentModules && attachmentModules.Any(item => item?.GetValue<string>() == "notes") ? new HashSet<string>(StringComparer.Ordinal) { "personal_notes_sync" } : [];
        var modules = new HashSet<string>(StringComparer.Ordinal); if (kind == "personal_sync.request" && body["modules"] is JsonArray request) foreach (var item in request) modules.Add(item!.GetValue<string>()); else if (kind == "personal_sync.batch" && body["records"] is JsonArray records) foreach (var item in records) modules.Add(item!["kind"]!.GetValue<string>() is "note" or "notebook" ? "notes" : "tasks");
        else if (kind == "personal_sync.report") foreach (var direction in new[] { "sent", "received" }) if (body[direction] is JsonObject counts) { if (counts["notes"]?.GetValue<long>() > 0 || counts["notebooks"]?.GetValue<long>() > 0) modules.Add("notes"); if (counts["tasks"]?.GetValue<long>() > 0) modules.Add("tasks"); }
        if (modules.Count == 0 && kind is ("personal_sync.batch" or "personal_sync.report") && durableRequest?["modules"] is JsonArray durableModules)
            foreach (var item in durableModules) modules.Add(item!.GetValue<string>());
        return modules.Select(module => module == "notes" ? "personal_notes_sync" : "personal_tasks_sync").ToHashSet(StringComparer.Ordinal);
    }
    private static JsonObject WithPeer(JsonObject body, TelefonPeer peer) { var copy = body.DeepClone().AsObject(); copy["device_id"] = peer.Id; copy["display_name"] = peer.Name; return copy; }
    internal static bool SupportsPersonalFormat2(TelefonPeer peer) => peer.Capabilities["personal_notes_sync"]?["versions"] is JsonArray versions && versions.Any(item => item?.GetValue<int>() == 2);
    internal static bool SupportsPersonalFormat(TelefonPeer peer, string capability, int format) =>
        peer.Capabilities[capability]?["versions"] is JsonArray versions && versions.Any(item => item?.GetValue<int>() == format);
    internal static string IncomingCallDisposition(JsonObject? current, JsonObject incoming)
    {
        if (current is not null && (TelefonProtocolContract.Integer(incoming["occurred_ms"]) < TelefonProtocolContract.Integer(current["occurred_ms"]) ||
            current["call_ref"]?.GetValue<string>() == incoming["call_ref"]?.GetValue<string>() && (
                current["direction"]?.GetValue<string>() != incoming["direction"]?.GetValue<string>() ||
                current["state"]?.GetValue<string>() == "idle" && incoming["state"]?.GetValue<string>() != "idle"))) return "conflict";
        if (current is null || current["call_ref"]?.GetValue<string>() != incoming["call_ref"]?.GetValue<string>()) return "accepted";
        var prior = TelefonProtocolContract.Integer(current["revision"]); var revision = TelefonProtocolContract.Integer(incoming["revision"]);
        return revision < prior || revision == prior && !JsonNode.DeepEquals(current, incoming) ? "conflict" : JsonNode.DeepEquals(current, incoming) ? "duplicate" : "accepted";
    }
    private JsonObject? CurrentCall(string peerId)
    {
        if (calls.TryGetValue(peerId, out var current)) return current;
        var durable = store.LoadRecent(peerId, "incoming_call_state.event", 1).FirstOrDefault() as JsonObject;
        if (durable is not null) calls[peerId] = durable.DeepClone().AsObject();
        return durable;
    }
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    internal static bool RemoteCapability(TelefonPeer peer, string name) => peer.Capabilities[name] is JsonObject item &&
        item["available"]?.GetValue<bool>() == true && item["versions"] is JsonArray versions && versions.Any(value => value?.GetValue<int>() == 1);

    private static JsonObject Proof(string type, string side, string phase, PairingSecrets secrets) => new()
    { ["p"] = TelefonCrypto.Protocol, ["type"] = type, ["side"] = side, ["transcript"] = Convert.ToBase64String(secrets.Transcript), ["proof"] = Convert.ToBase64String(TelefonCrypto.PairProof(secrets.Key, phase, side, secrets.Transcript)) };
    private static void ValidateProof(JsonObject value, string type, string side, string phase, PairingSecrets secrets)
    {
        Require(value, "p", "type", "side", "transcript", "proof");
        if (value["p"]?.GetValue<string>() != TelefonCrypto.Protocol || value["type"]?.GetValue<string>() != type || value["side"]?.GetValue<string>() != side ||
            !CryptographicOperations.FixedTimeEquals(TelefonCrypto.StrictBase64(value, "transcript", 32), secrets.Transcript) ||
            !CryptographicOperations.FixedTimeEquals(TelefonCrypto.StrictBase64(value, "proof", 32), TelefonCrypto.PairProof(secrets.Key, phase, side, secrets.Transcript))) throw new CryptographicException();
    }
    private static void VerifyMac(byte[] key, string label, JsonObject value)
    { var copy = value.DeepClone().AsObject(); var actual = TelefonCrypto.StrictBase64(copy, "mac", 32); copy.Remove("mac"); if (!CryptographicOperations.FixedTimeEquals(actual, Hmac(key, label, TelefonCrypto.Canonical(copy)))) throw new CryptographicException(); }
    private static byte[] Hmac(byte[] key, string label, byte[] value) { using var hmac = new HMACSHA256(key); return hmac.ComputeHash(Encoding.UTF8.GetBytes(label).Concat(value).ToArray()); }
    private static string CanonicalUuid(JsonObject value, string name) { var text = value[name]?.GetValue<string>() ?? ""; return Guid.TryParseExact(text, "D", out var id) && id.ToString("D") == text ? text : throw new InvalidDataException(); }
    private static string DisplayName(JsonObject value, string name) { var text = value[name]?.GetValue<string>() ?? ""; return text.EnumerateRunes().Count() is >= 1 and <= 60 && !text.Any(char.IsControl) ? text : throw new InvalidDataException(); }
    private static int ProtocolVersion(JsonNode? value)
    { if (!TelefonProtocolContract.TryInteger(value, out var version) || version is < 1 or > 65_535) throw new InvalidDataException(); return (int)version; }
    private static void Require(JsonObject value, params string[] fields) { var expected = fields.ToHashSet(StringComparer.Ordinal); if (value.Count != expected.Count || value.Any(item => !expected.Contains(item.Key))) throw new InvalidDataException(); }
    internal static async Task<JsonObject> ReadFrameAsync(Stream stream, int maximum, CancellationToken cancellation)
    { var prefix = new byte[4]; await stream.ReadExactlyAsync(prefix, cancellation); var length = BinaryPrimitives.ReadUInt32BigEndian(prefix); if (length is 0 || length > maximum) throw new InvalidDataException(); var bytes = new byte[(int)length]; await stream.ReadExactlyAsync(bytes, cancellation); using var document = JsonDocument.Parse(bytes); ValidateJson(document.RootElement); return JsonNode.Parse(bytes) as JsonObject ?? throw new InvalidDataException(); }
    internal static async Task WriteFrameAsync(Stream stream, JsonObject value, CancellationToken cancellation)
    { var bytes = TelefonCrypto.Canonical(value); var prefix = new byte[4]; BinaryPrimitives.WriteUInt32BigEndian(prefix, (uint)bytes.Length); await stream.WriteAsync(prefix, cancellation); await stream.WriteAsync(bytes, cancellation); await stream.FlushAsync(cancellation); }

    private static void ValidateJson(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
            { if (!names.Add(property.Name)) throw new InvalidDataException("Doppelter JSON-Schlüssel."); ValidateJson(property.Value); }
        }
        else if (value.ValueKind == JsonValueKind.Array) foreach (var item in value.EnumerateArray()) ValidateJson(item);
        else if (value.ValueKind == JsonValueKind.Number && !value.TryGetInt64(out _))
            throw new InvalidDataException("Bruchzahlen sind im Telefonprotokoll nicht erlaubt.");
    }

    internal static async Task<JsonObject> ReadFrameWithinAsync(Stream stream, int maximum, TimeSpan timeout,
        CancellationToken cancellation)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(timeout);
        try { return await ReadFrameAsync(stream, maximum, deadline.Token); }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested)
        { throw new TimeoutException(T("Phone connection cancelled or timed out.")); }
    }

    internal async Task ShutdownAsync()
    {
        if (disposed) return;
        disposed = true; cleanupTimer.Dispose(); dialCleanupTimer.Dispose();
        await StopAsync().ConfigureAwait(false);
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
    }
    public void Dispose() => ShutdownAsync().GetAwaiter().GetResult();
}

internal sealed class TelefonConnection : IDisposable
{
    private readonly TelefonPeer peer; private readonly Stream stream; private readonly byte[] sid;
    private readonly byte[] receiveKey; private readonly byte[] receivePrefix; private readonly byte[] sendKey; private readonly byte[] sendPrefix;
    private readonly TelefonStore store; private readonly Func<TelefonPeer, JsonObject, Task<TelefonAck?>> receive; private readonly CancellationToken cancellation; private readonly string transport; private readonly SemaphoreSlim writer = new(1, 1);
    private long receiveSequence; private long sendSequence; private long lastReceivedMs; private long lastSentMs; private bool disposed;
    private readonly Func<JsonObject, Task>? customAccepted;
    private readonly Func<TelefonPeer, string, JsonObject, string?>? authorizeCall;
    private readonly Func<TelefonConnection, TelefonPeer, JsonObject, Action, bool>? sendCall;
    internal string RemoteCloseReason { get; private set; } = "";
    internal string Transport => transport;
    internal TelefonConnection(TelefonPeer peer, Stream stream, byte[] sid, byte[] material, TelefonStore store, Func<TelefonPeer, JsonObject, Task<TelefonAck?>> receive, CancellationToken cancellation, string transport, Func<JsonObject, Task>? customAccepted = null,
        Func<TelefonPeer, string, JsonObject, string?>? authorizeCall = null,
        Func<TelefonConnection, TelefonPeer, JsonObject, Action, bool>? sendCall = null)
    { this.authorizeCall = authorizeCall; this.sendCall = sendCall; this.customAccepted = customAccepted; this.peer = peer; this.stream = stream; this.sid = sid.ToArray(); receiveKey = material[..32]; receivePrefix = material[32..36]; sendKey = material[36..68]; sendPrefix = material[68..72]; this.store = store; this.receive = receive; this.cancellation = cancellation; this.transport = transport; lastReceivedMs = lastSentMs = Now(); }
    internal async Task RunAsync()
    {
        Task<JsonObject>? read = null;
        while (!cancellation.IsCancellationRequested)
        {
            await PumpOutboxAsync(); read ??= TelefonCoordinator.ReadFrameAsync(stream, 1_048_576, cancellation);
            var completed = await Task.WhenAny(read, Task.Delay(1_000, cancellation)); var now = Now();
            if (completed == read)
            {
                var plain = Open(await read); read = null; lastReceivedMs = now; await HandlePlainAsync(plain);
                if (RemoteCloseReason.Length > 0) return;
            }
            if (now - lastReceivedMs >= 75_000) throw new IOException("Telefon-Heartbeat abgelaufen.");
            if (now - lastSentMs >= 25_000) await SendPlainAsync(new JsonObject { ["type"] = "ping", ["ping_id"] = Guid.NewGuid().ToString("D"), ["sent_ms"] = now });
        }
    }
    internal async Task InitializeAsync(long capabilityRevision)
    {
        await SendPlainAsync(new JsonObject { ["type"] = "session_ready", ["connection_id"] = Guid.NewGuid().ToString("D"), ["capabilities_revision"] = capabilityRevision, ["last_received_seq"] = -1 });
        var ready = Open(await TelefonCoordinator.ReadFrameWithinAsync(stream, 1_048_576,
            TimeSpan.FromSeconds(15), cancellation));
        if (ready.Count != 4 || ready["type"]?.GetValue<string>() != "session_ready" ||
            TelefonProtocolContract.Integer(ready["capabilities_revision"]) < 1 || TelefonProtocolContract.Integer(ready["last_received_seq"]) != -1 ||
            !Guid.TryParseExact(ready["connection_id"]?.GetValue<string>(), "D", out _)) throw new InvalidDataException("Ungültiges session_ready.");
    }
    internal async Task SendMessageAsync(string kind, JsonObject body, long ttl)
    {
        var now = Now();
        if (kind == "device_status.request" && TelefonProtocolContract.TryInteger(body["version"], out var statusVersion) && statusVersion == 4)
        {
            var message = new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
                ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60_000, ["body"] = body.DeepClone() };
            await Task.Run(() => store.SendIdentifierRequest(peer, body, now, () => SendPlainAsync(message).GetAwaiter().GetResult()), cancellation);
            return;
        }
        if (kind == "device_status.request") store.RememberStatusRequest(peer.Id, body["request_id"]!.GetValue<string>(), checked(now + ttl));
        store.Enqueue(peer.Id, kind, body, ttl, now); await PumpOutboxAsync();
    }
    internal Task PumpOutboxNowAsync() => PumpOutboxAsync();
    internal Task SendCapabilitiesAsync(long revision) { var value = TelefonProtocolContract.DesktopCapabilities(); value["revision"] = revision; return SendMessageAsync("capabilities.update", value, 86_400_000); }
    internal Task SendGrantsAsync(long revision, JsonObject grants) => SendMessageAsync("grants.update", new JsonObject { ["revision"] = revision, ["grants"] = grants.DeepClone() }, 86_400_000);
    private async Task HandlePlainAsync(JsonObject plain)
    {
        var type = plain["type"]?.GetValue<string>();
        if (type == "ping")
        { TelefonProtocolContract.ExactObject(plain, "type", "ping_id", "sent_ms"); ValidateControlUuidAndTime(plain); await SendPlainAsync(new JsonObject { ["type"] = "pong", ["ping_id"] = plain["ping_id"]!.GetValue<string>(), ["sent_ms"] = TelefonProtocolContract.Integer(plain["sent_ms"]) }); return; }
        if (type == "pong") { TelefonProtocolContract.ExactObject(plain, "type", "ping_id", "sent_ms"); ValidateControlUuidAndTime(plain); return; }
        if (type == "close")
        {
            TelefonProtocolContract.ExactObject(plain, "type", "reason");
            var reason = plain["reason"]?.GetValue<string>() ?? "";
            if (reason is not ("normal" or "shutdown" or "better_transport" or "unpaired" or "protocol_upgrade"))
                throw new InvalidDataException("Ungültiger Schließgrund.");
            RemoteCloseReason = reason; return;
        }
        if (type == "ack")
        {
            TelefonProtocolContract.ExactObject(plain, "type", "message_id", "status", "error"); var id = plain["message_id"]?.GetValue<string>(); var status = plain["status"]?.GetValue<string>(); var error = plain["error"]?.GetValue<string>();
            if (!TelefonProtocolContract.IsUuidV4(id) || status is not ("accepted" or "duplicate" or "rejected") || (status == "rejected" ? error is not ("expired" or "invalid_schema" or "unsupported" or "not_granted" or "too_large" or "temporary_failure" or "permanent_failure" or "restore_unavailable" or "conflict") : error != "none")) throw new InvalidDataException("Ungültiges Ack.");
            var queued = store.OutboxMessage(peer.Id, id!);
            if (status is "accepted" or "duplicate" && queued?["kind"]?.GetValue<string>() == "personal_sync.custom_batch" &&
                queued["body"] is JsonObject customBody && customBody["deletions"] is JsonArray { Count: > 0 } && customAccepted is not null)
                await customAccepted(new JsonObject { ["source_id"] = customBody["source_id"]!.DeepClone(),
                    ["revision"] = customBody["revision"]!.DeepClone(), ["deletions"] = customBody["deletions"]!.DeepClone() });
            if (queued?["kind"]?.GetValue<string>() is string queuedKind && TelefonProtocolContract.PersonalKinds.Contains(queuedKind) && queuedKind != "personal_sync.settings")
            {
                store.AcknowledgePersonalOutbox(peer.Id, id!, status!, error!, Now()); return;
            }
            if (status == "rejected" && error == "temporary_failure")
            {
                store.RetryOutbox(peer.Id, id!, Now(), error); return;
            }
            store.CompleteOutbox(peer.Id, id!); return;
        }
        if (type != "message") throw new InvalidDataException("Unbekanntes Steuerobjekt.");
        var now = Now(); TelefonAck ack;
        if (plain["kind"]?.GetValue<string>() == "device_status.report" && plain["body"] is JsonObject statusBody &&
            (statusBody.ContainsKey("identifiers") || statusBody.ContainsKey("version")))
        {
            TelefonMessageContract.ValidateMessage(plain, now, true);
            ack = TelefonProtocolContract.Integer(plain["expires_ms"]) - TelefonProtocolContract.Integer(plain["created_ms"]) > 60_000
                ? new TelefonAck(plain["message_id"]!.GetValue<string>(), "rejected", "invalid_schema")
                : await receive(peer, plain) ?? new TelefonAck(plain["message_id"]!.GetValue<string>(), "accepted", "none");
        }
        else if (plain["kind"]?.GetValue<string>() is string kind &&
            (kind.StartsWith("personal_sync.custom_", StringComparison.Ordinal) || TelefonProtocolContract.PersonalKinds.Contains(kind) && kind is not "personal_sync.settings"))
        {
            ack = store.CommitIncoming(peer.Id, plain, now, AuthorizePersonal, deferAcceptance: true, reauthorizeDuplicates: true);
            if (ack.Process)
            {
                try
                {
                    var result = await receive(peer, plain); if (result is not null) ack = result;
                    if (ack.Status == "accepted" && ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
                }
                catch (TimeoutException)
                { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
                catch (Exception error) when (error is InvalidDataException or InvalidOperationException)
                { ack = new TelefonAck(ack.MessageId, "rejected", "permanent_failure"); store.MarkIncomingRejected(peer.Id, ack.MessageId, ack.Error, now); }
            }
        }
        else
        {
            ack = store.CommitIncoming(peer.Id, plain, now, Authorize, reauthorizeDuplicates: IsCallResultOrEvent(plain["kind"]?.GetValue<string>()));
            if (ack.Process)
            {
                var result = await receive(peer, plain); if (result is not null) ack = result;
                if (ack.Status == "rejected") store.MarkIncomingRejected(peer.Id, ack.MessageId, ack.Error, now);
                else store.MarkIncomingProcessed(peer.Id, ack.MessageId);
            }
        }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
    }
    private string? AuthorizePersonal(string kind, JsonObject body)
    {
        if (kind.StartsWith("personal_sync.custom_", StringComparison.Ordinal)) return
            kind != "personal_sync.custom_batch" && store.CustomAllowed(peer.Id, kind, body, false) &&
            (body["trigger"]?.GetValue<string>() != "auto_wifi" || transport == "wifi") ? null : "not_granted";
        var current = store.LoadPeers().First(value => value.Id == peer.Id);
        var run = kind == "personal_sync.request" ? null : new PersonalSyncStore(store).LoadRun(peer.Id, body["run_id"]!.GetValue<string>(), Now());
        if (kind != "personal_sync.request" && (run is null || run.Expired)) return "expired";
        if (kind == "personal_sync.report" && body["trigger"]?.GetValue<string>() != run!.Request["trigger"]?.GetValue<string>()) return "invalid_schema";
        if (kind is "personal_sync.batch" or "personal_sync.report" && body["format"]!.GetValue<int>() != run!.Request["format"]!.GetValue<int>()) return "invalid_schema";
        var grants = TelefonCoordinator.PersonalGrants(kind, body, run?.Request);
        if (grants.Count == 0 || grants.Any(name => store.LocalGrants()[name]?.GetValue<bool>() != true || current.Grants[name]?.GetValue<bool>() != true)) return "not_granted";
        var settings = store.PersonalSettings(peer.Id);
        if (!settings.OwnDevice || !settings.RemoteOwnDevice) return "not_granted";
        if ((kind == "personal_sync.request" && body["trigger"]?.GetValue<string>() == "auto_wifi" || run?.Policy == "wifi_only") &&
            transport != "wifi") return "not_granted";
        if (body["format"]?.GetValue<int>() == 3 && grants.Any(name => !TelefonCoordinator.SupportsPersonalFormat(current, name, 3))) return "invalid_schema";
        return body["format"]?.GetValue<int>() == 2 && !TelefonCoordinator.SupportsPersonalFormat2(current) ? "invalid_schema" : null;
    }
    private string? Authorize(string kind, JsonObject body)
    {
        if (authorizeCall is not null && IsCallResultOrEvent(kind)) return authorizeCall(peer, kind, body);
        var current = peer.Id == "" ? peer : store.LoadPeers().First(value => value.Id == peer.Id);
        if (kind == "capabilities.update") { var revision = TelefonProtocolContract.ValidateCapabilities(body); return revision <= current.CapabilityRevision ? "invalid_schema" : null; }
        if (kind == "grants.update") { var revision = TelefonProtocolContract.ValidateGrants(body); return revision <= current.GrantRevision ? "invalid_schema" : null; }
        if (kind == "device_status.report")
            return current.Grants["device_status"]?.GetValue<bool>() != true ? "not_granted" :
                store.HasStatusRequest(peer.Id, body["request_id"]!.GetValue<string>(), Now()) || TelefonCoordinator.RemoteCapability(current, "device_status") ? null : "invalid_schema";
        if (kind == "selected_notifications_readonly.event") return store.LocalGrants()["selected_notifications_readonly"]?.GetValue<bool>() == true && TelefonCoordinator.RemoteCapability(current, "selected_notifications_readonly") ? null : "not_granted";
        if (kind == "dial_request.result") return current.Grants["dial_request"]?.GetValue<bool>() == true && store.HasCommand(peer.Id, body["client_ref"]!.GetValue<string>()) ? null : "not_granted";
        if (kind is "answer_call.result" or "end_call.result") return store.HasCommand(peer.Id, body["command_ref"]!.GetValue<string>()) ? null : "not_granted";
        if (kind == "incoming_call_state.event")
        {
            var stateGranted = store.LocalGrants()["incoming_call_state"]?.GetValue<bool>() == true && current.Grants["incoming_call_state"]?.GetValue<bool>() == true;
            var sharesNumber = body["number_status"]?.GetValue<string>() == "available";
            var numberGranted = store.LocalGrants()["incoming_call_number"]?.GetValue<bool>() == true && current.Grants["incoming_call_number"]?.GetValue<bool>() == true;
            if (!stateGranted || sharesNumber && !numberGranted) return "not_granted";
            var prior = store.LoadRecent(peer.Id, "incoming_call_state.event", 1).FirstOrDefault() as JsonObject;
            if (TelefonCoordinator.IncomingCallDisposition(prior, body) == "conflict") return "conflict";
            return null;
        }
        if (kind == "personal_sync.settings") return null;
        return "unsupported";
    }
    private static bool IsCallResultOrEvent(string? kind) => kind is "dial_request.result" or "answer_call.result" or "end_call.result" or "incoming_call_state.event";
    private async Task PumpOutboxAsync()
    {
        var now = Now(); foreach (var item in store.Due(peer.Id, now, transport: transport))
        {
            if (item.Message["kind"]?.GetValue<string>()?.StartsWith("personal_sync.custom_", StringComparison.Ordinal) == true)
            {
                if (item.Message["kind"]!.GetValue<string>() == "personal_sync.custom_batch" && store.HasPendingCustomSettings(peer.Id)) continue;
                if (!await Task.Run(() => store.SendCustomIfAllowed(peer.Id, item.Message,
                    () => SendPlainAsync(item.Message).GetAwaiter().GetResult()), cancellation))
                { store.CompleteOutbox(peer.Id, item.Id); continue; }
            }
            else if (sendCall is not null && item.Message["kind"]?.GetValue<string>() is "dial_request.command" or "answer_call.command" or "end_call.command")
            {
                if (!await SendCallPlainAsync(item.Message)) store.CompleteOutbox(peer.Id, item.Id);
            }
            else await SendPlainAsync(item.Message);
            store.MarkAttempt(item.Id, item.Attempts, now);
        }
    }
    private static void ValidateControlUuidAndTime(JsonObject value)
    { if (!TelefonProtocolContract.IsUuidV4(value["ping_id"]?.GetValue<string>()) || !TelefonProtocolContract.TryInteger(value["sent_ms"], out var sent) || sent is < 0 or > 253402300799999) throw new InvalidDataException("Ungültiger Heartbeat."); }
    private async Task<bool> SendCallPlainAsync(JsonObject value)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token);
        try
        {
            return sendCall!(this, peer, value, () => {
                deadline.Token.ThrowIfCancellationRequested();
                TelefonCoordinator.WriteFrameAsync(stream, Seal(value), deadline.Token).GetAwaiter().GetResult();
                lastSentMs = Now();
            });
        }
        catch { stream.Dispose(); throw; }
        finally { writer.Release(); }
    }
    private async Task SendPlainAsync(JsonObject value)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromSeconds(15));
        await writer.WaitAsync(deadline.Token);
        try { var envelope = Seal(value); await TelefonCoordinator.WriteFrameAsync(stream, envelope, deadline.Token); lastSentMs = Now(); }
        catch { stream.Dispose(); throw; }
        finally { writer.Release(); }
    }
    private JsonObject Seal(JsonObject value)
    { var sequence = sendSequence++; var header = Header(sequence, "desktop_to_phone"); var nonce = sendPrefix.Concat(LongBytes(sequence)).ToArray(); var plain = TelefonCrypto.Canonical(value); var cipher = new byte[plain.Length]; var tag = new byte[16]; using (var aes = new AesGcm(sendKey, 16)) aes.Encrypt(nonce, plain, cipher, tag, TelefonCrypto.Canonical(header)); header["ciphertext"] = Convert.ToBase64String(cipher.Concat(tag).ToArray()); return header; }
    private JsonObject Open(JsonObject envelope)
    { var sequence = receiveSequence++; var header = Header(sequence, "phone_to_desktop"); if (envelope.Count != 5 || envelope.Any(item => item.Key is not ("p" or "sid" or "seq" or "dir" or "ciphertext"))) throw new CryptographicException(); var cipherText = envelope["ciphertext"]?.GetValue<string>() ?? ""; var cipher = Convert.FromBase64String(cipherText); if (Convert.ToBase64String(cipher) != cipherText || cipher.Length < 16 || !JsonNode.DeepEquals(header["p"], envelope["p"]) || !JsonNode.DeepEquals(header["sid"], envelope["sid"]) || !JsonNode.DeepEquals(header["seq"], envelope["seq"]) || !JsonNode.DeepEquals(header["dir"], envelope["dir"])) throw new CryptographicException(); var plain = new byte[cipher.Length - 16]; if (plain.Length > 262_144) throw new InvalidDataException("Anwendungsnachricht ist zu groß."); using (var aes = new AesGcm(receiveKey, 16)) aes.Decrypt(receivePrefix.Concat(LongBytes(sequence)).ToArray(), cipher.AsSpan(0, plain.Length), cipher.AsSpan(plain.Length), plain, TelefonCrypto.Canonical(header)); var value = JsonNode.Parse(plain) as JsonObject ?? throw new InvalidDataException(); if (!plain.SequenceEqual(TelefonCrypto.Canonical(value))) throw new InvalidDataException("Sicherer Inhalt ist nicht kanonisch."); return value; }
    private JsonObject Header(long sequence, string direction) => new() { ["p"] = TelefonCrypto.Protocol, ["sid"] = Convert.ToBase64String(sid), ["seq"] = sequence, ["dir"] = direction };
    private static byte[] LongBytes(long value) { var result = new byte[8]; BinaryPrimitives.WriteInt64BigEndian(result, value); return result; }
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    public void Dispose() { if (disposed) return; disposed = true; store.PurgeIdentifiers(peer.Id); try { stream.Dispose(); } catch { } CryptographicOperations.ZeroMemory(receiveKey); CryptographicOperations.ZeroMemory(sendKey); writer.Dispose(); }
}
