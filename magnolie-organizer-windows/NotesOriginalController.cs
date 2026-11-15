using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Explicit native injection only. Receive stages bounded authenticated frames;
// the deferred worker alone reads private state/uses the native book gate.
// Writer offers must join the actual UI/SavedBook CAS lane, never write around
// unsaved renderer edits. Cached readiness is an extra restriction, not consent.
internal sealed partial class NotesOriginalController
{
    private readonly record struct Pins(MagnolienbaumCoordinator.NotesPins Peer, MagnolienbaumCoordinator.NotesPins Own);
    private sealed record Source(string Binding, JsonObject Value, Pins Pins)
    { internal string Id => NotesOriginalSchema.Text(Value, "local_id"); }
    private sealed record Frame(Pins Pins, JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport, string Key);
    private sealed class Owner(Source source, NotesOriginalNegotiation protocol, JsonObject request)
    {
        internal readonly Source Source = source;
        internal NotesOriginalNegotiation Protocol = protocol;
        internal readonly JsonObject Request = request;
        internal string Id => NotesOriginalSchema.Text(Request, "request_id");
        internal NotesOriginalPendingResult? Pending;
        internal NotesOriginalRequestIntents.FreshRequest? Fresh;
        internal NotesOriginalRequestIntents.UnconfirmedQuery? Unconfirmed;
        internal NotesOriginalRequestIntents.RecoveryContext? Recovery;
        internal NotesOriginalSavedAckIntents.HistoryQuery? History;
        internal NotesOriginalSavedAckIntents.SavedAck? Ack;
        internal NotesOriginalSavedAckIntents.RestoredAck? Restored;
        internal NotesOriginalPendingResult.NativeCommit? Commit;
        internal NotesOriginalBootstrapSave? Bootstrap;
        internal string? AckKey;
        internal string? ResultHash;
        internal bool Held, AckDelivered;
    }
    internal sealed record Work(string Kind, object? Invocation = null, string RequestId = "");
    private sealed record BootstrapLease(NotesOriginalBootstrapSave Invocation, Frame Frame, Owner? Owner);
    private readonly NotesOriginalChoiceStore consent;
    private readonly NotesOriginalRequestIntents requests;
    private readonly NotesOriginalSavedAckIntents outcomes;
    private readonly ContactSourceSavedCommit commit;
    private readonly Func<bool> ready;
    private readonly Func<long> clock;
    private readonly object gate = new();
    private readonly SemaphoreSlim worker = new(1, 1);
    private readonly CancellationTokenSource stop = new();
    private readonly Dictionary<Pins, NotesOriginalNegotiation> peers = [];
    private readonly Dictionary<(Pins Pins, string Id), Owner> owners = [];
    private readonly Dictionary<(string Binding, string Id), Owner> physical = [];
    private readonly Dictionary<(string Binding, string Id), (Pins Pins, NotesOriginalSavedAckIntents.TerminalProof Proof)> retired = [];
    private readonly Dictionary<(Pins Pins, string Key), Frame> frames = [];
    private readonly LinkedList<(Pins Pins, string Key)> order = [];
    private readonly Queue<string> held = [];
    private readonly Dictionary<(Pins Pins, string Kind, string Id), long> due = [];
    private Source[] sources = [];
    private BootstrapLease? bootstrap;
    private bool active = true;
    private int discoveryCursor, sendCursor;
    private readonly int maxPeers, perPeer;

