using System.Runtime.Versioning;
using System.Security.AccessControl;

namespace MagnolieOrganizer.Windows.Tests;

[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioBootstrapTests
{
    internal static Task ProtectedManagedInputsAsync()
    {
        static bool Allowed(string sddl) => PhoneCameraAudioBootstrapLease.ProtectedLoadInput(new RawSecurityDescriptor(sddl));
        TestAssert.That(Allowed("O:BAG:BAD:P(A;;FA;;;BA)(A;;FA;;;SY)(A;;FRFX;;;BU)"), "Protected installed bootstrap refused");
        const string trusted = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
        TestAssert.That(Allowed("O:" + trusted + "G:SYD:P(A;;FA;;;" + trusted + ")(A;;FRFX;;;BU)"), "Windows installer-owned immutable input refused");
        foreach (var rights in new[] { "GW", "GA", "WD", "WO", "SD", "0x2", "0x4", "0x10", "0x40", "0x100" })
            TestAssert.That(!Allowed("O:BAG:BAD:P(A;;FA;;;BA)(A;;" + rights + ";;;BU)"), "Mutable bootstrap input admitted: " + rights);
        TestAssert.That(!Allowed("O:BUG:BUD:P(A;;FRFX;;;BU)(A;;FA;;;BA)"), "User-owned bootstrap admitted despite owner ACL authority");
        TestAssert.That(!Allowed("O:BAG:BA"), "Missing bootstrap DACL admitted");
        if (string.Equals(Path.GetFileNameWithoutExtension(Environment.ProcessPath), "dotnet", StringComparison.OrdinalIgnoreCase))
            TestAssert.That(PhoneCameraAudioBootstrapLease.TryAcquire() is null, "Framework-dependent test host acquired native apphost elevation capability");
        return Task.CompletedTask; // Memory/read-only gate only; no UAC or files created.
    }
}
