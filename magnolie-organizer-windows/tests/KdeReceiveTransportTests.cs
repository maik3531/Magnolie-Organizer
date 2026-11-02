using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class KdeReceiveTransportTests
{
    private sealed class RevokingStream(Action revoke) : MemoryStream
    {
        public override async ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default)
        {
            await base.WriteAsync(buffer, cancellationToken);
            revoke();
        }
    }

    internal static async Task RunAsync()
    {
        using var desktop = KdeConnectTests.Certificate("desktop_payload");
        using var phone = KdeConnectTests.Certificate("phone_payload");
        using var otherPhone = KdeConnectTests.Certificate("phone_payload");
        using var otherDesktop = KdeConnectTests.Certificate("other_desktop");
        foreach (var scenario in new[] { "valid", "empty", "short", "long", "wrong-key", "wrong-id", "wrong-client", "revoked", "canceled" })
        {
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(12));
            using var cancelReceive = CancellationTokenSource.CreateLinkedTokenSource(deadline.Token);
            var listener = KdeConnectTests.BindKdeListener();
            var port = ((IPEndPoint)listener.LocalEndpoint).Port;
            var expectedFailure = scenario is not ("valid" or "empty");
            var allowed = true;
            using MemoryStream output = scenario == "revoked" ? new RevokingStream(() => allowed = false) : new MemoryStream();
            var payload = scenario == "empty" ? Array.Empty<byte>() : new byte[] { 1, 2, 3, 4 };
            long advertised = scenario == "short" ? 5 : scenario == "long" ? 3 : payload.Length;
            var progress = new List<long>();
            var server = ServeAsync();
            async Task ServeAsync()
            {
                try
                {
                    using var client = await listener.AcceptTcpClientAsync(deadline.Token);
                    await using var tls = new SslStream(client.GetStream(), false, (_, presented, _, _) =>
                    {
                        if (presented is null) return false;
                        using var value = new X509Certificate2(presented);
                        return KdeConnectProtocol.CertificatePin(value) == KdeConnectProtocol.CertificatePin(desktop);
                    });
                    await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions
                    {
                        ServerCertificate = scenario == "wrong-key" ? otherPhone : phone,
                        ClientCertificateRequired = true, EnabledSslProtocols = SslProtocols.Tls12,
                        CertificateRevocationCheckMode = X509RevocationMode.NoCheck
                    }, deadline.Token);
                    if (scenario == "canceled") await Task.Delay(Timeout.InfiniteTimeSpan, deadline.Token);
                    await tls.WriteAsync(payload, deadline.Token);
                    await tls.FlushAsync(deadline.Token);
                }
                catch (Exception error) when (expectedFailure && error is AuthenticationException or IOException or OperationCanceledException) { }
            }
            try
            {
                if (scenario == "canceled") cancelReceive.CancelAfter(TimeSpan.FromMilliseconds(250));
                KdeIncomingPayloadReceipt? receipt = null;
                var failed = false;
                try
                {
                    receipt = await KdeConnectDirectBackend.ReceiveFilePayloadTransportAsync(IPAddress.Loopback, port,
                        scenario == "wrong-client" ? otherDesktop : desktop, scenario == "wrong-id" ? "another_phone" : "phone_payload",
                        KdeConnectProtocol.CertificatePin(phone), advertised, output, () => allowed, cancelReceive.Token, progress.Add);
                }
                catch (Exception error) when (expectedFailure && error is AuthenticationException or IOException or
                    InvalidDataException or InvalidOperationException or OperationCanceledException) { failed = true; }
                if (expectedFailure) deadline.Cancel();
                await server.WaitAsync(TimeSpan.FromSeconds(2));
                TestAssert.That(failed == expectedFailure && (receipt is null) == expectedFailure,
                    "Payload transport returned an acceptance/receipt for a rejected peer, source or byte stream: " + scenario);
                if (!expectedFailure)
                {
                    TestAssert.That(output.ToArray().SequenceEqual(payload) && receipt!.Bytes == advertised &&
                        receipt.Sha256 == Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant(),
                        "Pinned payload readback/digest did not match the actual bytes.");
                    TestAssert.That(progress.SequenceEqual(progress.Order()) && progress.All(value => value <= advertised) &&
                        (advertised == 0 || progress.Last() == advertised), "Byte progress was invented or exceeded the actual payload.");
                }
                if (scenario is "wrong-key" or "wrong-id" or "wrong-client")
                    TestAssert.That(output.Length == 0, "An unauthenticated peer wrote application bytes to staging.");
            }
            finally
            {
                deadline.Cancel(); listener.Stop();
                try { await server.WaitAsync(TimeSpan.FromSeconds(2)); }
                catch (Exception error) when (error is OperationCanceledException or SocketException) { }
            }
        }
        using var discarded = new MemoryStream();
        await TestAssert.ThrowsAsync<InvalidDataException>(() => KdeConnectDirectBackend.ReceiveFilePayloadTransportAsync(
            IPAddress.Parse("8.8.8.8"), 1716, desktop, "phone_payload", KdeConnectProtocol.CertificatePin(phone), 1,
            discarded, () => true, CancellationToken.None), "Public IP payload redirection was allowed.");
    }
}
