using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

internal sealed class MagnolienbaumCoordinator : IDisposable
{
    private const int DefaultPort = 8737;
    internal const int MaxMessageBytes = 40 * 1024 * 1024;
    internal const int MaxInboxBytes = 64 * 1024 * 1024;
    private readonly object gate = new();
    private readonly MagnolienbaumStore storage;
    private readonly Func<string, object, Task> emit;
    private readonly HttpClient client;
    private readonly NextcloudMailboxSettingsStore mailboxSettings;
    private readonly NextcloudMailbox mailbox;
    private readonly SemaphoreSlim mailboxWorker = new(1, 1);
    private readonly SemaphoreSlim outboxWorker = new(1, 1);
    private readonly SemaphoreSlim connectionSlots = new(16, 16);
    private JsonObject state;
    private JsonArray outbox;
    private JsonArray inbox;
    private CancellationTokenSource? serviceCancellation;
    private readonly List<TcpListener> listeners = [];
    private readonly Dictionary<string, IncomingFsSession> incomingFsSessions = new(StringComparer.Ordinal);
    private UdpClient? udp;
    private Task? maintenance;
    private readonly List<Task> networkTasks = [];
    private readonly List<Task> connectionTasks = [];
    private readonly Dictionary<string, int> activeConnections = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<long>> requestTimes = new(StringComparer.Ordinal);
    private string serviceError = "";
    private string mailboxError = "";
    private string mailboxErrorCode = "none";
    private string mailboxState = "nicht_eingerichtet";
    private readonly string migrationNotice;
    private bool disposed;

    internal MagnolienbaumCoordinator(WindowsPaths paths, Func<string, object, Task> emit)
    {
        storage = new MagnolienbaumStore(paths);
        this.emit = emit;
        state = storage.LoadOrCreate();
        outbox = storage.LoadOutbox();
        var removedStatusMessages = outbox.OfType<JsonObject>().Where(item => String(item, "art") is "geraete_status_anfrage" or "geraete_status").ToArray();
        foreach (var item in removedStatusMessages) outbox.Remove(item);
        if (removedStatusMessages.Length > 0) storage.SaveOutbox(outbox);
        migrationNotice = removedStatusMessages.Length > 0
            ? $"{removedStatusMessages.Length} alte Gerätestatus-Nachricht(en) wurden terminal aus der Baumwarteschlange entfernt. Koppeln Sie das Telefon über die Telefonverbindung neu."
            : "";
        inbox = storage.LoadInbox();
        RecoverBaum1Counters();
        client = new HttpClient(new SocketsHttpHandler { UseProxy = false, ConnectTimeout = TimeSpan.FromSeconds(6) })
            { Timeout = TimeSpan.FromSeconds(8) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("Magnolie-Organizer-Windows/2.0.3");
        mailboxSettings = new NextcloudMailboxSettingsStore(paths.BaumMailboxSettings, paths.BaumMailboxPassword);
        mailbox = new NextcloudMailbox(mailboxSettings);
    }

    internal Task ResumeAsync() => Boolean(state, "an") ? StartAsync() : Task.CompletedTask;

    internal async Task ReportMailboxStatusAsync(string callback = "App.baumBriefkastenStatus")
    {
        NextcloudMailboxSettings? settings = null;
        try { settings = mailboxSettings.Load(); }
        catch (Exception error) { mailboxError = error.Message; mailboxErrorCode = MailboxErrorCode(error); mailboxState = "unvollstaendig"; }
        var hasPassword = mailboxSettings.HasApplicationPassword;
        await emit(callback, new { aktiv = settings?.MailboxActive ?? false,
            davAktiv = settings?.DavActive ?? false, briefkastenAktiv = settings?.MailboxActive ?? false,
            url = settings?.ServerBase ?? "",
            benutzer = settings?.User ?? "", kennwortVorhanden = hasPassword,
            zustand = mailboxError.Length > 0 ? "unvollstaendig" : settings is null ? "unvollstaendig" :
                !(settings.DavActive || settings.MailboxActive) ? "aus" : !hasPassword ? "unvollstaendig" :
                mailboxState == "nicht_eingerichtet" ? "bereit" : mailboxState, fehler = mailboxError,
            fehlerCode = mailboxError.Length == 0 ? "none" : mailboxErrorCode }).ConfigureAwait(false);
    }

    internal async Task SaveMailboxAsync(bool davActive, bool mailboxActive, string url, string user, string applicationPassword,
        bool deletePassword)
    {
        try
        {
            var server = NextcloudMailbox.ValidateServer(url).AbsoluteUri.TrimEnd('/');
            var validatedUser = NextcloudMailboxSettingsStore.ValidateUser(user);
            var previous = mailboxSettings.Load();
            var endpointChanged = previous is not null &&
                (previous.ServerBase != server || previous.User != validatedUser);
            if (deletePassword && applicationPassword.Length > 0)
                throw new ArgumentException("Das Kennwort kann nicht gleichzeitig gelöscht und ersetzt werden.");
            if (endpointChanged && mailboxSettings.HasApplicationPassword && applicationPassword.Length == 0)
                throw new InvalidOperationException("Bei einer neuen Serveradresse oder einem neuen Benutzer ist ein neues Anwendungskennwort erforderlich.");
            if ((davActive || mailboxActive) && (deletePassword || applicationPassword.Length == 0 && !mailboxSettings.HasApplicationPassword))
                throw new InvalidOperationException("Das Nextcloud-Anwendungskennwort fehlt.");
            var target = new NextcloudMailboxSettings(davActive, mailboxActive, server, validatedUser);
            mailboxSettings.SaveConfiguration(target, applicationPassword, deletePassword);
            mailboxError = ""; mailboxErrorCode = "none"; mailboxState = davActive || mailboxActive ? "bereit" : "aus";
        }
        catch (Exception error)
        {
            mailboxError = error.Message; mailboxErrorCode = MailboxErrorCode(error); mailboxState = "fehler";
        }
        await ReportMailboxStatusAsync("App.baumBriefkastenGespeichert").ConfigureAwait(false);
    }

    internal async Task TestMailboxAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var settings = mailboxSettings.Load() ?? throw new InvalidOperationException("Nextcloud ist nicht eingerichtet.");
            if (settings.DavActive)
            {
                using var dav = new NextcloudDavClient(mailboxSettings);
                await dav.ListSourcesAsync(cancellationToken).ConfigureAwait(false);
            }
            if (settings.MailboxActive)
                await mailbox.TestAccessAsync(String(state, "kennung"), cancellationToken).ConfigureAwait(false);
            if (!settings.DavActive && !settings.MailboxActive) throw new InvalidOperationException("Nextcloud ist nicht aktiviert.");
            mailboxError = ""; mailboxErrorCode = "none"; mailboxState = "bereit";
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
        catch (Exception error)
        {
            mailboxError = error.Message; mailboxErrorCode = MailboxErrorCode(error); mailboxState = "fehler";
        }
        await ReportMailboxStatusAsync("App.baumBriefkastenPruefung").ConfigureAwait(false);
    }

