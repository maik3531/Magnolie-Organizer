using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows;

/// <summary>One native UI-approved Windows mirror. The MainForm owns the
/// independent view and the selected WLAN parent owns the v26 control lease.</summary>
internal sealed class PhoneScreenDesktopSession
{
    private const int Width = 720, Height = 1280, Density = 160;
    private readonly CancellationTokenSource stop = new();
    private readonly TaskCompletionSource drained = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TelefonConnection.ScreenControl control;
    private PhoneScreenWindow? window;

    private PhoneScreenDesktopSession(TelefonConnection.ScreenProbe probe, Action originalCurrent)
    {
        void RequireDesktop()
        {
            originalCurrent();
            if (!PhoneScreenWindow.InteractiveDesktop()) throw new InvalidOperationException("screen_original_desktop_locked");
        }
        control = probe.Parent.BindScreenControl(probe, RequireDesktop, RequestStop);
    }

    internal static PhoneScreenDesktopSession Start(MainForm main, TelefonConnection.ScreenProbe probe, Action originalCurrent)
    {
        var owner = new PhoneScreenDesktopSession(probe, originalCurrent);
        try
        {
            owner.window = main.AttachPhoneScreen(Width, Height, owner.IsCurrent, owner.Stop, owner.drained.Task);
            _ = Task.Run(owner.RunAsync);
            return owner;
        }
        catch
        {
            owner.Stop();
            owner.window?.Stop();
            owner.control.ReleaseAfterDrain();
            owner.drained.TrySetResult();
            throw;
        }
    }

    private bool IsCurrent()
    {
        control.Current();
        return !stop.IsCancellationRequested;
    }

    internal void Stop() => control.Stop();
    private void RequestStop() => stop.Cancel();  // No UI or network wait in the stop callback.

    private async Task RunAsync()
    {
        PhoneScreenReceiveRun? receiver = null;
        byte[]? secret = null;
        try
        {
            var (listener, expectedPeer) = control.OpenListener();
            using (listener)
            {
                var address = (IPEndPoint)listener.LocalEndPoint!;
                secret = RandomNumberGenerator.GetBytes(32);
                await control.OfferAsync(secret, address.Port, Width, Height, Density).ConfigureAwait(false);
                var remaining = TimeSpan.FromSeconds((double)(control.Deadline - Stopwatch.GetTimestamp()) / Stopwatch.Frequency);
                if (remaining <= TimeSpan.Zero) throw new TimeoutException("screen_original_probe_expired");
                await control.Prepared.WaitAsync(remaining, stop.Token).ConfigureAwait(false);
                using var accept = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
                remaining = TimeSpan.FromSeconds((double)(control.Deadline - Stopwatch.GetTimestamp()) / Stopwatch.Frequency);
                if (remaining <= TimeSpan.Zero) throw new TimeoutException("screen_original_probe_expired");
                accept.CancelAfter(remaining < TimeSpan.FromSeconds(5) ? remaining : TimeSpan.FromSeconds(5));
                Socket accepted = await listener.AcceptAsync(accept.Token).ConfigureAwait(false);
                try
                {
                    control.Current();
                    if (accepted.RemoteEndPoint is not IPEndPoint remote || !remote.Address.Equals(expectedPeer) ||
                        !Equals(accepted.LocalEndPoint, address)) throw new UnauthorizedAccessException("screen_data_peer_changed");
                    receiver = new PhoneScreenReceiveRun(accepted, control.SessionId, secret, Width, Height,
                        control.Current, control.RequireSend, control.SendAsync, window!.OfferJpeg, Stop);
                }
                catch { accepted.Dispose(); throw; }
            }
            CryptographicOperations.ZeroMemory(secret);
            using var interrupt = stop.Token.Register(receiver.Stop);
            if (!stop.IsCancellationRequested) receiver.Start();
            await receiver.Drained.ConfigureAwait(false);
        }
        catch (Exception) { /* This view terminates independently of the paired control connection. */ }
        finally
        {
            Stop();
            if (secret is not null) CryptographicOperations.ZeroMemory(secret);
            try { await control.StopPeerAsync().ConfigureAwait(false); }
            catch (Exception) { /* Parent may be gone; the original data socket is closed independently. */ }
            try
            {
                if (receiver is not null)
                {
                    receiver.Stop();
                    await receiver.Drained.ConfigureAwait(false);
                }
                control.ReleaseAfterDrain();
                drained.TrySetResult();
            }
            catch (Exception error) { drained.TrySetException(error); }
        }
    }
}
