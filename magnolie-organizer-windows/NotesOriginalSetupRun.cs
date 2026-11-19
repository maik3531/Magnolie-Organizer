using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Explicit acquired setup -> caller-owned worker -> one-use native UI dispatch.
// No constructor thread/service/action registration. Status is NOT authority.
internal sealed class NotesOriginalSetupRun : IDisposable
{
    internal sealed record SelectionView(MagnolienbaumCoordinator.NotesPins Peer, JsonObject Export);
    private readonly object gate = new();
    private readonly Func<Func<Task>, bool> postUi;
    private readonly Func<bool> isUiThread;
    private readonly Func<IReadOnlyList<SelectionView>, CancellationToken, Task<int?>> chooseSource;
    private readonly Func<NotesOriginalSetupFlow.View, CancellationToken, Task<string?>> chooseContact;
    private readonly Action<string> finished;
    private readonly CancellationTokenSource lifetime = new();
    private readonly object lifetimeGate = new();
    private bool lifetimeDisposed;
    private readonly CancellationToken token;
    private readonly TaskCompletionSource done = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource quiesced = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int activeWork;
    private NotesOriginalSetupAcquisition? acquisition;
    private IReadOnlyList<NotesOriginalSetupCollector.Candidate> candidates = [];
    private readonly Dictionary<object, IUiRequest> requests = [];
    private readonly HashSet<object> dispatchedRequests = [];
    private object? pending, notice;
    private string phase = "created";
    private static bool Terminal(string value) => value is "configured" or "cancelled" or "waiting-network" or "held";

    internal NotesOriginalSetupRun(NotesOriginalSetupAcquisition acquisition, Func<Func<Task>, bool> postUi,
        Func<bool> isUiThread, Func<IReadOnlyList<SelectionView>, CancellationToken, Task<int?>> chooseSource,
        Func<NotesOriginalSetupFlow.View, CancellationToken, Task<string?>> chooseContact, Action<string> finished)
    {
        ArgumentNullException.ThrowIfNull(acquisition); ArgumentNullException.ThrowIfNull(postUi);
        ArgumentNullException.ThrowIfNull(isUiThread); ArgumentNullException.ThrowIfNull(chooseSource);
        ArgumentNullException.ThrowIfNull(chooseContact); ArgumentNullException.ThrowIfNull(finished);
        this.acquisition = acquisition; this.postUi = postUi; this.isUiThread = isUiThread;
        this.chooseSource = chooseSource; this.chooseContact = chooseContact; this.finished = finished;
        token = lifetime.Token;
    }
    internal string Phase { get { lock (gate) return phase; } }
    internal Task Done => done.Task;
    internal Task Quiesced => quiesced.Task; // Terminal cleanup AND all started worker/UI callbacks returned.
    internal bool RetainsPendingData { get { lock (gate) return acquisition is not null || candidates.Count != 0 || requests.Count != 0; } }

    internal async Task RunAsync()
    {
        NotesOriginalSetupAcquisition current;
        lock (gate)
        {
            if (phase != "created") return;
            phase = "probing"; current = acquisition!; activeWork++;
        }
        try
        {
            if (isUiThread()) { Finish("held"); return; }
            if (!await current.ProbeAsync(token).ConfigureAwait(false)) { Finish("waiting-network"); return; }
            lock (gate) { if (Terminal(phase)) return; phase = "waiting-export"; }
            var found = await current.WaitAsync(token).ConfigureAwait(false);
            var owner = new object();
            lock (gate)
            {
                if (Terminal(phase)) return;
                candidates = found; pending = owner; phase = "offering";
            }
            if (!postUi(() => ChooseUiAsync(owner))) Finish("held"); // Queued closure retains no candidate snapshots.
        }
        catch { Finish("held"); }
        finally { ExitWork(); }
    }

