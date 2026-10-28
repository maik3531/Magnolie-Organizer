using MagnolieOrganizer.Windows;
using System.Reflection;
using System.Security.Cryptography;

namespace MagnolieOrganizer.Windows.Tests;

internal static class ManagedAccountRuntimePolicyTests
{
    internal static async Task<int> NativeUpdateProbeAsync(string packagedRuntime, string root, string originalMar)
    {
        if (!OperatingSystem.IsWindows() || !Path.GetFileName(root).StartsWith("Magnolie-Update210-", StringComparison.Ordinal) ||
            !string.Equals(Path.GetDirectoryName(Path.GetFullPath(root)), Path.TrimEndingDirectorySeparator(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("An owned native updater fixture is required.");
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(4));
        var profile = Path.Combine(root, "profile"); Directory.CreateDirectory(profile);
        var compatibility = "[Compatibility]\nLastVersion=158.0.1_20261019221403\n";
        var compatibilityPath = Path.Combine(profile, "compatibility.ini"); File.WriteAllText(compatibilityPath, compatibility);
        static byte[] Digest(string path) { using var file = File.OpenRead(path); return SHA256.HashData(file); }
        var before = Digest(Path.Combine(packagedRuntime, "thunderbird.exe"));
        try
        {
            var pending = false;
            try { await ManagedAccountRuntimeUpdater.EnsureAvailableAsync(profile, packagedRuntime, false, timeout.Token); }
            catch (AccountRuntimeUpdatingException) { pending = true; }
            TestAssert.That(pending, "A missing compatible component did not enter the bounded background update path.");
            var taskField = typeof(ManagedAccountRuntimeUpdater).GetField("worker", BindingFlags.Static | BindingFlags.NonPublic)!;
            var task = (Task)taskField.GetValue(null)!;
            try { await ManagedAccountRuntimeUpdater.EnsureAvailableAsync(profile, packagedRuntime, false, timeout.Token); }
            catch (AccountRuntimeUpdatingException) { }
            TestAssert.That(ReferenceEquals(task, taskField.GetValue(null)), "Repeated status reads started duplicate component workers.");
            await task.WaitAsync(timeout.Token);
            var selected = await ManagedAccountRuntimeUpdater.EnsureAvailableAsync(profile, packagedRuntime, false, timeout.Token);
            TestAssert.That(selected.Source == AccountRuntimeSource.Managed && selected.Build.CompareTo(MozillaRuntimeBuild.Parse("158.0.1_20261019221403")) >= 0,
                "The automatic worker did not publish a verified compatible runtime.");
            TestAssert.That(File.ReadAllText(compatibilityPath) == compatibility && before.SequenceEqual(Digest(Path.Combine(packagedRuntime, "thunderbird.exe"))),
                "Component preparation altered the source installation or profile metadata.");
            using (var cancelled = new CancellationTokenSource())
            {
                cancelled.Cancel();
                await TestAssert.ThrowsAsync<OperationCanceledException>(() =>
                    ManagedAccountRuntimeUpdater.EnsureAvailableAsync(profile, packagedRuntime, false, cancelled.Token),
                    "A cancelled caller still received a component result.");
            }
            var negative = Path.Combine(root, "negative");
            var source = Path.Combine(negative, "base");
            ManagedAccountRuntimeUpdater.CopyRuntime(packagedRuntime, source, timeout.Token);
            var patch = Path.Combine(negative, "patch"); Directory.CreateDirectory(patch);
            var mar = Path.Combine(patch, "update.mar"); File.Copy(originalMar, mar);
            using (var file = new FileStream(mar, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            { file.Position = 4096; var value = file.ReadByte(); file.Position = 4096; file.WriteByte((byte)(value ^ 1)); file.Flush(true); }
            File.WriteAllText(Path.Combine(patch, "update.status"), "pending");
            var rejected = false;
            try { await ManagedAccountRuntimeUpdater.ApplyMozillaStagingAsync(source, patch, timeout.Token); }
            catch (IOException) { rejected = true; }
            var negativeStatus = File.ReadAllText(Path.Combine(patch, "update.status")).Trim();
            TestAssert.That(rejected && negativeStatus == "failed: 19", "Mozilla did not reject the tampered MAR specifically with CERT_VERIFY_ERROR.");
            TestAssert.That(before.SequenceEqual(Digest(Path.Combine(source, "thunderbird.exe"))) &&
                File.ReadAllText(compatibilityPath) == compatibility, "A rejected signed update altered original executable/profile data.");
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
            { background_worker_shared = true, selected_version = selected.Build.Version.ToString(), selected_source = selected.Source.ToString(),
                signature_readback = true, profile_unchanged = true, packaged_source_unchanged = true,
                cancelled_caller_rejected = true, tampered_mar_rejected = true, tampered_mar_status = negativeStatus }));
            return 0;
        }
        finally { await ManagedAccountRuntimeUpdater.StopAsync(); }
    }

    internal static int NativeProbe(string packagedRuntime, string stagedRuntime)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var root = Path.Combine(Path.GetTempPath(), "magnolie-runtime-trust-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var packaged = ManagedAccountRuntimeResolver.ReadCandidate(Path.Combine(packagedRuntime, "thunderbird.exe"), AccountRuntimeSource.Managed)
                ?? throw new InvalidDataException("Packaged Mozilla signature, x64 identity or build metadata validation failed.");
            var staged = ManagedAccountRuntimeResolver.ReadCandidate(Path.Combine(stagedRuntime, "thunderbird.exe"), AccountRuntimeSource.Managed)
                ?? throw new InvalidDataException("Staged Mozilla signature, x64 identity or build metadata validation failed.");
            var tampered = Path.Combine(root, "tampered.exe");
            File.Copy(packaged!.Executable, tampered);
            using (var file = new FileStream(tampered, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            { file.Position = 128; var value = file.ReadByte(); file.Position = 128; file.WriteByte((byte)(value ^ 1)); file.Flush(true); }
            TestAssert.That(!MozillaCodeTrust.IsTrusted(tampered), "Native trust accepted a tampered signed executable.");
            var extensions = ManagedAccountRuntimeResolver.ProviderCompatibility(packagedRuntime);
            var installed = ManagedAccountRuntimeResolver.InstalledExecutables().Select(path =>
                ManagedAccountRuntimeResolver.ReadCandidate(path, AccountRuntimeSource.Installed)).OfType<AccountRuntimeCandidate>().ToArray();
            var preferred = ManagedAccountRuntimePolicy.Select(installed.Append(packaged), null, extensions);
            if (installed.Any(candidate => extensions.All(extension => extension.Supports(candidate.Build.Version))))
                TestAssert.That(preferred?.Source == AccountRuntimeSource.Installed, "The native resolver ignored a compatible installed application.");
            File.WriteAllText(Path.Combine(root, "compatibility.ini"), "[Compatibility]\nLastVersion=158.0.1_20261019221403\n");
            var required = ManagedAccountRuntimePolicy.ProfileRequirement(root);
            TestAssert.That(ManagedAccountRuntimePolicy.Select(installed.Append(packaged), required, extensions) is null,
                "The reported profile could still reach an older/incompatible application.");
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
            { packaged = packaged.Build.Version.ToString(), staged = staged!.Build.Version.ToString(),
                signed_candidates_verified = true, tampered_executable_rejected = true,
                installed_candidates = installed.Length, installed_preference = preferred?.Source.ToString(),
                profile_downgrade_rejected = true, staged_provider_compatible = extensions.All(extension => extension.Supports(staged.Build.Version)) }));
            return 0;
        }
        finally { Directory.Delete(root, true); }
    }

    internal static void Run()
    {
        static AccountRuntimeCandidate Candidate(string version, AccountRuntimeSource source = AccountRuntimeSource.Installed, bool trusted = true) =>
            new(source + "/thunderbird.exe", MozillaRuntimeBuild.Parse(version), source, trusted);
        var required = MozillaRuntimeBuild.Parse("158.0.1_20261019221403");
        var extensions = new[] { AccountAddonCompatibility.Parse("153.0", "158.*"), AccountAddonCompatibility.Parse("153.0", "158.*") };
        var oldPackage = Candidate("155.0", AccountRuntimeSource.Managed);
        var oldInstalled = Candidate("156.0");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([oldInstalled, oldPackage], required, extensions) is null,
            "A downgraded Thunderbird was selected for the reported 158 profile.");
        var managed = Candidate("158.0.1_20261019221403", AccountRuntimeSource.Managed);
        var installed = Candidate("158.0.2_20261021221403");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([oldPackage, managed, installed], required, extensions) == installed,
            "An installed compatible Thunderbird was not preferred.");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([Candidate("159.0"), managed], required, extensions) == managed,
            "A system upgrade beyond provider compatibility was allowed to upgrade the managed profile.");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([Candidate("158.0.2", trusted: false), managed], required, extensions) == managed,
            "An untrusted installed executable displaced the verified managed runtime.");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([Candidate("158.0.1_20261018221403"), managed], required, extensions) == managed,
            "An older same-version build was selected for a newer profile build.");
        TestAssert.That(ManagedAccountRuntimePolicy.Select([managed], required,
            [AccountAddonCompatibility.Parse("153.0", "157.*")]) is null,
            "Updating Thunderbird silently bypassed the actual extension maximum.");
        TestAssert.That(MozillaRuntimeBuild.Parse("158.0").CompareTo(MozillaRuntimeBuild.Parse("158.0.0")) == 0,
            "Equivalent Mozilla version forms compared differently.");
        TestAssert.That(AccountAddonCompatibility.Parse("153.0", "158.0.*").Supports(MozillaRuntimeBuild.Parse("158.0.9").Version) &&
            !AccountAddonCompatibility.Parse("153.0", "158.0.*").Supports(MozillaRuntimeBuild.Parse("158.1").Version),
            "Wildcard extension bounds permitted an unsupported version.");
        TestAssert.That(ManagedAccountRuntimePolicy.UpdateVersion("158.0.1", required, oldPackage.Build, extensions) == "158.0.1",
            "The supported current release was not selected for component repair.");
        TestAssert.That(ManagedAccountRuntimePolicy.UpdateVersion("159.0", MozillaRuntimeBuild.Parse("158.0.2"), managed.Build, extensions) == "158.0.2",
            "An unsupported newer major blocked repair of a known supported profile version.");
        TestAssert.That(ManagedAccountRuntimePolicy.UpdateVersion("159.0", null, managed.Build, extensions) == "158.0.1" &&
            ManagedAccountRuntimePolicy.UpdateVersion("155.0", required, managed.Build, extensions) == "158.0.1",
            "Component repair selected an unsupported release or downgraded the packaged component.");
        TestAssert.Throws<InvalidDataException>(() => ManagedAccountRuntimePolicy.UpdateVersion("159.0", required, oldPackage.Build,
            [AccountAddonCompatibility.Parse("153.0", "157.*")]), "Component repair ignored the actual provider maximum.");
        var root = Path.Combine(Path.GetTempPath(), "magnolie-runtime-policy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            TestAssert.That(ManagedAccountRuntimePolicy.ProfileRequirement(root) is null, "An unused profile invented a version requirement.");
            var path = Path.Combine(root, "compatibility.ini");
            var content = "[Compatibility]\nLastVersion=158.0.1_20261019221403\nLastOSABI=WINNT_x86_64-msvc\n";
            File.WriteAllText(path, content);
            TestAssert.That(ManagedAccountRuntimePolicy.ProfileRequirement(root) == required && File.ReadAllText(path) == content,
                "Profile compatibility inspection changed or misread existing metadata.");
            foreach (var platformBuild in new[] { "20261019221403", "20261018221403" })
            {
                content = $"[Compatibility]\nLastVersion=158.0.1_20261019221403/{platformBuild}\nLastOSABI=WINNT_x86_64-msvc\n";
                File.WriteAllText(path, content);
                TestAssert.That(ManagedAccountRuntimePolicy.ProfileRequirement(root) == required && File.ReadAllText(path) == content,
                    "The real Mozilla application/platform build format blocked startup or changed the profile.");
            }
            foreach (var invalid in new[] { "[Compatibility]\n", "[Compatibility]\nLastVersion=invalid\n",
                "[Compatibility]\nLastVersion=158.0\nLastVersion=155.0\n",
                "[Compatibility]\nLastVersion=158.0.1_20261019221403/invalid\n",
                "[Compatibility]\nLastVersion=158.0.1_20261019221403/20261019221403/20261019221403\n" })
            {
                File.WriteAllText(path, invalid);
                TestAssert.Throws<InvalidDataException>(() => ManagedAccountRuntimePolicy.ProfileRequirement(root),
                    "Malformed profile metadata was treated as permission to downgrade.");
                TestAssert.That(File.ReadAllText(path) == invalid, "Invalid compatibility metadata was silently repaired/reset.");
            }
        }
        finally { Directory.Delete(root, true); }
    }
}
