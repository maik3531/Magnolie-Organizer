using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed record ActorCommitPlan(string Token, string ViewRevision, string AfterHash, string BookSource, long BeforeSequence);
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
        internal JsonObject IncomingCounts { get; set; } = new() { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0 };
        internal int IncomingAttachments { get; set; }
    }
    private readonly Dictionary<string, ActorAdmission> actorAdmissions = new(StringComparer.Ordinal);

    internal async Task<JsonObject> ExecuteMcpActorAsync(JsonObject request, CancellationToken cancellation)
    {
        try
        {
            var action = McpText(request, "action", true);
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
                "notes_actor_status" => await PersonalActorStatusAsync(handle, cancellation),
                "notes_actor_cancel" => await CancelPersonalActorAsync(handle, cancellation),
                "notes_actor_read" => await ReadPersonalActorStagingAsync(handle,
                    request["offset"]?.GetValue<int>() ?? 0, request["limit"]?.GetValue<int>() ?? 65536,
                    McpText(request, "expectedRevision"), McpText(request, "attachmentSha256"), cancellation),
                "notes_actor_prepare_commit" => await PreparePersonalActorCommitAsync(handle, McpText(request, "expectedRevision", true), McpText(request, "bookSha256", true), cancellation),
                "notes_actor_commit" => await CommitPersonalActorAsync(handle, McpText(request, "claimToken", true), cancellation),
                "notes_actor_reply" => await QueuePersonalActorReplyAsync(handle, McpText(request, "claimToken", true),
                    request["batches"]?.AsArray() ?? throw new InvalidDataException(), request["sources"]?.AsArray() ?? throw new InvalidDataException(), cancellation),
                _ => throw new InvalidDataException("unsupported_actor_action")
            };
            return new() { ["ok"] = true, ["actor"] = result };
        }
        catch (OperationCanceledException) { return new() { ["ok"] = false, ["code"] = "cancelled" }; }
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

    internal async Task<JsonObject> StartPersonalActorAsync(PersonalActorHandle handle, CancellationToken cancellation = default)
    {
        var admission = await WithPersonalActorStoreAsync(registry => {
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
                TelefonProtocolContract.Integer(value.Start["expires_ms"]) <= Now()) throw new InvalidOperationException("actor_source_changed");
            registry.RequireCurrent(handle);
            return value;
        }, cancellation);
        // Authority was claimed above; lifecycle cancellation may make an in-flight write's outcome unknown.
        await admission.Connection.SendPlainAsync(admission.Start.DeepClone().AsObject());
        return new() { ["actor_id"] = handle.ActorId, ["message_id"] = admission.Start["message_id"]!.DeepClone(),
            ["dispatch_started"] = true, ["delivery_confirmed"] = false, ["persisted"] = false };
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

    internal Task<JsonObject> PreparePersonalActorCommitAsync(PersonalActorHandle handle, string viewRevision, string afterHash,
        CancellationToken cancellation = default) => WithPersonalActorStoreAsync(registry => {
        if (!System.Text.RegularExpressions.Regex.IsMatch(viewRevision, "^[0-9a-f]{64}$") || !System.Text.RegularExpressions.Regex.IsMatch(afterHash, "^[0-9a-f]{64}$"))
            throw new InvalidDataException("invalid_actor_commit_plan");
        var view = ReadPersonalActorStaging(registry, handle, 0, 1, viewRevision, "");
        if (view["batch_ready"]!.GetValue<bool>() != true) throw new InvalidOperationException("actor_staging_incomplete");
        var admission = actorAdmissions[handle.ActorId]; var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
        if (personalSync.DecisionIntents(Now()).Any(value => value.PeerId == privatePeer && value.Body["run_id"]!.GetValue<string>() == handle.ActorId))
            throw new InvalidOperationException("actor_deletion_review_required");
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
        if (plan is null) admission.CommitPlan = plan = new(Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), viewRevision, afterHash, book.BookSource, book.Sequence);
        else if (plan.ViewRevision != viewRevision || plan.AfterHash != afterHash || plan.BookSource != book.BookSource)
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
                var privatePeer = PersonalSyncActorContract.StoragePeer(handle.ActorId);
                var batch = personalSync.ReadyBatches(Now()).Single(value => value.PeerId == privatePeer && value.RunId == handle.ActorId && !value.Reply);
                if (!personalSync.CommitBatch(privatePeer, batch.PendingMessageId, batch.CommitToken, Now(), out _))
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
        for (var index = 0; index < batches.Length; index++)
        {
            var body = batches[index]; PersonalSyncContract.ValidateBody("personal_sync.batch", body);
            if (body["run_id"]!.GetValue<string>() != handle.ActorId || body["format"]!.GetValue<int>() != 3 || !body["reply"]!.GetValue<bool>() ||
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

    internal Task<JsonObject> PersonalActorStatusAsync(PersonalActorHandle handle, CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => {
            var result = registry.Status(handle);
            if (actorAdmissions.TryGetValue(handle.ActorId, out var admission) && admission.Handle == handle)
            {
                result["book_persisted"] = admission.SaveReceipt is not null; result["reply_queued"] = admission.ReplyCount != 0;
                result["phone_persisted"] = admission.PhonePersisted; result["completion_report_queued"] = admission.CompletionReportId.Length != 0;
            }
            return result;
        }, cancellation);

    private void QueueActorCompletionReport(ActorAdmission admission)
    {
        if (admission.SaveReceipt is null || admission.ReplyCount == 0 || admission.CompletionReportId.Length != 0 ||
            admission.ReplyIds.Any(id => store.OutboxMessage(admission.PeerId, id) is not null)) return;
        var run = admission.Handle.ActorId; var privatePeer = PersonalSyncActorContract.StoragePeer(run);
        var batch = personalSync.ReadyBatches(Now()).SingleOrDefault(value => value.PeerId == privatePeer && value.RunId == run && value.Reply);
        if (batch is null) return;
        var files = batch.Records.OfType<JsonObject>().Where(value => value["kind"]!.GetValue<string>() == "note")
            .SelectMany(value => (value["value"]?["attachments"] as JsonArray ?? []).OfType<JsonObject>()).GroupBy(value => value["sha256"]!.GetValue<string>()).Select(group => group.First()).ToArray();
        if (files.Any(value => !personalSync.OutgoingAttachmentComplete(privatePeer, run, true, batch.RecordsHash, value["sha256"]!.GetValue<string>(), Now()))) return;
        if (admission.Outbound.Count >= 4096) throw new InvalidOperationException("actor_capacity");
        var started = TelefonProtocolContract.Integer(admission.Start["created_ms"]);
        var report = new JsonObject { ["format"] = 3, ["run_id"] = run, ["state"] = "complete", ["trigger"] = "manual", ["transport"] = admission.Connection.Transport,
            ["sent"] = ActorCounts(batch.Records.OfType<JsonObject>()), ["received"] = admission.IncomingCounts.DeepClone(), ["conflicts"] = 0,
            ["attachments_omitted"] = 0, ["oversized_skipped"] = 0, ["started_ms"] = started, ["finished_ms"] = Math.Max(started, Now()), ["error"] = "none",
            ["attachments"] = new JsonObject { ["declared"] = files.Length, ["requested"] = files.Length, ["sent"] = files.Length,
                ["received"] = admission.IncomingAttachments, ["reused"] = 0, ["preserved"] = files.Length, ["failed"] = 0,
                ["bytes"] = files.Sum(value => TelefonProtocolContract.Integer(value["size"])) },
            ["deletions"] = new JsonObject { ["pending"] = 0, ["deleted"] = 0, ["restored"] = 0, ["conflicts"] = 0, ["blocked"] = 0,
                ["trash"] = new JsonObject { ["notes"] = 0, ["tasks"] = 0, ["notebooks"] = 0, ["attachments"] = 0 } } };
        var id = store.Enqueue(admission.PeerId, "personal_sync.report", report, 86400000, Now(), actorRunId: run);
        admission.CompletionReportId = id; admission.Outbound.Add(id);
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
            await WithPersonalActorStoreAsync(registry => {
                if (message["body"] is not JsonObject body || body["run_id"] is not JsonValue id || !id.TryGetValue<string>(out var run) ||
                    !actorAdmissions.TryGetValue(run, out var admission) || admission.PeerId != peer.Id ||
                    admission.PublicKey != Convert.ToBase64String(peer.PublicKey) || admission.Connection != connection ||
                    online.GetValueOrDefault(peer.Id) != connection) return false;
                registry.RequireCurrent(admission.Handle);
                var kind = message["kind"]!.GetValue<string>();
                if (kind == PersonalSyncActorContract.AckKind)
                {
                    PersonalSyncActorContract.ValidateAck(body);
                    var acknowledged = body["message_id"]!.GetValue<string>();
                    if (admission.Outbound.Contains(acknowledged))
                    {
                        registry.Put(admission.Handle, message);
                        if (body["status"]!.GetValue<string>() is "accepted" or "duplicate") {
                            store.CompleteOutbox(peer.Id, acknowledged);
                            if (acknowledged == admission.CompletionReportId) admission.PhonePersisted = true;
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
                if (semanticKind == "personal_sync.request" && (TelefonProtocolContract.Integer(content["format"]) != 3 || content["trigger"]!.GetValue<string>() != "manual")) return false;
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
                            if (!valid) return false;
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

    internal async Task PumpPersonalActorAsync(TelefonConnection connection)
    {
        ActorAdmission[] admitted;
        lock (gate) admitted = actorAdmissions.Values.Where(value => value.Connection == connection).ToArray();
        if (admitted.Length == 0) return;
        var dispatch = new List<JsonObject>();
        try
        {
            await WithPersonalActorStoreAsync(registry => {
                registry.Reap();
                foreach (var admission in admitted)
                {
                    try
                    {
                        if (registry.Status(admission.Handle)["phase"]!.GetValue<string>() == "cancelled")
                            continue; // Retain the bound cancellation target until its lease expires.
                    }
                    catch (InvalidOperationException) { actorAdmissions.Remove(admission.Handle.ActorId); continue; }
                    registry.RequireCurrent(admission.Handle);
                    QueueActorCompletionReport(admission);
                    if (online.GetValueOrDefault(admission.PeerId) != connection) continue;
                    foreach (var item in store.Due(admission.PeerId, Now(), transport: connection.Transport))
                    {
                        if (item.Message["kind"]?.GetValue<string>() != PersonalSyncActorContract.DataKind ||
                            item.Message["body"]?["run_id"]?.GetValue<string>() != admission.Handle.ActorId || !admission.Outbound.Contains(item.Id)) continue;
                        store.MarkAttempt(item.Id, item.Attempts, Now());
                        registry.RequireCurrent(admission.Handle);
                        dispatch.Add(item.Message);
                    }
                }
                return true;
            });
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { return; }
        foreach (var message in dispatch) await connection.SendPlainAsync(message);
    }
}
