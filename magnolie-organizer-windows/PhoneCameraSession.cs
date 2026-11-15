using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

// Trusted native implementation only, never renderer callbacks or a preview.
// Prepare must honor cancellation; readiness checks and Stop only signal/check
// owned native resources without blocking/reentrancy. Write copies before return,
// is bounded, and must be interruptible by Stop; it must not leave detached IO.
internal interface IPhoneCameraOutputs : IDisposable
{
    Task PrepareAsync(PhoneCameraSession.OutputAuthority original, CancellationToken cancellation);
    void RequireVideoReady();
    void RequireMicrophoneReady();
    void Write(PhoneCameraMediaFrame frame);
    void Stop();
}

/// <summary>
/// One explicitly started original control/listener/AV owner. Constructing does
/// not open outputs, listen, advertise v24, request permission or grant SEND.
/// The native UI/provider bootstrap must supply the original live context and
/// actual system outputs. There is deliberately no default/test fallback.
/// </summary>
internal sealed class PhoneCameraSession
{
    /// <summary>Identity-bound live original context, NOT a readiness or consent
    /// grant. Native outputs retain this exact object; metadata cannot replace it.</summary>
    internal sealed class OutputAuthority
    {
        private readonly PhoneCameraSession owner;
        internal OutputAuthority(PhoneCameraSession owner) { this.owner = owner; }
        internal Guid Scope { get; } = Guid.NewGuid();
        internal bool Muted => owner.muted;
        internal bool Front => owner.front;
        internal void RequireCurrent() => owner.RequireOutputAuthority(this, sending: false);
        internal void RequireSending() => owner.RequireOutputAuthority(this, sending: true);
        // Native lease distinguishes valid preparation from terminal errors by
        // EXACT E_ACCESSDENIED. Never translate an arbitrary failed Current or
        // reconstructed owner into a legitimate preparation/SEND phase.
        internal int NativeAuthorityStatus(bool sending)
        {
            const int denied = unchecked((int)0x80070005);
            try { RequireCurrent(); return sending && !owner.IsSending ? denied : 0; }
            catch (Exception error) { return error.HResult < 0 ? error.HResult : denied; }
        }
        internal void RequirePublication(PhoneCameraControlBinding originalBinding)
        {
            if (!ReferenceEquals(owner.outputAuthority, this) || !ReferenceEquals(owner.binding, originalBinding))
                throw new InvalidOperationException("webcam_original_publication_authority_required");
            try
            {
                RequireCurrent();
                owner.outputs.RequireVideoReady();
                if (!owner.muted) owner.outputs.RequireMicrophoneReady();
                RequireCurrent(); // Readiness callbacks cannot replace or revive the owner.
            }
            catch (Exception failure) { owner.Fail(failure); throw; }
        }
        internal void ReportFailure(Exception failure)
        {
            ArgumentNullException.ThrowIfNull(failure);
            if (!ReferenceEquals(owner.outputAuthority, this)) throw new InvalidOperationException("webcam_original_output_authority_required");
            owner.Fail(failure);
        }
    }
    private readonly TelefonConnection parent;
    private readonly IPhoneCameraOutputs outputs;
    private readonly OutputAuthority outputAuthority;
    private readonly Action originalCurrent;
    private readonly bool muted, front;
    private readonly CancellationTokenSource stop = new();
    private readonly TaskCompletionSource controlReady = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private PhoneCameraControlBinding? binding;
    private Socket? listener;
    private PhoneCameraMediaChannel? media;
    private Socket? accepted;
    private Exception? error, cleanupError;
    private int started, stopping, sending, done, cleanupConfirmed, outputAdmitted;
    private long sentAt, videoAt, audioAt;
    internal Exception? Error => Volatile.Read(ref error);
    internal Exception? CleanupError => Volatile.Read(ref cleanupError);
    internal bool IsSending => Volatile.Read(ref sending) != 0 && !stop.IsCancellationRequested;
    internal bool IsCompletelyStopped => Volatile.Read(ref done) != 0 && Volatile.Read(ref cleanupConfirmed) != 0;
    internal Task ControlReady => controlReady.Task;

