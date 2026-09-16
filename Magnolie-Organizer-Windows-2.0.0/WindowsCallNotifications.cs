using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using Windows.Data.Xml.Dom;
using Windows.UI.Notifications;

namespace MagnolieOrganizer.Windows;

internal sealed class WindowsCallNotifications : IDisposable
{
    private const string AppId = "MagnolieOrganizer.CallAlert";
    private const string Scheme = "magnolie-call";
    private readonly CancellationTokenSource lifetime = new();
    private readonly Func<string, Task<bool>> execute;
    private readonly string appId;
    private readonly string scheme;
    private readonly string pipeName;
    private readonly Guid activatorId;
    private ToastNotifier? notifier;
    private ToastNotification? toast;
    internal int LastErrorHResult { get; private set; }
    internal string RegistrationState { get; private set; } = "not_checked";
    internal string ShortcutPath => Path.Combine(NativeMethods.UserProgramsPath(), appId + ".lnk");
    private static bool Elevated => new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
    private static string PipeName => "Magnolie.Call." + WindowsIdentity.GetCurrent().User!.Value + "." + System.Diagnostics.Process.GetCurrentProcess().SessionId;
    private static bool ValidToken(string value) => Regex.IsMatch(value, "\\A[0-9a-f]{64}\\z", RegexOptions.CultureInvariant);

    internal WindowsCallNotifications(Func<string, Task<bool>> execute, Guid? isolationId = null, bool listen = true)
    {
        this.execute = execute;
        // Native tests must never share installed protocol, app or pipe identities.
        appId = isolationId is { } id ? AppId + ".Test." + id.ToString("N") : AppId;
        scheme = isolationId is { } scope ? Scheme + "-test-" + scope.ToString("N") : Scheme;
        pipeName = isolationId is { } pipeScope ? PipeName + ".Test." + pipeScope.ToString("N") : PipeName;
        // Protocol-only toasts use a stub CLSID, not an executable COM server.
        activatorId = isolationId ?? new Guid("1f92528e-6443-4b7b-b814-935076341c1f");
        if (listen && !Elevated) _ = ListenAsync();
    }

