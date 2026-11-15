using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Short-lived cached UI restriction only. Never consent, a saved witness or ACK.
internal sealed class NotesOriginalUiReadiness(Func<string?> ownedText, Func<long>? monotonicMilliseconds = null)
{
    internal sealed record Probe(string Token, string BeforeText);
    private readonly object gate = new();
    private readonly Func<long> clock = monotonicMilliseconds ?? (() => Environment.TickCount64);
    private Probe? pending;
    private long deadline, readyUntil;
    private bool active = true;
    internal bool IsReady { get { lock (gate) return active && clock() < readyUntil; } } // No book callback at receive time.
    internal Probe Request()
    {
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_readiness_stopped");
            if (pending is not null && clock() < deadline) return pending;
        }
        var text = ownedText() ?? throw new InvalidOperationException("notes_readiness_owned_book_required");
        lock (gate)
        {
            if (!active) throw new InvalidOperationException("notes_readiness_stopped");
            pending = new(Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant(), text);
            deadline = clock() + 5_000; readyUntil = 0; return pending;
        }
    }
    internal bool Accept(string token, bool idle)
    {
        Probe probe; long expires;
        lock (gate)
        {
            if (!active || pending is null || token != pending.Token || clock() >= deadline) return false;
            probe = pending; expires = deadline; pending = null; readyUntil = 0;
        }
        var current = ownedText();
        lock (gate)
        {
            if (!active || !idle || current != probe.BeforeText || pending is not null || deadline != expires || clock() >= expires) return false;
            readyUntil = clock() + 5_000; return true;
        }
    }
    internal void Invalidate() { lock (gate) { readyUntil = 0; pending = null; } }
    internal void Stop() { lock (gate) { active = false; readyUntil = 0; pending = null; } }
}
