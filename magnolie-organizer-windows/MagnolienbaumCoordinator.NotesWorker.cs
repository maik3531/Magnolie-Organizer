using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class MagnolienbaumCoordinator
{
    private readonly SemaphoreSlim notesMaintenanceWake = new(0, 1);
    private Func<CancellationToken, Task>? notesMaintenanceTurn;
    private Action? notesPipelineStop;
    private Func<JsonObject, JsonObject, NativeNotesOrigin, string, bool>? notesPipelineReceive;
    internal void AttachNotesOriginalPipeline(Func<JsonObject, JsonObject, NativeNotesOrigin, string, bool> receive,
        Func<CancellationToken, Task> maintenanceTurn, Action stop)
    {
        ArgumentNullException.ThrowIfNull(receive); ArgumentNullException.ThrowIfNull(maintenanceTurn); ArgumentNullException.ThrowIfNull(stop);
        lock (gate)
        {
            if (disposed || NotesOriginalReceive is not null || notesMaintenanceTurn is not null || notesPipelineStop is not null)
                throw new InvalidOperationException("notes_native_pipeline_already_bound");
            NotesOriginalReceive = receive; notesPipelineReceive = receive; notesMaintenanceTurn = maintenanceTurn; notesPipelineStop = stop;
        }
        WakeNotesMaintenance();
    }
    internal void WakeNotesMaintenance()
    {
        if (Volatile.Read(ref notesMaintenanceTurn) is null) return;
        try { notesMaintenanceWake.Release(); }
        catch (SemaphoreFullException) { } // One coalesced wake, no receive-time work.
    }
    private async Task MaintainNotesOriginalAsync(CancellationToken cancellation)
    {
        var operation = Volatile.Read(ref notesMaintenanceTurn);
        if (operation is not null) await operation(cancellation).ConfigureAwait(false);
    }
    private void StopNotesOriginalPipeline() => DetachNotesPipeline(null);
    internal bool DetachNotesOriginalPipeline(Action expectedStop)
    {
        ArgumentNullException.ThrowIfNull(expectedStop);
        return DetachNotesPipeline(expectedStop);
    }
    private bool DetachNotesPipeline(Action? expectedStop)
    {
        Action? stop;
        lock (gate)
        {
            stop = notesPipelineStop;
            if (stop is null || expectedStop is not null && stop != expectedStop) return false;
            notesPipelineStop = null; notesMaintenanceTurn = null;
            if (NotesOriginalReceive == notesPipelineReceive) NotesOriginalReceive = null;
            notesPipelineReceive = null; // Preserve a foreign callback installed after our attachment too.
        }
        stop(); // Outside tree gate; never wait on a book/native callback under receive's gate.
        return true;
    }
}
