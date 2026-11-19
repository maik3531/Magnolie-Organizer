namespace MagnolieOrganizer.Windows;

// Explicit application-owned setup lifetime. Construction starts nothing; only
// StartAsync invokes preparation, then the supplied owned worker scheduler.
internal sealed class NotesOriginalSetupHost : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly CancellationTokenSource lifetime = new();
    private readonly object lifetimeGate = new();
    private bool lifetimeDisposed;
    private int noticeUsed;
    private readonly TaskCompletionSource<string> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly Func<CancellationToken, Task<NotesOriginalSetupAcquisition?>> begin;
    private readonly Func<Func<Task>, Task> launchWorker;
    private readonly Func<Func<Task>, bool> postUi;
    private readonly Func<bool> isUiThread;
    private readonly Func<IReadOnlyList<NotesOriginalSetupRun.SelectionView>, CancellationToken, Task<int?>> chooseSource;
    private readonly Func<NotesOriginalSetupFlow.View, CancellationToken, Task<string?>> chooseContact;
    private readonly Action<string> finished;
    private NotesOriginalSetupRun? activeRun;
    private bool started, stopped;

    internal NotesOriginalSetupHost(Func<CancellationToken, Task<NotesOriginalSetupAcquisition?>> begin,
        Func<Func<Task>, Task> launchWorker, Func<Func<Task>, bool> postUi, Func<bool> isUiThread,
        Func<IReadOnlyList<NotesOriginalSetupRun.SelectionView>, CancellationToken, Task<int?>> chooseSource,
        Func<NotesOriginalSetupFlow.View, CancellationToken, Task<string?>> chooseContact, Action<string> finished)
    {
        ArgumentNullException.ThrowIfNull(begin); ArgumentNullException.ThrowIfNull(launchWorker);
        ArgumentNullException.ThrowIfNull(postUi); ArgumentNullException.ThrowIfNull(isUiThread);
        ArgumentNullException.ThrowIfNull(chooseSource); ArgumentNullException.ThrowIfNull(chooseContact); ArgumentNullException.ThrowIfNull(finished);
        this.begin = begin; this.launchWorker = launchWorker; this.postUi = postUi; this.isUiThread = isUiThread;
        this.chooseSource = chooseSource; this.chooseContact = chooseContact; this.finished = finished;
    }
    internal Task<string> Completion => completion.Task; // Includes started worker and active UI callback return.
    internal Task<string> StartAsync(CancellationToken cancellation = default)
    {
        lock (gate)
        {
            if (started || stopped) throw new InvalidOperationException("notes_setup_host_already_used");
            started = true;
        }
        _ = ExecuteAsync(cancellation); // Async native preparation; caller does not block the UI thread.
        return completion.Task;
    }
    private async Task ExecuteAsync(CancellationToken cancellation)
    {
        NotesOriginalSetupAcquisition? acquisition = null; NotesOriginalSetupRun? run = null;
        Task? worker = null; CancellationTokenRegistration registration = default;
        var result = "held";
        try
        {
            using var external = cancellation.Register(() => { _ = StopAsync(); });
            lifetime.Token.ThrowIfCancellationRequested();
            acquisition = await begin(lifetime.Token).ConfigureAwait(false);
            lifetime.Token.ThrowIfCancellationRequested();
            if (acquisition is null) { result = "cancelled"; return; }
            run = new(acquisition, postUi, isUiThread, chooseSource, chooseContact, _ => { });
            lock (gate) activeRun = run;
            registration = lifetime.Token.Register(run.Cancel);
            lifetime.Token.ThrowIfCancellationRequested();
            worker = launchWorker(run.RunAsync) ?? throw new InvalidOperationException("notes_setup_owned_worker_required");
            await worker.ConfigureAwait(false);
            if (run.Phase == "created") run.Cancel(); // A closed application scheduler must not strand the run.
            await run.Quiesced.ConfigureAwait(false);
            result = run.Phase;
        }
        catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { result = "cancelled"; }
        catch { result = lifetime.IsCancellationRequested ? "cancelled" : "held"; }
        finally
        {
            run?.Cancel();
            try
            {
                if (worker is not null) { try { await worker.ConfigureAwait(false); } catch { } }
                if (run is not null) await run.Quiesced.ConfigureAwait(false);
            }
            finally
            {
                try { registration.Dispose(); run?.Dispose(); acquisition?.Stop(); }
                catch { result = "held"; }
                finally
                {
                    lock (gate) activeRun = null;
                    PostFinalStatus(result);
                    completion.TrySetResult(result);
                }
            }
        }
    }
    internal Task StopAsync()
    {
        NotesOriginalSetupRun? run; bool idle;
        lock (gate) { stopped = true; run = activeRun; idle = !started; }
        lock (lifetimeGate)
        {
            if (!lifetimeDisposed) { try { lifetime.Cancel(); } catch (AggregateException) { } }
        }
        run?.Cancel();
        if (idle) completion.TrySetResult("cancelled");
        return completion.Task; // Never synchronously join a UI/dialog callback.
    }
    public async ValueTask DisposeAsync()
    {
        await StopAsync().ConfigureAwait(false);
        lock (lifetimeGate)
        {
            if (!lifetimeDisposed) { lifetimeDisposed = true; lifetime.Dispose(); }
        }
    }
    private void PostFinalStatus(string result)
    {
        try
        {
            postUi(() =>
            {
                if (Interlocked.Exchange(ref noticeUsed, 1) == 0 && isUiThread())
                { try { finished(result); } catch { } }
                return Task.CompletedTask;
            });
        }
        catch { } // Informational only, never consent or a reason to keep work alive.
    }
}
