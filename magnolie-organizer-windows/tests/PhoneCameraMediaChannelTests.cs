using System.Buffers.Binary;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PhoneCameraMediaChannelTests
{
    private const string Session = "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1";
    private static byte[] Secret => Enumerable.Repeat((byte)0xb2, 32).ToArray();
    private sealed class Pair : IDisposable
    {
        internal Socket Sender { get; }
        internal Socket Receiver { get; }
        internal Pair()
        {
            using var listener = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            listener.Bind(new IPEndPoint(IPAddress.Loopback, 0)); listener.Listen(1);
            Sender = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
            Sender.Connect(listener.LocalEndPoint!); Sender.SendTimeout = 2000;
            Receiver = listener.Accept();
        }
        internal void Send(byte[] data, int chunk = 32768)
        {
            for (var at = 0; at < data.Length;)
                at += Sender.Send(data.AsSpan(at, Math.Min(chunk, data.Length - at)), SocketFlags.None);
        }
        public void Dispose() { Sender.Dispose(); Receiver.Dispose(); }
    }

    // Independent sender, checked against the Python packet SHA-256 goldens.
    // Only this controlled test counterpart encrypts: production Windows is RX.
    private static byte[] Packet(ulong global, byte track = 2, ulong trackSequence = 0,
        ulong pts = 0, int size = PhoneCameraMediaChannel.AudioBytes, byte fill = 42, byte version = 1)
    {
        var protocol = Encoding.ASCII.GetBytes("magnolie-phone-webcam/1\0phone_to_desktop\0");
        var session = Convert.FromHexString(Session);
        var material = HKDF.DeriveKey(HashAlgorithmName.SHA256, Secret, 36, session, protocol);
        using var cipher = new AesGcm(material.AsSpan(0, 32), 16);
        var plain = new byte[18 + size]; plain[0] = version; plain[1] = track;
        BinaryPrimitives.WriteUInt64BigEndian(plain.AsSpan(2), trackSequence);
        BinaryPrimitives.WriteUInt64BigEndian(plain.AsSpan(10), pts);
        plain.AsSpan(18).Fill(fill);
        var packet = new byte[12 + plain.Length + 16];
        BinaryPrimitives.WriteInt32BigEndian(packet, plain.Length + 16);
        BinaryPrimitives.WriteUInt64BigEndian(packet.AsSpan(4), global);
        var aad = protocol.Concat(session).Concat(packet.AsSpan(0, 12).ToArray()).ToArray();
        var nonce = new byte[12]; material.AsSpan(32).CopyTo(nonce);
        BinaryPrimitives.WriteUInt64BigEndian(nonce.AsSpan(4), global);
        cipher.Encrypt(nonce, plain, packet.AsSpan(12, plain.Length), packet.AsSpan(12 + plain.Length), aad);
        CryptographicOperations.ZeroMemory(material);
        return packet;
    }

    internal static async Task GoldensAsync()
    {
        var path = Path.Combine(TestSource.Root("contracts/phone-webcam-media-v1-vectors.json"), "contracts", "phone-webcam-media-v1-vectors.json");
        using var fixture = JsonDocument.Parse(File.ReadAllText(path));
        TestAssert.That(fixture.RootElement.GetProperty("session").GetString() == Session &&
            fixture.RootElement.GetProperty("secret").GetString() == Convert.ToHexString(Secret).ToLowerInvariant(), "Golden context differs");
        using var pair = new Pair();
        using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret, () => { });
        foreach (var row in fixture.RootElement.GetProperty("packets").EnumerateArray())
        {
            var track = row.GetProperty("track").GetByte();
            var packet = Packet(row.GetProperty("global_sequence").GetUInt64(), track,
                row.GetProperty("track_sequence").GetUInt64(), row.GetProperty("pts_us").GetUInt64(),
                row.GetProperty("bytes").GetInt32(), row.GetProperty("fill").GetByte());
            TestAssert.That(Convert.ToHexString(SHA256.HashData(packet)).ToLowerInvariant() == row.GetProperty("packet_sha256").GetString(), "Python golden differs");
            var sender = Task.Run(() => pair.Send(packet, chunk: 307));
            var frame = channel.Receive(); await sender.WaitAsync(TimeSpan.FromSeconds(4));
            TestAssert.That(frame.Video == (track == 1) && frame.Sequence == row.GetProperty("track_sequence").GetInt64() &&
                frame.PresentationTimeUs == row.GetProperty("pts_us").GetInt64() && frame.Data.Length == row.GetProperty("bytes").GetInt32() &&
                frame.Data.All(value => value == row.GetProperty("fill").GetByte()), "Decoded AV/PTS differs");
        }
        TestAssert.That(!channel.IsRetired, "Healthy original channel unexpectedly retired");
    }

    internal static Task RejectionsAsync()
    {
        foreach (var mode in new[] { "huge", "small", "sequence", "ciphertext", "replay", "eof" })
        {
            using var pair = new Pair();
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret, () => { });
            var packet = Packet(0);
            if (mode == "huge") { BinaryPrimitives.WriteUInt32BigEndian(packet, uint.MaxValue); packet = packet[..12]; }
            if (mode == "small") { BinaryPrimitives.WriteUInt32BigEndian(packet, 33); packet = packet[..12]; }
            if (mode == "sequence") { packet[11] = 1; packet = packet[..12]; }
            if (mode == "ciphertext") packet[^1] ^= 1;
            if (mode == "replay") { pair.Send(packet); channel.Receive(); }
            if (mode == "eof") { packet = packet[..15]; }
            pair.Send(packet);
            if (mode == "eof") pair.Sender.Shutdown(SocketShutdown.Send);
            TestAssert.Throws<Exception>(() => channel.Receive(), "Invalid " + mode + " was accepted");
            TestAssert.That(channel.IsRetired, "Failure must retire exact socket: " + mode);
            TestAssert.Throws<IOException>(() => channel.Receive(), "Retired receiver reused");
        }
        return Task.CompletedTask;
    }

    internal static Task PacketGrammarAsync()
    {
        foreach (var packet in new[] { Packet(0, version: 2), Packet(0, track: 3), Packet(0, size: 1919),
            Packet(0, track: 1), Packet(0, trackSequence: ulong.MaxValue), Packet(0, pts: 9_007_199_254_740_992) })
        {
            using var pair = new Pair();
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret, () => { });
            pair.Send(packet);
            TestAssert.Throws<IOException>(() => channel.Receive(), "Authenticated invalid grammar accepted");
            TestAssert.That(channel.IsRetired, "Grammar failure not sticky");
        }
        return Task.CompletedTask;
    }

    internal static Task ContextIsolationAsync()
    {
        foreach (var wrongSession in new[] { false, true })
        {
            using var original = new Pair();
            using var unrelatedParent = new Pair();
            var secret = Secret;
            if (!wrongSession) secret[0] ^= 1;
            using var channel = new PhoneCameraMediaChannel(original.Receiver,
                wrongSession ? new string('c', 32) : Session, secret, () => { });
            original.Send(Packet(0));
            TestAssert.Throws<CryptographicException>(() => channel.Receive(), "Foreign session/key authenticated");
            TestAssert.That(channel.IsRetired, "Foreign context rejection is not sticky");
            unrelatedParent.Send([42]);
            unrelatedParent.Receiver.ReceiveTimeout = 1000;
            var marker = new byte[1];
            TestAssert.That(unrelatedParent.Receiver.Receive(marker) == 1 && marker[0] == 42,
                "Media rejection changed an unrelated original connection");
        }
        using (var pair = new Pair())
        {
            TestAssert.Throws<ArgumentException>(() => new PhoneCameraMediaChannel(pair.Receiver, new string('A', 32), Secret, () => { }), "Uppercase session accepted");
            TestAssert.Throws<ArgumentException>(() => new PhoneCameraMediaChannel(pair.Receiver, Session, new byte[31], () => { }), "Short key accepted");
            TestAssert.That(pair.Receiver.Connected, "Invalid constructor arguments adopted the caller socket");
        }
        return Task.CompletedTask;
    }

    internal static async Task OriginalGuardAndStopAsync()
    {
        using (var pair = new Pair())
        {
            var live = 1;
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret,
                () => { if (Volatile.Read(ref live) == 0) throw new InvalidOperationException("original owner revoked"); });
            var receive = Task.Run(() => TestAssert.Throws<InvalidOperationException>(() => channel.Receive(), "Idle revoke ignored"));
            Volatile.Write(ref live, 0);
            await receive.WaitAsync(TimeSpan.FromSeconds(2));
            TestAssert.That(channel.IsRetired, "Original revoke did not retire");
            Volatile.Write(ref live, 1);
            TestAssert.Throws<IOException>(() => channel.Receive(), "Owner ABA restored old channel");
        }
        using (var pair = new Pair())
        {
            using var entered = new ManualResetEventSlim();
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret, entered.Set);
            entered.Reset();
            var receive = Task.Run(() => TestAssert.Throws<Exception>(() => channel.Receive(), "Stop did not interrupt reader"));
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(1)), "Reader did not enter");
            channel.Dispose();
            await receive.WaitAsync(TimeSpan.FromSeconds(2));
        }
        using (var pair = new Pair())
        {
            var checks = 0;
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret,
                () => { if (++checks == 7) throw new InvalidOperationException("revoked after decryption"); });
            pair.Send(Packet(0));
            TestAssert.Throws<InvalidOperationException>(() => channel.Receive(), "Final original guard bypassed");
            TestAssert.That(channel.IsRetired && checks == 7, "Failure did not reach exact final guard");
        }
    }

    internal static Task TimeoutAndSecretAsync()
    {
        using (var pair = new Pair())
        {
            var secret = Secret;
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, secret, () => { });
            CryptographicOperations.ZeroMemory(secret);
            pair.Send(Packet(0));
            TestAssert.That(channel.Receive().Data.Length == 1920, "Channel retained mutable caller secret");
        }
        using (var pair = new Pair())
        {
            using var channel = new PhoneCameraMediaChannel(pair.Receiver, Session, Secret, () => { });
            pair.Send(Packet(0)[..12]);
            var watch = Stopwatch.StartNew();
            TestAssert.Throws<IOException>(() => channel.Receive(), "Incomplete payload did not time out");
            TestAssert.That(channel.IsRetired && watch.Elapsed < TimeSpan.FromSeconds(4), "Packet deadline is not bounded");
        }
        return Task.CompletedTask;
    }

    internal static async Task<int> HostAsync()
    {
        // Test counterpart only: no control negotiation, pairing or native output.
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        using var listener = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        listener.Bind(new IPEndPoint(IPAddress.Loopback, 0)); listener.Listen(1);
        Console.WriteLine(JsonSerializer.Serialize(new { port = ((IPEndPoint)listener.LocalEndPoint!).Port }));
        using var original = await listener.AcceptAsync(deadline.Token);
        using var receiver = new PhoneCameraMediaChannel(original, Session, Secret, () => deadline.Token.ThrowIfCancellationRequested());
        for (var index = 0; index < 3; index++)
        {
            var frame = receiver.Receive();
            Console.WriteLine(JsonSerializer.Serialize(new { video = frame.Video, sequence = frame.Sequence,
                pts_us = frame.PresentationTimeUs, bytes = frame.Data.Length,
                sha256 = Convert.ToHexString(SHA256.HashData(frame.Data)).ToLowerInvariant() }));
        }
        return 0;
    }
}
