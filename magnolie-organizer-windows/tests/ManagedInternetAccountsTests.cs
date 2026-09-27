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

    internal static async Task<int> ProbeAsync(string runtime, string profile, string nativeExecutable, bool lifecycle = false)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(lifecycle ? 180 : 60));
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
            if (lifecycle)
            {
                TestAssert.That(Path.GetFileName(profile).StartsWith("accounts38-lifecycle-", StringComparison.Ordinal), "Fixture profile required.");
                var google = status["google"]!["accounts"]!.AsArray();
                var microsoft = status["microsoft"]!["accounts"]!.AsArray();
                TestAssert.That(google.Count == 2 && google.All(x => x!.GetValue<string>().EndsWith("@example.invalid", StringComparison.Ordinal)) &&
                    microsoft.Count == 2 && microsoft.All(x => x!["name"]!.GetValue<string>().StartsWith("Fixture38-", StringComparison.Ordinal)), "Synthetic fixture required.");
                var googleId = google[0]!.GetValue<string>(); var microsoftId = microsoft[0]!["id"]!.GetValue<string>();
                async Task Change(string provider, string id, string action, string name = "") =>
                    _ = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "manage-account", ["provider"] = provider,
                        ["accountId"] = id, ["action"] = action, ["name"] = name }, timeout.Token, managed: true);
                await Change("google", googleId, "rename", "Fixture38-Google-renamed");
                await Change("microsoft", microsoftId, "rename", "Fixture38-Microsoft-renamed");
                await ManagedInternetAccounts.StopAsync();
                await ManagedInternetAccounts.EnsureStartedAsync(timeout.Token, profile, runtime, nativeExecutable);
                var restarted = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "status" }, timeout.Token, managed: true);
                TestAssert.That(restarted["google"]!["details"]!.AsArray().Any(x => x!["name"]!.GetValue<string>() == "Fixture38-Google-renamed") &&
                    restarted["microsoft"]!["accounts"]!.AsArray().Any(x => x!["name"]!.GetValue<string>() == "Fixture38-Microsoft-renamed"), "Renamed accounts did not survive restart.");
                await Change("google", googleId, "remove"); await Change("microsoft", microsoftId, "remove");
                await ManagedInternetAccounts.StopAsync();
                await ManagedInternetAccounts.EnsureStartedAsync(timeout.Token, profile, runtime, nativeExecutable);
                var final = await ThunderbirdBridge.CallAsync(new JsonObject { ["op"] = "status" }, timeout.Token, managed: true);
                TestAssert.That(final["google"]!["accounts"]!.AsArray().Count == 1 &&
                    final["google"]!["accounts"]![0]!.GetValue<string>() != googleId &&
                    final["microsoft"]!["accounts"]!.AsArray().Count == 1 &&
                    final["microsoft"]!["accounts"]![0]!["id"]!.GetValue<string>() != microsoftId, "Removal affected another account or did not persist.");
                Console.WriteLine("Account lifecycle: renamed, restarted, selectively removed, restarted; both other accounts retained.");
            }
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
