using System.Runtime.InteropServices;

namespace MagnolieOrganizer.Windows;

// Test-only call table, absent from product. No native DLL, MF, COM registration,
// protected-file fixture, driver, endpoint or real device is opened here.
internal sealed partial class PhoneCameraVideoParentRuntime
{
    internal sealed class DiagnosticPlan : IDisposable
    {
        internal readonly TaskCompletionSource ReadyPolled = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int Creates, Prepares, Writes, Stops, Closes, SourceChecks, SourceReleases;
        internal uint Flags, OwnerSize;
        internal bool FailClose;
        internal int ReadyStatus;
        internal byte[]? RecordReference, RecordSnapshot;
        internal Guid Scope;
        private CheckFunction? current, sending, registration;
        private MapFunction? map;
        private ExportFunction? export;
        internal int Current() => current!(IntPtr.Zero);
        internal int Sending() => sending!(IntPtr.Zero);
        internal int Registration() => registration!(IntPtr.Zero);
        internal long Mapped(long pts)
        {
            if (map is null) throw new InvalidOperationException("Muted test video has no external mapper");
            RequireSuccess(map(IntPtr.Zero, pts, out var mapped)); return mapped;
        }
        internal byte[] Anchor()
        {
            if (export is null) throw new InvalidOperationException("Muted test video has no external anchor");
            var memory = Marshal.AllocHGlobal(33);
            try { RequireSuccess(export(IntPtr.Zero, memory, 33)); var record = new byte[33]; Marshal.Copy(memory, record, 0, 33); return record; }
            finally { Marshal.Copy(new byte[33], 0, memory, 33); Marshal.FreeHGlobal(memory); }
        }
        private Calls Table() => new() {
            Create = (in Guid scope, in OwnerV1 owner, out ulong handle) => {
                Creates++; Scope = scope; Flags = owner.Flags; OwnerSize = owner.Size;
                current = Marshal.GetDelegateForFunctionPointer<CheckFunction>(owner.Current);
                sending = Marshal.GetDelegateForFunctionPointer<CheckFunction>(owner.Sending);
                registration = Marshal.GetDelegateForFunctionPointer<CheckFunction>(owner.Registration);
                map = owner.ObserveVideo == IntPtr.Zero ? null : Marshal.GetDelegateForFunctionPointer<MapFunction>(owner.ObserveVideo);
                export = owner.ExportAnchor == IntPtr.Zero ? null : Marshal.GetDelegateForFunctionPointer<ExportFunction>(owner.ExportAnchor);
                handle = 19; return Current();
            },
            Prepare = own => { Prepares++; return Current(); },
            Ready = own => { ReadyPolled.TrySetResult(); return Current() != 0 ? Current() : Volatile.Read(ref ReadyStatus); },
            Write = (own, record, bytes) => { Writes++; RecordReference = record; RecordSnapshot = record.ToArray(); return Sending(); },
            Stop = own => { Interlocked.Increment(ref Stops); return 0; },
            Close = own => { Closes++; return FailClose ? unchecked((int)0x800705b4) : 0; }
        };
        private void RequireSource()
        {
            if (SourceReleases != 0) throw new ObjectDisposedException("Diagnostic source pin");
            SourceChecks++;
        }
        public void Dispose() { SourceReleases++; }
        internal PhoneCameraVideoParentRuntime RegisterOriginal(PhoneCameraSession.OutputAuthority original, PhoneCameraAudioParentRuntime.VideoClockLease? clock)
        {
            original.RequireCurrent();
            if (original.Muted != (clock is null)) throw new InvalidOperationException("Diagnostic audio mode mismatch");
            return Register(new PhoneCameraVideoParentRuntime(original, Table(), this, RequireSource, null, clock));
        }
    }
    internal static PhoneCameraVideoParentRuntime CreateDiagnostic(PhoneCameraSession.OutputAuthority original,
        DiagnosticPlan plan, PhoneCameraAudioParentRuntime.VideoClockLease? clock) => plan.RegisterOriginal(original, clock);
    internal bool DiagnosticRootRetained => roots.ContainsKey(this);
    internal void ReleaseStoppedDiagnosticFixture(DiagnosticPlan plan)
    {
        if (closeTask is null || !closeTask.IsFaulted || !ReferenceEquals(source, plan))
            throw new InvalidOperationException("Only the stopped fake call table can be released");
        plan.FailClose = false; RequireSuccess(calls.Close(handle)); handle = 0; Release();
    }
}
