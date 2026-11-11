using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;

namespace MagnolieOrganizer.Windows.Tests;

[SupportedOSPlatform("windows")]
internal static class PhoneCameraAudioParentModuleTests
{
    internal static Task FixedLayoutAsync()
    {
        TestAssert.That(PhoneCameraAudioParentModule.IsInstalledProcessLayout(@"C:\Program Files\Magnolie\Magnolie Organizer.exe", @"C:\Program Files\Magnolie\"), "Supported original layout refused");
        foreach (var process in new[] { @"\\host\share\Magnolie Organizer.exe", @"C:Magnolie Organizer.exe", @"C:\Magnolie Organizer.exe",
            @"C:\safe\dotnet.exe", @"C:\safe\foreign.exe", @"C:/safe/Magnolie Organizer.exe", @"C:\safe\..\Magnolie Organizer.exe",
            @"C:\safe\\Magnolie Organizer.exe", @"C:\safe.\Magnolie Organizer.exe", @"C:\safe\Magnolie Organizer.exe:alternate" })
            TestAssert.That(!PhoneCameraAudioParentModule.IsInstalledProcessLayout(process, @"C:\safe"), "Nonoriginal/alternate process layout accepted: " + process);
        TestAssert.That(!PhoneCameraAudioParentModule.IsInstalledProcessLayout(@"C:\safe\Magnolie Organizer.exe", @"C:\foreign"), "Assembly base directory substituted process sibling");
        return Task.CompletedTask;
    }
    internal static Task ProtectedAclAsync()
    {
        foreach (var owner in new[] { "BA", "SY", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464" })
            TestAssert.That(PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor("O:" + owner + "G:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;BU)")), "Trusted immutable owner/read-only user ACL refused");
        foreach (var rights in new[] { "GW", "GA", "0x2", "0x4", "0x10", "0x40", "0x100", "SD", "WD", "WO" })
            TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor("O:BAG:BAD:P(A;;" + rights + ";;;BU)(A;;FA;;;BA)")), "Unprivileged mutation accepted: " + rights);
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor("O:BUG:BAD:P(A;;FRFX;;;BU)")), "Untrusted owner accepted");
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent,
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), null, null, null)), "Null DACL accepted");
        return Task.CompletedTask;
    }
    internal static Task AmbiguousAclAsync()
    {
        var admin = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
        var users = new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null);
        var acl = new RawAcl(2, 130);
        for (int i = 0; i < 129; ++i) acl.InsertAce(i, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, 0x120089, users, false, null));
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent, admin, null, null, acl)), "Unbounded ACL accepted");
        acl = new RawAcl(2, 1); acl.InsertAce(0, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, 2, users, true, []));
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor(ControlFlags.DiscretionaryAclPresent, admin, null, null, acl)), "Conditional callback ACE accepted");
        TestAssert.That(!PhoneCameraAudioParentModule.AllowsProtectedImage(new RawSecurityDescriptor("O:BAG:BAD:P(D;;GW;;;BU)(A;;GW;;;BU)")), "Deny ACE compensated untrusted mutation grant");
        return Task.CompletedTask;
    }
    private static void Refused(Action action, string? expected = null)
    {
        try { action(); throw new Exception("Actual unprotected/reparse image admitted"); }
        catch (Exception e) when (e is UnauthorizedAccessException or System.IO.IOException or Win32Exception)
        { TestAssert.That(expected is null || e.Message == expected, "Unexpected held-file refusal: " + e.Message); }
    }
    internal static Task ActualWritableFileAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-parent-module-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        var path = Path.Combine(root, PhoneCameraAudioParentPayload.Filename);
        try
        {
            File.WriteAllText(path, "Not an executable; must be refused BEFORE any load");
            Refused(() => PhoneCameraAudioParentModule.ProbeHeldPath(path, directory: false, ancestors: false), "webcam_audio_parent_protected_image_required");
            Refused(() => PhoneCameraAudioParentModule.ProbeHeldPath(path, directory: false, ancestors: true));
            File.WriteAllText(path, "Admission released every own file/ancestor handle after failure");
        }
        finally { File.Delete(path); Directory.Delete(root); }
        return Task.CompletedTask;
    }
    internal static async Task ActualJunctionAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-parent-junction-" + Guid.NewGuid().ToString("N"));
        var target = Path.Combine(root, "target"); var link = Path.Combine(root, "link"); Directory.CreateDirectory(target);
        try
        {
            var start = new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe"))
                { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            // cmd built-ins do not use the C-runtime quoting/escaping applied
            // by ArgumentList to a single compound command argument.
            start.Arguments = "/d /c mklink /J \"" + link + "\" \"" + target + "\"";
            using var process = Process.Start(start)!;
            var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
            TestAssert.That(process.ExitCode == 0, "Own junction fixture creation failed: " + await output + await error);
            Refused(() => PhoneCameraAudioParentModule.ProbeHeldPath(link, directory: true, ancestors: false), "webcam_audio_parent_no_reparse_required");
        }
        finally
        {
            if (Directory.Exists(link)) Directory.Delete(link); // Remove only own junction, never its target recursively.
            Directory.Delete(target); Directory.Delete(root);
        }
    }
}
