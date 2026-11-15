namespace MagnolieOrganizer.Windows;

internal sealed partial class NotesOriginalController
{
    private sealed record TransportNative(NotesOriginalController Controller, Pins Pins, NotesOriginalNegotiation Protocol,
        Owner? Owner, string Kind, object Invocation);
    internal sealed class TransportPlan(object proof)
    {
        private TransportNative Native() => proof as TransportNative ?? throw new InvalidOperationException("notes_controller_native_transport_plan_required");
        internal string Kind => Native().Kind;
        internal async Task<bool> SendAsync(MagnolienbaumCoordinator coordinator, Func<bool> networkAllowed, CancellationToken cancellation = default)
        {
            var native = Native(); native.Controller.RequirePlan(native);
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellation, native.Controller.stop.Token);
            bool Allowed() { native.Controller.RequirePlan(native); return networkAllowed(); }
            var delivered = native.Invocation switch
            {
                NotesOriginalNegotiation protocol => await coordinator.SendNotesProbeAsync(protocol, Allowed, linked.Token).ConfigureAwait(false),
                NotesOriginalRequestIntents.FreshRequest request => await coordinator.SendNotesRequestAsync(native.Owner!.Pending!, request, native.Protocol, Allowed, linked.Token).ConfigureAwait(false),
                NotesOriginalRequestIntents.UnconfirmedQuery query => await coordinator.SendNotesQueryAsync(query, native.Protocol, Allowed, linked.Token).ConfigureAwait(false),
                NotesOriginalSavedAckIntents.HistoryQuery query => await coordinator.SendNotesQueryAsync(query, native.Protocol, Allowed, linked.Token).ConfigureAwait(false),
                NotesOriginalSavedAckIntents.SavedAck ack => await coordinator.SendNotesSavedAckAsync(ack, native.Protocol, Allowed, linked.Token).ConfigureAwait(false),
                NotesOriginalSavedAckIntents.RestoredAck ack => await coordinator.SendNotesSavedAckAsync(ack, native.Protocol, Allowed, linked.Token).ConfigureAwait(false),
                _ => throw new InvalidOperationException("notes_controller_typed_transport_required")
            };
            native.Controller.RequirePlan(native);
            if (delivered && native.Kind == "ack")
                lock (native.Controller.gate) native.Owner!.AckDelivered = true;
            return delivered; // Delivery only, never terminal/native saved authority.
        }
    }

    private void RequirePlan(TransportNative plan)
    {
        lock (gate)
        {
            RequireActive();
            if (!peers.TryGetValue(plan.Pins, out var current) || !ReferenceEquals(current, plan.Protocol))
                throw new InvalidOperationException("notes_controller_transport_protocol_replaced");
        }
        if (plan.Owner is not null) Guard(plan.Owner);
        else plan.Protocol.NativeProbePins();
    }

    private void RenewExpired()
    {
        // Under serial deferred worker/book gate, never receive or network.
        KeyValuePair<Pins, NotesOriginalNegotiation>[] current;
        lock (gate) { RequireActive(); current = peers.ToArray(); }
        foreach (var pair in current)
        {
            if (!pair.Value.HasOffer) continue;
            try { pair.Value.RequireCurrent(); continue; }
            catch (Exception error) when (Expected(error)) { }
            lock (gate)
            {
                RequireActive(); pair.Value.Cancel();
                var replacement = new NotesOriginalNegotiation(pair.Key.Peer, pair.Key.Own);
                peers[pair.Key] = replacement;
                foreach (var owner in owners.Values.Where(value => value.Source.Pins == pair.Key))
                {
                    if (owner.Pending is not null) requests.ForgetLocalOwnership(owner.Pending);
                    owner.Protocol = replacement;
                    owner.Pending = null; owner.Fresh = null; owner.Recovery = null; owner.Commit = null; owner.Bootstrap = null;
                    owner.Ack = null; owner.Restored = null; owner.History = null; owner.Unconfirmed = null; owner.AckDelivered = false;
                    // Disk holds/result identity remain intact. New offers may
                    // recover by queries, never recreate provider-send authority.
                }
                if (bootstrap?.Frame.Pins == pair.Key) bootstrap = null;
                foreach (var slot in retired.Where(value => value.Value.Pins == pair.Key).Select(value => value.Key).ToArray()) retired.Remove(slot);
                foreach (var frame in frames.Values.Where(value => value.Pins == pair.Key).ToArray()) ForgetFrame(frame);
                foreach (var key in due.Keys.Where(value => value.Pins == pair.Key).ToArray()) due.Remove(key);
            }
        }
    }

    internal async Task<TransportPlan?> NextTransportAsync(CancellationToken cancellation = default)
    {
        await worker.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
            try
            {
                RefreshSources(); RenewExpired();
                var candidates = new List<(Pins Pins, NotesOriginalNegotiation Protocol, Owner? Owner)>();
                lock (gate)
                {
                    foreach (var peer in peers) if (!peer.Value.HasOffer) candidates.Add((peer.Key, peer.Value, null));
                    foreach (var owner in owners.Values.Where(value => !value.Held && value.Protocol.HasOffer)) candidates.Add((owner.Source.Pins, owner.Protocol, owner));
                }
                if (candidates.Count == 0) return null;
                for (var n = 0; n < candidates.Count; n++)
                {
                    var selected = candidates[sendCursor++ % candidates.Count];
                    if (sendCursor == int.MaxValue) sendCursor = 0;
                    var kind = selected.Owner is null ? "probe" : "query";
                    var id = selected.Owner?.Id ?? "";
                    // One deadline per owner, not one per lane: switching lanes
                    // cannot bypass the 30-second retry bound.
                    var key = (selected.Pins, selected.Owner is null ? "probe" : "owner", id);
                    var now = clock();
                    lock (gate) if (due.TryGetValue(key, out var deadline) && now < deadline) continue;
                    try
                    {
                        object invocation;
                        if (selected.Owner is null) invocation = selected.Protocol;
                        else
                        {
                            var owner = selected.Owner; Guard(owner); DemoteStale(owner);
                            if (owner.Commit is not null && owner.AckKey is null) continue; // Await actual native completion, never send a guessed ACK.
                            if (owner.History is null && owner.Unconfirmed is null && owner.Fresh is null)
                            {
                                var saved = outcomes.LoadHeld(NotesOriginalSchema.Hash(owner.Request));
                                if (saved is not null)
                                { owner.AckKey = NotesOriginalSchema.Hash(owner.Request); owner.History = outcomes.ReadOnlyQuery(owner.AckKey, consent, selected.Protocol); }
                                else owner.Unconfirmed = requests.ReadOnlyQuery(owner.Source.Binding, owner.Source.Id, consent, selected.Protocol);
                            }
                            if (!owner.AckDelivered && owner.Restored is not null) { owner.Restored.RequireFor(selected.Protocol); invocation = owner.Restored; kind = "ack"; }
                            else if (!owner.AckDelivered && owner.Ack is not null)
                            {
                                try { owner.Ack.RequireFor(selected.Protocol); invocation = owner.Ack; kind = "ack"; }
                                catch (Exception error) when (Expected(error))
                                { owner.Ack = null; invocation = owner.History ?? throw new InvalidOperationException("notes_controller_genuine_history_required"); }
                            }
                            else if (owner.History is not null) { owner.History.Request(selected.Protocol); invocation = owner.History; }
                            else if (owner.Unconfirmed is not null) { owner.Unconfirmed.Request(selected.Protocol); invocation = owner.Unconfirmed; }
                            else { owner.Fresh!.RequireFor(owner.Pending!, selected.Protocol); invocation = owner.Fresh; kind = "request"; }
                        }
                        var proof = new TransportNative(this, selected.Pins, selected.Protocol, selected.Owner, kind, invocation);
                        RequirePlan(proof);
                        lock (gate) due[key] = now + 30_000;
                        return new(proof);
                    }
                    catch (Exception error) when (Expected(error))
                    { lock (gate) { if (selected.Owner is not null) selected.Owner.Held = true; } Hold("transport-plan"); }
                }
                return null;
            }
            catch (Exception error) when (Expected(error)) { Hold("transport-refresh"); return null; }
            finally { MutationGate.Global.Release(); }
        }
        finally { worker.Release(); }
    }
}
