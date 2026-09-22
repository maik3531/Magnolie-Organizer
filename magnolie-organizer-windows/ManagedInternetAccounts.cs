using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Runtime.InteropServices;
using System.Globalization;

namespace MagnolieOrganizer.Windows;

internal static class ManagedInternetAccounts
{
    internal static string Profile => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Magnolie Internet Accounts", "profile");
    internal static string Runtime => Path.Combine(AppContext.BaseDirectory, "account-runtime");
    internal static bool Enabled => File.Exists(Path.Combine(Profile, "magnolie-managed.json"));
    private static readonly SemaphoreSlim StartGate = new(1, 1);
    private static Process? ownedProcess;

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(nint window, out uint process);
    [DllImport("user32.dll")]
    private static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(nint window);

    internal static int MailWindows(JsonObject environment, bool hide)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var pid = environment["pid"]!.GetValue<int>();
        var visible = 0;
        foreach (var item in environment["mailWindows"]?.AsArray() ?? [])
        {
            var text = item!.GetValue<string>();
            if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) text = text[2..];
            if (!long.TryParse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var value)) throw new InvalidDataException();
            var window = (nint)value;
            GetWindowThreadProcessId(window, out var owner);
            if (owner != pid) throw new InvalidDataException("Mail window does not belong to the account helper.");
            if (hide) ShowWindow(window, 0);
            if (IsWindowVisible(window)) visible++;
        }
        return visible;
    }

    internal static void PrepareProfile(string profile, string runtime, string bridgeXpi, string language)
    {
        var marker = Path.Combine(profile, "magnolie-managed.json");
        if (Directory.Exists(profile) && !File.Exists(marker))
            throw new InvalidDataException("Refusing to reconfigure a profile not owned by Magnolie.");
        if (File.Exists(marker) && JsonNode.Parse(File.ReadAllText(marker))?["schema"]?.GetValue<int>() != 1)
            throw new InvalidDataException("Unknown account profile format.");
        foreach (var file in new[] { "thunderbird.exe", "runtime.json",
            "magnolie-extensions/tbsync@jobisoft.de.xpi", "magnolie-extensions/eas4tbsync@jobisoft.de.xpi" })
            if (!File.Exists(Path.Combine(runtime, file))) throw new FileNotFoundException("The packaged account helper is incomplete.");
        if (Directory.Exists(profile) && (File.GetAttributes(profile) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Account profiles cannot be filesystem links.");
        Directory.CreateDirectory(profile);
        // Mark the newly owned directory before staging dependencies so an
        // interrupted first setup can safely resume without touching other profiles.
        new AtomicStore().Write(marker, "{\"schema\":1}");
        var extensions = Path.Combine(profile, "extensions");
        Directory.CreateDirectory(extensions);
        if ((File.GetAttributes(extensions) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException();
        foreach (var id in new[] { "tbsync@jobisoft.de", "eas4tbsync@jobisoft.de" })
            File.Copy(Path.Combine(runtime, "magnolie-extensions", id + ".xpi"), Path.Combine(extensions, id + ".xpi"), true);
        File.Copy(bridgeXpi, Path.Combine(extensions, ThunderbirdBridge.ExtensionId + ".xpi"), true);
        var preferences = new Dictionary<string, object>
        {
            ["extensions.magnolie.managed"] = true,
            ["extensions.autoDisableScopes"] = 0, ["extensions.enabledScopes"] = 15,
            ["extensions.startupScanScopes"] = 15, ["extensions.sideloadScopes"] = 15,
            ["extensions.update.enabled"] = false, ["app.update.auto"] = false,
            ["app.update.background.enabled"] = false, ["app.update.service.enabled"] = false,
            ["mail.provider.enabled"] = false, ["mail.provider.suppress_dialog_on_startup"] = true,
            ["mail.shell.checkDefaultClient"] = false, ["mailnews.start_page.enabled"] = false,
            ["toolkit.telemetry.enabled"] = false,
            ["intl.locale.requested"] = language, ["intl.accept_languages"] = language,
            ["mail.accountmanager.accounts"] = "account1", ["mail.accountmanager.localfoldersserver"] = "server1",
            ["mail.account.account1.server"] = "server1", ["mail.server.server1.type"] = "none",
            ["mail.server.server1.hostname"] = "Local Folders", ["mail.server.server1.userName"] = "nobody",
            ["mail.server.server1.name"] = "Magnolie"
        };
        new AtomicStore().Write(Path.Combine(profile, "user.js"), string.Join("\n", preferences.Select(item =>
            $"user_pref({JsonSerializer.Serialize(item.Key)}, {JsonSerializer.Serialize(item.Value)});")) + "\n");
    }

    internal static async Task EnsureStartedAsync(CancellationToken token, string? profile = null,
        string? runtime = null, string? nativeExecutable = null, Action<string>? diagnostics = null)
    {
        await StartGate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            profile ??= Profile; runtime ??= Runtime;
            try
            {
                var running = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, token, 500, managed: true);
                if (running["managed"]?.GetValue<bool>() == true && running["ready"]?.GetValue<bool>() == true &&
                    string.Equals(Path.GetFullPath(running["profile"]!.GetValue<string>()), Path.GetFullPath(profile), StringComparison.OrdinalIgnoreCase))
                {
                    ownedProcess ??= Process.GetProcessById(running["pid"]!.GetValue<int>());
                    MailWindows(running, hide: true);
                    return;
                }
                throw new InvalidDataException("Unexpected account helper identity.");
            }
            catch (Exception error) when (error is IOException or TimeoutException) { }
            var xpi = ThunderbirdBridge.InstallHost(managed: true, nativeExecutable);
            PrepareProfile(profile, runtime, xpi, System.Globalization.CultureInfo.CurrentUICulture.Name);
            var start = new ProcessStartInfo(Path.Combine(runtime, "thunderbird.exe"))
            { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true, RedirectStandardError = true };
            // The managed extension keeps the normal startup window hidden;
            // provider authentication popups remain visible to the user.
            foreach (var value in new[] { "-no-remote", "-purgecaches", "-profile", profile }) start.ArgumentList.Add(value);
            if (diagnostics is not null) start.Environment["MAGNOLIE_ACCOUNT_PROBE_TRACE"] = profile;
            ownedProcess = Process.Start(start) ?? throw new IOException("Could not start account helper.");
            if (diagnostics is not null) ownedProcess.ErrorDataReceived += (_, data) =>
            {
                if (data.Data?.StartsWith("JavaScript error:", StringComparison.Ordinal) == true ||
                    data.Data?.Contains("tbsync", StringComparison.OrdinalIgnoreCase) == true) diagnostics(data.Data!);
            };
            // The account runtime must not inherit the caller's console pipes.
            // Its provider diagnostics may contain account identifiers, so do
            // not relay them into the organizer log or the parent process.
            ownedProcess.BeginOutputReadLine(); ownedProcess.BeginErrorReadLine();
            using var startup = CancellationTokenSource.CreateLinkedTokenSource(token);
            startup.CancelAfter(TimeSpan.FromSeconds(45));
            string? previousReadiness = null;
            while (true)
            {
                startup.Token.ThrowIfCancellationRequested();
                // Mozilla's Windows launcher may successfully hand off to a
                // child process and exit before extension startup completes.
                if (ownedProcess.HasExited && ownedProcess.ExitCode != 0)
                    throw new IOException($"The account helper exited before it was ready (0x{ownedProcess.ExitCode:X8}).");
                try
                {
                    var ready = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, startup.Token, 500, managed: true);
                    var readiness = $"managed={ready["managed"]}, provider={ready["providerReady"]}";
                    if (readiness != previousReadiness) { diagnostics?.Invoke(readiness); previousReadiness = readiness; }
                    if (ready["managed"]?.GetValue<bool>() != true ||
                        !string.Equals(Path.GetFullPath(ready["profile"]!.GetValue<string>()), Path.GetFullPath(profile), StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException();
                    var runtimePid = ready["pid"]!.GetValue<int>();
                    if (runtimePid != ownedProcess.Id) { ownedProcess.Dispose(); ownedProcess = Process.GetProcessById(runtimePid); }
                    MailWindows(ready, hide: true);
                    if (ready["ready"]?.GetValue<bool>() != true) { await Task.Delay(300, startup.Token).ConfigureAwait(false); continue; }
                    return;
                }
                catch (Exception error) when (error is IOException or TimeoutException)
                { await Task.Delay(300, startup.Token).ConfigureAwait(false); }
            }
        }
        finally { StartGate.Release(); }
    }

    internal static async Task BeginSignInAsync(string provider, string email, CancellationToken token)
    {
        if (provider is not ("google" or "personal-ms" or "office365")) throw new ArgumentException();
        if (email.Length > 254 || email.Any(char.IsControl) || !email.Contains('@')) throw new ArgumentException();
        await EnsureStartedAsync(token).ConfigureAwait(false);
        await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "login", ["provider"] = provider, ["email"] = email },
            token, managed: true).ConfigureAwait(false);
    }

    internal static async Task StopAsync()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        try
        {
            if (ownedProcess is null)
            {
                if (!Enabled) return;
                var running = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, deadline.Token, 500, managed: true);
                if (running["managed"]?.GetValue<bool>() != true ||
                    !string.Equals(Path.GetFullPath(running["profile"]!.GetValue<string>()), Path.GetFullPath(Profile), StringComparison.OrdinalIgnoreCase)) return;
                ownedProcess = Process.GetProcessById(running["pid"]!.GetValue<int>());
            }
            await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "shutdown" }, deadline.Token, 500, managed: true);
            await ownedProcess.WaitForExitAsync(deadline.Token);
        }
        catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException or ArgumentException) { }
        finally { ownedProcess?.Dispose(); ownedProcess = null; }
    }
}
