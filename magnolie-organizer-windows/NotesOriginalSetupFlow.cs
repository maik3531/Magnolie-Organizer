using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed class NotesOriginalSetupFlow(NotesOriginalChoiceStore choices, Func<NativeActorBookSnapshot?> capture)
{
    internal sealed record View(bool Addition, JsonObject Export, MagnolienbaumCoordinator.NotesPins Peer,
        IReadOnlyList<JsonObject> Contacts);

    // Explicit native caller only. No portable selection, renderer grant, key
    // backend/startup registration or automatic full replacement of old sources.
    internal async Task<NotesOriginalChoiceStore.SetupDecision> BeginAsync(CancellationToken cancellation = default)
    {
        await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
        try { return choices.BeginSetupDecision(); }
        finally { MutationGate.Global.Release(); }
    }
    internal void RequireDecision(NotesOriginalChoiceStore.SetupDecision decision) => decision.RequireCurrent(choices); // Caller holds book gate.

    internal async Task<bool> ConfigureAsync(NotesOriginalSetupCollector.Candidate candidate,
        Func<View, CancellationToken, Task<string?>> chooseNative, CancellationToken cancellation = default,
        NotesOriginalChoiceStore.SetupDecision? beforePeerDecision = null)
    {
        ArgumentNullException.ThrowIfNull(candidate); ArgumentNullException.ThrowIfNull(chooseNative);
        NotesOriginalChoiceStore.SetupDecision decision; JsonObject export;
        await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            export = candidate.Display(); decision = beforePeerDecision ?? choices.BeginSetupDecision();
            decision.RequireCurrent(choices);
        }
        finally { MutationGate.Global.Release(); }
        // All values shown by the dialog are detached display copies. Returning
        // an ID selects from the original native snapshot, never from these copies.
        var contacts = ContactSourceUpdateRun.SavedContacts(decision.Snapshot).OfType<JsonObject>()
            .Select(value => value.DeepClone().AsObject()).ToArray();
        try
        {
            var selected = await chooseNative(new(decision.IsAddition, export, candidate.Peer, contacts), cancellation).ConfigureAwait(false);
            cancellation.ThrowIfCancellationRequested();
            if (selected is null) { decision.Cancel(); return false; }
            await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
            try
            {
                decision.RequireCurrent(choices);
                var choice = candidate.Choose(decision.Snapshot, capture, _ => selected);
                cancellation.ThrowIfCancellationRequested();
                decision.Commit(choice);
                return true;
            }
            finally { MutationGate.Global.Release(); }
        }
        catch { decision.Cancel(); throw; }
    }
}