    internal NotesOriginalController(NotesOriginalChoiceStore consent, NotesOriginalRequestIntents requests,
        NotesOriginalSavedAckIntents outcomes, ContactSourceSavedCommit commit, Func<bool> nativeReady,
        int maxPeers = 8, int perPeer = 8, Func<long>? monotonicMilliseconds = null)
    {
        if (maxPeers is < 1 or > 32 || perPeer is < 1 or > 32) throw new ArgumentOutOfRangeException();
        this.consent = consent; this.requests = requests; this.outcomes = outcomes; this.commit = commit;
        ready = nativeReady ?? throw new ArgumentNullException(nameof(nativeReady)); this.maxPeers = maxPeers; this.perPeer = perPeer;
        clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
    }
    private static bool Expected(Exception error) => error is InvalidOperationException or InvalidDataException or IOException or UnauthorizedAccessException or CryptographicException or JsonException or ArgumentException or FormatException or NotSupportedException;
    private void RequireActive() { if (!active) throw new InvalidOperationException("notes_controller_stopped"); }
    private void Hold(string kind) { lock (gate) { if (held.Count == maxPeers * perPeer) held.Dequeue(); held.Enqueue(kind); } }
    internal (int Queued, int Owners, int Held, int Peers) Counts { get { lock (gate) return (frames.Count, owners.Count, held.Count, peers.Count); } }
    internal Work ProbeOne()
    {
        lock (gate)
        {
            RequireActive();
            var protocol = peers.Values.FirstOrDefault(value => !value.HasOffer);
            return protocol is null ? new("waiting") : new("probe", protocol);
        }
    } // Native protocol object only; actual sending still uses reserved typed lanes.
    private static Pins SourcePins(JsonObject source) => new(new(source["peer"]![0]!.GetValue<string>(), source["peer"]![1]!.GetValue<string>()),
        new(source["own"]![0]!.GetValue<string>(), source["own"]![1]!.GetValue<string>()));

    internal bool Stage(JsonObject peer, JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        // Actual FS1 receive only. No key/book/readiness callback or file IO.
        try
        {
            var verified = origin.RequireCurrent(body, transport); var pins = new Pins(verified.Peer, verified.Own);
            var kind = NotesOriginalSchema.Text(body, "art");
            if (kind is not ("kontakt_original_aushandlung" or "kontakt_original_export" or "kontakt_original_ergebnis" or "kontakt_original_abschlussstatus")) return false;
            if (MagnolienbaumCrypto.Canonical(body).Length > 256 * 1024) return false;
            var identity = kind == "kontakt_original_export" ? NotesOriginalSchema.Text(body, "share_id") + ":" + NotesOriginalSchema.Text(body, "setup_id") :
                kind == "kontakt_original_aushandlung" ? "offer" : NotesOriginalSchema.Text(body, "request_id");
            if (identity.Length is < 1 or > 512) return false;
            var key = kind + ":" + identity;
            lock (gate)
            {
                RequireActive(); if (!peers.ContainsKey(pins)) return false;
                if (kind == "kontakt_original_ergebnis" && owners.TryGetValue((pins, identity), out var known) && known.ResultHash is not null &&
                    known.ResultHash != NotesOriginalSchema.Hash(body))
                { known.Held = true; Hold("conflicting-result"); return false; }
                if (frames.TryGetValue((pins, key), out var prior))
                {
                    if (kind is "kontakt_original_ergebnis" or "kontakt_original_abschlussstatus" && !JsonNode.DeepEquals(prior.Body, body))
                    {
                        if (owners.TryGetValue((pins, identity), out var owner)) owner.Held = true;
                        Hold("conflicting-result"); return false;
                    }
                    frames[(pins, key)] = new(pins, body.DeepClone().AsObject(), origin, transport, key); return true;
                }
                if (frames.Count(pair => pair.Key.Pins == pins) >= perPeer) return false;
                frames.Add((pins, key), new(pins, body.DeepClone().AsObject(), origin, transport, key)); order.AddLast((pins, key)); return true;
            }
        }
        catch (Exception error) when (Expected(error)) { return false; }
    }

