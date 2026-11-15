namespace MagnolieOrganizer.Windows;

internal sealed partial class BridgeDispatcher
{
    // Explicit native injection only: no startup factory or history-key creation.
    internal NotesOriginalUiSaveSession? NativeNotesUi { get; set; }
    internal NotesOriginalUiReadiness? NativeNotesReadiness { get; set; }
    internal Action? NativeNotesWake { get; set; }
    private NotesOriginalNativeSession? nativeNotesSession;
    private int notesSetupPrompt;
    private NotesOriginalSetupAcquisition? nativeNotesSetupAcquisition;

    private NotesOriginalChoiceStore NativeNotesChoiceStore() => NativeNotesChoices ??= new NotesOriginalChoiceStore(
        new ContactSourcePrivateFiles(Path.Combine(Path.GetFullPath(paths.Root), "notes-original-choices")), NativeActorBook,
        () => ContactSourcePrimaryBook.Capture(Path.GetFullPath(paths.Data), store, encryption, () => currentPlainTextAvailable && !restoreInProgress && !disposed),
        () => Path.GetFullPath(paths.Data), currentNativeData: () => currentPlainTextAvailable && !restoreInProgress && !disposed ? currentPlainText : null);

    // Explicit native main-thread UI entry, not a renderer/startup command. Never
    // instantiate a coordinator/service/identity to make an unavailable peer appear.
    internal async Task<NotesOriginalSetupAcquisition?> BeginNotesSetupAsync(CancellationToken cancellation = default)
    {
        if (!OperatingSystem.IsWindows() || baumInstance is null || disposed || restoreInProgress || !currentPlainTextAvailable ||
            Interlocked.CompareExchange(ref notesSetupPrompt, 1, 0) != 0)
            throw new InvalidOperationException("notes_setup_native_context_required");
        NotesOriginalSetupAcquisition? acquisition = null;
        try
        {
            if (nativeNotesSetupAcquisition?.IsActive == true) throw new InvalidOperationException("notes_setup_acquisition_busy");
            Interlocked.Exchange(ref nativeNotesSetupAcquisition, null)?.Stop();
            var coordinator = baumInstance; var choices = NativeNotesChoiceStore();
            void Usable()
            {
                if (disposed || restoreInProgress || !currentPlainTextAvailable || !ReferenceEquals(baumInstance, coordinator) ||
                    !ReferenceEquals(NativeNotesChoices, choices)) throw new InvalidOperationException("notes_setup_native_context_changed");
            }
            using var operation = CancellationTokenSource.CreateLinkedTokenSource(cancellation, backgroundLifetime.Token);
            acquisition = await NotesOriginalSetupAcquisition.BeginAsync(new(choices, NativeActorBook), coordinator,
                (peers, token) => NotesOriginalPeerDialog.ChooseAsync(form, peers, T, token), Usable, OriginalContactWlanAvailable, operation.Token);
            nativeNotesSetupAcquisition = acquisition;
            Usable(); operation.Token.ThrowIfCancellationRequested();
            return acquisition;
        }
        catch
        {
            if (acquisition is not null) Interlocked.CompareExchange(ref nativeNotesSetupAcquisition, null, acquisition);
            acquisition?.Stop(); throw;
        }
        finally { Volatile.Write(ref notesSetupPrompt, 0); }
    }
    internal async Task<bool> CompleteNotesSetupAsync(NotesOriginalSetupAcquisition acquisition,
        NotesOriginalSetupCollector.Candidate candidate, CancellationToken cancellation = default)
    {
        ArgumentNullException.ThrowIfNull(acquisition); ArgumentNullException.ThrowIfNull(candidate);
        if (!ReferenceEquals(nativeNotesSetupAcquisition, acquisition) || disposed || restoreInProgress || !currentPlainTextAvailable ||
            Interlocked.CompareExchange(ref notesSetupPrompt, 1, 0) != 0)
            throw new InvalidOperationException("notes_setup_owned_acquisition_required");
        try
        {
            using var operation = CancellationTokenSource.CreateLinkedTokenSource(cancellation, backgroundLifetime.Token);
            var configured = await acquisition.ConfigureAsync(candidate,
                (view, token) => NotesOriginalSetupDialog.ChooseAsync(form, view, T, token), operation.Token);
            if (configured) NativeNotesWake?.Invoke();
            return configured;
        }
        finally
        {
            Interlocked.CompareExchange(ref nativeNotesSetupAcquisition, null, acquisition);
            try { acquisition.Stop(); }
            finally { Volatile.Write(ref notesSetupPrompt, 0); }
        }
    }

