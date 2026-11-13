using System.Runtime.Versioning;
using System.Security.AccessControl;
using Microsoft.Win32;

namespace MagnolieOrganizer.Windows.Tests;

[SupportedOSPlatform("windows")]
internal static class PhoneCameraSourceRegistrationTests
{
    // Memory-only policies. Never call InstallCurrent/CreateCurrent, open keys
    // for writing, prepare ProgramData, load DLLs or register any COM source.
    internal static Task RegistryAclPolicyAsync()
    {
        static bool Allowed(string text) => PhoneCameraSourceRegistration.AllowsRegistrySecurity(new RawSecurityDescriptor(text));
        const string prefix = "O:BAG:BAD:P";
        TestAssert.That(Allowed(prefix + "(A;CI;KA;;;SY)(A;CI;KA;;;BA)(A;CI;KR;;;BU)"), "Protected class ACL refused");
        TestAssert.That(Allowed("O:SYG:SYD:AI(A;ID;KR;;;BU)(A;CIIOID;GR;;;BU)(A;ID;KA;;;BA)(A;ID;KA;;;SY)(A;CIIOID;GA;;;CO)(A;ID;KR;;;AC)"),
            "Observed standard registry parent policy refused");
        TestAssert.That(Allowed(prefix + "(A;;KA;;;BA)(A;;0x00000010;;;BU)"), "KEY_NOTIFY incorrectly treated as file write");
        foreach (var sid in new[] { "BU", "WD", "AU", "AC", "S-1-5-21-1-2-3-1001" })
        foreach (var rights in new[] { "KW", "KA", "GA", "GW", "SD", "WD", "WO", "0x00000002", "0x00000004", "0x00000020" })
            TestAssert.That(!Allowed(prefix + "(A;;KA;;;BA)(A;;" + rights + ";;;" + sid + ")"), "Unprivileged registry mutation admitted: " + rights + "/" + sid);
        TestAssert.That(!Allowed("O:BUG:BUD:P(A;;KA;;;BA)"), "Unprivileged class owner admitted");
        TestAssert.That(!Allowed("O:BAG:BA"), "Null DACL admitted");
        return Task.CompletedTask;
    }
    internal static Task ExactReadbackAsync()
    {
        const string path = "C:\\ProgramData\\Magnolie-Webcam-Source\\fixture\\Magnolie.PhoneCameraSource.x64.dll";
        var classes = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue> { [""] = new(RegistryValueKind.String, "Magnolie Phone Camera Source") };
        var server = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue> {
            [""] = new(RegistryValueKind.String, path), ["ThreadingModel"] = new(RegistryValueKind.String, "Both") };
        bool Matches(Dictionary<string, PhoneCameraSourceRegistration.RegistryValue> cls, string[] children,
            Dictionary<string, PhoneCameraSourceRegistration.RegistryValue> dll, string[] grandchildren, string expected = path) =>
            PhoneCameraSourceRegistration.MatchesRegistration(cls, children, dll, grandchildren, expected);
        TestAssert.That(Matches(classes, ["InprocServer32"], server, []), "Exact owned registration refused");
        foreach (var mutation in new Action<Dictionary<string, PhoneCameraSourceRegistration.RegistryValue>>[] {
            d => d[""] = new(RegistryValueKind.String, "C:\\Users\\fixture\\external.dll"),
            d => d[""] = new(RegistryValueKind.ExpandString, path),
            d => d["ThreadingModel"] = new(RegistryValueKind.String, "Free"),
            d => d["ThreadingModel"] = new(RegistryValueKind.MultiString, new[] { "Both" }),
            d => d.Remove("ThreadingModel"), d => d["foreign"] = new(RegistryValueKind.String, "keep") })
        {
            var changed = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue>(server); mutation(changed);
            TestAssert.That(!Matches(classes, ["InprocServer32"], changed, []), "Foreign/incomplete registry readback accepted");
        }
        TestAssert.That(!Matches(classes, [], server, []) && !Matches(classes, ["InprocServer32", "foreign"], server, []) &&
            !Matches(classes, ["InprocServer32"], server, ["foreign"]) && !Matches(classes, ["InprocServer32"], server, [], ""), "Foreign subkey/empty path accepted");
        var extra = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue>(classes) { ["foreign"] = new(RegistryValueKind.String, "keep") };
        TestAssert.That(!Matches(extra, ["InprocServer32"], server, []), "Foreign class value ignored");
        // This actual test assembly has no embedded Source: ordinary readback
        // must return before opening native keys/files, never find a sidecar or
        // attempt the elevated installation path. This is NOT installed acceptance.
        TestAssert.That(PhoneCameraSourcePayload.LoadEmbedded() is null &&
            PhoneCameraSourceRegistration.HoldInstalledCurrent() is null,
            "Absent embedded Source acquired an installed/adjacent fallback");
        foreach (var kind in new[] { RegistryValueKind.ExpandString, RegistryValueKind.MultiString, RegistryValueKind.Binary })
        {
            var changed = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue>(classes) {
                [""] = new(kind, "Magnolie Phone Camera Source") };
            TestAssert.That(!Matches(changed, ["InprocServer32"], server, []), "Class readback lost exact value kind");
        }
        var before = new Dictionary<string, PhoneCameraSourceRegistration.RegistryValue>(server);
        TestAssert.That(!Matches(classes, ["InprocServer32"], server, [], path + ".foreign") &&
            server.Count == before.Count && server.All(pair => before[pair.Key] == pair.Value),
            "Read-only mismatch rewrote the original registration snapshot");
        return Task.CompletedTask;
    }
    internal static Task PersistentFileOwnerAsync()
    {
        var descriptor = new RawSecurityDescriptor(PhoneCameraAudioStaging.PersistentFileSecurity);
        TestAssert.That(descriptor.Owner?.Value == "S-1-5-32-544" && PhoneCameraAudioParentModule.AllowsProtectedImage(descriptor),
            "Actual persistent-file creation policy lacks trusted owner or write protection");
        var userOwned = PhoneCameraAudioStaging.PersistentFileSecurity.Replace("O:BA", "O:S-1-5-21-1-2-3-1001", StringComparison.Ordinal);
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor(userOwned)),
            "User-owned persistent image accepted despite protected DACL");
        TestAssert.That(!PhoneCameraSourceRegistration.AllowsRegistrySecurity(descriptor),
            "FILE_EXECUTE was mistaken for allowed registry KEY_CREATE_LINK");
        return Task.CompletedTask;
    }
}