    internal PhoneCameraSession(TelefonConnection originalParent, IPhoneCameraOutputs originalOutputs,
        Action originalCurrent, bool muted, bool front)
    {
        parent = originalParent ?? throw new ArgumentNullException(nameof(originalParent));
        outputs = originalOutputs ?? throw new ArgumentNullException(nameof(originalOutputs));
        this.originalCurrent = originalCurrent ?? throw new ArgumentNullException(nameof(originalCurrent));
        this.muted = muted; this.front = front;
        outputAuthority = new OutputAuthority(this);
    }
    // Native bootstrap only; construction remains inert. RunAsync still needs
    // the original connected parent, explicit live opt-in and original control
    // exchange. No renderer, saved permission or screen-share consent fallback.
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static PhoneCameraSession CreateNative(TelefonConnection originalParent, Action originalCurrent, bool muted, bool front) =>
        new(originalParent, new PhoneCameraNativeOutputs(), originalCurrent, muted, front);
    internal Task RunAsync()
    {
        if (Interlocked.Exchange(ref started, 1) != 0) throw new InvalidOperationException("webcam_original_session_already_used");
        return Task.Run(RunCoreAsync);
    }
    internal void Stop()
    {
        if (Interlocked.Exchange(ref stopping, 1) != 0) return;
        // Retire native authority BEFORE cancellation callbacks or output Stop.
        Volatile.Write(ref outputAdmitted, 0); Volatile.Write(ref sending, 0); stop.Cancel();
        // Close only this owner's IO before waiting for a media-reader lock.
        Volatile.Read(ref listener)?.Dispose(); Volatile.Read(ref accepted)?.Dispose();
        Volatile.Read(ref media)?.Dispose();
        try { outputs.Stop(); }
        catch (Exception failure) { Interlocked.CompareExchange(ref cleanupError, failure, null); }
    }
    private void Fail(Exception failure)
    { Interlocked.CompareExchange(ref error, failure, null); Stop(); }
    private void RequireOutputAuthority(OutputAuthority original, bool sending)
    {
        if (!ReferenceEquals(outputAuthority, original)) throw new InvalidOperationException("webcam_original_output_authority_required");
        if (Volatile.Read(ref stopping) != 0 || stop.IsCancellationRequested) throw new ObjectDisposedException("webcam_original_output_owner_retired");
        if (Volatile.Read(ref outputAdmitted) != 1 || binding is null) throw new InvalidOperationException("webcam_original_joined_output_context_required");
        // Do NOT call RequireMediaContext/output readiness here: preparation and
        // native lease publication need Current before readiness and actual SEND.
        try { binding.RequireCurrent(); }
        catch (Exception failure) { Fail(failure); throw; }
        if (Volatile.Read(ref stopping) != 0 || stop.IsCancellationRequested) throw new ObjectDisposedException("webcam_original_output_owner_retired");
        if (sending && !IsSending) throw new InvalidOperationException("webcam_actual_send_required");
    }
    private void RequireMediaContext()
    {
        stop.Token.ThrowIfCancellationRequested(); binding!.RequireCurrent();
        outputs.RequireVideoReady(); if (!muted) outputs.RequireMicrophoneReady();
    }
    private void RequireSending()
    {
        RequireMediaContext();
        if (!IsSending) throw new InvalidOperationException("webcam_actual_send_required");
    }
    private static JsonObject Report(JsonObject probe, string op, string session)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = PhoneCameraControl.Report, ["created_ms"] = now, ["expires_ms"] = now + 60000,
            ["body"] = new JsonObject { ["version"] = 24, ["request_id"] = probe["body"]!["request_id"]!.DeepClone(),
                ["nonce"] = probe["body"]!["nonce"]!.DeepClone(), ["op"] = op, ["session"] = session } };
    }
    private async Task ControlsAsync(TaskCompletionSource prepared)
    {
        try
        {
            while (!stop.IsCancellationRequested)
            {
                var control = await binding!.ReadAsync(stop.Token);
                switch (control["body"]!["op"]!.GetValue<string>())
                {
                    case "prepared":
                        if (!prepared.TrySetResult()) throw new InvalidDataException("webcam_duplicate_prepared");
                        break;
                    case "stop": Stop(); return;
                    case "error": throw new IOException("webcam_phone_capture_failed");
                    default: throw new InvalidDataException("webcam_control_phase_invalid");
                }
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (Exception failure) { Fail(failure); }
    }
    private async Task MonitorAsync()
    {
        try
        {
            var begin = Stopwatch.GetTimestamp();
            while (!stop.IsCancellationRequested)
            {
                binding!.RequireCurrent();
                if (IsSending)
                {
                    RequireSending();
                    var initial = Stopwatch.GetElapsedTime(Volatile.Read(ref sentAt)) >= TimeSpan.FromSeconds(2);
                    var video = Volatile.Read(ref videoAt); var audio = Volatile.Read(ref audioAt);
                    if ((video == 0 && initial) || (!muted && audio == 0 && initial) ||
                        video != 0 && Stopwatch.GetElapsedTime(video) > TimeSpan.FromMilliseconds(500) ||
                        !muted && audio != 0 && Stopwatch.GetElapsedTime(audio) > TimeSpan.FromMilliseconds(500))
                        throw new IOException("webcam_joined_track_stalled");
                }
                else if (Stopwatch.GetElapsedTime(begin) >= TimeSpan.FromSeconds(60)) throw new TimeoutException("webcam_original_start_timeout");
                await Task.Delay(50, stop.Token);
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (Exception failure) { Fail(failure); }
    }
    private async Task ReceiveAsync()
    {
        long videoSequence = 0, audioSequence = 0, videoPts = -1, audioPts = -1;
        long? firstPts = null; long anchor = 0;
        while (!stop.IsCancellationRequested)
        {
            RequireSending(); var frame = media!.Receive();
            try
            {
                var expected = frame.Video ? videoSequence : audioSequence;
                var previous = frame.Video ? videoPts : audioPts;
                if (!frame.Video && muted || frame.Sequence != expected || expected == long.MaxValue || frame.PresentationTimeUs <= previous)
                    throw new InvalidDataException("webcam_track_continuity_invalid");
                var other = frame.Video ? audioPts : videoPts;
                if (other >= 0 && Math.Abs(frame.PresentationTimeUs - other) > 250000) throw new InvalidDataException("webcam_tracks_diverged");
                if (firstPts is null) { firstPts = frame.PresentationTimeUs; anchor = Stopwatch.GetTimestamp(); }
                var offset = frame.PresentationTimeUs - firstPts.Value;
                while (true)
                {
                    RequireSending();
                    var remaining = offset - Stopwatch.GetElapsedTime(anchor).Ticks / 10;
                    if (remaining is < -250000 or > 250000) throw new IOException("webcam_presentation_outside_bound");
                    if (remaining <= 0) break;
                    await Task.Delay(TimeSpan.FromMilliseconds(Math.Min(10d, remaining / 1000d)), stop.Token);
                }
                RequireSending(); outputs.Write(frame); RequireSending();
                var now = Stopwatch.GetTimestamp();
                if (frame.Video) { videoSequence++; videoPts = frame.PresentationTimeUs; Volatile.Write(ref videoAt, now); }
                else { audioSequence++; audioPts = frame.PresentationTimeUs; Volatile.Write(ref audioAt, now); }
            }
            finally { CryptographicOperations.ZeroMemory(frame.Data); }
        }
    }
    private async Task RunCoreAsync()
    {
        JsonObject? probe = null; string? session = null; byte[]? secret = null;
        Task? monitor = null, controls = null;
        try
        {
            stop.Token.ThrowIfCancellationRequested(); originalCurrent();
            binding = parent.BindWebcamControl(originalCurrent, Stop);
            controlReady.TrySetResult();
            monitor = MonitorAsync();
            probe = await binding.ReadAsync(stop.Token);
            if (probe["body"]!["op"]!.GetValue<string>() != "probe") throw new InvalidDataException("webcam_probe_required");
            session = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
            secret = RandomNumberGenerator.GetBytes(32); binding.BindSession(session);
            var opened = parent.OpenWebcamListener(binding); listener = opened.Listener;
            var offer = Report(probe, "offer", session); var body = offer["body"]!.AsObject();
            body["secret"] = Convert.ToHexString(secret).ToLowerInvariant(); body["port"] = ((IPEndPoint)listener.LocalEndPoint!).Port;
            body["muted"] = muted; body["front"] = front;
            try { await binding.SendAsync(offer); }
            catch (Exception failure) { Fail(failure); throw; }
            var prepared = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            controls = ControlsAsync(prepared);
            await prepared.Task.WaitAsync(stop.Token);
            using var acceptDeadline = CancellationTokenSource.CreateLinkedTokenSource(stop.Token); acceptDeadline.CancelAfter(TimeSpan.FromSeconds(2));
            accepted = await listener.AcceptAsync(acceptDeadline.Token);
            binding.RequireCurrent();
            if (accepted.RemoteEndPoint is not IPEndPoint remote || !remote.Address.Equals(opened.Remote))
                throw new InvalidDataException("webcam_original_phone_ip_required");
            listener.Dispose(); listener = null;
            Volatile.Write(ref outputAdmitted, 1);
            outputAuthority.RequireCurrent();
            using var outputDeadline = CancellationTokenSource.CreateLinkedTokenSource(stop.Token); outputDeadline.CancelAfter(TimeSpan.FromSeconds(10));
            await outputs.PrepareAsync(outputAuthority, outputDeadline.Token);
            RequireMediaContext();
            media = new PhoneCameraMediaChannel(accepted, session, secret, RequireMediaContext);
            // Construction admits only the original prepared socket/context.
            // ReceiveAsync is unreachable until actual SEND publication succeeds.
            try { await binding.SendPreparedAsync(Report(probe, "send", session), outputAuthority); }
            catch (Exception failure) { Fail(failure); throw; }
            Volatile.Write(ref sentAt, Stopwatch.GetTimestamp()); Volatile.Write(ref sending, 1);
            await ReceiveAsync();
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (Exception failure) when (stop.IsCancellationRequested && failure is IOException or SocketException or ObjectDisposedException) { }
        catch (Exception failure) { Fail(failure); }
        finally
        {
            Stop();
            controlReady.TrySetCanceled(stop.Token);
            listener?.Dispose(); accepted?.Dispose(); media?.Dispose();
            if (controls is not null) await controls;
            if (monitor is not null) await monitor;
            if (binding is not null && probe is not null && session is not null)
                try { await binding.SendAsync(Report(probe, "stop", session)); } catch (Exception) { }
            binding?.Dispose();
            try { outputs.Dispose(); if (CleanupError is null && binding?.RetirementError is null) Volatile.Write(ref cleanupConfirmed, 1); }
            catch (Exception failure) { Interlocked.CompareExchange(ref cleanupError, failure, null); }
            if (secret is not null) CryptographicOperations.ZeroMemory(secret);
            Volatile.Write(ref done, 1);
        }
    }
}
