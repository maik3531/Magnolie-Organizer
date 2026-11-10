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
        internal readonly SemaphoreSlim Writes = new(0);
        public async Task PrepareAsync(bool muted, CancellationToken cancellation)
        {
            Interlocked.Increment(ref Prepared); Preparing.TrySetResult();
            if (HoldPreparation) await ContinuePreparation.Task.WaitAsync(cancellation);
        }
        public void RequireVideoReady() { if (Prepared != 1 || Stopped != 0) throw new IOException("controlled video not ready"); }
        public void RequireMicrophoneReady()
        { Interlocked.Increment(ref MicrophoneChecks); if (MissingMicrophone) throw new IOException("controlled required microphone missing"); }
        public void Write(PhoneCameraMediaFrame frame)
        {
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
}
