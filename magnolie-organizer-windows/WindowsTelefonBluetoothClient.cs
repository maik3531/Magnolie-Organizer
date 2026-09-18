#if WINDOWS
using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.Rfcomm;
using Windows.Devices.Enumeration;
using Windows.Devices.Radios;
using Windows.Networking.Sockets;

namespace MagnolieOrganizer.Windows;

internal sealed class WindowsTelefonBluetoothClient : ITelefonBluetoothClient
{
    private static string T(string text) => NativeLocalization.Gettext(text);
    public async Task<IReadOnlyList<TelefonBluetoothCandidate>> DiscoverAsync(CancellationToken cancellation)
    {
        var adapter = await BluetoothAdapter.GetDefaultAsync().AsTask(cancellation);
        if (adapter is null || !adapter.IsClassicSupported || (await adapter.GetRadioAsync().AsTask(cancellation)).State != RadioState.On)
            throw new NotSupportedException(T("Bluetooth is unavailable. Check the radio and OS permissions."));
        var devices = new Dictionary<string, TelefonBluetoothCandidate>();
        var gate = new object();
        var watcher = DeviceInformation.CreateWatcher(BluetoothDevice.GetDeviceSelector(),
            ["System.Devices.Aep.DeviceAddress"], DeviceInformationKind.AssociationEndpoint);
        watcher.Added += (_, info) =>
        {
            var raw = info.Properties.GetValueOrDefault("System.Devices.Aep.DeviceAddress")?.ToString()?.ToUpperInvariant() ?? "";
            if (!TelefonBluetoothClient.ValidAddress(raw)) return;
            var name = new string(info.Name.Where(c => !char.IsControl(c) && char.GetUnicodeCategory(c) != System.Globalization.UnicodeCategory.Format).Take(60).ToArray());
            lock (gate) if (devices.Count < 32) devices.TryAdd(raw, new(info.Id, raw, name.Length == 0 ? raw : name, info.Pairing.IsPaired));
        };
        try { watcher.Start(); await Task.Delay(TimeSpan.FromSeconds(8), cancellation); }
        finally { if (watcher.Status is DeviceWatcherStatus.Started or DeviceWatcherStatus.EnumerationCompleted) watcher.Stop(); }
        lock (gate) return devices.Values.ToArray();
    }

    public async Task PairAsync(TelefonBluetoothCandidate selected, CancellationToken cancellation)
    {
        if (!TelefonBluetoothClient.ValidAddress(selected.Address)) throw new InvalidDataException();
        var info = await DeviceInformation.CreateFromIdAsync(selected.Id, ["System.Devices.Aep.DeviceAddress"], DeviceInformationKind.AssociationEndpoint).AsTask(cancellation);
        if (!string.Equals(info.Properties.GetValueOrDefault("System.Devices.Aep.DeviceAddress")?.ToString(), selected.Address, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException(T("Wrong Bluetooth device."));
        if (!info.Pairing.IsPaired)
        {
            var result = await info.Pairing.PairAsync(DevicePairingProtectionLevel.EncryptionAndAuthentication).AsTask(cancellation);
            if (result.Status is not (DevicePairingResultStatus.Paired or DevicePairingResultStatus.AlreadyPaired))
                throw new UnauthorizedAccessException(T("Bluetooth system pairing was not confirmed."));
        }
    }

    public async Task<TelefonBluetoothLink> ConnectAsync(string address, CancellationToken cancellation)
    {
        if (!TelefonBluetoothClient.ValidAddress(address)) throw new InvalidDataException();
        var number = Convert.ToUInt64(address.Replace(":", ""), 16);
        using var device = await BluetoothDevice.FromBluetoothAddressAsync(number).AsTask(cancellation)
            ?? throw new IOException(T("Bluetooth device unavailable."));
        if (device.BluetoothAddress != number || !device.DeviceInformation.Pairing.IsPaired) throw new UnauthorizedAccessException();
        var services = await device.GetRfcommServicesForIdAsync(RfcommServiceId.FromUuid(TelefonCoordinator.BluetoothService), BluetoothCacheMode.Uncached).AsTask(cancellation);
        if (services.Error != BluetoothError.Success || services.Services.Count != 1) throw new IOException(T("Open the phone connection screen and try again."));
        using var service = services.Services[0];
        if (service.Device.BluetoothAddress != number) throw new InvalidDataException(T("Wrong Bluetooth device."));
        var socket = new StreamSocket();
        try
        {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
            deadline.CancelAfter(TimeSpan.FromSeconds(10));
            using var registration = deadline.Token.Register(socket.Dispose);
            await socket.ConnectAsync(service.ConnectionHostName, service.ConnectionServiceName, SocketProtectionLevel.BluetoothEncryptionWithAuthentication).AsTask(deadline.Token);
            return new TelefonBluetoothLink(address, new TelefonDuplexStream(socket.InputStream.AsStreamForRead(), socket.OutputStream.AsStreamForWrite()), socket.Dispose);
        }
        catch { socket.Dispose(); throw; }
    }
}
#endif
