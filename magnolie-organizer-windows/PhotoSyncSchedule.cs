using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed class NativePhotoSyncScope
{
    internal DeviceTransferBinding Binding { get; }
    internal string SourceEpoch { get; }
    internal object Owner { get; }
    internal NativePhotoSyncScope(DeviceTransferBinding binding, string sourceEpoch, object owner)
    {
        binding.Validate();
        if (owner is null || !Regex.IsMatch(sourceEpoch, "\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant) ||
            binding.SenderId == binding.ReceiverId || new[] { binding.SenderId, binding.ReceiverId }.Any(id =>
                !Regex.IsMatch(id, "\\A[A-Za-z0-9_-]{16,160}\\z", RegexOptions.CultureInvariant)))
            throw new InvalidDataException("photo_schedule_invalid_native_scope");
        Binding = binding; SourceEpoch = sourceEpoch; Owner = owner;
    }
}

internal sealed class NativePhotoRun(NativePhotoSyncScope scope, string trigger)
{
    internal string Id { get; } = Guid.NewGuid().ToString("N");
    internal NativePhotoSyncScope Scope { get; } = scope;
    internal string Trigger { get; } = trigger;
}

// Inert run coordination only: no timer/thread, store, scan, network, implicit
// consent or receipt. Native desktop event-loop/worker adapters remain required.
internal sealed class PhotoSyncSchedule(Func<NativePhotoSyncScope?> currentScope, Func<long> monotonicMs) : IDisposable
{
    internal const long IntervalMs = 60000;
    internal const long DebounceMs = 1000;
    private readonly object gate = new();
    private string mode = "manual";
    private NativePhotoRun? active;
    private long? due;
    private bool dirty;
    private bool closed;
    private long? lastTime;
    internal string Mode { get { lock (gate) return mode; } }
    internal NativePhotoRun? Active { get { lock (gate) return active; } }

    private long Now()
    {
        var value = monotonicMs();
        if (value < 0 || value > long.MaxValue - IntervalMs || lastTime is not null && value < lastTime.Value)
            throw new InvalidOperationException("photo_schedule_clock_changed");
        lastTime = value;
        return value;
    }
    private void Ready() { if (closed) throw new InvalidOperationException("photo_schedule_closed"); }
    private static bool Same(NativePhotoSyncScope first, NativePhotoSyncScope? second) => second is not null &&
        first.Binding == second.Binding && first.SourceEpoch == second.SourceEpoch && ReferenceEquals(first.Owner, second.Owner);

    internal void SetMode(string value)
    {
        lock (gate)
        {
            Ready();
            if (value is not ("manual" or "automatic")) throw new InvalidDataException("photo_schedule_invalid_mode");
            if (value == mode) return;
            var now = Now();
            mode = value; dirty = false; due = value == "automatic" ? now : null;
        }
    }
    internal NativePhotoRun RequestNow()
    {
        lock (gate)
        {
            Ready(); Now();
            if (active is not null) return active; // Show current progress, never overlap.
            return Begin(currentScope() ?? throw new InvalidOperationException("photo_schedule_not_ready"), "manual");
        }
    }
    internal void HintChanged()
    {
        lock (gate)
        {
            Ready();
            if (mode != "automatic") return;
            var now = Now();
            if (active is not null) dirty = true;
            else due = due is null ? now + DebounceMs : Math.Min(due.Value, now + DebounceMs);
        }
    }
    internal NativePhotoRun? TakeDue()
    {
        lock (gate)
        {
            Ready();
            if (mode != "automatic" || active is not null) return null;
            var now = Now();
            if (due is null || now < due.Value) return null;
            var scope = currentScope();
            return scope is null ? null : Begin(scope, "automatic"); // Offline/revoked is pause, never deletion proof.
        }
    }
    private NativePhotoRun Begin(NativePhotoSyncScope scope, string trigger)
    {
        active = new(scope, trigger); due = null; dirty = false;
        return active;
    }
    internal bool CancellationRequested(NativePhotoRun run)
    {
        lock (gate) return run is null || closed || !ReferenceEquals(active, run) || !Same(run.Scope, currentScope());
    }
    // Exact native worker END only, never a wire ACK or cancellation request.
    internal bool Finished(NativePhotoRun run)
    {
        lock (gate)
        {
            if (run is null || !ReferenceEquals(active, run)) return false;
            var now = Now(); active = null;
            if (!closed && mode == "automatic") due = now + (dirty ? DebounceMs : IntervalMs);
            dirty = false;
            return true;
        }
    }
    public void Dispose()
    {
        lock (gate)
        {
            closed = true; mode = "manual"; due = null; dirty = false;
            // Keep active ownership until the actual native worker has ended.
        }
    }
}
