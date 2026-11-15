namespace MagnolieOrganizer.Windows;

internal sealed record ContactSourceAutomationNotice(long Id, string Sha256, bool Ok, int Grants);
internal sealed record ContactSourceAutomationSetup(bool Changed, int Grants, bool Desired, bool Waiting, long Id, string Sha256);

// Native lifecycle/correlation only. No deserialized approval or frontend status
// may call this in place of the actual writer/setup boundary. Scheduling belongs
// to the native host; tests explicitly drive probes with synthetic observations.
internal sealed class ContactSourceAutomation(
    ContactSourceApprovalStore store, ContactSourceNativeSession session,
    Func<NativeActorBookSnapshot?> capture, Func<bool> available,
    Func<ContactSourceAutomationNotice, Task> notify) : IDisposable
{
    private sealed record Ack(long Id, string Hash);
    private readonly object gate = new();
    private readonly SemaphoreSlim refresh = new(1, 1);
    private readonly CancellationTokenSource lifetime = new();
    private Ack? last;
    private long generation;
    private bool setup, blocked, disposed, eligible;
    private string applied = "";
    private bool? usable;
    private static string Fingerprint(StoredContactSourceApproval stored) => stored.KeyIdentity + "/" + stored.Generation + "/" +
        stored.AccountRevision + "/" + stored.Snapshot.SavedBook.BookSource + "/" + stored.Snapshot.SavedBook.Sequence;

    private bool Current(Ack ack, long expected)
    {
        lock (gate)
            if (disposed || blocked || setup || !eligible || generation != expected || !ReferenceEquals(last, ack)) return false;
        if (!available()) return false;
        var snapshot = capture();
        if (snapshot?.SavedBook.Sha256 != ack.Hash) return false;
        lock (gate) return !disposed && !blocked && !setup && eligible && generation == expected && ReferenceEquals(last, ack);
    }

    internal async Task<bool> SavedAsync(long id, string hash, bool recognized)
    {
        if (id < 1 || hash.Length != 64 || hash.Any(value => value is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            throw new ArgumentException("contact_source_native_saveack_required");
        bool held;
        lock (gate)
        {
            if (disposed) return false;
            last = new(id, hash); generation++; applied = ""; usable = null; eligible = recognized; setup = false;
            held = blocked || !recognized;
        }
        if (held) { session.Revoke(); return false; } // No account/book/file observation, no stale runtime grant.
        await ProbeAsync(wait: true).ConfigureAwait(false);
        return HasCurrentIntent;
    }

    internal bool HasCurrentIntent
    { get { lock (gate) return !disposed && !blocked && !setup && eligible && last is not null; } }

    internal async Task<bool> ProbeAsync(bool wait = false)
    {
        if (wait) await refresh.WaitAsync(lifetime.Token).ConfigureAwait(false);
        else if (!await refresh.WaitAsync(0, lifetime.Token).ConfigureAwait(false)) return false;
        try
        {
            Ack? ack; long expected;
            lock (gate) { ack = last; expected = generation; }
            if (ack is null || !Current(ack, expected)) return false;
            bool recognized;
            try { recognized = store.RecognizesSaved(); }
            catch (Exception) { recognized = false; }
            bool ok = false; var grants = 0; var next = "";
            try
            {
                if (!recognized) throw new InvalidOperationException("contact_source_native_intent_unavailable");
                var stored = await Task.Run(store.LoadCurrent, lifetime.Token).ConfigureAwait(false);
                if (stored is null) throw new UnauthorizedAccessException("contact_source_stored_account_or_book_changed");
                if (!Current(ack, expected)) return false;
                next = Fingerprint(stored);
                bool restore;
                lock (gate) restore = applied != next;
                if (restore || session.GrantCount == 0)
                    await session.RestoreAsync(stored, () =>
                    {
                        if (!Current(ack, expected)) throw new InvalidOperationException("contact_source_native_restore_context_changed");
                    }, lifetime.Token).ConfigureAwait(false);
                if (!Current(ack, expected)) return false;
                grants = session.GrantCount; ok = grants > 0;
            }
            catch (Exception) when (!lifetime.IsCancellationRequested)
            {
                if (!Current(ack, expected)) return false;
                session.Revoke(); // Volatile access loss NEVER erases signed human intent.
            }
            bool report;
            lock (gate)
            {
                if (generation != expected || !ReferenceEquals(last, ack) || disposed || blocked || setup) return false;
                report = usable != ok || (ok && applied != next);
                usable = ok; applied = ok ? next : "";
            }
            if (report && Current(ack, expected))
                await notify(new(ack.Id, ack.Hash, ok, grants)).ConfigureAwait(false);
            return ok;
        }
        finally { refresh.Release(); }
    }

    internal async Task<ContactSourceAutomationSetup> ConfigureAsync(
        Func<IReadOnlyList<NextcloudDavSource>, IReadOnlyList<string>, CancellationToken, Task<IReadOnlyList<string>?>> ask,
        CancellationToken cancellation = default)
    {
        long expected;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (setup) throw new InvalidOperationException("native_busy");
            setup = true; expected = ++generation;
        }
        try
        {
            var changed = await session.ConfigureAsync(ask, cancellation).ConfigureAwait(false);
            Ack? ack;
            lock (gate)
            {
                if (generation != expected || disposed) throw new InvalidOperationException("contact_source_approval_context_changed");
                if (changed) blocked = false;
                ack = last; applied = ""; usable = null;
            }
            var desired = store.RecognizesSaved();
            var snapshot = capture();
            var correlated = ack is not null && snapshot?.SavedBook.Sha256 == ack.Hash;
            var count = session.GrantCount;
            var configured = "";
            if (desired && count > 0)
                try
                {
                    var current = await Task.Run(store.LoadCurrent, cancellation).ConfigureAwait(false);
                    if (current is null) throw new UnauthorizedAccessException("contact_source_account_access_wait");
                    configured = Fingerprint(current);
                }
                catch (Exception) when (!cancellation.IsCancellationRequested)
                { session.Revoke(); count = 0; }
            bool resumable;
            lock (gate)
            {
                if (generation != expected || disposed) throw new InvalidOperationException("contact_source_approval_context_changed");
                eligible = desired && correlated && !blocked;
                resumable = eligible;
                applied = configured; usable = count > 0;
            }
            return new(changed, count, resumable, resumable && count == 0, correlated ? ack!.Id : 0, correlated ? ack!.Hash : "");
        }
        finally { lock (gate) if (generation == expected) setup = false; }
    }

    internal async Task RevokeAsync(bool durable)
    {
        lock (gate)
        {
            generation++; setup = false; last = null; applied = ""; usable = null; eligible = false;
            if (durable) blocked = true; // Failed durable revoke must stay blocked in this process.
        }
        session.Revoke();
        if (durable) await Task.Run(store.Revoke, lifetime.Token).ConfigureAwait(false);
    }

    public void Dispose()
    {
        lock (gate) { if (disposed) return; disposed = true; generation++; last = null; }
        lifetime.Cancel(); session.Revoke();
    }
}