    private void RefreshSources()
    {
        var selected = consent.DiscoverySources();
        Source[] current = selected is null ? [] : selected.Value.Sources.Select(value => new Source(selected.Value.Binding, value, SourcePins(value))).ToArray();
        var allowed = current.Select(source => source.Pins).ToHashSet();
        lock (gate)
        {
            RequireActive(); sources = current;
            foreach (var pins in peers.Keys.Where(pins => !allowed.Contains(pins)).ToArray())
            {
                peers[pins].Cancel(); peers.Remove(pins);
                foreach (var owner in owners.Values.Where(owner => owner.Source.Pins == pins).ToArray()) Drop(owner);
                foreach (var frame in frames.Values.Where(value => value.Pins == pins).ToArray()) ForgetFrame(frame);
                foreach (var key in due.Keys.Where(value => value.Pins == pins).ToArray()) due.Remove(key);
            }
            foreach (var owner in owners.Values.Where(owner => !current.Any(source => source.Binding == owner.Source.Binding &&
                         JsonNode.DeepEquals(source.Value, owner.Source.Value))).ToArray()) Drop(owner);
            foreach (var slot in retired.Keys.Where(slot => !current.Any(source => source.Binding == slot.Binding && source.Id == slot.Id)).ToArray()) retired.Remove(slot);
            foreach (var pins in current.Select(source => source.Pins).Distinct())
                if (peers.Count < maxPeers && !peers.ContainsKey(pins)) peers.Add(pins, new(pins.Peer, pins.Own));
        }
    }
    private void Guard(Owner owner, NotesOriginalPendingResult? pending = null)
    {
        NotesOriginalNegotiation protocol;
        lock (gate)
        {
            RequireActive();
            if (owner.Held || !owners.TryGetValue((owner.Source.Pins, owner.Id), out var current) || !ReferenceEquals(current, owner) ||
                !physical.TryGetValue((owner.Source.Binding, owner.Source.Id), out current) || !ReferenceEquals(current, owner) ||
                !peers.TryGetValue(owner.Source.Pins, out protocol!) || !ReferenceEquals(protocol, owner.Protocol) ||
                pending is not null && !ReferenceEquals(owner.Pending, pending))
                throw new InvalidOperationException("notes_controller_owned_context_required");
        }
        protocol.RequireCurrent(); // Never hold registry gate across tree/native callbacks.
    }
    private void ExportGuard(Frame frame, NotesOriginalNegotiation protocol)
    {
        lock (gate)
        {
            RequireActive();
            if (!peers.TryGetValue(frame.Pins, out var current) || !ReferenceEquals(current, protocol) ||
                !frames.TryGetValue((frame.Pins, frame.Key), out var queued) || !ReferenceEquals(queued, frame))
                throw new InvalidOperationException("notes_controller_export_replaced");
        }
        protocol.RequireCurrent();
    }
    private void Add(Owner owner)
    {
        lock (gate)
        {
            RequireActive();
            if (owners.Count(pair => pair.Key.Pins == owner.Source.Pins) >= perPeer || physical.ContainsKey((owner.Source.Binding, owner.Source.Id)))
                throw new InvalidOperationException("notes_controller_physical_owner_held");
            owners.Add((owner.Source.Pins, owner.Id), owner); physical.Add((owner.Source.Binding, owner.Source.Id), owner);
        }
    }
    private void Drop(Owner owner)
    {
        owner.Held = true; owners.Remove((owner.Source.Pins, owner.Id)); physical.Remove((owner.Source.Binding, owner.Source.Id));
        due.Remove((owner.Source.Pins, "owner", owner.Id));
        if (owner.Pending is not null) requests.ForgetLocalOwnership(owner.Pending); // Memory only, no durable hold release.
    }
    private void ForgetFrame(Frame frame)
    {
        lock (gate) if (frames.TryGetValue((frame.Pins, frame.Key), out var current) && ReferenceEquals(current, frame))
        { frames.Remove((frame.Pins, frame.Key)); var node = order.Find((frame.Pins, frame.Key)); if (node is not null) order.Remove(node); }
    }
    private Frame? FirstFrame()
    {
        lock (gate)
        {
            RequireActive();
            while (order.First is not null)
            {
                var key = order.First.Value; if (frames.TryGetValue(key, out var frame)) return frame;
                order.RemoveFirst();
            }
            return null;
        }
    }
    private void Defer(Frame frame)
    {
        lock (gate) if (frames.TryGetValue((frame.Pins, frame.Key), out var current) && ReferenceEquals(current, frame))
        { var node = order.Find((frame.Pins, frame.Key)); if (node is not null) order.Remove(node); order.AddLast((frame.Pins, frame.Key)); }
    }
    private bool SaveBusy() { lock (gate) return bootstrap is not null || owners.Values.Any(owner => !owner.Held && owner.Commit is not null && owner.AckKey is null); }

