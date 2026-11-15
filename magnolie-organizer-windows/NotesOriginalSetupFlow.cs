using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class NotesOriginalSetupFlow(NotesOriginalChoiceStore choices, Func<NativeActorBookSnapshot?> capture)
{
    internal sealed record View(bool Addition, JsonObject Export, MagnolienbaumCoordinator.NotesPins Peer,
        IReadOnlyList<JsonObject> Contacts);

    // Explicit native caller only. No portable selection, renderer grant, key
    // backend/startup registration or automatic full replacement of old sources.
    internal async Task<bool> ConfigureAsync(NotesOriginalSetupCollector.Candidate candidate,
        Func<View, CancellationToken, Task<string?>> chooseNative, CancellationToken cancellation = default)
    {
        ArgumentNullException.ThrowIfNull(candidate); ArgumentNullException.ThrowIfNull(chooseNative);
        NotesOriginalChoiceStore.SetupDecision decision; JsonObject export;
        await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            export = candidate.Display(); decision = choices.BeginSetupDecision();
        }
        finally { MutationGate.Global.Release(); }
        // All values shown by the dialog are detached display copies. Returning
        // an ID selects from the original native snapshot, never from these copies.
        var contacts = ContactSourceUpdateRun.SavedContacts(decision.Snapshot).OfType<JsonObject>()
            .Select(value => value.DeepClone().AsObject()).ToArray();
        var selected = await chooseNative(new(decision.IsAddition, export, candidate.Peer, contacts), cancellation).ConfigureAwait(false);
        cancellation.ThrowIfCancellationRequested();
        if (selected is null) return false; // Closing the native dialog grants nothing.
        await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            var choice = candidate.Choose(decision.Snapshot, capture, _ => selected);
            cancellation.ThrowIfCancellationRequested();
            decision.Commit(choice);
            return true;
        }
        finally { MutationGate.Global.Release(); }
    }
}
