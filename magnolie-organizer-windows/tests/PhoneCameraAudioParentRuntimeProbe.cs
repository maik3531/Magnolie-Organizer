using System.Runtime.InteropServices;

namespace MagnolieOrganizer.Windows;

// Entire controlled call table is absent from production. This never loads a
// DLL, creates an OS child, opens an endpoint or bypasses the protected loader.
internal sealed partial class PhoneCameraAudioParentRuntime
{
    internal sealed class DiagnosticPlan
    {
        internal readonly TaskCompletionSource PrepareEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource WriteEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly ManualResetEventSlim stop = new(false);
        internal bool HoldPrepare, HoldWrite, FailClose;
        internal int Creates, Prepares, Writes, Stops, Closes, Releases, Active;
        internal Guid Scope;
        internal byte[]? Digest, RecordReference, RecordSnapshot;
        internal uint OwnerBytes;
        private OwnerCheck? current, sending;
        private OwnerFailure? failed;
        internal int Current() => current!(IntPtr.Zero);
        internal int Sending() => sending!(IntPtr.Zero);
        internal void Failure(int reason) => failed!(IntPtr.Zero, reason);
        internal PhoneCameraAudioParentRuntime RegisterOriginal(PhoneCameraSession.OutputAuthority original) =>
            Register(original, Table(), Enumerable.Range(1, 32).Select(n => (byte)n).ToArray());
        private Calls Table() => new() {
            Create = (in Guid scope, byte[] digest, uint bytes, in OwnerV1 owner, out ulong handle) => {
                Creates++; Scope = scope; Digest = digest.ToArray(); OwnerBytes = owner.Size;
                current = Marshal.GetDelegateForFunctionPointer<OwnerCheck>(owner.Current);
                sending = Marshal.GetDelegateForFunctionPointer<OwnerCheck>(owner.Sending);
                failed = Marshal.GetDelegateForFunctionPointer<OwnerFailure>(owner.Failed);
                handle = 17;
                return bytes == 32 && owner.Size == Marshal.SizeOf<OwnerV1>() && owner.Version == 1 ? Current() : unchecked((int)0x80070057);
            },
            Prepare = own => {
                Interlocked.Increment(ref Active); Prepares++; PrepareEntered.TrySetResult();
                try { return HoldPrepare ? (stop.Wait(5000) ? unchecked((int)0x80004004) : unchecked((int)0x800705b4)) : Current(); }
                finally { Interlocked.Decrement(ref Active); }
            },
            Ready = own => Current(),
            Video = (ulong own, long pts, out long mapped) => { mapped = pts + 100; return Sending(); },
            Write = (own, record, bytes) => {
                Interlocked.Increment(ref Active); Writes++; RecordReference = record; RecordSnapshot = record.ToArray(); WriteEntered.TrySetResult();
                try { return HoldWrite ? (stop.Wait(5000) ? unchecked((int)0x80004004) : unchecked((int)0x800705b4)) : Sending(); }
                finally { Interlocked.Decrement(ref Active); }
            },
            Anchor = (own, record, bytes) => { for (int i = 0; i < record.Length; i++) record[i] = (byte)(i + 1); return Sending(); },
            Stop = own => { Interlocked.Increment(ref Stops); stop.Set(); return 0; },
            Close = own => { Closes++; return FailClose || Active != 0 ? unchecked((int)0x800705b4) : 0; },
            ReleaseModule = () => { if (Active != 0 || Closes == 0) throw new Exception("Diagnostic module released before confirmed/drained Close"); Releases++; }
        };
    }
    internal static PhoneCameraAudioParentRuntime CreateDiagnostic(PhoneCameraSession.OutputAuthority original, DiagnosticPlan plan)
    {
        original.RequireCurrent();
        return plan.RegisterOriginal(original);
    }
    internal bool DiagnosticRootRetained => roots.ContainsKey(this);
    internal void ReleaseStoppedDiagnosticFixture(DiagnosticPlan plan)
    {
        // Test cleanup only: this table has NO actual module/OS child. Confirm
        // fake termination after asserting production's no-retry retained root.
        if (!closeTask!.IsFaulted || plan.Active != 0 || !ReferenceEquals(calls.ReleaseModule.Target, plan))
            throw new Exception("Only terminal own diagnostic fixture may be released");
        plan.FailClose = false; RequireSuccess(calls.Close(handle)); calls.ReleaseModule(); handle = 0; roots.TryRemove(this, out _);
    }
}
