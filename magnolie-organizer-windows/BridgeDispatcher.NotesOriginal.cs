namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    // Explicit native injection only: no startup factory or history-key creation.
    internal NotesOriginalUiSaveSession? NativeNotesUi { get; set; }

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
