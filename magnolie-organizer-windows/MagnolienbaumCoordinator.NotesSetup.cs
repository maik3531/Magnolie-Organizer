using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class MagnolienbaumCoordinator
{
    private Func<JsonObject, NativeNotesOrigin, string, bool>? notesSetupReceive;
    private Action? notesSetupStop;
    internal void AttachNotesSetup(Func<JsonObject, NativeNotesOrigin, string, bool> stage, Action stop)
    {
        ArgumentNullException.ThrowIfNull(stage); ArgumentNullException.ThrowIfNull(stop);
        lock (gate)
        {
            if (disposed || outboxPaused || notesSetupReceive is not null || notesSetupStop is not null)
                throw new InvalidOperationException("notes_setup_slot_unavailable");
            notesSetupReceive = stage; notesSetupStop = stop;
        }
    }
    internal void DetachNotesSetup(Action expectedStop) => StopNotesSetup(expectedStop);
    private void StopNotesSetup(Action? expectedStop = null)
    {
        Action? stop;
        lock (gate)
        {
            stop = notesSetupStop;
            if (stop is null || expectedStop is not null && stop != expectedStop) return;
            notesSetupStop = null; notesSetupReceive = null;
        }
        stop(); // Native cancellation only, outside tree lock.
    }
}
