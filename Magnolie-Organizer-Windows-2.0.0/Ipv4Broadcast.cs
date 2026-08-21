using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;

namespace MagnolieOrganizer.Windows;

internal static class Ipv4Broadcast
{
    internal static IReadOnlyList<IPAddress> DirectedAddresses()
    {
        var result = new List<IPAddress>();
        try
        {
            foreach (var adapter in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (adapter.OperationalStatus != OperationalStatus.Up ||
                    adapter.NetworkInterfaceType == NetworkInterfaceType.Loopback) continue;
                IPInterfaceProperties properties;
                try { properties = adapter.GetIPProperties(); }
                catch (NetworkInformationException) { continue; }
                foreach (var entry in properties.UnicastAddresses)
                {
                    if (entry.Address.AddressFamily != AddressFamily.InterNetwork ||
                        IPAddress.IsLoopback(entry.Address) || entry.IPv4Mask is null) continue;
                    var candidate = Calculate(entry.Address, entry.IPv4Mask);
                    if (!candidate.Equals(IPAddress.Broadcast) && !result.Contains(candidate)) result.Add(candidate);
                }
            }
        }
        catch (NetworkInformationException) { }
        return result;
    }

    internal static IPAddress Calculate(IPAddress address, IPAddress mask)
    {
        var hostBytes = address.GetAddressBytes();
        var maskBytes = mask.GetAddressBytes();
        if (address.AddressFamily != AddressFamily.InterNetwork || maskBytes.Length != hostBytes.Length)
            throw new ArgumentException("Adresse und Netzmaske müssen IPv4-Werte sein.");
        var broadcast = new byte[hostBytes.Length];
        for (var index = 0; index < hostBytes.Length; index++)
            broadcast[index] = (byte)(hostBytes[index] | ~maskBytes[index]);
        return new IPAddress(broadcast);
    }
}
