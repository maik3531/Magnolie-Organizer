using System;
using System.Buffers.Binary;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Threading;

namespace MagnolieOrganizer.Windows;

/// <summary>One already admitted phone-to-Windows viewing socket for #245.
/// Proof does not grant SEND. The caller retains the original control, user
/// choice, window and session-lock guards. No decoder, listener or settings.
/// </summary>
internal sealed class PhoneScreenViewLane : IDisposable
{
    private static readonly byte[] Domain = "magnolie-phone-screen-view/1\0phone_to_desktop\0"u8.ToArray();
    private static readonly byte[] ProofDomain = "magnolie-phone-screen-proof/1\0"u8.ToArray();
    private const int HeaderSize = 12, TagSize = 16, MaxJpeg = 1_048_576;
    private readonly Socket socket;
    private readonly Action requireOriginal, requireSend;
    private readonly object gate = new();
    private readonly byte[] aad;
    private AesGcm? cipher;
    private byte[]? proofKey;
    private readonly byte[] prefix;
    private long ordinal;
    private int retired;
    private bool proofVerified;

    internal PhoneScreenViewLane(Socket socket, ReadOnlySpan<byte> session, ReadOnlySpan<byte> secret,
        int width, int height, Action requireOriginal, Action requireSend)
    {
        this.socket = socket;
        this.requireOriginal = requireOriginal;
        this.requireSend = requireSend;
        prefix = new byte[4];
        aad = new byte[Domain.Length + 20 + HeaderSize];
        try
        {
            if (session.Length != 16 || secret.Length != 32 || width is < 2 or > 1920 || height is < 2 or > 1920 ||
                width * height > 1920 * 1080 || !socket.Connected || socket.SocketType != SocketType.Stream ||
                socket.AddressFamily is not (AddressFamily.InterNetwork or AddressFamily.InterNetworkV6))
                throw new ArgumentException("screen_lane_original_context_required");
            Domain.CopyTo(aad, 0);
            session.CopyTo(aad.AsSpan(Domain.Length));
            BinaryPrimitives.WriteUInt16BigEndian(aad.AsSpan(Domain.Length + 16), (ushort)width);
            BinaryPrimitives.WriteUInt16BigEndian(aad.AsSpan(Domain.Length + 18), (ushort)height);
            Span<byte> material = stackalloc byte[36];
            try
            {
                HKDF.DeriveKey(HashAlgorithmName.SHA256, secret, material, session, aad.AsSpan(0, aad.Length - HeaderSize));
                cipher = new AesGcm(material[..32], TagSize);
                material[32..].CopyTo(prefix);
                proofKey = secret.ToArray();
            }
            finally { CryptographicOperations.ZeroMemory(material); }
            requireOriginal();
            socket.ReceiveTimeout = socket.SendTimeout = 100;
        }
        catch { Dispose(); throw; }
    }

    internal void Prove()
    {
        lock (gate)
        {
            var key = proofKey ?? throw new InvalidOperationException("screen_lane_proof_already_used");
            proofKey = null;
            try
            {
                var start = Stopwatch.GetTimestamp();
                Span<byte> challenge = stackalloc byte[16];
                RandomNumberGenerator.Fill(challenge);
                Span<byte> context = stackalloc byte[ProofDomain.Length + aad.Length - HeaderSize + challenge.Length];
                ProofDomain.CopyTo(context);
                aad.AsSpan(0, aad.Length - HeaderSize).CopyTo(context[ProofDomain.Length..]);
                challenge.CopyTo(context[^challenge.Length..]);
                Transfer(challenge, true, start, false);
                Span<byte> actual = stackalloc byte[32];
                Transfer(actual, false, start, false);
                Span<byte> expected = stackalloc byte[32];
                HMACSHA256.HashData(key, context, expected);
                var matched = CryptographicOperations.FixedTimeEquals(actual, expected);
                CryptographicOperations.ZeroMemory(expected);
                CryptographicOperations.ZeroMemory(actual);
                if (!matched) throw new InvalidDataException("screen_socket_proof_invalid");
                Current(start, false);
                proofVerified = true;
            }
            catch { Dispose(); throw; }
            finally { CryptographicOperations.ZeroMemory(key); }
        }
    }

    // An empty payload is an authenticated heartbeat; never forward it to JPEG decoding.
    internal byte[] Receive()
    {
        lock (gate)
        {
            byte[]? clear = null;
            try
            {
                if (!proofVerified || ordinal == long.MaxValue)
                    throw new InvalidOperationException("screen_lane_proof_or_sequence_invalid");
                var start = Stopwatch.GetTimestamp();
                var header = aad.AsSpan(aad.Length - HeaderSize);
                Transfer(header, false, start, true);
                uint size = BinaryPrimitives.ReadUInt32BigEndian(header);
                if (size < TagSize || size > MaxJpeg + TagSize || BinaryPrimitives.ReadUInt64BigEndian(header[4..]) != (ulong)ordinal)
                    throw new InvalidDataException("screen_lane_envelope_invalid");
                byte[] encrypted = new byte[(int)size];
                Transfer(encrypted, false, start, true);
                clear = new byte[encrypted.Length - TagSize];
                Span<byte> nonce = stackalloc byte[12];
                prefix.CopyTo(nonce);
                header[4..].CopyTo(nonce[4..]);
                cipher!.Decrypt(nonce, encrypted.AsSpan(0, clear.Length), encrypted.AsSpan(clear.Length), clear, aad);
                Current(start, true);
                ordinal++;
                byte[] result = clear;
                clear = null;
                return result;
            }
            catch { Dispose(); throw; }
            finally { if (clear is not null) CryptographicOperations.ZeroMemory(clear); }
        }
    }

    private void Current(long start, bool media)
    {
        if (Volatile.Read(ref retired) != 0) throw new IOException("screen_lane_retired");
        requireOriginal();
        if (media) requireSend();
        if (Volatile.Read(ref retired) != 0) throw new IOException("screen_lane_retired");
        if (Stopwatch.GetElapsedTime(start) >= TimeSpan.FromSeconds(2)) throw new TimeoutException("screen_lane_deadline");
    }

    private void Transfer(Span<byte> bytes, bool write, long start, bool media)
    {
        while (!bytes.IsEmpty)
        {
            Current(start, media);
            int count;
            try { count = write ? socket.Send(bytes, SocketFlags.None) : socket.Receive(bytes, SocketFlags.None); }
            catch (SocketException error) when (error.SocketErrorCode is SocketError.TimedOut or SocketError.WouldBlock) { continue; }
            if (count == 0) throw new EndOfStreamException("screen_lane_disconnected");
            bytes = bytes[count..];
        }
        Current(start, media);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref retired, 1) != 0) return;
        try { socket.Shutdown(SocketShutdown.Both); }
        catch (SocketException) { }
        catch (ObjectDisposedException) { }
        socket.Dispose();
        lock (gate)
        {
            cipher?.Dispose();
            cipher = null;
            CryptographicOperations.ZeroMemory(prefix);
            if (proofKey is not null) CryptographicOperations.ZeroMemory(proofKey);
            proofKey = null;
        }
    }
}
