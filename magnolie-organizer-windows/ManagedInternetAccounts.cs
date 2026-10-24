using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Runtime.InteropServices;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

internal sealed record ManagedAccountState(JsonObject Raw, JsonObject Public, string Revision);
internal sealed record ManagedAccountReceipt(ManagedAccountState State, bool Accepted, bool Verified);

// One GUI/MCP lane around the existing managed-runtime account operations.
internal sealed class ManagedAccountOperations
{
    private readonly SemaphoreSlim gate = new(1, 1);
    private readonly Func<bool> enabled;
    private readonly Func<CancellationToken, Task> ensure;
    private readonly Func<JsonObject, CancellationToken, Task<JsonObject>> call;
    private readonly Func<string, string, CancellationToken, Task> begin;
    private readonly Func<bool> permitted;
    internal ManagedAccountOperations(Func<bool>? permitted = null) : this(() => ManagedInternetAccounts.Enabled,
        token => ManagedInternetAccounts.EnsureStartedAsync(token),
        (request, token) => ThunderbirdBridge.CallAsync(request, token, managed: true), ManagedInternetAccounts.BeginSignInAsync, permitted) { }
    internal ManagedAccountOperations(Func<bool> enabled, Func<CancellationToken, Task> ensure,
        Func<JsonObject, CancellationToken, Task<JsonObject>> call, Func<string, string, CancellationToken, Task> begin, Func<bool>? permitted = null)
    { this.enabled = enabled; this.ensure = ensure; this.call = call; this.begin = begin; this.permitted = permitted ?? (() => true); }

