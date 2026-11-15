using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Explicit native setup acquisition only. Transport/exports are NOT source
// grants. No book/key callback, chooser, writer or publication runs on receive.
internal sealed class NotesOriginalSetupCollector
{
    private sealed record Frame(JsonObject Body, MagnolienbaumCoordinator.NativeNotesOrigin Origin, string Transport);
    private sealed record CandidateProof(NotesOriginalSetupCollector Owner, string Key, Frame Frame);
    internal sealed class Candidate(object proof)
    {
        private CandidateProof Native() => proof as CandidateProof ?? throw new InvalidOperationException("notes_setup_native_candidate_required");
        internal JsonObject Display()
        {
            var native = Native(); native.Owner.RequireCandidate(native.Key, native.Frame);
            return native.Frame.Body.DeepClone().AsObject(); // Untrusted display data only.
        }
        internal MagnolienbaumCoordinator.NotesPins Peer
        {
            get { var native = Native(); native.Owner.RequireCandidate(native.Key, native.Frame); return native.Owner.pins.Peer; }
        }
        internal NotesOriginalExportChoice Choose(NativeActorBookSnapshot snapshot, Func<NativeActorBookSnapshot?> capture,
            Func<IReadOnlyList<JsonObject>, string?> chooseNative)
        {
            var native = Native();
            void Current() => native.Owner.RequireCandidate(native.Key, native.Frame);
            Current();
            return new(native.Frame.Body, native.Frame.Origin, native.Frame.Transport, snapshot, capture, chooseNative, Current);
        }
    }

    private readonly object gate = new();
    private readonly MagnolienbaumCoordinator coordinator;
    private readonly NotesOriginalNegotiation protocol;
    private readonly Func<long> clock;
    private readonly long deadline;
    private readonly int budget;
    private readonly string challenge;
    private readonly (MagnolienbaumCoordinator.NotesPins Peer, MagnolienbaumCoordinator.NotesPins Own) pins;
    private readonly Dictionary<string, Frame> exports = [];
    private readonly HashSet<string> conflicts = [];
    private readonly TaskCompletionSource changed = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Frame? offer;
    private bool active = true, attached;

    internal NotesOriginalSetupCollector(MagnolienbaumCoordinator coordinator, NotesOriginalNegotiation protocol,
        Func<long>? monotonicMilliseconds = null, int budget = 8)
    {
        if (budget is < 1 or > 32) throw new ArgumentOutOfRangeException(nameof(budget));
        this.coordinator = coordinator; this.protocol = protocol; this.budget = budget;
        pins = protocol.NativeProbePins(); challenge = NotesOriginalSchema.Text(protocol.Probe(), "challenge");
        clock = monotonicMilliseconds ?? (() => Environment.TickCount64); deadline = clock() + 120_000;
    }
    private void RequireActive()
    { if (!active || clock() >= deadline) throw new InvalidOperationException("notes_setup_acquisition_expired"); }
    internal void Attach()
    {
        lock (gate) { RequireActive(); if (attached) throw new InvalidOperationException("notes_setup_already_attached"); }
        coordinator.AttachNotesSetup(Stage, Stop);
        lock (gate)
        {
            if (active && clock() < deadline) { attached = true; return; }
        }
        coordinator.DetachNotesSetup(Stop);
        throw new InvalidOperationException("notes_setup_acquisition_expired");
    }
    internal Task<bool> ProbeAsync(Func<bool> wlanAllowed, CancellationToken cancellation = default)
    {
        lock (gate) { RequireActive(); if (!attached) throw new InvalidOperationException("notes_setup_not_attached"); }
        return coordinator.SendNotesProbeAsync(protocol, () =>
        {
            lock (gate) RequireActive();
            return wlanAllowed(); // Existing native policy is a restriction only.
        }, cancellation);
    }
    private bool Stage(JsonObject body, MagnolienbaumCoordinator.NativeNotesOrigin origin, string transport)
    {
        try
        {
            if (origin.RequireCurrent(body, transport) != pins) return false;
            var kind = NotesOriginalSchema.Text(body, "art");
            if (kind == "kontakt_original_aushandlung")
            {
                if (NotesOriginalSchema.Text(body, "challenge") != challenge) return false;
                var expected = protocol.Probe(); expected["antwort"] = true;
                if (!JsonNode.DeepEquals(expected, body)) return false;
                lock (gate)
                {
                    RequireActive(); offer = new(body.DeepClone().AsObject(), origin, transport);
                    if (exports.Count > 0) changed.TrySetResult();
                }
                return true; // Only our challenge, not a worker's ongoing offer.
            }
            if (kind != "kontakt_original_export") return false;
            NotesOriginalExportChoice.ValidateExport(body);
            var key = NotesOriginalSchema.Text(body, "share_id") + ":" + NotesOriginalSchema.Text(body, "setup_id");
            lock (gate)
            {
                RequireActive();
                if (conflicts.Contains(key)) return false;
                if (exports.TryGetValue(key, out var old))
                {
                    if (!JsonNode.DeepEquals(old.Body, body)) { exports.Remove(key); conflicts.Add(key); return false; }
                }
                else if (exports.Count + conflicts.Count >= budget) return false;
                exports[key] = new(body.DeepClone().AsObject(), origin, transport);
                if (offer is not null) changed.TrySetResult(); // Deferred; tolerate export arriving before its offer.
                return true;
            }
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or ArgumentException or System.Security.Cryptography.CryptographicException)
        { return false; }
    }
    internal async Task<IReadOnlyList<Candidate>> WaitAsync(CancellationToken cancellation)
    {
        long remaining;
        lock (gate) { RequireActive(); remaining = deadline - clock(); }
        await changed.Task.WaitAsync(TimeSpan.FromMilliseconds(remaining), cancellation).ConfigureAwait(false);
        return Candidates();
    }
    internal IReadOnlyList<Candidate> Candidates()
    {
        Frame? negotiated; KeyValuePair<string, Frame>[] frames;
        lock (gate) { RequireActive(); negotiated = offer; frames = exports.ToArray(); }
        if (negotiated is null) throw new InvalidOperationException("notes_setup_protocol_offer_required");
        protocol.Accept(negotiated.Body, negotiated.Origin, negotiated.Transport);
        protocol.RequireCurrent();
        return frames.Select(pair =>
        {
            RequireCandidate(pair.Key, pair.Value);
            return new Candidate(new CandidateProof(this, pair.Key, pair.Value));
        }).ToArray();
    }
    private void RequireCandidate(string key, Frame frame)
    {
        void Current()
        {
            lock (gate)
            {
                RequireActive();
                if (!attached || !exports.TryGetValue(key, out var current) || !ReferenceEquals(current, frame) || conflicts.Contains(key))
                    throw new InvalidOperationException("notes_setup_candidate_changed");
            }
        }
        Current(); protocol.RequireCurrent();
        if (frame.Origin.RequireCurrent(frame.Body, frame.Transport) != pins) throw new InvalidOperationException("notes_setup_peer_changed");
        Current();
    }
    internal void Stop()
    {
        lock (gate) { if (!active) return; active = false; attached = false; exports.Clear(); conflicts.Clear(); offer = null; }
        changed.TrySetCanceled(); protocol.Cancel();
        coordinator.DetachNotesSetup(Stop); // Outside collector gate; owned/idempotent detach only.
    }
}