    // Native candidate only. No renderer/startup entry or acquisition registration.
    internal async Task<bool> ConfigureNotesCandidateAsync(NotesOriginalSetupCollector.Candidate candidate, CancellationToken cancellation = default)
    {
        if (!OperatingSystem.IsWindows() || disposed || restoreInProgress || !currentPlainTextAvailable ||
            Interlocked.CompareExchange(ref notesSetupPrompt, 1, 0) != 0)
            throw new InvalidOperationException("notes_setup_native_context_required");
        try
        {
            using var operation = CancellationTokenSource.CreateLinkedTokenSource(cancellation, backgroundLifetime.Token);
            var flow = new NotesOriginalSetupFlow(NativeNotesChoiceStore(), NativeActorBook);
            var configured = await flow.ConfigureAsync(candidate, (view, token) => NotesOriginalSetupDialog.ChooseAsync(form, view, T, token), operation.Token);
            if (configured) NativeNotesWake?.Invoke();
            return configured;
        }
        finally { Volatile.Write(ref notesSetupPrompt, 0); }
    }

    // Explicit future setup/resume entry, NOT called by startup/renderer commands.
    // Existing private native choices and an existing coordinator/key are required.
    internal async Task<NotesOriginalNativeSession.Admission> TryResumeKnownNotesAsync()
    {
        if (nativeNotesSession?.IsActive == true) return NotesOriginalNativeSession.Admission.Attached;
        if (nativeNotesSession is not null) await StopNativeNotesSessionAsync();
        if (!OperatingSystem.IsWindows() || baumInstance is null || disposed || restoreInProgress || !currentPlainTextAvailable)
            return NotesOriginalNativeSession.Admission.Held;
        if (NativeNotesUi is not null || NativeNotesReadiness is not null || NativeNotesWake is not null)
            return NotesOriginalNativeSession.Admission.Held; // Never replace a foreign native injection.
        var choices = NativeNotesChoiceStore();
        var session = new NotesOriginalNativeSession(paths, choices, OriginalContactCommit,
            () => currentPlainTextAvailable && !restoreInProgress && !disposed ? currentPlainText : null,
            baumInstance, OfferNotesWorkAsync, OfferNotesReadinessAsync, OriginalContactWlanAvailable);
        NativeNotesChoices = choices; NativeNotesUi = session.Ui; NativeNotesReadiness = session.Readiness; NativeNotesWake = session.Worker.Wake;
        try
        {
            var admission = await session.TryAttachKnownAsync(backgroundLifetime.Token);
            if (admission == NotesOriginalNativeSession.Admission.Attached && !disposed && !restoreInProgress && currentPlainTextAvailable)
                nativeNotesSession = session;
            else if (admission == NotesOriginalNativeSession.Admission.Attached) admission = NotesOriginalNativeSession.Admission.Held;
            return admission;
        }
        finally
        {
            if (!ReferenceEquals(nativeNotesSession, session))
            {
                await session.StopAsync();
                ClearNativeNotesHooks(session);
            }
        }
    }
    private async Task StopNativeNotesSessionAsync()
    {
        Interlocked.Exchange(ref nativeNotesSetupAcquisition, null)?.Stop();
        var session = Interlocked.Exchange(ref nativeNotesSession, null); if (session is null) return;
        await session.StopAsync();
        ClearNativeNotesHooks(session);
    }
    private void ClearNativeNotesHooks(NotesOriginalNativeSession session)
    {
        if (ReferenceEquals(NativeNotesUi, session.Ui)) NativeNotesUi = null;
        if (ReferenceEquals(NativeNotesReadiness, session.Readiness)) NativeNotesReadiness = null;
        if (NativeNotesWake == session.Worker.Wake) NativeNotesWake = null;
    }

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
