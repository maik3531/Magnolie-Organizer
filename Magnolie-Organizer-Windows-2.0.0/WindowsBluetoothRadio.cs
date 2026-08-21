using Windows.Devices.Radios;

namespace MagnolieOrganizer.Windows;

/// <summary>
/// Das echte Funkgerät über die WinRT-Radio-Schnittstelle.
///
/// Getrennt von <see cref="BluetoothRadioSwitch"/>, weil diese Datei WinRT
/// benötigt und deshalb nicht im Testprojekt übersetzt werden kann.
/// </summary>
internal sealed class WindowsBluetoothRadio : IBluetoothRadio
{
    public async Task<bool?> IsOnAsync()
    {
        var radio = await FindAsync().ConfigureAwait(false);
        return radio is null ? null : radio.State == RadioState.On;
    }

    public async Task<bool> SetAsync(bool on)
    {
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
            /* Ohne erteilten Zugriff meldet Windows keine Funkgeräte; das ist
               kein Fehlerfall, sondern schlicht „nicht möglich“. Dieselbe
               Abfrage stellt bereits TelefonBluetoothTransport. */
            if (await Radio.RequestAccessAsync() != RadioAccessStatus.Allowed) return null;
            return (await Radio.GetRadiosAsync()).FirstOrDefault(item => item.Kind == RadioKind.Bluetooth);
        }
        catch (Exception error) when (error is InvalidOperationException or UnauthorizedAccessException
                                          or System.Runtime.InteropServices.COMException)
        { return null; }
    }
}