    private static string MailboxErrorCode(Exception error) => error switch
    {
        TaskCanceledException => "timeout",
        HttpRequestException { StatusCode: HttpStatusCode.Unauthorized } => "http_401",
        HttpRequestException { StatusCode: HttpStatusCode.Forbidden } => "http_403",
        HttpRequestException { StatusCode: HttpStatusCode.InsufficientStorage } => "http_507",
        HttpRequestException { StatusCode: { } status } => $"http_{(int)status}",
        CryptographicException => "credential_unavailable",
        InvalidDataException => "invalid_response",
        ArgumentException => "invalid_config",
        _ => "nextcloud_error"
    };

    internal async Task ReportStatusAsync()
    {
        object report;
        lock (gate)
        {
            var ownPublic = Convert.FromBase64String(state["oeffentlich"]!.GetValue<string>());
            var partners = state["partner"]!.AsArray().OfType<JsonObject>().Select(partner => new
            {
                kennung = String(partner, "kennung"), name = String(partner, "name"), adresse = String(partner, "adresse"),
                port = Number(partner, "port", DefaultPort), vertraut = Boolean(partner, "vertraut"),
                fernAdresse = String(partner, "fernAdresse"), fernPort = Number(partner, "fernPort", DefaultPort),
                bestaetigt = Boolean(partner, "bestaetigt"), wartet = Boolean(partner, "wartet"),
                kontakte = Boolean(partner, "kontakte"), kontaktLoeschen = Boolean(partner, "kontaktLoeschen") || Boolean(partner, "loeschungen"),
                protokoll = String(partner, "protokoll", "baum-1"), paarungsart = String(partner, "paarungsart", "lokal-v1"),
                code = MagnolienbaumCrypto.PairingCode(ownPublic, Convert.FromBase64String(String(partner, "oeffentlich"))),
                fingerabdruck = MagnolienbaumCrypto.Fingerprint(Convert.FromBase64String(String(partner, "oeffentlich"))),
                zuletzt = String(partner, "zuletzt")
            }).ToArray();
            report = new { moeglich = true, an = Boolean(state, "an"), laeuft = serviceCancellation is not null,
                name = String(state, "name"), kennung = String(state, "kennung"),
                fingerabdruck = MagnolienbaumCrypto.Fingerprint(ownPublic), port = Number(state, "port", DefaultPort),
                partner = partners, post = outbox.Count, postOffen = outbox.OfType<JsonObject>().Count(item => !Boolean(item, "aufgegeben")),
                eingang = JsonNode.Parse(inbox.ToJsonString()), fehler = serviceError, migrationHinweis = migrationNotice, windows = true };
        }
        await emit("App.baumStand", report);
    }

    internal async Task SwitchAsync(bool enabled, string name)
    {
        if (name.Length > 0) name = name[..Math.Min(60, name.Length)];
        bool restart;
        lock (gate)
        {
            restart = enabled && name.Length > 0 && name != String(state, "name") && serviceCancellation is not null;
            if (name.Length > 0) state["name"] = name;
            state["an"] = enabled;
            storage.SaveState(state);
        }
        if (!enabled || restart) await StopAsync();
        if (enabled) await StartAsync();
        await ReportStatusAsync();
    }

    internal async Task StartAsync()
    {
        lock (gate)
        {
            if (serviceCancellation is not null || !Boolean(state, "an")) return;
            serviceCancellation = new CancellationTokenSource();
            serviceError = "";
        }
        var cancellation = serviceCancellation;
        var port = Number(state, "port", DefaultPort);
        foreach (var address in new[] { IPAddress.Any, IPAddress.IPv6Any })
        {
            try
            {
                var listener = new TcpListener(address, port);
                if (address.AddressFamily == AddressFamily.InterNetworkV6) listener.Server.DualMode = false;
                listener.Start(16); listeners.Add(listener);
                networkTasks.Add(Task.Run(() => AcceptLoopAsync(listener, cancellation.Token), CancellationToken.None));
            }
            catch (SocketException) { }
        }
        if (listeners.Count == 0)
        {
            lock (gate) serviceError = $"TCP-Port {port} konnte nicht geöffnet werden; der Briefkasten bleibt verfügbar.";
        }
        try
        {
            udp = new UdpClient(new IPEndPoint(IPAddress.Any, port));
            networkTasks.Add(Task.Run(() => UdpLoopAsync(udp, cancellation.Token), CancellationToken.None));
        }
        catch (SocketException) { udp = null; }
        maintenance = Task.Run(() => MaintenanceLoopAsync(cancellation.Token), CancellationToken.None);
        await MaintainOutboxAsync(1, cancellation.Token).ConfigureAwait(false);
        await PollMailboxSafeAsync(cancellation.Token).ConfigureAwait(false);
    }

    internal async Task StopAsync()
    {
        CancellationTokenSource? cancellation;
        lock (gate) { cancellation = serviceCancellation; serviceCancellation = null; }
        if (cancellation is null) return;
        cancellation.Cancel();
        foreach (var listener in listeners) listener.Stop();
        listeners.Clear(); udp?.Dispose(); udp = null;
        lock (gate)
        {
            foreach (var session in incomingFsSessions.Values) session.Session.Dispose();
            incomingFsSessions.Clear();
        }
        var tasks = networkTasks.ToArray(); networkTasks.Clear();
        if (maintenance is not null) tasks = tasks.Append(maintenance).ToArray();
        try { await Task.WhenAll(tasks).ConfigureAwait(false); }
        catch (Exception error) when (error is OperationCanceledException or SocketException or ObjectDisposedException) { }
        Task[] handlers;
        lock (gate) { handlers = connectionTasks.ToArray(); }
        try { await Task.WhenAll(handlers).ConfigureAwait(false); }
        catch (Exception error) when (error is OperationCanceledException or SocketException or ObjectDisposedException or IOException) { }
        maintenance = null; cancellation.Dispose();
    }