    private async Task ChooseUiAsync(object owner)
    {
        NotesOriginalSetupAcquisition current; IReadOnlyList<NotesOriginalSetupCollector.Candidate> found;
        lock (gate)
        {
            if (pending != owner || phase != "offering") return;
            current = acquisition!; found = candidates; candidates = []; pending = null; phase = "choosing"; activeWork++;
        }
        try
        {
            if (!isUiThread()) { Finish("held"); return; }
            await current.ValidateAsync(token);
            var valid = new List<NotesOriginalSetupCollector.Candidate>(); var views = new List<SelectionView>();
            foreach (var candidate in found)
            {
                try { var view = new SelectionView(candidate.Peer, candidate.Display()); valid.Add(candidate); views.Add(view); }
                catch (Exception error) when (error is InvalidOperationException or InvalidDataException or System.Security.Cryptography.CryptographicException) { }
            }
            if (valid.Count == 0) { Finish("held"); return; }
            var index = await OnUiAsync(() => chooseSource(views, token));
            if (index is null) { Cancel(); return; }
            if (index < 0 || index >= valid.Count) throw new InvalidOperationException("notes_setup_native_source_selection_required");
            var configured = await current.ConfigureAsync(valid[index.Value], (view, cancellation) =>
                OnUiAsync(() => chooseContact(view, cancellation)), token);
            Finish(configured ? "configured" : "cancelled");
        }
        catch { Finish("held"); }
        finally { ExitWork(); }
    }

    private interface IUiRequest
    {
        Task ExecuteAsync();
        void Cancel();
    }
    private sealed class UiRequest<T>(Func<Task<T>> action) : IUiRequest
    {
        private Func<Task<T>>? action = action;
        internal readonly TaskCompletionSource<T> Completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task ExecuteAsync()
        {
            var invoke = Interlocked.Exchange(ref action, null);
            if (invoke is null || Completion.Task.IsCompleted) return;
            try { Completion.TrySetResult(await invoke()); }
            catch (OperationCanceledException) { Completion.TrySetCanceled(); }
            catch (Exception error) { Completion.TrySetException(error); }
        }
        public void Cancel() { Interlocked.Exchange(ref action, null); Completion.TrySetCanceled(); }
    }
    private Task<T> OnUiAsync<T>(Func<Task<T>> action)
    {
        token.ThrowIfCancellationRequested();
        if (isUiThread()) return action();
        var owner = new object(); var request = new UiRequest<T>(action);
        lock (gate)
        {
            if (Terminal(phase)) return Task.FromCanceled<T>(new CancellationToken(true));
            requests.Add(owner, request);
        }
        try
        {
            if (!postUi(() => DispatchRequestAsync(owner))) { request.Cancel(); Finish("held"); }
        }
        catch { request.Cancel(); Finish("held"); }
        return request.Completion.Task;
    }
    private async Task DispatchRequestAsync(object owner)
    {
        IUiRequest? request;
        lock (gate)
        {
            if (Terminal(phase) || !requests.TryGetValue(owner, out request) || !dispatchedRequests.Add(owner)) return;
            activeWork++;
        }
        try
        {
            if (!isUiThread()) { Finish("held"); return; }
            await request.ExecuteAsync();
        }
        finally
        {
            lock (gate) { requests.Remove(owner); dispatchedRequests.Remove(owner); }
            ExitWork();
        }
    }

    internal void Cancel() => Finish("cancelled");
    private void Finish(string result)
    {
        NotesOriginalSetupAcquisition? current; IUiRequest[] queued; object owner;
        lock (gate)
        {
            if (Terminal(phase)) return;
            phase = result; current = acquisition; acquisition = null; candidates = []; pending = null;
            queued = requests.Values.ToArray(); requests.Clear(); dispatchedRequests.Clear(); owner = notice = new object();
        }
        try
        {
            CancelLifetime(false);
            foreach (var request in queued) request.Cancel();
            current?.Stop(); // No callbacks/IO under the run lock, no disk/history release.
        }
        finally { done.TrySetResult(); TryQuiesce(); }
        try
        {
            postUi(() =>
            {
                lock (gate) { if (notice != owner) return Task.CompletedTask; notice = null; }
                if (isUiThread()) { try { finished(result); } catch { } }
                return Task.CompletedTask;
            });
        }
        catch { } // A closed UI cannot retain candidate authority or snapshots.
    }
    private void ExitWork()
    {
        lock (gate) activeWork--;
        TryQuiesce();
    }
    private void TryQuiesce()
    {
        lock (gate)
        {
            if (done.Task.IsCompleted && activeWork == 0) quiesced.TrySetResult();
        }
    }
    private void CancelLifetime(bool dispose)
    {
        lock (lifetimeGate)
        {
            if (lifetimeDisposed) return;
            try { lifetime.Cancel(); } catch (AggregateException) { }
            if (dispose) { lifetimeDisposed = true; lifetime.Dispose(); }
        }
    }
    public void Dispose() { Cancel(); CancelLifetime(true); }
}