    internal static bool Activate(string argument, Guid? isolationId = null)
    {
        var scheme = isolationId is { } scope ? Scheme + "-test-" + scope.ToString("N") : Scheme;
        var pipeName = isolationId is { } pipeScope ? PipeName + ".Test." + pipeScope.ToString("N") : PipeName;
        var token = argument.StartsWith(scheme + ":", StringComparison.Ordinal) ? argument[(scheme.Length + 1)..] : argument;
        if (Elevated || !ValidToken(token)) return false;
        try
        {
            // CurrentUserOnly also rejects elevation mismatches. No profile/keys are read by this launcher.
            using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut, PipeOptions.CurrentUserOnly);
            pipe.Connect(1500);
            using var deadline = new CancellationTokenSource(5000);
            pipe.WriteAsync(Encoding.ASCII.GetBytes(token), deadline.Token).AsTask().GetAwaiter().GetResult();
            var result = new byte[1];
            pipe.ReadExactlyAsync(result, deadline.Token).AsTask().GetAwaiter().GetResult();
            return result[0] == 1;
        }
        catch (Exception error) when (error is IOException or TimeoutException or OperationCanceledException or UnauthorizedAccessException) { return false; }
    }

    private async Task ListenAsync()
    {
        while (!lifetime.IsCancellationRequested)
        {
            try
            {
                using var pipe = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.WaitForConnectionAsync(lifetime.Token);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                deadline.CancelAfter(5000);
                var bytes = new byte[64];
                await pipe.ReadExactlyAsync(bytes, deadline.Token);
                var token = Encoding.ASCII.GetString(bytes);
                var accepted = false;
                try { accepted = ValidToken(token) && await execute(token); }
                catch (Exception) { }
                await pipe.WriteAsync(new byte[] { accepted ? (byte)1 : (byte)0 }, deadline.Token);
            }
            catch (Exception error) when (error is IOException or OperationCanceledException or InvalidOperationException or UnauthorizedAccessException)
            {
                if (lifetime.IsCancellationRequested) return;
                await Task.Delay(250);
            }
        }
    }

    internal bool Show(string title, string caller, IReadOnlyDictionary<string, string> actions)
    {
        if (Elevated) return false;
        LastErrorHResult = 0;
        try
        {
            if (actions.Count > 2 || actions.Any(action => action.Key is not ("answer" or "reject") || !ValidToken(action.Value))) return false;
            if (!Register()) return false;
            if (notifier is null)
            {
                notifier = ToastNotificationManager.CreateToastNotifier(appId);
            }
            Withdraw();
            try { if (notifier.Setting != NotificationSetting.Enabled) return false; }
            catch (COMException error) when (error.HResult == unchecked((int)0x80070490))
            {
                // A fresh unpackaged identity may have no settings row until its
                // first Show. Windows still enforces notification policy in Show.
            }
            var xml = new XmlDocument();
            var buttons = string.Concat(actions.Select(item => $"<action content=\"{SecurityElement.Escape(NativeLocalization.Gettext(item.Key == "answer" ? "Answer" : "Reject"))}\" arguments=\"{scheme}:{item.Value}\" activationType=\"protocol\"/>"));
            // Body activation must never carry an answer/reject ticket.
            xml.LoadXml($"<toast duration=\"long\" activationType=\"protocol\" launch=\"{scheme}:dismiss\"><visual><binding template=\"ToastGeneric\"><text>{SecurityElement.Escape(title)}</text><text>{SecurityElement.Escape(caller)}</text></binding></visual><actions>{buttons}</actions><audio silent=\"true\"/></toast>");
            toast = new ToastNotification(xml) { ExpirationTime = DateTimeOffset.UtcNow.AddSeconds(60), Tag = "call", Group = "phone" };
            notifier.Show(toast);
            return true;
        }
        catch (Exception error) when (error is COMException or IOException or UnauthorizedAccessException or SecurityException or ArgumentException or System.ComponentModel.Win32Exception)
        { LastErrorHResult = error.HResult; return false; }
    }

    private const string OwnerSid = "MagnolieOwnerSid";
    private const string OwnerExecutable = "MagnolieOwnerExecutable";
    private static string Executable => Path.GetFullPath(Application.ExecutablePath);
    private static string Sid => WindowsIdentity.GetCurrent().User!.Value;
    private string ProtocolPath => @"Software\Classes\" + scheme;
    private string AppPath => @"Software\Classes\AppUserModelId\" + appId;
    private static string Command => $"\"{Executable}\" --call-action \"%1\"";
    private bool OwnedKey(RegistryKey key)
    {
        if (key.GetValue(OwnerSid) as string != Sid || key.GetValue(OwnerExecutable) as string != Executable) return false;
        if (key.ValueCount != 6 || key.SubKeyCount != 1 || key.GetValue("") as string != "URL:Magnolie call action" ||
            key.GetValue("URL Protocol") as string != "" || key.GetValue("MagnolieAppId") as string != appId ||
            key.GetValue("MagnolieActivator") as string != activatorId.ToString("B")) return false;
        using var shell = key.OpenSubKey("shell"); using var open = shell?.OpenSubKey("open"); using var command = open?.OpenSubKey("command");
        return shell is { ValueCount: 0, SubKeyCount: 1 } && open is { ValueCount: 0, SubKeyCount: 1 } &&
            command is { ValueCount: 1, SubKeyCount: 0 } && command.GetValue("") as string == Command;
    }

    internal bool Register()
    {
        if (Elevated) { RegistrationState = "elevated"; return false; }
        using var mutex = new Mutex(false, @"Local\" + appId + ".Registration." + Sid);
        try { if (!mutex.WaitOne(TimeSpan.FromSeconds(2))) { RegistrationState = "busy"; return false; } }
        catch (AbandonedMutexException) { }
        try
        {
            var shortcut = ShortcutPath;
            var programs = Path.GetDirectoryName(shortcut)!;
            if (!Directory.Exists(programs) || (File.GetAttributes(programs) & FileAttributes.ReparsePoint) != 0)
            { RegistrationState = "programs_unavailable"; return false; }
            if (Path.Exists(shortcut) && !NativeMethods.ToastShortcutMatches(shortcut, Executable, appId, activatorId, Sid))
            { RegistrationState = "shortcut_conflict"; return false; }
            // A registry-based AUMID belongs to a different registration topology.
            // Do not take it over, even if it uses our display name.
            using (var app = Registry.CurrentUser.OpenSubKey(AppPath))
                if (app is not null) { RegistrationState = "app_id_conflict"; return false; }
            using (var existing = Registry.CurrentUser.OpenSubKey(ProtocolPath))
            {
                if (existing is not null && !OwnedKey(existing))
                { RegistrationState = "protocol_conflict"; return false; }
            }
            using (var key = NativeMethods.CreateCurrentUserKey(ProtocolPath, out var created))
            {
                if (!created && !OwnedKey(key)) { RegistrationState = "registration_race"; return false; }
                if (created)
                {
                    key.SetValue(OwnerSid, Sid); key.SetValue(OwnerExecutable, Executable);
                    key.SetValue("MagnolieAppId", appId); key.SetValue("MagnolieActivator", activatorId.ToString("B"));
                    key.SetValue("", "URL:Magnolie call action"); key.SetValue("URL Protocol", "");
                    using var command = key.CreateSubKey(@"shell\open\command"); command.SetValue("", Command);
                }
            }
            if (!Path.Exists(shortcut))
            {
                var temporary = Path.Combine(Path.GetTempPath(), "magnolie-toast-" + Guid.NewGuid().ToString("N") + ".lnk");
                try
                {
                    NativeMethods.CreateToastShortcut(temporary, Executable, appId, activatorId);
                    File.Move(temporary, shortcut, false);
                    NativeMethods.NotifyShortcutChanged(shortcut);
                }
                finally { File.Delete(temporary); }
            }
            var matches = NativeMethods.ToastShortcutMatches(shortcut, Executable, appId, activatorId, Sid);
            RegistrationState = matches ? "registered" : "shortcut_verification_failed";
            return matches;
        }
        finally { mutex.ReleaseMutex(); }
    }

    internal bool Unregister()
    {
        using var mutex = new Mutex(false, @"Local\" + appId + ".Registration." + Sid);
        try { if (!mutex.WaitOne(TimeSpan.FromSeconds(2))) return false; }
        catch (AbandonedMutexException) { }
        try
        {
            Withdraw();
            var shortcut = ShortcutPath;
            var foreignShortcut = false;
            if (Path.Exists(shortcut))
            {
                var owned = false;
                try { owned = NativeMethods.ToastShortcutMatches(shortcut, Executable, appId, activatorId, Sid); }
                catch (COMException) { } // A malformed foreign link is not ours to remove.
                if (owned)
                { File.Delete(shortcut); NativeMethods.NotifyShortcutChanged(shortcut, true); }
                else foreignShortcut = true;
            }
            // A different registration is not ours to delete and must not make
            // uninstalling this installation impossible. Elevation does not change
            // the current-user/executable ownership checks used for cleanup.
            var removeProtocol = false;
            using (var key = Registry.CurrentUser.OpenSubKey(ProtocolPath))
            {
                removeProtocol = key is not null && OwnedKey(key);
            }
            if (removeProtocol)
            {
                Registry.CurrentUser.DeleteSubKeyTree(ProtocolPath, false);
                using var app = Registry.CurrentUser.OpenSubKey(AppPath);
                if (app is null && !foreignShortcut) { try { ToastNotificationManager.History.Clear(appId); } catch (COMException) { } }
            }
            notifier = null;
            return true;
        }
        finally { mutex.ReleaseMutex(); }
    }

    internal void Withdraw()
    {
        try
        {
            if (toast is not null)
            {
                notifier?.Hide(toast);
                ToastNotificationManager.History.Remove("call", "phone", appId);
            }
        }
        catch (System.Runtime.InteropServices.COMException) { }
        toast = null;
    }
    public void Dispose() { lifetime.Cancel(); Withdraw(); }
}
