using System.Text.Json.Nodes;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed record ActorAdmission(PersonalActorHandle Handle, string PeerId, string PublicKey,
        TelefonConnection Connection, JsonObject Scope, JsonObject Start, HashSet<string> Outbound, HashSet<string> AttachmentRequests,
        HashSet<string> AttachmentResults);
    private readonly Dictionary<string, ActorAdmission> actorAdmissions = new(StringComparer.Ordinal);

    private static JsonObject ActorControl(string kind, JsonObject body)
    {
        var now = Now();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = kind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
    }

    internal Task<PersonalActorHandle> CreatePersonalActorAsync(string id, string fingerprint, CancellationToken cancellation = default) =>
        WithPersonalActorStoreAsync(registry => registry.Create(id, fingerprint,
            CurrentActorSource(id, fingerprint) ?? throw new InvalidOperationException("actor_source_changed")), cancellation);

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
                        if (body["status"]!.GetValue<string>() is "accepted" or "duplicate") store.CompleteOutbox(peer.Id, acknowledged);
                    }
                    return true;
                }
                if (kind != PersonalSyncActorContract.DataKind) return false;
                var (semanticKind, content) = PersonalSyncActorContract.Unwrap(body);
                var manifest = connection.CurrentContentScope(admission.Scope);
                if (semanticKind == PhoneContentScope.DataKind) (semanticKind, content) = PhoneContentScope.Unwrap(content, manifest);
                if (semanticKind is not ("personal_sync.request" or "personal_sync.batch" or "personal_sync.report" or "personal_sync.attachment_chunk" or
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
