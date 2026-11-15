using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Trusted composition only. No renderer/config/path/delegate input in production.
// A terminal-but-unconfirmed native owner is deliberately rooted, never unloaded.
[SupportedOSPlatform("windows")]
internal sealed partial class PhoneCameraAudioParentRuntime
{
    [StructLayout(LayoutKind.Sequential)]
    private struct OwnerV1 { internal uint Size, Version; internal IntPtr Current, Sending, Failed, Context; }
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int OwnerCheck(IntPtr context);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void OwnerFailure(IntPtr context, int reason);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int CreateFunction(in Guid scope, [In] byte[] digest, uint bytes, in OwnerV1 owner, out ulong handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int HandleFunction(ulong handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int VideoFunction(ulong handle, long pts, out long mapped);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int RecordFunction(ulong handle, [In] byte[] record, uint bytes);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int AnchorFunction(ulong handle, [Out] byte[] record, uint bytes);
    private sealed class Calls
    {
        internal PhoneCameraAudioParentModule? Module;
        internal required CreateFunction Create;
        internal required HandleFunction Prepare, Ready, Stop, Close;
        internal required VideoFunction Video;
        internal required RecordFunction Write;
        internal required AnchorFunction Anchor;
        internal required Action ReleaseModule;
        internal static Calls From(PhoneCameraAudioParentModule module) => new() {
            Module = module,
            Create = module.Export<CreateFunction>("MagnoliePhoneAudioCreate"), Prepare = module.Export<HandleFunction>("MagnoliePhoneAudioPrepare"),
            Ready = module.Export<HandleFunction>("MagnoliePhoneAudioRequireReady"), Stop = module.Export<HandleFunction>("MagnoliePhoneAudioStop"),
            Close = module.Export<HandleFunction>("MagnoliePhoneAudioClose"), Video = module.Export<VideoFunction>("MagnoliePhoneAudioObserveVideo"),
            Write = module.Export<RecordFunction>("MagnoliePhoneAudioWrite"), Anchor = module.Export<AnchorFunction>("MagnoliePhoneAudioExportAnchor"),
            ReleaseModule = module.Dispose
        };
    }
    private static readonly ConcurrentDictionary<PhoneCameraAudioParentRuntime, byte> roots = new();
    private readonly PhoneCameraSession.OutputAuthority original;
    private readonly Calls calls;
    private readonly OwnerCheck currentCallback, sendingCallback;
    private readonly OwnerFailure failedCallback;
    private readonly object gate = new();
    private readonly TaskCompletionSource drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private ulong handle;
    private int active, stopped;
    private bool closing, prepared, prepareCalled, videoClockTaken;
    private Task? closeTask;
    private PhoneCameraAudioParentRuntime(PhoneCameraSession.OutputAuthority original, Calls calls)
    {
        this.original = original; this.calls = calls;
        currentCallback = _ => Callback(sending: false);
        sendingCallback = _ => Callback(sending: true);
        failedCallback = (_, reason) => { try { Fail(NativeFailure(reason)); } catch (Exception) { } };
    }
    private static Exception NativeFailure(int result) => new COMException("webcam_original_native_audio_failed", result < 0 ? result : unchecked((int)0x80070005));
    private static void RequireSuccess(int result) { if (result != 0) throw NativeFailure(result); }
    private int Callback(bool sending)
        => original.NativeAuthorityStatus(sending);
    internal static PhoneCameraAudioParentRuntime? CreateCurrent(PhoneCameraSession.OutputAuthority original)
    {
        ArgumentNullException.ThrowIfNull(original); original.RequireCurrent();
        if (original.Muted) throw new InvalidOperationException("webcam_muted_owner_must_not_launch_audio_worker");
        var worker = PhoneCameraAudioRuntimePayload.LoadEmbedded();
        if (worker is null) return null;
        var module = PhoneCameraAudioParentModule.LoadCurrent(original);
        if (module is null) return null;
        Calls calls;
        try { calls = Calls.From(module); }
        catch { module.Dispose(); throw; }
        return Register(original, calls, Convert.FromHexString(worker.Sha256));
    }
    private static PhoneCameraAudioParentRuntime Register(PhoneCameraSession.OutputAuthority original, Calls calls, byte[] digest)
    {
        try { original.RequireCurrent(); }
        catch { calls.ReleaseModule(); CryptographicOperations.ZeroMemory(digest); throw; }
        var runtime = new PhoneCameraAudioParentRuntime(original, calls);
        roots.TryAdd(runtime, 0); // BEFORE any native callback pointer is exposed.
        var owner = new OwnerV1 { Size = (uint)Marshal.SizeOf<OwnerV1>(), Version = 1,
            Current = Marshal.GetFunctionPointerForDelegate(runtime.currentCallback), Sending = Marshal.GetFunctionPointerForDelegate(runtime.sendingCallback),
            Failed = Marshal.GetFunctionPointerForDelegate(runtime.failedCallback), Context = IntPtr.Zero };
        var scope = original.Scope;
        var returned = false;
        try
        {
            var result = calls.Create(in scope, digest, (uint)digest.Length, in owner, out runtime.handle); returned = true;
            RequireSuccess(result);
            if (runtime.handle == 0) throw new InvalidDataException("webcam_original_native_handle_required");
            original.RequireCurrent();
            return runtime;
        }
        catch
        {
            // The versioned native Create contract guarantees no registered
            // owner on returned failure/zero handle. A thrown/unknown call or
            // nonzero handle is retained until explicit confirmed cleanup.
            if (returned && runtime.handle == 0) { calls.ReleaseModule(); roots.TryRemove(runtime, out _); }
            else runtime.Stop();
            throw;
        }
        finally { CryptographicOperations.ZeroMemory(digest); }
    }
    private ulong Enter(bool sending, bool preparation = false)
    {
        if (sending) original.RequireSending(); else original.RequireCurrent();
        lock (gate)
        {
            if (closing || Volatile.Read(ref stopped) != 0 || handle == 0) throw new ObjectDisposedException("webcam_original_native_audio_retired");
            if (preparation) { if (prepareCalled) throw new InvalidOperationException("webcam_original_native_prepare_already_used"); prepareCalled = true; }
            else if (!prepared) throw new InvalidOperationException("webcam_original_native_prepare_required");
            active++; return handle;
        }
    }
    private void Exit()
    {
        lock (gate) { --active; if (closing && active == 0) drained.TrySetResult(); }
    }
    private void Fail(Exception failure) { try { original.ReportFailure(failure); } finally { Stop(); } }
    internal async Task PrepareAsync(CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        var own = Enter(sending: false, preparation: true);
        try
        {
            using var registration = cancellation.Register(Stop);
            // Always await the actual native call; never WaitAsync(token) and
            // abandon a later COM/Prepare continuation with live callbacks.
            await Task.Run(() => {
                cancellation.ThrowIfCancellationRequested();
                RequireSuccess(calls.Prepare(own)); original.RequireCurrent(); cancellation.ThrowIfCancellationRequested();
            });
            lock (gate)
            {
                if (closing || Volatile.Read(ref stopped) != 0) throw new ObjectDisposedException("webcam_original_native_audio_retired");
                prepared = true;
            }
        }
        catch (Exception failure) { Fail(failure); throw; }
        finally { Exit(); }
    }
    internal void RequireReady()
    {
        var own = Enter(sending: false);
        try { RequireSuccess(calls.Ready(own)); original.RequireCurrent(); }
        catch (Exception failure) { Fail(failure); throw; }
        finally { Exit(); }
    }
    internal long ObserveVideo(long originalPtsUs)
    {
        var own = Enter(sending: true);
        try { RequireSuccess(calls.Video(own, originalPtsUs, out var mapped)); original.RequireSending(); return mapped; }
        catch (Exception failure) { Fail(failure); throw; }
        finally { Exit(); }
    }
    internal void Write(PhoneCameraMediaFrame frame)
    {
        var record = new byte[PhoneCameraAudioPacket.Bytes]; var own = Enter(sending: true);
        try { PhoneCameraAudioPacket.Write(frame, record); RequireSuccess(calls.Write(own, record, (uint)record.Length)); original.RequireSending(); }
        catch (Exception failure) { Fail(failure); throw; }
        finally { CryptographicOperations.ZeroMemory(record); Exit(); }
    }
    internal byte[] ExportAnchor()
    {
        var record = new byte[33]; var own = Enter(sending: true);
        try { RequireSuccess(calls.Anchor(own, record, (uint)record.Length)); original.RequireSending(); return record; }
        catch (Exception failure) { CryptographicOperations.ZeroMemory(record); Fail(failure); throw; }
        finally { Exit(); }
    }
    // One exact video owner borrows the EXISTING native audio mapper/anchor.
    // The hold is a counted lifetime, never readiness/SEND or a new clock epoch.
    // Video must confirm its own Source cleanup before disposing this hold and
    // awaiting audio Close. Unknown video cleanup must retain it, not unload.
    internal VideoClockLease HoldOriginalVideoClock(PhoneCameraSession.OutputAuthority exactOriginal) => new(this, exactOriginal);
    internal sealed class VideoClockLease : IDisposable
    {
        private PhoneCameraAudioParentRuntime? runtime;
        internal VideoClockLease(PhoneCameraAudioParentRuntime parent, PhoneCameraSession.OutputAuthority exactOriginal)
        {
            if (!ReferenceEquals(parent.original, exactOriginal) || parent.original.Muted)
                throw new InvalidOperationException("webcam_video_clock_original_audio_owner_required");
            parent.Enter(sending: false);
            try
            {
                lock (parent.gate)
                {
                    if (parent.closing || Volatile.Read(ref parent.stopped) != 0)
                        throw new ObjectDisposedException("webcam_original_native_audio_retired");
                    if (parent.videoClockTaken) throw new InvalidOperationException("webcam_video_clock_already_taken");
                    parent.videoClockTaken = true; runtime = parent; // Enter stays counted until exact video cleanup.
                }
            }
            catch { parent.Exit(); throw; }
        }
        private PhoneCameraAudioParentRuntime Current => Volatile.Read(ref runtime) ??
            throw new ObjectDisposedException(nameof(VideoClockLease));
        internal long ObserveVideo(long actuallyAdmittedPtsUs) => Current.ObserveVideo(actuallyAdmittedPtsUs);
        internal byte[] ExportAnchor() => Current.ExportAnchor(); // Same native 33 bytes, never reconstructed.
        internal PhoneCameraAudioParentModule BorrowOriginalModule(PhoneCameraSession.OutputAuthority exactOriginal)
        {
            var parent = Current;
            if (!ReferenceEquals(parent.original, exactOriginal))
                throw new InvalidOperationException("webcam_video_clock_original_audio_owner_required");
            parent.original.RequireCurrent();
            return parent.calls.Module ?? throw new InvalidOperationException("webcam_video_original_native_module_required");
        }
        public void Dispose() => Interlocked.Exchange(ref runtime, null)?.Exit();
    }
    internal void Stop()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        ulong own;
        lock (gate) { if (closing || handle == 0) return; active++; own = handle; }
        try { RequireSuccess(calls.Stop(own)); }
        catch (Exception failure) { try { original.ReportFailure(failure); } catch (Exception) { } }
        finally { Exit(); }
    }
    internal Task CloseAsync()
    {
        lock (gate)
        {
            if (closeTask is not null) return closeTask;
            closing = true; Interlocked.Exchange(ref stopped, 1);
            if (active == 0) drained.TrySetResult();
            return closeTask = Task.Run(CloseCoreAsync);
        }
    }
    private async Task CloseCoreAsync()
    {
        // No new managed calls can enter after closing. Stop interrupts the
        // still-counted original call, then drain BEFORE native Close/unload.
        var own = handle;
        RequireSuccess(calls.Stop(own));
        await drained.Task;
        RequireSuccess(calls.Close(own));
        lock (gate) { handle = 0; }
        calls.ReleaseModule();
        roots.TryRemove(this, out _);
        GC.KeepAlive(currentCallback); GC.KeepAlive(sendingCallback); GC.KeepAlive(failedCallback);
    }
}
