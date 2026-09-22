using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ManagedInternetAccountsTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-account-profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var runtime = Path.Combine(root, "runtime");
            Directory.CreateDirectory(Path.Combine(runtime, "magnolie-extensions"));
            foreach (var file in new[] { "thunderbird.exe", "runtime.json", "magnolie-extensions/tbsync@jobisoft.de.xpi", "magnolie-extensions/eas4tbsync@jobisoft.de.xpi" })
                File.WriteAllText(Path.Combine(runtime, file), "fixture");
            var xpi = Path.Combine(root, "bridge.xpi"); File.WriteAllText(xpi, "bridge");
            var personal = Path.Combine(root, "personal"); Directory.CreateDirectory(personal);
            File.WriteAllText(Path.Combine(personal, "prefs.js"), "PERSONAL PROFILE");
            TestAssert.Throws<InvalidDataException>(() => ManagedInternetAccounts.PrepareProfile(personal, runtime, xpi, "de"),
                "An existing personal Thunderbird profile was reconfigured.");
            TestAssert.That(File.ReadAllText(Path.Combine(personal, "prefs.js")) == "PERSONAL PROFILE", "Personal settings changed.");
            var profile = Path.Combine(root, "managed");
            ManagedInternetAccounts.PrepareProfile(profile, runtime, xpi, "de");
            File.WriteAllText(Path.Combine(profile, "keep-account-data"), "PRESERVE");
            ManagedInternetAccounts.PrepareProfile(profile, runtime, xpi, "fr");
            TestAssert.That(File.ReadAllText(Path.Combine(profile, "keep-account-data")) == "PRESERVE" &&
                File.ReadAllText(Path.Combine(profile, "user.js")).Contains("extensions.magnolie.managed") &&
                File.Exists(Path.Combine(profile, "extensions", ThunderbirdBridge.ExtensionId + ".xpi")),
                "Managed setup lost account data or required manual add-on installation.");
            TestAssert.That(ThunderbirdBridge.IsManagedSource("thunderbird-calendar:managed:profile:calendar") &&
                !ThunderbirdBridge.IsManagedSource("thunderbird-calendar:personal:calendar"), "Managed and personal sources share a transport.");
        }
        finally { Directory.Delete(root, true); }
        return Task.CompletedTask;
    }

    internal static async Task<int> ProbeAsync(string runtime, string profile, string nativeExecutable)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        System.Diagnostics.Process? process = null;
        try
        {
            await ManagedInternetAccounts.EnsureStartedAsync(timeout.Token, profile, runtime, nativeExecutable, Console.WriteLine);
            var environment = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "environment" }, timeout.Token, managed: true);
            var status = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "status" }, timeout.Token, managed: true);
            TestAssert.That(environment["managed"]?.GetValue<bool>() == true && environment["ready"]?.GetValue<bool>() == true,
                "The managed helper did not finish automatic setup.");
            TestAssert.That(ManagedInternetAccounts.MailWindows(environment, hide: false) == 0, "The background helper exposed a mail window.");
            TestAssert.That(status["microsoft"]?["protocol"]?.GetValue<int>() == 1, "The bundled Microsoft account adapter is unavailable.");
            process = System.Diagnostics.Process.GetProcessById(environment["pid"]!.GetValue<int>());
            TestAssert.That(string.Equals(process.MainModule!.FileName, Path.Combine(runtime, "thunderbird.exe"), StringComparison.OrdinalIgnoreCase),
                "The probe used an installed mail client instead of the packaged helper.");
            Console.WriteLine("Managed account helper: bundled runtime, automatic isolated profile and add-on setup, dedicated native channel, Microsoft adapter ready.");
            return 0;
        }
        finally
        {
            await ManagedInternetAccounts.StopAsync();
            if (process is not null)
            {
                var exited = process.WaitForExit(5000);
                process.Dispose();
                TestAssert.That(exited, "The owned account helper remained running after shutdown.");
                Console.WriteLine("Managed account helper shutdown confirmed.");
            }
        }
    }
}