    internal async Task SearchAsync()
    {
        var found = new Dictionary<string, JsonObject>();
        using var search = new UdpClient(AddressFamily.InterNetwork) { EnableBroadcast = true };
        search.Client.ReceiveTimeout = 400;
        var call = "MAGNOLIENBAUM?"u8.ToArray();
        var targets = new List<IPAddress> { IPAddress.Broadcast, IPAddress.Loopback };
        targets.AddRange(Ipv4Broadcast.DirectedAddresses());
        foreach (var target in targets.Distinct())
            try { await search.SendAsync(call, new IPEndPoint(target, Number(state, "port", DefaultPort))); } catch (SocketException) { }
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(1.5));
        while (!timeout.IsCancellationRequested)
        {
            try
            {
                var packet = await search.ReceiveAsync(timeout.Token);
                var item = JsonNode.Parse(packet.Buffer) as JsonObject;
                var id = item is null ? "" : String(item, "kennung");
                if (String(item!, "magnolie") != "baum-1" || id.Length == 0 || id == String(state, "kennung")) continue;
                item!["adresse"] = packet.RemoteEndPoint.Address.ToString(); item["fundart"] = "udp"; found[id] = item;
            }
            catch (OperationCanceledException) { break; } catch (Exception) { }
        }
        await emit("App.baumGefunden", new { nachbarn = found.Values.Select(item => JsonNode.Parse(item.ToJsonString())).ToArray() });
    }

    internal async Task PairV1Async(string host, int port, string expectedFingerprint)
    {
        try
        {
            var expected = NormalizeFingerprint(expectedFingerprint);
            if (expectedFingerprint.Length > 0 && expected.Length == 0) throw new ArgumentException("Der eingegebene Fingerabdruck ist unvollständig.");
            var request = MagnolienbaumPairing.Identity(state);
            var response = await PostAsync(BuildUri(host, port, "/magnolie/v1/paarung"), request, CancellationToken.None);
            var publicKey = Convert.FromBase64String(String(response, "oeffentlich"));
            if (publicKey.Length != 32) throw new InvalidDataException("Der andere Zweig sandte keinen gültigen Schlüssel.");
            var fingerprint = MagnolienbaumCrypto.Fingerprint(publicKey);
            if (expected.Length > 0 && expected != fingerprint) throw new CryptographicException($"Der Fingerabdruck stimmt nicht überein (empfangen: {fingerprint}).");
            JsonObject partner;
            var identity = response.DeepClone().AsObject(); identity.Remove("code");
            lock (gate) { partner = MagnolienbaumPairing.AddPartner(state, identity, host, false); storage.SaveState(state); }
            await emit("App.baumPaarung", new { ok = true, fehler = "", kennung = String(partner, "kennung"), name = String(partner, "name"),
                code = MagnolienbaumCrypto.PairingCode(Convert.FromBase64String(String(state, "oeffentlich")), publicKey), fingerabdruck = fingerprint });
        }
        catch (Exception error) { await emit("App.baumPaarung", new { ok = false, fehler = $"Der andere Zweig antwortet nicht ({error.Message})." }); }
    }

    internal JsonObject CreatePairingFile(string address, int port)
    {
        lock (gate)
        {
            var document = MagnolienbaumPairing.CreateFile(state, address, port, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            storage.SaveState(state); return document;
        }
    }

    internal async Task ImportPairingFileAsync(JsonObject document)
    {
        try
        {
            MagnolienbaumPairing.ValidateFile(document, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            var request = MagnolienbaumPairing.BuildRequest(state, document);
            var target = document["ziel"]!.AsObject(); JsonObject response;
            try { response = await PostAsync(BuildUri(String(target, "adresse"), Number(target, "port", DefaultPort), "/magnolie/v2/paarung"), request, CancellationToken.None); }
            catch (Exception) { response = await PostAsync(BuildUri(String(target, "adresse"), Number(target, "port", DefaultPort), "/magnolie/v2/paarung"), request, CancellationToken.None); }
            MagnolienbaumPairing.ValidateResponse(document, request, response);
            JsonObject partner;
            lock (gate)
            {
                partner = MagnolienbaumPairing.AddPartner(state, document["einlader"]!.AsObject(), String(target, "adresse"), true);
                storage.SaveState(state);
            }
            await emit("App.baumPaarungsdatei", new { ok = true, art = "importiert", name = String(partner, "name"), fehler = "" });
            await ReportStatusAsync();
        }
        catch (Exception error) { await emit("App.baumPaarungsdatei", new { ok = false, art = "importiert", fehler = error.Message }); }
    }

    internal async Task ConfirmAsync(string id, bool yes)
    {
        lock (gate)
        {
            var partners = state["partner"]!.AsArray();
            var partner = Partner(id);
            if (partner is not null && yes) { partner["bestaetigt"] = true; partner["wartet"] = false; }
            else if (partner is not null) partners.Remove(partner);
            storage.SaveState(state);
        }
        await ReportStatusAsync();
    }

    internal async Task RemoveAsync(string id) { lock (gate) { var partner = Partner(id); if (partner is not null) state["partner"]!.AsArray().Remove(partner); storage.SaveState(state); } await ReportStatusAsync(); }

    internal async Task SetPartnerAsync(string id, bool trusted, bool contacts, bool deletions, string remoteAddress, int remotePort)
    {
        try
        {
            if (remoteAddress.Length > 0) _ = BuildUri(remoteAddress, remotePort, "/");
            lock (gate)
            {
                var partner = Partner(id); if (partner is null || !Boolean(partner, "bestaetigt")) throw new InvalidOperationException("Dieser Zweig wurde noch nicht bestätigt.");
                partner["vertraut"] = trusted; partner["kontakte"] = contacts; partner["kontaktLoeschen"] = deletions;
                partner.Remove("loeschungen");
                partner["fernAdresse"] = remoteAddress; partner["fernPort"] = remoteAddress.Length > 0 ? remotePort : DefaultPort;
                storage.SaveState(state);
            }
            await emit("App.baumPartnerEinstellungen", new { ok = true, fehler = "" });
        }
        catch (Exception error) { await emit("App.baumPartnerEinstellungen", new { ok = false, fehler = error.Message }); }
        await ReportStatusAsync();
    }

    internal async Task SendAsync(string id, string kind, JsonNode content)
    {
        if (kind is not ("aufgabe" or "stand" or "termin" or "kontakt" or "notiz" or "notiz_sync" or "sync_anfrage" or "kontakt_sync" or "kontakt_loeschen"))
        { await emit("App.baumGesendet", new { ok = false, fehler = "Diese Art kann nicht geteilt werden." }); return; }
        if (kind is "kontakt_sync" or "kontakt_loeschen")
        {
            try
            {
                var candidate = content.DeepClone().AsObject(); candidate["art"] = kind;
                if (kind == "kontakt_sync") BaumContactSyncContract.Validate(candidate);
                else if (kind == "kontakt_loeschen") BaumContactSyncContract.ValidateDelete(candidate);
            }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException)
            { await emit("App.baumGesendet", new { ok = false, fehler = error.Message }); return; }
        }
        JsonObject? partner;
        var queuedId = MagnolienbaumStore.RandomId(12);
        lock (gate)
        {
            partner = Partner(id);
            if (partner is null || !Boolean(partner, "bestaetigt") ||
                kind == "kontakt_loeschen" && (!Boolean(partner, "kontakte") ||
                    !(Boolean(partner, "kontaktLoeschen") || Boolean(partner, "loeschungen")))) { partner = null; }
            else
            {
                var payload = content.DeepClone().AsObject(); payload["art"] = kind;
                var candidate = outbox.DeepClone().AsArray();
                candidate.Add(new JsonObject { ["id"] = queuedId, ["transportId"] = Convert.ToBase64String(RandomNumberGenerator.GetBytes(16)),
                    ["an"] = id, ["art"] = kind, ["inhalt"] = payload, ["versuche"] = 0, ["zuletzt"] = "", ["angelegt"] = Timestamp() });
                storage.SaveOutbox(candidate);
                outbox = candidate;
            }
        }
        if (partner is null) { await emit("App.baumGesendet", new { ok = false, fehler = "Dieser Zweig wurde noch nicht bestätigt." }); return; }
        var report = await MaintainOutboxAsync(0, serviceCancellation?.Token ?? CancellationToken.None);
        bool deletionOpen;
        lock (gate) deletionOpen = kind == "kontakt_loeschen" &&
            outbox.OfType<JsonObject>().Any(item => String(item, "id") == queuedId);
        if (deletionOpen)
        {
            lock (gate)
            {
                var candidate = new JsonArray(outbox.OfType<JsonObject>().Where(item => String(item, "id") != queuedId)
                    .Select(item => item.DeepClone()).ToArray());
                storage.SaveOutbox(candidate);
                outbox = candidate;
            }
            await emit("App.baumGesendet", new { ok = false, fehler = "Der Löschvorschlag wurde nicht zugestellt und nicht vorgemerkt." });
            await ReportStatusAsync(); return;
        }
        await emit("App.baumGesendet", new { ok = true, fehler = "", zugestellt = report.Delivered, offen = report.Open, an = String(partner, "name", id) });
        await ReportStatusAsync();
    }

    internal void ClearInbox(IEnumerable<string> ids)
    {
        var set = ids.ToHashSet(StringComparer.Ordinal);
        lock (gate) { inbox = new JsonArray(inbox.OfType<JsonObject>().Where(item => !set.Contains(String(item, "id"))).Select(item => item.DeepClone()).ToArray()); storage.SaveInbox(inbox); }
    }

    private async Task<QueueReport> MaintainOutboxAsync(int maximum, CancellationToken cancellation)
    {
        await outboxWorker.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            List<JsonObject> due;
            lock (gate)
            {
                due = outbox.OfType<JsonObject>().Where(item => !Boolean(item, "aufgegeben"))
                    .GroupBy(item => String(item, "an"), StringComparer.Ordinal).Select(group => group.First())
                    .Where(IsDue).Take(maximum == 0 ? int.MaxValue : maximum).ToList();
            }
            var delivered = 0;
            foreach (var item in due)
            {
                cancellation.ThrowIfCancellationRequested();
                JsonObject? partner; lock (gate) { partner = Partner(String(item, "an")); }
                if (partner is null || TooOld(item)) { lock (gate) { item["aufgegeben"] = true; storage.SaveOutbox(outbox); } continue; }
                var success = false;
                try { success = await DeliverAsync(partner, item, cancellation).ConfigureAwait(false); }
                catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
                catch (Exception error) { mailboxState = "fehler"; mailboxError = error.Message; }
                lock (gate)
                {
                    if (success) { outbox.Remove(item); delivered++; }
                    else { item["versuche"] = Number(item, "versuche") + 1; item["zuletzt"] = Timestamp(); }
                    storage.SaveOutbox(outbox); storage.SaveState(state);
                }
            }
            lock (gate) return new QueueReport(delivered, outbox.OfType<JsonObject>().Count(item => !Boolean(item, "aufgegeben")));
        }
        finally { outboxWorker.Release(); }
    }

    private async Task<bool> DeliverAsync(JsonObject partner, JsonObject item, CancellationToken cancellation)
    {
        if (String(partner, "protokoll", "baum-1") == "baum-fs1") return await DeliverFsAsync(partner, item, cancellation).ConfigureAwait(false);
        var transportId = ReadTransportId(item);
        var ownId = String(state, "kennung");
        var partnerId = String(partner, "kennung");
        var key = PartnerKey(partner);
        var storedEnvelope = item["briefUmschlag"] as JsonObject;
        long counter = Long(item, "briefZaehler");
        JsonObject envelope = storedEnvelope ?? new JsonObject();
        if (storedEnvelope is null)
        {
            lock (gate)
            {
                counter = Long(partner, "zaehler_raus") + 1; partner["zaehler_raus"] = counter;
                envelope = MagnolienbaumCrypto.EncryptBaum1(key, ownId, counter, item["inhalt"]!.DeepClone());
                item["briefUmschlag"] = envelope.DeepClone(); item["briefZaehler"] = counter;
                storage.SaveOutbox(outbox); storage.SaveState(state);
            }
        }
        var fallbackAllowed = true;
        foreach (var endpoint in Endpoints(partner))
            try { _ = await PostAsync(BuildUri(endpoint.Host, endpoint.Port, "/magnolie/v1/nachricht"), envelope, cancellation).ConfigureAwait(false); return true; }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
            catch (Exception error) { fallbackAllowed &= DirectUnavailable(error); }
        if (MailboxEnabled())
        {
            if (await mailbox.ReceiptExistsAsync(transportId, partnerId, ownId, key, cancellation).ConfigureAwait(false))
            {
                try { await mailbox.DeleteIncomingAsync(partnerId, transportId, cancellation).ConfigureAwait(false); } catch { }
                try { await mailbox.DeleteReceiptAsync(ownId, transportId, cancellation).ConfigureAwait(false); } catch { }
                return true;
            }
            if (fallbackAllowed)
            {
                await mailbox.EnsureHierarchyAsync(partnerId, cancellation).ConfigureAwait(false);
                _ = await mailbox.UploadAsync(transportId, ownId, partnerId, envelope, key, cancellation).ConfigureAwait(false);
                mailboxState = "hinterlegt"; mailboxError = "";
            }
        }
        return false;
    }

    private async Task<bool> DeliverFsAsync(JsonObject partner, JsonObject item, CancellationToken cancellation)
    {
        foreach (var endpoint in Endpoints(partner))
        {
            using var start = MagnolienbaumFs1.BuildStart(state, partner);
            MagnolienbaumFsSession? session = null;
            try
            {
                var basis = BuildUri(endpoint.Host, endpoint.Port, "/");
                var response = await PostAsync(new Uri(basis, "/magnolie/v2/sitzung"), start.Message, cancellation).ConfigureAwait(false);
                session = MagnolienbaumFs1.OpenResponse(state, partner, start.Message, response, start.EphemeralPrivate);
                var envelope = MagnolienbaumFs1.BuildEnvelope(session, String(state, "kennung"), String(partner, "kennung"),
                    item["inhalt"]!.DeepClone(), String(item, "transportId"));
                var acknowledgement = await PostAsync(new Uri(basis, "/magnolie/v2/nachricht"), envelope, cancellation).ConfigureAwait(false);
                if (MagnolienbaumFs1.VerifyAcknowledgement(session, envelope, acknowledgement))
                {
                    lock (gate) { partner["zuletzt"] = Timestamp(); }
                    return true;
                }
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
            catch (Exception) { }
            finally { session?.Dispose(); }
        }
        return false;
    }

    private async Task AcceptLoopAsync(TcpListener listener, CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                var socket = await listener.AcceptTcpClientAsync(cancellation).ConfigureAwait(false);
                if (!await connectionSlots.WaitAsync(0, cancellation).ConfigureAwait(false)) { socket.Dispose(); continue; }
                var source = Source(socket);
                if (!TryBeginConnection(source)) { socket.Dispose(); connectionSlots.Release(); continue; }
                Task? handler = null;
                handler = Task.Run(async () =>
                {
                    try { await HandleConnectionAsync(socket, cancellation).ConfigureAwait(false); }
                    finally
                    {
                        EndConnection(source); socket.Dispose(); connectionSlots.Release();
                        lock (gate) { connectionTasks.Remove(handler!); }
                    }
                }, CancellationToken.None);
                lock (gate)
                {
                    connectionTasks.RemoveAll(task => task.IsCompleted);
                    connectionTasks.Add(handler);
                }
            }
            catch (OperationCanceledException) { break; } catch (SocketException) when (cancellation.IsCancellationRequested) { break; }
        }
    }

    private async Task HandleConnectionAsync(TcpClient socket, CancellationToken serviceToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(serviceToken); timeout.CancelAfter(TimeSpan.FromSeconds(45));
        socket.ReceiveTimeout = 5000; socket.SendTimeout = 5000;
        var stream = socket.GetStream(); var header = new List<byte>(1024); var matched = 0;
        while (header.Count < 16384 && matched < 4)
        {
            var one = new byte[1]; if (await stream.ReadAsync(one, timeout.Token).ConfigureAwait(false) != 1) return; header.Add(one[0]);
            matched = one[0] == "\r\n\r\n"u8[matched] ? matched + 1 : one[0] == (byte)'\r' ? 1 : 0;
        }
        if (matched != 4) { await WriteResponseAsync(stream, 400, Error("Die Anfrage ist unlesbar."), timeout.Token).ConfigureAwait(false); return; }
        var lines = Encoding.ASCII.GetString(header.ToArray()).Split("\r\n", StringSplitOptions.None);
        var requestLine = lines[0].Split(' ');
        if (requestLine.Length != 3 || requestLine[0] != "POST") { await WriteResponseAsync(stream, 404, Error("Unbekannter Endpunkt."), timeout.Token).ConfigureAwait(false); return; }
        var source = Source(socket);
        if (!RequestAllowed(source, requestLine[1] is "/magnolie/v1/paarung" or "/magnolie/v2/paarung"))
        { await WriteResponseAsync(stream, 429, Error("Zu viele Anfragen."), timeout.Token).ConfigureAwait(false); return; }
        var headers = lines.Skip(1).Where(line => line.Length > 0).Select(line => line.Split(':', 2)).Where(parts => parts.Length == 2).ToArray();
        if (headers.Any(parts => parts[0].Equals("Transfer-Encoding", StringComparison.OrdinalIgnoreCase)) || headers.Any(parts => parts[0].Equals("Expect", StringComparison.OrdinalIgnoreCase)))
        { await WriteResponseAsync(stream, 400, Error("Die Anfrage ist unlesbar."), timeout.Token).ConfigureAwait(false); return; }
        var lengths = headers.Where(parts => parts[0].Equals("Content-Length", StringComparison.OrdinalIgnoreCase)).Select(parts => parts[1].Trim()).ToArray();
        if (lengths.Length == 0) { await WriteResponseAsync(stream, 411, Error("Content-Length fehlt."), timeout.Token).ConfigureAwait(false); return; }
        if (lengths.Length != 1 || !long.TryParse(lengths[0], out var length) || length.ToString() != lengths[0] || length < 0)
        { await WriteResponseAsync(stream, 400, Error("Die Anfrage ist unlesbar."), timeout.Token).ConfigureAwait(false); return; }
        if (!RequestBodyAllowed(requestLine[1], length)) { await WriteResponseAsync(stream, 413, Error("Die Nachricht ist zu groß."), timeout.Token).ConfigureAwait(false); return; }
        var body = new byte[(int)length]; await stream.ReadExactlyAsync(body, timeout.Token).ConfigureAwait(false);
        JsonObject payload;
        try { payload = JsonNode.Parse(body) as JsonObject ?? throw new JsonException(); }
        catch (JsonException) { await WriteResponseAsync(stream, 400, Error("Die Anfrage ist unlesbar."), timeout.Token).ConfigureAwait(false); return; }
        var response = HandleRequest(requestLine[1], payload, source);
        await WriteResponseAsync(stream, response.Status, response.Body, timeout.Token).ConfigureAwait(false);
        if (response.Notify) { await ReportStatusAsync().ConfigureAwait(false); }
    }

    internal static int RequestBodyLimit(string path) =>
        path is "/magnolie/v1/nachricht" or "/magnolie/v2/nachricht" ? MaxMessageBytes : 128 * 1024;

    internal static bool RequestBodyAllowed(string path, long length) =>
        length >= 0 && length <= RequestBodyLimit(path);

    private HttpResult HandleRequest(string path, JsonObject payload, string source)
    {
        try
        {
            lock (gate)
            {
                if (!Boolean(state, "an")) return new(503, Error("Der Magnolienbaum ist ausgeschaltet."));
                if (path == "/magnolie/v1/paarung")
                {
                    var partner = MagnolienbaumPairing.AddPartner(state, payload, source, false); storage.SaveState(state);
                    var response = MagnolienbaumPairing.Identity(state);
                    response["code"] = MagnolienbaumCrypto.PairingCode(Convert.FromBase64String(String(state, "oeffentlich")), Convert.FromBase64String(String(partner, "oeffentlich")));
                    return new(200, response, true);
                }
                if (path == "/magnolie/v2/paarung")
                {
                    var response = MagnolienbaumPairing.AcceptRequest(state, payload, source, DateTimeOffset.UtcNow.ToUnixTimeSeconds()); storage.SaveState(state);
                    return new(200, response, true);
                }
                if (path == "/magnolie/v2/sitzung")
                {
                    var partner = Partner(String(payload, "von"));
                    if (partner is null || !Boolean(partner, "bestaetigt")) throw new InvalidOperationException("Dieser Zweig wurde noch nicht bestätigt.");
                    var now = Stopwatch.GetTimestamp();
                    foreach (var expired in incomingFsSessions.Where(item => item.Value.Expires <= now).Select(item => item.Key).ToArray())
                    { incomingFsSessions[expired].Session.Dispose(); incomingFsSessions.Remove(expired); }
                    if (incomingFsSessions.Count >= 64) throw new InvalidOperationException("Zu viele sichere Sitzungen sind offen.");
                    var result = MagnolienbaumFs1.BuildResponse(state, partner, payload);
                    if (incomingFsSessions.ContainsKey(result.Session.Sid))
                    { result.Session.Dispose(); throw new InvalidOperationException("Diese sichere Sitzung existiert bereits."); }
                    incomingFsSessions[result.Session.Sid] = new IncomingFsSession(result.Session, String(partner, "kennung"),
                        NormalizeSource(source), now + 30L * Stopwatch.Frequency);
                    return new(200, result.Response);
                }
                if (path == "/magnolie/v2/nachricht") return HandleFsMessage(payload, source);
                if (path == "/magnolie/v1/nachricht")
                {
                    var partner = Partner(String(payload, "von"));
                    if (partner is null || !Boolean(partner, "bestaetigt")) throw new InvalidOperationException("Dieser Zweig wurde noch nicht bestätigt.");
                    var content = MagnolienbaumCrypto.DecryptBaum1(PartnerKey(partner), payload, String(partner, "kennung"), Long(partner, "zaehler_rein"), out var counter);
                    var entry = StoreIncoming(partner, content);
                    partner["zaehler_rein"] = counter; partner["zuletzt"] = Timestamp();
                    storage.SaveState(state);
                    return new(200, new JsonObject { ["ok"] = true, ["art"] = entry?["art"]?.GetValue<string>() ?? content["art"]!.GetValue<string>() }, true);
                }
                return new(404, Error("Unbekannter Endpunkt."));
            }
        }
        catch (InboxFullException error) { return new(503, Error(error.Message)); }
        catch (Exception error) { return new(403, Error(error.Message)); }
    }

    private HttpResult HandleFsMessage(JsonObject payload, string source)
    {
        var sid = String(payload, "sid");
        if (!incomingFsSessions.Remove(sid, out var incoming) || incoming.Expires <= Stopwatch.GetTimestamp() ||
            incoming.Source != NormalizeSource(source))
        {
            incoming?.Session.Dispose();
            throw new InvalidOperationException("Die sichere Sitzung ist unbekannt oder abgelaufen.");
        }
        using (incoming.Session)
        {
            var partner = Partner(incoming.PartnerId);
            if (partner is null || !Boolean(partner, "bestaetigt")) throw new InvalidOperationException("Dieser Zweig wurde noch nicht bestätigt.");
            var opened = MagnolienbaumFs1.OpenEnvelope(incoming.Session, String(state, "kennung"), String(partner, "kennung"), payload);
            var seen = partner["transportIds"] as JsonArray ?? new JsonArray();
            if (!seen.Any(item => item?.GetValue<string>() == opened.TransportId))
            {
                StoreIncoming(partner, opened.Content);
                seen.Add(opened.TransportId);
                while (seen.Count > 256) seen.RemoveAt(0);
                partner["transportIds"] = seen;
            }
            partner["protokoll"] = "baum-fs1"; partner["zuletzt"] = Timestamp();
            storage.SaveState(state);
            return new HttpResult(200, MagnolienbaumFs1.BuildAcknowledgement(incoming.Session, payload), true);
        }
    }

    private JsonObject? StoreIncoming(JsonObject partner, JsonNode content, string briefTransportId = "")
    {
        var kind = content["art"]?.GetValue<string>() ?? "aufgabe";
        if (kind == "kontakt_sync") BaumContactSyncContract.Validate(content);
        if (kind == "kontakt_loeschen")
        {
            BaumContactSyncContract.ValidateDelete(content);
            if (!Boolean(partner, "kontakte") || !Boolean(partner, "loeschungen"))
                throw new InvalidOperationException("Löschvorschläge sind für diesen Partner nicht freigegeben.");
            if (content["quelle"]!.GetValue<string>() != String(partner, "kennung"))
                throw new InvalidOperationException("Die Quelle des Löschvorschlags stimmt nicht mit dem Partner überein.");
            var duplicate = inbox.OfType<JsonObject>().FirstOrDefault(item => String(item, "von") == String(partner, "kennung") &&
                String(item, "art") == kind && String(item["inhalt"]!.AsObject(), "freigabeId") == content["freigabeId"]!.GetValue<string>() &&
                String(item["inhalt"]!.AsObject(), "quelle") == content["quelle"]!.GetValue<string>() &&
                Long(item["inhalt"]!.AsObject(), "version") == content["version"]!.GetValue<long>());
            if (duplicate is not null) return duplicate;
        }
        if (inbox.Count >= 500) throw new InboxFullException("Der Magnolienbaum-Eingang ist voll.");
        var entry = new JsonObject { ["id"] = MagnolienbaumStore.RandomId(12), ["von"] = String(partner, "kennung"),
            ["vonName"] = String(partner, "name"), ["art"] = kind,
            ["inhalt"] = content.DeepClone(), ["empfangen"] = Timestamp() };
        if (briefTransportId.Length > 0) entry["briefTransportId"] = briefTransportId;
        var candidate = inbox.DeepClone().AsArray(); candidate.Add(entry);
        if (Encoding.UTF8.GetByteCount(candidate.ToJsonString()) > MaxInboxBytes)
            throw new InboxFullException("Der Magnolienbaum-Eingang ist zu groß.");
        storage.SaveInbox(candidate); inbox = candidate;
        return entry;
    }

    private async Task UdpLoopAsync(UdpClient socket, CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                var packet = await socket.ReceiveAsync(cancellation).ConfigureAwait(false);
                if (!packet.Buffer.AsSpan().SequenceEqual("MAGNOLIENBAUM?"u8)) continue;
                JsonObject response;
                lock (gate) response = new JsonObject { ["magnolie"] = "baum-1", ["name"] = String(state, "name"),
                    ["kennung"] = String(state, "kennung"), ["fingerabdruck"] = MagnolienbaumCrypto.Fingerprint(Convert.FromBase64String(String(state, "oeffentlich"))),
                    ["port"] = Number(state, "port", DefaultPort) };
                await socket.SendAsync(Encoding.UTF8.GetBytes(response.ToJsonString()), packet.RemoteEndPoint, cancellation).ConfigureAwait(false);
            }
            catch (OperationCanceledException) { break; } catch (SocketException) when (cancellation.IsCancellationRequested) { break; }
        }
    }

    private async Task MaintenanceLoopAsync(CancellationToken cancellation)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(30));
        try
        {
            while (await timer.WaitForNextTickAsync(cancellation).ConfigureAwait(false))
            {
                try { await MaintainOutboxAsync(1, cancellation).ConfigureAwait(false); }
                catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
                catch (Exception error) { serviceError = error.Message; }
                await PollMailboxSafeAsync(cancellation).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
    }

    private async Task PollMailboxSafeAsync(CancellationToken cancellation)
    {
        if (!MailboxEnabled() || !await mailboxWorker.WaitAsync(0, cancellation).ConfigureAwait(false)) return;
        try
        {
            var ownId = String(state, "kennung");
            await mailbox.EnsureHierarchyAsync(ownId, cancellation).ConfigureAwait(false);
            var pending = new List<(string Sender, byte[] Id, JsonObject Envelope)>();
            long pendingBytes = 0;
            Exception? documentError = null;
            foreach (var id in await mailbox.ListIncomingAsync(ownId, cancellation).ConfigureAwait(false))
            {
                if (pending.Count >= 256)
                { documentError ??= new InvalidDataException("Der Briefkasten enthält zu viele gleichzeitig wartende Nachrichten."); break; }
                try
                {
                    var document = await mailbox.GetIncomingDocumentAsync(ownId, id, cancellation).ConfigureAwait(false);
                    if (pendingBytes + document.LongLength > 64L * 1024 * 1024)
                    { documentError ??= new InvalidDataException("Der Briefkasten-Rückstand ist für einen Prüflauf zu groß."); break; }
                    var sender = NextcloudMailboxProtocol.ReadSender(document, id, ownId);
                    JsonObject partner;
                    lock (gate) partner = Partner(sender) ?? throw new InvalidDataException("Der Briefkasten-Absender ist unbekannt.");
                    var envelope = NextcloudMailboxProtocol.ReadMessage(document, id, sender, ownId,
                        PartnerKey(partner)) as JsonObject ?? throw new InvalidDataException("Der Briefkasten-Umschlag ist ungültig.");
                    pending.Add((sender, id, envelope));
                    pendingBytes += document.LongLength;
                }
                catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
                catch (Exception error) { documentError ??= error; }
            }
            foreach (var entry in pending.OrderBy(value => value.Sender, StringComparer.Ordinal)
                         .ThenBy(value => Long(value.Envelope, "zaehler")))
                await AcceptMailboxMessageAsync(ownId, entry.Sender, entry.Id, entry.Envelope, cancellation).ConfigureAwait(false);
            mailboxState = documentError is null ? "bereit" : "unvollstaendig";
            mailboxError = documentError?.Message ?? "";
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
        catch (Exception error) { mailboxState = "fehler"; mailboxError = error.Message; }
        finally { mailboxWorker.Release(); }
    }

    private async Task AcceptMailboxMessageAsync(string ownId, string sender, byte[] transportId, JsonObject envelope,
        CancellationToken cancellation)
    {
        JsonObject partner;
        byte[] key;
        var duplicate = false;
        lock (gate)
        {
            partner = Partner(sender) ?? throw new InvalidDataException("Der Briefkasten-Absender ist unbekannt.");
            key = PartnerKey(partner);
            var seen = partner["brief_transport_ids"] as JsonArray;
            var transportText = MagnolienbaumCrypto.Base64Url(transportId);
            duplicate = seen?.Any(value => value?.GetValue<string>() == transportText) == true ||
                inbox.OfType<JsonObject>().Any(value => String(value, "briefTransportId") == transportText);
            var expectedCounter = checked(Long(partner, "zaehler_rein") + 1);
            if (!duplicate && Long(envelope, "zaehler") == expectedCounter)
            {
                var plain = MagnolienbaumCrypto.DecryptBaum1(key, envelope, sender,
                    Long(partner, "zaehler_rein"), out var counter);
                _ = StoreIncoming(partner, plain, transportText) ?? throw new InvalidDataException("Der Briefkasteninhalt ist ungültig.");
                partner["zaehler_rein"] = counter;
                seen ??= new JsonArray(); seen.Add(transportText);
                while (seen.Count > 2048) seen.RemoveAt(0);
                partner["brief_transport_ids"] = seen; storage.SaveState(state);
            }
            else if (duplicate)
            {
                // Eine bereits dauerhaft angenommene Nachricht darf erneut quittiert werden.
            }
            else return;
        }
        await mailbox.WriteReceiptAsync(transportId, ownId, sender, key, cancellation).ConfigureAwait(false);
        await mailbox.DeleteIncomingAsync(ownId, transportId, cancellation).ConfigureAwait(false);
        if (!duplicate) await emit("App.baumNachrichtEmpfangen", new { von = sender }).ConfigureAwait(false);
    }

    private async Task<JsonObject> PostAsync(Uri uri, JsonObject payload, CancellationToken cancellation)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, uri);
        request.Content = new ByteArrayContent(Encoding.UTF8.GetBytes(payload.ToJsonString()));
        request.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellation).ConfigureAwait(false);
        byte[] bytes;
        try { bytes = await ReadDirectResponseAsync(response, cancellation).ConfigureAwait(false); }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
        catch (Exception error) { throw new InvalidDataException("Die direkte Gegenstelle hat keine vollständige Antwort gesendet.", error); }
        JsonObject result;
        try { result = JsonNode.Parse(bytes) as JsonObject ?? throw new JsonException(); }
        catch (JsonException error) { throw new InvalidDataException("Die Antwort ist unlesbar.", error); }
        if (!response.IsSuccessStatusCode) throw new HttpRequestException(
            String(result, "fehler", response.ReasonPhrase ?? "HTTP-Fehler"), null, response.StatusCode);
        return result;
    }

    private static async Task<byte[]> ReadDirectResponseAsync(HttpResponseMessage response, CancellationToken cancellation)
    {
        const int maximum = 128 * 1024;
        if (response.Content.Headers.ContentLength > maximum) throw new InvalidDataException("Die Antwort ist zu groß.");
        await using var input = await response.Content.ReadAsStreamAsync(cancellation).ConfigureAwait(false);
        using var output = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var read = await input.ReadAsync(buffer, cancellation).ConfigureAwait(false);
            if (read == 0) return output.ToArray();
            if (output.Length + read > maximum) throw new InvalidDataException("Die Antwort ist zu groß.");
            output.Write(buffer, 0, read);
        }
    }

    private byte[] PartnerKey(JsonObject partner) => MagnolienbaumCrypto.PartnerKey(Convert.FromBase64String(String(state, "geheim")),
        Convert.FromBase64String(String(partner, "oeffentlich")), String(state, "kennung"), String(partner, "kennung"));

    private JsonObject? Partner(string id) => state["partner"]!.AsArray().OfType<JsonObject>().FirstOrDefault(item => String(item, "kennung") == id);

    private static IEnumerable<(string Host, int Port)> Endpoints(JsonObject partner)
    {
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var endpoint in new[] { (String(partner, "adresse"), Number(partner, "port", DefaultPort)), (String(partner, "fernAdresse"), Number(partner, "fernPort", DefaultPort)) })
            if (endpoint.Item1.Length > 0 && result.Add(endpoint.Item1 + "\0" + endpoint.Item2)) yield return (endpoint.Item1, endpoint.Item2);
    }

    private static Uri BuildUri(string host, int port, string path)
    {
        if (port is < 1 or > 65535 || string.IsNullOrWhiteSpace(host) || host.Any(character => char.IsControl(character) || "/\\@?#".Contains(character)))
            throw new ArgumentException("Host oder Port ist ungültig.");
        var clean = host.Trim().TrimStart('[').TrimEnd(']');
        return new UriBuilder(Uri.UriSchemeHttp, clean, port, path).Uri;
    }

    private bool MailboxEnabled()
    {
        try { return mailboxSettings.Load() is { Active: true } && mailboxSettings.HasApplicationPassword; }
        catch (Exception error) { mailboxState = "fehler"; mailboxError = error.Message; return false; }
    }

    private void RecoverBaum1Counters()
    {
        var changed = false;
        foreach (var group in outbox.OfType<JsonObject>().Where(item => item["briefUmschlag"] is JsonObject)
                     .GroupBy(item => String(item, "an"), StringComparer.Ordinal))
        {
            var partner = Partner(group.Key);
            if (partner is null) continue;
            var reserved = group.Max(item => Long(item, "briefZaehler"));
            if (reserved <= Long(partner, "zaehler_raus")) continue;
            partner["zaehler_raus"] = reserved; changed = true;
        }
        if (changed) storage.SaveState(state);
    }

    private static byte[] ReadTransportId(JsonObject item)
    {
        var id = Convert.FromBase64String(String(item, "transportId"));
        if (id.Length != 16) throw new InvalidDataException("Die Transportkennung ist ungültig.");
        return id;
    }

    internal static bool DirectUnavailable(Exception error) => error switch
    {
        HttpRequestException { StatusCode: null } => true,
        IOException or SocketException or TimeoutException => true,
        TaskCanceledException => true,
        _ => false
    };

    private static bool IsDue(JsonObject item)
    {
        var attempts = Number(item, "versuche"); if (attempts == 0) return true;
        if (!DateTime.TryParseExact(String(item, "zuletzt"), "yyyy-MM-dd HH:mm:ss", null, System.Globalization.DateTimeStyles.None, out var last)) return true;
        var minutes = new[] { 1, 2, 5, 10, 30, 60 }[Math.Min(attempts - 1, 5)]; return DateTime.Now >= last.AddMinutes(minutes);
    }
    private static bool TooOld(JsonObject item) => DateTime.TryParseExact(String(item, "angelegt"), "yyyy-MM-dd HH:mm:ss", null,
        System.Globalization.DateTimeStyles.None, out var created) && DateTime.Now > created.AddDays(7);
    private static string Timestamp() => DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
    private static string NormalizeFingerprint(string value) { var clean = new string(value.Where(Uri.IsHexDigit).ToArray()).ToUpperInvariant(); return clean.Length == 16 ? string.Join("-", clean.Chunk(4).Select(chars => new string(chars))) : ""; }
    private static string NormalizeSource(string value)
    {
        var plain = value.Split('%', 2)[0];
        return IPAddress.TryParse(plain, out var address) ? (address.IsIPv4MappedToIPv6 ? address.MapToIPv4() : address).ToString() : value.Trim().ToLowerInvariant();
    }
    private static string Source(TcpClient socket) =>
        (socket.Client.RemoteEndPoint as IPEndPoint)?.Address.ToString() ?? "";

    internal bool TryBeginConnection(string source)
    {
        source = NormalizeSource(source);
        lock (gate)
        {
            var count = activeConnections.GetValueOrDefault(source);
            if (count >= 4) return false;
            activeConnections[source] = count + 1;
            return true;
        }
    }

    internal void EndConnection(string source)
    {
        source = NormalizeSource(source);
        lock (gate)
        {
            var count = activeConnections.GetValueOrDefault(source) - 1;
            if (count > 0) activeConnections[source] = count;
            else activeConnections.Remove(source);
        }
    }

    internal bool RequestAllowed(string source, bool pairing)
    {
        source = NormalizeSource(source);
        var now = Stopwatch.GetTimestamp();
        var window = 60L * Stopwatch.Frequency;
        lock (gate)
        {
            if (!requestTimes.TryGetValue(source, out var times)) requestTimes[source] = times = [];
            times.RemoveAll(value => now - value >= window);
            if (times.Count >= (pairing ? 8 : 120)) return false;
            times.Add(now);
            if (requestTimes.Count > 1000)
                foreach (var old in requestTimes.Where(item => item.Value.Count == 0 || now - item.Value[^1] >= window).Select(item => item.Key).ToArray())
                    requestTimes.Remove(old);
            return true;
        }
    }
    private static string String(JsonObject value, string name, string fallback = "") => value[name]?.GetValue<string>() ?? fallback;
    private static int Number(JsonObject value, string name, int fallback = 0) => value[name]?.GetValue<int>() ?? fallback;
    private static long Long(JsonObject value, string name, long fallback = 0) =>
        value[name] is JsonValue number && number.TryGetValue<long>(out var result) ? result : fallback;
    private static bool Boolean(JsonObject value, string name) => value[name]?.GetValue<bool>() ?? false;
    private static JsonObject Error(string message) => new() { ["fehler"] = message };

    internal (int Status, JsonObject Body) HandleProtocolRequest(string path, JsonObject payload, string source)
    {
        var result = HandleRequest(path, payload, source);
        return (result.Status, result.Body);
    }
    private static async Task WriteResponseAsync(NetworkStream stream, int status, JsonObject body, CancellationToken cancellation)
    {
        var content = Encoding.UTF8.GetBytes(body.ToJsonString());
        var reason = status switch { 200 => "OK", 400 => "Bad Request", 403 => "Forbidden", 404 => "Not Found", 411 => "Length Required", 413 => "Payload Too Large", 429 => "Too Many Requests", 503 => "Service Unavailable", _ => "Error" };
        var header = Encoding.ASCII.GetBytes($"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {content.Length}\r\nConnection: close\r\n\r\n");
        await stream.WriteAsync(header, cancellation).ConfigureAwait(false);
        await stream.WriteAsync(content, cancellation).ConfigureAwait(false);
    }

    internal async Task ShutdownAsync()
    {
        if (disposed) return;
        await StopAsync().ConfigureAwait(false);
        disposed = true;
        mailbox.Dispose(); client.Dispose();
    }

    public void Dispose()
    {
        if (disposed) return; disposed = true;
        serviceCancellation?.Cancel();
        foreach (var listener in listeners) listener.Stop();
        udp?.Dispose();
        lock (gate)
        {
            foreach (var session in incomingFsSessions.Values) session.Session.Dispose();
            incomingFsSessions.Clear();
        }
        mailbox.Dispose(); client.Dispose();
    }

    private sealed record HttpResult(int Status, JsonObject Body, bool Notify = false);
    private sealed record QueueReport(int Delivered, int Open);
    private sealed class InboxFullException(string message) : Exception(message);
    private sealed record IncomingFsSession(MagnolienbaumFsSession Session, string PartnerId, string Source, long Expires);
}
