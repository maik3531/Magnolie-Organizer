using System.Buffers.Binary;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Meldet den Organizer als <c>_magnolie-phone._tcp</c> im lokalen Netz an.
///
/// Windows unterscheidet sich hier deutlich von Linux:
///   * Ein an <c>0.0.0.0</c> gebundener Socket sendet Multicast ausschließlich
///     über die Schnittstelle der Standardroute. Bei WLAN neben Ethernet, VPN
///     oder virtuellen Adaptern (Hyper-V, VirtualBox, VMware) erreicht die
///     Ankündigung das Telefon deshalb nie. Es wird darum je Schnittstelle
///     gesendet.
///   * Windows beantwortet keine mDNS-Abfrage nach dem eigenen
///     <c>.local</c>-Namen. Ohne A-Satz in der eigenen Antwort kann das Telefon
///     den im SRV-Satz genannten Rechner nicht auflösen. Der A-Satz gehört
///     deshalb zwingend in dieselbe Antwort.
/// </summary>
internal sealed class TelefonMdnsPublisher : IDisposable
{
    private static readonly IPAddress MulticastAddress = IPAddress.Parse("224.0.0.251");
    private const int MulticastPort = 5353;
    private readonly UdpClient socket;
    private readonly string deviceId;
    private readonly string displayName;
    private readonly Func<byte[]?> pairingToken;
    private readonly CancellationToken cancellation;
    private readonly string hostName;
    private bool disposed;

