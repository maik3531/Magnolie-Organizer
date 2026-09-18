using Microsoft.Win32;

namespace MagnolieOrganizer.Windows;

internal interface IPhoneStartupPlatform
{
    TraySettings Load();
    void Save(TraySettings settings);
    object? CaptureAutostart();
    void EnableAutostart();
    void RestoreAutostart(object? snapshot);
}

internal sealed class NativePhoneStartupPlatform(WindowsPaths paths) : IPhoneStartupPlatform
{
    private readonly TraySettingsService tray = new(paths.TraySettings);
    public TraySettings Load()
    {
        var settings = tray.Load();
        if (tray.LoadFailed) throw new IOException(NativeLocalization.Gettext("The background settings could not be saved."));
        return settings;
    }
    public void Save(TraySettings settings) => tray.Save(settings);
    public object? CaptureAutostart() => TraySettingsService.CaptureAutostart();
    public void EnableAutostart()
    {
        var error = TraySettingsService.ConfigureAutostart(true, Environment.ProcessPath ?? throw new IOException());
        if (error.Length > 0) throw new IOException(error);
    }
    public void RestoreAutostart(object? snapshot) => TraySettingsService.RestoreAutostart((TrayAutostartEntry?)snapshot);
}

internal static class FirstRunPhoneStartup
{
    internal static void Apply(IReadOnlyList<string> transports, TelefonStore? phone, IPhoneStartupPlatform platform,
        bool connectedPhone = false)
    {
        if (transports.Distinct(StringComparer.Ordinal).Count() != transports.Count || transports.Any(t => t is not ("wifi" or "bluetooth" or "kdeconnect")))
            throw new ArgumentException("Invalid phone startup services.");
        var needsPhone = connectedPhone || transports.Any(t => t is "wifi" or "bluetooth");
        if (needsPhone && phone is null) throw new InvalidOperationException();
        // Connection consent survives an app restart; background launch is a separate opt-in.
        if (transports.Count == 0)
        {
            if (needsPhone) phone!.Enabled = true;
            return;
        }
        var previous = platform.Load();
        var registration = platform.CaptureAutostart();
        var previousPhone = needsPhone ? phone!.ReadEnabledStrict() : false;
        var phoneAttempted = false;
        try
        {
            platform.Save(previous with { Aktiv = true, Autostart = true, StartMinimiert = true });
            // Preserve a pre-existing approved reminder/tray command verbatim.
            if (!previous.Autostart || registration is null) platform.EnableAutostart();
            if (needsPhone) { phoneAttempted = true; phone!.Enabled = true; }
            if (platform.Load() != (previous with { Aktiv = true, Autostart = true, StartMinimiert = true }) ||
                platform.CaptureAutostart() is null || needsPhone && !phone!.ReadEnabledStrict())
                throw new IOException(NativeLocalization.Gettext("The background settings could not be saved."));
        }
        catch (Exception failure)
        {
            var errors = new List<Exception> { failure };
            try { if (phoneAttempted) phone!.Enabled = previousPhone; } catch (Exception error) { errors.Add(error); }
            try { platform.RestoreAutostart(registration); } catch (Exception error) { errors.Add(error); }
            try { platform.Save(previous); } catch (Exception error) { errors.Add(error); }
            if (errors.Count > 1) throw new AggregateException(NativeLocalization.Gettext("The background settings could not be saved."), errors);
            throw;
        }
    }
}

internal sealed record TrayAutostartEntry(object Value, RegistryValueKind Kind);

internal static class FirstRunPhoneFinish
{
    internal static async Task<FirstRunSetupSelections> CompleteAsync(FirstRunSetupState state, FirstRunSetupSelections selections,
        bool skipped, IFirstRunSetupPhoneServices? phones, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        if (skipped)
        {
            selections = selections with { PhoneBackgroundServices = [], ForegroundPhoneTransports = [], Autostart = false, Tray = false };
            state.Complete(selections, true);
            return selections;
        }
        IReadOnlyList<string> live;
        try { live = phones is null ? Array.Empty<string>() : await phones.ConnectedAsync(cancellation); }
        catch (Exception error) when (selections.PhoneBackgroundServices.Count == 0 &&
            !cancellation.IsCancellationRequested &&
            error is IOException or InvalidOperationException or UnauthorizedAccessException or TimeoutException)
        {
            // An unavailable optional phone must not prevent the organizer from starting.
            live = Array.Empty<string>();
        }
        if (selections.PhoneBackgroundServices.Any(t => !live.Contains(t)))
            throw new InvalidOperationException(NativeLocalization.Gettext("The phone is no longer connected."));
        selections = selections with { ForegroundPhoneTransports = live.Where(t => t is "wifi" or "bluetooth").ToArray() };
        cancellation.ThrowIfCancellationRequested();
        state.Complete(selections, false);
        try
        {
            if (phones is not null && (live.Count > 0 || selections.PhoneBackgroundServices.Count > 0))
                await phones.CommitStartupAsync(selections.PhoneBackgroundServices, cancellation);
            return selections;
        }
        catch { state.Begin(); throw; }
    }
}
