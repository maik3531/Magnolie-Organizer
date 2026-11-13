using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

// Exact original native video owner. No UI/config paths, staging, installers,
// second module load for joined audio, or callbacks supplied by a renderer.
[SupportedOSPlatform("windows")]
internal sealed partial class PhoneCameraVideoParentRuntime
{
    private const int NotInitialized = unchecked((int)0xc00d36b6); // MF_E_NOT_INITIALIZED, NOT platform-not-initialized.
    private const int Denied = unchecked((int)0x80070005);
    [StructLayout(LayoutKind.Sequential)]
    private struct OwnerV1
    {
        internal uint Size, Version, Flags, Reserved;
        internal IntPtr Current, Sending, Failed, Registration, ObserveVideo, ExportAnchor, Context;
    }
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate uint VersionFunction();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int CheckFunction(IntPtr context);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void FailureFunction(IntPtr context, int reason);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int MapFunction(IntPtr context, long pts, out long mapped);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int ExportFunction(IntPtr context, IntPtr record, uint bytes);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int CreateFunction(in Guid scope, in OwnerV1 owner, out ulong handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int HandleFunction(ulong handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int WriteFunction(ulong handle, [In] byte[] record, uint bytes);
    private sealed class Calls
    {
        internal required CreateFunction Create;
        internal required HandleFunction Prepare, Ready, Stop, Close;
        internal required WriteFunction Write;
        internal static Calls From(PhoneCameraAudioParentModule module)
        {
            if (module.Export<VersionFunction>("MagnoliePhoneVideoVersion")() != 1)
                throw new InvalidDataException("webcam_video_abi_version_invalid");
            return new() {
                Create = module.Export<CreateFunction>("MagnoliePhoneVideoCreate"), Prepare = module.Export<HandleFunction>("MagnoliePhoneVideoPrepare"),
                Ready = module.Export<HandleFunction>("MagnoliePhoneVideoRequireReady"), Stop = module.Export<HandleFunction>("MagnoliePhoneVideoStop"),
                Close = module.Export<HandleFunction>("MagnoliePhoneVideoClose"), Write = module.Export<WriteFunction>("MagnoliePhoneVideoWrite")
            };
        }
    }
    internal sealed class UnconfirmedCreationException(Exception cause) : Exception("webcam_video_create_cleanup_unconfirmed", cause);
    private static readonly ConcurrentDictionary<PhoneCameraVideoParentRuntime, byte> roots = new();
    private readonly PhoneCameraSession.OutputAuthority original;
    private readonly Calls calls;
    private readonly PhoneCameraAudioParentRuntime.VideoClockLease? audioClock;
    private readonly PhoneCameraAudioParentModule? ownModule;
    private readonly IDisposable source;
    private readonly Action sourceCurrent;
    private readonly CheckFunction current, sending, registration;
    private readonly FailureFunction failed;
    private readonly MapFunction observe;
    private readonly ExportFunction export;
    private readonly object gate = new();
    private readonly TaskCompletionSource drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private ulong handle;
    private int active, stopped, registrationEnded;
    private bool prepareCalled, prepared, closing;
    private Task? closeTask;
    private PhoneCameraVideoParentRuntime(PhoneCameraSession.OutputAuthority original, Calls calls,
        IDisposable source, Action sourceCurrent, PhoneCameraAudioParentModule? ownModule,
        PhoneCameraAudioParentRuntime.VideoClockLease? audioClock)
    {
        this.original = original; this.calls = calls; this.source = source; this.sourceCurrent = sourceCurrent;
        this.ownModule = ownModule; this.audioClock = audioClock;
        current = _ => Authority(sending: false);
        sending = _ => Authority(sending: true);
        // Registration is ONLY the held native lifetime. Registry IO is done on
        // ordinary Prepare/readiness/write callers, never an MF/lease callback.
        registration = _ => Volatile.Read(ref registrationEnded) == 0 ? 0 : Denied;
        failed = (_, reason) => { try { Fail(NativeFailure(reason)); } catch (Exception) { } };
        observe = (IntPtr _, long pts, out long mapped) => {
            mapped = 0;
            try { original.RequireSending(); mapped = this.audioClock!.ObserveVideo(pts); original.RequireSending(); return 0; }
            catch (Exception error) { return FailureStatus(error); }
        };
        export = (_, destination, bytes) => {
            byte[]? record = null;
            try
            {
                original.RequireSending();
                if (destination == IntPtr.Zero || bytes != 33) return unchecked((int)0x80070057);
                record = this.audioClock!.ExportAnchor();
                if (record.Length != 33) return unchecked((int)0x80070057);
                Marshal.Copy(record, 0, destination, 33); original.RequireSending(); return 0;
            }
            catch (Exception error) { return FailureStatus(error); }
            finally { if (record is not null) CryptographicOperations.ZeroMemory(record); }
        };
    }
    private static int FailureStatus(Exception error) => error.HResult < 0 ? error.HResult : Denied;
    private static Exception NativeFailure(int status) => new COMException("webcam_original_native_video_failed", status < 0 ? status : Denied);
    private static void RequireSuccess(int status) { if (status != 0) throw NativeFailure(status); }
    private int Authority(bool sending)
        => original.NativeAuthorityStatus(sending);
    internal static PhoneCameraVideoParentRuntime CreateCurrent(PhoneCameraSession.OutputAuthority original, PhoneCameraAudioParentRuntime? audio)
    {
        ArgumentNullException.ThrowIfNull(original); original.RequireCurrent();
        if (original.Muted != (audio is null)) throw new InvalidOperationException("webcam_original_video_audio_mode_required");
        var source = PhoneCameraSourceRegistration.HoldInstalledCurrent() ?? throw new InvalidOperationException("webcam_installed_source_required");
        PhoneCameraAudioParentRuntime.VideoClockLease? clock = null;
        PhoneCameraAudioParentModule? own = null;
        Calls calls;
        try
        {
            clock = audio?.HoldOriginalVideoClock(original);
            var module = clock is null ? own = PhoneCameraAudioParentModule.LoadCurrent(original) ??
                throw new InvalidOperationException("webcam_video_parent_payload_required") : clock.BorrowOriginalModule(original);
            calls = Calls.From(module); source.RequireCurrent(); original.RequireCurrent();
        }
        catch { own?.Dispose(); clock?.Dispose(); source.Dispose(); throw; }
        PhoneCameraVideoParentRuntime runtime;
        try { runtime = new PhoneCameraVideoParentRuntime(original, calls, source, source.RequireCurrent, own, clock); }
        catch { own?.Dispose(); clock?.Dispose(); source.Dispose(); throw; }
        return Register(runtime);
    }
    private static PhoneCameraVideoParentRuntime Register(PhoneCameraVideoParentRuntime runtime)
    {
        roots.TryAdd(runtime, 0);
        var scope = runtime.original.Scope; var invoked = false; var returned = false;
        try
        {
            var owner = new OwnerV1 { Size = (uint)Marshal.SizeOf<OwnerV1>(), Version = 1, Flags = runtime.original.Muted ? 1u : 0u,
                Current = Marshal.GetFunctionPointerForDelegate(runtime.current), Sending = Marshal.GetFunctionPointerForDelegate(runtime.sending),
                Failed = Marshal.GetFunctionPointerForDelegate(runtime.failed), Registration = Marshal.GetFunctionPointerForDelegate(runtime.registration),
                ObserveVideo = runtime.original.Muted ? IntPtr.Zero : Marshal.GetFunctionPointerForDelegate(runtime.observe),
                ExportAnchor = runtime.original.Muted ? IntPtr.Zero : Marshal.GetFunctionPointerForDelegate(runtime.export), Reserved = 0, Context = IntPtr.Zero };
            invoked = true;
            var status = runtime.calls.Create(in scope, in owner, out runtime.handle); returned = true;
            RequireSuccess(status);
            if (runtime.handle == 0) throw new InvalidDataException("webcam_original_video_handle_required");
            runtime.original.RequireCurrent(); return runtime;
        }
        catch (Exception error)
        {
            if (!invoked || returned && runtime.handle == 0) { runtime.Release(); throw; }
            runtime.Stop(); throw new UnconfirmedCreationException(error); // Retain exact root/module/source/audio clock.
        }
    }
    private ulong Enter(bool sending, bool preparation = false)
    {
        if (sending) original.RequireSending(); else original.RequireCurrent();
        try { sourceCurrent(); }
        catch (Exception error) { Fail(error); throw; }
        lock (gate)
        {
            if (closing || Volatile.Read(ref stopped) != 0 || handle == 0) throw new ObjectDisposedException("webcam_original_video_retired");
            if (preparation) { if (prepareCalled) throw new InvalidOperationException("webcam_video_prepare_already_used"); prepareCalled = true; }
            else if (!prepared) throw new InvalidOperationException("webcam_video_prepare_required");
            active++; return handle;
        }
    }
    private void Exit() { lock (gate) { --active; if (closing && active == 0) drained.TrySetResult(); } }
    private void Fail(Exception error) { try { original.ReportFailure(error); } finally { Stop(); } }
    internal async Task PrepareAsync(CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested(); var own = Enter(sending: false, preparation: true);
        try
        {
            using var stop = cancellation.Register(Stop);
            await Task.Run(() => { cancellation.ThrowIfCancellationRequested(); RequireSuccess(calls.Prepare(own)); });
            // Only actual MF Start is readiness. Wait under the ORIGINAL live
            // control deadline/cancellation; no artificial Ready or longer lease.
            for (;;)
            {
                cancellation.ThrowIfCancellationRequested(); original.RequireCurrent(); sourceCurrent();
                if (Volatile.Read(ref stopped) != 0) throw new ObjectDisposedException("webcam_original_video_retired");
                var status = calls.Ready(own);
                if (status == 0) break;
                if (status != NotInitialized) RequireSuccess(status);
                await Task.Delay(50, cancellation);
            }
            lock (gate)
            {
                if (closing || Volatile.Read(ref stopped) != 0) throw new ObjectDisposedException("webcam_original_video_retired");
                prepared = true;
            }
        }
        catch (Exception error) { Fail(error); throw; }
        finally { Exit(); }
    }
    internal void RequireReady()
    {
        var own = Enter(sending: false);
        try { RequireSuccess(calls.Ready(own)); original.RequireCurrent(); }
        catch (Exception error) { Fail(error); throw; }
        finally { Exit(); }
    }
    internal void Write(PhoneCameraMediaFrame frame)
    {
        var record = new byte[PhoneCameraVideoPacket.Bytes]; var own = Enter(sending: true);
        try { PhoneCameraVideoPacket.Write(frame, record); RequireSuccess(calls.Write(own, record, (uint)record.Length)); original.RequireSending(); }
        catch (Exception error) { Fail(error); throw; }
        finally { CryptographicOperations.ZeroMemory(record); Exit(); }
    }
    internal void Stop()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        ulong own;
        lock (gate) { if (closing || handle == 0) return; active++; own = handle; }
        try { RequireSuccess(calls.Stop(own)); }
        catch (Exception error) { try { original.ReportFailure(error); } catch (Exception) { } }
        finally { Exit(); }
    }
    internal Task CloseAsync()
    {
        lock (gate)
        {
            if (closeTask is not null) return closeTask;
            closing = true; Interlocked.Exchange(ref stopped, 1);
            if (active == 0) drained.TrySetResult();
            return closeTask = Task.Run(async () => {
                RequireSuccess(calls.Stop(handle)); await drained.Task;
                RequireSuccess(calls.Close(handle)); handle = 0; Release();
            });
        }
    }
    private void Release()
    {
        Volatile.Write(ref registrationEnded, 1);
        source.Dispose(); audioClock?.Dispose(); ownModule?.Dispose(); roots.TryRemove(this, out _);
        GC.KeepAlive(current); GC.KeepAlive(sending); GC.KeepAlive(registration); GC.KeepAlive(failed); GC.KeepAlive(observe); GC.KeepAlive(export);
    }
}