    internal async Task<ManagedAccountReceipt> ExecuteAsync(string action, string provider, string account, string email, string name,
        string? expectedRevision, CancellationToken token)
    {
        if (action is not ("read" or "sign_in" or "rename" or "remove" or "edit")) throw new InvalidDataException();
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            var before = await ReadAsync(token).ConfigureAwait(false);
            if (expectedRevision is not null && expectedRevision != before.Revision) throw new InvalidOperationException("conflict");
            if (action == "read") return new(before, false, false);
            if (before.Public["google_pending"]!.GetValue<bool>() || before.Public["microsoft_pending"]!.GetValue<bool>()) throw new InvalidOperationException("native_busy");
            token.ThrowIfCancellationRequested();
            if (!permitted()) throw new OperationCanceledException(token);
            if (action == "sign_in")
            {
                if (provider is not ("google" or "personal-ms" or "office365") || email.Length > 254 || email.Any(char.IsControl) || !email.Contains('@')) throw new InvalidDataException();
                await begin(provider, email, token).ConfigureAwait(false);
            }
            else
            {
                if (provider is not ("google" or "microsoft") || account.Length is < 1 or > 254 ||
                    action == "rename" && (string.IsNullOrWhiteSpace(name) || name.Length > 254)) throw new InvalidDataException();
                if (!before.Public["accounts"]!.AsArray().OfType<JsonObject>().Any(item =>
                    item["provider"]!.GetValue<string>() == provider && item["id"]!.GetValue<string>() == account)) throw new InvalidOperationException("not_found");
                await ensure(token).ConfigureAwait(false);
                token.ThrowIfCancellationRequested();
                if (!permitted()) throw new OperationCanceledException(token);
                await call(new() { ["op"] = "manage-account", ["provider"] = provider, ["action"] = action, ["accountId"] = account, ["name"] = name }, token).ConfigureAwait(false);
            }
            var after = await ReadAsync(token).ConfigureAwait(false);
            var verified = false;
            if (action is "rename" or "remove")
            {
                if (after.Public["ready"]!.GetValue<bool>() != true) throw new InvalidDataException();
                var target = after.Public["accounts"]!.AsArray().OfType<JsonObject>().SingleOrDefault(item =>
                    item["provider"]!.GetValue<string>() == provider && item["id"]!.GetValue<string>() == account);
                verified = action == "remove" ? target is null : target?["name"]?.GetValue<string>() == name;
                if (!verified) throw new InvalidDataException("The account change could not be verified.");
            }
            return new(after, true, verified);
        }
        finally { gate.Release(); }
    }

    private async Task<ManagedAccountState> ReadAsync(CancellationToken token)
    {
        JsonObject raw;
        if (!enabled()) raw = new() { ["bereit"] = false };
        else
        {
            await ensure(token).ConfigureAwait(false);
            raw = await call(new() { ["op"] = "status" }, token).ConfigureAwait(false);
            raw["bereit"] = true;
        }
        return Project(raw);
    }
    internal static ManagedAccountState Project(JsonObject raw)
    {
        static bool Error(JsonNode? node) => node is not null && node.ToJsonString() is not ("null" or "false" or "0" or "\"\"");
        static string Text(JsonNode? node) { var value = node?.GetValue<string>() ?? ""; return value.Length <= 254 ? value : throw new InvalidDataException(); }
        var ready = raw["bereit"]?.GetValue<bool>() == true;
        var accounts = new List<JsonObject>();
        if (ready)
        {
            var google = raw["google"]?["accounts"]?.AsArray() ?? throw new InvalidDataException();
            var microsoft = raw["microsoft"]?["accounts"]?.AsArray() ?? throw new InvalidDataException();
            if (google.Count + microsoft.Count > 1000) throw new InvalidDataException();
            foreach (var item in google)
            {
                var id = Text(item);
                var detail = raw["google"]?["details"]?.AsArray().OfType<JsonObject>().FirstOrDefault(value => Text(value["id"]) == id);
                accounts.Add(new() { ["provider"] = "google", ["id"] = id, ["name"] = Text(detail?["name"]) is { Length: > 0 } name ? name : id,
                    ["enabled"] = detail?["enabled"]?.GetValue<bool>() != false, ["error_present"] = Error(detail?["error"]) });
            }
            foreach (var node in microsoft)
            {
                var item = node as JsonObject ?? throw new InvalidDataException();
                accounts.Add(new() { ["provider"] = "microsoft", ["id"] = Text(item["id"]), ["name"] = Text(item["name"]),
                    ["enabled"] = item["enabled"]?.GetValue<bool>() == true, ["error_present"] = Error(item["error"]) });
            }
        }
        if (accounts.Count > 1000 || accounts.Any(item => item["id"]!.GetValue<string>().Length == 0) ||
            accounts.Select(item => (item["provider"]!.GetValue<string>(), item["id"]!.GetValue<string>())).Distinct().Count() != accounts.Count) throw new InvalidDataException();
        var content = new JsonObject { ["ready"] = ready, ["google_pending"] = raw["google"]?["pending"]?.GetValue<bool>() == true,
            ["microsoft_pending"] = raw["microsoft"]?["login"]?["pending"]?.GetValue<bool>() == true,
            ["error_present"] = Error(raw["google"]?["error"]) || Error(raw["microsoft"]?["login"]?["error"]),
            ["google_tasks_available"] = JsonValue.Create(raw["google"]?["tasks"]?["available"]?.GetValue<bool>()),
            ["microsoft_tasks_available"] = JsonValue.Create(raw["microsoft"]?["tasks"]?["available"]?.GetValue<bool>()),
            ["accounts"] = new JsonArray(accounts.OrderBy(item => item["provider"]!.GetValue<string>(), StringComparer.Ordinal)
                .ThenBy(item => item["id"]!.GetValue<string>(), StringComparer.Ordinal).Select(item => (JsonNode)item).ToArray()) };
        return new(raw, content, Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content.ToJsonString()))).ToLowerInvariant());
    }
}

