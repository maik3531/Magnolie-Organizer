using Windows.Devices.Radios;
using Windows.Foundation.Metadata;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Das echte Funkgerät über die WinRT-Radio-Schnittstelle.
///
/// Getrennt von <see cref="BluetoothRadioSwitch"/>, weil diese Datei WinRT
/// benötigt und deshalb nicht im Testprojekt übersetzt werden kann.
/// </summary>
internal sealed class WindowsBluetoothRadio : IBluetoothRadio
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetCurrentPackageFullName(ref uint length, IntPtr name);

    internal static JsonObject CallRoutingCapability()
    {
        var api = false;
        var identity = false;
        try
        {
            if (OperatingSystem.IsWindows())
            {
                api = ApiInformation.IsApiContractPresent("Windows.ApplicationModel.Calls.CallsPhoneContract", 6)
                    && ApiInformation.IsTypePresent("Windows.ApplicationModel.Calls.PhoneLineTransportDevice");
                uint length = 0;
                identity = GetCurrentPackageFullName(ref length, IntPtr.Zero) == 122 && length > 0;
            }
        }
        catch (Exception error) when (error is TypeLoadException or DllNotFoundException or EntryPointNotFoundException
                                      or InvalidOperationException or UnauthorizedAccessException or NotSupportedException or COMException) { }
        // The shipped Win32 deployment has neither an approved restricted capability
        // nor a packaged transport adapter. API presence and RadioOn prove neither.
        return new JsonObject
        {
            ["backend"] = "windows_public_phone_transport", ["state"] = "unsupported",
            ["available"] = false, ["active"] = false,
            ["reason"] = !api ? "public_api_unavailable" : !identity ? "package_identity_required" : "approved_capability_required",
            ["api_present"] = api, ["package_identity"] = identity,
            ["approved_capability"] = false, ["required_capability"] = "phoneLineTransportManagement",
            ["local_role"] = "111e", ["remote_role"] = "111f",
            ["route"] = new JsonObject { ["state"] = "unsupported", ["active"] = false }
        };
    }

    public async Task<bool?> IsOnAsync()
    {
        var radio = await FindAsync().ConfigureAwait(false);
        return radio is null ? null : radio.State == RadioState.On;
    }

    public async Task<bool> SetAsync(bool on)
    {
        if (CallRoutingCapability()["available"]?.GetValue<bool>() != true) return false;
        var radio = await FindAsync().ConfigureAwait(false);
        if (radio is null) return false;
        try { return await radio.SetStateAsync(on ? RadioState.On : RadioState.Off) == RadioAccessStatus.Allowed; }
        catch (Exception error) when (error is InvalidOperationException or UnauthorizedAccessException
                                          or System.Runtime.InteropServices.COMException)
        { return false; }
    }

    private static async Task<Radio?> FindAsync()
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            // Observation only. Automatic call handling must not prompt for access.
            return (await Radio.GetRadiosAsync()).FirstOrDefault(item => item.Kind == RadioKind.Bluetooth);
        }
        catch (Exception error) when (error is InvalidOperationException or UnauthorizedAccessException
                                          or System.Runtime.InteropServices.COMException)
        { return null; }
    }
}
