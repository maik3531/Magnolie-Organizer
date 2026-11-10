using System.Security.AccessControl;
using System.Runtime.Versioning;

namespace MagnolieOrganizer.Windows.Tests;

[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioStagingTests
{
    // In-memory ACL parsing only: never call Prepare, request elevation, create
    // ProgramData directories, execute helpers or install any audio driver.
    internal static Task ProtectedAclPolicyAsync()
    {
        static bool Allowed(string sddl, bool parent = false) =>
            PhoneCameraAudioStaging.AllowsProtectedDirectory(new RawSecurityDescriptor(sddl), parent);
        const string prefix = "O:BAG:BAD:P";
        TestAssert.That(Allowed(prefix + "(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)"), "Own protected staging ACL refused");
        TestAssert.That(Allowed("O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)"), "System-owned staging ACL refused");
        foreach (var sid in new[] { "BU", "WD", "AU" })
        foreach (var rights in new[] { "FW", "FA", "WD", "WO", "DC", "SD", "0x00000002", "0x00000004", "0x00000010", "0x00000100" })
            TestAssert.That(!Allowed(prefix + "(A;;FA;;;BA)(A;;" + rights + ";;;" + sid + ")"), "Unprivileged mutation granted: " + rights + "/" + sid);
        TestAssert.That(!Allowed("O:BUG:BUD:P(A;;FA;;;BA)"), "Unprivileged owner admitted");
        TestAssert.That(!Allowed("O:BAG:BA"), "Missing DACL admitted");
        TestAssert.That(Allowed(prefix + "(A;;FA;;;BA)(A;;0x00000002;;;BU)", parent: true) &&
            !Allowed(prefix + "(A;;FA;;;BA)(A;;0x00000040;;;BU)", parent: true), "ProgramData sibling-create/delete distinction lost");
        TestAssert.That(Allowed("O:SYG:SYD:PAI(A;OICIIO;GA;;;CO)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)(A;CI;0x116;;;BU)", parent: true),
            "Observed standard Windows ProgramData ACL refused despite mandatory held no-write/no-delete sharing");
        return Task.CompletedTask;
    }
}
