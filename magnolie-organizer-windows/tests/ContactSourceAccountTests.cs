using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

// Native-account prerequisite for #621 only. Synthetic local files and an
// explicit controlled protector; no DPAPI/OS dialog/provider operation claimed.
internal static class ContactSourceAccountTests
{
    private sealed class Protector : ISecretProtector
    {
        internal byte[]? Plain, Cipher;
        internal Action? DuringRead;
        internal bool Unavailable;
        internal int SizeOverride = -1, Reads;
        public byte[] Protect(byte[] plain) => plain.Select(value => (byte)(value ^ 0x5a)).ToArray();
        public byte[] Unprotect(byte[] cipher)
        {
            Reads++; Cipher = cipher;
            if (Unavailable) throw new CryptographicException("Controlled unavailable credential protection");
            Plain = SizeOverride >= 0 ? Enumerable.Repeat((byte)0x55, SizeOverride).ToArray() : Protect(cipher);
            DuringRead?.Invoke();
            return Plain;
        }
    }

    internal static void Run()
    {
        foreach (var mode in new[] { "success", "new-instance", "renewed-credential", "different-user", "different-server",
            "different-provider", "different-slot", "disabled", "missing-credential", "corrupt-credential", "unavailable-protector",
            "empty-secret", "oversized-secret", "changed-during-read", "no-config", "default-no-files" })
        {
            var root = Path.Combine(Path.GetTempPath(), "magnolie-contact-account-" + Guid.NewGuid().ToString("N"));
            var settingsPath = Path.Combine(root, "settings.json"); var credentialPath = Path.Combine(root, "credential.dat");
            var protector = new Protector();
            var store = new NextcloudMailboxSettingsStore(settingsPath, credentialPath, protector);
            try
            {
                if (mode == "default-no-files")
                {
                    TestAssert.Throws<UnauthorizedAccessException>(() => store.ReadContactSourceAccount(), "Missing native account granted credential access");
                    TestAssert.That(!Directory.Exists(root) && protector.Reads == 0, "Default account observation created files or accessed credentials");
                }
                else
                {
                    var settings = new NextcloudMailboxSettings(true, false, "https://source.invalid/nc", "synthetic") { AccountType = "generic-dav" };
                    store.Save(settings); store.SetApplicationPassword("synthetic-only-account-secret");
                    var before = store.ReadContactSourceAccount();
                    TestAssert.That(before.Settings == settings && before.Revision == store.ReadSnapshot().Revision,
                        "Native usable account did not match its actual current revision/settings");
                    TestAssert.That(!before.Identity.Contains("synthetic-only-account-secret", StringComparison.Ordinal) &&
                        !before.Identity.Contains("protectedCredential", StringComparison.Ordinal) &&
                        !before.Identity.Contains(before.Revision, StringComparison.Ordinal),
                        "Nonsecret native identity retained credentials or a process-local verifier");
                    TestAssert.That(protector.Plain?.All(value => value == 0) == true && protector.Cipher?.All(value => value == 0) == true,
                        "Native account observation retained credential buffers");
                    var reads = protector.Reads;
                    if (mode == "new-instance") store = new(settingsPath, credentialPath, protector);
                    if (mode == "renewed-credential") store.SetApplicationPassword("renewed-synthetic-only-secret");
                    if (mode == "different-user") store.Save(settings with { User = "other-synthetic" });
                    if (mode == "different-server") store.Save(settings with { ServerBase = "https://other.invalid/nc" });
                    if (mode == "different-provider") store.Save(settings with { AccountType = "nextcloud" });
                    if (mode == "different-slot")
                    {
                        var other = Path.Combine(root, "other-credential.dat"); File.Copy(credentialPath, other);
                        store = new(settingsPath, other, protector);
                    }
                    if (mode == "disabled") store.Save(settings with { DavActive = false });
                    if (mode == "missing-credential") store.ClearApplicationPassword();
                    if (mode == "corrupt-credential") File.WriteAllText(credentialPath, "not-base64");
                    if (mode == "unavailable-protector") protector.Unavailable = true;
                    if (mode == "empty-secret") protector.SizeOverride = 0;
                    if (mode == "oversized-secret") protector.SizeOverride = 16 * 1024 + 1;
                    if (mode == "changed-during-read") protector.DuringRead = () => store.Save(settings with { User = "changed-during-native-read" });
                    if (mode == "no-config") File.Delete(settingsPath);
                    if (mode is "disabled" or "missing-credential" or "corrupt-credential" or "unavailable-protector" or
                        "empty-secret" or "oversized-secret" or "changed-during-read" or "no-config")
                    {
                        Exception? failure = null;
                        try { store.ReadContactSourceAccount(); } catch (Exception error) { failure = error; }
                        TestAssert.That(failure is not null && !failure.Message.Contains("synthetic-only-account-secret", StringComparison.Ordinal),
                            "Unavailable or concurrently changed actual credentials granted native account access");
                        if (mode is "disabled" or "missing-credential" or "corrupt-credential" or "no-config")
                            TestAssert.That(protector.Reads == reads, "Unavailable native settings unnecessarily opened credentials");
                    }
                    else
                    {
                        var after = store.ReadContactSourceAccount();
                        TestAssert.That((after.Identity == before.Identity) == (mode is "success" or "new-instance" or "renewed-credential"),
                            "Native nonsecret account/slot identity changed on renewal or survived a different account");
                        TestAssert.That((after.Revision == before.Revision) == (mode is "success" or "new-instance"),
                            "Fresh account revision did not preserve the exact actual current credential context");
                    }
                    TestAssert.That(protector.Plain?.All(value => value == 0) == true && protector.Cipher?.All(value => value == 0) == true,
                        "Failed or successful native account read retained credential buffers");
                }
                Console.WriteLine("CONTACT SOURCE NATIVE ACCOUNT PASS " + mode);
            }
            finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
        }
    }
}
