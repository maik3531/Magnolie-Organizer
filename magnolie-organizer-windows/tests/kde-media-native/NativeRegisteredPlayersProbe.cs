using System.Diagnostics;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;
using Microsoft.Win32;

internal static class NativeRegisteredPlayersProbe
{
    internal static int Child()
    {
        var stage = Environment.GetEnvironmentVariable("MAGNOLIE_NATIVE_PLAYER_STAGE");
        var name = Path.GetFileNameWithoutExtension(Environment.ProcessPath);
        if (string.IsNullOrEmpty(stage) || name is not ("Magnolie-owned-music" or "Magnolie-owned-video")) return 2;
        File.WriteAllText(Path.Combine(stage, name + ".marker"), Environment.ProcessId.ToString());
        return 0;
    }

    internal static int Run()
    {
        var id = Guid.NewGuid().ToString("N");
        var stage = Path.Combine(Path.GetTempPath(), "magnolie-registered-" + id);
        var key = @"SOFTWARE\MagnolieNativePlayers\" + id;
        var registrations = new List<string>();
        var classes = new List<string>();
        var children = new List<Process>();
        var executables = new List<string>();
        var previous = Environment.GetEnvironmentVariable("MAGNOLIE_NATIVE_PLAYER_STAGE");
        bool existed;
        using (var existing = Registry.CurrentUser.OpenSubKey(@"SOFTWARE\RegisteredApplications")) existed = existing is not null;
        Directory.CreateDirectory(stage);
        try
        {
            Environment.SetEnvironmentVariable("MAGNOLIE_NATIVE_PLAYER_STAGE", stage);
            var appHost = Path.Combine(AppContext.BaseDirectory, "KdeMediaNative.exe");
            if (!File.Exists(appHost)) throw new Exception("Owned apphost missing");
            // Apphost keeps its embedded DLL location; copies remain next to the
            // freshly built fixture assembly, never in an installed app folder.
            foreach (var slot in new[] { "music", "video" })
            {
                var name = "Magnolie-owned-" + slot;
                var executable = Path.Combine(AppContext.BaseDirectory, name + ".exe");
                if (File.Exists(executable)) throw new Exception("Owned launch path already exists");
                File.Copy(appHost, executable);
                executables.Add(executable);
                var registration = "Magnolie-native-" + slot + "-" + id;
                var progId = registration + ".media";
                registrations.Add(registration); classes.Add(progId);
                using (var capabilities = Registry.CurrentUser.CreateSubKey(key + "\\" + slot + "\\Capabilities"))
                {
                    capabilities.SetValue("ApplicationName", name);
                    using var associations = capabilities.CreateSubKey("FileAssociations");
                    associations.SetValue(slot == "music" ? ".mp3" : ".mp4", progId);
                }
                using (var command = Registry.CurrentUser.CreateSubKey(@"SOFTWARE\Classes\" + progId + @"\shell\open\command"))
                    command.SetValue(null, "\"" + executable + "\" \"%1\"");
                using (var registered = Registry.CurrentUser.CreateSubKey(@"SOFTWARE\RegisteredApplications"))
                    registered.SetValue(registration, key + "\\" + slot + "\\Capabilities");
            }
            var apps = KdeRegisteredPlayers.Installed().Where(app => registrations.Any(registration => app.Id.EndsWith(registration, StringComparison.Ordinal))).ToArray();
            if (apps.Length != 2) throw new Exception("Owned registered media handlers were not discovered");
            var choices = new KdeRegisteredPlayers(stage, () => apps);
            foreach (var slot in new[] { "music", "video" })
                choices.Configure(slot, apps.Single(app => app.Name == "Magnolie-owned-" + slot).Id);
            foreach (var alias in choices.Choices().Keys)
            {
                try { choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => false); throw new Exception("Revoked source launched an app"); }
                catch (InvalidOperationException error) when (error.Message == "local_media_source_changed") { }
            }
            if (Directory.GetFiles(stage, "*.marker").Length != 0) throw new Exception("Denied requests executed");
            foreach (var alias in choices.Choices().Keys) choices.Closed(alias, new JsonObject { ["action"] = "Play" }, () => true);
            var deadline = Environment.TickCount64 + 10000;
            while (Directory.GetFiles(stage, "*.marker").Length != 2 && Environment.TickCount64 < deadline) Thread.Sleep(20);
            foreach (var slot in new[] { "music", "video" })
            {
                var pid = int.Parse(File.ReadAllText(Path.Combine(stage, "Magnolie-owned-" + slot + ".marker")));
                try
                {
                    var process = Process.GetProcessById(pid); children.Add(process);
                    if (!process.WaitForExit(3000)) throw new Exception("Owned child did not finish");
                }
                catch (ArgumentException) { } // The short-lived owned child already exited.
            }
            var reopened = new KdeRegisteredPlayers(stage, () => apps);
            if (reopened.Choices().Count != 2) throw new Exception("Native choices did not persist");
            Console.WriteLine("PASS: native Windows registered media handlers / closed music and video / revoked source / both owned application launches / persistence");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            foreach (var child in children) child.Dispose();
            using (var registered = Registry.CurrentUser.OpenSubKey(@"SOFTWARE\RegisteredApplications", true))
                foreach (var registration in registrations)
                    if (registered?.GetValue(registration) is string value && value.StartsWith(key + "\\", StringComparison.Ordinal)) registered.DeleteValue(registration);
            foreach (var progId in classes) Registry.CurrentUser.DeleteSubKeyTree(@"SOFTWARE\Classes\" + progId, false);
            Registry.CurrentUser.DeleteSubKeyTree(key, false);
            if (!existed)
            {
                using var registered = Registry.CurrentUser.OpenSubKey(@"SOFTWARE\RegisteredApplications");
                if (registered is { ValueCount: 0, SubKeyCount: 0 }) Registry.CurrentUser.DeleteSubKey(@"SOFTWARE\RegisteredApplications", false);
            }
            foreach (var executable in executables)
            {
                if (File.Exists(executable)) File.Delete(executable);
            }
            Environment.SetEnvironmentVariable("MAGNOLIE_NATIVE_PLAYER_STAGE", previous);
            Directory.Delete(stage, true);
        }
    }
}
