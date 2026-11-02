using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace MagnolieOrganizer.Windows;

internal sealed record KdeIncomingPayloadReceipt(long Bytes, string Sha256);

internal sealed partial class KdeConnectDirectBackend
{
    // Writes only to the receiver's already-owned staging stream. A successful
    // receipt is NOT user acceptance, a destination publication or a book ACK.
    internal static async Task<KdeIncomingPayloadReceipt> ReceiveFilePayloadTransportAsync(
        IPAddress address, int port, X509Certificate2 certificate, string peerId, string peerPin,
        long size, Stream output, Func<bool> permitted, CancellationToken cancellationToken,
        Action<long>? progress = null)
    {
        if (!IsPrivateAddress(address) || port is < KdeConnectProtocol.FirstPort or > KdeConnectProtocol.LastPort ||
            !IsPin(peerPin) || string.IsNullOrEmpty(peerId) || peerId.Length > 200 || peerId.Any(char.IsControl) ||
            size is < 0 or > KdeShareProtocol.MaxFileBytes || !output.CanWrite || !certificate.HasPrivateKey)
            throw new InvalidDataException("invalid_incoming_file_transport");
        using var operation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        operation.CancelAfter(TimeSpan.FromMinutes(2));
        void Require()
        {
            operation.Token.ThrowIfCancellationRequested();
            if (!permitted()) throw new InvalidOperationException("incoming_file_source_changed");
        }
        Require();
        using var client = new TcpClient(address.AddressFamily);
        X509Certificate2? remote = null;
        try
        {
            using (var handshake = CancellationTokenSource.CreateLinkedTokenSource(operation.Token))
            {
                handshake.CancelAfter(TimeSpan.FromSeconds(8));
                await client.ConnectAsync(address, port, handshake.Token).ConfigureAwait(false);
            }
            await using var tls = new SslStream(client.GetStream(), false, (_, presented, _, _) =>
                ValidateCertificate(presented, peerId, peerPin, ref remote));
            using (var handshake = CancellationTokenSource.CreateLinkedTokenSource(operation.Token))
            {
                handshake.CancelAfter(TimeSpan.FromSeconds(8));
                await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions
                {
                    TargetHost = peerId, ClientCertificates = new X509CertificateCollection { certificate },
                    EnabledSslProtocols = SslProtocols.Tls12, AllowRenegotiation = false,
                    CertificateRevocationCheckMode = X509RevocationMode.NoCheck
                }, handshake.Token).ConfigureAwait(false);
            }
            if (remote is null) throw new AuthenticationException("incoming_file_peer_unverified");
            Require();
            using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var buffer = new byte[65536];
            long received = 0;
            async Task<int> ReadAsync(Memory<byte> target)
            {
                using var read = CancellationTokenSource.CreateLinkedTokenSource(operation.Token);
                read.CancelAfter(TimeSpan.FromSeconds(8));
                return await tls.ReadAsync(target, read.Token).ConfigureAwait(false);
            }
            while (received < size)
            {
                Require();
                var count = await ReadAsync(buffer.AsMemory(0, (int)Math.Min(buffer.Length, size - received))).ConfigureAwait(false);
                if (count == 0) throw new EndOfStreamException("incoming_file_payload_truncated");
                Require();
                await output.WriteAsync(buffer.AsMemory(0, count), operation.Token).ConfigureAwait(false);
                digest.AppendData(buffer, 0, count);
                received += count;
                Require();
                progress?.Invoke(received);
            }
            if (await ReadAsync(buffer.AsMemory(0, 1)).ConfigureAwait(false) != 0)
                throw new InvalidDataException("incoming_file_payload_exceeds_size");
            Require();
            await output.FlushAsync(operation.Token).ConfigureAwait(false);
            Require();
            return new(received, Convert.ToHexString(digest.GetHashAndReset()).ToLowerInvariant());
        }
        finally { remote?.Dispose(); }
    }
}
