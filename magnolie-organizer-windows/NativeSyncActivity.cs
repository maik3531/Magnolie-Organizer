namespace MagnolieOrganizer.Windows;

// A lease spans admitted awaited IO and cleanup, not merely a requested action.
internal sealed class NativeSyncActivity
{
    private int owners;
    internal bool Active => Volatile.Read(ref owners) > 0;
    internal event Action? Changed;
    internal IDisposable Enter()
    {
        Interlocked.Increment(ref owners); Notify();
        return new Lease(this);
    }
    private void Notify()
    {
        if (Changed is not { } handlers) return;
        foreach (Action handler in handlers.GetInvocationList())
            try { handler(); } catch { /* A visual observer must never break IO. */ }
    }
    private sealed class Lease(NativeSyncActivity owner) : IDisposable
    {
        private NativeSyncActivity? current = owner;
        public void Dispose()
        {
            if (Interlocked.Exchange(ref current, null) is not { } value) return;
            Interlocked.Decrement(ref value.owners); value.Notify();
        }
    }
}
