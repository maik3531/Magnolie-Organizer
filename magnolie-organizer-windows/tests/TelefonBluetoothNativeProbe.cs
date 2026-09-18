#if WINDOWS
using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.Rfcomm;
using Windows.Devices.Enumeration;
using Windows.Devices.Radios;
#endif

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonBluetoothNativeProbe
{
    internal static async Task<int> RunAsync()
    {
#if WINDOWS
        // Read-only inventory. No discovery, PairAsync, RequestAccessAsync,
        // advertising, radio state changes or connections to real devices.
        var adapter = await BluetoothAdapter.GetDefaultAsync();
        var radios = await Radio.GetRadiosAsync();
        var paired = await DeviceInformation.FindAllAsync(BluetoothDevice.GetDeviceSelectorFromPairingState(true),
            ["System.Devices.Aep.DeviceAddress"], DeviceInformationKind.AssociationEndpoint);
        Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {
            adapter = adapter is not null, classic = adapter?.IsClassicSupported == true,
            radios = radios.Count(r => r.Kind == RadioKind.Bluetooth),
            powered = radios.Count(r => r.Kind == RadioKind.Bluetooth && r.State == RadioState.On),
            bondedDeviceCount = paired.Count,
            pairingApi = typeof(DeviceInformationPairing).GetMethods().Any(m => m.Name == "PairAsync"),
            rfcommApi = typeof(RfcommDeviceService).FullName
        }));
        return 0;
#else
        await Task.CompletedTask;
        Console.Error.WriteLine("Build this read-only probe with the Windows target framework.");
        return 2;
#endif
    }
}
