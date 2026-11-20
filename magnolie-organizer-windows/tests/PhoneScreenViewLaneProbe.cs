#if MAGNOLIE_PHONE_SCREEN_WIRE_PROBE
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace MagnolieOrganizer.Windows;

// Standalone bounded loopback probe. No installed application, device or UI.
internal static class PhoneScreenViewLaneProbe
{
    private static readonly byte[] Session = Convert.FromHexString("000102030405060708090a0b0c0d0e0f");
    private static readonly byte[] Secret = Convert.FromHexString("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
    private static void Check(bool condition) { if (!condition) throw new Exception("Screen view wire check failed"); }

    private static void WithPair(Action<Socket, Socket> test)
    {
        using var listener = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        listener.Bind(new IPEndPoint(IPAddress.Loopback, 0));
        listener.Listen(1);
        using var peer = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        peer.Connect(listener.LocalEndPoint!);
        peer.ReceiveTimeout = peer.SendTimeout = 2000;
        using var original = listener.Accept();
        test(original, peer);
    }

    private static void Prove(PhoneScreenViewLane lane, NetworkStream phone, bool wrong = false)
    {
        var proof = Task.Run(lane.Prove);
        AnswerProof(phone, wrong);
        proof.GetAwaiter().GetResult();
    }

    private static void AnswerProof(NetworkStream phone, bool wrong = false)
    {
        byte[] context = new byte["magnolie-phone-screen-proof/1\0magnolie-phone-screen-view/1\0phone_to_desktop\0"u8.Length + 36];
        "magnolie-phone-screen-proof/1\0magnolie-phone-screen-view/1\0phone_to_desktop\0"u8.CopyTo(context);
        Session.CopyTo(context.AsSpan(context.Length - 36));
        Convert.FromHexString(wrong ? "00120010" : "00110010").CopyTo(context.AsSpan(context.Length - 20));
        phone.ReadExactly(context.AsSpan(context.Length - 16));
        phone.Write(HMACSHA256.HashData(Secret, context));
    }

    private static void Throws<T>(Action action) where T : Exception
    {
        try { action(); } catch (T) { return; }
        throw new Exception($"Expected {typeof(T).Name}");
    }

    public static void Main()
    {
        WithPair((original, peer) =>
        {
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { }, () => { });
            using var phone = new NetworkStream(peer);
            Prove(lane, phone);
            // Shared vectors: heartbeat, opaque test payload, replay.
            phone.Write(Convert.FromHexString("000000100000000000000000645ed91909ccdd8fc7eec4b153dbaa61"
                + "0000001600000000000000012cf1d07d1ce098974a3ae945893a44699c661252d503"
                + "000000100000000000000000645ed91909ccdd8fc7eec4b153dbaa61"));
            Check(lane.Receive().Length == 0);
            Check(lane.Receive().AsSpan().SequenceEqual("second"u8));
            Throws<InvalidDataException>(() => lane.Receive());
        });
        WithPair((original, peer) =>
        {
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { }, () => { });
            using var phone = new NetworkStream(peer);
            Throws<InvalidDataException>(() => Prove(lane, phone, true));
            Check(phone.ReadByte() == -1);
        });
        WithPair((original, peer) =>
        {
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { }, () => throw new UnauthorizedAccessException());
            using var phone = new NetworkStream(peer);
            Prove(lane, phone);
            Throws<UnauthorizedAccessException>(() => lane.Receive());
            Check(phone.ReadByte() == -1);
        });
        WithPair((original, peer) =>
        {
            int checks = 0;
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { },
                () => { if (++checks == 5) throw new UnauthorizedAccessException(); });
            using var phone = new NetworkStream(peer);
            Prove(lane, phone);
            phone.Write(Convert.FromHexString("000000150000000000000000ff4cf254a965f55e05d2cde81cd0c87f07d170c8a0"));
            Throws<UnauthorizedAccessException>(() => lane.Receive());
            Check(phone.ReadByte() == -1);
        });
        WithPair((original, peer) =>
        {
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { }, () => { });
            using var phone = new NetworkStream(peer);
            Prove(lane, phone);
            phone.Write(Convert.FromHexString("001000110000000000000000"));
            Throws<InvalidDataException>(() => lane.Receive()); // No payload needed to reject the bad length.
            Check(phone.ReadByte() == -1);
        });
        WithPair((original, peer) =>
        {
            using var entered = new ManualResetEventSlim(false);
            using var lane = new PhoneScreenViewLane(original, Session, Secret, 17, 16, () => { }, entered.Set);
            using var phone = new NetworkStream(peer);
            Prove(lane, phone);
            var reader = Task.Run(() =>
            {
                try { lane.Receive(); }
                catch (Exception error) when (error is IOException or SocketException or ObjectDisposedException) { return; }
                throw new Exception("Pending reader returned a picture after terminal Stop");
            });
            Check(entered.Wait(TimeSpan.FromSeconds(1)));
            lane.Dispose();
            Check(reader.Wait(TimeSpan.FromSeconds(1)));
            Check(phone.ReadByte() == -1);
        });
        Console.WriteLine("6/6 Windows screen wire source checks (managed .NET loopback, no native UI)");
        WithPair((original, peer) =>
        {
            using var writeEntered = new ManualResetEventSlim(false);
            using var framePresented = new ManualResetEventSlim(false);
            using var phone = new NetworkStream(peer);
            var publication = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            byte[]? picture = null;
            var ended = 0;
            var run = new PhoneScreenReceiveRun(original, Session, Secret, 17, 16, () => { },
                () => { if (!publication.Task.IsCompletedSuccessfully) throw new UnauthorizedAccessException(); },
                guard => { guard(); writeEntered.Set(); return publication.Task; },
                bytes => { if (!bytes.AsSpan().SequenceEqual("second"u8)) return false; picture = bytes; framePresented.Set(); return true; },
                () => Interlocked.Increment(ref ended));
            try
            {
                run.Start();
                AnswerProof(phone);
                Check(writeEntered.Wait(TimeSpan.FromSeconds(1)));
                phone.Write(Convert.FromHexString("000000100000000000000000645ed91909ccdd8fc7eec4b153dbaa61"
                    + "0000001600000000000000012cf1d07d1ce098974a3ae945893a44699c661252d503"));
                Check(!framePresented.Wait(TimeSpan.FromMilliseconds(100)) && !run.Drained.IsCompleted);
                publication.SetResult();
                Check(framePresented.Wait(TimeSpan.FromSeconds(1)));
                run.Stop();
                run.Drained.WaitAsync(TimeSpan.FromSeconds(2)).GetAwaiter().GetResult();
                Check(ended == 1 && run.Failure is null && picture is not null && picture.AsSpan().IndexOfAnyExcept((byte)0) < 0);
            }
            finally
            {
                publication.TrySetCanceled();
                run.Stop();
                run.Drained.WaitAsync(TimeSpan.FromSeconds(2)).GetAwaiter().GetResult();
            }
        });
        WithPair((original, peer) =>
        {
            using var phone = new NetworkStream(peer);
            int stopped = 0;
            var run = new PhoneScreenReceiveRun(original, Session, Secret, 17, 16, () => { }, () => { },
                _ => throw new Exception("Unexpected publication"), _ => false, () => stopped++);
            run.Stop();
            run.Stop();
            run.Drained.WaitAsync(TimeSpan.FromSeconds(1)).GetAwaiter().GetResult();
            Check(stopped == 1 && phone.ReadByte() == -1);
            Throws<InvalidOperationException>(run.Start);
        });
        Console.WriteLine("2/2 Windows receive-owner checks (managed .NET loopback, controlled output)");
    }
}
#endif