    internal TelefonMdnsPublisher(string deviceId, string displayName, Func<byte[]?> pairingToken, CancellationToken cancellation)
    {
        this.deviceId = deviceId; this.displayName = displayName; this.pairingToken = pairingToken; this.cancellation = cancellation;
        hostName = LocalHostName();
        socket = new UdpClient(AddressFamily.InterNetwork);
        socket.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
        socket.Client.Bind(new IPEndPoint(IPAddress.Any, MulticastPort));
        socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastTimeToLive, 255);
        JoinAllInterfaces();
    }

    internal async Task RunAsync()
    {
        await AnnounceAsync();
        var nextPeriodic = DateTimeOffset.UtcNow.AddSeconds(30);
        var nextAnswer = DateTimeOffset.UtcNow.AddSeconds(1);
        try
        {
            while (!cancellation.IsCancellationRequested)
            {
                using var interval = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                interval.CancelAfter(TimeSpan.FromSeconds(5));
                var query = false;
                try { query = IsOwnServiceQuery((await socket.ReceiveAsync(interval.Token)).Buffer); }
                catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { }
                catch (SocketException) { }
                /* Auf eine passende Abfrage wird geantwortet, sonst nur im
                   festen Takt. Ohne diese Trennung löst jedes fremde mDNS-Paket
                   im Netz eine eigene Ankündigung aus. Antworten werden dabei
                   zusammengefasst: Ein Telefon fragt beim Suchen mehrfach, und
                   eine Antwort je Abfrage verleitet es dazu, mehrere
                   Paarungsverbindungen gleichzeitig zu öffnen. */
                var now = DateTimeOffset.UtcNow;
                if ((query && now >= nextAnswer) || now >= nextPeriodic)
                {
                    await AnnounceAsync();
                    nextAnswer = DateTimeOffset.UtcNow.AddSeconds(1);
                    nextPeriodic = DateTimeOffset.UtcNow.AddSeconds(30);
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (ObjectDisposedException) { }
    }

    internal Task AnnounceNowAsync() => AnnounceAsync();

    private async Task AnnounceAsync()
    {
        if (disposed) return;
        var target = new IPEndPoint(MulticastAddress, MulticastPort);
        /* Je Schnittstelle mit deren eigener Adresse im A-Satz: nur so trägt die
           Antwort die Adresse, unter der das Telefon den Organizer erreicht. */
        var sent = false;
        foreach (var (index, address) in MulticastInterfaces())
        {
            try
            {
                socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastInterface,
                    IPAddress.HostToNetworkOrder(index));
                await socket.SendAsync(BuildResponse(address), target, cancellation);
                sent = true;
            }
            catch (SocketException) { }
            catch (ObjectDisposedException) { return; }
        }
        if (sent) return;
        try { await socket.SendAsync(BuildResponse(null), target, cancellation); }
        catch (SocketException) { }
        catch (ObjectDisposedException) { }
    }

    /// <summary>Alle betriebsbereiten, multicastfähigen IPv4-Schnittstellen mit ihrer Adresse.</summary>
    internal static List<(int Index, IPAddress Address)> MulticastInterfaces()
    {
        var result = new List<(int, IPAddress)>();
        try
        {
            foreach (var adapter in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (adapter.OperationalStatus != OperationalStatus.Up ||
                    adapter.NetworkInterfaceType == NetworkInterfaceType.Loopback ||
                    !adapter.SupportsMulticast) continue;
                IPInterfaceProperties properties;
                try { properties = adapter.GetIPProperties(); }
                catch (NetworkInformationException) { continue; }
                int index;
                try { index = properties.GetIPv4Properties()?.Index ?? 0; }
                catch (NetworkInformationException) { continue; }
                if (index == 0) continue;
                var address = properties.UnicastAddresses
                    .Select(entry => entry.Address)
                    .FirstOrDefault(entry => entry.AddressFamily == AddressFamily.InterNetwork &&
                        !IPAddress.IsLoopback(entry));
                if (address is null) continue;
                result.Add((index, address));
            }
        }
        catch (NetworkInformationException) { }
        return result;
    }

    private void JoinAllInterfaces()
    {
        var joined = false;
        foreach (var (index, _) in MulticastInterfaces())
        {
            try
            {
                socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.AddMembership,
                    new MulticastOption(MulticastAddress, index));
                joined = true;
            }
            catch (SocketException) { }
        }
        if (joined) return;
        try { socket.JoinMulticastGroup(MulticastAddress); }
        catch (SocketException) { }
    }

    /// <summary>Erkennt eine mDNS-Abfrage nach genau diesem Dienst.</summary>
    private bool IsOwnServiceQuery(byte[] packet)
    {
        if (packet.Length < 12) return false;
        /* Antworten (QR-Bit gesetzt) sind keine Abfrage. */
        if ((packet[2] & 0x80) != 0) return false;
        var questions = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(4, 2));
        if (questions == 0) return false;
        var wanted = Encoding.UTF8.GetBytes(TelefonCoordinator.ServiceType.TrimEnd('.').Split('.')[0]);
        for (var offset = 12; offset + wanted.Length + 1 < packet.Length; offset++)
            if (packet[offset] == wanted.Length && packet.AsSpan(offset + 1, wanted.Length).SequenceEqual(wanted))
                return true;
        return false;
    }

    internal static string LocalHostName()
    {
        string raw;
        try { raw = Dns.GetHostName(); }
        catch (SocketException) { raw = "magnolie"; }
        var label = new string(raw.Split('.')[0]
            .Select(character => char.IsAsciiLetterOrDigit(character) || character == '-' ? character : '-')
            .ToArray()).Trim('-');
        if (label.Length == 0) label = "magnolie";
        if (label.Length > 63) label = label[..63];
        return label + ".local.";
    }

    private byte[] BuildResponse(IPAddress? address) =>
        BuildAnnouncement(deviceId, displayName, hostName, pairingToken(), address);

    /// <summary>
    /// Baut die mDNS-Antwort. Der A-Satz gehört zwingend dazu: Windows
    /// beantwortet keine Abfrage nach dem eigenen <c>.local</c>-Namen, das
    /// Telefon könnte den Rechner aus dem SRV-Satz sonst nicht auflösen.
    /// </summary>
    internal static byte[] BuildAnnouncement(string deviceId, string displayName, string hostName,
        byte[]? token, IPAddress? address)
    {
        var service = TelefonCoordinator.ServiceType;
        var instance = deviceId + "." + service;
        var txt = new[] { "v=1", "role=desktop", "id=" + deviceId, "name=" + displayName,
            token is null ? "pair=0" : "token=" + Convert.ToBase64String(token), token is null ? "" : "pair=1" }.Where(value => value.Length > 0).ToArray();
        var answers = (ushort)(address is null ? 3 : 4);
        using var stream = new MemoryStream();
        WriteUInt16(stream, 0); WriteUInt16(stream, 0x8400); WriteUInt16(stream, 0); WriteUInt16(stream, answers); WriteUInt16(stream, 0); WriteUInt16(stream, 0);
        Record(stream, service, 12, Name(instance));
        using (var srv = new MemoryStream()) { WriteUInt16(srv, 0); WriteUInt16(srv, 0); WriteUInt16(srv, TelefonCoordinator.Port); srv.Write(Name(hostName)); Record(stream, instance, 33, srv.ToArray()); }
        using (var data = new MemoryStream()) { foreach (var item in txt) { var bytes = Encoding.UTF8.GetBytes(item); data.WriteByte((byte)bytes.Length); data.Write(bytes); } Record(stream, instance, 16, data.ToArray()); }
        if (address is not null) Record(stream, hostName, 1, address.GetAddressBytes());
        return stream.ToArray();
    }

    private static void Record(Stream stream, string name, ushort type, byte[] data)
    { stream.Write(Name(name)); WriteUInt16(stream, type); WriteUInt16(stream, 1); WriteUInt32(stream, 120); WriteUInt16(stream, (ushort)data.Length); stream.Write(data); }
    private static byte[] Name(string value)
    { using var stream = new MemoryStream(); foreach (var label in value.TrimEnd('.').Split('.')) { var bytes = Encoding.UTF8.GetBytes(label); if (bytes.Length is < 1 or > 63) throw new InvalidDataException("Ungültiger mDNS-Name."); stream.WriteByte((byte)bytes.Length); stream.Write(bytes); } stream.WriteByte(0); return stream.ToArray(); }
    private static void WriteUInt16(Stream stream, ushort value) { Span<byte> bytes = stackalloc byte[2]; BinaryPrimitives.WriteUInt16BigEndian(bytes, value); stream.Write(bytes); }
    private static void WriteUInt32(Stream stream, uint value) { Span<byte> bytes = stackalloc byte[4]; BinaryPrimitives.WriteUInt32BigEndian(bytes, value); stream.Write(bytes); }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        try { socket.DropMulticastGroup(MulticastAddress); } catch (Exception error) when (error is SocketException or ObjectDisposedException) { }
        socket.Dispose();
    }
}
