using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.Rfcomm;
using Windows.Devices.Enumeration;
using Windows.Devices.Radios;
using Windows.Networking.Sockets;
using Windows.Storage.Streams;

namespace MagnolieOrganizer.Windows;

internal sealed record TelefonBluetoothDevice(string Address, string Name);

/// <summary>
/// Veröffentlicht das Magnolie-Telefonprotokoll zusätzlich als
/// Bluetooth-RFCOMM-Dienst und reicht eingehende Verbindungen unverändert an
/// dieselbe Rahmenverarbeitung wie WLAN weiter.
///
/// Der Dienst wird nur veröffentlicht, wenn Windows ein eingeschaltetes
/// Bluetooth-Funkgerät meldet und den Zugriff erlaubt. Der Linkschutz bleibt
/// bewusst bei „verschlüsselt ohne Authentifizierung“: Vertraulichkeit und
/// Echtheit stellt ausschließlich die X25519-Sitzung des Telefonprotokolls
/// her, die über RFCOMM genau dieselben Rahmen überträgt wie über TCP.
/// </summary>
internal sealed class TelefonBluetoothTransport : IDisposable
{
    private const uint ServiceNameAttribute = 0x0100;
    private const byte ServiceNameAttributeType = 4 << 3 | 5;
    private const string ServiceName = "Magnolie Organizer";

    private readonly Guid serviceId;
    private readonly Func<Stream, CancellationToken, Task> handler;
    private readonly CancellationTokenSource lifetime = new();
    private readonly object gate = new();
    private RfcommServiceProvider? provider;
    private StreamSocketListener? listener;
    private bool starting;
    private bool disposed;

    internal TelefonBluetoothTransport(Guid serviceId, Func<Stream, CancellationToken, Task> handler)
    { this.serviceId = serviceId; this.handler = handler; }

    /// <summary>
    /// Startet die Veröffentlichung. <c>Reason</c> ist <c>available</c>, wenn der
    /// Dienst läuft; sonst nennt es den Grund aus dem Vertrag und
    /// <c>Message</c> den Klartext für die Oberfläche.
    /// </summary>
    internal async Task<(string Reason, string Message)> StartAsync()
    {
        lock (gate)
        {
            if (disposed) return ("disabled", TelefonBluetoothSupport.DefaultBlocker);
            if (provider is not null) return ("available", "");
            if (starting) return ("disabled", "Der Bluetooth-Dienst wird bereits gestartet.");
            starting = true;
        }
        RfcommServiceProvider? created = null;
        StreamSocketListener? socketListener = null;
        try
        {
            var access = await Radio.RequestAccessAsync();
            if (access != RadioAccessStatus.Allowed)
                return ("permission_missing",
                    "Windows verweigert dieser Anwendung den Zugriff auf das Bluetooth-Funkgerät. " +
                    "Erlauben Sie ihn in den Windows-Einstellungen unter Datenschutz und Sicherheit.");
            var radios = await Radio.GetRadiosAsync();
            var radio = radios.FirstOrDefault(item => item.Kind == RadioKind.Bluetooth);
            if (radio is null) return ("no_hardware", "Dieser Rechner meldet kein Bluetooth-Funkgerät.");
            if (radio.State != RadioState.On) return ("disabled", "Das Bluetooth-Funkgerät ist ausgeschaltet.");

            created = await RfcommServiceProvider.CreateAsync(RfcommServiceId.FromUuid(serviceId));
            socketListener = new StreamSocketListener();
            socketListener.ConnectionReceived += OnConnectionReceived;
            await socketListener.BindServiceNameAsync(created.ServiceId.AsString(),
                SocketProtectionLevel.BluetoothEncryptionAllowNullAuthentication);
            WriteServiceName(created);
            created.StartAdvertising(socketListener, true);
            lock (gate)
            {
                if (disposed) return ("disabled", TelefonBluetoothSupport.DefaultBlocker);
                provider = created; listener = socketListener; created = null; socketListener = null;
            }
            return ("available", "");
        }
        catch (Exception error) when (error is System.Runtime.InteropServices.COMException or
                                          UnauthorizedAccessException or InvalidOperationException or
                                          PlatformNotSupportedException or NotSupportedException or
                                          ObjectDisposedException or ArgumentException)
        {
            return ("os_restricted", "Der Bluetooth-Dienst konnte nicht veröffentlicht werden: " + error.Message);
        }
        finally
        {
            lock (gate) starting = false;
            try { created?.StopAdvertising(); }
            catch (Exception error) when (error is System.Runtime.InteropServices.COMException or ObjectDisposedException) { }
            try { socketListener?.Dispose(); }
            catch (Exception error) when (error is System.Runtime.InteropServices.COMException or ObjectDisposedException) { }
        }
    }

