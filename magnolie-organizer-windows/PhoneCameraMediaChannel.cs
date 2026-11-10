using System.Buffers.Binary;
using System.Diagnostics;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace MagnolieOrganizer.Windows;

internal sealed record PhoneCameraMediaFrame(bool Video, long Sequence, long PresentationTimeUs, byte[] Data);

/// <summary>
/// One original, dedicated phone-to-desktop AV socket. This is not a camera,
/// microphone, listener or permission: its caller must first bind the socket and
/// fresh secret/session to the actual authenticated parent and capture consent.
/// The guard must be live, nonblocking and safe under this private reader lock.
/// No retry, parent replacement, stored authority or native device enumeration.
/// </summary>
internal sealed class PhoneCameraMediaChannel : IDisposable
{
    internal const int VideoBytes = 640 * 480 * 3 / 2;
    internal const int AudioBytes = 960 * 2;
    internal const int HeaderBytes = 12;
    internal const int PacketBytes = 18;
    internal const int MaxCipherBytes = PacketBytes + VideoBytes + 16;
    private static readonly byte[] Protocol = Encoding.ASCII.GetBytes("magnolie-phone-webcam/1\0phone_to_desktop\0");
    private readonly object gate = new();
    private readonly Socket socket;
    private readonly Action current;
    private readonly AesGcm cipher;
    private readonly byte[] prefix;
    private readonly byte[] aad;
    private long sequence;
    private int retired;

    internal bool IsRetired => Volatile.Read(ref retired) != 0;

    internal PhoneCameraMediaChannel(Socket originalSocket, string session, byte[] secret, Action current)
    {
        ArgumentNullException.ThrowIfNull(originalSocket);
        ArgumentNullException.ThrowIfNull(current);
        if (session is null || !Regex.IsMatch(session, "\\A[0-9a-f]{32}\\z") || secret is null || secret.Length != 32 ||
            originalSocket.SocketType != SocketType.Stream ||
            originalSocket.AddressFamily is not (AddressFamily.InterNetwork or AddressFamily.InterNetworkV6))
            throw new ArgumentException("webcam_media_context_invalid");
        socket = originalSocket;
        this.current = current;
        var sessionBytes = Convert.FromHexString(session);
        var material = HKDF.DeriveKey(HashAlgorithmName.SHA256, secret, 36, sessionBytes, Protocol);
        try
        {
            cipher = new AesGcm(material.AsSpan(0, 32), 16);
            prefix = material.AsSpan(32, 4).ToArray();
            aad = new byte[Protocol.Length + sessionBytes.Length + HeaderBytes];
            Protocol.CopyTo(aad, 0);
            sessionBytes.CopyTo(aad, Protocol.Length);
        }
        finally { CryptographicOperations.ZeroMemory(material); }
        try
        {
            current();
            // Only this dedicated socket is changed, never the control parent.
            socket.ReceiveTimeout = 100;
        }
        catch { Dispose(); throw; }
    }

    private void RequireCurrent(long started)
    {
        if (IsRetired) throw new IOException("webcam_media_channel_retired");
        current();
        if (IsRetired) throw new IOException("webcam_media_channel_retired");
        if (Stopwatch.GetElapsedTime(started) >= TimeSpan.FromSeconds(2))
            throw new IOException("webcam_media_channel_timeout");
    }

    private void ReadExactly(Span<byte> target, long started)
    {
        var at = 0;
        while (at < target.Length)
        {
            RequireCurrent(started);
            int count;
            try { count = socket.Receive(target[at..], SocketFlags.None); }
            catch (SocketException error) when (error.SocketErrorCode is SocketError.TimedOut or SocketError.WouldBlock)
            { continue; }
            if (count == 0) throw new IOException("webcam_media_channel_eof");
            at += count;
        }
        RequireCurrent(started);
    }

    internal PhoneCameraMediaFrame Receive()
    {
        lock (gate)
        {
            byte[]? plain = null;
            byte[]? data = null;
            try
            {
                if (sequence == long.MaxValue) throw new IOException("webcam_media_sequence_exhausted");
                var started = Stopwatch.GetTimestamp();
                RequireCurrent(started);
                Span<byte> header = stackalloc byte[HeaderBytes];
                ReadExactly(header, started);
                var length = BinaryPrimitives.ReadUInt32BigEndian(header);
                var wireSequence = BinaryPrimitives.ReadUInt64BigEndian(header[4..]);
                // Validate length/global sequence before any ciphertext allocation
                // or payload read; a hostile length cannot create a huge buffer.
                if (wireSequence != (ulong)sequence || length < PacketBytes + 16 || length > MaxCipherBytes)
                    throw new IOException("webcam_media_envelope_invalid");
                var encrypted = new byte[(int)length];
                ReadExactly(encrypted, started);
                plain = new byte[encrypted.Length - 16];
                Span<byte> nonce = stackalloc byte[12];
                prefix.CopyTo(nonce);
                BinaryPrimitives.WriteInt64BigEndian(nonce[4..], sequence);
                header.CopyTo(aad.AsSpan(aad.Length - HeaderBytes));
                cipher.Decrypt(nonce, encrypted.AsSpan(0, plain.Length), encrypted.AsSpan(plain.Length), plain, aad);
                var trackSequence = BinaryPrimitives.ReadUInt64BigEndian(plain.AsSpan(2));
                var pts = BinaryPrimitives.ReadUInt64BigEndian(plain.AsSpan(10));
                if (plain[0] != 1 || plain[1] is not (1 or 2) || trackSequence > long.MaxValue || pts > 9_007_199_254_740_991 ||
                    plain.Length != PacketBytes + (plain[1] == 1 ? VideoBytes : AudioBytes))
                    throw new IOException("webcam_packet_invalid");
                data = plain.AsSpan(PacketBytes).ToArray();
                RequireCurrent(started);
                var result = new PhoneCameraMediaFrame(plain[1] == 1, (long)trackSequence, (long)pts, data);
                sequence++;
                data = null; // Ownership passes only after the final original guard.
                return result;
            }
            catch { Dispose(); throw; }
            finally
            {
                if (plain is not null) CryptographicOperations.ZeroMemory(plain);
                if (data is not null) CryptographicOperations.ZeroMemory(data);
            }
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref retired, 1) != 0) return;
        // Interrupt only the original socket BEFORE waiting for the reader lock.
        // This lets external stop unblock a pending Receive without deadlock.
        try { socket.Shutdown(SocketShutdown.Both); }
        catch (SocketException) { }
        catch (ObjectDisposedException) { }
        socket.Dispose();
        lock (gate)
        {
            cipher.Dispose();
            CryptographicOperations.ZeroMemory(prefix);
        }
    }
}
