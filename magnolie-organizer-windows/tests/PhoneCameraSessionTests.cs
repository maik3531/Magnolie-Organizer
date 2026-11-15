using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraSessionTests
{
    // Controlled test adapter only. Never installed or selected by product code.
    private sealed class Outputs : IPhoneCameraOutputs
    {
        internal readonly ConcurrentQueue<(bool Video, long Pts, byte[] Data, long At)> Written = new();
        internal readonly TaskCompletionSource Preparing = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource ContinuePreparation = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource Writing = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly ManualResetEventSlim finishWrite = new(false);
        internal bool HoldPreparation, MissingMicrophone, FailCleanup, HoldWrite;
        internal int Prepared, MicrophoneChecks, Stopped, Disposed;
        internal PhoneCameraSession.OutputAuthority? Authority;
        internal readonly SemaphoreSlim Writes = new(0);
        public async Task PrepareAsync(PhoneCameraSession.OutputAuthority original, CancellationToken cancellation)
        {
            original.RequireCurrent();
            Volatile.Write(ref Authority, original);
            Interlocked.Increment(ref Prepared); Preparing.TrySetResult();
            if (HoldPreparation) await ContinuePreparation.Task.WaitAsync(cancellation);
        }
        public void RequireVideoReady() { if (Prepared != 1 || Stopped != 0) throw new IOException("controlled video not ready"); }
        public void RequireMicrophoneReady()
        { Interlocked.Increment(ref MicrophoneChecks); if (MissingMicrophone) throw new IOException("controlled required microphone missing"); }
        public void Write(PhoneCameraMediaFrame frame)
        {
            Authority!.RequireSending();
            if (HoldWrite)
            {
                Writing.TrySetResult();
                if (!finishWrite.Wait(TimeSpan.FromSeconds(4))) throw new IOException("controlled native write watchdog");
                if (Stopped != 0) throw new OperationCanceledException("controlled native write interrupted");
            }
            Written.Enqueue((frame.Video, frame.PresentationTimeUs, frame.Data.ToArray(), Stopwatch.GetTimestamp())); Writes.Release();
        }
        public void Stop() { Interlocked.Increment(ref Stopped); finishWrite.Set(); }
        public void Dispose() { Interlocked.Increment(ref Disposed); finishWrite.Dispose(); if (FailCleanup) throw new IOException("controlled cleanup not confirmed"); }
    }
    private sealed class Fixture : IAsyncDisposable
    {
        internal readonly PhoneCameraParentTests.Fixture Parent = new();
        internal readonly Outputs Output = new();
        internal readonly CancellationTokenSource Deadline = new(TimeSpan.FromSeconds(9));
        internal readonly JsonObject Probe = PhoneCameraParentTests.Message();
        internal readonly PhoneCameraSession Session;
        internal readonly Task ParentRun, Run;
        internal Socket? Sender;
        internal string Identity = "";
        internal byte[] Secret = [];
        internal bool Current = true, SawSend;
        private long readSequence, phoneSequence, mediaSequence;
        internal Fixture(bool muted = false)
        {
            Session = new PhoneCameraSession(Parent.Connection, Output,
                () => { if (!Current) throw new InvalidOperationException("controlled original native context revoked"); }, muted, true);
            ParentRun = Parent.Connection.RunAsync(); Run = Session.RunAsync();
        }
        private async Task<JsonObject> Next()
        {
            var value = await Parent.Read(readSequence++);
            if (value["kind"]?.GetValue<string>() == PhoneCameraControl.Report && value["body"]?["op"]?.GetValue<string>() == "send") SawSend = true;
            return value;
        }
        internal async Task OfferAsync()
        {
            await Session.ControlReady.WaitAsync(Deadline.Token); await Parent.Send(Probe, phoneSequence++);
            JsonObject? offer = null;
            for (int i = 0; i < 3 && offer is null; ++i)
            {
                var value = await Next();
                if (value["body"]?["op"]?.GetValue<string>() == "offer") offer = value;
                else TestAssert.That(value["type"]?.GetValue<string>() == "ack", "Unexpected original control before OFFER");
            }
            TestAssert.That(offer is not null && Output.Prepared == 0 && !Session.IsSending && !SawSend, "Outputs/SEND started before phone preparation");
            Identity = offer!["body"]!["session"]!.GetValue<string>(); Secret = Convert.FromHexString(offer["body"]!["secret"]!.GetValue<string>());
            TestAssert.That(offer["body"]!["front"]!.GetValue<bool>(), "Original camera choice lost");
            Sender = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp) { SendTimeout = 2000 };
            await Sender.ConnectAsync(new IPEndPoint(IPAddress.Loopback, offer["body"]!["port"]!.GetValue<int>()), Deadline.Token);
        }
        internal Task PreparedAsync() => Parent.Send(PhoneCameraParentTests.Follow(Probe, "prepared", Identity), phoneSequence++);
        internal async Task ReadSendOrStopAsync()
        {
            for (int i = 0; i < 4; ++i)
            {
                var value = await Next(); var op = value["body"]?["op"]?.GetValue<string>();
                if (op is "send" or "stop") return;
                TestAssert.That(value["type"]?.GetValue<string>() == "ack", "Unexpected parent response");
            }
            throw new Exception("No SEND/STOP response");
        }
        internal async Task SendFrame(bool video, ulong sequence, ulong pts)
        {
            var data = PhoneCameraMediaChannelTests.Packet((ulong)mediaSequence++, video ? (byte)1 : (byte)2, sequence, pts,
                video ? PhoneCameraMediaChannel.VideoBytes : PhoneCameraMediaChannel.AudioBytes, video ? (byte)60 : (byte)42,
                sessionIdentity: Identity, sessionSecret: Secret);
            for (int at = 0; at < data.Length;)
                at += await Sender!.SendAsync(data.AsMemory(at), SocketFlags.None, Deadline.Token);
        }
        internal async Task WaitWrites(int count)
        { for (int i = 0; i < count; ++i) await Output.Writes.WaitAsync(Deadline.Token); }
        public async ValueTask DisposeAsync()
        {
            Session.Stop(); Sender?.Dispose();
            try { await Run.WaitAsync(TimeSpan.FromSeconds(4)); }
            finally
            {
                Parent.Connection.Dispose();
                try { await ParentRun.WaitAsync(TimeSpan.FromSeconds(3)); } catch (Exception) { }
                Parent.Dispose(); Deadline.Dispose(); Output.Writes.Dispose();
            }
        }
    }
    internal static async Task JoinedEncryptedAvAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        TestAssert.That(f.SawSend && f.Output.Prepared == 1, "SEND not published after original PREPARED/provider preparation");
        await f.SendFrame(false,0,0); await f.SendFrame(true,0,0); await f.SendFrame(false,1,20000);
        await f.SendFrame(false,2,40000); await f.SendFrame(false,3,60000); await f.SendFrame(true,1,66667);
        await f.WaitWrites(6); f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        var written = f.Output.Written.ToArray();
        TestAssert.That(written.Length == 6 && written.All(v => v.Data.All(b => b == (v.Video ? 60 : 42))), "Actual binary AV changed before native handoff");
        TestAssert.That(written[2].Pts-written[0].Pts == 20000 && written[5].Pts-written[0].Pts == 66667 &&
            Stopwatch.GetElapsedTime(written[0].At,written[2].At) >= TimeSpan.FromMilliseconds(10) &&
            Stopwatch.GetElapsedTime(written[0].At,written[5].At) >= TimeSpan.FromMilliseconds(40), "Joined output burst lost original presentation spacing");
        TestAssert.That(f.Session.Error is null && f.Session.IsCompletelyStopped && f.Output.Stopped == 1 && f.Output.Disposed == 1, "Original joined AV cleanup not confirmed");
        f.Parent.NoPersistentControls();
    }
    internal static async Task MissingMicrophonePreventsSendAsync()
    {
        await using var f = new Fixture(); f.Output.MissingMicrophone = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(!f.SawSend && f.Output.Written.IsEmpty && f.Session.Error is IOException && f.Session.IsCompletelyStopped,
            "Missing microphone silently fell back to video or granted SEND");
    }
    internal static async Task ExplicitMuteAsync()
    {
        await using var f = new Fixture(muted:true); f.Output.MissingMicrophone = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        await f.SendFrame(true,0,0); await f.SendFrame(true,1,66667); await f.WaitWrites(2);
        f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.SawSend && f.Session.Error is null && f.Output.MicrophoneChecks == 0 && f.Session.IsCompletelyStopped, "Explicit mute was ignored or required a fake audio endpoint");
    }
    internal static async Task FailedSendNeverReadsMediaAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        await f.Parent.Writer.WaitAsync(f.Deadline.Token);
        try
        {
            f.Output.ContinuePreparation.TrySetResult(); await f.Run.WaitAsync(f.Deadline.Token);
            TestAssert.That(!f.Session.IsSending && f.Output.Written.IsEmpty && f.Session.Error is not null,
                "Unpublished SEND admitted media/native output");
        }
        finally { f.Parent.Writer.Release(); }
    }
    internal static async Task RevocationStopsPendingInputAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        f.Current = false; await f.Run.WaitAsync(TimeSpan.FromSeconds(3));
        TestAssert.That(!f.Session.IsSending && f.Session.Error is not null && f.Session.IsCompletelyStopped && f.Output.Written.IsEmpty,
            "Revocation failed to interrupt original pending media input");
        f.Current = true; TestAssert.Throws<InvalidOperationException>(() => f.Session.RunAsync(), "Old owner revived after context restoration");
    }
    internal static async Task TrackGapRetiresBothAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        await f.SendFrame(false,0,0); await f.WaitWrites(1); await f.SendFrame(true,1,1000); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.Session.Error is InvalidDataException && f.Output.Written.Count == 1 && f.Session.IsCompletelyStopped,
            "Track gap was admitted or left other output running");
    }
    internal static async Task CleanupFailureRemainsPendingAsync()
    {
        await using var f = new Fixture(); f.Output.FailCleanup = true;
        await f.OfferAsync(); f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.Session.CleanupError is IOException && !f.Session.IsCompletelyStopped, "Unconfirmed provider cleanup presented as a stopped reusable owner");
        TestAssert.Throws<InvalidOperationException>(() => f.Session.RunAsync(), "Unknown cleanup outcome was retried");
    }
    internal static async Task MissingInitialTrackAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        // Audio stays active through its original 20ms presentation cadence;
        // the missing video track, not inactivity of audio, must end the run.
        for (ulong i = 0; i < 100; ++i) await f.SendFrame(false,i,i*20000);
        await f.Run.WaitAsync(TimeSpan.FromSeconds(4));
        TestAssert.That(f.Session.Error is IOException && f.Session.Error.Message == "webcam_joined_track_stalled" &&
            f.Output.Written.Count >= 50 && f.Output.Written.All(v => !v.Video) && f.Session.IsCompletelyStopped,
            "Missing initial video did not retire active joined audio");
    }
    internal static async Task MutedAudioRejectedAsync()
    {
        await using var f = new Fixture(muted:true); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        await f.SendFrame(false,0,0); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.Session.Error is InvalidDataException && f.Output.Written.IsEmpty && f.Session.IsCompletelyStopped,
            "Muted session accepted undeclared microphone audio");
    }
    internal static async Task RevocationInterruptsNativeWriteAsync()
    {
        await using var f = new Fixture(); f.Output.HoldWrite = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync(); await f.SendFrame(false,0,0);
        await f.Output.Writing.Task.WaitAsync(f.Deadline.Token); f.Current = false;
        await f.Run.WaitAsync(TimeSpan.FromSeconds(3));
        TestAssert.That(f.Session.Error is not null && f.Output.Written.IsEmpty && f.Output.Stopped == 1 && f.Session.IsCompletelyStopped,
             "Original guard loss left native output write blocked/alive");
    }
    internal static async Task AuthorityPrepareThenActualSendAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); TestAssert.That(f.Output.Authority is null, "Output context escaped before original phone PREPARED");
        await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var authority = f.Output.Authority!; authority.RequireCurrent();
        TestAssert.That(authority.Scope != Guid.Empty && !authority.Muted && authority.Front && !f.Session.IsSending && !f.SawSend,
            "Original configuration or prepare/SEND phase lost");
        TestAssert.Throws<InvalidOperationException>(authority.RequireSending, "Prepare invented actual SEND");
        authority.RequireCurrent(); TestAssert.That(f.Session.Error is null && f.Output.MicrophoneChecks == 0,
            "Prepare authority recursed into readiness or refused Current while SEND was pending");
        f.Output.ContinuePreparation.TrySetResult(); await f.ReadSendOrStopAsync();
        await f.SendFrame(false, 0, 0); await f.WaitWrites(1); authority.RequireSending(); f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.Throws<ObjectDisposedException>(authority.RequireCurrent, "Stopped native context remained current");
        TestAssert.That(f.Session.Error is null && f.Session.IsCompletelyStopped, "Normal authority cleanup became an error");
    }
    internal static async Task AuthorityCannotBeReplacedAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        var original = f.Output.Authority!; var forged = new PhoneCameraSession.OutputAuthority(f.Session);
        TestAssert.Throws<InvalidOperationException>(forged.RequireCurrent, "Reconstructed object granted original identity");
        TestAssert.Throws<InvalidOperationException>(() => forged.ReportFailure(new IOException("not original")), "Forged object retired an unrelated original owner");
        original.RequireCurrent(); TestAssert.That(f.Session.Error is null, "Forgery rejection damaged genuine current owner");
        await using var other = new Fixture(muted:true); await other.OfferAsync(); await other.PreparedAsync(); await other.ReadSendOrStopAsync();
        var second = other.Output.Authority!;
        TestAssert.That(!ReferenceEquals(original, second) && original.Scope != second.Scope && second.Muted, "Distinct joined native scopes were substituted");
        await f.SendFrame(false, 0, 0); await f.WaitWrites(1); original.RequireSending();
        await other.SendFrame(true, 0, 0); await other.WaitWrites(1);
        f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.Throws<ObjectDisposedException>(original.RequireSending, "Old context adopted replacement SEND");
        second.RequireSending(); TestAssert.That(other.Session.Error is null, "Old stop affected another original joined context");
    }
    internal static async Task AuthorityOriginalLossCannotReviveAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        var authority = f.Output.Authority!; f.Current = false;
        try { authority.RequireCurrent(); throw new Exception("Revoked original output context admitted"); }
        catch (InvalidOperationException) { }
        f.Current = true; await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.Throws<ObjectDisposedException>(authority.RequireCurrent, "Native Current resurrected when source flag returned");
        TestAssert.Throws<ObjectDisposedException>(authority.RequireSending, "Native SEND resurrected when source flag returned");
        TestAssert.That(f.Session.Error is not null && !f.Session.IsSending && f.Session.IsCompletelyStopped, "Original context loss failed to retire both outputs");
    }
    internal static async Task AuthorityBackendFailureRetiresJoinedAsync()
    {
        await using var f = new Fixture(); await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        var authority = f.Output.Authority!; var failure = new IOException("controlled original backend failed");
        authority.ReportFailure(failure); authority.ReportFailure(new IOException("later")); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(ReferenceEquals(f.Session.Error, failure) && f.Output.Stopped == 1 && f.Output.Disposed == 1 &&
            !f.Session.IsSending && f.Session.IsCompletelyStopped && f.Output.Written.IsEmpty, "Backend failure did not stop precisely the original joined owner once");
    }
    internal static async Task AuthorityExplicitMuteIsOriginalAsync()
    {
        await using var f = new Fixture(muted:true); f.Output.MissingMicrophone = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.ReadSendOrStopAsync();
        var authority = f.Output.Authority!; authority.RequireCurrent();
        TestAssert.That(authority.Muted && authority.Front && f.Output.MicrophoneChecks == 0, "Native context changed original explicit mute/front choice");
        await f.SendFrame(true, 0, 0); await f.WaitWrites(1); authority.RequireSending(); f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.Session.Error is null && f.Session.IsCompletelyStopped, "Explicitly muted owner required fake microphone readiness");
    }
    private static async Task NoSendAfterOutputLossAtWriterAsync(bool backendFailure)
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        await f.Parent.Writer.WaitAsync(f.Deadline.Token);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        // Observer is called AFTER the actual WaitAsync task has queued. It
        // cannot grant readiness, execute an alternative sender or release IO.
        f.Parent.Connection.WebcamWriterWaitProbe = (message, waiting) => {
            if (message["body"]?["op"]?.GetValue<string>() == "send" && !waiting.IsCompleted)
                entered.TrySetResult();
        };
        try
        {
            f.Output.ContinuePreparation.TrySetResult(); await entered.Task.WaitAsync(f.Deadline.Token);
            TestAssert.That(!f.SawSend && !f.Session.IsSending, "SEND escaped the held original crypto writer");
            if (backendFailure) f.Output.Authority!.ReportFailure(new IOException("controlled output lost while original writer held"));
            else f.Output.MissingMicrophone = true;
        }
        finally { f.Parent.Connection.WebcamWriterWaitProbe = null; f.Parent.Writer.Release(); }
        await f.ReadSendOrStopAsync(); await f.Run.WaitAsync(f.Deadline.Token);
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new { issue = 552, backendFailure, receivedEncryptedSend = f.SawSend,
            sourceContextStillCurrent = f.Current, framesWritten = f.Output.Written.Count, isSending = f.Session.IsSending,
            stopped = f.Session.IsCompletelyStopped, errorType = f.Session.Error?.GetType().Name, observedActualSender = entered.Task.IsCompletedSuccessfully }));
        TestAssert.That(!f.SawSend,
            "Actual encrypted SEND published after output loss while the original writer was held");
        TestAssert.That(f.Output.Written.IsEmpty && !f.Session.IsSending && f.Session.Error is not null && f.Session.IsCompletelyStopped,
            "Controlled output loss did not preserve joined cleanup/no-media invariants");
        f.Parent.NoPersistentControls();
    }
    internal static Task BackendFailureBlocksWaitingSendAsync() => NoSendAfterOutputLossAtWriterAsync(true);
    internal static Task ReadinessLossBlocksWaitingSendAsync() => NoSendAfterOutputLossAtWriterAsync(false);
    internal static async Task PublicationRejectsSubstituteAuthorityAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        using var other = new PhoneCameraParentTests.Fixture();
        using var unrelated = other.Connection.BindWebcamControl(() => { }, () => { });
        var original = f.Output.Authority!;
        TestAssert.Throws<InvalidOperationException>(() => original.RequirePublication(unrelated), "Original output adopted another binding");
        var forged = new PhoneCameraSession.OutputAuthority(f.Session);
        TestAssert.Throws<InvalidOperationException>(() => forged.RequirePublication(unrelated), "Forged output context granted publication");
        original.RequireCurrent(); unrelated.RequireCurrent();
        TestAssert.That(f.Session.Error is null, "Substitution refusal stopped genuine prepared session");
        f.Output.ContinuePreparation.TrySetResult(); await f.ReadSendOrStopAsync();
        await f.SendFrame(false, 0, 0); await f.WaitWrites(1); original.RequireSending();
        f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.That(f.Session.Error is null && f.Session.IsCompletelyStopped, "Genuine typed SEND failed after rejected substitutions");
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task LoaderRequiresOriginalCurrentAsync()
    {
        if (!OperatingSystem.IsWindows()) return;
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var original = f.Output.Authority!;
        TestAssert.That(PhoneCameraAudioParentModule.LoadCurrent(original) is null, "Missing embedded DLL acquired an external loader fallback");
        var forged = new PhoneCameraSession.OutputAuthority(f.Session);
        TestAssert.Throws<InvalidOperationException>(() => PhoneCameraAudioParentModule.LoadCurrent(forged), "Forged Current reached loader resources");
        original.RequireCurrent();
        f.Session.Stop(); await f.Run.WaitAsync(f.Deadline.Token);
        TestAssert.Throws<ObjectDisposedException>(() => PhoneCameraAudioParentModule.LoadCurrent(original), "Retired original reached loader resources");
        f.Parent.NoPersistentControls();
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeOriginalCallbacksAndRecordsAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var original = f.Output.Authority!; var plan = new PhoneCameraAudioParentRuntime.DiagnosticPlan();
        var runtime = PhoneCameraAudioParentRuntime.CreateDiagnostic(original, plan);
        PhoneCameraAudioParentRuntime.VideoClockLease? videoClock = null;
        PhoneCameraVideoParentRuntime? videoRuntime = null;
        PhoneCameraNativeOutputs? nativeOutputs = null;
        var videoPlan = new PhoneCameraVideoParentRuntime.DiagnosticPlan { ReadyStatus = unchecked((int)0xc00d36b6) };
        try
        {
            await runtime.PrepareAsync(f.Deadline.Token); runtime.RequireReady();
            TestAssert.Throws<InvalidOperationException>(() => runtime.HoldOriginalVideoClock(new PhoneCameraSession.OutputAuthority(f.Session)),
                "Reconstructed authority borrowed the original native clock");
            videoClock = runtime.HoldOriginalVideoClock(original);
            TestAssert.Throws<InvalidOperationException>(() => runtime.HoldOriginalVideoClock(original), "Two video owners borrowed one audio clock");
            videoRuntime = PhoneCameraVideoParentRuntime.CreateDiagnostic(original, videoPlan, videoClock);
            var videoPreparing = videoRuntime.PrepareAsync(f.Deadline.Token);
            await videoPlan.ReadyPolled.Task.WaitAsync(f.Deadline.Token);
            TestAssert.That(!videoPreparing.IsCompleted && videoPlan.Sending() == unchecked((int)0x80070005) &&
                videoPlan.Registration() == 0 && videoPlan.Scope == original.Scope && videoPlan.OwnerSize == 72 && videoPlan.Flags == 0,
                "Video binding/callbacks fabricated readiness or SEND, or lost the exact ABI/scope");
            Volatile.Write(ref videoPlan.ReadyStatus, 0); await videoPreparing;
            videoRuntime.RequireReady();
            nativeOutputs = PhoneCameraNativeOutputs.CreateDiagnostic(original, runtime, videoRuntime);
            nativeOutputs.RequireVideoReady(); nativeOutputs.RequireMicrophoneReady();
            TestAssert.That(plan.Current() == 0 && plan.Sending() == unchecked((int)0x80070005) && f.Session.Error is null && plan.Scope == original.Scope && plan.OwnerBytes == 40 &&
                plan.Digest!.SequenceEqual(Enumerable.Range(1, 32).Select(n => (byte)n)), "Original ABI/scope/digest or Current-before-SEND lost");
            TestAssert.Throws<InvalidOperationException>(() => runtime.ObserveVideo(0), "Prepared runtime invented actual SEND");
            TestAssert.Throws<InvalidOperationException>(() => videoClock.ObserveVideo(0), "Clock hold granted SEND during preparation");
            f.Output.ContinuePreparation.TrySetResult(); await f.ReadSendOrStopAsync(); await f.SendFrame(false, 0, 0); await f.WaitWrites(1);
            TestAssert.That(plan.Sending() == 0 && runtime.ObserveVideo(123) == 223, "Runtime did not use actual original SEND/video PTS");
            var pcm = Enumerable.Repeat((byte)42, PhoneCameraMediaChannel.AudioBytes).ToArray();
            runtime.Write(new PhoneCameraMediaFrame(false, 0, 123, pcm));
            TestAssert.That(plan.RecordReference!.All(b => b == 0) && plan.RecordSnapshot!.Length == 1938 && plan.RecordSnapshot[0] == 1 &&
                plan.RecordSnapshot[1] == 2 && plan.RecordSnapshot.AsSpan(18).ToArray().SequenceEqual(pcm) && pcm.All(b => b == 42), "Private native PCM copy not exact/erased or caller bytes changed");
            TestAssert.That(runtime.ExportAnchor().SequenceEqual(Enumerable.Range(1, 33).Select(n => (byte)n)), "Native anchor export was rewritten");
            TestAssert.That(videoClock.ObserveVideo(456) == 556 && videoClock.ExportAnchor().SequenceEqual(runtime.ExportAnchor()),
                "Video lease replaced the original native mapper or anchor");
            TestAssert.That(videoPlan.Mapped(456) == 556 && videoPlan.Anchor().SequenceEqual(runtime.ExportAnchor()),
                "Native video callbacks replaced the held original audio clock/anchor");
            var i420 = Enumerable.Repeat((byte)55, PhoneCameraMediaChannel.VideoBytes).ToArray();
            nativeOutputs.Write(new PhoneCameraMediaFrame(true, 0, 456, i420));
            TestAssert.That(videoPlan.RecordReference!.All(b => b == 0) && videoPlan.RecordSnapshot![1] == 1 &&
                videoPlan.RecordSnapshot.AsSpan(18).ToArray().SequenceEqual(i420) && i420.All(b => b == 55),
                "Original native I420 copy was rewritten/not erased or modified caller media");
            await videoRuntime.CloseAsync();
            TestAssert.That(videoPlan.Closes == 1 && videoPlan.SourceReleases == 1 && videoPlan.Registration() < 0 &&
                !videoRuntime.DiagnosticRootRetained && plan.Releases == 0, "Video released pins before confirmed cleanup or unloaded shared audio module");
            videoClock.Dispose(); videoClock.Dispose();
            TestAssert.Throws<ObjectDisposedException>(() => videoClock.ExportAnchor(), "Disposed video clock remained usable");
            TestAssert.Throws<InvalidOperationException>(() => runtime.HoldOriginalVideoClock(original), "Disposed video hold allowed a replacement owner/epoch");
        }
        finally
        {
            if (nativeOutputs is not null) nativeOutputs.Dispose();
            else { if (videoRuntime is not null) await videoRuntime.CloseAsync(); videoClock?.Dispose(); await runtime.CloseAsync(); }
        }
        TestAssert.That(!runtime.DiagnosticRootRetained && plan.Closes == 1 && plan.Releases == 1, "Confirmed Close did not release exact root/module once");
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeForgeryAndOriginalFailureAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var plan = new PhoneCameraAudioParentRuntime.DiagnosticPlan();
        var forged = new PhoneCameraSession.OutputAuthority(f.Session);
        TestAssert.That(forged.NativeAuthorityStatus(true) != unchecked((int)0x80070005) && forged.NativeAuthorityStatus(false) < 0,
            "Forged native callback was treated as legitimate preparation");
        TestAssert.Throws<InvalidOperationException>(() => PhoneCameraAudioParentRuntime.CreateDiagnostic(forged, plan), "Forged authority registered native callbacks");
        TestAssert.That(plan.Creates == 0, "Forgery reached C-API registration");
        var runtime = PhoneCameraAudioParentRuntime.CreateDiagnostic(f.Output.Authority!, plan);
        try
        {
            await runtime.PrepareAsync(f.Deadline.Token);
            plan.Failure(unchecked((int)0x80004005)); await f.Run.WaitAsync(f.Deadline.Token);
            var first = f.Session.Error; plan.Failure(unchecked((int)0x80070005));
            TestAssert.That(first is not null && ReferenceEquals(first, f.Session.Error) && plan.Current() < 0 && plan.Sending() < 0 &&
                f.Output.Stopped == 1 && f.Session.IsCompletelyStopped && plan.Stops == 1, "Native failure did not retire exact owner/runtime once");
        }
        finally { await runtime.CloseAsync(); }
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeCancelledPrepareDrainsAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var plan = new PhoneCameraAudioParentRuntime.DiagnosticPlan { HoldPrepare = true };
        var runtime = PhoneCameraAudioParentRuntime.CreateDiagnostic(f.Output.Authority!, plan);
        using var cancellation = new CancellationTokenSource(); var preparing = runtime.PrepareAsync(cancellation.Token);
        await plan.PrepareEntered.Task.WaitAsync(f.Deadline.Token); cancellation.Cancel();
        try { await preparing; throw new Exception("Cancelled controlled prepare succeeded"); } catch (System.Runtime.InteropServices.COMException) { }
        await runtime.CloseAsync();
        TestAssert.That(plan.Active == 0 && plan.Closes == 1 && plan.Releases == 1 && !runtime.DiagnosticRootRetained, "Cancelled native prepare was detached or module released before drain");
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeConcurrentWriteCloseAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var plan = new PhoneCameraAudioParentRuntime.DiagnosticPlan { HoldWrite = true };
        var runtime = PhoneCameraAudioParentRuntime.CreateDiagnostic(f.Output.Authority!, plan); await runtime.PrepareAsync(f.Deadline.Token);
        using var videoClock = runtime.HoldOriginalVideoClock(f.Output.Authority!);
        var videoPlan = new PhoneCameraVideoParentRuntime.DiagnosticPlan();
        var videoRuntime = PhoneCameraVideoParentRuntime.CreateDiagnostic(f.Output.Authority!, videoPlan, videoClock);
        await videoRuntime.PrepareAsync(f.Deadline.Token);
        var nativeOutputs = PhoneCameraNativeOutputs.CreateDiagnostic(f.Output.Authority!, runtime, videoRuntime);
        f.Output.ContinuePreparation.TrySetResult(); await f.ReadSendOrStopAsync(); await f.SendFrame(false, 0, 0); await f.WaitWrites(1);
        var write = Task.Run(() => runtime.Write(new PhoneCameraMediaFrame(false, 0, 0, new byte[PhoneCameraMediaChannel.AudioBytes])));
        await plan.WriteEntered.Task.WaitAsync(f.Deadline.Token); var close = runtime.CloseAsync();
        TestAssert.That(ReferenceEquals(close, runtime.CloseAsync()), "Concurrent Close launched another cleanup");
        try { await write; throw new Exception("Stopped pending write succeeded"); } catch (System.Runtime.InteropServices.COMException) { }
        await plan.StopEntered.Task.WaitAsync(f.Deadline.Token);
        TestAssert.That(!close.IsCompleted && plan.Closes == 0 && plan.Releases == 0,
            "Audio module closed before original video clock lifetime drained");
        TestAssert.Throws<ObjectDisposedException>(() => videoClock.ObserveVideo(1), "Closing audio runtime granted a fresh video mapping");
        await Task.Run(nativeOutputs.Dispose); // Actual composition: Source confirmation BEFORE audio Close/unload.
        TestAssert.That(videoPlan.Closes == 1 && videoPlan.SourceReleases == 1 && !videoRuntime.DiagnosticRootRetained,
            "Video failed to confirm/retire original Source before shared module release");
        await close;
        TestAssert.That(plan.Active == 0 && plan.Closes == 1 && plan.Releases == 1 && plan.RecordReference!.All(b => b == 0) &&
            !runtime.DiagnosticRootRetained, "Close preceded managed call/PCM drain");
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeUnconfirmedCloseRetainsRootAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        var plan = new PhoneCameraAudioParentRuntime.DiagnosticPlan { FailClose = true };
        var runtime = PhoneCameraAudioParentRuntime.CreateDiagnostic(f.Output.Authority!, plan); await runtime.PrepareAsync(f.Deadline.Token);
        var close = runtime.CloseAsync();
        try { await close; throw new Exception("Unconfirmed native Close reported success"); } catch (System.Runtime.InteropServices.COMException) { }
        GC.Collect(); GC.WaitForPendingFinalizers();
        TestAssert.That(runtime.DiagnosticRootRetained && plan.Releases == 0 && plan.Closes == 1 && ReferenceEquals(close, runtime.CloseAsync()),
            "Unconfirmed Close unloaded callbacks/module, lost root or retried native cleanup");
        try { runtime.RequireReady(); throw new Exception("Terminal native owner revived"); } catch (ObjectDisposedException) { }
        runtime.ReleaseStoppedDiagnosticFixture(plan); // Own fake table only; NO real native owner/module exists.
        var heldAudioPlan = new PhoneCameraAudioParentRuntime.DiagnosticPlan();
        var heldAudio = PhoneCameraAudioParentRuntime.CreateDiagnostic(f.Output.Authority!, heldAudioPlan);
        await heldAudio.PrepareAsync(f.Deadline.Token);
        var heldClock = heldAudio.HoldOriginalVideoClock(f.Output.Authority!);
        var videoPlan = new PhoneCameraVideoParentRuntime.DiagnosticPlan { FailClose = true };
        var video = PhoneCameraVideoParentRuntime.CreateDiagnostic(f.Output.Authority!, videoPlan, heldClock);
        await video.PrepareAsync(f.Deadline.Token);
        var videoClose = video.CloseAsync();
        try { await videoClose; throw new Exception("Unknown Source cleanup was accepted"); } catch (System.Runtime.InteropServices.COMException) { }
        var audioClose = heldAudio.CloseAsync();
        await heldAudioPlan.StopEntered.Task.WaitAsync(f.Deadline.Token);
        try
        {
            TestAssert.That(video.DiagnosticRootRetained && videoPlan.SourceReleases == 0 && videoPlan.Registration() == 0 &&
                ReferenceEquals(videoClose, video.CloseAsync()) && videoPlan.Closes == 1 && !audioClose.IsCompleted && heldAudioPlan.Releases == 0,
                "Unknown video cleanup retried, revoked registration accounting, released Source pins or unloaded shared audio module");
        }
        finally
        {
            video.ReleaseStoppedDiagnosticFixture(videoPlan); // Only the fake native table; not a productive retry route.
            await audioClose;
        }
        TestAssert.That(videoPlan.SourceReleases == 1 && heldAudioPlan.Releases == 1 && !video.DiagnosticRootRetained,
            "Controlled fake cleanup failed to drain its own retained test roots");
    }
    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    internal static async Task RuntimeProductionNoFallbackOrMutedWorkerAsync()
    {
        await using var f = new Fixture(); f.Output.HoldPreparation = true;
        await f.OfferAsync(); await f.PreparedAsync(); await f.Output.Preparing.Task.WaitAsync(f.Deadline.Token);
        TestAssert.That(PhoneCameraAudioParentRuntime.CreateCurrent(f.Output.Authority!) is null, "Production factory replaced missing immutable worker with external runtime");
        TestAssert.Throws<InvalidOperationException>(() => PhoneCameraAudioParentRuntime.CreateCurrent(new PhoneCameraSession.OutputAuthority(f.Session)), "Production factory accepted reconstructed authority");
        f.Output.Authority!.RequireCurrent();
        using (var nativeOutputs = new PhoneCameraNativeOutputs())
        {
            try
            {
                await nativeOutputs.PrepareAsync(f.Output.Authority!, f.Deadline.Token);
                throw new Exception("Missing Source acquired native outputs");
            }
            catch (InvalidOperationException error) when (error.Message == "webcam_installed_source_required") { }
        }
        f.Output.Authority!.RequireCurrent(); // A missing payload is not a new authority or audio fallback.
        await using var muted = new Fixture(muted: true); muted.Output.HoldPreparation = true;
        await muted.OfferAsync(); await muted.PreparedAsync(); await muted.Output.Preparing.Task.WaitAsync(muted.Deadline.Token);
        TestAssert.Throws<InvalidOperationException>(() => PhoneCameraAudioParentRuntime.CreateCurrent(muted.Output.Authority!), "Explicitly muted original could launch audio worker");
        muted.Output.Authority!.RequireCurrent();
        var mutedPlan = new PhoneCameraVideoParentRuntime.DiagnosticPlan();
        var mutedVideo = PhoneCameraVideoParentRuntime.CreateDiagnostic(muted.Output.Authority!, mutedPlan, null);
        await mutedVideo.PrepareAsync(muted.Deadline.Token);
        TestAssert.That(mutedPlan.Flags == 1 && mutedPlan.Sending() == unchecked((int)0x80070005), "Muted video opened audio callbacks or granted SEND");
        TestAssert.Throws<InvalidOperationException>(() => mutedPlan.Anchor(), "Muted video borrowed an external audio anchor");
        await mutedVideo.CloseAsync();
        using var stoppedOutputs = new PhoneCameraNativeOutputs(); stoppedOutputs.Stop();
        TestAssert.Throws<InvalidOperationException>(() => stoppedOutputs.PrepareAsync(muted.Output.Authority!, muted.Deadline.Token),
            "Stopped native output composition started replacement outputs");
    }
}
