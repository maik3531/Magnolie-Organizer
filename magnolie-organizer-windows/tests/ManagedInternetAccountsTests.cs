using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ManagedInternetAccountsTests
{
    internal static async Task RunAsync()
    {
        ManagedAccountRuntimePolicyTests.Run();
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
            await TestOperationsAsync();
            var providerCalls = 0;
            var preparing = new ManagedAccountOperations(() => true, _ => throw new AccountRuntimeUpdatingException(),
                (_, _) => { providerCalls++; return Task.FromResult(new JsonObject()); }, (_, _, _) => { providerCalls++; return Task.CompletedTask; });
            foreach (var action in new[] { "read", "sign_in", "rename", "remove", "edit" })
                await TestAssert.ThrowsAsync<AccountRuntimeUpdatingException>(() => preparing.ExecuteAsync(action, "google", "owned@example.test",
                    "owned@example.test", "Owned", null, default), "Component preparation reached an account action or claimed a ready inventory.");
            TestAssert.That(providerCalls == 0, "An account provider was called before its component became available.");
        }
        finally { Directory.Delete(root, true); }
    }

    private static async Task TestOperationsAsync()
    {
        var raw = JsonNode.Parse("""
            {"google":{"accounts":["alice@example.test","bob@example.test"],"details":[{"id":"alice@example.test","name":"Alice","enabled":true},{"id":"bob@example.test","name":"Bob","enabled":true}],"pending":false,"tasks":{"available":false},"token":"owned-private-google-token"},
             "microsoft":{"accounts":[{"id":"owned-ms","name":"Work","enabled":true,"error":"owned-private-provider-error"}],"login":{"pending":false},"tasks":{"available":true},"secret":"owned-private-ms-token"}}
            """)!.AsObject();
        var configured = true; var permitted = true; var ignoreWrite = false; var writes = 0; var starts = 0; var ensures = 0;
        var operations = new ManagedAccountOperations(() => configured, _ => { ensures++; return Task.CompletedTask; }, (request, _) =>
        {
            if (request["op"]!.GetValue<string>() == "status") return Task.FromResult(raw.DeepClone().AsObject());
            writes++;
            if (!ignoreWrite)
            {
                var id = request["accountId"]!.GetValue<string>(); var action = request["action"]!.GetValue<string>();
                var details = raw["google"]!["details"]!.AsArray();
                if (request["provider"]!.GetValue<string>() == "google")
                {
                    var detail = details.OfType<JsonObject>().Single(item => item["id"]!.GetValue<string>() == id);
                    if (action == "rename") detail["name"] = request["name"]!.GetValue<string>();
                    if (action == "remove") { details.Remove(detail); var ids = raw["google"]!["accounts"]!.AsArray(); ids.Remove(ids.Single(item => item!.GetValue<string>() == id)); }
                }
            }
            return Task.FromResult(new JsonObject { ["ok"] = true });
        }, (provider, email, _) =>
        {
            TestAssert.That(provider == "google" && email == "new@example.test", "Managed sign-in lost its actual provider/email input.");
            configured = true; starts++; raw["google"]!["pending"] = true; return Task.CompletedTask;
        }, () => permitted);
        Task<ManagedAccountReceipt> Execute(string action = "read", string? revision = null, string account = "alice@example.test", string name = "Renamed") =>
            operations.ExecuteAsync(action, "google", account, "new@example.test", name, revision, default);
        var first = await Execute();
        TestAssert.That(first.State.Public["accounts"]!.AsArray().Count == 3 && !first.Accepted && !first.Verified &&
            !first.State.Public.ToJsonString().Contains("owned-private", StringComparison.Ordinal), "Managed account inventory exposed raw provider fields.");
        var renamed = await Execute("rename", first.State.Revision);
        TestAssert.That(renamed.Accepted && renamed.Verified && renamed.State.Revision != first.State.Revision &&
            renamed.State.Public["accounts"]![0]!["name"]!.GetValue<string>() == "Renamed", "Rename did not verify actual provider status.");
        var before = writes;
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => Execute("remove", first.State.Revision), "Stale account revision was accepted.");
        TestAssert.That(writes == before, "Stale account revision still mutated the provider.");
        ignoreWrite = true;
        await TestAssert.ThrowsAsync<InvalidDataException>(() => Execute("rename", renamed.State.Revision, name: "Ignored"), "A false backend ACK was reported as verified rename.");
        ignoreWrite = false;
        var current = await Execute();
        var removed = await Execute("remove", current.State.Revision);
        TestAssert.That(removed.Verified && removed.State.Public["accounts"]!.AsArray().Count == 2 &&
            removed.State.Public["accounts"]!.AsArray().All(item => item!["id"]!.GetValue<string>() != "alice@example.test"), "Selective removal affected another account or was not read back.");
        permitted = false; before = writes;
        await TestAssert.ThrowsAsync<OperationCanceledException>(() => Execute("remove", removed.State.Revision, "bob@example.test"), "Profile/sync mutation gate was ignored.");
        TestAssert.That(writes == before, "A disallowed account operation reached the provider."); permitted = true;
        configured = false; var previousEnsures = ensures;
        var empty = await Execute();
        TestAssert.That(!empty.State.Public["ready"]!.GetValue<bool>() && ensures == previousEnsures, "Reading an unconfigured account helper started it.");
        var opening = await Execute("sign_in", empty.State.Revision);
        TestAssert.That(opening.Accepted && !opening.Verified && starts == 1 && opening.State.Public["google_pending"]!.GetValue<bool>(), "Opening a provider sign-in window claimed completed authentication.");
        await TestAssert.ThrowsAsync<InvalidOperationException>(() => Execute("remove", opening.State.Revision, "bob@example.test"), "Pending sign-in did not block account mutation.");
        var malformed = raw.DeepClone().AsObject(); malformed["bereit"] = true; malformed["microsoft"]!["accounts"]!.AsArray().Add("owned-bad-row");
        TestAssert.Throws<InvalidDataException>(() => ManagedAccountOperations.Project(malformed), "Malformed account rows were silently omitted from revision/readback.");
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
            TestAssert.That(string.Equals(process.MainModule!.FileName, Path.GetFullPath(Path.Combine(runtime, "thunderbird.exe")), StringComparison.OrdinalIgnoreCase),
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
