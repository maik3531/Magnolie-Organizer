using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;

namespace MagnolieOrganizer.Windows;

internal sealed partial class KdeConnectDirectBackend
{
    private readonly SemaphoreSlim mediaPayloads = new(1, 1);

    private async Task SendMediaArtworkAsync(Connection connection, KdeMediaArtwork artwork, Func<bool> permitted, CancellationToken cancellationToken)
    {
        if (!await mediaPayloads.WaitAsync(0, cancellationToken).ConfigureAwait(false)) return;
        try
        {
            if (connection.LocalAddress is not { } address || !permitted()) return;
            await SendMediaArtworkTransportAsync(address, local.Certificate, connection.Identity.DeviceId,
                KdeConnectProtocol.CertificatePin(connection.Certificate), artwork, permitted, connection.WriteAsync, cancellationToken).ConfigureAwait(false);
        }
        finally { mediaPayloads.Release(); }
    }

    internal static async Task SendMediaArtworkTransportAsync(IPAddress address, X509Certificate2 certificate, string peerId, string peerPin,
        KdeMediaArtwork artwork, Func<bool> permitted, Func<byte[], CancellationToken, Task> announce, CancellationToken cancellationToken)
    {
        if (artwork.Data.Length is < 1 or > 2 * 1024 * 1024 || !permitted()) throw new InvalidDataException("invalid_media_payload");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(TimeSpan.FromSeconds(8)); var token = deadline.Token;
        TcpListener? listener = null;
        X509Certificate2? remote = null;
        try
        {
            for (var port = KdeConnectProtocol.FirstPort; port <= KdeConnectProtocol.LastPort; port++)
            {
                var candidate = new TcpListener(address, port);
                try { candidate.Start(1); listener = candidate; break; }
                catch (SocketException) { candidate.Stop(); }
            }
            if (listener is null) throw new IOException("media_payload_port_unavailable");
            if (!permitted()) throw new InvalidOperationException("local_media_source_changed");
            var selectedPort = ((IPEndPoint)listener.LocalEndpoint).Port;
            await announce(KdeConnectProtocol.Encode(KdeMediaState.Packet, artwork.Body, payloadSize: artwork.Data.Length, payloadPort: selectedPort), token).ConfigureAwait(false);
            using var client = await listener.AcceptTcpClientAsync(token).ConfigureAwait(false);
            await using var tls = new SslStream(client.GetStream(), false, (_, presented, _, _) =>
                ValidateCertificate(presented, peerId, peerPin, ref remote));
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
            {
                ServerCertificate = certificate, ClientCertificateRequired = true,
                EnabledSslProtocols = SslProtocols.Tls12, CertificateRevocationCheckMode = X509RevocationMode.NoCheck
            }, token).ConfigureAwait(false);
            if (remote is null) throw new AuthenticationException("media_payload_peer_unverified");
            for (var offset = 0; offset < artwork.Data.Length; offset += 65536)
            {
                if (!permitted()) throw new InvalidOperationException("local_media_source_changed");
                await tls.WriteAsync(artwork.Data.AsMemory(offset, Math.Min(65536, artwork.Data.Length - offset)), token).ConfigureAwait(false);
            }
            await tls.FlushAsync(token).ConfigureAwait(false);
        }
        finally { listener?.Stop(); remote?.Dispose(); }
    }
}
