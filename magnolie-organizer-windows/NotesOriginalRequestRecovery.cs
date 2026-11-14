using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalRequestIntents
{
    private sealed record RecoveryNative(QueryProof Query, JsonObject Result, MagnolienbaumCoordinator.NativeNotesOrigin Origin,
        string Transport, NotesOriginalNegotiation Protocol)
    { internal NotesOriginalPendingResult? Pending; }

    internal sealed class RecoveryNeedsRealSave(RecoveryContext context) : InvalidOperationException("notes_request_real_native_save_required")
    { internal RecoveryContext Context { get; } = context; }

    internal sealed class RecoveryContext(object proof)
    {
        private RecoveryNative Native() => proof as RecoveryNative ?? throw new InvalidOperationException("notes_request_private_verified_recovery_required");
        internal JsonObject RequireCurrent()
        { var native = Native(); return native.Query.Store.RequireRecovery(native); }
        internal NativeActorBookSnapshot? CurrentSaved()
        {
            var native = Native(); var frame = RequireCurrent();
            return native.Query.Consent.CurrentSavedForRecovery(frame);
        }
        internal (JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport) Result()
        { var native = Native(); RequireCurrent(); return (native.Result.DeepClone().AsObject(), native.Origin, native.Transport); }
        internal NotesOriginalPendingResult Resume()
        {
            var native = Native(); RequireCurrent();
            if (native.Pending is not null) return native.Pending;
            var snapshot = CurrentSaved() ?? throw new RecoveryNeedsRealSave(this);
            var pending = NotesOriginalPendingResult.FromRecovery(this, snapshot);
            RequireCurrent();
            lock (native.Query.Store.gate)
            {
                if (native.Query.Generation != native.Query.Store.generation) throw new InvalidOperationException("notes_request_recovery_process_expired");
                native.Pending = pending; native.Query.Store.recovered.Add(pending, this);
            }
            return pending;
        }
        internal object RequirePending(NotesOriginalPendingResult pending)
        {
            var native = Native();
            if (!ReferenceEquals(native.Pending, pending)) throw new InvalidOperationException("notes_request_owned_recovered_pending_required");
            RequireCurrent(); return native;
        }
    }

    internal RecoveryContext Recover(UnconfirmedQuery query, JsonObject result, MagnolienbaumCoordinator.NativeNotesOrigin origin,
        string transport, NotesOriginalNegotiation protocol)
    {
        // Deferred native worker under the existing serial mutation gate only.
        var proof = (QueryProof)query.RequireOwner(this);
        var native = new RecoveryNative(proof, result.DeepClone().AsObject(), origin, transport, protocol);
        RequireRecovery(native); return new(native);
    }

    private JsonObject RequireRecovery(RecoveryNative proof)
    {
        RequireQuery(proof.Query, proof.Protocol);
        var frame = LoadPhysical(proof.Query.Binding, proof.Query.LocalId) ?? throw new InvalidOperationException("notes_request_physical_history_missing");
        if (NotesOriginalSchema.Hash(frame) != proof.Query.FrameHash || proof.Origin.RequireCurrent(proof.Result, proof.Transport) != proof.Protocol.RequireCurrent())
            throw new InvalidOperationException("notes_request_verified_recovery_changed");
        NotesOriginalPendingResult.ValidateResult(frame["request"]!.AsObject(), NotesOriginalSchema.Text(frame, "request_sha256"),
            NotesOriginalSchema.Integer(frame["export"]!.AsObject(), "native_revision"), proof.Result);
        proof.Query.Consent.VerifyUnconfirmedHistory(frame); proof.Origin.RequireCurrent(proof.Result, proof.Transport);
        return frame;
    }

    private (string Key, string KeyIdentity, JsonObject Frame) SavedRecovered(NotesOriginalPendingResult pending, RecoveryContext recovery)
    {
        var native = (RecoveryNative)recovery.RequirePending(pending);
        var frame = RequireRecovery(native); var context = Crypto(); var physical = NotesOriginalSchema.Text(frame, "physical");
        var key = RecordKey(physical, frame);
        lock (gate)
        {
            if (!recovered.TryGetValue(pending, out var owned) || !ReferenceEquals(owned, recovery)) throw new InvalidOperationException("notes_request_recovery_process_expired");
            using var directory = files.Open() ?? throw new IOException("notes_request_private_history_missing");
            Identity(directory, context.Identity, initialize: false);
            var record = Physical(directory, context.Crypto, physical) ?? throw new IOException("notes_request_physical_history_missing");
            if (record.Key != key || !JsonNode.DeepEquals(record.Frame, frame)) throw new InvalidOperationException("notes_request_recovered_history_changed");
            var archive = directory.Read("r-" + key + ".json", Limit);
            if (archive is null)
            {
                // Only after the actual recovered native save. Repairing the
                // exact archive does not publish a provider-send process nonce.
                directory.Write("r-" + key + ".json", record.Encrypted, Limit); stage("recovered-archive-written");
                archive = directory.Read("r-" + key + ".json", Limit);
            }
            if (archive != record.Encrypted) throw new InvalidOperationException("notes_request_recovered_archive_changed");
        }
        pending.ConfirmedSave(); recovery.RequirePending(pending);
        return (key, context.Identity, frame);
    }
}
