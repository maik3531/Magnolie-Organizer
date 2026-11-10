using System.Text.Json.Nodes;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed record ActorCommitPlan(string Token, string ViewRevision, string AfterHash, string BookSource, long BeforeSequence, JsonObject DeletionReview, JsonObject? FixedReview);
    // Metadata only: no candidate text, source book or provider callback retained.
    private sealed class ActorHistoricalSaveClaim(NativeHistoricalRestoreCandidateProof proof, string reviewRevision,
        string choiceRevision, string sourceRevision, JsonArray targets, JsonArray choices, Dictionary<string, string> frameHashes, string authority)
    {
        internal readonly string Token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        internal readonly NativeHistoricalRestoreCandidateProof Proof = proof;
        internal readonly string ReviewRevision = reviewRevision, ChoiceRevision = choiceRevision, RestoreSourceRevision = sourceRevision, CompletionAuthority = authority;
        internal readonly JsonArray Targets = targets.DeepClone().AsArray(), Choices = choices.DeepClone().AsArray();
        internal readonly Dictionary<string, string> OriginalHashes = frameHashes;
        internal bool WriterGateChecked;
        internal NativeBookSaveState? SavedReceipt = null;
        internal NativeBookSaveState? ConfirmingSavedBook;
        internal PersonalActorDecisionCompletion? Completion = null;
    }
    // Volatile authenticated-origin quarantine, never normal data/save/ACK authority.
    private sealed class ActorTargetOrigin(string source, JsonObject scope)
    {
        internal readonly string Source = source;
        internal readonly JsonObject Scope = scope.DeepClone().AsObject();
        internal long WallDeadline = Now() + 30000, MonotonicDeadline = Environment.TickCount64 + 30000;
        internal readonly Dictionary<string, byte[]> Frames = new(StringComparer.Ordinal);
        internal int Bytes, Targets;
        internal bool Invalid;
    }
    // Native readiness only, not an IPC/request setting. Default remains closed
    // until both controllers and frontend review/receipt union are accepted.
    internal bool NativeMixedActorReady { get; set; }
    private sealed record ActorAdmission(PersonalActorHandle Handle, string PeerId, string PublicKey,
        TelefonConnection Connection, JsonObject Scope, JsonObject Start, HashSet<string> Outbound, HashSet<string> AttachmentRequests,
        HashSet<string> AttachmentResults)
    {
        internal HashSet<string> ProducedChunks { get; } = [];
        internal ActorCommitPlan? CommitPlan { get; set; }
        internal NativeBookSaveState? SaveReceipt { get; set; }
        internal string ReplyIdentity { get; set; } = "";
        internal int ReplyCount { get; set; }
        internal HashSet<string> ReplyIds { get; } = [];
        internal string CompletionReportId { get; set; } = "";
        internal bool PhonePersisted { get; set; }
        internal bool PhoneDataPersisted { get; set; }
        internal PersonalActorDecisionCompletion? Completion { get; set; }
        internal HashSet<string> CompletionIds { get; } = [];
        internal Dictionary<string, JsonObject> NativeAcknowledgments { get; } = new(StringComparer.Ordinal);
        internal bool NativeAckInFlight { get; set; }
        internal int NativeAckAttempts { get; set; }
        internal long NativeAckNextAttempt { get; set; }
        internal JsonObject IncomingCounts { get; set; } = new() { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0 };
        internal int IncomingAttachments { get; set; }
        internal NativeBookSaveState? ProducerBook { get; set; }
        internal IReadOnlyList<JsonObject>? ProducerBodies { get; set; }
        internal HashSet<string> ProducerIds { get; } = new(StringComparer.Ordinal);
        internal IReadOnlyList<JsonObject> ProducerFrames { get; set; } = [];
        internal IReadOnlyList<JsonObject> FixedFrames { get; set; } = [];
        internal PersonalActorReportOwner? ReportOwner { get; set; }
        internal string LateClaimToken { get; set; } = "";
        internal NativeBookSaveState? LateSaveReceipt { get; set; }
        internal PersonalActorDecisionCompletion? LateCompletion { get; set; }
        internal IReadOnlyList<JsonObject> LateOwnAcknowledgments { get; set; } = [];
        internal Dictionary<string, JsonObject> CompletionDeferredControls { get; } = new(StringComparer.Ordinal);
        internal bool StartDispatched { get; set; }
        internal ActorTargetOrigin? IncomingTargetOrigin { get; set; }
        internal ActorHistoricalSaveClaim? HistoricalSaveClaim { get; set; }
    }
    private readonly Dictionary<string, ActorAdmission> actorAdmissions = new(StringComparer.Ordinal);

    // Native pre-admission read only. Every page requires the same fresh source
    // pin (peer/key/channel/grants/book/scope); no saved manifest or actor owner
    // is created by this operation. Not a public MCP tool or transport frame.
    internal Task<JsonObject> ReadPersonalActorScopeAsync(string id, string fingerprint, string expectedSource,
        int offset = 0, int limit = 128, CancellationToken cancellation = default) => WithPersonalActorStoreAsync(_ => {
            if (expectedSource.Length != 64 || CurrentActorSource(id, fingerprint) != expectedSource)
                throw new InvalidOperationException("actor_source_changed");
            if (!online.TryGetValue(id, out var connection)) throw new InvalidOperationException("actor_source_changed");
            var reference = connection.ActorSourceSnapshot()["scope"]!.AsObject();
            var manifest = connection.CurrentContentScope(reference);
            var page = PhoneContentScope.ReadPage(manifest, offset, limit);
            var peer = RequireSolePeer(id); var local = SharedLocalCapabilities();
            var format = new[] { 14, 3 }.FirstOrDefault(value => new[] { "personal_notes_sync", "personal_tasks_sync" }.All(name =>
                SupportsPersonalFormat(peer, name, value) && local[name]?["versions"] is JsonArray versions && versions.Any(item => item?.GetValue<int>() == value)));
            if (format == 0) throw new InvalidOperationException("actor_record_format_unavailable");
            var settings = store.SharedSettings(id, peer.PublicKey) ?? throw new InvalidOperationException("actor_source_changed");
            page["baseline"] = new JsonObject { ["record_format"] = format,
                ["propagate_deletions"] = SharedSyncSettings.Effective(settings)["skip_deletions"]?.GetValue<bool>() == false &&
                    store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() == true && peer.Grants["personal_deletions_sync"]?.GetValue<bool>() == true };
            if (CurrentActorSource(id, fingerprint) != expectedSource || !ReferenceEquals(online.GetValueOrDefault(id), connection))
                throw new InvalidOperationException("actor_source_changed");
            page["sourceRevision"] = expectedSource;
            return page;
        }, cancellation);

    internal async Task<JsonObject> ExecuteMcpActorAsync(JsonObject request, CancellationToken cancellation)
    {
        try
        {
            var action = McpText(request, "action", true);
            if (action == "notes_actor_scope")
            {
                var page = await ReadPersonalActorScopeAsync(McpText(request, "peerId", true), McpText(request, "fingerprint", true),
                    McpText(request, "sourceRevision", true), request["offset"]?.GetValue<int>() ?? 0,
                    request["limit"]?.GetValue<int>() ?? 128, cancellation);
                return new() { ["ok"] = true, ["scopePage"] = page };
            }
            if (action is "notes_actor_source" or "notes_actor_create")
            {
                var id = McpText(request, "peerId", true); var fingerprint = McpText(request, "fingerprint", true);
                var source = CurrentActorSource(id, fingerprint);
                if (source is null) return new() { ["ok"] = false, ["code"] = "unsupported_feature" };
                if (action == "notes_actor_source") return new() { ["ok"] = true, ["sourceRevision"] = source };
                if (source != McpText(request, "sourceRevision", true)) return new() { ["ok"] = false, ["code"] = "source_changed" };
                var created = await CreatePersonalActorAsync(id, fingerprint, cancellation, source);
                return new() { ["ok"] = true, ["actorId"] = created.ActorId, ["ownerToken"] = created.OwnerToken, ["bookSource"] = "" };
            }
            var handle = new PersonalActorHandle(McpText(request, "actorId", true), McpText(request, "ownerToken", true));
            var result = action switch
            {
                "notes_actor_start" => await StartPersonalActorAsync(handle, cancellation),
                "notes_actor_produce" => await ProducePersonalActorProposalsAsync(handle, cancellation),
                "notes_actor_dispatch_proposals" => await DispatchPersonalActorProposalsAsync(handle, cancellation),
                "notes_actor_status" => await PersonalActorStatusAsync(handle, cancellation),
                "notes_actor_historical_review" => await ReviewPersonalActorIncomingTargetsAsync(handle, cancellation: cancellation),
                "notes_actor_historical_source_review" => await ReviewPersonalActorHistoricalRestoreAsync(handle, McpText(request, "reviewRevision", true),
                    request["choices"]?.AsArray().Select(value => value!.AsObject()).ToArray() ?? throw new InvalidDataException("actor_target_review_explicit_choices_required"), cancellation),
                "notes_actor_late_review" => await ReadPersonalActorLateReviewAsync(handle,
                    request["offset"]?.GetValue<int>() ?? 0, request["limit"]?.GetValue<int>() ?? 65536, McpText(request, "expectedRevision"), cancellation),
                "notes_actor_prepare_late_save" => await PreparePersonalActorLateSaveAsync(handle, McpText(request, "reviewRevision", true), McpText(request, "bookSha256", true), cancellation),
                "notes_actor_confirm_late_save" => await ConfirmPersonalActorLateSaveAsync(handle, McpText(request, "claimToken", true), cancellation),
                "notes_actor_cancel" => await CancelPersonalActorAsync(handle, cancellation),
                "notes_actor_read" => await ReadPersonalActorStagingAsync(handle,
                    request["offset"]?.GetValue<int>() ?? 0, request["limit"]?.GetValue<int>() ?? 65536,
                    McpText(request, "expectedRevision"), McpText(request, "attachmentSha256"), cancellation),
                "notes_actor_prepare_commit" => await PreparePersonalActorCommitAsync(handle, McpText(request, "expectedRevision", true), McpText(request, "bookSha256", true), cancellation,
                    request["deletionPlan"] is null ? null : request["deletionPlan"]!.AsObject()),
                "notes_actor_commit" => await CommitPersonalActorAsync(handle, McpText(request, "claimToken", true), cancellation),
                "notes_actor_reply" => await QueuePersonalActorReplyAsync(handle, McpText(request, "claimToken", true),
                    request["batches"]?.AsArray() ?? throw new InvalidDataException(), request["sources"]?.AsArray() ?? throw new InvalidDataException(), cancellation),
                "notes_actor_begin_completion" => await BeginPersonalActorCompletionAsync(handle, McpText(request, "claimToken", true), cancellation),
                "notes_actor_advance_completion" => await AdvancePersonalActorCompletionAsync(handle, cancellation),
                _ => throw new InvalidDataException("unsupported_actor_action")
            };
            return new() { ["ok"] = true, ["actor"] = result };
        }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
        catch (Microsoft.Data.Sqlite.SqliteException) { return new() { ["ok"] = false, ["code"] = "native_operation_failed" }; }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException or ArgumentException or FormatException)
        { return new() { ["ok"] = false, ["code"] = "source_changed" }; }
    }

    private static JsonObject ActorControl(string kind, JsonObject body)
    {
        var now = Now();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
    }

    internal Task<PersonalActorHandle> CreatePersonalActorAsync(string id, string fingerprint, CancellationToken cancellation = default,
        string expectedSource = "") => WithPersonalActorStoreAsync(registry => {
            var source = CurrentActorSource(id, fingerprint) ?? throw new InvalidOperationException("actor_source_changed");
            if (expectedSource.Length != 0 && expectedSource != source) throw new InvalidOperationException("actor_source_changed");
            return registry.Create(id, fingerprint, source);
        }, cancellation);

    private ActorAdmission RequirePersonalActorAdmission(PersonalSyncActorStore registry, PersonalActorHandle handle, bool requireStartFresh = false)
    {
            registry.RequireCurrent(handle);
            var status = registry.Status(handle); var id = status["peer_id"]!.GetValue<string>();
            var peer = RequireSolePeer(id);
            if (!online.TryGetValue(id, out var connection) || TelefonCrypto.Fingerprint(peer.PublicKey) != status["fingerprint"]!.GetValue<string>())
                throw new InvalidOperationException("actor_source_changed");
            if (!actorAdmissions.TryGetValue(handle.ActorId, out var value))
            {
                var start = ActorControl(PersonalSyncActorContract.StartKind, PersonalSyncActorContract.Start(handle.ActorId));
                value = new ActorAdmission(handle, id, Convert.ToBase64String(peer.PublicKey), connection,
                    connection.ActorSourceSnapshot()["scope"]!.DeepClone().AsObject(), start, [start["message_id"]!.GetValue<string>()], [], []);
                actorAdmissions.Add(handle.ActorId, value);
            }
            if (value.Handle != handle || value.PublicKey != Convert.ToBase64String(peer.PublicKey) || !ReferenceEquals(value.Connection, connection) ||
                 requireStartFresh && TelefonProtocolContract.Integer(value.Start["expires_ms"]) <= Now()) throw new InvalidOperationException("actor_source_changed");
            registry.RequireCurrent(handle);
            return value;
    }

    internal Task<JsonObject> ProducePersonalActorProposalsAsync(PersonalActorHandle handle, CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => {
            var admission = RequirePersonalActorAdmission(registry, handle);
            var status = registry.Status(handle); var fingerprint = status["fingerprint"]!.GetValue<string>();
            string? Current()
            {
                // Includes protected owner token, native process epoch and both
                // TTLs. A generic peer source alone cannot authorize a retry.
                registry.RequireCurrent(handle);
                if (RequirePersonalActorAdmission(registry, handle) != admission) throw new InvalidOperationException("actor_source_changed");
                return CurrentActorSource(admission.PeerId, fingerprint);
            }
            var source = Current() ?? throw new InvalidOperationException("actor_source_changed");
            var snapshot = NativeProducerBook() ?? throw new InvalidOperationException("actor_native_saved_book_unavailable");
            if (NativeSavedBook() != snapshot.SavedBook || snapshot.SavedBook.BookSource != NativeBookSource())
                throw new InvalidOperationException("actor_native_saved_book_changed");
            if (admission.ProducerBook is not null && admission.ProducerBook != snapshot.SavedBook)
                throw new InvalidOperationException("actor_producer_book_changed");
            var manifest = admission.Connection.CurrentContentScope(admission.Scope);
            var peer = RequireSolePeer(admission.PeerId);
            var settings = store.SharedSettings(peer.Id, peer.PublicKey) ?? throw new InvalidOperationException("actor_source_changed");
            var allowed = SharedSyncSettings.Effective(settings)["skip_deletions"]?.GetValue<bool>() == false &&
                store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() == true && peer.Grants["personal_deletions_sync"]?.GetValue<bool>() == true;
            if (admission.ProducerBodies is null)
            {
                var bodies = allowed ? PersonalActorOutgoingProducer.Prepare(snapshot, manifest, peer.Id, handle.ActorId, NativeSavedBook, Current) : [];
                // Retain exact prepared batch identity for SQL-failure retries;
                // no plaintext book cache and no re-preparation with new IDs.
                admission.ProducerBook = snapshot.SavedBook; admission.ProducerBodies = bodies;
            }
            var prepared = admission.ProducerBodies;
            if (!allowed && prepared.Count != 0) throw new InvalidOperationException("actor_deletions_not_granted");
            Current();
            var frames = prepared.Count == 0 ? [] : store.QueueActorDeletionProposals(peer.Id, handle.ActorId, prepared,
                source, snapshot.SavedBook, Current, NativeSavedBook);
            foreach (var frame in frames)
            {
                var id = frame["message_id"]!.GetValue<string>(); admission.Outbound.Add(id); admission.ProducerIds.Add(id);
            }
            admission.ProducerFrames = frames.Select(value => value.DeepClone().AsObject()).ToArray();
            Current();
            if (NativeSavedBook() != snapshot.SavedBook) throw new InvalidOperationException("actor_producer_book_changed");
            var result = new JsonObject { ["producer_staged"] = true, ["message_count"] = frames.Count,
                ["late_decision_phase"] = 1,
                ["proposal_count"] = prepared.Sum(body => body["proposals"]!.AsArray().Count),
                ["proposal_ids"] = new JsonArray(prepared.SelectMany(body => body["proposals"]!.AsArray().OfType<JsonObject>())
                    .Select(value => (JsonNode)value["proposal_id"]!.DeepClone()).ToArray()),
                ["book_sha256"] = snapshot.SavedBook.Sha256, ["save_sequence"] = snapshot.SavedBook.Sequence };
            if (NativeMixedActorReady) result["mixed_decision_phase"] = 1;
            return result;
        }, cancellation);

    // Native host only, under its book/writer guard. No MCP/IPC route exposes
    // this observation and no observer/captured snapshot survives the operation.
    // In particular, observing is NOT incoming admission, action or data rights.
    internal Task<IReadOnlyList<JsonObject>> ObservePersonalActorIncomingTargetsAsync(PersonalActorHandle handle,
        IReadOnlyList<JsonObject> targets, CancellationToken cancellation = default)
    {
        if (targets.Count is < 1 or > 256) throw new InvalidDataException("actor_target_capacity");
        var copied = targets.Select(value => value.DeepClone().AsObject()).ToArray();
        return WithPersonalActorStoreAsync<IReadOnlyList<JsonObject>>(registry => ObservePersonalActorIncomingTargets(registry, handle, copied), cancellation);
    }

    private IReadOnlyList<JsonObject> ObservePersonalActorIncomingTargets(PersonalSyncActorStore registry,
        PersonalActorHandle handle, IReadOnlyList<JsonObject> copied)
    {
        var admission = RequirePersonalActorAdmission(registry, handle);
        var fingerprint = registry.Status(handle)["fingerprint"]!.GetValue<string>();
        string? Current()
        {
            registry.RequireCurrent(handle);
            if (RequirePersonalActorAdmission(registry, handle) != admission) throw new InvalidOperationException("actor_source_changed");
            var peer = RequireSolePeer(admission.PeerId);
            var settings = store.SharedSettings(peer.Id, peer.PublicKey);
            if (settings is null || SharedSyncSettings.Effective(settings)["skip_deletions"]?.GetValue<bool>() != false ||
                store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != true || peer.Grants["personal_deletions_sync"]?.GetValue<bool>() != true)
                throw new InvalidOperationException("actor_deletions_not_granted");
            return CurrentActorSource(peer.Id, fingerprint);
        }
        Current();
        // One capture within the caller-held writer guard. Fresh save/source
        // witnesses are still checked at every observation boundary.
        var captured = NativeProducerBook() ?? throw new InvalidOperationException("actor_native_saved_book_unavailable");
        NativeActorBookSnapshot Snapshot()
        {
            var value = captured;
            if (NativeSavedBook() != value.SavedBook || NativeBookSource() != value.SavedBook.BookSource)
                throw new InvalidOperationException("actor_native_saved_book_changed");
            return value;
        }
        var observation = new PersonalActorIncomingLiveTargetObservation(admission.PeerId, handle.ActorId,
            () => Current() is not null, Current, Snapshot, () => admission.Connection.CurrentContentScope(admission.Scope));
        return observation.ObserveMany(handle.ActorId, copied);
    }

    private (ActorAdmission Admission, string Source, JsonObject Scope) PersonalActorTargetOriginCurrent(
        PersonalSyncActorStore registry, PersonalActorHandle handle)
    {
        var admission = RequirePersonalActorAdmission(registry, handle);
        var peer = RequireSolePeer(admission.PeerId); var settings = store.SharedSettings(peer.Id, peer.PublicKey);
        if (settings is null || SharedSyncSettings.Effective(settings)["skip_deletions"]?.GetValue<bool>() != false ||
            store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != true || peer.Grants["personal_deletions_sync"]?.GetValue<bool>() != true)
            throw new InvalidOperationException("actor_deletions_not_granted");
        var source = CurrentActorSource(peer.Id, registry.Status(handle)["fingerprint"]!.GetValue<string>())
            ?? throw new InvalidOperationException("actor_source_changed");
        if (personalSync.LoadRun(PersonalSyncActorContract.StoragePeer(handle.ActorId), handle.ActorId, Now()) is not { Expired: false } request ||
            request.Request["trigger"]?.GetValue<string>() != "manual")
            throw new InvalidOperationException("actor_target_origin_run_retired");
        return (admission, source, admission.Connection.CurrentContentScope(admission.Scope));
    }

    private static void CheckPersonalActorTargetOrigin(ActorTargetOrigin origin, string source, JsonObject scope)
    {
        if (origin.Invalid || origin.Source != source || !JsonNode.DeepEquals(origin.Scope, scope) ||
            Now() >= origin.WallDeadline || Environment.TickCount64 >= origin.MonotonicDeadline)
        {
            origin.Invalid = true;
            throw new InvalidOperationException("actor_target_origin_changed");
        }
    }

    // Called only from authenticated ReceivePersonalActorAsync, not raw registry.Put.
    private void QuarantinePersonalActorIncomingTargets(PersonalSyncActorStore registry, PersonalActorHandle handle, JsonObject wire)
    {
        var clear = registry.ValidateIncomingTargetWire(handle, wire);
        var (_, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
        if (body["proposals"]!.AsArray().OfType<JsonObject>().Any(item => item["kind"]!.GetValue<string>() is not ("note" or "task" or "attachment")))
            throw new InvalidDataException("actor_target_origin_kind");
        var (admission, source, scope) = PersonalActorTargetOriginCurrent(registry, handle);
        var origin = admission.IncomingTargetOrigin ??= new ActorTargetOrigin(source, scope);
        CheckPersonalActorTargetOrigin(origin, source, scope);
        var id = wire["message_id"]!.GetValue<string>();
        if (origin.Frames.TryGetValue(id, out var old))
        {
            if (!old.AsSpan().SequenceEqual(clear)) { origin.Invalid = true; throw new InvalidOperationException("actor_target_origin_frame_changed"); }
            return; // Exact retransmission never renews either deadline.
        }
        var count = body["proposals"]!.AsArray().Count;
        if (origin.Frames.Count >= 256 || origin.Bytes + clear.Length > 1024 * 1024 || origin.Targets + count > 256)
        { origin.Invalid = true; throw new InvalidOperationException("actor_target_origin_capacity"); }
        origin.Frames.Add(id, clear); origin.Bytes += clear.Length; origin.Targets += count;
        var after = PersonalActorTargetOriginCurrent(registry, handle);
        CheckPersonalActorTargetOrigin(origin, after.Source, after.Scope);
    }

    private IReadOnlyList<JsonObject> ReadPersonalActorIncomingTargetFrames(PersonalSyncActorStore registry, PersonalActorHandle handle)
    {
        var (admission, source, scope) = PersonalActorTargetOriginCurrent(registry, handle);
        var origin = admission.IncomingTargetOrigin ?? throw new InvalidOperationException("actor_target_origin_missing");
        CheckPersonalActorTargetOrigin(origin, source, scope);
        var sequences = new Dictionary<long, bool>(); var frames = new List<(long Sequence, JsonObject Wire)>();
        string? batch = null; var proposals = new HashSet<string>(StringComparer.Ordinal);
        var targets = new HashSet<(string, string, string)>();
        foreach (var clear in origin.Frames.Values)
        {
            var wire = JsonNode.Parse(clear)!.AsObject(); registry.ValidateIncomingTargetWire(handle, wire);
            var (_, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
            var sequence = TelefonProtocolContract.Integer(body["sequence"]); var currentBatch = body["proposal_batch_id"]!.GetValue<string>();
            if (sequences.ContainsKey(sequence) || batch is not null && batch != currentBatch)
                throw new InvalidOperationException("actor_target_origin_group");
            batch = currentBatch; sequences.Add(sequence, body["last"]!.GetValue<bool>());
            foreach (var item in body["proposals"]!.AsArray().OfType<JsonObject>())
                if (!proposals.Add(item["proposal_id"]!.GetValue<string>()) || !targets.Add((item["kind"]!.GetValue<string>(), item["parent_id"]!.GetValue<string>(), item["id"]!.GetValue<string>())))
                    throw new InvalidOperationException("actor_target_origin_group");
            frames.Add((sequence, wire));
        }
        if (frames.Count == 0 || !sequences.Keys.Order().SequenceEqual(Enumerable.Range(0, sequences.Count).Select(value => (long)value)) ||
            sequences.Any(pair => pair.Value != (pair.Key == sequences.Count - 1)))
            throw new InvalidOperationException("actor_target_origin_incomplete");
        var after = PersonalActorTargetOriginCurrent(registry, handle); CheckPersonalActorTargetOrigin(origin, after.Source, after.Scope);
        return frames.OrderBy(value => value.Sequence).Select(value => value.Wire).ToArray();
    }

    // Private native only. No MCP/IPC route, no caller-supplied frame source.
    internal Task<IReadOnlyList<JsonObject>> ReadPersonalActorIncomingTargetFramesAsync(PersonalActorHandle handle,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => ReadPersonalActorIncomingTargetFrames(registry, handle), cancellation);

    internal Task<JsonObject> ReviewPersonalActorIncomingTargetsAsync(PersonalActorHandle handle,
        string? expectedRevision = null, IReadOnlyList<JsonObject>? choices = null, CancellationToken cancellation = default)
    {
        var copied = choices?.Select(value => value.DeepClone().AsObject()).ToArray();
        return WithPersonalActorStoreAsync(registry => ReviewPersonalActorIncomingTargets(registry, handle, expectedRevision, copied), cancellation);
    }

    private JsonObject ReviewPersonalActorIncomingTargets(PersonalSyncActorStore registry, PersonalActorHandle handle,
        string? expectedRevision = null, IReadOnlyList<JsonObject>? choices = null)
    {
        if ((choices is null) != (expectedRevision is null) || expectedRevision is not null &&
            (expectedRevision.Length != 64 || expectedRevision.Any(value => value is not (>= 'a' and <= 'f' or >= '0' and <= '9'))))
            throw new InvalidDataException("actor_target_review_explicit_choices_required");
        var copied = choices?.Select(value => value.DeepClone().AsObject()).ToArray();
        var admission = PersonalActorTargetOriginCurrent(registry, handle).Admission;
        (string Source, JsonObject Scope) Current()
        {
            var current = PersonalActorTargetOriginCurrent(registry, handle);
            if (!ReferenceEquals(current.Admission, admission)) throw new InvalidOperationException("actor_source_changed");
            return (current.Source, current.Scope);
        }
        NativeBookSaveState? Saved()
        {
            Current(); var saved = NativeSavedBook();
            if (saved is null || saved.BookSource != NativeBookSource()) throw new InvalidOperationException("native_book_not_saved");
            return saved;
        }
        var review = new PersonalActorIncomingTargetChoiceReview(handle.ActorId,
            () => ReadPersonalActorIncomingTargetFrames(registry, handle),
            targets => ObservePersonalActorIncomingTargets(registry, handle, targets),
            () => Current().Source, () => Current().Scope, Saved);
        return copied is null ? review.Review() : review.DraftChoices(expectedRevision!, copied);
    }

    // Private operation-local origin/choice/source binding, NOT a native save
    // claim. Caller retains its writer guard. No MCP/IPC/wire route invokes it.
    internal Task<JsonObject> ReviewPersonalActorHistoricalRestoreAsync(PersonalActorHandle handle, string expectedRevision,
        IReadOnlyList<JsonObject> choices, CancellationToken cancellation = default)
    {
        var copied = choices.Select(value => value.DeepClone().AsObject()).ToArray();
        return WithPersonalActorStoreAsync(registry => ReviewPersonalActorHistoricalRestore(registry, handle, expectedRevision, copied), cancellation);
    }

    private JsonObject ReviewPersonalActorHistoricalRestore(PersonalSyncActorStore registry, PersonalActorHandle handle, string expectedRevision, IReadOnlyList<JsonObject> copied)
    {
            var view = ReviewPersonalActorIncomingTargets(registry, handle);
            var draft = ReviewPersonalActorIncomingTargets(registry, handle, expectedRevision, copied);
            if (draft["decisions"]!.AsArray().OfType<JsonObject>().Any(value => value["decision"]!.GetValue<string>() != "restore"))
                throw new InvalidOperationException("actor_historical_restore_target_not_ready");
            var initial = PersonalActorTargetOriginCurrent(registry, handle);
            Dictionary<string, string> Frames() => ReadPersonalActorIncomingTargetFrames(registry, handle)
                .ToDictionary(wire => wire["message_id"]!.GetValue<string>(), PersonalSyncContract.ProjectionHash, StringComparer.Ordinal);
            var original = Frames();
            var request = personalSync.LoadRun(PersonalSyncActorContract.StoragePeer(handle.ActorId), handle.ActorId, Now())
                ?? throw new InvalidOperationException("actor_target_origin_run_retired");
            var captured = NativeProducerBook() ?? throw new InvalidOperationException("actor_native_saved_book_unavailable");
            string Current()
            {
                var actual = PersonalActorTargetOriginCurrent(registry, handle);
                if (!ReferenceEquals(actual.Admission, initial.Admission) || actual.Source != initial.Source || !JsonNode.DeepEquals(actual.Scope, initial.Scope))
                    throw new InvalidOperationException("actor_source_changed");
                return actual.Source;
            }
            NativeActorBookSnapshot Snapshot()
            {
                if (NativeSavedBook() != captured.SavedBook || NativeBookSource() != captured.SavedBook.BookSource)
                    throw new InvalidOperationException("actor_native_saved_book_changed");
                return captured;
            }
            var proof = new PersonalActorHistoricalRestoreSourceObservation(initial.Admission.PeerId, handle.ActorId,
                checked((int)TelefonProtocolContract.Integer(request.Request["format"])), () => Current().Length != 0, Current, Snapshot,
                () => initial.Admission.Connection.CurrentContentScope(initial.Admission.Scope));
            var sources = proof.ObserveMany(handle.ActorId, view["targets"]!.AsArray().Select(value => value!.AsObject()).ToArray());
            var after = Frames();
            if (original.Count != after.Count || original.Any(pair => after.GetValueOrDefault(pair.Key) != pair.Value))
                throw new InvalidOperationException("actor_target_origin_frame_changed");
            Current(); Snapshot();
            var result = draft.DeepClone().AsObject();
            var sourceNodes = new JsonArray(sources.Select(value => (JsonNode)new JsonObject {
                ["target"] = value["target"]!.DeepClone(), ["source"] = value["local_restore_source"]!.DeepClone() }).ToArray());
            result["local_restore_sources"] = sourceNodes;
            result["restore_source_revision"] = PersonalSyncContract.ProjectionHash(new JsonObject { ["choice_revision"] = draft["choice_revision"]!.DeepClone(),
                ["saved_book"] = new JsonObject { ["book_source"] = captured.SavedBook.BookSource, ["sequence"] = captured.SavedBook.Sequence,
                    ["sha256"] = captured.SavedBook.Sha256 }, ["sources"] = sourceNodes.DeepClone() });
            return result;
    }

    // Native writer preparation only, no public/MCP/IPC route or document I/O.
    internal Task<JsonObject> PreparePersonalActorHistoricalRestoreSaveAsync(PersonalActorHandle handle, string expectedRevision,
        IReadOnlyList<JsonObject> choices, string candidateText, CancellationToken cancellation = default)
    {
        var copied = choices.Select(value => value.DeepClone().AsObject()).ToArray();
        return WithPersonalActorStoreAsync(registry => {
            var initial = PersonalActorTargetOriginCurrent(registry, handle); var admission = initial.Admission;
            if (admission.HistoricalSaveClaim is not null) throw new InvalidOperationException("actor_historical_save_already_prepared");
            var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
            if (personalSync.DecisionIntents(Now()).Any(value => value.PeerId == privatePeer && value.Body["run_id"]?.GetValue<string>() == handle.ActorId) ||
                admission.ProducerBodies is not null || admission.CommitPlan is not null || admission.Completion is not null)
                throw new InvalidOperationException("actor_historical_mixed_group_not_ready");
            registry.RequireHistoricalDataIdle(handle, initial.Scope);
            var reviewed = ReviewPersonalActorHistoricalRestore(registry, handle, expectedRevision, copied);
            var targets = reviewed["local_restore_sources"]!.AsArray().Select(value => value!["target"]!.DeepClone().AsObject()).ToArray();
            var request = personalSync.LoadRun(privatePeer, handle.ActorId, Now()) ?? throw new InvalidOperationException("actor_target_origin_run_retired");
            var proof = NativeHistoricalRestoreCandidateProof.Prepare(admission.PeerId, handle.ActorId, checked((int)TelefonProtocolContract.Integer(request.Request["format"])),
                targets, copied, candidateText, () => ReferenceEquals(PersonalActorTargetOriginCurrent(registry, handle).Admission, admission),
                () => PersonalActorTargetOriginCurrent(registry, handle).Source, NativeProducerBook,
                () => admission.Connection.CurrentContentScope(admission.Scope));
            var fingerprint = registry.Status(handle)["fingerprint"]!.GetValue<string>();
            var authority = CurrentActorCompletionAuthority(admission.PeerId, fingerprint) ?? throw new InvalidOperationException("actor_historical_completion_source_unavailable");
            var origin = admission.IncomingTargetOrigin ?? throw new InvalidOperationException("actor_target_origin_missing");
            var hashes = ReadPersonalActorIncomingTargetFrames(registry, handle).ToDictionary(wire => wire["message_id"]!.GetValue<string>(), PersonalSyncContract.ProjectionHash, StringComparer.Ordinal);
            var plan = new ActorHistoricalSaveClaim(proof, expectedRevision, reviewed["choice_revision"]!.GetValue<string>(), reviewed["restore_source_revision"]!.GetValue<string>(),
                new JsonArray(targets.Select(value => (JsonNode)value.DeepClone()).ToArray()), new JsonArray(copied.Select(value => (JsonNode)value.DeepClone()).ToArray()), hashes, authority);
            bool? NativeGuard(string operation, JsonObject? wire)
            {
                if (plan.Completion is { } terminal) return operation == "save" ? false : terminal.Validator(operation == "maintain" ? "read" : operation, wire);
                var confirming = operation == "confirm" && plan.ConfirmingSavedBook is not null && plan.WriterGateChecked;
                if (operation is not ("begin" or "save") && !confirming) return null;
                if (!ReferenceEquals(actorAdmissions.GetValueOrDefault(handle.ActorId), admission) || !ReferenceEquals(admission.HistoricalSaveClaim, plan) ||
                    online.GetValueOrDefault(admission.PeerId) != admission.Connection || !ReferenceEquals(admission.IncomingTargetOrigin, origin)) return false;
                var source = CurrentActorSource(admission.PeerId, fingerprint);
                if (source is null) return null;
                if (source != initial.Source) return false;
                var scope = admission.Connection.CurrentContentScope(admission.Scope);
                if (!confirming) CheckPersonalActorTargetOrigin(origin, source, scope);
                if (!JsonNode.DeepEquals(scope, initial.Scope)) return false;
                var frames = origin.Frames.Values.Select(clear => JsonNode.Parse(clear)!.AsObject()).ToArray();
                if (frames.Length != hashes.Count || frames.Any(frame => hashes.GetValueOrDefault(frame["message_id"]!.GetValue<string>()) != PersonalSyncContract.ProjectionHash(frame))) return false;
                if (!confirming) foreach (var frame in frames) registry.ValidateHistoricalTargetEnvelope(handle, frame);
                var snapshot = NativeProducerBook(); var saved = NativeSavedBook();
                if (snapshot is null || saved is null) return null;
                var contentHash = NativeBookJson.Hash(JsonNode.Parse(snapshot.Text)!.AsObject());
                if (confirming)
                    return saved == plan.ConfirmingSavedBook && saved == snapshot.SavedBook && saved.BookSource == proof.BeforeSavedBook.BookSource &&
                        saved.Sequence == proof.BeforeSavedBook.Sequence + 1 && saved.Sha256 == proof.AfterSha256 && contentHash == proof.AfterContentSha256 &&
                        CurrentActorCompletionAuthority(admission.PeerId, fingerprint) == plan.CompletionAuthority;
                return snapshot.SavedBook == proof.BeforeSavedBook && saved == snapshot.SavedBook && contentHash == proof.BeforeContentSha256;
            }
            admission.HistoricalSaveClaim = plan;
            try { registry.BeginCompletion(handle, NativeGuard); registry.CheckHistoricalSave(handle); }
            catch
            {
                admission.HistoricalSaveClaim = null;
                registry.Cancel(handle);
                throw;
            }
            return new JsonObject { ["claim_token"] = plan.Token, ["after_sha256"] = proof.AfterSha256, ["before_sequence"] = proof.BeforeSavedBook.Sequence,
                ["book_source"] = proof.BeforeSavedBook.BookSource, ["data_closed"] = true, ["book_persisted"] = false, ["phone_persisted"] = false };
        }, cancellation);
    }

    // Called under the retained native writer/source guard immediately before
    // writing exactly candidateText. Invocation is single-use, not a SaveACK.
    internal Task<JsonObject> CheckPersonalActorHistoricalRestoreSaveAsync(PersonalActorHandle handle, string claimToken, string candidateText,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => CheckPersonalActorHistoricalRestoreSave(registry, handle, claimToken, candidateText), cancellation);

    private JsonObject CheckPersonalActorHistoricalRestoreSave(PersonalSyncActorStore registry, PersonalActorHandle handle, string claimToken, string candidateText)
    {
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.HistoricalSaveClaim is not { } plan ||
            claimToken != plan.Token) throw new InvalidOperationException("actor_historical_save_claim_unavailable");
        if (plan.WriterGateChecked) throw new InvalidOperationException("actor_historical_writer_claim_already_used");
        if (candidateText.Length > 256L * 1024 * 1024 || Encoding.UTF8.GetByteCount(candidateText) > 256L * 1024 * 1024 ||
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(candidateText))).ToLowerInvariant() != plan.Proof.AfterSha256)
            throw new InvalidOperationException("actor_historical_writer_payload_changed");
        registry.CheckHistoricalSave(handle); plan.WriterGateChecked = true;
        return new JsonObject { ["writer_invocation_checked"] = true, ["book_persisted"] = false };
    }

    // Native-only writer invocation under the SAME source/owner gate as its
    // single-use precheck. Caller must also retain the native document writer
    // lock; never expose the callback through MCP/IPC or perform wire I/O here.
    internal Task<JsonObject> WritePersonalActorHistoricalRestoreSaveAsync(PersonalActorHandle handle, string claimToken, string candidateText,
        Action<string> nativeWriter, CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        ArgumentNullException.ThrowIfNull(nativeWriter);
        CheckPersonalActorHistoricalRestoreSave(registry, handle, claimToken, candidateText);
        try { nativeWriter(candidateText); }
        catch
        {
            registry.Cancel(handle); // Unknown/failed I/O never authorizes replay or local rollback.
            throw;
        }
        return ActorStatus(registry, handle); // Only Confirm can assert the saved historical receipt.
    }, cancellation);

    // Actual native SaveACK -> metadata-only exact historical receipt handoff.
    // Still private: no GUI/private-IPC writer route is enabled by this method.
    internal Task<JsonObject> ConfirmPersonalActorHistoricalRestoreSaveAsync(PersonalActorHandle handle, string claimToken,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.HistoricalSaveClaim is not { } plan || claimToken != plan.Token)
            throw new InvalidOperationException("actor_historical_save_claim_unavailable");
        if (plan.Completion is not null) { registry.ReadCompletionControls(handle); return ActorStatus(registry, handle); }
        if (!plan.WriterGateChecked) throw new InvalidOperationException("actor_historical_writer_not_invoked");
        var proof = plan.Proof; var snapshot = NativeProducerBook(); var saved = NativeSavedBook();
        if (snapshot is null || saved is null || saved != snapshot.SavedBook || saved.BookSource != proof.BeforeSavedBook.BookSource ||
            saved.Sequence != proof.BeforeSavedBook.Sequence + 1 || saved.Sha256 != proof.AfterSha256 ||
            NativeBookJson.Hash(JsonNode.Parse(snapshot.Text)!.AsObject()) != proof.AfterContentSha256)
            throw new InvalidOperationException("actor_historical_actual_save_proof_missing");
        if (!JsonNode.DeepEquals(NativeHistoricalRestoreCandidateProof.Live(JsonNode.Parse(snapshot.Text)!.AsObject()), JsonNode.Parse(proof.AfterLiveJson)))
            throw new InvalidOperationException("actor_historical_saved_live_delta_changed");
        plan.ConfirmingSavedBook = saved;
        registry.CheckHistoricalConfirm(handle);
        var manifest = admission.Connection.CurrentContentScope(admission.Scope);
        var fingerprint = registry.Status(handle)["fingerprint"]!.GetValue<string>();
        var decisions = new JsonArray(plan.Choices.OfType<JsonObject>().Select(choice => (JsonNode)new JsonObject {
            ["proposal_id"] = choice["proposal_id"]!.DeepClone(), ["decision"] = choice["decision"]!.DeepClone(), ["expected_clock"] = choice["expected_clock"]!.DeepClone() }).ToArray());
        PersonalSyncActorContract.HistoricalCompletionMembers(handle.ActorId, manifest, plan.Targets, decisions, plan.Targets);
        var queued = new List<JsonObject>();
        try
        {
            foreach (var chunk in decisions.OfType<JsonObject>().Chunk(32))
            {
                var body = new JsonObject { ["format"] = 1, ["run_id"] = handle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(chunk.Select(value => (JsonNode)value.DeepClone()).ToArray()) };
                var id = store.Enqueue(admission.PeerId, "personal_sync.deletion_decision", body, 86400000, Now(), actorRunId: handle.ActorId);
                queued.Add(store.OutboxMessage(admission.PeerId, id) ?? throw new InvalidOperationException("actor_outbox_missing"));
            }
            JsonObject? Scope()
            {
                if (CurrentActorCompletionAuthority(admission.PeerId, fingerprint) is null) return null;
                return admission.Connection.CurrentContentScope(admission.Connection.ActorSourceSnapshot()["scope"]!.AsObject());
            }
            var terminal = new PersonalActorDecisionCompletion(handle.ActorId, plan.Targets, queued,
                () => CurrentActorCompletionAuthority(admission.PeerId, fingerprint), Scope, () => NativeSavedBook(),
                () => registry.ReadCompletionControls(handle), beforeScope: manifest, nativeHistoricalTargets: plan.Targets);
            if (CurrentActorCompletionAuthority(admission.PeerId, fingerprint) != plan.CompletionAuthority)
                throw new InvalidOperationException("actor_historical_completion_source_changed");
            foreach (var identity in admission.Outbound)
            {
                var old = store.OutboxMessage(admission.PeerId, identity);
                if (old?["kind"]?.GetValue<string>() == PersonalSyncActorContract.DataKind && old["body"]?["run_id"]?.GetValue<string>() == handle.ActorId)
                    store.CompleteOutbox(admission.PeerId, identity);
            }
            plan.Completion = terminal; admission.Completion = terminal;
            admission.CompletionIds.Clear(); admission.CompletionIds.UnionWith(queued.Select(value => value["message_id"]!.GetValue<string>()));
            admission.Outbound.Clear(); admission.Outbound.UnionWith(admission.CompletionIds);
            admission.NativeAcknowledgments.Clear(); admission.CompletionDeferredControls.Clear();
            plan.SavedReceipt = saved; admission.PhonePersisted = false;
            admission.IncomingTargetOrigin?.Frames.Clear(); admission.IncomingTargetOrigin = null;
            registry.ReadCompletionControls(handle);
        }
        catch
        {
            if (plan.Completion is null) foreach (var wire in queued) store.CompleteOutbox(admission.PeerId, wire["message_id"]!.GetValue<string>());
            throw; // Never roll back or repeat an already acknowledged document save.
        }
        return ActorStatus(registry, handle);
    }, cancellation);

    internal async Task<JsonObject> StartPersonalActorAsync(PersonalActorHandle handle, CancellationToken cancellation = default)
    {
        var admission = await WithPersonalActorStoreAsync(registry => RequirePersonalActorAdmission(registry, handle, requireStartFresh: true), cancellation);
        // Authority was claimed above; lifecycle cancellation may make an in-flight write's outcome unknown.
        await admission.Connection.SendPlainAsync(admission.Start.DeepClone().AsObject());
        lock (gate)
            if (actorAdmissions.GetValueOrDefault(handle.ActorId) == admission && online.GetValueOrDefault(admission.PeerId) == admission.Connection)
                admission.StartDispatched = true;
        return new() { ["actor_id"] = handle.ActorId, ["message_id"] = admission.Start["message_id"]!.DeepClone(),
             ["dispatch_started"] = true, ["delivery_confirmed"] = false, ["persisted"] = false };
    }

    internal async Task<JsonObject> DispatchPersonalActorProposalsAsync(PersonalActorHandle handle, CancellationToken cancellation = default)
    {
        var admission = await WithPersonalActorStoreAsync(registry => {
            var value = RequirePersonalActorAdmission(registry, handle);
            if (!value.StartDispatched || value.ProducerBook is null || value.ProducerBodies is null || NativeSavedBook() != value.ProducerBook)
                throw new InvalidOperationException("actor_producer_dispatch_not_ready");
            return value;
        }, cancellation);
        var frames = await WithPersonalActorStoreAsync(registry => {
            registry.RequireCurrent(handle);
            return store.Due(admission.PeerId, Now(), transport: admission.Connection.Transport)
                .Where(item => admission.ProducerIds.Contains(item.Id)).Select(item => item.Message).ToArray();
        }, cancellation);
        var sent = 0;
        foreach (var frame in frames)
        {
            var claim = await WithPersonalActorStoreAsync(registry => {
                if (RequirePersonalActorAdmission(registry, handle) != admission || NativeSavedBook() != admission.ProducerBook)
                    throw new InvalidOperationException("actor_producer_book_changed");
                var due = store.Due(admission.PeerId, Now(), transport: admission.Connection.Transport)
                    .SingleOrDefault(item => item.Id == frame["message_id"]!.GetValue<string>());
                if (due is null || !JsonNode.DeepEquals(due.Message, frame)) return false;
                store.MarkAttempt(due.Id, due.Attempts, Now()); registry.RequireCurrent(handle);
                if (NativeSavedBook() != admission.ProducerBook) throw new InvalidOperationException("actor_producer_book_changed");
                return true;
            }, cancellation);
            if (!claim) continue;
            await admission.Connection.SendPlainAsync(frame.DeepClone().AsObject());
            await WithPersonalActorStoreAsync(registry => {
                if (RequirePersonalActorAdmission(registry, handle) != admission || NativeSavedBook() != admission.ProducerBook)
                    throw new InvalidOperationException("actor_producer_dispatch_outcome_unknown");
                return true;
            }, cancellation);
            sent++;
        }
        return new JsonObject { ["dispatch_started"] = sent != 0, ["message_count"] = sent, ["delivery_confirmed"] = false };
    }

    internal async Task<JsonObject> CancelPersonalActorAsync(PersonalActorHandle handle, CancellationToken cancellation = default)
    {
        ActorAdmission? dispatch = null;
        var result = await WithPersonalActorStoreAsync(registry => {
            var status = registry.Cancel(handle);
            if (actorAdmissions.Remove(handle.ActorId, out var value) && value.Handle == handle)
            {
                foreach (var id in value.Outbound)
                {
                    var queued = store.OutboxMessage(value.PeerId, id);
                    if (queued?["kind"]?.GetValue<string>() == PersonalSyncActorContract.DataKind && queued["body"]?["run_id"]?.GetValue<string>() == handle.ActorId)
                        store.CompleteOutbox(value.PeerId, id);
                }
                if (online.GetValueOrDefault(value.PeerId) == value.Connection &&
                    store.LoadPeers().Any(peer => peer.Id == value.PeerId && Convert.ToBase64String(peer.PublicKey) == value.PublicKey)) dispatch = value;
            }
            return status;
        }, cancellation);
        if (dispatch is not null) await dispatch.Connection.SendPlainAsync(ActorControl(PersonalSyncActorContract.CancelKind, PersonalSyncActorContract.Cancel(handle.ActorId)));
        result["cancel_dispatch_started"] = dispatch is not null;
        return result;
    }

    internal Task<JsonObject> ReadPersonalActorStagingAsync(PersonalActorHandle handle, int offset = 0, int limit = 65536,
        string expectedRevision = "", string attachmentSha256 = "", CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => ReadPersonalActorStaging(registry, handle, offset, limit, expectedRevision, attachmentSha256), cancellation);

    private JsonObject ReadPersonalActorStaging(PersonalSyncActorStore registry, PersonalActorHandle handle, int offset, int limit,
        string expectedRevision, string attachmentSha256)
    {
        if (offset < 0 || limit is < 1 or > 65536 || expectedRevision.Length != 0 &&
            !System.Text.RegularExpressions.Regex.IsMatch(expectedRevision, "^[0-9a-f]{64}$") || offset != 0 && expectedRevision.Length == 0 ||
            attachmentSha256.Length != 0 && (!System.Text.RegularExpressions.Regex.IsMatch(attachmentSha256, "^[0-9a-f]{64}$") || expectedRevision.Length == 0))
            throw new InvalidDataException("invalid_actor_staging_read");
        registry.RequireCurrent(handle);
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle)
            throw new InvalidOperationException("actor_not_started");
        var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
        var manifest = admission.Connection.CurrentContentScope(admission.Scope);
        var run = personalSync.LoadRun(privatePeer, handle.ActorId, Now());
        if (run is { Expired: true }) throw new InvalidOperationException("actor_run_expired");
        var batch = personalSync.ReadyBatches(Now()).SingleOrDefault(value => value.PeerId == privatePeer && value.RunId == handle.ActorId && !value.Reply);
        if (batch is not null && PhoneContentScope.FilterRecords(batch.Records.OfType<JsonObject>().ToArray(), manifest).Count != batch.Records.Count)
            throw new InvalidDataException("actor_record_outside_scope");
        var intents = personalSync.DecisionIntents(Now()).Where(value => value.PeerId == privatePeer && value.Body["run_id"]!.GetValue<string>() == handle.ActorId);
        var value = new JsonObject { ["content_scope"] = manifest.DeepClone(), ["request"] = run?.Request.DeepClone(),
            ["batch"] = batch is null ? null : new JsonObject { ["message_id"] = batch.PendingMessageId, ["commit_token"] = batch.CommitToken,
                ["records_hash"] = batch.RecordsHash, ["records"] = batch.Records.DeepClone() },
            ["intents"] = new JsonArray(intents.Select(item => (JsonNode)new JsonObject { ["kind"] = item.Kind, ["body"] = item.Body.DeepClone(),
                ["pending_message_id"] = item.PendingMessageId, ["commit_token"] = item.CommitToken }).ToArray()) };
        var raw = TelefonCrypto.Canonical(value);
        try
        {
            var revision = Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant();
            if (expectedRevision.Length != 0 && expectedRevision != revision) throw new InvalidOperationException("actor_staging_changed");
            JsonObject? descriptor = null;
            if (attachmentSha256.Length != 0)
            {
                descriptor = batch?.Records.OfType<JsonObject>().Where(item => item["kind"]!.GetValue<string>() == "note")
                    .SelectMany(item => (item["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
                    .FirstOrDefault(item => item["sha256"]!.GetValue<string>() == attachmentSha256)
                    ?? throw new InvalidDataException("actor_attachment_manifest_missing");
                var file = personalSync.ReadVerifiedAttachment(privatePeer, handle.ActorId, false, batch!.RecordsHash,
                    attachmentSha256, "incoming", admission.Connection.Transport, Now());
                CryptographicOperations.ZeroMemory(raw); raw = file;
            }
            if (offset > raw.Length) throw new InvalidDataException("invalid_actor_staging_offset");
            var end = Math.Min(raw.Length, (long)offset + limit);
            registry.RequireCurrent(handle);
            var result = new JsonObject { ["revision"] = revision, ["total_bytes"] = raw.Length, ["offset"] = offset,
                ["next_offset"] = end < raw.Length ? JsonValue.Create(end) : null, ["batch_ready"] = batch is not null,
                ["data_base64"] = Convert.ToBase64String(raw, offset, (int)end - offset) };
            if (descriptor is not null) { result["attachment_sha256"] = attachmentSha256; result["mime"] = descriptor["mime"]!.DeepClone(); }
            return result;
        }
        finally { CryptographicOperations.ZeroMemory(raw); }
    }

    private JsonObject ActorDeletionReview(ActorAdmission admission, string runId, JsonObject? plan)
    {
        var privatePeer = PersonalSyncActorContract.StoragePeer(runId);
        var intents = personalSync.DecisionIntents(Now()).Where(value => value.PeerId == privatePeer && value.Body["run_id"]!.GetValue<string>() == runId).ToArray();
        if (intents.Length != 0)
        {
            var peer = RequireSolePeer(admission.PeerId);
            if (Convert.ToBase64String(peer.PublicKey) != admission.PublicKey) throw new InvalidOperationException("actor_source_changed");
            var settings = store.SharedSettings(admission.PeerId, peer.PublicKey);
            if (settings is null || SharedSyncSettings.Effective(settings)["skip_deletions"]!.GetValue<bool>() ||
                store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != true || peer.Grants["personal_deletions_sync"]?.GetValue<bool>() != true)
                throw new InvalidOperationException("actor_deletions_not_authorized");
            if (plan is null) throw new InvalidOperationException("actor_deletion_review_required");
        }
        var native = new JsonArray(intents.Select(value => (JsonNode)new JsonObject { ["kind"] = value.Kind, ["message_id"] = value.PendingMessageId,
            ["commit_token"] = value.CommitToken, ["body"] = value.Body.DeepClone() }).ToArray());
        var review = PersonalSyncActorContract.DeletionReview(runId, plan, native);
        if (intents.Length != 0)
        {
            var manifest = admission.Connection.CurrentContentScope(admission.Scope);
            var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
            var targets = new JsonArray(); var decisions = new JsonArray();
            void AddProof(JsonObject body, bool outgoingDecision)
            {
                var proof = store.PersonalDecisionTargets(privatePeer, body, outgoingDecision)
                    ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
                foreach (var target in proof.OfType<JsonObject>())
                {
                    var valid = target["kind"]!.GetValue<string>() switch {
                        "note" => notes.Contains(target["id"]!.GetValue<string>()), "task" => tasks.Contains(target["id"]!.GetValue<string>()),
                        "attachment" => notes.Contains(target["parent_id"]!.GetValue<string>()), _ => false };
                    if (!valid) throw new InvalidOperationException("actor_completion_target_outside_scope");
                    targets.Add(target.DeepClone());
                }
                foreach (var decision in body["decisions"]!.AsArray()) decisions.Add(decision!.DeepClone());
            }
            foreach (var intent in intents)
                if (intent.Kind == "personal_sync.deletion_proposals")
                {
                    foreach (var proposal in intent.Body["proposals"]!.AsArray().OfType<JsonObject>())
                    {
                        var valid = proposal["kind"]!.GetValue<string>() switch {
                            "note" => notes.Contains(proposal["id"]!.GetValue<string>()), "task" => tasks.Contains(proposal["id"]!.GetValue<string>()),
                            "attachment" => notes.Contains(proposal["parent_id"]!.GetValue<string>()), _ => false };
                        if (!valid) throw new InvalidOperationException("actor_deletion_outside_scope");
                    }
                }
                else
                {
                    AddProof(intent.Body, false);
                }
            foreach (var choices in review["choices"]!.AsArray().OfType<JsonObject>().Chunk(32))
                AddProof(new JsonObject { ["format"] = 1, ["run_id"] = runId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(choices.Select(value => (JsonNode)new JsonObject {
                        ["proposal_id"] = value["proposal_id"]!.DeepClone(), ["decision"] = value["decision"]!.DeepClone(),
                        ["expected_clock"] = value["expected_clock"]!.DeepClone() }).ToArray()) }, true);
            // Validate the whole bounded/disjoint group before a GUI save plan,
            // not only after data persistence at terminal-owner creation.
            PersonalSyncActorContract.CompletionMembers(runId, manifest, targets, decisions);
        }
        return review;
    }

    private JsonObject? ActorFixedReview(ActorAdmission admission, string runId, JsonObject review)
    {
        if (admission.ProducerBodies is not { Count: > 0 } produced || review["intents"]!.AsArray().Count == 0) return null;
        if (review["intents"]!.AsArray().OfType<JsonObject>().Any(value => value["kind"]!.GetValue<string>() != "personal_sync.deletion_proposals"))
            throw new InvalidOperationException("actor_mixed_initial_decisions_not_supported");
        var before = admission.Connection.CurrentContentScope(admission.Scope);
        var choices = new JsonArray(review["choices"]!.AsArray().OfType<JsonObject>().Select(value => (JsonNode)new JsonObject {
            ["proposal_id"] = value["proposal_id"]!.DeepClone(), ["decision"] = value["decision"]!.DeepClone(), ["expected_clock"] = value["expected_clock"]!.DeepClone() }).ToArray());
        var fixedTargets = new JsonArray();
        foreach (var chunk in choices.Chunk(32))
        {
            var body = new JsonObject { ["format"] = 1, ["run_id"] = runId, ["decision_id"] = runId,
                ["decisions"] = new JsonArray(chunk.Select(value => value!.DeepClone()).ToArray()) };
            var proof = store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(runId), body, true)
                ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
            foreach (var target in proof) fixedTargets.Add(target!.DeepClone());
        }
        PersonalSyncActorContract.CompletionMembers(runId, before, fixedTargets, choices);
        var union = new JsonArray();
        foreach (var proposal in produced.SelectMany(value => value["proposals"]!.AsArray().OfType<JsonObject>()))
            union.Add(new JsonObject(new[] { "proposal_id", "kind", "id", "parent_id", "prior_hash", "clock" }
                .Select(key => new KeyValuePair<string, JsonNode?>(key, proposal[key]!.DeepClone()))));
        foreach (var target in fixedTargets) union.Add(target!.DeepClone());
        // Early identity/count checks do not pretend the late choice is known.
        var dummy = new JsonArray(union.OfType<JsonObject>().Select(value => (JsonNode)new JsonObject {
            ["proposal_id"] = value["proposal_id"]!.DeepClone(), ["decision"] = "restore", ["expected_clock"] = value["clock"]!.DeepClone() }).ToArray());
        PersonalSyncActorContract.CompletionMembers(runId, before, union, dummy);
        return new JsonObject { ["before_scope"] = before.DeepClone(), ["targets"] = fixedTargets, ["choices"] = choices };
    }

    internal Task<JsonObject> PreparePersonalActorCommitAsync(PersonalActorHandle handle, string viewRevision, string afterHash,
        CancellationToken cancellation = default, JsonObject? deletionPlan = null) => WithPersonalActorStoreAsync(registry => {
        if (!System.Text.RegularExpressions.Regex.IsMatch(viewRevision, "^[0-9a-f]{64}$") || !System.Text.RegularExpressions.Regex.IsMatch(afterHash, "^[0-9a-f]{64}$"))
            throw new InvalidDataException("invalid_actor_commit_plan");
        var view = ReadPersonalActorStaging(registry, handle, 0, 1, viewRevision, "");
        if (view["batch_ready"]!.GetValue<bool>() != true) throw new InvalidOperationException("actor_staging_incomplete");
        var admission = actorAdmissions[handle.ActorId]; var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
        var deletionReview = ActorDeletionReview(admission, handle.ActorId, deletionPlan);
        if (admission.ProducerBodies is { Count: > 0 } && deletionReview["intents"]!.AsArray().Count != 0 && !NativeMixedActorReady)
            throw new InvalidOperationException("actor_mixed_post_data_review_not_ready");
        var fixedReview = ActorFixedReview(admission, handle.ActorId, deletionReview);
        var batch = personalSync.ReadyBatches(Now()).Single(value => value.PeerId == privatePeer && value.RunId == handle.ActorId && !value.Reply);
        admission.IncomingCounts = ActorCounts(batch.Records.OfType<JsonObject>());
        admission.IncomingAttachments = batch.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).Select(value => value["sha256"]!.GetValue<string>()).Distinct().Count();
        foreach (var hash in batch.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).Select(value => value["sha256"]!.GetValue<string>()).Distinct())
            ReadPersonalActorStaging(registry, handle, 0, 1, viewRevision, hash);
        var book = NativeSavedBook() ?? throw new InvalidOperationException("native_book_not_saved");
        if (book.BookSource != NativeBookSource() || book.Sequence <= 0) throw new InvalidOperationException("actor_book_source_changed");
        var plan = admission.CommitPlan;
        if (plan is null) admission.CommitPlan = plan = new(Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), viewRevision, afterHash, book.BookSource, book.Sequence, deletionReview, fixedReview);
        else if (plan.ViewRevision != viewRevision || plan.AfterHash != afterHash || plan.BookSource != book.BookSource || !JsonNode.DeepEquals(plan.DeletionReview, deletionReview) || !JsonNode.DeepEquals(plan.FixedReview, fixedReview))
            throw new InvalidOperationException("actor_commit_plan_changed");
        registry.RequireCurrent(handle);
        return new JsonObject { ["claim_token"] = plan.Token, ["view_revision"] = plan.ViewRevision, ["after_sha256"] = plan.AfterHash, ["book_persisted"] = false };
    }, cancellation);

    internal Task<JsonObject> CommitPersonalActorAsync(PersonalActorHandle handle, string claimToken, CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => {
            registry.RequireCurrent(handle);
            if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.CommitPlan is not { } plan || plan.Token != claimToken)
                throw new InvalidOperationException("actor_commit_plan_unavailable");
            if (admission.SaveReceipt is null)
            {
                var book = NativeSavedBook() ?? throw new InvalidOperationException("native_book_not_saved");
                if (book.BookSource != plan.BookSource || book.BookSource != NativeBookSource() || book.Sequence <= plan.BeforeSequence || book.Sha256 != plan.AfterHash)
                    throw new InvalidOperationException("actor_save_proof_missing");
                ReadPersonalActorStaging(registry, handle, 0, 1, plan.ViewRevision, "");
                var review = ActorDeletionReview(admission, handle.ActorId, plan.DeletionReview);
                if (!JsonNode.DeepEquals(ActorFixedReview(admission, handle.ActorId, review), plan.FixedReview)) throw new InvalidOperationException("actor_fixed_review_changed");
                var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
                var batch = personalSync.ReadyBatches(Now()).Single(value => value.PeerId == privatePeer && value.RunId == handle.ActorId && !value.Reply);
                var intents = review["intents"]!.AsArray().OfType<JsonObject>().Select(value => (value["message_id"]!.GetValue<string>(), value["commit_token"]!.GetValue<string>())).ToArray();
                if (!personalSync.CommitBatch(privatePeer, batch.PendingMessageId, batch.CommitToken, Now(), out _, intents))
                    throw new InvalidOperationException("actor_core_commit_failed");
                registry.RequireCurrent(handle); admission.SaveReceipt = book;
            }
            return new JsonObject { ["book_persisted"] = true, ["core_committed"] = true, ["phone_persisted"] = false,
                ["save_sequence"] = admission.SaveReceipt.Sequence, ["book_sha256"] = admission.SaveReceipt.Sha256 };
        }, cancellation);

    internal Task<JsonObject> QueuePersonalActorReplyAsync(PersonalActorHandle handle, string claimToken, JsonArray batchNodes, JsonArray sourceNodes,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        registry.RequireCurrent(handle);
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.SaveReceipt is not { } receipt ||
            admission.CommitPlan?.Token != claimToken) throw new InvalidOperationException("actor_reply_requires_commit");
        var book = NativeSavedBook() ?? throw new InvalidOperationException("native_book_not_saved");
        if (book.BookSource != receipt.BookSource || book.BookSource != NativeBookSource() || book.Sequence < receipt.Sequence || book.Sha256 != receipt.Sha256)
            throw new InvalidOperationException("actor_saved_reply_changed");
        var batches = batchNodes.OfType<JsonObject>().ToArray();
        if (batches.Length != batchNodes.Count || batches.Length is < 1 or > 4096) throw new InvalidDataException("invalid_actor_reply_batches");
        var request = personalSync.LoadRun(PersonalSyncActorContract.StoragePeer(handle.ActorId), handle.ActorId, Now())
            ?? throw new InvalidDataException("actor_request_missing");
        for (var index = 0; index < batches.Length; index++)
        {
            var body = batches[index]; PersonalSyncContract.ValidateBody("personal_sync.batch", body);
            if (body["run_id"]!.GetValue<string>() != handle.ActorId || body["format"]!.GetValue<int>() != request.Request["format"]!.GetValue<int>() || !body["reply"]!.GetValue<bool>() ||
                body["sequence"]!.GetValue<int>() != index || body["last"]!.GetValue<bool>() != (index + 1 == batches.Length))
                throw new InvalidDataException("inconsistent_actor_reply");
        }
        var records = new JsonArray(batches.SelectMany(body => body["records"]!.AsArray()).Select(value => value!.DeepClone()).ToArray());
        var recordsHash = PersonalSyncContract.RecordsHash(records);
        if (records.Count > 100000 || batches.Any(body => body["records_hash"]!.GetValue<string>() != recordsHash) ||
            PhoneContentScope.FilterRecords(records.OfType<JsonObject>().ToArray(), admission.Connection.CurrentContentScope(admission.Scope)).Count != records.Count)
            throw new InvalidDataException("actor_reply_outside_scope_or_hash");
        var descriptorGroups = records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).GroupBy(value => value["sha256"]!.GetValue<string>())
            .ToArray();
        foreach (var group in descriptorGroups)
            if (group.Any(value => !JsonNode.DeepEquals(value["size"], group.First()["size"]) || !JsonNode.DeepEquals(value["mime"], group.First()["mime"])))
                throw new InvalidDataException("conflicting_actor_reply_manifest");
        var descriptors = descriptorGroups.ToDictionary(group => group.Key, group => group.First(), StringComparer.Ordinal);
        if (descriptors.Count > 256 || sourceNodes.Count != descriptors.Count || descriptors.Values.Sum(value => TelefonProtocolContract.Integer(value["size"])) > 50L * 1024 * 1024)
            throw new InvalidDataException("actor_reply_capacity_or_sources");
        var decoded = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        try
        {
            foreach (var source in sourceNodes.OfType<JsonObject>())
            {
                var hash = source["sha256"]!.GetValue<string>();
                var file = PersonalSyncContract.DecodeDataUrl(source["data"]!.GetValue<string>());
                if (!descriptors.TryGetValue(hash, out var descriptor) || file.Mime != descriptor["mime"]!.GetValue<string>() ||
                    file.Data.LongLength != TelefonProtocolContract.Integer(descriptor["size"]) || Convert.ToHexString(SHA256.HashData(file.Data)).ToLowerInvariant() != hash ||
                    !decoded.TryAdd(hash, file.Data)) { CryptographicOperations.ZeroMemory(file.Data); throw new InvalidDataException("actor_reply_source_changed"); }
            }
            if (decoded.Count != sourceNodes.Count || !decoded.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(descriptors.Keys)) throw new InvalidDataException("incomplete_actor_reply_sources");
            var identity = Convert.ToHexString(SHA256.HashData(TelefonCrypto.Canonical(batchNodes))).ToLowerInvariant();
            if (admission.ReplyIdentity.Length != 0 && admission.ReplyIdentity != identity) throw new InvalidOperationException("actor_reply_changed");
            if (admission.ReplyCount == 0)
            {
                if (admission.ReplyIdentity.Length != 0) throw new InvalidOperationException("actor_reply_outcome_unknown");
                if (admission.Outbound.Count + batches.Length > 4096) throw new InvalidOperationException("actor_capacity");
                admission.ReplyIdentity = identity;
                var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
                var run = personalSync.LoadRun(privatePeer, handle.ActorId, Now()) ?? throw new InvalidOperationException("actor_run_expired");
                foreach (var (hash, data) in decoded)
                    personalSync.StageAttachment(privatePeer, handle.ActorId, true, recordsHash, descriptors[hash], "outgoing", run.Policy, run.ExpiresMs,
                        data.Chunk(PersonalSyncContract.ChunkRaw).Select((bytes, index) => (index, bytes)));
                PersonalSyncStagedBatch? staged = null;
                foreach (var body in batches)
                {
                    var id = store.Enqueue(admission.PeerId, "personal_sync.batch", body, 86400000, Now(), actorRunId: handle.ActorId);
                    var wire = store.OutboxMessage(admission.PeerId, id) ?? throw new InvalidOperationException("actor_outbox_missing");
                    staged = personalSync.StageBatch(privatePeer, PersonalSyncActorContract.SemanticMessage(wire), admission.Connection.Transport, Now());
                    admission.Outbound.Add(id); admission.ReplyIds.Add(id);
                }
                if (staged is null) throw new InvalidOperationException("actor_reply_staging_incomplete");
                admission.ReplyCount = batches.Length;
            }
            registry.RequireCurrent(handle);
            return new JsonObject { ["reply_queued"] = true, ["message_count"] = admission.ReplyCount, ["book_persisted"] = true, ["phone_persisted"] = false, ["delivery_confirmed"] = false };
        }
        finally { foreach (var data in decoded.Values) CryptographicOperations.ZeroMemory(data); }
    }, cancellation);

    private static JsonObject ActorCounts(IEnumerable<JsonObject> values)
    {
        var records = values.ToArray();
        return new() { ["notes"] = records.Count(value => value["kind"]!.GetValue<string>() == "note"),
            ["tasks"] = records.Count(value => value["kind"]!.GetValue<string>() == "task"),
            ["notebooks"] = records.Count(value => value["kind"]!.GetValue<string>() == "notebook") };
    }

    internal Task<JsonObject> BeginPersonalActorCompletionAsync(PersonalActorHandle handle, string claimToken,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle ||
            admission.CommitPlan is not { } plan || plan.Token != claimToken) throw new InvalidOperationException("actor_completion_claim_unavailable");
        BeginPersonalActorCompletion(registry, admission);
        return ActorStatus(registry, handle);
    }, cancellation);

    internal async Task<JsonObject> AdvancePersonalActorCompletionAsync(PersonalActorHandle handle, CancellationToken cancellation = default)
    {
        var connection = await WithPersonalActorStoreAsync(registry => {
            if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.Completion is null)
                throw new InvalidOperationException("actor_completion_not_ready");
            registry.Status(handle); return admission.Connection;
        }, cancellation);
        await PumpPersonalActorAsync(connection); // I/O stays outside owner/store guards.
        return await PersonalActorStatusAsync(handle, cancellation);
    }

    internal static void RequireActorProducerDecisionSet(IReadOnlyList<JsonObject>? prepared, IEnumerable<JsonObject> incoming)
    {
        var expected = (prepared ?? []).SelectMany(body => body["proposals"]!.AsArray().OfType<JsonObject>())
            .ToDictionary(value => value["proposal_id"]!.GetValue<string>(), value => value["clock"], StringComparer.Ordinal);
        if (expected.Count == 0) return; // Preserve non-producer legacy review ownership.
        var received = new HashSet<string>(StringComparer.Ordinal);
        foreach (var body in incoming)
        {
            PersonalSyncContract.ValidateBody("personal_sync.deletion_decision", body);
            foreach (var decision in body["decisions"]!.AsArray().OfType<JsonObject>())
            {
                var id = decision["proposal_id"]!.GetValue<string>();
                if (!expected.TryGetValue(id, out var clock) || !received.Add(id) || !JsonNode.DeepEquals(clock, decision["expected_clock"]))
                    throw new InvalidOperationException("actor_producer_decision_set_changed");
            }
        }
        if (!received.SetEquals(expected.Keys)) throw new InvalidOperationException("actor_producer_decisions_incomplete");
    }

    private void BeginPersonalActorCompletion(PersonalSyncActorStore registry, ActorAdmission admission)
    {
        var handle = admission.Handle;
        if (admission.Completion is not null) { registry.ReadCompletionControls(handle); return; }
        registry.RequireCurrent(handle);
        var plan = admission.CommitPlan ?? throw new InvalidOperationException("actor_completion_claim_unavailable");
        var choices = plan.DeletionReview["choices"]!.AsArray().OfType<JsonObject>().ToArray();
        var incoming = plan.DeletionReview["intents"]!.AsArray().OfType<JsonObject>()
            .Where(value => value["kind"]!.GetValue<string>() == "personal_sync.deletion_decision").ToArray();
        if (admission.SaveReceipt is not { } receipt || !admission.PhoneDataPersisted || choices.Length + incoming.Length == 0)
            throw new InvalidOperationException("actor_completion_not_ready");
        var saved = NativeSavedBook() ?? throw new InvalidOperationException("native_book_not_saved");
        if (saved != receipt || saved.BookSource != NativeBookSource()) throw new InvalidOperationException("actor_saved_completion_changed");
        var frames = new List<JsonObject>(); var queuedFrames = new List<JsonObject>(); var ownAcks = new List<JsonObject>(); var targets = new JsonArray();
        var incomingBodies = new List<JsonObject>();
        var fingerprint = registry.Status(handle)["fingerprint"]!.GetValue<string>();
        try
        {
            // Read the actual protected received frame while data ownership is
            // still active; review references alone contain no target authority.
            var manifest = admission.Connection.CurrentContentScope(admission.Scope);
            foreach (var reference in incoming)
            {
                var original = registry.Read(handle, reference["message_id"]!.GetValue<string>());
                var (kind, body) = PersonalSyncActorContract.Unwrap(original["body"]!.AsObject());
                if (kind == PhoneContentScope.DataKind) (kind, body) = PhoneContentScope.Unwrap(body, manifest);
                if (kind != "personal_sync.deletion_decision" || body["run_id"]!.GetValue<string>() != handle.ActorId)
                    throw new InvalidOperationException("actor_completion_decision_envelope_changed");
                incomingBodies.Add(body);
                var native = store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(handle.ActorId), body, false)
                    ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
                foreach (var target in native.OfType<JsonObject>())
                {
                    var targetKind = target["kind"]!.GetValue<string>();
                    var memberKind = targetKind == "task" ? "tasks" : "notes";
                    var member = target[targetKind == "attachment" ? "parent_id" : "id"]!.GetValue<string>();
                    if (!manifest["members"]![memberKind]!.AsArray().Any(value => value!.GetValue<string>() == member))
                        throw new InvalidOperationException("actor_completion_target_outside_scope");
                    targets.Add(target.DeepClone());
                }
                var semantic = original.DeepClone().AsObject(); semantic["kind"] = kind; semantic["body"] = body;
                frames.Add(PersonalSyncActorContract.WireMessage(semantic, handle.ActorId)); // Reference only, never queued/sent.
                ownAcks.Add(ActorControl(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(handle.ActorId, original["message_id"]!.GetValue<string>())));
            }
            RequireActorProducerDecisionSet(admission.ProducerBodies, incomingBodies);
            foreach (var chunk in choices.Chunk(32))
            {
                if (admission.Outbound.Count + frames.Count >= 4096) throw new InvalidOperationException("actor_capacity");
                var body = new JsonObject { ["format"] = 1, ["run_id"] = handle.ActorId, ["decision_id"] = Guid.NewGuid().ToString("D"),
                    ["decisions"] = new JsonArray(chunk.Select(value => (JsonNode)new JsonObject {
                        ["proposal_id"] = value["proposal_id"]!.DeepClone(), ["decision"] = value["decision"]!.DeepClone(),
                        ["expected_clock"] = value["expected_clock"]!.DeepClone() }).ToArray()) };
                var native = store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(handle.ActorId), body, true)
                    ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
                foreach (var target in native) targets.Add(target!.DeepClone());
                var id = store.Enqueue(admission.PeerId, "personal_sync.deletion_decision", body, 86400000, Now(), actorRunId: handle.ActorId);
                var queued = store.OutboxMessage(admission.PeerId, id) ?? throw new InvalidOperationException("actor_outbox_missing");
                queuedFrames.Add(queued); frames.Add(queued);
            }
            JsonObject? Scope()
            {
                if (CurrentActorCompletionAuthority(admission.PeerId, fingerprint) is null) return null;
                return admission.Connection.CurrentContentScope(admission.Connection.ActorSourceSnapshot()["scope"]!.AsObject());
            }
            var completion = new PersonalActorDecisionCompletion(handle.ActorId, targets, frames,
                () => CurrentActorCompletionAuthority(admission.PeerId, fingerprint), Scope, () => NativeSavedBook(),
                () => registry.ReadCompletionControls(handle), nativeSentAcknowledgments: ownAcks);
            registry.BeginCompletion(handle, completion.Validator);
            admission.Completion = completion;
            admission.CompletionIds.UnionWith(queuedFrames.Select(value => value["message_id"]!.GetValue<string>()));
            admission.Outbound.UnionWith(admission.CompletionIds);
            foreach (var ack in ownAcks) admission.NativeAcknowledgments.Add(ack["message_id"]!.GetValue<string>(), ack);
            admission.PhonePersisted = false;
        }
        catch
        {
            foreach (var frame in queuedFrames) store.CompleteOutbox(admission.PeerId, frame["message_id"]!.GetValue<string>());
            throw;
        }
    }

    private JsonObject ActorStatus(PersonalSyncActorStore registry, PersonalActorHandle handle)
    {
        var result = registry.Status(handle);
        if (actorAdmissions.TryGetValue(handle.ActorId, out var admission) && admission.Handle == handle)
        {
            result["book_persisted"] = admission.SaveReceipt is not null; result["reply_queued"] = admission.ReplyCount != 0;
            result["deletion_book_persisted"] = admission.LateSaveReceipt is not null;
            result["phone_data_persisted"] = admission.PhoneDataPersisted;
            result["phone_persisted"] = admission.PhonePersisted; result["completion_report_queued"] = admission.CompletionReportId.Length != 0;
            if (admission.HistoricalSaveClaim is { } historical) result["historical_book_persisted"] = historical.SavedReceipt is not null;
            if (admission.Completion is not null) result["deletion_completion"] = admission.Completion.Summary();
        }
        return result;
    }

    internal Task<JsonObject> PersonalActorStatusAsync(PersonalActorHandle handle, CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => {
            return ActorStatus(registry, handle);
        }, cancellation);

    internal Task<JsonObject> ReadPersonalActorLateReviewAsync(PersonalActorHandle handle, int offset = 0, int limit = 65536,
        string expectedRevision = "", CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => ReadPersonalActorLateReview(registry, handle, offset, limit, expectedRevision), cancellation);

    private JsonObject ReadPersonalActorLateReview(PersonalSyncActorStore registry, PersonalActorHandle handle, int offset, int limit, string expectedRevision)
    {
        if (offset < 0 || limit is < 1 or > 65536 || expectedRevision.Length != 0 && !System.Text.RegularExpressions.Regex.IsMatch(expectedRevision, "\\A[a-f0-9]{64}\\z") ||
            offset != 0 && expectedRevision.Length == 0) throw new InvalidDataException("invalid_actor_late_review_page");
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle || admission.ReportOwner is not { } waiting || admission.Completion is not null)
            throw new InvalidOperationException("actor_late_review_owner_unavailable");
        var controls = registry.ReadCompletionControls(handle); var targets = waiting.NativeTargets;
        if (!admission.PhoneDataPersisted) return new JsonObject { ["review_ready"] = false, ["expected_proposals"] = targets.Count };
        var incoming = controls.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind)
            .Select(value => PersonalSyncActorContract.Unwrap(value["body"]!.AsObject()).Body).ToArray();
        try { RequireActorProducerDecisionSet(admission.ProducerBodies, incoming); }
        catch (InvalidOperationException error) when (error.Message == "actor_producer_decisions_incomplete")
        { return new JsonObject { ["review_ready"] = false, ["expected_proposals"] = targets.Count }; }
        JsonObject? CurrentScope() => admission.Connection.CurrentContentScope(admission.Connection.ActorSourceSnapshot()["scope"]!.AsObject());
        var review = waiting.BeginReview(CurrentScope, () => NativeSavedBook()); var view = review.Review();
        var projection = new JsonObject { ["targets"] = targets, ["decisions"] = view["decisions"]!.DeepClone(),
            ["decision_message_ids"] = new JsonArray(view["frame_hashes"]!.AsObject().Select(pair => pair.Key).OrderBy(value => value, StringComparer.Ordinal).Select(value => (JsonNode)JsonValue.Create(value)!).ToArray()),
            ["content_scope"] = view["scope"]!.DeepClone(), ["review_revision"] = view["revision"]!.DeepClone(),
            ["data_saved_book"] = new JsonObject { ["book_source"] = waiting.DataSavedBook.BookSource, ["sequence"] = waiting.DataSavedBook.Sequence, ["sha256"] = waiting.DataSavedBook.Sha256 } };
        if (waiting.NativeFixedTargets.Count != 0)
        {
            projection["fixed_targets"] = view["fixed_targets"]!.DeepClone();
            projection["fixed_decisions"] = view["fixed_decisions"]!.DeepClone();
            projection["fixed_decision_message_ids"] = new JsonArray(view["fixed_frame_hashes"]!.AsObject().Select(pair => pair.Key)
                .OrderBy(value => value, StringComparer.Ordinal).Select(value => (JsonNode)JsonValue.Create(value)!).ToArray());
        }
        var raw = TelefonCrypto.Canonical(projection);
        try
        {
            if (raw.Length > 4 * 1024 * 1024) throw new InvalidOperationException("actor_late_review_capacity");
            var revision = Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant();
            if (expectedRevision.Length != 0 && expectedRevision != revision || offset > raw.Length) throw new InvalidOperationException("actor_late_review_revision_changed");
            registry.ReadCompletionControls(handle);
            var count = Math.Min(limit, raw.Length - offset); var next = offset + count;
            return new JsonObject { ["review_ready"] = true, ["expected_proposals"] = targets.Count, ["revision"] = revision,
                ["review_revision"] = view["revision"]!.DeepClone(), ["total_bytes"] = raw.Length, ["offset"] = offset,
                ["next_offset"] = next < raw.Length ? JsonValue.Create(next) : null, ["data_base64"] = Convert.ToBase64String(raw, offset, count),
                ["deletion_book_persisted"] = view["book_persisted"]!.DeepClone(), ["phone_persisted"] = false };
        }
        finally { CryptographicOperations.ZeroMemory(raw); }
    }

    internal Task<JsonObject> PreparePersonalActorLateSaveAsync(PersonalActorHandle handle, string expectedRevision, string afterSha256,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        var page = ReadPersonalActorLateReview(registry, handle, 0, 1, "");
        if (!page["review_ready"]!.GetValue<bool>()) throw new InvalidOperationException("actor_producer_decisions_incomplete");
        var admission = actorAdmissions[handle.ActorId];
        var claim = admission.ReportOwner!.ActiveReview!.PrepareSave(expectedRevision, afterSha256);
        admission.LateClaimToken = claim["claim_token"]!.GetValue<string>();
        claim["deletion_book_persisted"] = claim["book_persisted"]!.DeepClone(); claim["phone_persisted"] = false;
        return claim;
    }, cancellation);

    internal Task<JsonObject> ConfirmPersonalActorLateSaveAsync(PersonalActorHandle handle, string claimToken,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        if (!actorAdmissions.TryGetValue(handle.ActorId, out var admission) || admission.Handle != handle ||
            !System.Text.RegularExpressions.Regex.IsMatch(claimToken, "\\A[a-f0-9]{64}\\z") || admission.LateClaimToken.Length != 64 ||
            !CryptographicOperations.FixedTimeEquals(Convert.FromHexString(claimToken), Convert.FromHexString(admission.LateClaimToken)))
            throw new InvalidOperationException("actor_review_save_claim_unavailable");
        if (admission.ReportOwner is not { } waiting || waiting.ActiveReview is null) throw new InvalidOperationException("actor_late_review_owner_unavailable");
        JsonObject Receipt() => new() { ["deletion_book_persisted"] = true, ["completion_started"] = admission.Completion is not null,
            ["phone_persisted"] = admission.PhonePersisted, ["book_sha256"] = admission.LateSaveReceipt!.Sha256, ["save_sequence"] = admission.LateSaveReceipt.Sequence };
        if (admission.Completion is not null) { registry.ReadCompletionControls(handle); return Receipt(); }
        ReadPersonalActorLateReview(registry, handle, 0, 1, "");
        waiting.ActiveReview.ConfirmSaved(claimToken);
        admission.LateSaveReceipt = waiting.ActiveReview.SavedBook ?? throw new InvalidOperationException("actor_review_save_proof_missing");
        if (admission.LateCompletion is null)
        {
            var frames = registry.ReadCompletionControls(handle).OfType<JsonObject>()
                .Where(value => value["kind"]!.GetValue<string>() == PersonalSyncActorContract.DataKind).ToArray();
            var targets = new JsonArray();
            foreach (var wire in frames)
            {
                var (kind, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
                if (kind != "personal_sync.deletion_decision") throw new InvalidOperationException("actor_completion_decision_envelope_changed");
                var proof = store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(handle.ActorId), body, false)
                    ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
                foreach (var target in proof) targets.Add(target!.DeepClone());
            }
            var expected = waiting.NativeTargets.OfType<JsonObject>().ToDictionary(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal);
            if (targets.Count != expected.Count || targets.OfType<JsonObject>().Any(value =>
                !expected.TryGetValue(value["proposal_id"]!.GetValue<string>(), out var original) || !JsonNode.DeepEquals(value, original)))
                throw new InvalidOperationException("actor_completion_target_proof_changed");
            var fixedFrames = waiting.FixedDecisionFrames;
            var fixedTargets = new JsonArray();
            foreach (var wire in fixedFrames)
            {
                var (kind, body) = PersonalSyncActorContract.Unwrap(wire["body"]!.AsObject());
                if (kind != "personal_sync.deletion_decision") throw new InvalidOperationException("actor_completion_decision_envelope_changed");
                var proof = store.PersonalDecisionTargets(PersonalSyncActorContract.StoragePeer(handle.ActorId), body, true)
                    ?? throw new InvalidOperationException("actor_completion_target_proof_missing");
                foreach (var target in proof) fixedTargets.Add(target!.DeepClone());
            }
            var fixedExpected = waiting.NativeFixedTargets.OfType<JsonObject>().ToDictionary(value => value["proposal_id"]!.GetValue<string>(), StringComparer.Ordinal);
            if (fixedTargets.Count != fixedExpected.Count || fixedTargets.OfType<JsonObject>().Any(value =>
                !fixedExpected.TryGetValue(value["proposal_id"]!.GetValue<string>(), out var original) || !JsonNode.DeepEquals(value, original)))
                throw new InvalidOperationException("actor_completion_target_proof_changed");
            foreach (var target in fixedTargets) targets.Add(target!.DeepClone());
            var acknowledgments = frames.Select(wire => ActorControl(PersonalSyncActorContract.AckKind,
                PersonalSyncActorContract.Ack(handle.ActorId, wire["message_id"]!.GetValue<string>()))).ToArray();
            var fingerprint = registry.Status(handle)["fingerprint"]!.GetValue<string>();
            admission.LateCompletion = new PersonalActorDecisionCompletion(handle.ActorId, targets, frames.Concat(fixedFrames).ToArray(),
                () => CurrentActorCompletionAuthority(admission.PeerId, fingerprint),
                () => admission.Connection.CurrentContentScope(admission.Connection.ActorSourceSnapshot()["scope"]!.AsObject()),
                () => NativeSavedBook(), () => registry.ReadCompletionControls(handle), nativeSentAcknowledgments: acknowledgments, beforeScope: waiting.OriginalScope);
            admission.LateOwnAcknowledgments = acknowledgments;
        }
        // Import original protected peer receipts under the old current review
        // owner AND the independently pinned final scope/separate late SaveACK.
        // No fresh headers, reinsertion or initial choice mutation is involved.
        foreach (var wire in registry.ReadCompletionControls(handle).OfType<JsonObject>())
            if (wire["kind"]!.GetValue<string>() == PersonalSyncActorContract.AckKind && waiting.IsFixedDecisionFrame(wire["body"]!["message_id"]!.GetValue<string>()))
                admission.LateCompletion.RecordPersisted(wire);
        registry.PromoteDecisionReview(handle, waiting.Validator, admission.LateCompletion.Validator);
        admission.Completion = admission.LateCompletion;
        admission.CompletionIds.Clear(); // Received original decisions are references, never outgoing data.
        foreach (var wire in waiting.FixedDecisionFrames) admission.CompletionIds.Add(wire["message_id"]!.GetValue<string>());
        foreach (var ack in admission.LateOwnAcknowledgments) admission.NativeAcknowledgments.Add(ack["message_id"]!.GetValue<string>(), ack);
        admission.PhonePersisted = false;
        return Receipt();
    }, cancellation);

    private void QueueActorCompletionReport(PersonalSyncActorStore registry, ActorAdmission admission)
    {
        if (admission.SaveReceipt is null || admission.ReplyCount == 0 || admission.CompletionReportId.Length != 0 ||
            admission.ReplyIds.Any(id => store.OutboxMessage(admission.PeerId, id) is not null)) return;
        var run = admission.Handle.ActorId; var privatePeer = PersonalSyncActorContract.StoragePeer(run);
        var batch = personalSync.ReadyBatches(Now()).SingleOrDefault(value => value.PeerId == privatePeer && value.RunId == run && value.Reply);
        if (batch is null) return;
        var files = batch.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).GroupBy(value => value["sha256"]!.GetValue<string>()).Select(group => group.First()).ToArray();
        if (files.Any(value => !personalSync.OutgoingAttachmentComplete(privatePeer, run, true, batch.RecordsHash, value["sha256"]!.GetValue<string>(), Now()))) return;
        var fixedReview = admission.CommitPlan?.FixedReview;
        IReadOnlyList<JsonObject> fixedFrames = [];
        if (fixedReview is not null)
        {
            var fingerprint = registry.Status(admission.Handle)["fingerprint"]!.GetValue<string>();
            string? Source() { registry.RequireCurrent(admission.Handle); return CurrentActorSource(admission.PeerId, fingerprint); }
            var source = Source() ?? throw new InvalidOperationException("actor_source_changed");
            fixedFrames = store.QueueActorFixedDecisions(admission.PeerId, run, fixedReview["choices"]!.AsArray().OfType<JsonObject>().ToArray(),
                source, admission.SaveReceipt, Source, () => admission.SaveReceipt);
            admission.FixedFrames = fixedFrames; // Retain original IDs across report/handoff SQL failure, not yet dispatchable.
        }
        if (admission.Outbound.Count + fixedFrames.Count >= 4096) throw new InvalidOperationException("actor_capacity");
        var started = TelefonProtocolContract.Integer(admission.Start["created_ms"]);
        var report = new JsonObject { ["format"] = batch.Format, ["run_id"] = run, ["state"] = "complete", ["trigger"] = "manual", ["transport"] = admission.Connection.Transport,
            ["sent"] = ActorCounts(batch.Records.OfType<JsonObject>()), ["received"] = admission.IncomingCounts.DeepClone(), ["conflicts"] = 0,
            ["attachments_omitted"] = 0, ["oversized_skipped"] = 0, ["started_ms"] = started, ["finished_ms"] = Math.Max(started, Now()), ["error"] = "none",
            ["attachments"] = new JsonObject { ["declared"] = files.Length, ["requested"] = files.Length, ["sent"] = files.Length,
                ["received"] = admission.IncomingAttachments, ["reused"] = 0, ["preserved"] = files.Length, ["failed"] = 0,
                ["bytes"] = files.Sum(value => TelefonProtocolContract.Integer(value["size"])) },
            ["deletions"] = new JsonObject { ["pending"] = 0, ["deleted"] = 0, ["restored"] = 0, ["conflicts"] = 0, ["blocked"] = 0,
                ["trash"] = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0, ["attachments"] = 0 } } };
        var id = store.Enqueue(admission.PeerId, "personal_sync.report", report, 86400000, Now(), actorRunId: run);
        try
        {
            if (admission.ProducerBodies is { Count: > 0 } prepared)
            {
                if (admission.CommitPlan!.DeletionReview["intents"]!.AsArray().Count != 0 && fixedReview is null)
                    throw new InvalidOperationException("actor_mixed_post_data_review_not_ready");
                var fingerprint = registry.Status(admission.Handle)["fingerprint"]!.GetValue<string>();
                var targets = new JsonArray();
                foreach (var proposal in prepared.SelectMany(value => value["proposals"]!.AsArray().OfType<JsonObject>()))
                {
                    var target = new JsonObject();
                    foreach (var key in new[] { "proposal_id", "kind", "id", "parent_id", "prior_hash", "clock" }) target[key] = proposal[key]!.DeepClone();
                    targets.Add(target);
                }
                var queued = store.OutboxMessage(admission.PeerId, id) ?? throw new InvalidOperationException("actor_outbox_missing");
                var waiting = new PersonalActorReportOwner(run, targets, fixedReview?["before_scope"]?.AsObject() ?? admission.Connection.CurrentContentScope(admission.Scope), queued, admission.SaveReceipt,
                    () => CurrentActorCompletionAuthority(admission.PeerId, fingerprint), () => registry.ReadCompletionControls(admission.Handle), admission.ProducerFrames,
                    nativeFixedTargets: fixedReview?["targets"]?.AsArray(), fixedDecisionFrames: fixedFrames);
                registry.BeginDecisionReview(admission.Handle, waiting.Validator);
                admission.ReportOwner = waiting;
                foreach (var wire in fixedFrames) admission.Outbound.Add(wire["message_id"]!.GetValue<string>());
            }
            else registry.RequireCurrent(admission.Handle);
        }
        catch { store.CompleteOutbox(admission.PeerId, id); throw; }
        admission.CompletionReportId = id; admission.Outbound.Add(id);
    }

    private void PersistPersonalActorPeerAcknowledgment(PersonalSyncActorStore registry, ActorAdmission admission, JsonObject message)
    {
        var completion = admission.Completion ?? throw new InvalidOperationException("actor_completion_not_ready");
        registry.PutCompletionControl(admission.Handle, message);
        completion.RecordPersisted(message);
        var body = message["body"]!.AsObject(); var state = body["status"]!.GetValue<string>();
        if (state is "accepted" or "duplicate") store.CompleteOutbox(admission.PeerId, body["message_id"]!.GetValue<string>());
        else if (body["error"]!.GetValue<string>() != "temporary_failure")
        {
            registry.Cancel(admission.Handle);
            foreach (var pendingId in admission.Outbound) store.CompleteOutbox(admission.PeerId, pendingId);
            return;
        }
        var summary = completion.Summary();
        if (summary["saved"]!.GetValue<int>() == summary["expected"]!.GetValue<int>())
        { registry.FinishCompletion(admission.Handle); admission.PhonePersisted = true;
            store.RememberPersonalSuccess(admission.PeerId, admission.PublicKey, admission.Handle.ActorId, "manual", Now()); }
    }

    private static bool DeferPersonalActorPeerAcknowledgment(ActorAdmission admission, JsonObject message)
    {
        if (admission.Completion is not { } completion || completion.Validator("put", message) != true) return false;
        // This is bounded UNTRUSTED pending metadata, not a protected receipt.
        // Exact identity/authority/save/scope/TTL checks run again on Advance.
        var id = message["message_id"]!.GetValue<string>(); var deferred = admission.CompletionDeferredControls;
        if (deferred.TryGetValue(id, out var previous) && !JsonNode.DeepEquals(previous, message))
            throw new InvalidDataException("actor_frame_conflict");
        if (!deferred.ContainsKey(id) && (deferred.Count >= 256 ||
            deferred.Values.Sum(value => TelefonCrypto.Canonical(value).Length) + TelefonCrypto.Canonical(message).Length > 1024 * 1024)) return false;
        deferred[id] = message.DeepClone().AsObject(); return true;
    }

    internal async Task ReceivePersonalActorAsync(TelefonConnection connection, TelefonPeer peer, JsonObject message)
    {
        JsonObject? reply = null;
        try
        {
            lock (gate)
            {
                if (message["body"] is not JsonObject candidate || candidate["run_id"] is not JsonValue candidateId ||
                    !candidateId.TryGetValue<string>(out var candidateRun) || !actorAdmissions.TryGetValue(candidateRun, out var admitted) ||
                    admitted.Connection != connection || admitted.PeerId != peer.Id ||
                    admitted.PublicKey != Convert.ToBase64String(peer.PublicKey) || online.GetValueOrDefault(peer.Id) != connection) return;
            }
            using var syncActivity = TraySyncActivity.Enter();
            await WithPersonalActorStoreAsync(registry => {
                if (message["body"] is not JsonObject body || body["run_id"] is not JsonValue id || !id.TryGetValue<string>(out var run) ||
                    !actorAdmissions.TryGetValue(run, out var admission) || admission.PeerId != peer.Id ||
                    admission.PublicKey != Convert.ToBase64String(peer.PublicKey) || admission.Connection != connection ||
                    online.GetValueOrDefault(peer.Id) != connection) return false;
                var kind = message["kind"]!.GetValue<string>();
                if (admission.Completion is { } completion)
                {
                    if (kind != PersonalSyncActorContract.AckKind) return false;
                    PersonalSyncActorContract.ValidateAck(body);
                    if (completion.ExpectsNativeAcknowledgment(body["message_id"]!.GetValue<string>()))
                        return true; // A peer cannot attest to this endpoint's native send.
                    try { PersistPersonalActorPeerAcknowledgment(registry, admission, message); }
                    catch (Microsoft.Data.Sqlite.SqliteException) { return DeferPersonalActorPeerAcknowledgment(admission, message); }
                    return true;
                }
                if (admission.HistoricalSaveClaim is not null)
                    return true; // Prepared data-closed owner: no raw/content staging, SaveACK or earned receipt yet.
                if (admission.ReportOwner is not null)
                {
                    registry.PutCompletionControl(admission.Handle, message);
                    if (kind == PersonalSyncActorContract.AckKind && body["status"]!.GetValue<string>() is "accepted" or "duplicate")
                    {
                        var acknowledged = body["message_id"]!.GetValue<string>(); store.CompleteOutbox(peer.Id, acknowledged);
                        if (acknowledged == admission.CompletionReportId) { admission.PhoneDataPersisted = true; admission.PhonePersisted = false; }
                    }
                    return true; // Protected decision metadata is not a successful decision ACK.
                }
                registry.RequireCurrent(admission.Handle);
                if (kind == PersonalSyncActorContract.AckKind)
                {
                    PersonalSyncActorContract.ValidateAck(body);
                    var acknowledged = body["message_id"]!.GetValue<string>();
                    if (admission.Outbound.Contains(acknowledged))
                    {
                        registry.Put(admission.Handle, message);
                        if (body["status"]!.GetValue<string>() is "accepted" or "duplicate") {
                            store.CompleteOutbox(peer.Id, acknowledged);
                            if (acknowledged == admission.CompletionReportId)
                            {
                                admission.PhoneDataPersisted = true;
                                admission.PhonePersisted = admission.CommitPlan?.DeletionReview["intents"]?.AsArray().Count == 0 &&
                                    (admission.ProducerBodies is null || admission.ProducerBodies.Count == 0);
                            }
                        }
                    }
                    return true;
                }
                if (kind != PersonalSyncActorContract.DataKind) return false;
                var (semanticKind, content) = PersonalSyncActorContract.Unwrap(body);
                var manifest = connection.CurrentContentScope(admission.Scope);
                if (semanticKind == PhoneContentScope.DataKind) (semanticKind, content) = PhoneContentScope.Unwrap(content, manifest);
                if (semanticKind is not ("personal_sync.request" or "personal_sync.batch" or "personal_sync.report" or "personal_sync.attachment_chunk" or
                    "personal_sync.attachment_request" or "personal_sync.attachment_result" or
                    "personal_sync.deletion_proposals" or "personal_sync.deletion_decision")) return false;
                if (semanticKind == "personal_sync.request" && (TelefonProtocolContract.Integer(content["format"]) is not (3 or 14) || content["trigger"]!.GetValue<string>() != "manual")) return false;
                if (semanticKind == "personal_sync.request" && TelefonProtocolContract.Integer(content["format"]) == 14 &&
                    PersonalGrants(semanticKind, content, null).Any(name => !SupportsPersonalFormat(peer, name, 14))) return false;
                if (semanticKind == "personal_sync.batch")
                {
                    var records = content["records"]!.AsArray().Select(value => value!.AsObject()).ToArray();
                    if (PhoneContentScope.FilterRecords(records, manifest).Count != records.Length) return false;
                }
                var storagePeer = PersonalSyncActorContract.StoragePeer(run);
                if (semanticKind is "personal_sync.deletion_proposals" or "personal_sync.deletion_decision")
                {
                    var currentPeer = RequireSolePeer(peer.Id);
                    var settings = store.SharedSettings(peer.Id, currentPeer.PublicKey);
                    if (settings is null || SharedSyncSettings.Effective(settings)["skip_deletions"]!.GetValue<bool>() ||
                        store.LocalGrants()["personal_deletions_sync"]?.GetValue<bool>() != true || currentPeer.Grants["personal_deletions_sync"]?.GetValue<bool>() != true ||
                        personalSync.LoadRun(storagePeer, run, Now()) is not { Expired: false }) return false;
                    if (semanticKind == "personal_sync.deletion_proposals")
                    {
                        var notes = manifest["members"]!["notes"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
                        var tasks = manifest["members"]!["tasks"]!.AsArray().Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);
                        foreach (var item in content["proposals"]!.AsArray().OfType<JsonObject>())
                        {
                            var valid = item["kind"]!.GetValue<string>() switch {
                                "note" => notes.Contains(item["id"]!.GetValue<string>()),
                                "task" => tasks.Contains(item["id"]!.GetValue<string>()),
                                "attachment" => notes.Contains(item["parent_id"]!.GetValue<string>()), _ => false };
                            if (!valid) { QuarantinePersonalActorIncomingTargets(registry, admission.Handle, message); return false; }
                        }
                    }
                    else
                    {
                        var decisionKinds = store.PersonalDecisionKinds(storagePeer, content, false);
                        if (decisionKinds is null || decisionKinds.Count == 0 || decisionKinds.Any(value => value is not ("note" or "task" or "attachment"))) return false;
                    }
                }
                JsonObject? descriptor = null;
                PersonalSyncRun? attachmentRun = null;
                if (semanticKind is "personal_sync.attachment_request" or "personal_sync.attachment_result")
                {
                    if (content["reply"]!.GetValue<bool>() != true) return false;
                    var outgoing = personalSync.ReadyBatches(Now()).FirstOrDefault(value => value.PeerId == storagePeer && value.RunId == run &&
                        value.Reply && value.RecordsHash == content["records_hash"]!.GetValue<string>());
                    if (outgoing is null) return false;
                    var records = outgoing.Records.OfType<JsonObject>().ToArray();
                    if (PhoneContentScope.FilterRecords(records, manifest).Count != records.Length) return false;
                    var declared = records.Where(value => value["kind"]!.GetValue<string>() == "note")
                        .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
                        .GroupBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal).ToDictionary(value => value.Key, value => value.First(), StringComparer.Ordinal);
                    var wants = semanticKind == "personal_sync.attachment_request" ? content["wants"]!.AsArray().OfType<JsonObject>() : [content];
                    foreach (var want in wants)
                    {
                        if (!declared.TryGetValue(want["sha256"]!.GetValue<string>(), out var item)) return false;
                        var total = (TelefonProtocolContract.Integer(item["size"]) + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw;
                        if ((want["ranges"] as JsonArray ?? []).OfType<JsonArray>().Any(range => TelefonProtocolContract.Integer(range[1]) > total)) return false;
                    }
                }
                if (semanticKind == "personal_sync.attachment_chunk")
                {
                    var staged = personalSync.ReadyBatches(Now()).FirstOrDefault(value => value.PeerId == storagePeer && value.RunId == run &&
                        value.Reply == content["reply"]!.GetValue<bool>() && value.RecordsHash == content["records_hash"]!.GetValue<string>());
                    if (staged is null) return false;
                    var records = staged.Records.OfType<JsonObject>().ToArray();
                    if (PhoneContentScope.FilterRecords(records, manifest).Count != records.Length) return false;
                    descriptor = records.Where(value => value["kind"]!.GetValue<string>() == "note")
                        .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
                        .FirstOrDefault(value => value["sha256"]!.GetValue<string>() == content["sha256"]!.GetValue<string>());
                    attachmentRun = personalSync.LoadRun(storagePeer, run, Now());
                    if (descriptor is null || attachmentRun is null || attachmentRun.Expired) return false;
                }
                registry.Put(admission.Handle, message);
                var semantic = message.DeepClone().AsObject(); semantic["kind"] = semanticKind; semantic["body"] = content.DeepClone();
                if (semanticKind == "personal_sync.request") personalSync.RememberRun(storagePeer, content, Now(), TelefonProtocolContract.Integer(message["expires_ms"]));
                else if (semanticKind == "personal_sync.batch")
                {
                    var staged = personalSync.StageBatch(storagePeer, semantic, connection.Transport, Now());
                    if (staged is not null) QueueActorAttachmentRequests(admission, staged);
                }
                else if (semanticKind == "personal_sync.attachment_chunk")
                {
                    var raw = Convert.FromBase64String(content["data"]!.GetValue<string>());
                    try
                    {
                        personalSync.StageAttachment(storagePeer, run, content["reply"]!.GetValue<bool>(), content["records_hash"]!.GetValue<string>(),
                            descriptor!, "incoming", attachmentRun!.Policy, attachmentRun.ExpiresMs, []);
                        personalSync.StageAttachmentChunk(storagePeer, run, content["reply"]!.GetValue<bool>(), content["records_hash"]!.GetValue<string>(),
                            content["sha256"]!.GetValue<string>(), "incoming", content["index"]!.GetValue<int>(), raw,
                            Math.Min(attachmentRun.ExpiresMs, TelefonProtocolContract.Integer(message["expires_ms"])));
                    }
                    finally { CryptographicOperations.ZeroMemory(raw); }
                    QueueActorAttachmentResult(admission, content);
                }
                else if (semanticKind == "personal_sync.attachment_request") QueueActorRequestedChunks(admission, message["message_id"]!.GetValue<string>(), content);
                else if (semanticKind == "personal_sync.attachment_result")
                {
                    if (content["state"]!.GetValue<string>() == "complete") personalSync.CompleteOutgoingAttachment(storagePeer, run, true,
                        content["records_hash"]!.GetValue<string>(), content["sha256"]!.GetValue<string>(), Now());
                }
                else if (semanticKind is "personal_sync.deletion_proposals" or "personal_sync.deletion_decision")
                {
                    if (semanticKind == "personal_sync.deletion_proposals") store.RememberPersonalProposalKinds(storagePeer, content, false);
                    personalSync.StageDecisionIntent(storagePeer, semantic, connection.Transport, Now());
                    registry.RequireCurrent(admission.Handle);
                    return true; // No success receipt for a deletion intent before native book commit.
                }
                registry.RequireCurrent(admission.Handle);
                reply = ActorControl(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(run, message["message_id"]!.GetValue<string>()));
                return true;
            });
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { }
        if (reply is not null) await connection.SendPlainAsync(reply);
    }

    private void QueueActorRequestedChunks(ActorAdmission admission, string requestId, JsonObject content)
    {
        var run = admission.Handle.ActorId; var privatePeer = PersonalSyncActorContract.StoragePeer(run);
        var recordsHash = content["records_hash"]!.GetValue<string>(); var count = 0;
        foreach (var want in content["wants"]!.AsArray().OfType<JsonObject>())
        {
            var hash = want["sha256"]!.GetValue<string>();
            var data = personalSync.ReadVerifiedAttachment(privatePeer, run, true, recordsHash, hash, "outgoing", admission.Connection.Transport, Now());
            try
            {
                foreach (var range in want["ranges"]!.AsArray().OfType<JsonArray>())
                    for (var index = range[0]!.GetValue<int>(); index < range[1]!.GetValue<int>(); index++)
                    {
                        if (count++ == 8) return;
                        var identity = $"{requestId}:{hash}:{index}";
                        if (admission.ProducedChunks.Contains(identity)) continue;
                        if (admission.Outbound.Count >= 4096) throw new InvalidOperationException("actor_capacity");
                        var offset = index * PersonalSyncContract.ChunkRaw;
                        var body = new JsonObject { ["format"] = 2, ["run_id"] = run, ["reply"] = true, ["records_hash"] = recordsHash,
                            ["sha256"] = hash, ["index"] = index, ["data"] = Convert.ToBase64String(data, offset, Math.Min(PersonalSyncContract.ChunkRaw, data.Length - offset)) };
                        var id = store.Enqueue(admission.PeerId, "personal_sync.attachment_chunk", body, 86400000, Now(), actorRunId: run);
                        admission.Outbound.Add(id); admission.ProducedChunks.Add(identity);
                    }
            }
            finally { CryptographicOperations.ZeroMemory(data); }
        }
    }

    private void QueueActorAttachmentRequests(ActorAdmission admission, PersonalSyncStagedBatch staged)
    {
        var descriptors = staged.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>())
            .GroupBy(value => value["sha256"]!.GetValue<string>(), StringComparer.Ordinal).OrderBy(value => value.Key, StringComparer.Ordinal).ToArray();
        var run = personalSync.LoadRun(staged.PeerId, staged.RunId, Now()) ?? throw new InvalidDataException("Actor run missing.");
        foreach (var group in descriptors)
        {
            var descriptor = group.First();
            if (group.Any(value => !JsonNode.DeepEquals(value["size"], descriptor["size"]) || !JsonNode.DeepEquals(value["mime"], descriptor["mime"])))
                throw new InvalidDataException("Conflicting actor attachment manifest.");
            personalSync.StageAttachment(staged.PeerId, staged.RunId, staged.Reply, staged.RecordsHash, descriptor, "incoming", run.Policy, run.ExpiresMs, []);
            var ranges = personalSync.MissingAttachmentRanges(staged.PeerId, staged.RunId, staged.Reply, staged.RecordsHash, group.Key, "incoming", Now());
            var total = (TelefonProtocolContract.Integer(descriptor["size"]) + PersonalSyncContract.ChunkRaw - 1) / PersonalSyncContract.ChunkRaw;
            for (var start = 0; start < total; start += 8)
            {
                var end = Math.Min(start + 8, total);
                var key = $"{staged.Reply}:{staged.RecordsHash}:{group.Key}:{start}:{end}";
                if (admission.AttachmentRequests.Contains(key) || !ranges.Any(value => value.Start < end && value.End > start)) continue;
                if (admission.Outbound.Count >= 4096) throw new InvalidOperationException("actor_capacity");
                // Notes' existing producer serves at most eight chunks per request.
                var wants = new JsonArray(new JsonObject { ["sha256"] = group.Key, ["ranges"] = new JsonArray(new JsonArray(start, end)) });
                var body = new JsonObject { ["format"] = 2, ["run_id"] = staged.RunId, ["reply"] = staged.Reply, ["records_hash"] = staged.RecordsHash, ["wants"] = wants };
                var id = store.Enqueue(admission.PeerId, "personal_sync.attachment_request", body, 60000, Now(), actorRunId: staged.RunId);
                admission.Outbound.Add(id); admission.AttachmentRequests.Add(key);
            }
        }
    }

    private void QueueActorAttachmentResult(ActorAdmission admission, JsonObject content)
    {
        var run = admission.Handle.ActorId;
        var privatePeer = PersonalSyncActorContract.StoragePeer(run);
        var reply = content["reply"]!.GetValue<bool>(); var recordsHash = content["records_hash"]!.GetValue<string>();
        var hash = content["sha256"]!.GetValue<string>(); var key = $"{reply}:{recordsHash}:{hash}";
        if (admission.AttachmentResults.Contains(key) || personalSync.MissingAttachmentRanges(privatePeer, run, reply, recordsHash, hash, "incoming", Now()).Count != 0) return;
        var verified = personalSync.ReadVerifiedAttachment(privatePeer, run, reply, recordsHash, hash, "incoming", admission.Connection.Transport, Now());
        CryptographicOperations.ZeroMemory(verified);
        var body = new JsonObject { ["format"] = 2, ["run_id"] = run, ["reply"] = reply, ["records_hash"] = recordsHash,
            ["sha256"] = hash, ["state"] = "complete", ["error"] = "none" };
        var id = store.Enqueue(admission.PeerId, "personal_sync.attachment_result", body, 60000, Now(), actorRunId: run);
        admission.Outbound.Add(id); admission.AttachmentResults.Add(key);
    }

    private async Task SendPersonalActorNativeAcknowledgmentsAsync(ActorAdmission admission, TelefonConnection connection)
    {
        lock (gate) if (admission.NativeAcknowledgments.Count == 0) return;
        (PersonalActorDecisionCompletion Completion, JsonObject[] Frames)? claim;
        try
        {
            claim = await WithPersonalActorStoreAsync<(PersonalActorDecisionCompletion, JsonObject[])?>(registry => {
                if (actorAdmissions.GetValueOrDefault(admission.Handle.ActorId) != admission || admission.Connection != connection ||
                    online.GetValueOrDefault(admission.PeerId) != connection || admission.Completion is not { } completion ||
                    admission.SaveReceipt is null || !admission.PhoneDataPersisted || admission.PhonePersisted ||
                    NativeSavedBook() != (admission.LateSaveReceipt ?? admission.SaveReceipt) || admission.NativeAckInFlight ||
                    admission.NativeAckNextAttempt > Environment.TickCount64 || admission.NativeAcknowledgments.Count == 0) return null;
                var frames = admission.NativeAcknowledgments.Values.Take(32).ToArray();
                foreach (var wire in frames)
                {
                    if (TelefonProtocolContract.Integer(wire["expires_ms"]) <= Now()) { registry.Cancel(admission.Handle); return null; }
                    registry.CheckCompletionSend(admission.Handle, wire);
                }
                admission.NativeAckNextAttempt = Environment.TickCount64 + Math.Min(30000L, 1000L << Math.Min(admission.NativeAckAttempts, 5));
                admission.NativeAckAttempts++; admission.NativeAckInFlight = true;
                return (completion, frames);
            });
        }
        catch (InvalidOperationException) { return; } // Pending fresh scope/writer is not success.
        if (claim is not { } claimed) return;
        bool Current() => actorAdmissions.GetValueOrDefault(admission.Handle.ActorId) == admission &&
            admission.Connection == connection && online.GetValueOrDefault(admission.PeerId) == connection &&
            ReferenceEquals(admission.Completion, claimed.Completion) && !admission.PhonePersisted;
        try
        {
            foreach (var wire in claimed.Frames)
            {
                var ready = await WithPersonalActorStoreAsync(registry => {
                    if (!Current() || !admission.NativeAcknowledgments.TryGetValue(wire["message_id"]!.GetValue<string>(), out var queued) ||
                        !JsonNode.DeepEquals(queued, wire)) return false;
                    if (TelefonProtocolContract.Integer(wire["expires_ms"]) <= Now()) { registry.Cancel(admission.Handle); return false; }
                    registry.CheckCompletionSend(admission.Handle, wire); return true;
                });
                if (!ready) return;
                await connection.SendPlainAsync(wire); // Outside policy/source/store guards.
                var recorded = await WithPersonalActorStoreAsync(registry => {
                    if (!Current()) return false;
                    registry.CheckCompletionSend(admission.Handle, wire);
                    claimed.Completion.RecordSuccessfulAcknowledgmentSend(wire);
                    registry.PutCompletionControl(admission.Handle, wire);
                    claimed.Completion.RecordPersisted(wire);
                    admission.NativeAcknowledgments.Remove(wire["message_id"]!.GetValue<string>());
                    if (claimed.Completion.Validator("finish", null) == true)
                    { registry.FinishCompletion(admission.Handle); admission.PhonePersisted = true;
                        store.RememberPersonalSuccess(admission.PeerId, admission.PublicKey, admission.Handle.ActorId, "manual", Now()); }
                    return true;
                });
                if (!recorded) return;
            }
        }
        finally { lock (gate) admission.NativeAckInFlight = false; }
    }

    internal async Task PumpPersonalActorAsync(TelefonConnection connection)
    {
        ActorAdmission[] admitted;
        lock (gate) admitted = actorAdmissions.Values.Where(value => value.Connection == connection).ToArray();
        if (admitted.Length == 0) return;
        var dispatch = new List<(JsonObject Message, ActorAdmission? ReportAdmission, PersonalActorReportOwner? Waiting)>();
        try
        {
            await WithPersonalActorStoreAsync(registry => {
                registry.Reap();
                // Bound synchronous receipt persistence across ALL admissions
                // in this pump. Retain untouched original envelopes for the
                // next call; the existing per-envelope authority/SQL checks
                // remain the only route to a protected receipt.
                var completionControlsBudget = 16;
                foreach (var admission in admitted)
                {
                    try
                    {
                        if (registry.Status(admission.Handle)["phase"]!.GetValue<string>() == "cancelled")
                            continue; // Retain the bound cancellation target until its lease expires.
                    }
                    catch (InvalidOperationException) { actorAdmissions.Remove(admission.Handle.ActorId); continue; }
                    if (admission.HistoricalSaveClaim is not null && admission.Completion is null) continue;
                    if (admission.Completion is not null)
                    {
                        foreach (var pending in admission.CompletionDeferredControls.Values.Take(completionControlsBudget).ToArray())
                        {
                            completionControlsBudget--;
                            try
                            {
                                PersistPersonalActorPeerAcknowledgment(registry, admission, pending);
                                admission.CompletionDeferredControls.Remove(pending["message_id"]!.GetValue<string>());
                            }
                            catch (Microsoft.Data.Sqlite.SqliteException) { break; } // Retry metadata only; do not resend decisions.
                        }
                        if (admission.CompletionDeferredControls.Count != 0) continue;
                    }
                    if (admission.Completion is null && admission.ReportOwner is null)
                    {
                        registry.RequireCurrent(admission.Handle);
                        QueueActorCompletionReport(registry, admission);
                        if (admission.PhoneDataPersisted && admission.CommitPlan?.DeletionReview["intents"] is JsonArray intents && intents.Count != 0)
                            BeginPersonalActorCompletion(registry, admission);
                    }
                    if (online.GetValueOrDefault(admission.PeerId) != connection) continue;
                    foreach (var item in store.Due(admission.PeerId, Now(), transport: connection.Transport))
                    {
                        if (item.Message["kind"]?.GetValue<string>() != PersonalSyncActorContract.DataKind ||
                            item.Message["body"]?["run_id"]?.GetValue<string>() != admission.Handle.ActorId || !admission.Outbound.Contains(item.Id)) continue;
                        if (admission.Completion is not null && !admission.CompletionIds.Contains(item.Id)) continue;
                        var fixedDecision = admission.ReportOwner?.IsFixedDecisionFrame(item.Id) == true;
                        if (admission.ReportOwner is not null && admission.Completion is null && item.Id != admission.CompletionReportId && !fixedDecision) continue;
                        if (admission.ProducerIds.Contains(item.Id) && (!admission.StartDispatched || NativeSavedBook() != admission.ProducerBook)) continue;
                        if (admission.Completion is not null) registry.CheckCompletionSend(admission.Handle, item.Message);
                        else if (admission.ReportOwner is not null)
                        {
                            try
                            {
                                if (fixedDecision) registry.CheckDecisionControlSend(admission.Handle, item.Message);
                                else registry.CheckDecisionReportSend(admission.Handle, item.Message);
                            }
                            catch (InvalidOperationException error) when (error.Message == "actor_completion_not_ready")
                            { continue; } // Defer this frame, not fixed decisions already collected in this pump.
                        }
                        else registry.RequireCurrent(admission.Handle);
                        store.MarkAttempt(item.Id, item.Attempts, Now());
                        if (admission.ReportOwner is not null && admission.Completion is null)
                        {
                            if (fixedDecision) registry.CheckDecisionControlSend(admission.Handle, item.Message);
                            else registry.CheckDecisionReportSend(admission.Handle, item.Message);
                        }
                        var waiting = admission.Completion is null ? admission.ReportOwner : null;
                        dispatch.Add((item.Message, waiting is null ? null : admission, waiting));
                    }
                }
                return true;
            });
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { return; }
        foreach (var claim in dispatch)
        {
            var message = claim.Message;
            var reportOwner = claim.ReportAdmission;
            var waiting = claim.Waiting;
            var fixedDecision = waiting?.IsFixedDecisionFrame(message["message_id"]!.GetValue<string>()) == true;
            if (reportOwner is not null)
            {
                var allowed = false;
                try
                {
                    allowed = await WithPersonalActorStoreAsync(registry => {
                        if (reportOwner.ReportOwner != waiting || reportOwner.Completion is not null) return false;
                        if (fixedDecision) registry.CheckDecisionControlSend(reportOwner.Handle, message);
                        else registry.CheckDecisionReportSend(reportOwner.Handle, message);
                        return actorAdmissions.GetValueOrDefault(reportOwner.Handle.ActorId) == reportOwner && online.GetValueOrDefault(reportOwner.PeerId) == connection &&
                            JsonNode.DeepEquals(store.OutboxMessage(reportOwner.PeerId, message["message_id"]!.GetValue<string>()), message);
                    });
                }
                catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { }
                if (!allowed) continue;
            }
            var producer = admitted.SingleOrDefault(value => value.ProducerIds.Contains(message["message_id"]!.GetValue<string>()));
            if (producer is not null)
            {
                var allowed = false;
                try
                {
                    allowed = await WithPersonalActorStoreAsync(registry => {
                        registry.RequireCurrent(producer.Handle);
                        return actorAdmissions.GetValueOrDefault(producer.Handle.ActorId) == producer &&
                            online.GetValueOrDefault(producer.PeerId) == connection && NativeSavedBook() == producer.ProducerBook &&
                            JsonNode.DeepEquals(store.OutboxMessage(producer.PeerId, message["message_id"]!.GetValue<string>()), message);
                    });
                }
                catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { }
                if (!allowed) continue;
            }
            await connection.SendPlainAsync(message);
            if (reportOwner is not null)
                await WithPersonalActorStoreAsync(registry => {
                    if (actorAdmissions.GetValueOrDefault(reportOwner.Handle.ActorId) != reportOwner || online.GetValueOrDefault(reportOwner.PeerId) != connection ||
                        reportOwner.ReportOwner != waiting || reportOwner.Completion is not null)
                        throw new InvalidOperationException("actor_report_dispatch_outcome_unknown");
                    if (fixedDecision)
                    {
                        registry.CheckDecisionControlSend(reportOwner.Handle, message);
                        waiting!.RecordSuccessfulFixedDecisionSend(message);
                    }
                    else registry.CheckDecisionReportSend(reportOwner.Handle, message);
                    return true;
                });
        }
        foreach (var admission in admitted) await SendPersonalActorNativeAcknowledgmentsAsync(admission, connection);
    }
}
