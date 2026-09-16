using System.Reflection;
using System.Runtime.Loader;
using System.Security.Principal;
using Microsoft.Win32;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (!OperatingSystem.IsWindows() || args.Length != 1) return 2;
        var assemblyPath = Path.GetFullPath(args[0]);
        var directory = Path.GetDirectoryName(assemblyPath)!;
        AssemblyLoadContext.Default.Resolving += (_, name) =>
        {
            var path = Path.Combine(directory, name.Name + ".dll");
            return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
        };
        var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
        var type = assembly.GetType("MagnolieOrganizer.Windows.WindowsCallNotifications", true)!;
        var flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
        var scope = Guid.NewGuid();
        var appId = "MagnolieOrganizer.CallAlert.Test." + scope.ToString("N");
        var protocol = @"Software\Classes\magnolie-call-test-" + scope.ToString("N");
        var appPath = @"Software\Classes\AppUserModelId\" + appId;
        using var instance = (IDisposable)Activator.CreateInstance(type, flags, null,
            new object?[] { (Func<string, Task<bool>>)(_ => Task.FromResult(false)), scope, false }, null)!;
        var shortcut = (string)type.GetProperty("ShortcutPath", flags)!.GetValue(instance)!;
        var executable = (string)type.GetProperty("Executable", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;
        var cleanup = type.GetMethod("Unregister", flags)!;
        void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); Console.WriteLine("PASS " + message); }
        bool Unregister() => (bool)cleanup.Invoke(instance, null)!;
        void OwnProtocol()
        {
            using var key = Registry.CurrentUser.CreateSubKey(protocol);
            key.SetValue("MagnolieOwnerSid", WindowsIdentity.GetCurrent().User!.Value);
            key.SetValue("MagnolieOwnerExecutable", executable);
            key.SetValue("MagnolieAppId", appId);
            key.SetValue("MagnolieActivator", scope.ToString("B"));
            key.SetValue("", "URL:Magnolie call action");
            key.SetValue("URL Protocol", "");
            using var command = key.CreateSubKey(@"shell\open\command");
            command.SetValue("", $"\"{executable}\" --call-action \"%1\"");
        }
        try
        {
            Console.WriteLine("Elevated=" + new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator));
            Check(Unregister() && Unregister(), "no registration is an idempotent success");
            using (var app = Registry.CurrentUser.CreateSubKey(appPath)) app.SetValue("sentinel", "foreign");
            using (var key = Registry.CurrentUser.CreateSubKey(protocol)) key.SetValue("sentinel", "foreign");
            File.WriteAllText(shortcut, "synthetic foreign shortcut");
            Check(Unregister(), "foreign registrations do not block uninstall");
            using (var key = Registry.CurrentUser.OpenSubKey(protocol)) Check(key?.GetValue("sentinel") as string == "foreign", "foreign protocol retained");
            using (var app = Registry.CurrentUser.OpenSubKey(appPath)) Check(app?.GetValue("sentinel") as string == "foreign", "foreign app identity retained");
            Check(File.ReadAllText(shortcut) == "synthetic foreign shortcut", "foreign shortcut retained");
            Registry.CurrentUser.DeleteSubKeyTree(protocol);
            OwnProtocol();
            Check(Unregister(), "own protocol removed despite foreign app identity");
            using (var key = Registry.CurrentUser.OpenSubKey(protocol)) Check(key is null, "own protocol absent");
            Check(File.Exists(shortcut), "foreign shortcut still retained");
            Registry.CurrentUser.DeleteSubKeyTree(appPath);
            File.Delete(shortcut);
            OwnProtocol();
            var native = assembly.GetType("MagnolieOrganizer.Windows.NativeMethods", true)!;
            native.GetMethod("CreateToastShortcut", BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null,
                new object[] { shortcut, executable, appId, scope });
            // Registration normally runs unelevated. An elevated test process
            // may create files owned by Administrators; model the normal user's file.
            var file = new FileInfo(shortcut);
            var security = file.GetAccessControl();
            security.SetOwner(WindowsIdentity.GetCurrent().User!);
            file.SetAccessControl(security);
            Check(Unregister(), "owned shortcut and protocol cleaned");
            Check(!File.Exists(shortcut), "owned shortcut absent");
            using (var key = Registry.CurrentUser.OpenSubKey(protocol)) Check(key is null, "owned protocol absent after cleanup");
            Check(Unregister(), "repeated cleanup succeeds");
            return 0;
        }
        finally
        {
            // All names contain this run's random isolation ID; never installed identities.
            Registry.CurrentUser.DeleteSubKeyTree(protocol, false);
            Registry.CurrentUser.DeleteSubKeyTree(appPath, false);
            File.Delete(shortcut);
        }
    }
}
