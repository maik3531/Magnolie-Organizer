using System.Net;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed partial class KdeConnectDirectBackend
{
    private readonly IKdeFilesystemBrowser filesystem;
    private JsonObject OwnIdentity() => KdeConnectProtocol.IdentityBody(local.Id, local.Name, ListenerPort,
        localMediaSupported: localMedia is not null, localInputSupported: OperatingSystem.IsWindows(), filesystemSupported: filesystem.Available,
        systemVolumeSupported: systemVolume is not null);

    private Connection FilesystemConnection(string id)
    {
        if (disposed || lifetime.IsCancellationRequested || !filesystem.Available || !active.TryGetValue(id, out var connection) ||
            connection.Closed || connection.FilesystemBlocked || connection.Identity.DeviceType is not ("phone" or "tablet") ||
            !connection.Identity.IncomingCapabilities.Contains(KdeSftpDescription.Request) ||
            !connection.Identity.OutgoingCapabilities.Contains(KdeSftpDescription.Packet) ||
            connection.Address.Equals(IPAddress.Any) || connection.Address.Equals(IPAddress.IPv6Any) ||
            !store.LoadPeers().Any(peer => peer.Paired && peer.Id == id && peer.CertificatePin == KdeConnectProtocol.CertificatePin(connection.Certificate)))
            throw new InvalidOperationException("filesystem_unavailable");
        return connection;
    }
    private bool FilesystemCurrent(Connection connection)
    {
        lock (activeGate)
            try { return ReferenceEquals(FilesystemConnection(connection.Identity.DeviceId), connection); }
            catch (Exception error) when (error is InvalidOperationException or CryptographicException or ObjectDisposedException) { return false; }
    }
    internal JsonObject FilesystemStatus()
    {
        var devices = new JsonArray();
        lock (activeGate)
            foreach (var (id, candidate) in active)
                if (FilesystemCurrent(candidate))
                    devices.Add(new JsonObject { ["device_id"] = id, ["device_name"] = candidate.Identity.DeviceName,
                        ["available"] = true, ["transport"] = "wifi", ["token"] = candidate.FilesystemToken });
        return new JsonObject { ["native"] = false, ["devices"] = devices };
    }
    internal async Task<JsonObject> OpenFilesystemAsync(string id, string token, CancellationToken cancellation, Func<bool>? permitted = null)
    {
        Connection connection;
        lock (activeGate)
        {
            if (permitted?.Invoke() == false) throw new InvalidOperationException("locked");
            connection = FilesystemConnection(id);
            if (token != connection.FilesystemToken) throw new InvalidOperationException("filesystem_source_changed");
        }
        using var operation = CancellationTokenSource.CreateLinkedTokenSource(cancellation, lifetime.Token);
        await connection.FilesystemRequests.WaitAsync(operation.Token).ConfigureAwait(false);
        try
        {
            TaskCompletionSource<KdeSftpDescription> completion;
            if (!FilesystemCurrent(connection) || permitted?.Invoke() == false) throw new InvalidOperationException("filesystem_source_changed");
            lock (connection.FilesystemGate)
            {
                if (connection.Closed) throw new InvalidOperationException("filesystem_source_changed");
                completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
                connection.FilesystemReply = completion; connection.FilesystemDeadline = Environment.TickCount64 + 8000;
            }
            await connection.WriteAsync(KdeConnectProtocol.Encode(KdeSftpDescription.Request, new JsonObject { ["startBrowsing"] = true }), operation.Token).ConfigureAwait(false);
            KdeSftpDescription report;
            try { report = await completion.Task.WaitAsync(TimeSpan.FromSeconds(8), operation.Token).ConfigureAwait(false); }
            catch (TimeoutException)
            { connection.FilesystemBlocked = true; throw new IOException("filesystem_read_timeout"); }
            catch (OperationCanceledException)
            { if (!completion.Task.IsCompletedSuccessfully) connection.FilesystemBlocked = true; throw; }
            if (!FilesystemCurrent(connection)) throw new InvalidOperationException("filesystem_source_changed");
            var publicKey = KdeSftpDescription.PublicHostKey(connection.Certificate);
            await filesystem.OpenAsync(connection.FilesystemToken, connection.Address, report, publicKey,
                () => permitted?.Invoke() != false && FilesystemCurrent(connection), operation.Token).ConfigureAwait(false);
            return new JsonObject { ["ok"] = true, ["state"] = "opened", ["device_id"] = id };
        }
        finally
        {
            lock (connection.FilesystemGate) connection.FilesystemReply = null;
            connection.FilesystemRequests.Release();
        }
    }
    private void HandleFilesystemPacket(Connection connection, KdeConnectPacket packet)
    {
        if (!FilesystemCurrent(connection)) return;
        lock (connection.FilesystemGate)
        {
            var reply = connection.FilesystemReply;
            if (reply is null || reply.Task.IsCompleted || Environment.TickCount64 >= connection.FilesystemDeadline) return;
            try { reply.TrySetResult(KdeSftpDescription.Parse(packet.Body)); }
            catch (InvalidDataException) { reply.TrySetException(new IOException("filesystem_unavailable")); }
        }
    }
}