internal static class ManagedInternetAccounts
{
    internal static string Profile => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Magnolie Internet Accounts", "profile");
    internal static string Runtime => Path.Combine(AppContext.BaseDirectory, "account-runtime");
    internal static bool Enabled => File.Exists(Path.Combine(Profile, "magnolie-managed.json"));
    private static readonly SemaphoreSlim StartGate = new(1, 1);
    private static Process? ownedProcess;
    private static string? ownedProfile;
    private static string? failedProfile;
    private static DateTimeOffset nextStartAttempt;

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
            // Thunderbird also opens its integration dialog for Windows Search's
            // first run, independently of the default-mail-client preference.
            ["mail.winsearch.firstRunDone"] = true, ["mail.winsearch.enable"] = false,
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
        string? attemptedProfile = null;
        try
        {
            var explicitRuntime = runtime is not null;
            profile = Path.GetFullPath(profile ?? Profile); runtime = Path.GetFullPath(runtime ?? Runtime);
            try
            {
                var running = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, token, 500, managed: true);
                if (running["managed"]?.GetValue<bool>() == true && running["ready"]?.GetValue<bool>() == true &&
                    string.Equals(Path.GetFullPath(running["profile"]!.GetValue<string>()), Path.GetFullPath(profile), StringComparison.OrdinalIgnoreCase))
                {
                    var currentPid = running["pid"]!.GetValue<int>();
                    if (ownedProcess is null || ownedProcess.Id != currentPid)
                    { ownedProcess?.Dispose(); ownedProcess = Process.GetProcessById(currentPid); }
                    ownedProfile = profile;
                    MailWindows(running, hide: true);
                    failedProfile = null;
                    return;
                }
                throw new InvalidDataException("Unexpected account helper identity.");
            }
            catch (Exception error) when (error is IOException or TimeoutException) { }
            if (ownedProcess is not null && !ownedProcess.HasExited && string.Equals(ownedProfile, profile, StringComparison.OrdinalIgnoreCase))
                throw new IOException("The owned account helper is still starting or unavailable; a duplicate helper will not be launched.");
            if (string.Equals(failedProfile, profile, StringComparison.OrdinalIgnoreCase) && DateTimeOffset.UtcNow < nextStartAttempt)
                throw new IOException("The account helper could not start; a retry is temporarily deferred.");
            var selected = await ManagedAccountRuntimeUpdater.EnsureAvailableAsync(profile, runtime, !explicitRuntime, token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            var xpi = ThunderbirdBridge.InstallHost(managed: true, nativeExecutable);
            PrepareProfile(profile, runtime, xpi, System.Globalization.CultureInfo.CurrentUICulture.Name);
            var start = new ProcessStartInfo(selected.Executable)
            { WorkingDirectory = Path.GetDirectoryName(selected.Executable)!, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true, RedirectStandardError = true };
            // The managed extension keeps the normal startup window hidden;
            // provider authentication popups remain visible to the user.
            foreach (var value in new[] { "-no-remote", "-purgecaches", "-profile", profile }) start.ArgumentList.Add(value);
            if (diagnostics is not null) start.Environment["MAGNOLIE_ACCOUNT_PROBE_TRACE"] = profile;
            attemptedProfile = profile;
            ownedProcess?.Dispose();
            ownedProcess = Process.Start(start) ?? throw new IOException("Could not start account helper.");
            ownedProfile = profile;
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
                    failedProfile = null;
                    return;
                }
                catch (Exception error) when (error is IOException or TimeoutException)
                { await Task.Delay(300, startup.Token).ConfigureAwait(false); }
            }
        }
        catch
        {
            if (attemptedProfile is not null) { failedProfile = attemptedProfile; nextStartAttempt = DateTimeOffset.UtcNow.AddMinutes(1); }
            throw;
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
        await ManagedAccountRuntimeUpdater.StopAsync().ConfigureAwait(false);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        try
        {
            if (ownedProcess is null && !Enabled) return;
            var running = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, deadline.Token, 500, managed: true);
            if (running["managed"]?.GetValue<bool>() != true ||
                !string.Equals(Path.GetFullPath(running["profile"]!.GetValue<string>()), Path.GetFullPath(ownedProfile ?? Profile), StringComparison.OrdinalIgnoreCase)) return;
            var currentPid = running["pid"]!.GetValue<int>();
            if (ownedProcess is null || ownedProcess.Id != currentPid)
            { ownedProcess?.Dispose(); ownedProcess = Process.GetProcessById(currentPid); }
            await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "shutdown" }, deadline.Token, 500, managed: true);
            await ownedProcess.WaitForExitAsync(deadline.Token);
        }
        catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException or ArgumentException) { }
        finally { ownedProcess?.Dispose(); ownedProcess = null; ownedProfile = null; }
    }
}
