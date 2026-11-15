using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// One explicitly injected renderer handoff, not setup/consent/readiness authority.
// Native work and actual writer completion remain mandatory after the UI CAS.
internal sealed class NotesOriginalUiSaveSession(NotesOriginalController controller, Func<string?> ownedText,
    Func<long>? monotonicMilliseconds = null)
{
    internal sealed record Offer(string Token, string Kind, string BeforeText, string Text);
    internal sealed record Claimed(NotesOriginalBootstrapSave? Bootstrap, NotesOriginalController.SaveCompletion Completion, string ContactToken);
    private sealed record Lease(Offer Offer, NotesOriginalController.Work Work, NotesOriginalController.SaveCompletion Completion, long Expires);
    private readonly object gate = new();
    private readonly Func<long> clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
    private Lease? pending;
    private bool active = true;

    internal Offer Publish(NotesOriginalController.Work work)
    {
        lock (gate) if (!active) throw new InvalidOperationException("notes_ui_session_stopped");
        Expire();
        var before = ownedText() ?? throw new InvalidOperationException("notes_ui_owned_native_model_required");
        var completion = controller.PrepareSaveCompletion(work);
        var text = work.Invocation switch {
            NotesOriginalBootstrapSave bootstrap => bootstrap.Text,
            NotesOriginalPendingResult.NativeCommit native => native.Text,
            _ => throw new InvalidOperationException("notes_ui_native_save_work_required") };
        if (ownedText() != before) throw new InvalidOperationException("notes_ui_native_model_changed");
        var offer = new Offer(Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), work.Kind, before, text);
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_ui_session_stopped");
            if (pending is not null) throw new InvalidOperationException("notes_ui_save_already_pending");
            pending = new(offer, work, completion, clock() + 8_000);
        }
        return offer;
    }

    internal Claimed Claim(string token, string text)
    {
        Expire(); Lease lease;
        lock (gate)
        {
            lease = pending is not null && pending.Offer.Token == token ? pending : throw new InvalidOperationException("notes_ui_owned_save_token_required");
            pending = null; // One use, even if a later native recheck fails.
        }
        try
        {
            if (text != lease.Offer.Text || ownedText() != lease.Offer.BeforeText)
                throw new InvalidOperationException("notes_ui_exact_current_book_required");
            return new(lease.Work.Invocation as NotesOriginalBootstrapSave, lease.Completion,
                (lease.Work.Invocation as NotesOriginalPendingResult.NativeCommit)?.Offer.Token ?? "");
        }
        catch { lease.Completion.Failed(); throw; }
    }
    internal void Cancel(string token)
    {
        Lease? lease = null;
        lock (gate) if (pending?.Offer.Token == token) { lease = pending; pending = null; }
        lease?.Completion.Failed(); // Clears only that exact native memory lane.
    }
    internal void Expire()
    {
        Lease? lease = null;
        lock (gate) if (pending is not null && clock() >= pending.Expires) { lease = pending; pending = null; }
        lease?.Completion.Failed();
    }
    internal void Stop()
    {
        Lease? lease; lock (gate) { active = false; lease = pending; pending = null; }
        lease?.Completion.Failed();
    }
}
