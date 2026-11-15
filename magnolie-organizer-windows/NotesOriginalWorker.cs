namespace MagnolieOrganizer.Windows;

// Explicit native injection into the existing coordinator maintenance loop only.
// No new timer/server, key backend, setup factory or renderer permission source.
internal sealed class NotesOriginalWorker(NotesOriginalController controller, NotesOriginalUiSaveSession ui,
    NotesOriginalUiReadiness readiness, MagnolienbaumCoordinator coordinator,
    Func<NotesOriginalController.Work, Task> offerSave, Func<Task> askReady, Func<bool> wlanAllowed,
    Func<long>? monotonicMilliseconds = null)
{
    private readonly SemaphoreSlim turn = new(1, 1);
    private readonly CancellationTokenSource stopped = new();
    private readonly Func<long> clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
    private long nextReadyAsk;
    private int active = 1;
    internal void Attach()
    {
        if (Volatile.Read(ref active) == 0) throw new InvalidOperationException("notes_worker_stopped");
        coordinator.AttachNotesOriginalPipeline(controller.Stage, PulseAsync, Stop);
    }
    internal void Wake() => coordinator.WakeNotesMaintenance(); // Semaphore release only, safe under receive's tree gate.
    internal async Task PulseAsync(CancellationToken cancellation = default)
    {
        if (Volatile.Read(ref active) == 0) return;
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellation, stopped.Token);
        if (!await turn.WaitAsync(0, linked.Token).ConfigureAwait(false)) return; // Coalesce overlapping maintenance/events.
        try
        {
            ui.Expire();
            if (!readiness.IsReady && clock() >= nextReadyAsk)
            { nextReadyAsk = clock() + 5_000; await askReady().ConfigureAwait(false); }
            var budgetUsed = false;
            for (var count = 0; count < 4; count++)
            {
                linked.Token.ThrowIfCancellationRequested();
                var work = await controller.ProcessOneAsync(linked.Token).ConfigureAwait(false);
                if (work.Kind is "bootstrap" or "save")
                {
                    try { await offerSave(work).ConfigureAwait(false); }
                    catch { controller.RejectSaveWork(work); throw; }
                    return;
                } // At most one actual UI/book-save offer per turn.
                if (work.Kind == "waiting") break;
                budgetUsed = count == 3;
            }
            var plan = await controller.NextTransportAsync(linked.Token).ConfigureAwait(false);
            if (plan is not null) await plan.SendAsync(coordinator, wlanAllowed, linked.Token).ConfigureAwait(false);
            if (budgetUsed && readiness.IsReady && controller.Counts.Queued > 0) Wake(); // Drain a bounded backlog without waiting for the 30s tick.
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException or UnauthorizedAccessException or
            System.Security.Cryptography.CryptographicException or System.Text.Json.JsonException or ArgumentException)
        { /* Isolated quiet wait; source permission and durable holds are never relaxed. */ }
        finally { turn.Release(); }
    }
    internal void Stop()
    {
        if (Interlocked.Exchange(ref active, 0) == 0) return;
        stopped.Cancel(); controller.Stop(); ui.Stop(); readiness.Stop();
    }
    internal async Task StopAsync()
    {
        Stop(); await turn.WaitAsync().ConfigureAwait(false); turn.Release();
    }
}
