using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeConnectDiscovered(KdeConnectIdentity Identity, IPAddress Address, DateTimeOffset SeenAt);
internal sealed record KdeConnectPairing(string DeviceId, string DeviceName, string Code, DateTimeOffset ExpiresAt);
internal sealed record KdeConnectSmsReceived(KdeConnectSmsMessage Message, bool History, bool Notify);
internal sealed record KdeConnectSendResult(bool Ok, string State, string DeviceId, string? Error = null);
internal sealed record KdeConnectPairingEvent(string State, string DeviceId, string DeviceName, string Reason,
    string Code = "", DateTimeOffset? ExpiresAt = null);
internal sealed record KdeConnectStatus(bool Available, int DeviceCount, string Reason, bool Listening,
    int ListenerPort, int PairedCount, string DeviceId, string PeerName, string PairingState,
    int UnpairedCandidateCount, string UnpairedCandidateId, string UnpairedCandidateName,
    string ReplacementPeerId, bool CandidateReachable, int CandidateAgeSeconds,
    int ConnectionGeneration, string ConnectionDirection,
    bool HistoryAvailable, string BootstrapState, int ParseValid, int ParseSkipped, long LastReceiveMs,
    int PairingMismatchCount, int NextReconnectSeconds);

internal sealed class KdeConnectDirectBackend : IDisposable, IAsyncDisposable
{
    private static readonly TimeSpan CandidateLifetime = TimeSpan.FromMinutes(5);
    private static readonly int[] ReconnectSeconds = [5, 15, 30, 60];
    private const int MaxUnpairedConnections = 42;
    private const int MaxCandidates = 256;
    private readonly KdeConnectIdentityStore store;
    private readonly KdeConnectLocalIdentity local;
    private readonly ConcurrentDictionary<string, PendingPairing> pending = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, Connection> active = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, Connection> staged = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, PairingOperation> pairingOperations = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, KdeConnectDiscovered> candidates = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> connecting = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, int> pairingFailures = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> repairReported = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<Task, byte> backgroundTasks = new();
    private readonly object activeGate = new();
    private readonly SemaphoreSlim candidateSignal = new(0, 1);
    private readonly SemaphoreSlim incomingSlots = new(8, 8);
    private readonly SemaphoreSlim outgoingSlots = new(8, 8);
    private readonly CancellationTokenSource lifetime = new();
    private readonly TcpListener listener;
    private readonly UdpClient? udp;
    private readonly Task acceptTask;
    private readonly Task discoveryTask;
    private readonly bool activeDiscovery;
    private readonly string debugLogPath;
    private long generation;
    private int backoffIndex;
    private DateTimeOffset nextReconnect = DateTimeOffset.UtcNow;
    private volatile bool tcpListening = true;
    private bool disposed;
    private int disposalStarted;
    private volatile string pairingState = "idle";
    private readonly string logPath;

    /* Der Rueckruf verschluckte bisher jeden Fehler. Damit war nicht zu sehen,
       ob er im Moment der Rundsendung gelingt - dieselbe Blindstelle, die schon
       beim Bluetooth-Start Stunden gekostet hat. */
    private void LogRueckruf(string geraet, string ausgang)
    {
        RotatingLog.Append(logPath, $"{DateTimeOffset.Now:O} transport=kde stage=rueckruf {geraet}: {ausgang}");
    }

    private void DebugLog(string stage, string details, Exception? failure = null)
    {
        if (disposed && stage != "stop") return;
        var error = failure is null ? "" : " error=" + failure.ToString().ReplaceLineEndings(" | ");
        RotatingLog.Append(debugLogPath, $"{DateTimeOffset.Now:O} pid={Environment.ProcessId} " +
            $"thread={Environment.CurrentManagedThreadId} stage={stage} {details}{error}");
    }

    internal KdeConnectDirectBackend(WindowsPaths paths, IKdeConnectSecretProtector? protector = null,
        bool activeDiscovery = true)
    {
        this.activeDiscovery = activeDiscovery;
        logPath = Path.Combine(paths.Logs, "telefon.log");
        debugLogPath = Path.Combine(paths.Logs, "kde-connect-debug.log");
        store = new KdeConnectIdentityStore(paths, protector);
        local = store.LoadOrCreate();
        listener = BindListener();
        ListenerPort = ((IPEndPoint)listener.LocalEndpoint).Port;
        udp = TryBindUdp(activeDiscovery);
        DebugLog("start", $"device={local.Id} tcp={ListenerPort} udp={DiscoveryPort} discovery={activeDiscovery} " +
            $"os={Environment.OSVersion} runtime={Environment.Version}");
        acceptTask = AcceptLoopAsync(lifetime.Token);
        discoveryTask = DiscoveryLoopAsync(lifetime.Token);
    }

    internal event Action<KdeConnectStatus>? StatusChanged;
    internal event Action<KdeConnectSmsReceived>? SmsReceived;
    internal event Action<KdeConnectSendResult>? SendCompleted;
    internal event Action<KdeConnectPairingEvent>? PairingChanged;

    internal int ListenerPort { get; }
    internal int DiscoveryPort => (udp?.Client.LocalEndPoint as IPEndPoint)?.Port ?? 0;
    internal string LocalDeviceId => local.Id;
    internal bool HasPairedPeers => store.LoadPeers().Any(peer => peer.Paired);
    internal bool HasCandidateForTest(string deviceId) => candidates.ContainsKey(deviceId);
    internal void ExpireCandidatesForTest(DateTimeOffset now) => ExpireCandidates(now);
    internal string DebugLogForTest()
    {
        return RotatingLog.ReadAll(debugLogPath);
    }

    internal async Task ConnectForTestAsync(KdeConnectDiscovered device, string requiredPin,
        CancellationToken cancellationToken = default) =>
        Activate(await ConnectAsync(device, requiredPin, cancellationToken).ConfigureAwait(false), "outgoing");

    internal async Task<IReadOnlyList<KdeConnectDiscovered>> DiscoverAsync(TimeSpan duration,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        if (activeDiscovery) BroadcastIdentity();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(duration);
        try { await candidateSignal.WaitAsync(timeout.Token).ConfigureAwait(false); }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { }
        ExpireCandidates();
        return candidates.Values.ToArray();
    }

