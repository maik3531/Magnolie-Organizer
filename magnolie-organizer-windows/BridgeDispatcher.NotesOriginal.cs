namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    // Explicit native injection only: no startup factory or history-key creation.
    internal NotesOriginalUiSaveSession? NativeNotesUi { get; set; }
    internal NotesOriginalUiReadiness? NativeNotesReadiness { get; set; }
    internal Action? NativeNotesWake { get; set; }

    internal async Task OfferNotesReadinessAsync()
    {
        var readiness = NativeNotesReadiness ?? throw new InvalidOperationException("notes_ui_readiness_required");
        NotesOriginalUiReadiness.Probe probe;
        await MutationGate.Global.WaitAsync(backgroundLifetime.Token);
        try { probe = readiness.Request(); }
        finally { MutationGate.Global.Release(); }
        await form.SendAsync("App.notesOriginalBereit", new { token = probe.Token, beforeText = probe.BeforeText });
    }

    private async Task AcceptNotesReadinessAsync(string token, bool idle)
    {
        var ready = false;
        await MutationGate.Global.WaitAsync(backgroundLifetime.Token);
        try { ready = NativeNotesReadiness?.Accept(token, idle) == true; }
        finally { MutationGate.Global.Release(); }
        if (ready) NativeNotesWake?.Invoke(); // Native deferred wake only, never a permission grant.
    }

    internal async Task OfferNotesWorkAsync(NotesOriginalController.Work work)
    {
        var session = NativeNotesUi ?? throw new InvalidOperationException("notes_ui_native_session_required");
        NotesOriginalUiSaveSession.Offer offer;
        await MutationGate.Global.WaitAsync(backgroundLifetime.Token);
        try { offer = session.Publish(work); }
        finally { MutationGate.Global.Release(); }
        try
        {
            await form.SendAsync("App.notesOriginalSpeichern", new { token = offer.Token, kind = offer.Kind,
                beforeText = offer.BeforeText, text = offer.Text });
        }
        catch { session.Cancel(offer.Token); throw; }
    }
}
