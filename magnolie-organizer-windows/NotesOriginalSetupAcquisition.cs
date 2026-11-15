namespace MagnolieOrganizer.Windows;

// Explicit native peer selection/acquisition only, no startup/renderer registration.
internal sealed class NotesOriginalSetupAcquisition
{
    private readonly NotesOriginalSetupFlow flow;
    private readonly NotesOriginalChoiceStore.SetupDecision decision;
    private readonly NotesOriginalSetupCollector collector;
    private readonly Action current;
    private readonly Func<bool> wlan;
    private NotesOriginalSetupAcquisition(NotesOriginalSetupFlow flow, NotesOriginalChoiceStore.SetupDecision decision,
        NotesOriginalSetupCollector collector, Action current, Func<bool> wlan)
    { this.flow = flow; this.decision = decision; this.collector = collector; this.current = current; this.wlan = wlan; }
    internal bool IsActive { get { try { collector.RequireAttached(); return true; } catch (InvalidOperationException) { return false; } } }

    internal static async Task<NotesOriginalSetupAcquisition?> BeginAsync(NotesOriginalSetupFlow flow, MagnolienbaumCoordinator coordinator,
        Func<IReadOnlyList<MagnolienbaumCoordinator.NotesSetupPeerView>, CancellationToken, Task<string?>> choosePeer,
        Action requireUsable, Func<bool> wlanAllowed, CancellationToken cancellation = default)
    {
        ArgumentNullException.ThrowIfNull(flow); ArgumentNullException.ThrowIfNull(coordinator);
        ArgumentNullException.ThrowIfNull(choosePeer); ArgumentNullException.ThrowIfNull(requireUsable); ArgumentNullException.ThrowIfNull(wlanAllowed);
        var decision = await flow.BeginAsync(cancellation).ConfigureAwait(false);
        NotesOriginalSetupCollector? collector = null;
        try
        {
            requireUsable();
            var peers = coordinator.CaptureNotesSetupPeers();
            var views = peers.Select(peer => peer.Display()).ToArray();
            var ids = views.Select(view => view.Id).ToArray(); // Independent of a chooser replacing display array elements.
            var id = await choosePeer(views, cancellation).ConfigureAwait(false); // Outside all native gates.
            cancellation.ThrowIfCancellationRequested();
            if (id is null) { decision.Cancel(); return null; }
            var matches = peers.Where((peer, index) => ids[index] == id).ToArray();
            if (matches.Length != 1) throw new InvalidOperationException("notes_setup_explicit_native_peer_required");
            var selected = matches[0];
            void Current() { requireUsable(); selected.RequireCurrent(coordinator); }
            await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
            try
            {
                flow.RequireDecision(decision); Current();
                var pins = selected.RequireCurrent(coordinator);
                collector = new(coordinator, new(pins.Peer, pins.Own), requireNativeContext: Current);
                collector.Attach();
                cancellation.ThrowIfCancellationRequested();
            }
            finally { MutationGate.Global.Release(); }
            return new(flow, decision, collector, Current, wlanAllowed);
        }
        catch { decision.Cancel(); collector?.Stop(); throw; }
    }

    private async Task CheckAsync(CancellationToken cancellation)
    {
        collector.RequireAttached();
        await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
        try { flow.RequireDecision(decision); current(); }
        finally { MutationGate.Global.Release(); }
    }
    internal Task ValidateAsync(CancellationToken cancellation) => CheckAsync(cancellation); // Read guard only, no grant.
    internal async Task<bool> ProbeAsync(CancellationToken cancellation = default)
    {
        try
        {
            await CheckAsync(cancellation).ConfigureAwait(false);
            var delivered = await collector.ProbeAsync(() =>
            {
                if (!MutationGate.Global.Wait(0)) return false; // Busy is a restriction, never wait under a network callback.
                try { flow.RequireDecision(decision); current(); }
                finally { MutationGate.Global.Release(); }
                return wlan();
            }, cancellation).ConfigureAwait(false);
            await CheckAsync(cancellation).ConfigureAwait(false);
            return delivered;
        }
        catch { Stop(); throw; }
    }
    internal async Task<IReadOnlyList<NotesOriginalSetupCollector.Candidate>> WaitAsync(CancellationToken cancellation)
    {
        try
        {
            var candidates = await collector.WaitAsync(cancellation).ConfigureAwait(false);
            await CheckAsync(cancellation).ConfigureAwait(false);
            return candidates;
        }
        catch { Stop(); throw; }
    }
    internal async Task<bool> ConfigureAsync(NotesOriginalSetupCollector.Candidate candidate,
        Func<NotesOriginalSetupFlow.View, CancellationToken, Task<string?>> chooseContact, CancellationToken cancellation = default)
    {
        ArgumentNullException.ThrowIfNull(candidate); ArgumentNullException.ThrowIfNull(chooseContact);
        try { await CheckAsync(cancellation).ConfigureAwait(false); }
        catch { Stop(); throw; }
        candidate.RequireOwner(collector); // Foreign input must not consume this native acquisition.
        try { return await flow.ConfigureAsync(candidate, chooseContact, cancellation, decision).ConfigureAwait(false); }
        finally { Stop(); }
    }
    internal void Stop() { collector.Stop(); decision.Cancel(); } // Owned memory only; persistent consent/history survive.
}
