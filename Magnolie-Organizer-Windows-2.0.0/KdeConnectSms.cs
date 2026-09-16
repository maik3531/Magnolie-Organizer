using System.Diagnostics;

namespace MagnolieOrganizer.Windows;

internal sealed class KdeConnectSms : IDisposable
{
    private readonly Lazy<KdeConnectDirectBackend> backend;
    private KdeConnectDirectBackend native => backend.Value;
    private readonly SmsSubmissionJournal submissions;

    internal KdeConnectSms(WindowsPaths paths)
    {
        backend = new(() => new KdeConnectDirectBackend(paths));
        submissions = new(Path.Combine(paths.KdeConnect, "sms-submissions.json"));
    }

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

    internal async Task<KdeConnectSendResult> SendWithResultAsync(string number, string text, string country,
        string clientRef, string expectedDeviceId, string expectedFingerprint, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrEmpty(expectedDeviceId) || string.IsNullOrEmpty(expectedFingerprint))
            return new(false, "failed", "", "no_unique_device");
        var previous = submissions.Reserve(clientRef, number, text, country, expectedDeviceId, expectedFingerprint);
        if (previous is not null) return new(previous == "submitted", previous, "", previous == "uncertain" ? "uncertain" : null);
        try
        {
            var result = await native.SendSmsWithResultAsync(number, text, country, expectedDeviceId, expectedFingerprint, cancellationToken);
            if (result.Ok) submissions.Submitted(clientRef);
            return result;
        }
        catch { return new(false, "uncertain", "", "uncertain"); }
    }

    internal Task<KdeConnectPairing> StartPairingAsync() => native.BeginPairingAsync();
    internal Task ConfirmPairingAsync(string deviceId, bool accept) => native.ConfirmPairingAsync(deviceId, accept);
    internal void Remove(string deviceId) => native.Remove(deviceId);
    public void Dispose() { if (backend.IsValueCreated) backend.Value.Dispose(); }

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
