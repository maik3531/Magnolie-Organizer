using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class KdeConnectDirectBackend
{
    private readonly KdeSystemVolume? systemVolume;
    private readonly SemaphoreSlim systemVolumeUpdates = new(1, 1);

    private bool SystemVolumePermitted(Connection connection)
    {
        lock (activeGate)
            return !disposed && !lifetime.IsCancellationRequested && !connection.Closed &&
                active.TryGetValue(connection.Identity.DeviceId, out var current) && ReferenceEquals(current, connection) &&
                connection.Identity.OutgoingCapabilities.Contains(KdeSystemVolume.Request) &&
                connection.Identity.IncomingCapabilities.Contains(KdeSystemVolume.Packet) &&
                store.LoadPeers().Any(peer => peer.Paired && peer.Id == connection.Identity.DeviceId &&
                    peer.CertificatePin == KdeConnectProtocol.CertificatePin(connection.Certificate));
    }

    private async Task HandleSystemVolumeAsync(Connection? requester, JsonObject body, CancellationToken cancellationToken)
    {
        if (systemVolume is null || requester is not null && !SystemVolumePermitted(requester)) return;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(TimeSpan.FromSeconds(3));
        var entered = false;
        try
        {
            await systemVolumeUpdates.WaitAsync(deadline.Token).ConfigureAwait(false);
            entered = true;
            Connection[] connections = requester is null ? active.Values.Where(SystemVolumePermitted).ToArray() : [requester];
            if (connections.Length == 0) return;
            bool Permitted() => connections.Any(SystemVolumePermitted);
            var response = await systemVolume.ReceiveAsync(body, Permitted, deadline.Token).ConfigureAwait(false);
            var serialized = response.ToJsonString();
            foreach (var connection in connections)
            {
                if (!SystemVolumePermitted(connection) || requester is null && connection.SystemVolumeLast == serialized) continue;
                await connection.WriteAsync(KdeConnectProtocol.Encode(KdeSystemVolume.Packet, response), deadline.Token).ConfigureAwait(false);
                connection.SystemVolumeLast = serialized;
            }
        }
        catch (Exception) { /* No retry of a volume/mute action and no shutdown of unrelated paired modules. */ }
        finally { if (entered) systemVolumeUpdates.Release(); }
    }

    private async Task SystemVolumeWatchAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            if (active.Values.Any(SystemVolumePermitted))
                await HandleSystemVolumeAsync(null, new JsonObject { ["requestSinks"] = true }, cancellationToken).ConfigureAwait(false);
            try { await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) { break; }
        }
    }
}