    internal void Stop()
    {
        RfcommServiceProvider? current; StreamSocketListener? currentListener;
        lock (gate) { current = provider; currentListener = listener; provider = null; listener = null; }
        try { current?.StopAdvertising(); }
        catch (Exception error) when (error is System.Runtime.InteropServices.COMException or ObjectDisposedException) { }
        try { currentListener?.Dispose(); }
        catch (Exception error) when (error is System.Runtime.InteropServices.COMException or ObjectDisposedException) { }
    }

    /// <summary>Die in Windows bereits gekoppelten Bluetooth-Geräte.</summary>
    internal static async Task<IReadOnlyList<TelefonBluetoothDevice>> PairedDevicesAsync()
    {
        var result = new List<TelefonBluetoothDevice>();
        try
        {
            var found = await DeviceInformation.FindAllAsync(BluetoothDevice.GetDeviceSelectorFromPairingState(true));
            foreach (var entry in found)
            {
                BluetoothDevice? device = null;
                try { device = await BluetoothDevice.FromIdAsync(entry.Id); }
                catch (Exception error) when (error is System.Runtime.InteropServices.COMException or ArgumentException) { }
                if (device is null) continue;
                var name = device.Name.Length > 0 ? device.Name : entry.Name;
                result.Add(new TelefonBluetoothDevice(FormatAddress(device.BluetoothAddress), name));
                device.Dispose();
            }
        }
        catch (Exception error) when (error is System.Runtime.InteropServices.COMException or
                                          UnauthorizedAccessException or ArgumentException or
                                          PlatformNotSupportedException)
        { }
        return result;
    }

    internal static string FormatAddress(ulong address)
    {
        var bytes = BitConverter.GetBytes(address);
        return string.Join(':', bytes.Take(6).Reverse().Select(value => value.ToString("X2",
            System.Globalization.CultureInfo.InvariantCulture)));
    }

    private static void WriteServiceName(RfcommServiceProvider target)
    {
        var writer = new DataWriter { UnicodeEncoding = UnicodeEncoding.Utf8 };
        writer.WriteByte(ServiceNameAttributeType);
        writer.WriteByte((byte)ServiceName.Length);
        writer.WriteString(ServiceName);
        target.SdpRawAttributes.Add(ServiceNameAttribute, writer.DetachBuffer());
    }

    private void OnConnectionReceived(StreamSocketListener sender, StreamSocketListenerConnectionReceivedEventArgs args)
    {
        var socket = args.Socket;
        _ = Task.Run(async () =>
        {
            using (socket)
            using (var stream = new TelefonDuplexStream(socket.InputStream.AsStreamForRead(),
                       socket.OutputStream.AsStreamForWrite()))
            {
                try { await handler(stream, lifetime.Token); }
                catch (Exception) { }
            }
        });
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        Stop();
        lifetime.Cancel();
        lifetime.Dispose();
    }
}

/// <summary>
/// Fasst den getrennten Lese- und Schreibstrom eines WinRT-Sockets zu einem
/// beidseitigen Datenstrom zusammen, wie ihn die Rahmenverarbeitung erwartet.
/// </summary>
internal sealed class TelefonDuplexStream : Stream
{
    private readonly Stream read;
    private readonly Stream write;

    internal TelefonDuplexStream(Stream read, Stream write) { this.read = read; this.write = write; }

    public override bool CanRead => true;
    public override bool CanSeek => false;
    public override bool CanWrite => true;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() => write.Flush();
    public override Task FlushAsync(CancellationToken cancellationToken) => write.FlushAsync(cancellationToken);
    public override int Read(byte[] buffer, int offset, int count) => read.Read(buffer, offset, count);
    public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) =>
        read.ReadAsync(buffer, cancellationToken);
    public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        read.ReadAsync(buffer, offset, count, cancellationToken);
    public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
    public override void SetLength(long value) => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count) => write.Write(buffer, offset, count);
    public override ValueTask WriteAsync(ReadOnlyMemory<byte> buffer, CancellationToken cancellationToken = default) =>
        write.WriteAsync(buffer, cancellationToken);
    public override Task WriteAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
        write.WriteAsync(buffer, offset, count, cancellationToken);

    protected override void Dispose(bool disposing)
    {
        if (disposing) { read.Dispose(); write.Dispose(); }
        base.Dispose(disposing);
    }
}
