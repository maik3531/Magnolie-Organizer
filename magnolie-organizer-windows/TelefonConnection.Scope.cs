using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonConnection
{
    private PhoneContentScope.Session? receivedContentScope;
    private readonly string actorSourceEpoch = Guid.NewGuid().ToString("D");
    private bool? actorRemoteOwnDecision;
    private long actorRemoteOwnRevision;
    private long actorCapabilityRevision = -1, actorGrantRevision = -1;
    private JsonObject? sentConnectionCapabilities;
    private byte[]? receivedConnectionRequestHash;
    private string? acknowledgedConnectionRequest;
    private readonly ConcurrentDictionary<string, byte> acknowledgedConnectionBatches = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> acknowledgedReplyOriginalControls = new(StringComparer.Ordinal);
    private (string Id, string Token, long Expires)? scopedOriginalBatch;
    private volatile ScopedOriginalWindow? scopedOriginalWindow;
    private int scopedOriginalWindowAttempts;
    private long nextScopedOriginalWindowAttempt;
    private bool scopedOriginalWindowAnswered, scopedOriginalWindowRejected, scopedOriginalWindowComplete;
    private (string MessageId, string Token, NativeBookSaveState Book, bool NeedsResults)? savedConnectionBatch;
    private JsonObject? sentScopedReply;
    private int scopedReplyAttempts;
    private long nextScopedReplyAttempt;
    private bool scopedReplyQueued, scopedReplyRejected, scopedOriginalResultsQueued;
    internal Func<NativeBookSaveState?>? ConnectionReplyBook { get; set; }
    internal Func<JsonObject, Task>? ScopedConnectionBatchReady { get; set; }
    private string? offeredConnectionBatch;
    internal string? AuthenticatedLocalId { get; init; }
    internal Func<TelefonConnection, bool>? CurrentConnectionReader { get; set; }
    private string ScopePublicKey => Convert.ToHexString(peer.PublicKey);
    private bool ContentScopeSelected
    {
        get
        {
            var settings = store.SharedSettings(peer.Id, peer.PublicKey);
            return settings is not null && SharedSyncSettings.Effective(settings)["content_mode"]?.GetValue<string>() == "phone_scope";
        }
    }

    private bool ContentScopeAuthorized
    {
        get
        {
            if (!SharedControlsReady) return false;
            var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
            if (current is null || !PhoneContentScope.Supported(SharedLocalCapabilities(), current.Capabilities)) return false;
            if (new[] { "personal_notes_sync", "personal_tasks_sync" }.Any(name =>
                    store.LocalGrants()[name]?.GetValue<bool>() != true || current.Grants[name]?.GetValue<bool>() != true)) return false;
            return ContentScopeSelected;
        }
    }

    private bool ContentScopeControlsReady => ContentScopeAuthorized && SharedSettingsReady;
    internal bool SingleItemAllowed => ContentScopeControlsReady;
    internal Func<JsonObject, Task>? CollectionChanged { get; set; }
    private bool SingleItemRun(string kind, JsonObject body) =>
        (kind == "personal_sync.request" ? body : body["run_id"] is JsonValue id && id.TryGetValue<string>(out var run)
            ? new PersonalSyncStore(store).LoadRun(peer.Id, run, Now())?.Request : null)?["send_item"] is JsonObject;

    private void RequireContentScopeControls()
    {
        if (!ContentScopeAuthorized) throw new InvalidOperationException("Current content scope is unauthorized.");
        if (!SharedSettingsReady) throw new IOException("Shared preference agreement is pending.");
    }

    private string ConnectionRequestAuthority(JsonObject request, JsonObject reference)
    {
        if (disposed || cancellation.IsCancellationRequested || store.RestoreFenced || transport is not ("wifi" or "bluetooth") ||
            CurrentConnectionReader?.Invoke(this) != true || !ContentScopeControlsReady)
            throw new InvalidOperationException("Connection reader is unavailable.");
        CurrentContentScope(reference);
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
        var sent = Volatile.Read(ref sentConnectionCapabilities);
        if (current is null || sent is null || current.CapabilityRevision != Interlocked.Read(ref actorCapabilityRevision) ||
            current.GrantRevision != Interlocked.Read(ref actorGrantRevision) ||
            TelefonProtocolContract.Integer(sent["revision"]) != store.CurrentOwnRevision("capabilities") ||
            !PersonalSyncContract.AutoConnectionSupported(sent["items"]!.AsObject(), current.Capabilities))
            throw new InvalidOperationException("Connection automation was not negotiated on this reader.");
        var settings = store.SharedSettings(peer.Id, peer.PublicKey) ?? throw new InvalidOperationException("Shared choice unavailable.");
        if (SharedSyncSettings.Effective(settings)["auto_mode"]?.GetValue<string>() != "connection")
            throw new InvalidOperationException("Connection automation is not selected.");
        var format = request["format"]!.GetValue<int>();
        foreach (var module in request["modules"]!.AsArray())
        {
            var kind = "personal_" + module!.GetValue<string>() + "_sync";
            if (!TelefonCoordinator.SupportsPersonalFormat(current, kind, format) || sent["items"]?[kind]?["versions"] is not JsonArray versions ||
                !versions.Any(value => value?.GetValue<int>() == format))
                throw new InvalidOperationException("Connection record format was not negotiated.");
        }
        return Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(new JsonObject {
            ["reader"] = actorSourceEpoch, ["transport"] = transport, ["peer"] = current.Id,
            ["key"] = Convert.ToBase64String(current.PublicKey), ["scope"] = reference.DeepClone(),
            ["remote_capabilities"] = current.CapabilityRevision, ["remote_grants"] = current.GrantRevision,
            ["local_capabilities"] = TelefonProtocolContract.Integer(sent["revision"]), ["local_grants"] = store.LocalGrants(),
            ["local_grants_revision"] = store.CurrentOwnRevision("grants"),
            ["mode"] = settings["settings"]!["auto_mode"]!.DeepClone(),
            ["direction"] = settings["settings"]!["content_mode"]!.DeepClone(),
            ["deletion_choice"] = settings["settings"]!["skip_deletions"]!.DeepClone()
        }))).ToLowerInvariant();
    }

    private string AcknowledgedConnectionAuthority(JsonObject request, JsonObject reference)
    {
        var runId = request["run_id"]!.GetValue<string>();
        if (runId != Volatile.Read(ref acknowledgedConnectionRequest) &&
            (runId != scopedInitialRun || !scopedInitialComplete || scopedInitialRejected))
            throw new InvalidOperationException("The original reader has not acknowledged this connection request.");
        return ConnectionRequestAuthority(request, reference);
    }

    internal bool RequireScopedConnectionBatchForSave(string messageId, string token, JsonObject? candidate = null) =>
        new PersonalSyncStore(store).RequireScopedConnectionBatchForSave(peer.Id, messageId, token, Now(),
            AcknowledgedConnectionAuthority, acknowledgedConnectionBatches.ContainsKey, candidate);

    // The coordinator serializes access to this proof under the reader and
    // policy guards. The bridge retains the native document writer gate.
    internal void RecordScopedConnectionBatchSave(string messageId, string token, NativeBookSaveState book, bool needsResults) =>
        savedConnectionBatch = (messageId, token, book, needsResults);

    internal void QueueScopedConnectionReply(string messageId, string token, IReadOnlyList<JsonObject> batches, int conflicts, int oversized,
        Func<NativeBookSaveState?> currentBook, string? savedText)
    {
        if (savedConnectionBatch is not { } proof || proof.MessageId != messageId || proof.Token != token || currentBook() != proof.Book)
            throw new InvalidOperationException("The original reader has no confirmed scoped connection save.");
        var runs = new PersonalSyncStore(store);
        QueueOriginalResultsIfSaved(runs, currentBook);
        runs.QueueScopedConnectionReply(peer.Id, messageId, token, proof.Book, batches, conflicts, oversized, transport, Now(),
            AcknowledgedConnectionAuthority, CurrentContentScope, acknowledgedConnectionBatches.ContainsKey, () => currentBook() == proof.Book, savedText);
        savedConnectionBatch = null;
        scopedReplyQueued = true;
    }

    private void QueueOriginalResultsIfSaved(PersonalSyncStore runs, Func<NativeBookSaveState?> currentBook)
    {
        if (scopedOriginalResultsQueued || savedConnectionBatch is not { NeedsResults: true } proof) return;
        runs.QueueScopedOriginalResults(peer.Id, proof.MessageId, proof.Token, proof.Book, Now(),
            AcknowledgedConnectionAuthority, acknowledgedConnectionBatches.ContainsKey, currentBook);
        scopedOriginalResultsQueued = scopedReplyQueued = true;
    }

    private async Task<JsonObject?> PumpScopedOriginalsAsync()
    {
        var now = Now();
        if (scopedOriginalBatch is not { } input || input.Expires <= now || nextScopedOriginalWindowAttempt > now) return null;
        var runs = new PersonalSyncStore(store);
        try
        {
            if (scopedOriginalWindowComplete && scopedOriginalWindow is { } completed)
            {
                runs.RetireScopedOriginalWindow(completed, now, AcknowledgedConnectionAuthority);
                scopedOriginalWindow = null;
                scopedOriginalWindowAttempts = 0;
                scopedOriginalWindowAnswered = scopedOriginalWindowComplete = false;
            }
            if (scopedOriginalWindowAnswered || scopedOriginalWindowRejected) return null;
            var window = scopedOriginalWindow ??= runs.QueueScopedOriginalWindow(peer.Id, input.Id, input.Token, now,
                AcknowledgedConnectionAuthority, acknowledgedConnectionBatches.ContainsKey);
            if (window is null)
            {
                if (ScopedConnectionBatchReady is null) return null;
                var prepared = runs.PrepareScopedOriginalOffer(peer.Id, input.Id, input.Token, Now(),
                    AcknowledgedConnectionAuthority, acknowledgedConnectionBatches.ContainsKey);
                var offer = ScopedConnectionBatchOffer(prepared.Batch, prepared.Request, prepared.Reference, prepared.Data);
                scopedOriginalBatch = null;
                return offer;
            }
            await WritePlainAsync(window.Frame, () => runs.RequireScopedOriginalWindow(window, Now(), AcknowledgedConnectionAuthority));
            nextScopedOriginalWindowAttempt = Now() + TelefonStore.RetryDelayMs(++scopedOriginalWindowAttempts);
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or TelefonMessageException or
            CryptographicException or Microsoft.Data.Sqlite.SqliteException)
        {
            nextScopedOriginalWindowAttempt = Now() + TelefonStore.RetryDelayMs(1);
        }
        return null;
    }

    private async Task<bool> ObserveScopedOriginalAckAsync(string id, string status, string error)
    {
        if (scopedOriginalWindow?.Id != id) return false;
        await store.NotePolicyGate.WaitAsync(cancellation);
        try
        {
            if (scopedOriginalWindow is not { } window || window.Id != id) return false;
            if (scopedOriginalWindowAttempts == 0 || scopedOriginalWindowRejected) return true;
            new PersonalSyncStore(store).RequireScopedOriginalWindow(window, Now(), AcknowledgedConnectionAuthority);
            if (status is "accepted" or "duplicate" && error == "none") scopedOriginalWindowAnswered = true;
            else if (error != "temporary_failure" && !scopedOriginalWindowAnswered) scopedOriginalWindowRejected = true;
            return true;
        }
        catch (Exception fault) when (fault is InvalidOperationException or InvalidDataException or CryptographicException or Microsoft.Data.Sqlite.SqliteException or IOException)
        {
            return true; // A scoped ACK is never handled by the legacy queue.
        }
        finally { store.NotePolicyGate.Release(); }
    }

    private async Task PumpScopedConnectionReplyAsync()
    {
        if (ConnectionReplyBook is not { } currentBook || (Volatile.Read(ref acknowledgedConnectionRequest) ?? scopedInitialRun) is not { } runId ||
            scopedReplyRejected || nextScopedReplyAttempt > Now()) return;
        var runs = new PersonalSyncStore(store);
        JsonObject? CurrentFrame() => runs.NextScopedConnectionReply(peer.Id, runId, Now(), AcknowledgedConnectionAuthority, currentBook,
            acknowledgedReplyOriginalControls.ContainsKey);
        try
        {
            QueueOriginalResultsIfSaved(runs, currentBook);
            if (!scopedReplyQueued) return;
            if (CurrentFrame() is not { } frame) return;
            await WritePlainAsync(frame, () =>
            {
                if (!JsonNode.DeepEquals(frame, CurrentFrame()))
                    throw new InvalidOperationException("The scoped reply lost its original reader or saved book before send.");
            });
            sentScopedReply = frame;
            nextScopedReplyAttempt = Now() + TelefonStore.RetryDelayMs(++scopedReplyAttempts);
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or TelefonMessageException or
            CryptographicException or Microsoft.Data.Sqlite.SqliteException)
        {
            // A held plan does not delay ordinary controls, WLAN sync or time sync.
            nextScopedReplyAttempt = Now() + TelefonStore.RetryDelayMs(1);
        }
    }

    private async Task<bool> ObserveScopedConnectionReplyAckAsync(string id, string status, string error)
    {
        if ((Volatile.Read(ref acknowledgedConnectionRequest) ?? scopedInitialRun) is not { } runId ||
            ConnectionReplyBook is not { } currentBook) return false;
        await store.NotePolicyGate.WaitAsync(cancellation);
        try
        {
            if (sentScopedReply is not { } sent || sent["message_id"]!.GetValue<string>() != id) return false;
            if (scopedReplyRejected) return true;
            var runs = new PersonalSyncStore(store);
            if (status is "accepted" or "duplicate" && error == "none")
            {
                if (runs.AcknowledgeScopedConnectionReply(peer.Id, runId, sent, Now(), AcknowledgedConnectionAuthority, currentBook,
                    acknowledgedReplyOriginalControls.ContainsKey, out var more))
                {
                    var wrapper = sent["body"]!.AsObject();
                    scopedReplyQueued = more;
                    sentScopedReply = null;
                    scopedReplyAttempts = 0;
                    nextScopedReplyAttempt = 0;
                    if (!more && wrapper["kind"]?.GetValue<string>() == "personal_sync.report" &&
                        wrapper["body"] is JsonObject report && report["state"]?.GetValue<string>() == "complete")
                        PersonalSuccessConfirmed?.Invoke(this, report);
                }
            }
            else if (error != "temporary_failure" &&
                JsonNode.DeepEquals(runs.NextScopedConnectionReply(peer.Id, runId, Now(), AcknowledgedConnectionAuthority, currentBook,
                    acknowledgedReplyOriginalControls.ContainsKey), sent))
                scopedReplyRejected = true;
            return true;
        }
        catch (Exception fault) when (fault is InvalidOperationException or InvalidDataException or TelefonMessageException or
            CryptographicException or Microsoft.Data.Sqlite.SqliteException)
        { return true; }
        finally { store.NotePolicyGate.Release(); }
    }

    internal JsonObject CurrentContentScope(JsonObject claimed)
    {
        RequireContentScopeControls();
        if (receivedContentScope is null)
            throw new InvalidOperationException("Current content scope is unavailable.");
        // The session object is owned by this TelefonConnection, not a persisted global map.
        return receivedContentScope.Current(peer.Id, ScopePublicKey, 0, claimed);
    }

    internal JsonObject ActorSourceSnapshot()
    {
        if (disposed || cancellation.IsCancellationRequested || actorRemoteOwnDecision != true ||
            transport is not ("wifi" or "bluetooth") || !ContentScopeControlsReady)
            throw new InvalidOperationException("Actor source is unavailable.");
        var current = store.LoadPeers().SingleOrDefault(value => value.Id == peer.Id && value.PublicKey.SequenceEqual(peer.PublicKey));
        var local = SharedLocalCapabilities();
        if (current is null || current.CapabilityRevision != Interlocked.Read(ref actorCapabilityRevision) ||
            current.GrantRevision != Interlocked.Read(ref actorGrantRevision) ||
            !PersonalSyncActorContract.Supported(local, current.Capabilities) || receivedContentScope is null)
            throw new InvalidOperationException("Actor source is unavailable.");
        return new JsonObject { ["connection"] = actorSourceEpoch, ["transport"] = transport,
            ["peer"] = current.Id, ["key"] = Convert.ToBase64String(current.PublicKey),
            ["scope"] = receivedContentScope.CurrentReference(peer.Id, ScopePublicKey, 0),
            ["settings"] = store.SharedSettings(peer.Id, peer.PublicKey), ["local_capabilities"] = local.DeepClone(),
            ["local_control_revisions"] = new JsonArray(JsonValue.Create(store.CurrentOwnRevision("capabilities")), JsonValue.Create(store.CurrentOwnRevision("grants"))),
            ["remote_control_revisions"] = new JsonArray(JsonValue.Create(current.CapabilityRevision), JsonValue.Create(current.GrantRevision)),
            ["remote_own_revision"] = Interlocked.Read(ref actorRemoteOwnRevision),
            ["remote_capabilities"] = current.Capabilities.DeepClone(), ["local_grants"] = store.LocalGrants(),
            ["remote_grants"] = current.Grants.DeepClone() };
    }

    internal JsonObject? DataContentScope(string kind, JsonObject body)
    {
        if (kind == "personal_sync.deletion_decision") return null;
        if (body["run_id"] is not JsonValue id || !id.TryGetValue<string>(out var runId)) return null;
        var runs = new PersonalSyncStore(store);
        if (runs.LoadRun(peer.Id, runId, Now())?.Policy == "connection_only")
            throw new InvalidOperationException("Connection-only data requires the protected send path.");
        var reference = runs.ScopedRunReference(peer.Id, peer.PublicKey, runId, Now());
        if (reference is null) return null;
        if (kind is not ("personal_sync.request" or "personal_sync.batch" or "personal_sync.report" or
            "personal_sync.attachment_request" or "personal_sync.attachment_chunk" or "personal_sync.attachment_result" or "personal_sync.deletion_proposals"))
            throw new InvalidOperationException("Scoped runs do not transmit deletion decisions.");
        var manifest = CurrentContentScope(reference);
        if (kind == "personal_sync.batch")
        {
            var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            foreach (var value in body["records"]!.AsArray())
            {
                var record = value!.AsObject(); var type = record["kind"]!.GetValue<string>(); var recordId = record["id"]!.GetValue<string>();
                if (type == "note" && !notes.Contains(recordId) || type == "task" && !tasks.Contains(recordId))
                    throw new InvalidOperationException("Record outside current phone membership.");
            }
        }
        if (kind == "personal_sync.deletion_proposals")
        {
            var values = SharedSyncSettings.Effective(store.SharedSettings(peer.Id, peer.PublicKey) ?? throw new InvalidOperationException("Shared settings missing."));
            if (values["skip_deletions"]!.GetValue<bool>()) throw new InvalidOperationException("Deletion transfer disabled.");
            var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet();
            var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet();
            foreach (var node in body["proposals"]!.AsArray())
            {
                var item = node!.AsObject(); var type = item["kind"]!.GetValue<string>();
                var valid = type == "attachment" ? notes.Contains(item["parent_id"]!.GetValue<string>()) :
                    type == "note" ? notes.Contains(item["id"]!.GetValue<string>()) : type == "task" && tasks.Contains(item["id"]!.GetValue<string>());
                if (!valid) throw new InvalidOperationException("Deletion outside phone collection.");
            }
        }
        return manifest;
    }

    internal bool ScopedDeletionAllowed(string kind, JsonObject body, bool outgoing)
    {
        if (!ContentScopeControlsReady) return false;
        var current = store.SharedSettings(peer.Id, peer.PublicKey);
        if (current is null || SharedSyncSettings.Effective(current)["skip_deletions"]!.GetValue<bool>()) return false;
        if (kind == "personal_sync.deletion_proposals") return outgoing && DataContentScope(kind, body) is not null;
        return kind == "personal_sync.deletion_decision" && !outgoing &&
            new PersonalSyncStore(store).ScopedRunReference(peer.Id, peer.PublicKey, body["run_id"]!.GetValue<string>(), Now()) is not null &&
            body["decisions"]!.AsArray().All(value => value!["decision"]!.GetValue<string>() == "delete");
    }

    private async Task HandleScopedDataAsync(JsonObject message)
    {
        TelefonMessageContract.ValidateMessage(message, Now(), true);
        var id = message["message_id"]!.GetValue<string>(); var wrapped = message["body"]!.AsObject();
        string error;
        TelefonAck? boundReceipt = null;
        string? boundAuthority = null;
        JsonObject? authorityRequest = null;
        PersonalSyncStagedBatch? stagedConnectionBatch = null;
        ScopedOriginalWindow? finishedOriginalWindow = null;
        NativeBookSaveState? replyOriginalBook = null;
        bool initialOriginalWindow = false;
        JsonObject? confirmedReport = null;
        try
        {
            JsonObject inner;
            await store.NotePolicyGate.WaitAsync(cancellation);
            try
            {
                if (TelefonProtocolContract.Integer(message["expires_ms"]) <= Now()) throw new InvalidDataException("Scoped message expired.");
                var manifest = CurrentContentScope(wrapped["scope"]!.AsObject());
                var (kind, body) = PhoneContentScope.Unwrap(wrapped, manifest);
                inner = message.DeepClone().AsObject(); inner["kind"] = kind; inner["body"] = body;
                var runs = new PersonalSyncStore(store);
                var connectionRequest = kind == "personal_sync.request" &&
                    body["trigger"]?.GetValue<string>() == PersonalSyncContract.AutoConnectionTrigger;
                var savedRun = kind == "personal_sync.request" ? null :
                    runs.LoadRun(peer.Id, body["run_id"]!.GetValue<string>(), Now());
                var connectionBatch = kind == "personal_sync.batch" && savedRun?.Policy == "connection_only";
                var connectionChunk = kind == "personal_sync.attachment_chunk" && savedRun?.Policy == "connection_only";
                var replyOriginalControl = kind is "personal_sync.attachment_request" or "personal_sync.attachment_result" &&
                    savedRun?.Policy == "connection_only";
                var connectionReport = kind == "personal_sync.report" && savedRun?.Policy == "connection_only";
                var protectedMessage = connectionRequest || connectionBatch || connectionChunk || replyOriginalControl || connectionReport;
                if (store.HasIncomingReceipt(peer.Id, id) && !store.ReceivedMatches(peer.Id, protectedMessage ? message : inner))
                    throw new InvalidDataException("Conflicting scoped message identity.");
                if (kind == "personal_sync.request")
                {
                    var trigger = body["trigger"]!.GetValue<string>();
                    if (connectionRequest)
                    {
                        if (AuthenticatedLocalId is not { } localId || StringComparer.Ordinal.Compare(peer.Id, localId) >= 0)
                            throw new InvalidOperationException("The peer is not the elected connection initiator.");
                        var requestHash = SHA256.HashData(TelefonCrypto.Canonical(message));
                        if (scopedConnectionStarted ||
                            receivedConnectionRequestHash is { } previous && !previous.AsSpan().SequenceEqual(requestHash))
                            throw new InvalidOperationException("The original reader already admitted a connection request.");
                        var reference = wrapped["scope"]!.AsObject();
                        var authority = ConnectionRequestAuthority(body, reference);
                        boundReceipt = runs.RememberScopedConnectionRequest(peer.Id, peer.PublicKey, message, Now(), authority,
                            () => ConnectionRequestAuthority(body, reference));
                        receivedConnectionRequestHash = requestHash;
                        boundAuthority = authority;
                        authorityRequest = body;
                    }
                    else
                    {
                        if (trigger == "auto_wifi" && transport != "wifi")
                            throw new InvalidOperationException("WLAN-only request received on another transport.");
                        runs.RememberScopedRun(peer.Id, peer.PublicKey, body, wrapped["scope"]!.AsObject(), Now(), TelefonProtocolContract.Integer(message["expires_ms"]));
                    }
                }
                else if (connectionBatch)
                {
                    var reference = wrapped["scope"]!.AsObject();
                    var request = savedRun!.Request;
                    var authority = AcknowledgedConnectionAuthority(request, reference);
                    (boundReceipt, stagedConnectionBatch) = runs.StageScopedConnectionBatch(peer.Id, message, manifest, transport, Now(), authority,
                        () => AcknowledgedConnectionAuthority(request, reference));
                    boundAuthority = authority;
                    authorityRequest = request;
                }
                else if (connectionChunk)
                {
                    var reference = wrapped["scope"]!.AsObject();
                    var request = savedRun!.Request;
                    var authority = AcknowledgedConnectionAuthority(request, reference);
                    boundReceipt = runs.ScopedOriginalChunkDuplicate(peer.Id, message, request, reference, authority, Now(), AcknowledgedConnectionAuthority);
                    if (boundReceipt is null)
                    {
                        if (scopedOriginalWindow is not { } window || scopedOriginalWindowAttempts == 0 || scopedOriginalWindowRejected)
                            throw new InvalidOperationException("The original attachment window has not actually been sent.");
                        var (accepted, completed) = runs.StageScopedOriginalChunk(window, message, Now(), AcknowledgedConnectionAuthority);
                        boundReceipt = accepted;
                        if (completed) finishedOriginalWindow = window;
                    }
                    boundAuthority = authority;
                    authorityRequest = request;
                }
                else if (replyOriginalControl)
                {
                    var reference = wrapped["scope"]!.AsObject();
                    var request = savedRun!.Request;
                    replyOriginalBook = ConnectionReplyBook?.Invoke() ??
                        throw new InvalidOperationException("The native reply original book is unavailable.");
                    var forInitial = request["run_id"]!.GetValue<string>() == scopedInitialRun;
                    if (forInitial && scopedInitialRejected)
                        throw new InvalidOperationException("The initial outgoing original was rejected.");
                    Func<JsonObject, JsonObject, string> authorize = forInitial ? ConnectionRequestAuthority : AcknowledgedConnectionAuthority;
                    var authority = authorize(request, reference);
                    boundReceipt = runs.StageScopedOutgoingOriginalControl(peer.Id, message, Now(), reply: !forInitial, authorize,
                        () => ConnectionReplyBook?.Invoke() == replyOriginalBook ? replyOriginalBook : null);
                    initialOriginalWindow = forInitial && kind == "personal_sync.attachment_request";
                    boundAuthority = authority;
                    authorityRequest = request;
                }
                else if (connectionReport)
                {
                    var request = savedRun!.Request;
                    if (request["run_id"]?.GetValue<string>() != scopedInitialRun)
                        throw new InvalidOperationException("Only the elected initiator accepts a connection report.");
                    replyOriginalBook = ConnectionReplyBook?.Invoke() ??
                        throw new InvalidOperationException("The native book for the scoped report is unavailable.");
                    (boundReceipt, boundAuthority) = runs.StageScopedConnectionReport(peer.Id, message, transport, Now(),
                        AcknowledgedConnectionAuthority, () => ConnectionReplyBook?.Invoke() == replyOriginalBook ? replyOriginalBook : null);
                    authorityRequest = request;
                    confirmedReport = body;
                }
                else
                {
                    var runId = body["run_id"]!.GetValue<string>();
                    if (savedRun?.Policy == "connection_only" ||
                        !JsonNode.DeepEquals(wrapped["scope"], runs.ScopedRunReference(peer.Id, peer.PublicKey, runId, Now())))
                        throw new InvalidOperationException("Scoped run binding missing or different.");
                }
            }
            finally { store.NotePolicyGate.Release(); }
            if (boundReceipt is null) await HandlePlainBoundAsync(inner, wrapped["scope"]!.AsObject());
            else
            {
                await WritePlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = boundReceipt.MessageId,
                    ["status"] = boundReceipt.Status, ["error"] = boundReceipt.Error }, () =>
                {
                    var reference = wrapped["scope"]!.AsObject();
                    var authority = inner["kind"]!.GetValue<string>() == "personal_sync.request" ||
                        confirmedReport is null && replyOriginalBook is not null && authorityRequest!["run_id"]?.GetValue<string>() == scopedInitialRun
                        ? ConnectionRequestAuthority(authorityRequest!, reference)
                        : AcknowledgedConnectionAuthority(authorityRequest!, reference);
                    if (authority != boundAuthority || TelefonProtocolContract.Integer(message["expires_ms"]) <= Now() ||
                        replyOriginalBook is not null && ConnectionReplyBook?.Invoke() != replyOriginalBook)
                        throw new InvalidOperationException("Connection reader changed before acknowledgement.");
                });
                if (inner["kind"]!.GetValue<string>() == "personal_sync.request")
                    Volatile.Write(ref acknowledgedConnectionRequest, authorityRequest!["run_id"]!.GetValue<string>());
                else if (inner["kind"]!.GetValue<string>() == "personal_sync.batch")
                {
                    acknowledgedConnectionBatches.TryAdd(boundReceipt.MessageId, 0);
                    if (stagedConnectionBatch is { } ready)
                    {
                        if (ready.HasScopedOriginals)
                        {
                            await store.NotePolicyGate.WaitAsync(cancellation);
                            try
                            {
                                if (offeredConnectionBatch != ready.CommitToken)
                                {
                                    scopedOriginalBatch = (ready.PendingMessageId, ready.CommitToken, ready.ExpiresMs);
                                    offeredConnectionBatch = ready.CommitToken;
                                }
                            }
                            finally { store.NotePolicyGate.Release(); }
                        }
                        else await OfferScopedConnectionBatchAsync(ready, authorityRequest!, wrapped["scope"]!.AsObject());
                    }
                }
                else if (confirmedReport is not null)
                {
                    var completed = false;
                    await store.NotePolicyGate.WaitAsync(cancellation);
                    try
                    {
                        completed = new PersonalSyncStore(store).ConfirmScopedConnectionReport(peer.Id, message, transport, Now(),
                            AcknowledgedConnectionAuthority, () => ConnectionReplyBook?.Invoke() == replyOriginalBook ? replyOriginalBook : null);
                    }
                    catch (Exception fault) when (fault is IOException or InvalidOperationException or InvalidDataException or
                        CryptographicException or Microsoft.Data.Sqlite.SqliteException)
                    {
                        // The exact duplicate can retry local confirmation; do not send a second ACK.
                    }
                    finally { store.NotePolicyGate.Release(); }
                    if (completed) PersonalSuccessConfirmed?.Invoke(this, confirmedReport);
                }
                else if (replyOriginalBook is not null)
                {
                    acknowledgedReplyOriginalControls.TryAdd(boundReceipt.MessageId, 0);
                    if (initialOriginalWindow && boundReceipt.Status == "accepted")
                    {
                        scopedInitialComplete = false;
                        nextScopedInitialAttempt = 0;
                    }
                }
                else if (finishedOriginalWindow is { } finished)
                {
                    await store.NotePolicyGate.WaitAsync(cancellation);
                    try
                    {
                        if (ReferenceEquals(scopedOriginalWindow, finished))
                        {
                            scopedOriginalWindowComplete = true;
                            nextScopedOriginalWindowAttempt = 0;
                        }
                    }
                    finally { store.NotePolicyGate.Release(); }
                }
            }
            return;
        }
        catch (InvalidDataException) { error = "invalid_schema"; }
        catch (InvalidOperationException) { error = "not_granted"; }
        catch (IOException) { error = "temporary_failure"; }
        catch (CryptographicException) { error = "temporary_failure"; }
        catch (Microsoft.Data.Sqlite.SqliteException) { error = "temporary_failure"; }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = id, ["status"] = "rejected", ["error"] = error });
    }

    private async Task OfferScopedConnectionBatchAsync(PersonalSyncStagedBatch batch, JsonObject request, JsonObject reference)
    {
        if (ScopedConnectionBatchReady is not { } offer || offeredConnectionBatch == batch.CommitToken) return;
        try
        {
            RequireScopedConnectionBatchForSave(batch.PendingMessageId, batch.CommitToken);
            await offer(ScopedConnectionBatchOffer(batch, request, reference));
            offeredConnectionBatch = batch.CommitToken;
        }
        catch (Exception fault) when (fault is IOException or InvalidDataException or InvalidOperationException or
            OperationCanceledException or TimeoutException or Microsoft.Data.Sqlite.SqliteException)
        {
            // The wire receipt only confirms staging. An unavailable local
            // writer or GUI cannot turn it into a SaveACK or reply.
        }
    }

    private JsonObject ScopedConnectionBatchOffer(PersonalSyncStagedBatch batch, JsonObject request, JsonObject reference,
        JsonObject? attachmentData = null)
    {
        var body = new JsonObject { ["format"] = batch.Format, ["run_id"] = batch.RunId, ["records"] = batch.Records.DeepClone(),
            ["requested_modules"] = request["modules"]!.DeepClone() };
        if (batch.Reply) body["reply"] = true;
        if (attachmentData is not null) body["attachment_data"] = attachmentData;
        return new JsonObject { ["device_id"] = peer.Id, ["transport"] = transport,
            ["pending_message_id"] = batch.PendingMessageId, ["commit_token"] = batch.CommitToken,
            ["expires_ms"] = batch.ExpiresMs, ["content_scope"] = CurrentContentScope(reference),
            ["content_scope_fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey), ["body"] = body };
    }

    private Task SendScopedOrPlainAsync(JsonObject message)
    {
        var manifest = DataContentScope(message["kind"]!.GetValue<string>(), message["body"]!.AsObject());
        if (manifest is null)
        {
            if (ContentScopeSelected && TelefonProtocolContract.PersonalKinds.Contains(message["kind"]!.GetValue<string>()) &&
                message["kind"]!.GetValue<string>() != "personal_sync.settings" &&
                !SingleItemRun(message["kind"]!.GetValue<string>(), message["body"]!.AsObject()))
                throw new InvalidOperationException("Scoped preference does not permit raw content fallback.");
            return SendPlainAsync(message);
        }
        var wrapped = message.DeepClone().AsObject(); wrapped["kind"] = PhoneContentScope.DataKind;
        wrapped["body"] = PhoneContentScope.Wrap(message["kind"]!.GetValue<string>(), message["body"]!.AsObject(), manifest);
        return SendPlainAsync(wrapped);
    }

    private async Task HandleContentScopeAsync(JsonObject message)
    {
        JsonObject? collection = null;
        var now = Now(); TelefonMessageContract.ValidateMessage(message, now, true);
        var ack = store.CommitIncoming(peer.Id, message, now, (_, _) => ContentScopeAuthorized ? null : "not_granted",
            deferAcceptance: true, reauthorizeDuplicates: true);
        if (ack.Status is "accepted" or "duplicate" && !store.ReceivedMatches(peer.Id, message))
            ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema");
        try
        {
            if (ack.Status is "accepted" or "duplicate")
            {
                await store.NotePolicyGate.WaitAsync(cancellation);
                try
                {
                    RequireContentScopeControls();
                    if (TelefonProtocolContract.Integer(message["expires_ms"]) <= now) throw new InvalidDataException("Expired scope frame.");
                    receivedContentScope ??= new PhoneContentScope.Session(peer.Id, ScopePublicKey, 0);
                    collection = receivedContentScope.Receive(peer.Id, ScopePublicKey, 0, message["body"]!.AsObject());
                    if (ack.Process) store.MarkIncomingProcessed(peer.Id, ack.MessageId, now);
                }
                finally { store.NotePolicyGate.Release(); }
            }
        }
        catch (InvalidDataException) { ack = new TelefonAck(ack.MessageId, "rejected", "invalid_schema"); }
        catch (IOException) { ack = new TelefonAck(ack.MessageId, "rejected", "temporary_failure"); }
        catch (InvalidOperationException) { ack = new TelefonAck(ack.MessageId, "rejected", "not_granted"); }
        await SendPlainAsync(new JsonObject { ["type"] = "ack", ["message_id"] = ack.MessageId, ["status"] = ack.Status, ["error"] = ack.Error });
        if (collection is not null && ack.Status is "accepted" or "duplicate")
        {
            Volatile.Write(ref acknowledgedStartScope, PhoneContentScope.Reference(collection));
            if (CollectionChanged is not null)
                await CollectionChanged(new JsonObject { ["device_id"] = peer.Id, ["fingerprint"] = TelefonCrypto.Fingerprint(peer.PublicKey),
                    ["members"] = collection["members"]!.DeepClone() });
        }
    }
}

internal sealed partial class TelefonCoordinator
{
    // The bridge holds the document mutation gate. Hold the policy and online
    // reader gates across the synchronous native write; never await GUI or wire I/O here.
    internal async Task WriteScopedConnectionBatchAsync(string peerId, string messageId, string token, string before,
        JsonObject? previous, JsonObject candidate, string text, Action<string> writer, CancellationToken cancellation)
    {
        await store.NotePolicyGate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            lock (gate)
            {
                cancellation.ThrowIfCancellationRequested();
                if (disposed || !Enabled || store.RestoreFenced || !online.TryGetValue(peerId, out var reader) ||
                    NativeSavedBook() is not { } book || book.Sha256 != before || previous is null ||
                    ContainsAppliedScopedBatch(previous, token) || !ContainsAppliedScopedBatch(candidate, token))
                    throw new InvalidOperationException("The native connection batch or saved book is unavailable.");
                var hasOriginals = reader.RequireScopedConnectionBatchForSave(messageId, token, candidate);
                if (NativeSavedBook() != book)
                    throw new InvalidOperationException("The connection batch book changed before the native write.");
                var candidateHash = BaumSyncSnapshot.Hash(text);
                writer(text);
                var saved = NativeSavedBook();
                if (saved is null || saved.BookSource != book.BookSource || saved.Sequence != book.Sequence + 1 || saved.Sha256 != candidateHash)
                    throw new InvalidOperationException("The native writer did not confirm the exact connection batch book.");
                reader.RecordScopedConnectionBatchSave(messageId, token, saved, hasOriginals);
            }
        }
        finally { store.NotePolicyGate.Release(); }
    }

    internal async Task QueueScopedConnectionReplyAsync(string peerId, string messageId, string token, IReadOnlyList<JsonObject> batches,
        int conflicts, int oversized, CancellationToken cancellation, string? savedText = null)
    {
        await store.NotePolicyGate.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            lock (gate)
            {
                cancellation.ThrowIfCancellationRequested();
                if (disposed || !Enabled || store.RestoreFenced || !online.TryGetValue(peerId, out var reader))
                    throw new InvalidOperationException("The original connection reader is unavailable.");
                reader.QueueScopedConnectionReply(messageId, token, batches, conflicts, oversized, NativeSavedBook, savedText);
            }
        }
        finally { store.NotePolicyGate.Release(); }
    }

    private static bool ContainsAppliedScopedBatch(JsonObject book, string token) =>
        book["personalSync"]?["applied_batches"] is JsonArray tokens &&
        tokens.OfType<JsonValue>().Any(value => value.TryGetValue<string>(out var known) && known == token);
}
