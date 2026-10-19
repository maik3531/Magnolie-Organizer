using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class TelefonCoordinator
{
    private sealed record ActorAdmission(PersonalActorHandle Handle, string PeerId, string PublicKey,
        TelefonConnection Connection, JsonObject Scope, JsonObject Start, HashSet<string> Outbound);
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
                    connection.ActorSourceSnapshot()["scope"]!.DeepClone().AsObject(), start, [start["message_id"]!.GetValue<string>()]);
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
            if (actorAdmissions.Remove(handle.ActorId, out var value) && value.Handle == handle &&
                online.GetValueOrDefault(value.PeerId) == value.Connection &&
                store.LoadPeers().Any(peer => peer.Id == value.PeerId && Convert.ToBase64String(peer.PublicKey) == value.PublicKey)) dispatch = value;
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
                    if (admission.Outbound.Contains(body["message_id"]!.GetValue<string>())) registry.Put(admission.Handle, message);
                    return true;
                }
                if (kind != PersonalSyncActorContract.DataKind) return false;
                var (semanticKind, content) = PersonalSyncActorContract.Unwrap(body);
                var manifest = connection.CurrentContentScope(admission.Scope);
                if (semanticKind == PhoneContentScope.DataKind) (semanticKind, content) = PhoneContentScope.Unwrap(content, manifest);
                if (semanticKind is not ("personal_sync.request" or "personal_sync.batch" or "personal_sync.report")) return false;
                if (semanticKind == "personal_sync.request" && (TelefonProtocolContract.Integer(content["format"]) != 3 || content["trigger"]!.GetValue<string>() != "manual")) return false;
                if (semanticKind == "personal_sync.batch")
                {
                    var records = content["records"]!.AsArray().Select(value => value!.AsObject()).ToArray();
                    if (PhoneContentScope.FilterRecords(records, manifest).Count != records.Length) return false;
                }
                registry.Put(admission.Handle, message);
                var storagePeer = PersonalSyncActorContract.StoragePeer(run);
                var semantic = message.DeepClone().AsObject(); semantic["kind"] = semanticKind; semantic["body"] = content.DeepClone();
                if (semanticKind == "personal_sync.request") personalSync.RememberRun(storagePeer, content, Now(), TelefonProtocolContract.Integer(message["expires_ms"]));
                else if (semanticKind == "personal_sync.batch") personalSync.StageBatch(storagePeer, semantic, connection.Transport, Now());
                registry.RequireCurrent(admission.Handle);
                reply = ActorControl(PersonalSyncActorContract.AckKind, PersonalSyncActorContract.Ack(run, message["message_id"]!.GetValue<string>()));
                return true;
            });
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException) { }
        if (reply is not null) await connection.SendPlainAsync(reply);
    }
}