    internal async Task<Work> ProcessOneAsync(CancellationToken cancellation = default)
    {
        await worker.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
            try
            {
                try { RefreshSources(); RenewExpired(); }
                catch (Exception error) when (Expected(error)) { Hold("source-refresh"); return new("held"); }
                var frame = FirstFrame(); if (frame is null) return DiscoverOne();
                try
                {
                    frame.Origin.RequireCurrent(frame.Body, frame.Transport);
                    NotesOriginalNegotiation protocol; lock (gate) protocol = peers[frame.Pins];
                    var kind = NotesOriginalSchema.Text(frame.Body, "art");
                    if (kind == "kontakt_original_aushandlung")
                    { protocol.Accept(frame.Body, frame.Origin, frame.Transport); ForgetFrame(frame); return new("negotiated"); }
                    protocol.RequireCurrent();
                    if (kind == "kontakt_original_export")
                    {
                        if (!ready() || SaveBusy()) { Defer(frame); return new("waiting"); }
                        var source = sources.Single(value => value.Pins == frame.Pins && NotesOriginalSchema.Text(value.Value, "share_id") == NotesOriginalSchema.Text(frame.Body, "share_id") &&
                            NotesOriginalSchema.Text(value.Value, "setup_id") == NotesOriginalSchema.Text(frame.Body, "setup_id"));
                        lock (gate) if (physical.ContainsKey((source.Binding, source.Id))) { ForgetFrame(frame); return new("waiting"); }
                        var context = consent.ExportBootstrap(frame.Body, frame.Origin, frame.Transport);
                        context.AttachOwnerGuard(() => ExportGuard(frame, protocol));
                        NotesOriginalExportChoice choice;
                        try { choice = context.Restore(); }
                        catch (NotesOriginalChoiceStore.ExportNeedsRealSave)
                        {
                            var invocation = context.PrepareBootstrap(); lock (gate) bootstrap = new(invocation, frame, null);
                            Defer(frame); return new("bootstrap", invocation);
                        }
                        var pending = choice.CreatePending();
                        if (pending is null) { ForgetFrame(frame); return new("unchanged"); }
                        var owner = new Owner(source, protocol, pending.Request()) { Pending = pending }; Add(owner);
                        pending.AttachOwnerGuard(() => Guard(owner, pending));
                        try
                        {
                            NotesOriginalSavedAckIntents.TerminalProof? previous;
                            lock (gate) previous = retired.TryGetValue((source.Binding, source.Id), out var release) ? release.Proof : null;
                            owner.Fresh = requests.Seal(pending, previous);
                            lock (gate) retired.Remove((source.Binding, source.Id));
                        }
                        catch { lock (gate) Drop(owner); throw; }
                        ForgetFrame(frame); return new("request", pending, owner.Id);
                    }
                    Owner selected; lock (gate) selected = owners[(frame.Pins, NotesOriginalSchema.Text(frame.Body, "request_id"))];
                    Guard(selected);
                    if (selected.History is not null)
                    {
                        var firstRestored = selected.Restored is null;
                        selected.Restored = outcomes.Reauthorize(selected.History, frame.Body, frame.Origin, frame.Transport, protocol);
                        selected.AckDelivered = false;
                        if (firstRestored) lock (gate) due.Remove((selected.Source.Pins, "owner", selected.Id));
                        if (selected.Restored.TerminalConfirmed())
                        {
                            var terminal = outcomes.SealTerminal(selected.Restored); requests.Retire(terminal);
                            lock (gate) { retired[(selected.Source.Binding, selected.Source.Id)] = (selected.Source.Pins, terminal); Drop(selected); }
                            ForgetFrame(frame); return new("settled", terminal, selected.Id);
                        }
                        ForgetFrame(frame); return new("ack", selected.Restored, selected.Id);
                    }
                    if (!ready() || SaveBusy() && selected.Commit is null) { Defer(frame); return new("waiting"); }
                    if (selected.Commit is not null) { ForgetFrame(frame); return new("duplicate", selected.Commit, selected.Id); }
                    DemoteStale(selected);
                    if (selected.Pending is null)
                    {
                        selected.Unconfirmed ??= requests.ReadOnlyQuery(selected.Source.Binding, selected.Source.Id, consent, protocol);
                        var context = requests.Recover(selected.Unconfirmed, frame.Body, frame.Origin, frame.Transport, protocol);
                        selected.Recovery = context; context.AttachOwnerGuard(() => Guard(selected));
                        try { selected.Pending = context.Resume(); }
                        catch (NotesOriginalRequestIntents.RecoveryNeedsRealSave)
                        {
                            var invocation = context.PrepareBootstrap(); selected.Bootstrap = invocation;
                            lock (gate) bootstrap = new(invocation, frame, selected); Defer(frame); return new("bootstrap", invocation, selected.Id);
                        }
                        var recoveredPending = selected.Pending; recoveredPending.AttachOwnerGuard(() => Guard(selected, recoveredPending));
                    }
                    else if (selected.Recovery is null) selected.Pending.StageResult(frame.Body, frame.Origin, frame.Transport);
                    selected.ResultHash = NotesOriginalSchema.Hash(frame.Body);
                    selected.Commit = selected.Pending.PrepareCommit(commit);
                    ForgetFrame(frame); return new("save", selected.Commit, selected.Id);
                }
                catch (Exception error) when (Expected(error) || error is KeyNotFoundException)
                { ForgetFrame(frame); Hold(NotesOriginalSchema.Text(frame.Body, "art")); return new("held"); }
            }
            finally { MutationGate.Global.Release(); }
        }
        finally { worker.Release(); }
    }

    private void DemoteStale(Owner owner)
    {
        if (owner.Pending is null || owner.Commit is not null || owner.AckKey is not null || owner.Pending.BeforeSnapshotCurrent()) return;
        Guard(owner); var previous = owner.Pending;
        requests.ForgetLocalOwnership(previous); owner.Pending = null; owner.Fresh = null;
        owner.Unconfirmed = requests.ReadOnlyQuery(owner.Source.Binding, owner.Source.Id, consent, owner.Protocol);
    }

    internal void AfterNativeSave(Work work)
    {
        // Caller is the actual serial native save/ack lane under its book gate,
        // not a renderer saved Boolean. No networking takes place here.
        if (work.Kind == "bootstrap" && work.Invocation is NotesOriginalBootstrapSave invocation)
        {
            BootstrapLease lease;
            lock (gate) { RequireActive(); lease = bootstrap is not null && ReferenceEquals(bootstrap.Invocation, invocation) ? bootstrap : throw new InvalidOperationException("notes_controller_owned_bootstrap_required"); }
            try { invocation.RequireCompleted(); }
            catch { lock (gate) bootstrap = null; ForgetFrame(lease.Frame); if (lease.Owner is not null) lease.Owner.Held = true; Hold("bootstrap"); throw; }
            lock (gate) bootstrap = null; return;
        }
        if (work.Kind != "save" || work.Invocation is not NotesOriginalPendingResult.NativeCommit native) throw new InvalidOperationException("notes_controller_native_save_work_required");
        Owner owner;
        lock (gate) { RequireActive(); owner = owners.Values.Single(value => ReferenceEquals(value.Commit, native) && value.Id == work.RequestId); }
        try
        {
            Guard(owner, owner.Pending); owner.Ack = outcomes.Seal(owner.Pending!); owner.AckKey = NotesOriginalSchema.Hash(owner.Request); owner.AckDelivered = false;
            owner.History = outcomes.ReadOnlyQuery(owner.AckKey, consent, owner.Protocol);
            lock (gate) due.Remove((owner.Source.Pins, "owner", owner.Id)); // New genuine save authority, not a retry of the request phase.
        }
        catch { lock (gate) Drop(owner); Hold("save"); throw; } // Free only memory lane; durable slot is rediscovered read-only.
    }

    internal void Stop()
    {
        lock (gate)
        {
            if (!active) return; active = false;
            foreach (var protocol in peers.Values) protocol.Cancel();
            frames.Clear(); order.Clear(); owners.Clear(); physical.Clear(); retired.Clear(); peers.Clear(); due.Clear(); bootstrap = null;
        }
        stop.Cancel(); requests.Stop(); outcomes.Stop();
    }
}
