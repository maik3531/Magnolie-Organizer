using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    private readonly object personalSyncGate = new();
    private readonly Dictionary<string, JsonObject> personalSyncRequests = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (string PeerId, TaskCompletionSource<bool> Completion)> personalSyncWebCommits = new(StringComparer.Ordinal);

    private GraphConfiguration GraphConfig => new(Path.Combine(paths.Root, "graph-config.json"), Path.Combine(AppContext.BaseDirectory, "build-config.json"));
    private GraphTokenStore GraphTokens => new(Path.Combine(paths.Root, "graph-token.dat"), new DpapiCurrentUserProtector());
    private NextcloudMailboxSettingsStore NextcloudSettings => new(paths.BaumMailboxSettings, paths.BaumMailboxPassword);

    private async Task SignInInternetAccountAsync(JsonElement message)
    {
        try
        {
            using var timeout = NetworkDeadline(TimeSpan.FromSeconds(60));
            await ManagedInternetAccounts.BeginSignInAsync(Text(message, "anbieter"), Text(message, "email").Trim(), timeout.Token);
            await form.SendAsync("App.internetKontoAnmeldung", new { ok = true });
        }
        catch (Exception error)
        {
            await ReportErrorAsync("internet_konto_anmelden", error.ToString());
            await form.SendAsync("App.internetKontoAnmeldung", new { ok = false, fehler = T("Account sign-in could not be started. Please try again.") });
        }
    }

    private async Task InternetAccountStatusAsync()
    {
        if (!ManagedInternetAccounts.Enabled)
        {
            await form.SendAsync("App.internetKontenStatus", new { bereit = false });
            return;
        }
        try
        {
            using var timeout = NetworkDeadline(TimeSpan.FromSeconds(60));
            await ManagedInternetAccounts.EnsureStartedAsync(timeout.Token);
            var status = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "status" }, timeout.Token, managed: true);
            status["bereit"] = true;
            await form.SendAsync("App.internetKontenStatus", status);
        }
        catch (Exception error)
        {
            await ReportErrorAsync("internet_konten_status", error.ToString());
            await form.SendAsync("App.internetKontenStatus", new { bereit = false, fehler = T("Account sign-in could not be started. Please try again.") });
        }
    }

    private async Task<IReadOnlyList<NextcloudDavSource>> SelectedThunderbirdSourcesAsync(string addressBook,
        IReadOnlyList<string> calendars, CancellationToken token)
    {
        var selected = calendars.Append(addressBook).Where(ThunderbirdBridge.IsSource).ToArray();
        var result = new List<NextcloudDavSource>();
        if (selected.Any(ThunderbirdBridge.IsManagedSource))
        {
            await ManagedInternetAccounts.EnsureStartedAsync(token);
            result.AddRange(await ThunderbirdBridge.SourcesAsync(token, managed: true));
        }
        if (selected.Any(id => !ThunderbirdBridge.IsManagedSource(id)))
            result.AddRange(await ThunderbirdBridge.SourcesAsync(token));
        return result;
    }

    private async Task ContactSourcesAsync()
    {
        var clientId = GraphConfig.ClientId; var signedIn = false;
        try { signedIn = GraphTokens.Exists; } catch (Exception) { }
        NextcloudDavSources dav = new([], []); var nextcloudConfigured = false; var nextcloudError = ""; var accountType = "nextcloud";
        try
        {
            var settings = NextcloudSettings; var loaded = settings.Load(); accountType = loaded?.AccountType ?? "nextcloud";
            nextcloudConfigured = loaded?.DavActive == true && settings.HasApplicationPassword;
            if (nextcloudConfigured)
            {
                using var davClient = new NextcloudDavClient(settings); using var timeout = NetworkDeadline(TimeSpan.FromSeconds(60));
                dav = await davClient.ListSourcesAsync(timeout.Token);
                nextcloudError = dav.Error;
            }
        }
        catch (Exception error) { nextcloudError = NextcloudStatusText.For(error); }
        IReadOnlyList<NextcloudDavSource> thunderbirdSources = [];
        var thunderbirdConnected = false;
        if (File.Exists(ThunderbirdBridge.ManifestPath))
        {
            try
            {
                using var timeout = NetworkDeadline(TimeSpan.FromSeconds(10));
                thunderbirdSources = await ThunderbirdBridge.SourcesAsync(timeout.Token);
                thunderbirdConnected = true;
            }
            catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException)
            { /* A closed Thunderbird is unavailable, never an empty sync result. */ }
        }
        if (ManagedInternetAccounts.Enabled)
        {
            try
            {
                using var timeout = NetworkDeadline(TimeSpan.FromSeconds(60));
                await ManagedInternetAccounts.EnsureStartedAsync(timeout.Token);
                thunderbirdSources = thunderbirdSources.Concat(await ThunderbirdBridge.SourcesAsync(timeout.Token, managed: true)).ToArray();
            }
            catch (Exception error) { await ReportErrorAsync("internet_konten_status", error.ToString()); }
        }
        var addressBooks = new List<object> { new { uid = "windows-contacts", name = T("Windows Contacts folder"), art = "lokal", eingerichtet = true } };
        if (clientId.Length > 0 && signedIn) addressBooks.Add(new { uid = "microsoft-graph", name = "Outlook.com / Microsoft 365", art = "graph", eingerichtet = true });
        addressBooks.AddRange(dav.AddressBooks.Select(source => (object)new { uid = source.Uid, name = source.Name, art = accountType == "generic-dav" ? "generic-carddav" : "nextcloud-carddav", eingerichtet = true }));
        addressBooks.AddRange(thunderbirdSources.Where(source => source.Kind == "addressbook")
            .Select(source => (object)new { uid = source.Uid, name = source.Name, art = "thunderbird", eingerichtet = true }));
        await form.SendAsync("App.edsStatus", new
        {
            verfuegbar = true, buchOk = nextcloudError.Length == 0, windows = true,
            kalender = dav.Calendars.Concat(thunderbirdSources.Where(source => source.Kind == "calendar"))
                .Select(source => new { uid = source.Uid, name = source.Name, art = ThunderbirdBridge.IsSource(source.Uid) ? "thunderbird" : accountType == "generic-dav" ? "generic-caldav" : "nextcloud-caldav", supportsVtodo = source.SupportsVTodo, eingerichtet = true }).ToArray(),
            adressbuecher = addressBooks.ToArray(),
            graph = new { eingerichtet = clientId.Length > 0, angemeldet = signedIn },
            thunderbird = new { verbunden = thunderbirdConnected },
            nextcloud = new { eingerichtet = nextcloudConfigured, erreichbar = nextcloudConfigured && nextcloudError.Length == 0, kontoArt = accountType, fehler = nextcloudError }
        });
    }

    private async Task SaveGraphConfigurationAsync(JsonElement message)
    {
        try
        {
            var previous = GraphConfig.ClientId; GraphConfig.Save(Text(message, "clientId"));
            if (!previous.Equals(GraphConfig.ClientId, StringComparison.OrdinalIgnoreCase))
                lock (serviceGate) { graphRevision++; graphSignIn?.Cancel(); GraphTokens.Delete(); }
            await form.SendAsync("App.graphKonfiguration", new { ok = true, fehler = "" }); _ = QueueBackground(ContactSourcesAsync);
        }
        catch (Exception error) { await form.SendAsync("App.graphKonfiguration", new { ok = false, fehler = error.Message }); }
    }

    private async Task SignInGraphAsync()
    {
        using var timeout = NetworkDeadline(TimeSpan.FromMinutes(16));
        lock (serviceGate) graphSignIn = timeout;
        try
        {
            var clientId = GraphConfig.ClientId;
            if (clientId.Length == 0) throw new InvalidOperationException(T("Save your Microsoft OAuth client ID first."));
            var oauth = new MicrosoftOAuthClient(http);
            var device = await oauth.RequestDeviceCodeAsync(clientId, timeout.Token);
            var opened = ShellLauncher.OpenWebUri(device.VerificationUri);
            await form.SendAsync("App.graphAnmeldung", new { ok = true, fertig = false, code = device.UserCode, url = device.VerificationUri, nachricht = device.Message, browser = opened });
            var token = await oauth.PollTokenAsync(clientId, device, timeout.Token);
            lock (serviceGate) { timeout.Token.ThrowIfCancellationRequested(); GraphTokens.Save(token.RefreshToken); }
            await form.SendAsync("App.graphAnmeldung", new { ok = true, fertig = true, code = "", url = "", nachricht = "Microsoft-Anmeldung abgeschlossen." });
            await ContactSourcesAsync();
        }
        catch (Exception error) { await form.SendAsync("App.graphAnmeldung", new { ok = false, fertig = true, fehler = error.Message }); }
        finally { lock (serviceGate) if (ReferenceEquals(graphSignIn, timeout)) graphSignIn = null; }
    }

    private async Task SignOutGraphAsync()
    {
        try
        {
            lock (serviceGate) { graphRevision++; graphSignIn?.Cancel(); if (graphSync) activeSync?.Cancel(); GraphTokens.Delete(); }
            await form.SendAsync("App.graphAbmeldung", new { ok = true, fehler = "" }); _ = QueueBackground(ContactSourcesAsync);
        }
        catch (Exception error) { await form.SendAsync("App.graphAbmeldung", new { ok = false, fehler = error.Message }); }
    }

    private async Task SynchronizeContactsAsync(JsonElement message)
    {
        using var operation = NetworkDeadline(TimeSpan.FromMinutes(10));
        var locked = false;
        NextcloudDavClient? davClient = null;
        var thunderbirdClients = new List<NextcloudDavClient>();
        try
        {
            await MutationGate.Global.WaitAsync(operation.Token); locked = true;
            operation.Token.ThrowIfCancellationRequested();
            var requestedSource = message.TryGetProperty("wahl", out var snapshotChoice) ? PropertyText(snapshotChoice, "adressbuchUid") : "";
            var snapshotPrepared = contactCleanupSnapshot.Consume(currentPlainText, requestedSource);
            MutationGate.Global.Release(); locked = false;
            var source = message.TryGetProperty("wahl", out var choice) ? PropertyText(choice, "adressbuchUid") : "";
            lock (serviceGate) { activeSync = operation; graphSync = source == "microsoft-graph"; }
            var calendarIds = choice.ValueKind == JsonValueKind.Object ? SelectedCalendarIds(choice) : [];
            if (!NextcloudDavSelection.IsSupported(source, calendarIds))
                throw new InvalidOperationException(T("Address book"));
            if (source.Length == 0 && calendarIds.Count == 0) throw new InvalidOperationException(T("First choose a calendar or address book in Settings."));
            if (!message.TryGetProperty("daten", out var data) || data.ValueKind != JsonValueKind.Object) throw new ArgumentException(T("The synchronization data is missing."));
            var originalEpoch = data.TryGetProperty("syncEpoch", out var originalEpochNode) && originalEpochNode.ValueKind == JsonValueKind.String
                ? originalEpochNode.GetString() ?? "" : "";
            var transactionId = Text(message, "transactionId");
            ValidateSynchronizationTransaction(transactionId);
            async Task EnsureSnapshot()
            {
                operation.Token.ThrowIfCancellationRequested();
                if (snapshotPrepared) return;
                await MutationGate.Global.WaitAsync(operation.Token);
                try
                {
                    if ((JsonNode.Parse(currentPlainText)?["syncEpoch"]?.GetValue<string>() ?? "") != originalEpoch)
                        throw new InvalidOperationException(T("Synchronization failed."));
                    if (!snapshotPrepared) { CreateSnapshot(SnapshotReason.PreContact); snapshotPrepared = true; }
                }
                finally { MutationGate.Global.Release(); }
            }
            var originalContent = SyncSnapshotHandoff.Content(JsonNode.Parse(data.GetRawText())!.AsObject());
            var syncJournal = SynchronizationJournal(transactionId);
            var phases = new List<string>();
            if (source.Length > 0) phases.Add("contacts:" + source);
            phases.AddRange(calendarIds.Select(id => "calendar:" + id));
            phases.Add("complete");
            var resumed = syncJournal.Load();
            if (resumed is { } prior && (prior.Payload["syncEpoch"]?.GetValue<string>() ?? "") != originalEpoch)
                throw new InvalidDataException(T("The data is invalid."));
            if (resumed is { } pending && (pending.Id != transactionId || !phases.Contains(pending.Phase)))
                throw new InvalidDataException(T("The data is invalid."));
            var resumedPhase = resumed?.Phase ?? "";
            if (resumed is { Phase: "complete" } completedRun)
            {
                if (RecoveryJournal.HasRecoverableChanges(originalContent, SyncSnapshotHandoff.Content(completedRun.Payload))) await EnsureSnapshot();
                syncSnapshotHandoff.Completed(transactionId, completedRun.Payload, snapshotPrepared);
                await form.SendAsync("App.syncFertig", completedRun.Payload);
                return;
            }
            var thunderbirdSources = await SelectedThunderbirdSourcesAsync(source, calendarIds, operation.Token);
            if (resumed is { } saved)
            {
                using var resumeDocument = JsonDocument.Parse(saved.Payload.ToJsonString());
                data = resumeDocument.RootElement.Clone();
            }
            var contacts = ParseArray(data, "kontakte");
            var reconciliationBasis = data.TryGetProperty("syncAbgleichBasis", out var reconciliationNode)
                ? JsonNode.Parse(reconciliationNode.GetRawText())!.AsObject() : new JsonObject();
            if (reconciliationBasis.Count == 0)
                foreach (var field in new[] { "termine", "aufgaben", "kontakte", "jahrestage", "geloescht" })
                    if (data.TryGetProperty(field, out var value)) reconciliationBasis[field] = JsonNode.Parse(value.GetRawText());
            var deletedRoot = data.TryGetProperty("geloescht", out var deleted) && deleted.ValueKind == JsonValueKind.Object ? deleted : default;
            var tombstones = ParseArray(deletedRoot, "kontakte");
            var lastSync = data.TryGetProperty("letzterSync", out var last) && last.TryGetInt64(out var timestamp) ? timestamp : 0;
            var sourceCursors = data.TryGetProperty("letzteSyncs", out var syncsNode) && syncsNode.ValueKind == JsonValueKind.Object
                ? JsonNode.Parse(syncsNode.GetRawText())!.AsObject() : new JsonObject();
            var calendarCursors = sourceCursors["kalender"] as JsonObject ?? new JsonObject(); sourceCursors["kalender"] = calendarCursors;
            var taskCursors = sourceCursors["aufgaben"] as JsonObject ?? new JsonObject(); sourceCursors["aufgaben"] = taskCursors;
            var addressCursors = sourceCursors["adressbuecher"] as JsonObject ?? new JsonObject(); sourceCursors["adressbuecher"] = addressCursors;
            foreach (var item in sourceCursors.Where(item => item.Key is not ("kalender" or "aufgaben" or "adressbuecher")).ToArray())
            {
                if (NextcloudDavSelection.IsCalendar(item.Key)) calendarCursors[item.Key] = item.Value?.DeepClone();
                else addressCursors[item.Key] = item.Value?.DeepClone();
                sourceCursors.Remove(item.Key);
            }
            var syncMetadata = data.TryGetProperty("syncMetadaten", out var metadataNode) && metadataNode.ValueKind == JsonValueKind.Object
                ? JsonNode.Parse(metadataNode.GetRawText())!.AsObject() : new JsonObject();
            var nextcloudMetadata = syncMetadata["nextcloud"] as JsonObject ?? new JsonObject(); syncMetadata["nextcloud"] = nextcloudMetadata;
            var nextcloudCalendars = nextcloudMetadata["kalender"] as JsonObject ?? new JsonObject(); nextcloudMetadata["kalender"] = nextcloudCalendars;
            var nextcloudAddressBooks = nextcloudMetadata["adressbuecher"] as JsonObject ?? new JsonObject(); nextcloudMetadata["adressbuecher"] = nextcloudAddressBooks;
            nextcloudMetadata["quarantinedDeletes"] ??= new JsonObject(); nextcloudMetadata["transaktionen"] ??= new JsonObject();
            long Cursor(JsonObject cursors, string uid) => cursors[uid] is JsonValue cursor && cursor.TryGetValue<long>(out var value) ? value : lastSync;
            var additiveOnly = syncMetadata["ersteSyncLoeschungsfrei"]?.GetValue<bool>() == true ||
                data.TryGetProperty("syncNachRestore", out var restoreMode) &&
                restoreMode.ValueKind == JsonValueKind.Object && restoreMode.TryGetProperty("additiv", out var additive) && additive.ValueKind == JsonValueKind.True;
            var result = new ContactSyncResult(contacts, tombstones, new ContactSyncCounts(0, 0, 0, 0, 0));
            var taskCalendars = new HashSet<string>(StringComparer.Ordinal);
            var terms = data.TryGetProperty("termine", out var termsNode) ? JsonNode.Parse(termsNode.GetRawText()) : new JsonArray();
            var tasks = data.TryGetProperty("aufgaben", out var tasksNode) ? JsonNode.Parse(tasksNode.GetRawText()) : new JsonArray();
            var anniversaries = data.TryGetProperty("jahrestage", out var anniversariesNode) ? JsonNode.Parse(anniversariesNode.GetRawText()) : new JsonArray();
            var termTombstones = ParseArray(deletedRoot, "termine"); var taskTombstones = ParseArray(deletedRoot, "aufgaben");
            void SaveProgress(string phase) => syncJournal.Save(transactionId, phase, new JsonObject
            {
                ["termine"] = terms?.DeepClone(), ["aufgaben"] = tasks?.DeepClone(), ["kontakte"] = result.Contacts.DeepClone(),
                ["jahrestage"] = anniversaries?.DeepClone(),
                ["geloescht"] = new JsonObject { ["termine"] = termTombstones.DeepClone(), ["aufgaben"] = taskTombstones.DeepClone(), ["kontakte"] = result.Tombstones.DeepClone() },
                ["letzterSync"] = lastSync, ["letzteSyncs"] = sourceCursors.DeepClone(),
                ["syncMetadaten"] = syncMetadata.DeepClone(), ["syncEpoch"] = originalEpoch,
                ["syncAbgleichBasis"] = reconciliationBasis.DeepClone(),
                ["syncNachRestore"] = data.TryGetProperty("syncNachRestore", out var restore) ? JsonNode.Parse(restore.GetRawText()) : null
            });
            var resumedIndex = resumedPhase.Length == 0 ? -1 : phases.IndexOf(resumedPhase);
            if (source.Length > 0 && resumedIndex < phases.IndexOf("contacts:" + source))
            {
                IContactRemote remote;
                if (source == "windows-contacts")
                {
                    remote = new WindowsContactStore(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Contacts"));
                }
                else if (source == "microsoft-graph")
                {
                    var clientId = GraphConfig.ClientId; if (clientId.Length == 0) throw new InvalidOperationException(T("Microsoft Graph has not been configured yet."));
                    var refresh = GraphTokens.Load(); if (string.IsNullOrWhiteSpace(refresh)) throw new InvalidOperationException(T("Sign in to Microsoft first."));
                    var token = await new MicrosoftOAuthClient(http).RefreshAsync(clientId, refresh, operation.Token);
                    if (token.RefreshToken.Length > 0) GraphTokens.Save(token.RefreshToken);
                    remote = new GraphApiClient(http, token.AccessToken);
                }
                else if (ThunderbirdBridge.IsSource(source))
                {
                    var addressBook = thunderbirdSources.SingleOrDefault(item => item.Uid == source) ??
                        throw new InvalidOperationException(T("Address book"));
                    var bridgeClient = ThunderbirdBridge.CreateClient(addressBook, syncJournal, transactionId);
                    bridgeClient.BeforeMutation = EnsureSnapshot;
                    thunderbirdClients.Add(bridgeClient);
                    remote = new NextcloudCardDavRemote(bridgeClient, addressBook);
                }
                else
                {
                    davClient = new NextcloudDavClient(NextcloudSettings, journal: syncJournal, transactionId: transactionId);
                    davClient.BeforeMutation = EnsureSnapshot;
                    var sources = await davClient.ListSourcesAsync(operation.Token, calendars: false);
                    var addressBook = sources.AddressBooks.SingleOrDefault(item => item.Uid == source) ?? throw new InvalidOperationException(T("Address book"));
                    remote = new NextcloudCardDavRemote(davClient, addressBook);
                }
                var contactCursor = Cursor(addressCursors, source);
                var initialized = !NextcloudDavSelection.IsAddressBook(source) ||
                    nextcloudAddressBooks[source]?["initialisiert"]?.GetValue<bool>() == true;
                var firstContactRun = !initialized || !NextcloudDavSelection.IsAddressBook(source) &&
                    (contactCursor <= 0 || !contacts.Concat(tombstones).OfType<JsonObject>()
                        .Any(item => ContactFields.Source(item, source) is not null));
                result = await new ContactSyncEngine().SyncAsync(source, contacts, tombstones, contactCursor, remote,
                    operation.Token, additiveOnly || firstContactRun, EnsureSnapshot);
                if (result.Counts.Errors > 0)
                    throw new InvalidOperationException(T("The Nextcloud operation failed."));
                SaveProgress("contacts:" + source);
            }
            if (calendarIds.Count > 0)
            {
                IReadOnlyList<NextcloudDavSource> davCalendars = [];
                if (calendarIds.Any(id => !ThunderbirdBridge.IsSource(id)))
                {
                    davClient ??= new NextcloudDavClient(NextcloudSettings, journal: syncJournal, transactionId: transactionId);
                    davClient.BeforeMutation = EnsureSnapshot;
                    davCalendars = (await davClient.ListSourcesAsync(operation.Token, addressBooks: false)).Calendars;
                }
                var selected = calendarIds.Select(id => davCalendars.Concat(thunderbirdSources).SingleOrDefault(item => item.Uid == id) ??
                    throw new InvalidOperationException(T("No calendars found."))).ToArray();
                foreach (var calendar in selected.Where(item => item.SupportsVTodo)) taskCalendars.Add(calendar.Uid);
                foreach (var calendar in selected)
                {
                    var calendarClient = davClient;
                    if (ThunderbirdBridge.IsSource(calendar.Uid))
                    {
                        calendarClient = ThunderbirdBridge.CreateClient(calendar, syncJournal, transactionId);
                        calendarClient.BeforeMutation = EnsureSnapshot;
                        thunderbirdClients.Add(calendarClient);
                    }
                    var phase = "calendar:" + calendar.Uid;
                    if (resumedIndex >= phases.IndexOf(phase)) continue;
                    var calendarCursor = Cursor(calendarCursors, calendar.Uid);
                    var firstCalendarRun = nextcloudCalendars[calendar.Uid]?["initialisiert"]?.GetValue<bool>() != true || calendarCursor <= 0;
                    var taskCursor = Cursor(taskCursors, calendar.Uid);
                    var firstTaskRun = nextcloudCalendars[calendar.Uid]?["aufgabenInitialisiert"]?.GetValue<bool>() != true || taskCursor <= 0;
                    var isDefaultCalendar = calendar.Uid == selected[0].Uid;
                    var (calendarTerms, remainingTerms) = NextcloudDavSelection.SplitCalendarItems(
                        terms as JsonArray ?? [], calendar.Uid, isDefaultCalendar);
                    var (calendarAnniversaries, remainingAnniversaries) = NextcloudDavSelection.SplitCalendarItems(
                        anniversaries as JsonArray ?? [], calendar.Uid, isDefaultCalendar);
                    var (calendarTombstones, remainingTombstones) = NextcloudDavSelection.SplitCalendarTombstones(
                        termTombstones, calendar.Uid, isDefaultCalendar);
                    var (calendarTasks, remainingTasks) = NextcloudDavSelection.SplitCalendarItems(
                        tasks as JsonArray ?? [], calendar.Uid, isDefaultCalendar);
                    var (calendarTaskTombstones, remainingTaskTombstones) = NextcloudDavSelection.SplitCalendarTombstones(
                        taskTombstones, calendar.Uid, isDefaultCalendar);
                    using var calendarTimeout = CancellationTokenSource.CreateLinkedTokenSource(operation.Token); calendarTimeout.CancelAfter(TimeSpan.FromSeconds(12));
                    var calendarResult = await new NextcloudCalendarSync(calendarClient!).SyncAsync(calendar,
                        calendarTerms, calendarAnniversaries, calendarTombstones, calendarCursor,
                        additiveOnly || firstCalendarRun, calendarTimeout.Token);
                    foreach (var item in calendarResult.Termine) remainingTerms.Add(item?.DeepClone());
                    foreach (var item in calendarResult.Jahrestage) remainingAnniversaries.Add(item?.DeepClone());
                    foreach (var item in calendarResult.Tombstones) remainingTombstones.Add(item?.DeepClone());
                    terms = remainingTerms; anniversaries = remainingAnniversaries; termTombstones = remainingTombstones;
                    NextcloudTaskResult taskResult;
                    if (calendar.SupportsVTodo)
                    {
                        using var taskTimeout = CancellationTokenSource.CreateLinkedTokenSource(operation.Token); taskTimeout.CancelAfter(TimeSpan.FromSeconds(12));
                        taskResult = await new NextcloudTaskSync(calendarClient!).SyncAsync(calendar,
                            calendarTasks, calendarTaskTombstones, taskCursor,
                            additiveOnly || firstTaskRun, taskTimeout.Token);
                    }
                    else
                    {
                        foreach (var item in calendarTasks) remainingTasks.Add(item?.DeepClone());
                        foreach (var item in calendarTaskTombstones) remainingTaskTombstones.Add(item?.DeepClone());
                        taskResult = new NextcloudTaskResult([], [], 0, 0, 0, 0, 0);
                    }
                    foreach (var item in taskResult.Tasks) remainingTasks.Add(item?.DeepClone());
                    foreach (var item in taskResult.Tombstones) remainingTaskTombstones.Add(item?.DeepClone());
                    tasks = remainingTasks; taskTombstones = remainingTaskTombstones;
                    SaveProgress(phase);
                }
            }
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (source.Length > 0) addressCursors[source] = now;
            if (NextcloudDavSelection.IsAddressBook(source))
                nextcloudAddressBooks[source] = new JsonObject { ["initialisiert"] = true,
                    ["letzterSync"] = now, ["etags"] = SourceEtags(result.Contacts, source) };
            foreach (var calendarId in calendarIds)
            {
                calendarCursors[calendarId] = now;
                var supportsTasks = taskCalendars.Contains(calendarId);
                if (supportsTasks) taskCursors[calendarId] = now;
                var etags = SourceEtags(terms as JsonArray ?? [], calendarId);
                foreach (var item in SourceEtags(anniversaries as JsonArray ?? [], calendarId)) etags[item.Key] = item.Value?.DeepClone();
                foreach (var item in SourceEtags(tasks as JsonArray ?? [], calendarId)) etags[item.Key] = item.Value?.DeepClone();
                var priorMetadata = nextcloudCalendars[calendarId] as JsonObject;
                var calendarMetadata = new JsonObject { ["initialisiert"] = true,
                    ["letzterSync"] = now, ["etags"] = etags };
                if (supportsTasks)
                {
                    calendarMetadata["aufgabenInitialisiert"] = true;
                    calendarMetadata["letzterAufgabenSync"] = now;
                }
                else
                {
                    calendarMetadata["aufgabenInitialisiert"] = priorMetadata?["aufgabenInitialisiert"]?.DeepClone();
                    calendarMetadata["letzterAufgabenSync"] = priorMetadata?["letzterAufgabenSync"]?.DeepClone();
                }
                nextcloudCalendars[calendarId] = calendarMetadata;
            }
            operation.Token.ThrowIfCancellationRequested();
            nextcloudMetadata["pendingCommitId"] = transactionId;
            syncMetadata["ersteSyncLoeschungsfrei"] = false;
            var completed = new { transactionId, termine = terms, aufgaben = tasks, kontakte = result.Contacts, jahrestage = anniversaries,
                syncAbgleichBasis = reconciliationBasis,
                geloescht = new { termine = termTombstones, aufgaben = taskTombstones, kontakte = result.Tombstones }, letzterSync = now,
                letzteSyncs = sourceCursors,
                syncMetadaten = syncMetadata,
                syncEpoch = data.TryGetProperty("syncEpoch", out var epoch) ? epoch.GetString() : null,
                syncNachRestore = (object?)null, bericht = source == "windows-contacts" && calendarIds.Count == 0
                    ? T("Windows Contacts folder") + ": " + T("Synchronization completed.")
                    : T("Synchronization completed.") };
            var completedNode = JsonSerializer.SerializeToNode(completed)!.AsObject();
            if (RecoveryJournal.HasRecoverableChanges(originalContent, SyncSnapshotHandoff.Content(completedNode))) await EnsureSnapshot();
            syncJournal.Save(transactionId, "complete", completedNode);
            syncSnapshotHandoff.Completed(transactionId, completedNode, snapshotPrepared);
            await form.SendAsync("App.syncFertig", completed);
        }
        catch (Exception error)
        {
            await ReportErrorAsync("sync", error.ToString());
            await form.SendAsync("App.syncFehler", NextcloudStatusText.For(error));
        }
        finally
        {
            lock (serviceGate) if (ReferenceEquals(activeSync, operation)) { activeSync = null; graphSync = false; }
            try { davClient?.Dispose(); foreach (var client in thunderbirdClients) client.Dispose(); }
            finally { if (locked) MutationGate.Global.Release(); }
        }
    }

    private void CommitSynchronization(string transactionId)
    {
        ValidateSynchronizationTransaction(transactionId);
        if (!MutationGate.Global.Wait(0)) return;
        try
        {
            var journal = SynchronizationJournal(transactionId);
            if (journal.Load() is not { Phase: "complete" } completed || completed.Id != transactionId) return;
            var text = store.Read(paths.Data);
            if (text is null) return;
            if (EncryptionService.IsEncrypted(text)) text = encryption.DecryptDataWithSession(text);
            if (JsonNode.Parse(text) is not JsonObject saved || !SyncBaseline.ContainsSavedResult(completed.Payload, saved)) return;
            journal.Commit(transactionId);
        }
        finally { MutationGate.Global.Release(); }
    }

    private NextcloudSyncJournal SynchronizationJournal(string transactionId)
    {
        ValidateSynchronizationTransaction(transactionId);
        var path = paths.NextcloudSyncJournal + "." + transactionId;
        if (File.Exists(path) || File.Exists(path + ".creates")) return new NextcloudSyncJournal(path);
        var legacy = new NextcloudSyncJournal(paths.NextcloudSyncJournal).Load() ??
            new NextcloudSyncJournal(paths.NextcloudSyncJournal + ".creates").Load();
        if (legacy?.Id == transactionId) return new NextcloudSyncJournal(paths.NextcloudSyncJournal);
        var directory = Path.GetDirectoryName(path)!;
        var prefix = Path.GetFileName(paths.NextcloudSyncJournal) + ".";
        var pendingIds = Directory.Exists(directory) ? Directory.EnumerateFiles(directory, prefix + "*")
            .Select(file => Path.GetFileName(file)[prefix.Length..].Split('.')[0])
            .Where(id => id.Length == 64 && id.All(Uri.IsHexDigit)).Distinct(StringComparer.OrdinalIgnoreCase).Count() : 0;
        if (pendingIds + (legacy is null ? 0 : 1) >= 16) throw new InvalidDataException(T("Too many unfinished synchronization runs."));
        return new NextcloudSyncJournal(path);
    }

    private static void ValidateSynchronizationTransaction(string transactionId)
    {
        if (transactionId.Length != 64 || transactionId.Any(value => !Uri.IsHexDigit(value)))
            throw new InvalidDataException("Die Synchronisationstransaktion ist ungültig.");
    }

    private static JsonArray ParseArray(JsonElement parent, string name) => parent.ValueKind == JsonValueKind.Object && parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array
        ? JsonNode.Parse(value.GetRawText())!.AsArray() : new JsonArray();

    private static JsonObject SourceEtags(JsonArray values, string source)
    {
        var result = new JsonObject();
        foreach (var value in values.OfType<JsonObject>())
        {
            var mapping = ContactFields.Source(value, source); var id = mapping?["id"]?.GetValue<string>() ?? "";
            if (id.Length > 0) result[id] = mapping?["etag"]?.DeepClone();
        }
        return result;
    }

    private static IReadOnlyList<string> SelectedCalendarIds(JsonElement choice)
    {
        JsonElement values;
        if (!choice.TryGetProperty("kalenderUids", out values) && !choice.TryGetProperty("kalender", out values)) return [];
        if (values.ValueKind != JsonValueKind.Array) throw new InvalidDataException("Die Kalenderauswahl ist ungültig.");
        var result = values.EnumerateArray().Select(value => value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" :
            value.ValueKind == JsonValueKind.Object ? PropertyText(value, "uid") : "").ToArray();
        if (result.Any(value => !NextcloudDavSelection.IsCalendar(value)) || result.Distinct(StringComparer.Ordinal).Count() != result.Length)
            throw new InvalidDataException("Die Kalenderauswahl ist ungültig.");
        return result;
    }

    private void HandleKdeStatusChanged(KdeConnectStatus status)
    {
        _ = status;
        _ = SafeBackgroundAsync(telefon.ReportStatusAsync);
    }

    private void HandleKdeSmsReceived(KdeConnectSmsReceived received) => _ = SafeBackgroundAsync(() =>
        form.SendAsync("App.telefonSmsEmpfangen", new
        {
            device_id = received.Message.DeviceId,
            thread_id = received.Message.ThreadId,
            sms_id = received.Message.SmsId,
            from = received.Message.From,
            addresses = received.Message.Addresses,
            group = received.Message.Group,
            text = received.Message.Text,
            timestamp_ms = received.Message.TimestampMs,
            incoming = received.Message.Incoming,
            history = received.History,
            notify = received.Notify
        }));

    private void HandleKdePairingChanged(KdeConnectPairingEvent pairing) => _ = SafeBackgroundAsync(async () =>
    {
        if (pairing.State == "requested")
        {
            form.ShowPairingRequest();
            pendingKdePairingId = pairing.DeviceId;
            await form.SendAsync("App.kdePairingCode", new { state = pairing.State, device_id = pairing.DeviceId,
                device_name = pairing.DeviceName, code = pairing.Code,
                expires_ms = pairing.ExpiresAt?.ToUnixTimeMilliseconds() ?? 0, error = "" });
        }
        else
        {
            if (pairing.State is "paired" or "rejected" or "failed") pendingKdePairingId = "";
            await form.SendAsync("App.kdePairingStatus", new { state = pairing.State == "rejected" ? "failed" : pairing.State,
                device_id = pairing.DeviceId, device_name = pairing.DeviceName,
                error = pairing.Reason, reason = pairing.Reason });
        }
    });

    private async Task SafeBackgroundAsync(Func<Task> action)
    {
        if (disposed) return;
        try { await action(); }
        catch (Exception) when (disposed) { }
        catch (ObjectDisposedException) { }
    }

    private async Task<object> KdeStatusForWebAsync()
    {
        KdeConnectStatus status;
        try { status = await kdeConnectSms.DirectStatusAsync(); }
        catch (Exception) { return new { available = false, device_count = 0, reason = "unavailable" }; }
        return new
        {
            available = status.Available,
            device_count = status.DeviceCount,
            reason = status.Reason,
            listening = status.Listening,
            listen_port = status.ListenerPort,
            paired = status.PairedCount == 1,
            paired_count = status.PairedCount,
            device_id = status.DeviceId,
            device_fingerprint = status.DeviceFingerprint,
            peer_name = status.PeerName,
            pairing_state = status.PairingState,
            unpaired_candidate_count = status.UnpairedCandidateCount,
            unpaired_candidate_id = status.UnpairedCandidateId,
            unpaired_candidate_name = status.UnpairedCandidateName,
            replacement_peer_id = status.ReplacementPeerId,
            unpaired_candidate_reachable = status.CandidateReachable,
            unpaired_candidate_age_seconds = status.CandidateAgeSeconds,
            connection_generation = status.ConnectionGeneration,
            connection_direction = status.ConnectionDirection,
            history_available = status.HistoryAvailable,
            bootstrap_state = status.BootstrapState,
            parse_valid = status.ParseValid,
            parse_skipped = status.ParseSkipped,
            last_receive_ms = status.LastReceiveMs,
            pairing_mismatch_count = status.PairingMismatchCount,
            next_reconnect_seconds = status.NextReconnectSeconds
        };
    }

    private async Task<JsonObject> BuildTelefonStatusAsync(JsonObject backend)
    {
        var bluetoothDevices = new JsonArray();
        if (TelefonBluetoothSupport.Available)
            foreach (var device in await TelefonBluetoothTransport.PairedDevicesAsync())
                bluetoothDevices.Add(new JsonObject { ["address"] = device.Address, ["name"] = device.Name });
        var phoneStatus = (backend["telefone"] as JsonArray)?.OfType<JsonObject>()
            .ToDictionary(item => item["kennung"]!.GetValue<string>(), StringComparer.Ordinal) ?? [];
        var settings = ReadTelefonSettings();
        var localGrants = telefon.LocalGrants();
        var peers = new JsonArray();
        foreach (var peer in telefon.StatusPeers)
        {
            var status = phoneStatus.GetValueOrDefault(peer.Id);
            var transport = status?["online"]?.GetValue<bool>() == true ? status["transport"]?.GetValue<string>() ?? "offline" : "offline";
            var bluetoothAddress = status?["bluetooth_address"]?.GetValue<string>() ?? "";
            var personal = settings["personal_sync"]?[peer.Id] as JsonObject;
            peers.Add(new JsonObject
            {
                ["device_id"] = peer.Id,
                ["display_name"] = peer.Name,
                ["state"] = peer.State == "pair_commit_pending" ? "pair_commit_pending" : transport is "wifi" or "bluetooth" ? "online_" + transport : "offline",
                ["transport"] = transport,
                ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey),
                ["last_contact_ms"] = peer.LastSeenMs,
                ["capabilities"] = new JsonObject { ["revision"] = peer.CapabilityRevision,
                    ["items"] = peer.Capabilities.DeepClone() },
                ["grants"] = new JsonObject { ["revision"] = peer.GrantRevision,
                    ["grants"] = peer.Grants.DeepClone() },
                ["local_grants"] = new JsonObject { ["grants"] = localGrants.DeepClone() },
                ["own_device"] = personal?["own_device"]?.GetValue<bool>() == true,
                ["custom_sync"] = telefon.CustomSettings(peer.Id),
                ["remote_own_device"] = personal?["remote_own_device"]?.GetValue<bool>() == true,
                ["auto_wifi"] = personal?["auto_wifi"]?.GetValue<bool>() == true,
                ["personal_sync_active_auto"] = false,
                ["status"] = telefon.CachedDeviceStatus(peer.Id),
                ["bluetooth_enabled"] = TelefonBluetoothClient.ValidAddress(bluetoothAddress),
                ["bluetooth_address"] = bluetoothAddress,
                ["connection_error"] = ""
            });
        }
        return new JsonObject
        {
            ["enabled"] = backend["an"]?.GetValue<bool>() == true,
            ["listening"] = backend["laeuft"]?.GetValue<bool>() == true,
            ["port"] = backend["port"]?.DeepClone(),
            ["service"] = backend["dienst"]?.DeepClone(),
            ["device_id"] = backend["kennung"]?.DeepClone(),
            ["display_name"] = backend["name"]?.DeepClone(),
            ["fingerprint"] = backend["fingerabdruck"]?.DeepClone(),
            ["pairing_open"] = backend["paarungOffen"]?.DeepClone(),
            ["pairing_until_ms"] = backend["paarungBis"]?.DeepClone(),
            ["binding_conflict"] = backend["binding_conflict"]?.DeepClone(),
            ["error"] = TelefonError(backend["fehler"]?.GetValue<string>() ?? ""),
            ["peers"] = peers,
            ["capabilities"] = backend["capabilities"]?.DeepClone(),
            ["call_audio"] = WindowsBluetoothRadio.CallRoutingCapability(),
            ["bluetooth"] = new JsonObject { ["available"] = TelefonBluetoothSupport.Available,
                ["reason"] = TelefonBluetoothSupport.Reason,
                ["blocker"] = TelefonBluetoothSupport.Blocker, ["devices"] = bluetoothDevices },
            ["kdeconnect"] = backend["kdeconnect"]?.DeepClone()
        };
    }

    /// <summary>
    /// Ergänzt die Rückmeldung des Koordinators um den Firewallhinweis. Ohne ihn
    /// bliebe die häufigste Windows-Ursache für eine scheiternde WLAN-Verbindung
    /// in der Oberfläche unsichtbar.
    /// </summary>
    private string TelefonError(string backendError)
    {
        var hint = firewallHint;
        if (hint.Length == 0 && telefon.Enabled && !WindowsFirewall.Configured()) hint = WindowsFirewall.FirewallHint;
        if (hint.Length == 0) return backendError;
        return backendError.Length == 0 ? hint : backendError + " · " + hint;
    }

    /// <summary>
    /// Merkt sich je Telefon, ob der Bluetooth-Rückfallweg gewünscht ist und
    /// welche in Windows gekoppelte Adresse dazugehört.
    /// </summary>
    private async Task SetTelefonBluetoothAsync(JsonElement message)
    {
        var id = Text(message, "kennung");
        var enabled = Boolean(message, "an");
        var address = Text(message, "adresse");
        if (id.Length == 0) throw new InvalidDataException(T("The phone was not specified."));
        if (enabled && !TelefonBluetoothSupport.Available)
        {
            await ReportErrorAsync("telefon_bluetooth_schalten", TelefonBluetoothSupport.Blocker);
            await telefon.ReportStatusAsync();
            return;
        }
        if (enabled && address.Length == 0) throw new InvalidDataException(T("No Bluetooth address was selected."));
        var settings = ReadTelefonSettings();
        var all = settings["bluetooth"] as JsonObject;
        if (all is null) { all = new JsonObject(); settings["bluetooth"] = all; }
        all[id] = new JsonObject { ["enabled"] = enabled, ["address"] = enabled ? address : "" };
        store.WriteRecoverableJson(paths.TelefonSettings, settings.ToJsonString(JsonOptions.Default));
        await telefon.ReportStatusAsync();
    }

    private JsonObject ReadTelefonSettings()
    {
        try { return JsonNode.Parse(store.ReadRecoverableJson(paths.TelefonSettings, 1024 * 1024) ?? "{}") as JsonObject
                ?? throw new InvalidDataException(T("The phone settings are damaged.")); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        { throw new InvalidDataException(T("The phone settings are damaged."), error); }
    }

    private async Task HandleTelefonPairingEventAsync(JsonObject message)
    {
        var id = message["kennung"]?.GetValue<string>() ?? "";
        var code = message["code"]?.GetValue<string>() ?? "";
        if (message["fertig"]?.GetValue<bool>() == true)
        {
            pendingTelefonPairingId = "";
            await form.SendAsync("App.telefonGekoppelt", new { device_id = id,
                display_name = message["name"]?.GetValue<string>() ?? "" });
        }
        else if (id.Length > 0 && code.Length > 0)
        {
            form.ShowPairingRequest();
            pendingTelefonPairingId = id;
            await form.SendAsync("App.telefonPairingCode", new { attempt_id = id, device_id = id,
                display_name = message["name"]?.GetValue<string>() ?? "",
                code, fingerprint = message["fingerabdruck"]?.GetValue<string>() ?? "" });
        }
        else await form.SendAsync("App.telefonPairingOffen", new { port = TelefonCoordinator.Port,
            seconds = message["sekunden"]?.GetValue<int>() ?? 120 });
    }

    private void ConfirmTelefonPairing(JsonElement message)
    {
        var id = Text(message, "attemptId");
        if (id.Length == 0) id = Text(message, "kennung");
        if (id.Length == 0) id = pendingTelefonPairingId;
        if (id.Length == 0) throw new InvalidOperationException(T("No phone pairing is awaiting confirmation."));
        telefon.ConfirmPairing(id, Boolean(message, "ja"));
    }

    private void CancelTelefonPairing()
    {
        if (pendingTelefonPairingId.Length > 0) telefon.ConfirmPairing(pendingTelefonPairingId, false);
        pendingTelefonPairingId = "";
    }

    private string SoleTelefonId() => telefon.Peers is [var peer] ? peer.Id :
        throw new InvalidOperationException(T("Exactly one Magnolie Notes phone must be paired."));

    private async Task DialTelefonAsync(JsonElement message)
    {
        var number = PhoneUri.Normalize(Text(message, "nummer"), Text(message, "land"));
        var peerId = SoleTelefonId();
        if (Text(message, "kennung") is { Length: > 0 } expected && expected != peerId)
            throw new InvalidOperationException(T("The phone is not paired."));
        await telefon.RequestDialAsync(peerId, number, Text(message, "clientRef"));
    }

    private async Task AnswerTelefonAsync(JsonElement message)
    {
        var peerId = Text(message, "kennung");
        await telefon.RequestAnswerAsync(peerId, Text(message, "callRef"), Text(message, "commandRef"));
    }

    private Task EndTelefonCallAsync(JsonElement message)
    {
        var revision = message.TryGetProperty("revision", out var node) && node.TryGetInt64(out var value) ? value : 0;
        return telefon.RequestEndCallAsync(Text(message, "kennung"), Text(message, "callRef"), revision,
            Text(message, "commandRef"));
    }

    private async Task SendPersonalSyncAsync(JsonElement message)
    {
        var body = Object(message, "inhalt");
        var kind = Text(message, "art");
        try { await telefon.SendPersonalSyncAsync(Text(message, "kennung"), kind, body); }
        catch (Exception error) when (kind.StartsWith("personal_sync.custom_", StringComparison.Ordinal))
        { throw new InvalidOperationException(T("Personal synchronization failed."), error); }
    }

    private async Task SendPersonalSyncRunAsync(JsonElement message)
    {
        var peerId = Text(message, "kennung");
        var request = Object(message, "request");
        var batchNodes = NodeArray(message, "batches");
        var batches = batchNodes.OfType<JsonObject>().Select(item => item.DeepClone().AsObject()).ToArray();
        if (batches.Length != batchNodes.Count) throw new InvalidDataException(T("A personal synchronization batch is not an object."));
        if (batches.Length == 0) throw new InvalidDataException(T("Personal synchronization batches are missing."));
        PersonalSyncContract.ValidateBody("personal_sync.request", request);
        foreach (var batch in batches) PersonalSyncContract.ValidateBody("personal_sync.batch", batch);
        var runId = request["run_id"]!.GetValue<string>();
        if (batches.Any(batch => batch["run_id"]?.GetValue<string>() != runId ||
            batch["format"]!.GetValue<int>() != request["format"]!.GetValue<int>())) throw new InvalidDataException(T("The personal synchronization run does not match."));
        var reply = batches[0]["reply"]!.GetValue<bool>();
        if (reply)
        {
            if (!JsonNode.DeepEquals(telefon.PersonalRunRequest(peerId, runId), request))
                throw new InvalidDataException(T("The personal synchronization run does not match."));
        }
        var recordsHash = batches[0]["records_hash"]?.GetValue<string>() ?? "";
        if (recordsHash.Length != 64 || batches.Any(batch => batch["reply"]?.GetValue<bool>() != reply ||
            batch["records_hash"]?.GetValue<string>() != recordsHash))
            throw new InvalidDataException(T("The personal synchronization attachment identity does not match."));
        var sources = ParseAttachmentSources(NodeArray(message, "sources"));
        var descriptors = batches.SelectMany(batch => (batch["records"] as JsonArray ?? []).OfType<JsonObject>())
            .SelectMany(record => (record["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
            .GroupBy(descriptor => descriptor["sha256"]!.GetValue<string>(), StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.First().DeepClone().AsObject(), StringComparer.Ordinal);
        if (!descriptors.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(sources.Keys)) throw new InvalidDataException(T("The personal synchronization attachment sources are incomplete."));
        if (!reply) await telefon.SendPersonalSyncAsync(peerId, "personal_sync.request", request);
        foreach (var source in sources.Values)
        {
            source.Descriptor = descriptors[source.Hash];
            var chunks = source.Data.Chunk(PersonalSyncContract.ChunkRaw).Select((data, index) => (index, data));
            telefon.StagePersonalAttachment(peerId, runId, reply, recordsHash, source.Descriptor, "outgoing",
                request["trigger"]?.GetValue<string>() == "auto_wifi" ? DateTimeOffset.UtcNow.AddHours(1).ToUnixTimeMilliseconds() : DateTimeOffset.UtcNow.AddDays(1).ToUnixTimeMilliseconds(), chunks);
        }
        foreach (var batch in batches) await telefon.SendPersonalSyncAsync(peerId, "personal_sync.batch", batch);
        if (message.TryGetProperty("report", out var reportNode) && reportNode.ValueKind == JsonValueKind.Object)
            await telefon.StagePersonalReportAsync(peerId, JsonNode.Parse(reportNode.GetRawText())!.AsObject());
        if (message.TryGetProperty("commit", out var commit) && commit.ValueKind == JsonValueKind.Object)
        {
            var token = PropertyText(commit, "token");
            var committed = telefon.CommitPersonalSync(peerId, PropertyText(commit, "messageId"), token, "applied");
            CompletePersonalWebCommit(token, committed);
            if (!committed) throw new InvalidOperationException(T("The personal synchronization commit could not be confirmed."));
        }
    }

    private Task IndexPersonalSyncAttachmentsAsync(JsonElement message)
    {
        var sources = ParseAttachmentSources(NodeArray(message, "sources"));
        var peerId = Text(message, "kennung"); var runId = Text(message, "runId");
        var reply = Boolean(message, "reply"); var recordsHash = Text(message, "recordsHash");
        foreach (var source in sources.Values)
        {
            var descriptor = new JsonObject { ["attachment_id"] = source.Hash, ["name"] = source.Hash,
                ["kind"] = source.Mime.StartsWith("image/", StringComparison.Ordinal) ? "image" : "pdf",
                ["mime"] = source.Mime, ["size"] = source.Data.LongLength, ["sha256"] = source.Hash };
            try
            {
                telefon.StagePersonalAttachment(peerId, runId, reply, recordsHash, descriptor, "outgoing",
                    DateTimeOffset.UtcNow.AddDays(1).ToUnixTimeMilliseconds(),
                    source.Data.Chunk(PersonalSyncContract.ChunkRaw).Select((data, index) => (index, data)));
            }
            finally { CryptographicOperations.ZeroMemory(source.Data); }
        }
        return Task.CompletedTask;
    }

    private async Task CommitPersonalSyncAsync(JsonElement message)
    {
        var token = Text(message, "token");
        var success = Boolean(message, "erfolgreich");
        var outcome = message.TryGetProperty("outcome", out var result) && result.ValueKind == JsonValueKind.String
            ? result.GetString() ?? "invalid" : success ? "applied" : "invalid";
        var committed = telefon.CommitPersonalSync(Text(message, "kennung"), Text(message, "messageId"), token, outcome);
        CompletePersonalWebCommit(token, committed);
        if (!committed && success)
            await form.SendAsync("App.personalSyncFehler", new { fehler = T("The permanent personal synchronization commit was rejected.") });
    }

    private void CompletePersonalWebCommit(string token, bool committed)
    {
        TaskCompletionSource<bool>? completion;
        lock (personalSyncGate)
        {
            personalUiPending.Remove(token);
            completion = personalSyncWebCommits.Remove(token, out var pending) ? pending.Completion : null;
        }
        completion?.TrySetResult(committed);
    }

    private async Task HandlePersonalSyncEventAsync(JsonObject message)
    {
        lock (personalSyncGate) if (restoreInProgress) throw new OperationCanceledException();
        var peerId = message["device_id"]?.GetValue<string>() ?? "";
        var kind = message["kind"]?.GetValue<string>() ?? "";
        var body = message["body"] as JsonObject ?? new JsonObject();
        if (kind == "personal_sync.request")
        {
            lock (personalSyncGate) personalSyncRequests[PersonalRunKey(peerId, body["run_id"]!.GetValue<string>())] = body.DeepClone().AsObject();
            await form.SendAsync("App.personalSync", message);
            return;
        }
        if (kind == "personal_sync.attachment_chunk") return;
        if (kind == "personal_sync.attachment_request")
        {
            await RespondToAttachmentRequestAsync(peerId, body);
            return;
        }
        if (kind is "personal_sync.attachment_result") return;
        if (kind == "personal_sync.batch")
        {
            var runId = body["run_id"]!.GetValue<string>();
            JsonObject? request;
            lock (personalSyncGate) personalSyncRequests.TryGetValue(PersonalRunKey(peerId, runId), out request);
            request ??= telefon.PersonalRunRequest(peerId, runId);
            if (request is null || body["format"]?.GetValue<int>() != request["format"]!.GetValue<int>())
                throw new InvalidDataException(T("The personal synchronization run does not match."));
            body["requested_modules"] = request?["modules"]?.DeepClone() ?? new JsonArray();
            body["trigger"] = request?["trigger"]?.DeepClone();
            if (body["format"]?.GetValue<int>() >= 2) body["attachment_data"] = BuildAttachmentData(peerId, body);
            var token = message["commit_token"]?.GetValue<string>() ?? throw new InvalidDataException(T("The personal synchronization commit token is missing."));
            var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (personalSyncGate)
            {
                if (restoreInProgress) throw new OperationCanceledException();
                personalUiPending.Add(token); personalSyncWebCommits[token] = (peerId, completion);
            }
            await form.SendAsync("App.personalSync", message);
            bool committed;
            try { committed = await completion.Task.WaitAsync(TimeSpan.FromSeconds(30)); }
            finally { lock (personalSyncGate) if (completion.Task.IsCompleted) personalSyncWebCommits.Remove(token); }
            if (!committed) throw new InvalidDataException(T("The personal synchronization batch was not saved permanently."));
            return;
        }
        if (kind is "personal_sync.deletion_proposals" or "personal_sync.deletion_decision")
        {
            var token = message["commit_token"]?.GetValue<string>() ?? throw new InvalidDataException();
            var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (personalSyncGate)
            {
                if (restoreInProgress) throw new OperationCanceledException();
                personalUiPending.Add(token); personalSyncWebCommits[token] = (peerId, completion);
            }
            await form.SendAsync("App.personalSync", message);
            try { await completion.Task.WaitAsync(TimeSpan.FromSeconds(30)); }
            finally { lock (personalSyncGate) if (completion.Task.IsCompleted) personalSyncWebCommits.Remove(token); }
            return;
        }
        await form.SendAsync("App.personalSync", message);
    }

    private Dictionary<string, PersonalAttachmentSource> ParseAttachmentSources(JsonArray values)
    {
        if (values.Count > 64) throw new InvalidDataException(T("There are too many personal synchronization attachments."));
        var result = new Dictionary<string, PersonalAttachmentSource>(StringComparer.Ordinal);
        foreach (var node in values.OfType<JsonObject>())
        {
            var claimed = node["sha256"]?.GetValue<string>() ?? "";
            var decoded = PersonalSyncContract.DecodeDataUrl(node["data"]?.GetValue<string>() ?? "");
            var actual = Convert.ToHexString(SHA256.HashData(decoded.Data)).ToLowerInvariant();
            if (claimed != actual || !result.TryAdd(claimed, new PersonalAttachmentSource(claimed, decoded.Mime, decoded.Data)))
                throw new InvalidDataException(T("A personal synchronization attachment hash is invalid or duplicated."));
        }
        if (result.Count != values.Count) throw new InvalidDataException(T("A personal synchronization attachment source is not an object."));
        return result;
    }

    private async Task SendAttachmentChunksAsync(string peerId, string runId, bool reply, string recordsHash,
        PersonalAttachmentSource source, IReadOnlyList<(int Start, int End)>? ranges = null)
    {
        var data = telefon.ReadPersonalAttachment(peerId, runId, reply, recordsHash, source.Hash, "outgoing", "wifi");
        try
        {
            var total = (data.Length + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw;
            ranges ??= [(0, total)];
            foreach (var (start, end) in ranges)
                for (var index = start; index < end; index++)
                {
                    if (index < 0 || index >= total) throw new InvalidDataException(T("The attachment range is invalid."));
                    var offset = index * PersonalSyncContract.ChunkRaw;
                    var count = Math.Min(PersonalSyncContract.ChunkRaw, data.Length - offset);
                    var body = new JsonObject { ["format"] = 2, ["run_id"] = runId, ["reply"] = reply,
                        ["records_hash"] = recordsHash, ["sha256"] = source.Hash, ["index"] = index,
                        ["data"] = Convert.ToBase64String(data, offset, count) };
                    await telefon.SendPersonalSyncAsync(peerId, "personal_sync.attachment_chunk", body);
                }
        }
        finally { CryptographicOperations.ZeroMemory(data); }
    }

    private JsonObject BuildAttachmentData(string peerId, JsonObject body)
    {
        var result = new JsonObject();
        foreach (var record in (body["records"] as JsonArray ?? []).OfType<JsonObject>())
            foreach (var descriptor in (record["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
            {
                PersonalSyncContract.ValidateAttachmentDescriptor(descriptor);
                var hash = descriptor["sha256"]!.GetValue<string>();
                if (result.ContainsKey(hash)) continue;
                var runId = body["run_id"]!.GetValue<string>(); var reply = body["reply"]!.GetValue<bool>();
                var recordsHash = body["records_hash"]!.GetValue<string>();
                var bytes = telefon.ReadPersonalAttachment(peerId, runId, reply, recordsHash, hash, "incoming", "wifi");
                try { result[hash] = $"data:{descriptor["mime"]!.GetValue<string>()};base64,{Convert.ToBase64String(bytes)}"; }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
        return result;
    }

    private async Task RespondToAttachmentRequestAsync(string peerId, JsonObject body)
    {
        PersonalSyncContract.ValidateBody("personal_sync.attachment_request", body);
        foreach (var want in body["wants"]!.AsArray().OfType<JsonObject>())
        {
            var hash = want["sha256"]!.GetValue<string>();
            if (telefon.MissingPersonalAttachmentRanges(peerId, body["run_id"]!.GetValue<string>(),
                body["reply"]!.GetValue<bool>(), body["records_hash"]!.GetValue<string>(), hash, "outgoing").Count != 0)
                throw new InvalidDataException(T("The personal synchronization attachment source is incomplete."));
            var source = new PersonalAttachmentSource(hash, "", [], null);
            var ranges = want["ranges"]!.AsArray().OfType<JsonArray>().Select(range =>
                (range[0]!.GetValue<int>(), range[1]!.GetValue<int>())).ToArray();
            await SendAttachmentChunksAsync(peerId, body["run_id"]!.GetValue<string>(), body["reply"]!.GetValue<bool>(),
                body["records_hash"]!.GetValue<string>(), source, ranges);
        }
    }

    private static JsonObject Object(JsonElement parent, string name) => parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object
        ? JsonNode.Parse(value.GetRawText())!.AsObject() : throw new InvalidDataException($"{name} fehlt.");
    private static JsonArray NodeArray(JsonElement parent, string name) => parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array
        ? JsonNode.Parse(value.GetRawText())!.AsArray() : new JsonArray();
    private static string PersonalRunKey(string peerId, string runId) => peerId + "\0" + runId;
    private void ClearPersonalSyncRuntime()
    {
        lock (personalSyncGate)
        {
            foreach (var pending in personalSyncWebCommits.Values) pending.Completion.TrySetCanceled();
            personalSyncRequests.Clear(); personalSyncWebCommits.Clear();
        }
    }

    private void ClearPersonalSyncRuntime(string peerId)
    {
        lock (personalSyncGate)
        {
            foreach (var key in personalSyncRequests.Keys.Where(key => key.StartsWith(peerId + "\0", StringComparison.Ordinal)).ToArray()) personalSyncRequests.Remove(key);
            foreach (var token in personalSyncWebCommits.Where(item => item.Value.PeerId == peerId).Select(item => item.Key).ToArray())
                if (personalSyncWebCommits.Remove(token, out var pending)) pending.Completion.TrySetCanceled();
        }
    }

    private sealed record PersonalAttachmentSource(string Hash, string Mime, byte[] Data, JsonObject? InitialDescriptor = null)
    {
        internal JsonObject Descriptor { get; set; } = InitialDescriptor ?? new JsonObject();
    }
}
