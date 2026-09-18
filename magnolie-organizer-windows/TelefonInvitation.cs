using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

internal sealed record TelefonInvitationPhone(string Id, string Name, IPAddress Address, int Port, string Nonce);

// mDNS and invitations are untrusted discovery only. No keys or grants are
// accepted here; the existing telephone handshake authenticates the selected ID.
internal static class TelefonInvitation
{
    internal const string Service = "_magnolie-invite._tcp.local.";
    internal const string Protocol = "magnolie-phone-invite/1";
    internal static bool Local(IPAddress address)
    {
        var b = address.GetAddressBytes();
        return b.Length == 4 && (b[0] == 10 || b[0] == 172 && b[1] is >= 16 and <= 31 ||
            b[0] == 192 && b[1] == 168 || b[0] == 169 && b[1] == 254);
    }

    internal static async Task<IReadOnlyList<TelefonInvitationPhone>> DiscoverAsync(CancellationToken cancellation)
    {
        using var socket = new UdpClient(AddressFamily.InterNetwork);
        socket.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
        socket.Client.Bind(new IPEndPoint(IPAddress.Any, 5353));
        socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastTimeToLive, 255);
        var group = IPAddress.Parse("224.0.0.251");
        using var query = new MemoryStream();
        query.Write(new byte[] { 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0 });
        foreach (var label in Service.TrimEnd('.').Split('.')) { query.WriteByte((byte)label.Length); query.Write(Encoding.ASCII.GetBytes(label)); }
        query.Write(new byte[] { 0, 0, 12, 0, 1 });
        foreach (var (index, _) in TelefonMdnsPublisher.MulticastInterfaces())
        {
            try
            {
                socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.AddMembership, new MulticastOption(group, index));
                socket.Client.SetSocketOption(SocketOptionLevel.IP, SocketOptionName.MulticastInterface, IPAddress.HostToNetworkOrder(index));
                await socket.SendAsync(query.ToArray(), new IPEndPoint(group, 5353), cancellation);
            }
            catch (SocketException) { }
        }
        var records = new Dictionary<(IPAddress, string), (int Port, Dictionary<string, string>? Txt)>();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(4));
        try
        {
            for (var packets = 0; packets < 256; packets++)
            {
                var packet = await socket.ReceiveAsync(deadline.Token);
                if (packet.RemoteEndPoint.Port != 5353 || !Local(packet.RemoteEndPoint.Address)) continue;
                try { ReadAnnouncement(packet.Buffer, packet.RemoteEndPoint.Address, records); }
                catch (Exception error) when (error is InvalidDataException or ArgumentException or DecoderFallbackException or IndexOutOfRangeException) { }
            }
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { }
        var result = new List<TelefonInvitationPhone>();
        foreach (var (key, value) in records)
        {
            var txt = value.Txt;
            if (value.Port is < 1024 or > 65535 || txt is null || txt.Count != 4 || txt.GetValueOrDefault("v") != "1" ||
                !Guid.TryParseExact(txt.GetValueOrDefault("id"), "D", out var id) || id.ToString() != txt["id"] ||
                !txt.TryGetValue("name", out var name) || name.EnumerateRunes().Count() is < 1 or > 60 ||
                name.Any(c => char.IsControl(c) || char.GetUnicodeCategory(c) == System.Globalization.UnicodeCategory.Format) ||
                !txt.TryGetValue("nonce", out var nonce)) continue;
            try { if (Convert.FromBase64String(nonce).Length != 16 || Convert.ToBase64String(Convert.FromBase64String(nonce)) != nonce) continue; }
            catch (FormatException) { continue; }
            if (result.All(p => p.Id != txt["id"])) result.Add(new(txt["id"], name, key.Item1, value.Port, nonce));
        }
        return result.Take(16).ToArray();
    }

    internal static void ReadAnnouncement(byte[] packet, IPAddress source,
        Dictionary<(IPAddress, string), (int Port, Dictionary<string, string>? Txt)> records)
    {
        if (packet.Length is < 12 or > 9000 || (packet[2] & 0x80) == 0) return;
        int U16(int at) => BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(at, 2));
        string Name(ref int offset)
        {
            var pos = offset; var jumped = false; var labels = new List<string>();
            for (var hops = 0; hops < 64; hops++)
            {
                var length = packet[pos++];
                if (length == 0) { if (!jumped) offset = pos; return string.Join('.', labels) + "."; }
                if ((length & 0xc0) == 0xc0)
                { var pointer = ((length & 63) << 8) | packet[pos++]; if (!jumped) offset = pos; jumped = true; pos = pointer; continue; }
                if (length > 63 || pos + length > packet.Length) throw new InvalidDataException();
                labels.Add(Encoding.ASCII.GetString(packet, pos, length)); pos += length;
            }
            throw new InvalidDataException();
        }
        var questions = U16(4); var count = U16(6) + U16(8) + U16(10);
        if (questions > 32 || count > 128) return;
        var offset = 12;
        for (var i = 0; i < questions; i++) { Name(ref offset); offset += 4; }
        for (var i = 0; i < count; i++)
        {
            var owner = Name(ref offset); var type = U16(offset); var ttl = BinaryPrimitives.ReadUInt32BigEndian(packet.AsSpan(offset + 4, 4));
            var size = U16(offset + 8); offset += 10; var end = checked(offset + size);
            if (end > packet.Length) throw new InvalidDataException();
            var key = (source, owner);
            if (owner.EndsWith("." + Service, StringComparison.OrdinalIgnoreCase) && type is 16 or 33 && (records.ContainsKey(key) || records.Count < 64))
            {
                if (ttl == 0) { records.Remove(key); offset = end; continue; }
                var previous = records.GetValueOrDefault(key);
                if (type == 33 && size >= 7) previous.Port = U16(offset + 4);
                if (type == 16)
                {
                    var txt = new Dictionary<string, string>();
                    var at = offset;
                    while (at < end)
                    {
                        var length = packet[at++]; if (at + length > end) throw new InvalidDataException();
                        var text = new UTF8Encoding(false, true).GetString(packet, at, length); at += length;
                        var split = text.IndexOf('=');
                        if (split <= 0 || !txt.TryAdd(text[..split], text[(split + 1)..])) throw new InvalidDataException();
                    }
                    previous.Txt = txt;
                }
                records[key] = previous;
            }
            offset = end;
        }
    }

    internal static async Task SendAsync(TelefonInvitationPhone phone, JsonObject identity, CancellationToken cancellation)
    {
        if (!Local(phone.Address) || phone.Port is < 1024 or > 65535) throw new InvalidDataException();
        using var socket = new TcpClient(AddressFamily.InterNetwork);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(60));
        await socket.ConnectAsync(phone.Address, phone.Port, deadline.Token);
        var offer = identity.DeepClone().AsObject();
        offer["p"] = Protocol; offer["type"] = "offer"; offer["target"] = phone.Id;
        offer["nonce"] = phone.Nonce; offer["port"] = TelefonCoordinator.Port; offer["ttl"] = 60;
        await TelefonCoordinator.WriteFrameAsync(socket.GetStream(), offer, deadline.Token);
        var response = await TelefonCoordinator.ReadFrameAsync(socket.GetStream(), 2048, deadline.Token);
        if (response.Count != 3 || response["p"]?.GetValue<string>() != Protocol || response["type"]?.GetValue<string>() != "accepted" ||
            response["nonce"]?.GetValue<string>() != phone.Nonce) throw new InvalidDataException();
    }
}
