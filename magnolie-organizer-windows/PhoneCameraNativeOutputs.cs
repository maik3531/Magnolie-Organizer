using System.Runtime.Versioning;

namespace MagnolieOrganizer.Windows;

// Trusted native session composition. Construction is inert/default OFF. The
// existing session admits the ORIGINAL OutputAuthority before calling Prepare.
// No screen-sharing consent, setup/UAC, worker fallback or synthetic media here.
[SupportedOSPlatform("windows")]
internal sealed partial class PhoneCameraNativeOutputs : IPhoneCameraOutputs
{
    private readonly object gate = new();
    private readonly CancellationTokenSource stop = new();
    private PhoneCameraSession.OutputAuthority? original;
    private PhoneCameraAudioParentRuntime? audio;
    private PhoneCameraVideoParentRuntime? video;
    private Task? preparation, cleanup;
    private int stopping;
    private bool unconfirmedVideoCreation;
    public Task PrepareAsync(PhoneCameraSession.OutputAuthority original, CancellationToken cancellation)
    {
        ArgumentNullException.ThrowIfNull(original); original.RequireCurrent();
        lock (gate)
        {
            if (preparation is not null || Volatile.Read(ref stopping) != 0) throw new InvalidOperationException("webcam_native_output_owner_already_used");
            this.original = original;
            return preparation = Task.Run(async () => {
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellation, stop.Token);
                var token = linked.Token;
                token.ThrowIfCancellationRequested();
                // Fail on missing/unprotected Source BEFORE launching even our
                // own audio worker. Hold this readback through the hand-off to
                // video's independent pinned installed lease; never install here.
                using var installed = PhoneCameraSourceRegistration.HoldInstalledCurrent() ??
                    throw new InvalidOperationException("webcam_installed_source_required");
                installed.RequireCurrent(); original.RequireCurrent();
                if (!original.Muted)
                {
                    var ownAudio = PhoneCameraAudioParentRuntime.CreateCurrent(original) ?? throw new InvalidOperationException("webcam_original_audio_payload_required");
                    Volatile.Write(ref audio, ownAudio);
                    if (Volatile.Read(ref stopping) != 0) ownAudio.Stop();
                    await ownAudio.PrepareAsync(token);
                }
                original.RequireCurrent(); token.ThrowIfCancellationRequested();
                PhoneCameraVideoParentRuntime ownVideo;
                try { ownVideo = PhoneCameraVideoParentRuntime.CreateCurrent(original, audio); }
                catch (PhoneCameraVideoParentRuntime.UnconfirmedCreationException) { unconfirmedVideoCreation = true; throw; }
                Volatile.Write(ref video, ownVideo);
                if (Volatile.Read(ref stopping) != 0) ownVideo.Stop();
                await ownVideo.PrepareAsync(token);
                original.RequireCurrent();
            });
        }
    }
    public void RequireVideoReady() => (Volatile.Read(ref video) ?? throw new InvalidOperationException("webcam_native_video_prepare_required")).RequireReady();
    public void RequireMicrophoneReady() => (Volatile.Read(ref audio) ?? throw new InvalidOperationException("webcam_original_microphone_not_prepared")).RequireReady();
    public void Write(PhoneCameraMediaFrame frame)
    {
        ArgumentNullException.ThrowIfNull(frame);
        (original ?? throw new InvalidOperationException("webcam_original_output_owner_required")).RequireSending();
        if (frame.Video) (Volatile.Read(ref video) ?? throw new InvalidOperationException("webcam_native_video_prepare_required")).Write(frame);
        else (Volatile.Read(ref audio) ?? throw new InvalidOperationException("webcam_original_microphone_not_prepared")).Write(frame);
    }
    public void Stop()
    {
        if (Interlocked.Exchange(ref stopping, 1) != 0) return;
        stop.Cancel();
        Volatile.Read(ref video)?.Stop(); Volatile.Read(ref audio)?.Stop();
    }
    public void Dispose()
    {
        Stop();
        Task closing;
        lock (gate) closing = cleanup ??= Task.Run(async () => {
            var preparing = preparation;
            if (preparing is not null) { try { await preparing; } catch (Exception) { } }
            if (unconfirmedVideoCreation) throw new InvalidOperationException("webcam_video_create_cleanup_unconfirmed");
            // Never await audio Close while video still holds its mapper/module.
            // Unknown Source cleanup retains both exact runtimes and callbacks.
            if (video is not null) await video.CloseAsync();
            if (audio is not null) await audio.CloseAsync();
            stop.Dispose();
        });
        closing.GetAwaiter().GetResult();
    }
}