    internal async Task<KdeConnectPairing> BeginPairingAsync(CancellationToken cancellationToken = default)
    {
        CleanupPending();
        var waiting = pending.Values.ToArray();
        if (waiting.Length == 1) return waiting[0].Description;
        if (waiting.Length > 1) throw new InvalidOperationException("Mehrere KDE-Connect-Paarungen sind aktiv.");
        var pairedIds = store.LoadPeers().Where(peer => peer.Paired).Select(peer => peer.Id).ToHashSet(StringComparer.Ordinal);
        var replacementId = pairedIds.Count == 1 ? pairedIds.Single() : null;
        var operation = new PairingOperation(replacementId,
            CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, lifetime.Token));
        if (!pairingOperations.TryAdd(string.Empty, operation))
        { operation.Dispose(); throw new InvalidOperationException("Für dieses Gerät läuft bereits eine Paarung."); }
        pairingState = "connecting"; EmitStatus();
        KdeConnectDiscovered? candidate = null;
        Connection? connection = null;
        PendingPairing? createdPairing = null;
        var ownsCandidateOperation = false;
        try
        {
            var available = candidates.Values.Where(device => !pairedIds.Contains(device.Identity.DeviceId) &&
                DateTimeOffset.UtcNow - device.SeenAt <= CandidateLifetime).ToArray();
            if (available.Length == 0)
                available = (await DiscoverAsync(TimeSpan.FromSeconds(5), operation.Token).ConfigureAwait(false))
                    .Where(device => !pairedIds.Contains(device.Identity.DeviceId)).ToArray();
            operation.Token.ThrowIfCancellationRequested();
            if (available.Length != 1)
                throw new InvalidOperationException("Genau ein ungepaartes KDE-Connect-Gerät muss erreichbar sein.");
            candidate = available[0];
            if (!pairingOperations.TryAdd(candidate.Identity.DeviceId, operation))
                throw new InvalidOperationException("Für dieses Gerät läuft bereits eine Paarung.");
            ownsCandidateOperation = true;
            RemovePairingOperation(string.Empty, operation);
            if (!staged.ContainsKey(candidate.Identity.DeviceId) && connecting.ContainsKey(candidate.Identity.DeviceId))
            {
                DebugLog("pair.wait_callback", $"device={candidate.Identity.DeviceId}");
                var waitDeadline = DateTimeOffset.UtcNow.AddSeconds(11);
                while (!staged.ContainsKey(candidate.Identity.DeviceId) &&
                       connecting.ContainsKey(candidate.Identity.DeviceId) && DateTimeOffset.UtcNow < waitDeadline)
                    await Task.Delay(50, operation.Token).ConfigureAwait(false);
            }
            if (!staged.TryGetValue(candidate.Identity.DeviceId, out connection))
            {
                /* Gemessen am 16.08.: Das Telefon nimmt einen frischen
                   Handschlag nur an, solange seine App gerade aktiv war.
                   Danach bleibt der Port offen, die App bearbeitet die
                   Verbindung aber nicht mehr - von Windows wie von Linux aus
                   gleichermassen. Die Frist laeuft dann ab, und die bisherige
                   Meldung "Die Operation wurde abgebrochen" half niemandem
                   weiter. */
                try
                {
                    connection = await ConnectAsync(candidate, null, operation.Token).ConfigureAwait(false);
                }
                catch (Exception failure) when (failure is OperationCanceledException or IOException
                                                && !operation.Token.IsCancellationRequested)
                {
                    throw new InvalidOperationException(
                        "Das Telefon nimmt die Verbindung nicht an. Öffnen Sie die KDE-Connect-App " +
                        "auf dem Telefon, ziehen Sie die Geräteliste zum Aktualisieren nach unten und " +
                        "koppeln Sie unmittelbar danach erneut.", failure);
                }
                operation.Token.ThrowIfCancellationRequested();
                Stage(connection, "outgoing");
            }
            DebugLog("pair.connection_ready", $"device={candidate.Identity.DeviceId} generation={connection.Generation} " +
                $"direction={connection.Direction}");
            createdPairing = CreatePairing(connection, remoteConfirmed: false, operation);
            if (!pending.TryAdd(candidate.Identity.DeviceId, createdPairing))
                throw new InvalidOperationException("Für dieses Gerät läuft bereits eine Paarung.");
            await connection.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair", new JsonObject {
                ["pair"] = true, ["timestamp"] = createdPairing.Timestamp }), operation.Token).ConfigureAwait(false);
            pairingState = "requested";
            EmitPairing(createdPairing, "requested", "");
            return createdPairing.Description;
        }
        catch
        {
            RemovePairingOperation(string.Empty, operation);
            if (candidate is not null)
            {
                if (createdPairing is not null)
                    ((ICollection<KeyValuePair<string, PendingPairing>>)pending).Remove(
                        new KeyValuePair<string, PendingPairing>(candidate.Identity.DeviceId, createdPairing));
                if (ownsCandidateOperation) RemovePairingOperation(candidate.Identity.DeviceId, operation);
            }
            operation.Dispose();
            if (connection is not null &&
                (!pending.TryGetValue(connection.Identity.DeviceId, out var winner) ||
                 !ReferenceEquals(winner.Connection, connection)) && RemoveStaged(connection))
                connection.Dispose();
            if (!operation.Removed)
            {
                pairingState = cancellationToken.IsCancellationRequested ? "failed_cancelled" : "failed_network";
                EmitStatus();
            }
            throw;
        }
    }

    internal async Task ConfirmPairingAsync(string deviceId, bool accept, CancellationToken cancellationToken = default)
    {
        if (!pending.TryGetValue(deviceId, out var pairing) || pairing.ExpiresAt <= DateTimeOffset.UtcNow)
        { if (pairing is not null) ExpirePairing(deviceId, pairing); throw new InvalidOperationException("Die KDE-Connect-Paarungsanfrage ist abgelaufen."); }
        if (!accept)
        {
            try { await pairing.Connection.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair",
                new JsonObject { ["pair"] = false }), cancellationToken).ConfigureAwait(false); }
            finally
            {
                if (AbortPairing(deviceId, pairing, "rejected", "rejected", false))
                    await pairing.Connection.Completion.ConfigureAwait(false);
            }
            return;
        }
        if (pairing.Incoming)
            await pairing.Connection.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair",
                new JsonObject { ["pair"] = true }), cancellationToken).ConfigureAwait(false);
        var mutuallyConfirmed = pairing.ConfirmLocal();
        if (mutuallyConfirmed) FinishPairing(deviceId, pairing);
        else EmitPairing(pairing, "waiting_for_phone", "");
    }

    internal void Remove(string deviceId)
    {
        foreach (var item in pairingOperations.Where(item => item.Key == deviceId || item.Value.ReplacementPeerId == deviceId).ToArray())
        {
            item.Value.Cancel(removed: true);
            if (pending.TryGetValue(item.Key, out var pairing))
                AbortPairing(item.Key, pairing, "failed", "removed", false);
            else if (pairingOperations.TryRemove(item.Key, out var operation)) operation.Dispose();
            if (staged.TryRemove(item.Key, out var candidate)) candidate.Dispose();
            candidates.TryRemove(item.Key, out _);
        }
        if (staged.TryRemove(deviceId, out var stagedConnection)) stagedConnection.Dispose();
        candidates.TryRemove(deviceId, out _);
        Connection? connection;
        lock (activeGate) active.TryRemove(deviceId, out connection);
        connection?.Dispose();
        store.Remove(deviceId);
        pairingState = "idle";
        EmitStatus();
    }

    internal Task<KdeConnectStatus> GetStatusAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ExpireCandidates(); CleanupPending();
        return Task.FromResult(BuildStatus());
    }

    internal async Task<(bool Available, int DeviceCount, string Reason)> StatusAsync(CancellationToken cancellationToken = default)
    {
        var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
        return (status.Available, status.DeviceCount, status.Reason);
    }

    internal async Task<KdeConnectSendResult> SendSmsWithResultAsync(string number, string text, string country,
        CancellationToken cancellationToken = default)
    {
        var body = KdeConnectProtocol.SmsBody(PhoneUri.Normalize(number, country), text);
        await EnsureActiveAsync(cancellationToken).ConfigureAwait(false);
        var connections = UsableConnections();
        if (connections.Count != 1)
        {
            SafeInvoke(SendCompleted, new KdeConnectSendResult(false, "failed", "", "no_unique_device"));
            throw new InvalidOperationException("Genau ein gepaartes SMS-fähiges KDE-Connect-Telefon ist erforderlich.");
        }
        var connection = connections[0];
        try
        {
            // There is no KDE Connect submission id. A failed write is ambiguous and is never retried.
            await connection.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsRequest, body), cancellationToken).ConfigureAwait(false);
            var result = new KdeConnectSendResult(true, "submitted", connection.Identity.DeviceId);
            SafeInvoke(SendCompleted, result); return result;
        }
        catch (Exception error)
        {
            if (RemoveActive(connection)) connection.Dispose();
            var result = new KdeConnectSendResult(false, "failed", connection.Identity.DeviceId, error.Message);
            SafeInvoke(SendCompleted, result); ScheduleReconnect(false); throw;
        }
    }

    internal async Task SendSmsAsync(string number, string text, string country,
        CancellationToken cancellationToken = default) =>
        _ = await SendSmsWithResultAsync(number, text, country, cancellationToken).ConfigureAwait(false);

    private async Task EnsureActiveAsync(CancellationToken cancellationToken)
    {
        if (UsableConnections().Count > 0) return;
        if (activeDiscovery) { BroadcastIdentity(); ReconnectKnown(); }
        var deadline = DateTimeOffset.UtcNow.AddSeconds(5);
        while (UsableConnections().Count == 0 && DateTimeOffset.UtcNow < deadline)
            await Task.Delay(50, cancellationToken).ConfigureAwait(false);
    }

    private List<Connection> UsableConnections()
    {
        var pins = store.LoadPeers().Where(peer => peer.Paired).ToDictionary(peer => peer.Id, peer => peer.CertificatePin, StringComparer.Ordinal);
        return active.Values.Where(connection => !connection.Closed && connection.Identity.IncomingCapabilities.Contains(
                KdeConnectProtocol.SmsRequest, StringComparer.Ordinal) && pins.TryGetValue(connection.Identity.DeviceId, out var pin) &&
                string.Equals(pin, KdeConnectProtocol.CertificatePin(connection.Certificate), StringComparison.Ordinal)).ToList();
    }

    private async Task DiscoveryLoopAsync(CancellationToken cancellationToken)
    {
        var receive = udp is null ? Task.CompletedTask : ReceiveUdpLoopAsync(udp, cancellationToken);
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var now = DateTimeOffset.UtcNow;
                if (now >= nextReconnect)
                {
                    if (activeDiscovery && active.IsEmpty && staged.IsEmpty) BroadcastIdentity();
                    if (activeDiscovery) ReconnectKnown();
                    ExpireCandidates(); CleanupPending();
                    var delay = ReconnectSeconds[Math.Min(backoffIndex, ReconnectSeconds.Length - 1)];
                    backoffIndex = Math.Min(backoffIndex + 1, ReconnectSeconds.Length - 1);
                    nextReconnect = now.AddSeconds(delay);
                    EmitStatus();
                }
                await Task.Delay(250, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        try { await receive.ConfigureAwait(false); } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
    }

    private async Task ReceiveUdpLoopAsync(UdpClient socket, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            UdpReceiveResult datagram;
            try { datagram = await socket.ReceiveAsync(cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { break; }
            catch (SocketException) when (!cancellationToken.IsCancellationRequested) { continue; }
            if (!IsPrivateAddress(datagram.RemoteEndPoint.Address)) continue;
            try
            {
                var identity = KdeConnectProtocol.ParseIdentity(KdeConnectProtocol.Decode(datagram.Buffer));
                if (identity.DeviceId == local.Id) continue;
                if (!candidates.ContainsKey(identity.DeviceId) && candidates.Count >= MaxCandidates)
                {
                    var oldest = candidates.OrderBy(item => item.Value.SeenAt).FirstOrDefault();
                    if (!string.IsNullOrEmpty(oldest.Key)) candidates.TryRemove(oldest.Key, out _);
                }
                var device = new KdeConnectDiscovered(identity, datagram.RemoteEndPoint.Address, DateTimeOffset.UtcNow);
                candidates[identity.DeviceId] = device;
                DebugLog("udp.received", $"remote={datagram.RemoteEndPoint} device={identity.DeviceId} " +
                    $"name={identity.DeviceName} tcp={identity.TcpPort}");
                if (candidateSignal.CurrentCount == 0) candidateSignal.Release();
                ScheduleReconnect(true);
                if (activeDiscovery)
                {
                    if (store.LoadPeers().Any(peer => peer.Id == identity.DeviceId && peer.Paired)) TryConnect(device);
                    else TryAnnounce(device);
                }
                EmitStatus();
            }
            catch (InvalidDataException error) { DebugLog("udp.rejected", $"remote={datagram.RemoteEndPoint}", error); }
        }
    }

    /// <summary>
    /// Sendet die eigene Kennung an jedes erreichbare Teilnetz.
    ///
    /// Windows leitet <c>255.255.255.255</c> von einem an <c>0.0.0.0</c>
    /// gebundenen Socket nur über die Schnittstelle der Standardroute. Neben
    /// WLAN vorhandene Ethernet-, VPN- oder virtuelle Adapter (Hyper-V,
    /// VirtualBox, VMware) fangen die Sendung dann ab und das Telefon sieht den
    /// Organizer nie. Deshalb wird zusätzlich an die gerichtete
    /// Rundsendeadresse jedes IPv4-Netzes gesendet.
    /// </summary>
    private void BroadcastIdentity()
    {
        if (disposed || udp is null) return;
        try
        {
            var identity = KdeConnectProtocol.Encode("kdeconnect.identity",
                KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort));
            _ = udp.SendAsync(identity, new IPEndPoint(IPAddress.Broadcast, KdeConnectProtocol.FirstPort));
            var addresses = Ipv4Broadcast.DirectedAddresses();
            foreach (var address in addresses)
                _ = udp.SendAsync(identity, new IPEndPoint(address, KdeConnectProtocol.FirstPort));
            DebugLog("udp.broadcast", $"sourcePort={DiscoveryPort} tcp={ListenerPort} directed={string.Join(',', addresses)}");
        }
        catch (Exception error) when (error is SocketException or ObjectDisposedException)
        { DebugLog("udp.broadcast_failed", $"sourcePort={DiscoveryPort}", error); }
    }

    private void SendIdentity(IPAddress address)
    {
        if (disposed || udp is null || !IsPrivateAddress(address)) return;
        try
        {
            var identity = KdeConnectProtocol.Encode("kdeconnect.identity",
                KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort));
            _ = udp.SendAsync(identity, new IPEndPoint(address, KdeConnectProtocol.FirstPort));
            DebugLog("udp.reverse", $"remote={address}:{KdeConnectProtocol.FirstPort} tcp={ListenerPort}");
        }
        catch (Exception error) when (error is SocketException or ObjectDisposedException)
        { DebugLog("udp.reverse_failed", $"remote={address}:{KdeConnectProtocol.FirstPort}", error); }
    }

    private void ReconnectKnown()
    {
        foreach (var peer in store.LoadPeers().Where(peer => peer.Paired))
        {
            if (active.ContainsKey(peer.Id) || connecting.ContainsKey(peer.Id)) continue;
            if (candidates.TryGetValue(peer.Id, out var candidate)) TryConnect(candidate);
            else if (peer.LastAddress is not null && IPAddress.TryParse(peer.LastAddress, out var address) && peer.LastPort.HasValue)
                TryConnect(new KdeConnectDiscovered(new KdeConnectIdentity(peer.Id, peer.Name, peer.LastPort.Value,
                    [KdeConnectProtocol.SmsRequest], [KdeConnectProtocol.SmsMessages]), address, DateTimeOffset.UtcNow));
        }
    }

    private void TryConnect(KdeConnectDiscovered device)
    {
        if (!connecting.TryAdd(device.Identity.DeviceId, 0)) return;
        if (active.ContainsKey(device.Identity.DeviceId))
        { connecting.TryRemove(device.Identity.DeviceId, out _); return; }
        if (!outgoingSlots.Wait(0)) { connecting.TryRemove(device.Identity.DeviceId, out _); return; }
        Track(Task.Run(async () =>
        {
            Connection? connection = null;
            var watch = Stopwatch.StartNew();
            try
            {
                DebugLog("reconnect.start", $"device={device.Identity.DeviceId} remote={device.Address}:{device.Identity.TcpPort}");
                var peer = store.LoadPeers().Single(value => value.Id == device.Identity.DeviceId && value.Paired);
                connection = await ConnectAsync(device, peer.CertificatePin, lifetime.Token).ConfigureAwait(false);
                store.UpdateEndpoint(peer.Id, device.Address, device.Identity.TcpPort);
                pairingFailures.TryRemove(peer.Id, out _); Activate(connection, "outgoing"); connection = null;
                DebugLog("reconnect.success", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}");
            }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            catch (AuthenticationException error) { pairingFailures.AddOrUpdate(device.Identity.DeviceId, 1,
                (_, count) => Math.Min(count + 1, 100)); SendIdentity(device.Address); ScheduleReconnect(false);
                DebugLog("reconnect.auth_failed", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}", error); }
            catch (Exception error) { SendIdentity(device.Address); ScheduleReconnect(false);
                DebugLog("reconnect.failed", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}", error); }
            finally { connection?.Dispose(); connecting.TryRemove(device.Identity.DeviceId, out _); outgoingSlots.Release(); EmitStatus(); }
        }));
    }

    /// <summary>
    /// Verbindet sich zu einem noch nicht gepaarten Nachbarn und hält die
    /// Verbindung vorgemerkt bereit.
    ///
    /// NICHT ENTFERNEN. Diese Methode ist am Gerät gemessen, nicht vermutet,
    /// und sie ist bereits einmal bei einem Zusammenführen verlorengegangen.
    /// <c>KdeConnectTests</c> prüft ihr Vorhandensein deshalb ausdrücklich.
    ///
    /// Ohne diesen Rückruf erscheint der Rechner nie in der Geräteliste des
    /// Telefons. Android verwirft im WLAN-Stromsparmodus Rundsendungen,
    /// solange die App keine Multicast-Sperre hält; die Kennung des Rechners
    /// kommt dort also nicht an. Gemessen: neunzig fehlerfreie Rundsendungen
    /// in drei Minuten blieben unbeantwortet, während dasselbe Telefon
    /// gleichzeitig auf 1716/TCP lauschte. Ein einziger vom Rechner
    /// ausgehender Verbindungsaufbau genügte dagegen, damit das Gerät sofort
    /// in der Liste erschien. Das KDE-Connect-Original beantwortet deshalb
    /// jede empfangene Kennung mit einem eigenen Verbindungsaufbau.
    ///
    /// Die Verbindung bleibt ungepaart. <see cref="BeginPairingAsync"/>
    /// übernimmt eine bereits vorgemerkte Verbindung, statt eine zweite
    /// aufzubauen.
    /// </summary>
    private void TryAnnounce(KdeConnectDiscovered device)
    {
        if (staged.ContainsKey(device.Identity.DeviceId) || active.ContainsKey(device.Identity.DeviceId)) return;
        if (!connecting.TryAdd(device.Identity.DeviceId, 0)) return;
        if (!outgoingSlots.Wait(0)) { connecting.TryRemove(device.Identity.DeviceId, out _); return; }
        /* Androids passiver TCP-Pfad kann nach der Klartextkennung verstummen.
           Eine gezielte UDP-Identity fordert stattdessen Android auf, selbst zu
           unserem Listener zu verbinden. Diese Richtung ist zugleich diejenige,
           durch die der Rechner in Androids Geräteliste erscheint. Erst nach dem
           einsekündigen Android-Rate-Limit folgt der bisherige TCP-Rückruf. */
        SendIdentity(device.Address);
        Track(Task.Run(async () =>
        {
            var watch = Stopwatch.StartNew();
            try
            {
                DebugLog("callback.reverse_wait", $"device={device.Identity.DeviceId} waitMs=1500");
                await Task.Delay(1500, lifetime.Token).ConfigureAwait(false);
                if (staged.ContainsKey(device.Identity.DeviceId) || active.ContainsKey(device.Identity.DeviceId))
                {
                    LogRueckruf(device.Identity.DeviceId, "Gegenrichtung verbunden und vorgemerkt");
                    DebugLog("callback.reverse_connected", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}");
                    return;
                }
                DebugLog("callback.start", $"device={device.Identity.DeviceId} remote={device.Address}:{device.Identity.TcpPort}");
                var connection = await ConnectAsync(device, null, lifetime.Token).ConfigureAwait(false);
                /* Zwischenzeitlich kann das Gerät sich selbst gemeldet haben. */
                if (active.ContainsKey(device.Identity.DeviceId))
                {
                    connection.Dispose();
                    LogRueckruf(device.Identity.DeviceId, "verbunden; bestehende aktive Verbindung beibehalten");
                    DebugLog("callback.active_kept", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}");
                }
                else
                {
                    var retained = Stage(connection, "outgoing");
                    var held = ReferenceEquals(retained, connection);
                    LogRueckruf(device.Identity.DeviceId, held ? "verbunden und vorgemerkt" :
                        "verbunden; bestehende vorgemerkte Verbindung beibehalten");
                    DebugLog(held ? "callback.staged" : "callback.staged_kept",
                        $"device={device.Identity.DeviceId} generation={retained.Generation} elapsedMs={watch.ElapsedMilliseconds}");
                }
            }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            catch (Exception failure) { SendIdentity(device.Address); LogRueckruf(device.Identity.DeviceId,
                $"{failure.GetType().Name}: {failure.Message}");
                DebugLog("callback.failed", $"device={device.Identity.DeviceId} elapsedMs={watch.ElapsedMilliseconds}", failure); }
            finally { connecting.TryRemove(device.Identity.DeviceId, out _); outgoingSlots.Release(); EmitStatus(); }
        }));
    }

    private async Task<Connection> ConnectAsync(KdeConnectDiscovered device, string? requiredPin,
        CancellationToken cancellationToken)
    {
        var client = new TcpClient(device.Address.AddressFamily);
        client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(10)); var token = timeout.Token;
        var watch = Stopwatch.StartNew();
        try
        {
            DebugLog("outgoing.tcp_start", $"device={device.Identity.DeviceId} remote={device.Address}:{device.Identity.TcpPort}");
            await client.ConnectAsync(device.Address, device.Identity.TcpPort, token).ConfigureAwait(false);
            DebugLog("outgoing.tcp_connected", $"device={device.Identity.DeviceId} local={client.Client.LocalEndPoint} " +
                $"remote={client.Client.RemoteEndPoint} elapsedMs={watch.ElapsedMilliseconds}");
            var network = client.GetStream();
            /* Kein targetDeviceId in der KLARTEXT-Kennung. KDE Connect auf Android
               verwirft solche Identitaetspakete stillschweigend: Es liest sie, sendet
               kein ClientHello und laesst die Verbindung bis zum Fristablauf stehen.
               Ohne das Feld steht der Handschlag in 61 ms. Gemessen am 16.08.2026 mit
               kdeloesung.py, verschraenktes 2x2 ueber targetDeviceId und Faehigkeiten.
               Auch die sichere Kennung nach dem TLS-Aufbau sendet kein Ziel. Eingehend
               bleibt das Feld erlaubt - das Telefon schickt es selbst. */
            await network.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort)), token).ConfigureAwait(false);
            DebugLog("outgoing.plain_identity_sent", $"device={device.Identity.DeviceId} targetVersion={KdeConnectProtocol.Version}");
            X509Certificate2? remoteCertificate = null;
            var tls = new SslStream(network, false, (_, certificate, _, _) => ValidateCertificate(
                certificate, device.Identity.DeviceId, requiredPin, ref remoteCertificate));
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions {
                ServerCertificate = local.Certificate, ClientCertificateRequired = true,
                EnabledSslProtocols = SslProtocols.Tls12,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck }, token).ConfigureAwait(false);
            if (remoteCertificate is null) throw new AuthenticationException("Das KDE-Connect-Gerät hat kein Zertifikat vorgelegt.");
            DebugLog("outgoing.tls_ready", $"device={device.Identity.DeviceId} protocol={tls.SslProtocol} " +
                $"cipher={tls.NegotiatedCipherSuite} pin={KdeConnectProtocol.CertificatePin(remoteCertificate)[..12]} " +
                $"elapsedMs={watch.ElapsedMilliseconds}");
            await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort)), token).ConfigureAwait(false);
            var secureIdentity = KdeConnectProtocol.ParseIdentity(await KdeConnectProtocol.ReadAsync(tls, token).ConfigureAwait(false));
            if (!string.Equals(secureIdentity.DeviceId, device.Identity.DeviceId, StringComparison.Ordinal))
                throw new AuthenticationException("Die sichere KDE-Connect-Identität hat sich geändert.");
            DebugLog("outgoing.secure_identity", $"device={secureIdentity.DeviceId} name={secureIdentity.DeviceName} " +
                $"incoming={secureIdentity.IncomingCapabilities.Length} outgoing={secureIdentity.OutgoingCapabilities.Length}");
            return new Connection(client, tls, remoteCertificate, secureIdentity, device.Address, device.Identity.TcpPort);
        }
        catch (Exception error) { DebugLog("outgoing.failed", $"device={device.Identity.DeviceId} phaseMs={watch.ElapsedMilliseconds}", error);
            client.Dispose(); throw; }
    }

    private async Task AcceptLoopAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var client = await listener.AcceptTcpClientAsync(cancellationToken).ConfigureAwait(false);
                client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
                DebugLog("incoming.accepted", $"remote={client.Client.RemoteEndPoint} local={client.Client.LocalEndPoint}");
                if (!incomingSlots.Wait(0)) client.Dispose();
                else Track(HandleIncomingAsync(client, cancellationToken));
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (ObjectDisposedException) when (cancellationToken.IsCancellationRequested) { }
        finally { tcpListening = false; }
    }

    private async Task HandleIncomingAsync(TcpClient client, CancellationToken cancellationToken)
    {
        Connection? connection = null;
        var retained = false;
        var watch = Stopwatch.StartNew();
        try
        {
            if (client.Client.RemoteEndPoint is not IPEndPoint endpoint || !IsPrivateAddress(endpoint.Address))
                throw new AuthenticationException("KDE Connect ist nur im privaten Netzwerk erlaubt.");
            var network = client.GetStream();
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(10)); var token = timeout.Token;
            var plainIdentity = KdeConnectProtocol.ParseTargetedIdentity(
                await KdeConnectProtocol.ReadAsync(network, token).ConfigureAwait(false), local.Id);
            DebugLog("incoming.plain_identity", $"device={plainIdentity.DeviceId} name={plainIdentity.DeviceName} " +
                $"remote={endpoint.Address} tcp={plainIdentity.TcpPort}");
            var peer = store.LoadPeers().SingleOrDefault(value => value.Id == plainIdentity.DeviceId && value.Paired);
            X509Certificate2? remoteCertificate = null;
            var tls = new SslStream(network, false, (_, certificate, _, _) => ValidateCertificate(
                certificate, plainIdentity.DeviceId, peer?.CertificatePin, ref remoteCertificate));
            await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions {
                TargetHost = plainIdentity.DeviceId,
                ClientCertificates = new X509CertificateCollection { local.Certificate },
                EnabledSslProtocols = SslProtocols.Tls12,
                CertificateRevocationCheckMode = X509RevocationMode.NoCheck }, token).ConfigureAwait(false);
            if (remoteCertificate is null) throw new AuthenticationException("Das KDE-Connect-Gerät hat kein Zertifikat vorgelegt.");
            DebugLog("incoming.tls_ready", $"device={plainIdentity.DeviceId} protocol={tls.SslProtocol} " +
                $"cipher={tls.NegotiatedCipherSuite} pin={KdeConnectProtocol.CertificatePin(remoteCertificate)[..12]} " +
                $"elapsedMs={watch.ElapsedMilliseconds}");
            await tls.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.identity",
                KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort)), token).ConfigureAwait(false);
            var secureIdentity = KdeConnectProtocol.ParseIdentity(await KdeConnectProtocol.ReadAsync(tls, token).ConfigureAwait(false));
            if (!string.Equals(secureIdentity.DeviceId, plainIdentity.DeviceId, StringComparison.Ordinal))
                throw new AuthenticationException("Die sichere KDE-Connect-Identität hat sich geändert.");
            DebugLog("incoming.secure_identity", $"device={secureIdentity.DeviceId} name={secureIdentity.DeviceName} " +
                $"incoming={secureIdentity.IncomingCapabilities.Length} outgoing={secureIdentity.OutgoingCapabilities.Length}");
            connection = new Connection(client, tls, remoteCertificate, secureIdentity, endpoint.Address,
                plainIdentity.TcpPort);
            candidates[secureIdentity.DeviceId] = new KdeConnectDiscovered(secureIdentity, endpoint.Address, DateTimeOffset.UtcNow);
            if (peer is not null) store.UpdateEndpoint(peer.Id, endpoint.Address, plainIdentity.TcpPort);
            if (peer is null) Stage(connection, "incoming"); else Activate(connection, "incoming");
            if (candidateSignal.CurrentCount == 0) candidateSignal.Release();
            connection = null; retained = true;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception error) { DebugLog("incoming.failed", $"remote={client.Client.RemoteEndPoint} elapsedMs={watch.ElapsedMilliseconds}", error); }
        finally { connection?.Dispose(); if (!retained) client.Dispose(); incomingSlots.Release(); }
    }

    private Connection Activate(Connection connection, string direction)
    {
        Connection? previous = null;
        lock (activeGate)
        {
            if (active.TryGetValue(connection.Identity.DeviceId, out previous) && !previous.Closed && direction != "incoming")
            { DebugLog("active.kept", $"device={connection.Identity.DeviceId} generation={previous.Generation} rejectedDirection={direction}");
                connection.Dispose(); return previous; }
            if (previous is not null && pending.TryGetValue(connection.Identity.DeviceId, out var replacingPairing) &&
                ReferenceEquals(replacingPairing.Connection, previous) && !string.Equals(
                    KdeConnectProtocol.CertificatePin(previous.Certificate), KdeConnectProtocol.CertificatePin(connection.Certificate),
                    StringComparison.Ordinal))
            {
                pairingFailures.AddOrUpdate(connection.Identity.DeviceId, 1, (_, count) => Math.Min(count + 1, 100));
                connection.Dispose(); return previous;
            }
            connection.Direction = direction; connection.Generation = checked((int)Interlocked.Increment(ref generation));
            if (previous is not null) connection.State.TransferFrom(previous.State);
            active[connection.Identity.DeviceId] = connection;
            if (pending.TryGetValue(connection.Identity.DeviceId, out var pairing) && ReferenceEquals(pairing.Connection, previous))
                pairing.Connection = connection;
        }
        previous?.Dispose();
        DebugLog("active.set", $"device={connection.Identity.DeviceId} generation={connection.Generation} direction={direction} " +
            $"replaced={(previous is not null)}");
        if (store.LoadPeers().Any(peer => peer.Id == connection.Identity.DeviceId && peer.Paired))
        {
            if (connection.State.SmsStarted) ResumeSms(connection); else EnableSms(connection);
        }
        Track(MonitorAsync(connection, lifetime.Token)); EmitStatus(); return connection;
    }

    private Connection Stage(Connection connection, string direction)
    {
        Connection? previous = null;
        lock (activeGate)
        {
            staged.TryGetValue(connection.Identity.DeviceId, out previous);
            if (previous is null && staged.Count >= MaxUnpairedConnections)
            {
                DebugLog("staged.limit_rejected", $"device={connection.Identity.DeviceId} limit={MaxUnpairedConnections}");
                connection.Dispose();
                throw new InvalidOperationException("Zu viele ungepaarte KDE-Connect-Verbindungen.");
            }
            if (previous is not null && !previous.Closed && !string.Equals(
                    KdeConnectProtocol.CertificatePin(previous.Certificate), KdeConnectProtocol.CertificatePin(connection.Certificate),
                    StringComparison.Ordinal))
            {
                DebugLog("staged.certificate_rejected", $"device={connection.Identity.DeviceId} generation={previous.Generation}");
                connection.Dispose(); return previous;
            }
            connection.Direction = direction; connection.Generation = checked((int)Interlocked.Increment(ref generation));
            if (previous is not null) connection.State.TransferFrom(previous.State);
            staged[connection.Identity.DeviceId] = connection;
            if (pending.TryGetValue(connection.Identity.DeviceId, out var pairing) &&
                ReferenceEquals(pairing.Connection, previous)) pairing.Connection = connection;
        }
        previous?.Dispose();
        DebugLog("staged.set", $"device={connection.Identity.DeviceId} generation={connection.Generation} direction={direction} " +
            $"replaced={(previous is not null)}");
        Track(MonitorAsync(connection, lifetime.Token)); EmitStatus(); return connection;
    }

    private async Task MonitorAsync(Connection connection, CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested && !connection.Closed)
            {
                var packet = await KdeConnectProtocol.ReadAsync(connection.Stream, cancellationToken).ConfigureAwait(false);
                if (packet.Type == "kdeconnect.pair") await HandlePairPacketAsync(connection, packet, cancellationToken).ConfigureAwait(false);
                else if (packet.Type == KdeConnectProtocol.SmsMessages && connection.State.SmsStarted) HandleSmsPacket(connection, packet);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception error) { DebugLog("connection.read_failed", $"device={connection.Identity.DeviceId} " +
            $"generation={connection.Generation} direction={connection.Direction}", error); }
        finally
        {
            if (RemoveActive(connection)) { DebugLog("active.closed", $"device={connection.Identity.DeviceId} generation={connection.Generation}");
                connection.Dispose(); ScheduleReconnect(false); EmitStatus(); }
            else if (RemoveStaged(connection))
            {
                DebugLog("staged.closed", $"device={connection.Identity.DeviceId} generation={connection.Generation}");
                if (pending.TryGetValue(connection.Identity.DeviceId, out var pairing) &&
                    ReferenceEquals(pairing.Connection, connection))
                    AbortPairing(connection.Identity.DeviceId, pairing, "failed", "network", false);
                connection.Dispose(); EmitStatus();
            }
            connection.Complete();
        }
    }

    private void EnableSms(Connection connection)
    {
        lock (connection.State.Gate)
        {
            if (connection.State.SmsStarted) return;
            connection.State.SmsStarted = true;
            if (connection.Identity.IncomingCapabilities.Contains(KdeConnectProtocol.SmsRequestConversations, StringComparer.Ordinal))
            {
                connection.State.Bootstrap = true; connection.State.BootstrapState = "collecting";
                connection.State.BootstrapStarted = DateTimeOffset.UtcNow;
                connection.State.QuietDeadline = DateTimeOffset.UtcNow.AddSeconds(1);
                connection.State.BootstrapDeadline = DateTimeOffset.UtcNow.AddSeconds(5);
                _ = connection.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsRequestConversations,
                    KdeConnectProtocol.RequestConversationsBody()), lifetime.Token);
                ScheduleBootstrapCheck(connection);
            }
            else { connection.State.Bootstrap = false; connection.State.BootstrapState = "live"; }
        }
    }

    private void ResumeSms(Connection connection)
    {
        lock (connection.State.Gate)
        {
            if (!connection.State.Bootstrap) return;
            var remaining = connection.State.Requested.Except(connection.State.Responded).ToArray();
            if (remaining.Length == 0)
                _ = connection.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsRequestConversations,
                    KdeConnectProtocol.RequestConversationsBody()), lifetime.Token);
            else
                foreach (var thread in remaining)
                    _ = connection.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsRequestConversation,
                        KdeConnectProtocol.RequestConversationBody(long.Parse(thread,
                            System.Globalization.CultureInfo.InvariantCulture))), lifetime.Token);
            ScheduleBootstrapCheck(connection);
        }
    }

    private void HandleSmsPacket(Connection connection, KdeConnectPacket packet)
    {
        var messages = KdeConnectProtocol.ParseSmsMessages(packet, connection.Identity.DeviceId, out var skipped);
        var deliveries = new List<(KdeConnectSmsMessage[] Messages, bool History)>();
        lock (connection.State.Gate)
        {
            connection.State.ParseValid = messages.Count; connection.State.ParseSkipped = skipped;
            connection.State.LastReceiveMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var groups = messages.GroupBy(message => message.ThreadId).ToArray();
            var fullHistory = connection.Identity.IncomingCapabilities.Contains(KdeConnectProtocol.SmsRequestConversation, StringComparer.Ordinal);
            if (!connection.State.Bootstrap)
            {
                foreach (var group in groups)
                {
                    var history = connection.State.Requested.Contains(group.Key) && !connection.State.Responded.Contains(group.Key);
                    if (history) connection.State.Responded.Add(group.Key);
                    deliveries.Add((group.ToArray(), history));
                }
            }
            else foreach (var group in groups)
            {
                var pendingThread = connection.State.Requested.Contains(group.Key) && !connection.State.Responded.Contains(group.Key);
                if (fullHistory && pendingThread)
                {
                    connection.State.Responded.Add(group.Key); connection.State.Buffered.Remove(group.Key);
                    deliveries.Add((group.ToArray(), true));
                }
                else if (fullHistory && !connection.State.Requested.Contains(group.Key))
                {
                    if (!connection.State.Buffered.TryGetValue(group.Key, out var buffered))
                        connection.State.Buffered[group.Key] = buffered = [];
                    var ids = buffered.Select(message => message.Id).ToHashSet(StringComparer.Ordinal);
                    buffered.AddRange(group.Where(message => ids.Add(message.Id)));
                    connection.State.QuietDeadline = DateTimeOffset.UtcNow.AddSeconds(1);
                    connection.State.Requested.Add(group.Key);
                    _ = connection.WriteAsync(KdeConnectProtocol.Encode(KdeConnectProtocol.SmsRequestConversation,
                        KdeConnectProtocol.RequestConversationBody(long.Parse(group.Key, System.Globalization.CultureInfo.InvariantCulture))), lifetime.Token);
                    ScheduleBootstrapCheck(connection);
                }
                else
                {
                    connection.State.Responded.Add(group.Key); deliveries.Add((group.ToArray(), true));
                }
            }
            if (connection.State.Bootstrap) connection.State.BootstrapState = "waiting_threads";
        }
        foreach (var delivery in deliveries) Deliver(connection, delivery.Messages, delivery.History);
        CheckBootstrap(connection);
        EmitStatus();
    }

    private void Deliver(Connection connection, IEnumerable<KdeConnectSmsMessage> messages, bool history)
    {
        var deliverable = messages.Where(message => !message.Group)
            .GroupBy(message => message.Id, StringComparer.Ordinal).Select(group => group.First()).ToArray();
        var added = store.RememberSms(deliverable.Select(message => message.Id));
        foreach (var message in deliverable)
        {
            if (!added.Contains(message.Id)) continue;
            SafeInvoke(SmsReceived, new KdeConnectSmsReceived(message, history, !history && message.Incoming));
        }
    }

    private void ScheduleBootstrapCheck(Connection connection) => _ = Task.Run(async () =>
    {
        try { await Task.Delay(1100, lifetime.Token).ConfigureAwait(false); CheckBootstrap(connection); }
        catch (OperationCanceledException) { }
    });

    private void CheckBootstrap(Connection connection)
    {
        List<KdeConnectSmsMessage[]> deliveries = [];
        lock (connection.State.Gate)
        {
            if (!connection.State.Bootstrap) return;
            var now = DateTimeOffset.UtcNow;
            if (now < connection.State.BootstrapDeadline && (now < connection.State.QuietDeadline ||
                !connection.State.Requested.IsSubsetOf(connection.State.Responded)))
            { ScheduleBootstrapCheck(connection); return; }
            foreach (var buffered in connection.State.Buffered.Values) deliveries.Add([.. buffered]);
            connection.State.Buffered.Clear(); connection.State.Bootstrap = false; connection.State.BootstrapState = "live";
        }
        foreach (var delivery in deliveries) Deliver(connection, delivery, true);
        EmitStatus();
    }

    private async Task HandlePairPacketAsync(Connection connection, KdeConnectPacket packet, CancellationToken cancellationToken)
    {
        if (!TryParsePair(packet, out var wantsPair, out var timestamp)) return;
        var deviceId = connection.Identity.DeviceId;
        if (!wantsPair)
        {
            if (pending.TryGetValue(deviceId, out var rejected))
                AbortPairing(deviceId, rejected, "failed", "rejected", false);
            else if (store.LoadPeers().Any(value => value.Id == deviceId && value.Paired))
            {
                store.MarkUnpaired(deviceId);
                if (RemoveActive(connection)) connection.Dispose();
                pairingState = "idle"; ScheduleReconnect(false); EmitStatus();
            }
            return;
        }
        var peer = store.LoadPeers().SingleOrDefault(value => value.Id == deviceId);
        if (peer?.Paired == true)
        {
            if (timestamp is null)
            {
                if (repairReported.TryAdd(deviceId, 0))
                    SafeInvoke(PairingChanged, new KdeConnectPairingEvent("failed", deviceId,
                        connection.Identity.DeviceName, "repair_required"));
                pairingState = "failed_repair_required"; EmitStatus(); return;
            }
            return;
        }
        if (!pending.TryGetValue(deviceId, out var pairing))
        {
            if (timestamp is null) return;
            var peers = store.LoadPeers().Where(value => value.Paired).ToArray();
            var operation = new PairingOperation(peers.Length == 1 ? peers[0].Id : null,
                CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token));
            if (!pairingOperations.TryAdd(deviceId, operation)) { operation.Dispose(); return; }
            pairing = new PendingPairing(connection,
                KdeConnectProtocol.PairingCode(local.Certificate, connection.Certificate, timestamp.Value),
                DateTimeOffset.UtcNow.AddSeconds(30), true, timestamp.Value, operation);
            pairing.ConfirmRemote();
            if (!pending.TryAdd(deviceId, pairing))
            { pairingOperations.TryRemove(deviceId, out _); operation.Dispose(); return; }
            pairingState = "requested";
            EmitPairing(pairing, "requested", "");
        }
        else if (pairing.ConfirmRemote()) FinishPairing(deviceId, pairing);
        await Task.CompletedTask;
    }

    private KdeConnectPairing BeginPairingOnConnection(Connection connection)
    {
        var peers = store.LoadPeers().Where(value => value.Paired).ToArray();
        var operation = new PairingOperation(peers.Length == 1 ? peers[0].Id : null,
            CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token));
        if (!pairingOperations.TryAdd(connection.Identity.DeviceId, operation))
            return pending[connection.Identity.DeviceId].Description;
        var pairing = CreatePairing(connection, false, operation);
        if (!pending.TryAdd(connection.Identity.DeviceId, pairing))
        {
            pairingOperations.TryRemove(connection.Identity.DeviceId, out _); operation.Dispose();
            return pending[connection.Identity.DeviceId].Description;
        }
        _ = connection.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair", new JsonObject {
            ["pair"] = true, ["timestamp"] = pairing.Timestamp }), operation.Token);
        pairingState = "requested";
        EmitPairing(pairing, "requested", ""); return pairing.Description;
    }

    private PendingPairing CreatePairing(Connection connection, bool remoteConfirmed, PairingOperation operation)
    {
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        return new PendingPairing(connection, KdeConnectProtocol.PairingCode(local.Certificate,
            connection.Certificate, timestamp), DateTimeOffset.UtcNow.AddSeconds(30), false, timestamp, operation)
            { RemoteConfirmedInitially = remoteConfirmed };
    }

    private void FinishPairing(string deviceId, PendingPairing pairing)
    {
        var connection = pairing.Connection;
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var peer = new KdeConnectPeer(deviceId, connection.Identity.DeviceName,
            KdeConnectProtocol.CertificatePin(connection.Certificate), now, true, connection.Address.ToString(),
            connection.Port, now);
        Connection? oldConnection = null;
        try
        {
            lock (activeGate)
            {
                if (!pairing.MutuallyConfirmed) return;
                if (!pending.TryGetValue(deviceId, out var current) || !ReferenceEquals(current, pairing) ||
                    !staged.TryGetValue(deviceId, out var currentConnection) || !ReferenceEquals(currentConnection, connection)) return;
                if (pairing.Operation.ReplacementPeerId is { } oldId)
                {
                    store.Replace(oldId, peer);
                    active.TryRemove(oldId, out oldConnection);
                }
                else store.Confirm(peer, active.Keys);
                staged.TryRemove(deviceId, out _); active[deviceId] = connection;
                pending.TryRemove(deviceId, out _); pairingOperations.TryRemove(deviceId, out _);
                candidates.Clear();
                pairingState = "idle";
            }
        }
        catch
        {
            AbortPairing(deviceId, pairing, "failed", "storage", false);
            return;
        }
        pairing.Operation.Dispose(); oldConnection?.Dispose();
        repairReported.TryRemove(deviceId, out _); pairingFailures.TryRemove(deviceId, out _);
        EnableSms(connection); EmitPairing(pairing, "paired", ""); ScheduleReconnect(false); EmitStatus();
    }

    private static bool TryParsePair(KdeConnectPacket packet, out bool pair, out long? timestamp)
    {
        pair = false; timestamp = null;
        if (packet.Type != "kdeconnect.pair" || packet.Body.Count is < 1 or > 2 ||
            packet.Body["pair"] is not JsonValue value || !value.TryGetValue<bool>(out pair)) return false;
        if (packet.Body.Count == 1) return true;
        if (!pair || packet.Body["timestamp"] is not JsonValue time || !time.TryGetValue<long>(out var parsed) ||
            Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeSeconds() - parsed) > 1800) return false;
        timestamp = parsed; return true;
    }

    private void CleanupPending()
    {
        foreach (var item in pending.Where(item => item.Value.ExpiresAt <= DateTimeOffset.UtcNow))
            ExpirePairing(item.Key, item.Value);
    }

    private void ExpirePairing(string id, PendingPairing pairing)
    {
        AbortPairing(id, pairing, "failed", "timeout", true);
    }

    private void ExpireCandidates(DateTimeOffset? current = null)
    {
        var now = current ?? DateTimeOffset.UtcNow;
        var cutoff = now - CandidateLifetime;
        foreach (var item in candidates.Where(item => item.Value.SeenAt < cutoff && !active.ContainsKey(item.Key)))
        {
            if (staged.ContainsKey(item.Key)) continue;
            if (candidates.TryRemove(item.Key, out _))
                DebugLog("candidate.expired", $"device={item.Key} ageSeconds={(int)(now - item.Value.SeenAt).TotalSeconds}");
        }
    }

    private KdeConnectStatus BuildStatus()
    {
        lock (activeGate) return BuildStatusLocked();
    }

    private KdeConnectStatus BuildStatusLocked()
    {
        var peers = store.LoadPeers().Where(peer => peer.Paired).ToArray();
        var usable = UsableConnections();
        var unpaired = candidates.Values.Where(candidate => !peers.Any(peer => peer.Id == candidate.Identity.DeviceId)).ToArray();
        var diagnostic = unpaired.Length == 1 && staged.TryGetValue(unpaired[0].Identity.DeviceId, out var held)
            ? held : usable.Count == 1 ? usable[0] : null;
        var mismatch = pairingFailures.Values.Sum();
        var candidateAge = unpaired.Length == 1 ? Math.Max(0,
            (int)(DateTimeOffset.UtcNow - unpaired[0].SeenAt).TotalSeconds) : 0;
        var reason = usable.Count == 1 ? "" : usable.Count > 1 ? "multiple_devices" : mismatch >= 2 ? "pairing_mismatch" :
            !tcpListening ? "tcp_listener_stopped" : udp is null ? "udp_port_unavailable" : "no_device";
        return new KdeConnectStatus(usable.Count == 1, usable.Count, reason,
            !disposed && tcpListening && udp is not null, ListenerPort,
            peers.Length, usable.Count == 1 ? usable[0].Identity.DeviceId : "",
            peers.Length == 1 ? peers[0].Name : unpaired.Length == 1 ? unpaired[0].Identity.DeviceName : "",
            pending.IsEmpty ? pairingState : "requested",
            unpaired.Length, unpaired.Length == 1 ? unpaired[0].Identity.DeviceId : "",
            unpaired.Length == 1 ? unpaired[0].Identity.DeviceName : "",
            peers.Length == 1 && unpaired.Length == 1 ? peers[0].Id : "",
            unpaired.Length == 1 && staged.ContainsKey(unpaired[0].Identity.DeviceId), candidateAge,
            diagnostic?.Generation ?? 0, diagnostic?.Direction ?? "",
            usable.Count == 1 && usable[0].Identity.IncomingCapabilities.Contains(KdeConnectProtocol.SmsRequestConversations) &&
                usable[0].Identity.IncomingCapabilities.Contains(KdeConnectProtocol.SmsRequestConversation),
            diagnostic?.State.BootstrapState ?? "offline", diagnostic?.State.ParseValid ?? 0,
            diagnostic?.State.ParseSkipped ?? 0, diagnostic?.State.LastReceiveMs ?? 0, mismatch,
            Math.Max(0, (int)Math.Ceiling((nextReconnect - DateTimeOffset.UtcNow).TotalSeconds)));
    }

    private void EmitStatus() => SafeInvoke(StatusChanged, BuildStatus());
    private void EmitPairing(PendingPairing pairing, string state, string reason) =>
        SafeInvoke(PairingChanged, new KdeConnectPairingEvent(state, pairing.Connection.Identity.DeviceId,
            pairing.Connection.Identity.DeviceName, reason, pairing.Code, pairing.ExpiresAt));

    private void ScheduleReconnect(bool immediate)
    {
        if (immediate) backoffIndex = 0;
        var due = DateTimeOffset.UtcNow.AddSeconds(immediate ? 2 : ReconnectSeconds[0]);
        if (due < nextReconnect) nextReconnect = due;
    }

    private bool RemoveActive(Connection connection)
    {
        lock (activeGate) return active.TryGetValue(connection.Identity.DeviceId, out var current) &&
            ReferenceEquals(current, connection) && active.TryRemove(connection.Identity.DeviceId, out _);
    }

    private bool RemoveStaged(Connection connection)
    {
        lock (activeGate) return staged.TryGetValue(connection.Identity.DeviceId, out var current) &&
            ReferenceEquals(current, connection) && staged.TryRemove(connection.Identity.DeviceId, out _);
    }

    private bool RemovePairingOperation(string id, PairingOperation operation) =>
        ((ICollection<KeyValuePair<string, PairingOperation>>)pairingOperations).Remove(
            new KeyValuePair<string, PairingOperation>(id, operation));

    private bool AbortPairing(string deviceId, PendingPairing pairing, string eventState, string reason, bool sendReject)
    {
        lock (activeGate)
        {
            if (!((ICollection<KeyValuePair<string, PendingPairing>>)pending).Remove(
                new KeyValuePair<string, PendingPairing>(deviceId, pairing))) return false;
            pairing.Operation.Cancel(reason == "removed");
            pairingOperations.TryRemove(deviceId, out _);
            RemoveStaged(pairing.Connection);
            pairingState = "failed_" + reason;
        }
        if (sendReject)
            _ = pairing.Connection.WriteAsync(KdeConnectProtocol.Encode("kdeconnect.pair",
                new JsonObject { ["pair"] = false }), lifetime.Token);
        pairing.Connection.Dispose();
        pairing.Operation.Dispose();
        EmitPairing(pairing, eventState, reason); ScheduleReconnect(false); EmitStatus();
        return true;
    }

    private static bool ValidateCertificate(X509Certificate? certificate, string deviceId, string? requiredPin,
        ref X509Certificate2? captured)
    {
        if (certificate is null) return false;
        var value = new X509Certificate2(certificate);
        var now = DateTime.UtcNow;
        if (now < value.NotBefore.ToUniversalTime() || now > value.NotAfter.ToUniversalTime() ||
            !string.Equals(value.GetNameInfo(X509NameType.SimpleName, false), deviceId, StringComparison.Ordinal))
        { value.Dispose(); return false; }
        var pin = KdeConnectProtocol.CertificatePin(value);
        if (requiredPin is not null && (!IsPin(requiredPin) || !CryptographicOperations.FixedTimeEquals(
            Convert.FromHexString(requiredPin), Convert.FromHexString(pin))))
        { value.Dispose(); return false; }
        captured?.Dispose();
        captured = value; return true;
    }

    private static bool IsPin(string value) => value.Length == 64 && value.All(character =>
        character is >= '0' and <= '9' or >= 'a' and <= 'f');

    internal static bool IsPrivateAddress(IPAddress address)
    {
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        if (IPAddress.IsLoopback(address)) return true;
        var bytes = address.GetAddressBytes();
        if (address.AddressFamily == AddressFamily.InterNetwork)
            return bytes[0] == 10 || bytes[0] == 127 || bytes[0] == 169 && bytes[1] == 254 ||
                bytes[0] == 172 && bytes[1] is >= 16 and <= 31 || bytes[0] == 192 && bytes[1] == 168;
        return address.IsIPv6LinkLocal || (bytes[0] & 0xfe) == 0xfc;
    }

    private static TcpListener BindListener()
    {
        for (var port = KdeConnectProtocol.FirstPort; port <= KdeConnectProtocol.LastPort; port++)
        {
            var candidate = new TcpListener(IPAddress.Any, port);
            try { candidate.Start(8); return candidate; }
            catch (SocketException) { candidate.Stop(); }
        }
        throw new SocketException((int)SocketError.AddressAlreadyInUse);
    }

    private static UdpClient? TryBindUdp(bool activeDiscovery)
    {
        var socket = new UdpClient(AddressFamily.InterNetwork);
        try
        {
            if (!activeDiscovery)
            {
                socket.Client.Bind(new IPEndPoint(IPAddress.Loopback, 0));
                return socket;
            }
            socket.Client.ExclusiveAddressUse = true; socket.EnableBroadcast = true;
            socket.Client.Bind(new IPEndPoint(IPAddress.Any, KdeConnectProtocol.FirstPort)); return socket;
        }
        catch (SocketException) { socket.Dispose(); }
        /* Belegt eine andere Anwendung – etwa ein zusätzlich installiertes
           KDE Connect für Windows – den festen Suchport, blieb die Suche bisher
           vollständig aus. Ein Socket auf freiem Port kann die eigene Kennung
           weiterhin senden; das Telefon verbindet sich daraufhin selbst über
           TCP zurück. Nur das Mithören fremder Ankündigungen entfällt dann. */
        var fallback = new UdpClient(AddressFamily.InterNetwork);
        try
        {
            fallback.EnableBroadcast = true;
            fallback.Client.Bind(new IPEndPoint(IPAddress.Any, 0)); return fallback;
        }
        catch (SocketException) { fallback.Dispose(); return null; }
    }

    private static void SafeInvoke<T>(Action<T>? callback, T value)
    {
        if (callback is null) return;
        foreach (Action<T> handler in callback.GetInvocationList()) try { handler(value); } catch { }
    }

    private void Track(Task task)
    {
        backgroundTasks.TryAdd(task, 0);
        _ = task.ContinueWith(completed => backgroundTasks.TryRemove(completed, out _),
            CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }

    public void Dispose() => DisposeAsync().AsTask().GetAwaiter().GetResult();

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref disposalStarted, 1) != 0) return;
        disposed = true;
        DebugLog("stop", $"active={active.Count} staged={staged.Count} candidates={candidates.Count}");
        lifetime.Cancel(); listener.Stop(); udp?.Dispose();
        foreach (var connection in active.Values) connection.Dispose();
        foreach (var connection in staged.Values) connection.Dispose();
        foreach (var operation in pairingOperations.Values) operation.Dispose();
        active.Clear(); staged.Clear(); pending.Clear(); pairingOperations.Clear(); candidates.Clear(); connecting.Clear();
        try { await Task.WhenAll(acceptTask, discoveryTask).ConfigureAwait(false); } catch { }
        while (!backgroundTasks.IsEmpty)
        {
            var tasks = backgroundTasks.Keys.ToArray();
            if (tasks.Length == 0) break;
            try { await Task.WhenAll(tasks).ConfigureAwait(false); } catch { }
        }
        candidateSignal.Dispose(); lifetime.Dispose(); local.Certificate.Dispose();
    }

    private sealed class Connection(TcpClient client, SslStream stream, X509Certificate2 certificate,
        KdeConnectIdentity identity, IPAddress address, int port) : IDisposable
    {
        private readonly SemaphoreSlim writes = new(1, 1);
        private int closed;
        internal SslStream Stream { get; } = stream;
        internal X509Certificate2 Certificate { get; } = certificate;
        internal KdeConnectIdentity Identity { get; } = identity;
        internal IPAddress Address { get; } = address;
        internal int Port { get; } = port;
        internal SmsState State { get; } = new();
        internal int Generation { get; set; }
        internal string Direction { get; set; } = "";
        internal bool Closed => Volatile.Read(ref closed) != 0;
        internal Task Completion => completion.Task;
        private readonly TaskCompletionSource completion = new(TaskCreationOptions.RunContinuationsAsynchronously);

        internal async Task WriteAsync(byte[] packet, CancellationToken cancellationToken)
        {
            if (Closed) throw new EndOfStreamException("KDE-Connect-Verbindung ist geschlossen.");
            await writes.WaitAsync(cancellationToken).ConfigureAwait(false);
            try { await Stream.WriteAsync(packet, cancellationToken).ConfigureAwait(false); await Stream.FlushAsync(cancellationToken).ConfigureAwait(false); }
            finally { writes.Release(); }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref closed, 1) != 0) return;
            Stream.Dispose(); client.Dispose(); Certificate.Dispose(); writes.Dispose();
        }

        internal void Complete() => completion.TrySetResult();
    }

    private sealed class SmsState
    {
        internal object Gate { get; } = new();
        internal bool SmsStarted;
        internal bool Bootstrap;
        internal string BootstrapState = "idle";
        internal DateTimeOffset BootstrapStarted;
        internal DateTimeOffset QuietDeadline;
        internal DateTimeOffset BootstrapDeadline;
        internal HashSet<string> Requested { get; } = new(StringComparer.Ordinal);
        internal HashSet<string> Responded { get; } = new(StringComparer.Ordinal);
        internal Dictionary<string, List<KdeConnectSmsMessage>> Buffered { get; } = new(StringComparer.Ordinal);
        internal HashSet<string> Seen { get; } = new(StringComparer.Ordinal);
        internal Queue<string> SeenOrder { get; } = new();
        internal int ParseValid;
        internal int ParseSkipped;
        internal long LastReceiveMs;

        internal bool Remember(string id)
        {
            if (!Seen.Add(id)) return false;
            SeenOrder.Enqueue(id);
            while (SeenOrder.Count > 10_000) Seen.Remove(SeenOrder.Dequeue());
            return true;
        }

        internal void TransferFrom(SmsState previous)
        {
            lock (previous.Gate)
            {
                SmsStarted = previous.SmsStarted; Bootstrap = previous.Bootstrap;
                BootstrapState = previous.BootstrapState; BootstrapStarted = previous.BootstrapStarted;
                QuietDeadline = previous.QuietDeadline; BootstrapDeadline = previous.BootstrapDeadline;
                Requested.UnionWith(previous.Requested); Responded.UnionWith(previous.Responded);
                foreach (var item in previous.Buffered) Buffered[item.Key] = [.. item.Value];
                Seen.UnionWith(previous.Seen); foreach (var id in previous.SeenOrder) SeenOrder.Enqueue(id);
                ParseValid = previous.ParseValid; ParseSkipped = previous.ParseSkipped; LastReceiveMs = previous.LastReceiveMs;
            }
        }
    }

    private sealed class PendingPairing(Connection connection, string code, DateTimeOffset expiresAt,
        bool incoming, long timestamp, PairingOperation operation)
    {
        internal Connection Connection { get; set; } = connection;
        internal string Code { get; } = code;
        internal DateTimeOffset ExpiresAt { get; } = expiresAt;
        internal bool Incoming { get; } = incoming;
        internal long Timestamp { get; } = timestamp;
        internal PairingOperation Operation { get; } = operation;
        private readonly object gate = new();
        private bool localConfirmed;
        private bool remoteConfirmed;
        internal bool RemoteConfirmedInitially { init { remoteConfirmed = value; } }
        internal bool MutuallyConfirmed { get { lock (gate) return localConfirmed && remoteConfirmed; } }
        internal bool ConfirmLocal() { lock (gate) { localConfirmed = true; return remoteConfirmed; } }
        internal bool ConfirmRemote() { lock (gate) { remoteConfirmed = true; return localConfirmed; } }
        internal KdeConnectPairing Description => new(Connection.Identity.DeviceId, Connection.Identity.DeviceName, Code, ExpiresAt);
    }

    private sealed class PairingOperation(string? replacementPeerId, CancellationTokenSource cancellation) : IDisposable
    {
        private int removed;
        internal string? ReplacementPeerId { get; } = replacementPeerId;
        internal CancellationToken Token => cancellation.Token;
        internal bool Removed => Volatile.Read(ref removed) != 0;
        internal void Cancel(bool removed = false)
        {
            if (removed) Interlocked.Exchange(ref this.removed, 1);
            try { cancellation.Cancel(); } catch (ObjectDisposedException) { }
        }
        public void Dispose() => cancellation.Dispose();
    }
}
