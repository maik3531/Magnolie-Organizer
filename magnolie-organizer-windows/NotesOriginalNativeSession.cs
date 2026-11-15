using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Explicit composition for an already granted native profile. No startup call,
// dialog substitute, portable metadata grant, identity/key creation or service start.
internal sealed class NotesOriginalNativeSession
{
    internal enum Admission { Attached, NoChoice, KeyMissing, Held, Stopped }
    private readonly WindowsPaths paths;
    private readonly NotesOriginalChoiceStore choices;
    private readonly NotesOriginalExistingJournalKey key;
    private readonly SemaphoreSlim lifecycle = new(1, 1);
    private bool attached, stopped;
    internal NotesOriginalUiReadiness Readiness { get; }
    internal NotesOriginalUiSaveSession Ui { get; }
    internal NotesOriginalWorker Worker { get; }
    internal NotesOriginalController Controller { get; }
    internal bool IsActive => attached && !stopped && Worker.IsActive;

    internal NotesOriginalNativeSession(WindowsPaths nativePaths, NotesOriginalChoiceStore choices, ContactSourceSavedCommit actualCommit,
        Func<string?> ownedNativeText, MagnolienbaumCoordinator coordinator, Func<NotesOriginalController.Work, Task> offerSave,
        Func<Task> askReady, Func<bool> wlanAllowed, bool controlledUnix = false, Func<byte[], byte[]>? controlledUnprotect = null)
    {
        paths = nativePaths; this.choices = choices;
        key = new(nativePaths, controlledUnix, controlledUnprotect);
        Readiness = new(ownedNativeText);
        ContactSourcePrivateFiles Files(string name) => new(Path.Combine(Path.GetFullPath(nativePaths.Root), name), controlledUnix: controlledUnix,
            layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
        var requests = new NotesOriginalRequestIntents(Files("notes-original-requests"), key.ReadExisting);
        var outcomes = new NotesOriginalSavedAckIntents(Files("notes-original-outcomes"), key.ReadExisting, requests);
        Controller = new(choices, requests, outcomes, actualCommit, () => Readiness.IsReady);
        Ui = new(Controller, ownedNativeText);
        Worker = new(Controller, Ui, Readiness, coordinator, offerSave, askReady, wlanAllowed);
    }
    internal async Task<Admission> TryAttachKnownAsync(CancellationToken cancellation = default)
    {
        await lifecycle.WaitAsync(cancellation).ConfigureAwait(false);
        try
        {
            if (stopped || !Worker.IsActive) return Admission.Stopped;
            if (attached) return Admission.Attached;
            await MutationGate.Global.WaitAsync(cancellation).ConfigureAwait(false);
            try
            {
                var selected = choices.DiscoverySources();
                if (selected is null) return Admission.NoChoice;
                if (selected.Value.Sources.Count == 0 || selected.Value.Binding != Path.GetFullPath(paths.Data)) return Admission.Held;
                var existing = key.ReadExisting();
                if (existing is null) return Admission.KeyMissing;
                CryptographicOperations.ZeroMemory(existing); // Preflight only, never retain an old key after loss/replacement.
            }
            finally { MutationGate.Global.Release(); }
            Worker.Attach(); // Outside the native book gate; attachment itself starts no service/listener.
            attached = true; return Admission.Attached;
        }
        catch (Exception error) when (error is InvalidOperationException or InvalidDataException or IOException or UnauthorizedAccessException or
            CryptographicException or System.Text.Json.JsonException or ArgumentException or FormatException)
        { return Admission.Held; }
        finally { lifecycle.Release(); }
    }
    internal async Task StopAsync()
    {
        await lifecycle.WaitAsync().ConfigureAwait(false);
        try { stopped = true; attached = false; await Worker.StopAsync().ConfigureAwait(false); }
        finally { lifecycle.Release(); }
    }
}
