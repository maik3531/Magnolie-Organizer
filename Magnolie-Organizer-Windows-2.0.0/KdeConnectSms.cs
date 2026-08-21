using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

internal sealed class KdeConnectSms : IDisposable
{
    private readonly KdeConnectDirectBackend native;

    internal KdeConnectSms(WindowsPaths paths) => native = new KdeConnectDirectBackend(paths);

    internal event Action<KdeConnectStatus>? StatusChanged
    { add => native.StatusChanged += value; remove => native.StatusChanged -= value; }
    internal event Action<KdeConnectSmsReceived>? SmsReceived
    { add => native.SmsReceived += value; remove => native.SmsReceived -= value; }
    internal event Action<KdeConnectSendResult>? SendCompleted
    { add => native.SendCompleted += value; remove => native.SendCompleted -= value; }
    internal event Action<KdeConnectPairingEvent>? PairingChanged
    { add => native.PairingChanged += value; remove => native.PairingChanged -= value; }

    internal Task<KdeConnectStatus> DirectStatusAsync(CancellationToken cancellationToken = default) =>
        native.GetStatusAsync(cancellationToken);

    internal async Task<object> StatusAsync()
    {
        var direct = await native.StatusAsync();
        if (native.HasPairedPeers)
            return new { available = direct.Available, deviceCount = direct.DeviceCount, reason = direct.Reason, backend = "native" };
        var executable = FindExecutable();
        if (executable is null) return new { available = false, deviceCount = 0, reason = "not_installed" };
        var result = await RunAsync(executable, ["--list-available", "--id-only"], TimeSpan.FromSeconds(3));
        if (result.ExitCode != 0) return new { available = false, deviceCount = 0, reason = "command_failed" };
        var devices = result.Output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Select(value => value.Trim()).Where(value => value.Length is >= 4 and <= 200 &&
                value.All(character => char.IsLetterOrDigit(character) || "._:-".Contains(character)))
            .Distinct(StringComparer.Ordinal).ToArray();
        return new { available = devices.Length == 1, deviceCount = devices.Length,
            reason = devices.Length == 1 ? "" : devices.Length == 0 ? "no_device" : "multiple_devices" };
    }

    internal async Task SendAsync(string number, string text, string country)
    {
        var normalizedText = KdeConnectProtocol.NormalizeSmsText(text);
        if (string.IsNullOrWhiteSpace(normalizedText.Text) || normalizedText.Text.Length > 5000 ||
            normalizedText.Segments > KdeConnectProtocol.MaxSmsSegments)
            throw new InvalidOperationException("SMS-Nachricht ist ungültig oder länger als zehn Segmente.");
        var direct = await native.StatusAsync();
        if (native.HasPairedPeers)
        {
            await native.SendSmsAsync(number, normalizedText.Text, country);
            return;
        }
        var executable = FindExecutable() ?? throw new InvalidOperationException("KDE Connect ist nicht installiert.");
        var normalized = PhoneUri.Normalize(number, country);
        if (normalized.Length == 0)
            throw new InvalidOperationException("SMS-Empfänger oder Nachricht ist ungültig.");
        var discovery = await RunAsync(executable, ["--list-available", "--id-only"], TimeSpan.FromSeconds(3));
        var devices = discovery.Output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Select(value => value.Trim()).Where(value => value.Length is >= 4 and <= 200 &&
                value.All(character => char.IsLetterOrDigit(character) || "._:-".Contains(character)))
            .Distinct(StringComparer.Ordinal).ToArray();
        if (discovery.ExitCode != 0 || devices.Length != 1)
            throw new InvalidOperationException("Genau ein erreichbares KDE-Connect-Telefon ist erforderlich.");
        var result = await RunAsync(executable, ["--device", devices[0], "--send-sms", normalizedText.Text,
            "--destination", normalized], TimeSpan.FromSeconds(15));
        if (result.ExitCode != 0) throw new InvalidOperationException("KDE Connect hat die SMS nicht angenommen.");
    }

    internal Task<KdeConnectSendResult> SendWithResultAsync(string number, string text, string country,
        CancellationToken cancellationToken = default) =>
        native.SendSmsWithResultAsync(number, text, country, cancellationToken);

    internal Task<KdeConnectPairing> StartPairingAsync() => native.BeginPairingAsync();
    internal Task ConfirmPairingAsync(string deviceId, bool accept) => native.ConfirmPairingAsync(deviceId, accept);
    internal void Remove(string deviceId) => native.Remove(deviceId);
    public void Dispose() => native.Dispose();

    private static string? FindExecutable()
    {
        var names = new[] { "kdeconnect-cli.exe", "kdeconnect-cli" };
        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            foreach (var name in names)
            {
                var path = Path.Combine(directory.Trim(), name);
                if (File.Exists(path)) return path;
            }
        return null;
    }

    private static async Task<(int ExitCode, string Output)> RunAsync(string executable,
        IReadOnlyList<string> arguments, TimeSpan timeout)
    {
        using var process = new Process { StartInfo = new ProcessStartInfo {
            FileName = executable, UseShellExecute = false, RedirectStandardOutput = true,
            RedirectStandardError = true, CreateNoWindow = true } };
        foreach (var argument in arguments) process.StartInfo.ArgumentList.Add(argument);
        process.Start();
        var output = process.StandardOutput.ReadToEndAsync();
        using var cancellation = new CancellationTokenSource(timeout);
        try { await process.WaitForExitAsync(cancellation.Token); }
        catch (OperationCanceledException) { try { process.Kill(true); } catch { } throw new TimeoutException(); }
        return (process.ExitCode, await output);
    }
}
