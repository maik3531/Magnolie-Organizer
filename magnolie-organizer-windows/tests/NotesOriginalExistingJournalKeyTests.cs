using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows.Tests;

internal static partial class NotesOriginalChoiceStoreTests
{
    internal static void ExistingJournalKey(string root)
    {
        var modes = new[] { "missing-root", "missing-key", "roundtrip", "loss", "replacement", "bad-base64", "whitespace", "bad-length",
            "unprotect-fail", "changed-read", "read-only-layout", "link-key" };
        foreach (var mode in modes)
        {
            using var h = new Fixture(Path.Combine(root, mode)); h.Store.Approve([h.Choice]);
            using var protector = new Protector();
            var paths = new WindowsPaths(Path.Combine(h.Root, "native-profile"));
            var seed = new ContactSourcePrivateFiles(paths.Telefon, controlledUnix: !OperatingSystem.IsWindows());
            var returnedSecrets = new List<byte[]>();
            byte[] Unprotect(byte[] encrypted)
            {
                var secret = OperatingSystem.IsWindows()
                    ? ProtectedData.Unprotect(encrypted, Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)
                    : protector.Unprotect(encrypted);
                returnedSecrets.Add(secret); return secret;
            }
            void Seed(byte value = 42, int length = 32, bool wrongEntropy = false)
            {
                var secret = Enumerable.Repeat(value, length).ToArray(); byte[]? encrypted = null;
                try
                {
                    encrypted = OperatingSystem.IsWindows()
                        ? ProtectedData.Protect(secret, wrongEntropy ? null : Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)
                        : protector.Protect(secret);
                    using (var directory = seed.Open(create: true)!) directory.Write(".key.dpapi", Convert.ToBase64String(encrypted), 4096);
                    // Owned synthetic seed only; the production backend cannot write this leaf.
                    File.Move(Path.Combine(paths.Telefon, ".key.dpapi"), paths.TelefonStorageKey, overwrite: true);
                }
                finally { CryptographicOperations.ZeroMemory(secret); if (encrypted is not null) CryptographicOperations.ZeroMemory(encrypted); }
            }
            var backend = new NotesOriginalExistingJournalKey(paths, controlledUnix: !OperatingSystem.IsWindows(),
                controlledUnprotect: OperatingSystem.IsWindows() ? null : Unprotect);
            if (mode is "missing-root" or "missing-key")
            {
                if (mode == "missing-key") using (seed.Open(create: true)) { }
                TestAssert.That(backend.ReadExisting() is null && !File.Exists(paths.TelefonStorageKey) && !File.Exists(paths.TelefonDatabase) &&
                    (mode != "missing-root" || !Directory.Exists(paths.Root)), "Missing existing key created storage, database or fallback secret");
                continue;
            }
            Seed(length: mode == "bad-length" ? 31 : 32, wrongEntropy: mode == "unprotect-fail");
            var original = File.ReadAllText(paths.TelefonStorageKey);
            var narrow = new ContactSourcePrivateFiles(paths.Telefon, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.ExistingPhoneStorageKey);
            TestAssert.Throws<InvalidOperationException>(() => narrow.Open(create: true), "Read-only key layout created a root");
            using (var directory = narrow.Open()!)
            {
                TestAssert.Throws<InvalidOperationException>(() => directory.Write("storage.key", "replacement", 4096), "Read-only key layout wrote a key");
                TestAssert.Throws<InvalidOperationException>(() => directory.Delete("storage.key"), "Read-only key layout deleted a key");
                TestAssert.Throws<ArgumentException>(() => directory.Read(".key.dpapi", 4096), "Existing-key reader admitted consent leaf");
                TestAssert.Throws<ArgumentException>(() => directory.Read(".journal-key", 4096), "Existing-key reader admitted journal identity");
                TestAssert.Throws<ArgumentOutOfRangeException>(() => directory.Read("storage.key", 4097), "Key read budget expanded");
            }
            if (mode == "read-only-layout")
            {
                using (var consent = new ContactSourcePrivateFiles(paths.Telefon, controlledUnix: !OperatingSystem.IsWindows()).Open()!)
                    TestAssert.Throws<ArgumentException>(() => consent.Read("storage.key", 4096), "Consent layout widened to storage keys");
                using (var journal = new ContactSourcePrivateFiles(paths.Telefon, controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal).Open()!)
                    TestAssert.Throws<ArgumentException>(() => journal.Read("storage.key", 4096), "Journal layout widened to storage keys");
            }
            if (mode == "bad-base64") File.WriteAllText(paths.TelefonStorageKey, "not-base64");
            if (mode == "whitespace") File.WriteAllText(paths.TelefonStorageKey, original + "\n");
            if (mode == "unprotect-fail") protector.Unavailable = true;
            if (mode == "changed-read")
                backend = new(paths, controlledUnix: true, controlledUnprotect: encrypted => { var plain = Unprotect(encrypted); Seed(43); return plain; });
            if (mode == "link-key")
            {
                var other = Path.Combine(h.Root, "other-owned-key");
                if (OperatingSystem.IsWindows()) TestAssert.That(CreateStorageHardLink(other, paths.TelefonStorageKey, IntPtr.Zero), "Synthetic key hardlink setup failed");
                else { File.Move(paths.TelefonStorageKey, other); File.CreateSymbolicLink(paths.TelefonStorageKey, other); }
            }
            if (mode is "bad-base64" or "whitespace" or "bad-length" or "unprotect-fail" or "changed-read" or "link-key")
                Hold(() => backend.ReadExisting());
            else
            {
                var raw = Enumerable.Repeat((byte)42, 32).ToArray();
                var expected = HKDF.DeriveKey(HashAlgorithmName.SHA256, raw, 32,
                    info: Encoding.UTF8.GetBytes("Magnolie/notes-original/journal/from-existing-phone-storage/windows/v1"));
                var first = backend.ReadExisting()!; var second = backend.ReadExisting()!;
                TestAssert.That(first.AsSpan().SequenceEqual(expected) && first.AsSpan().SequenceEqual(second) && !first.AsSpan().SequenceEqual(raw) && !ReferenceEquals(first, second),
                    "Existing-key journal derivation lost purpose isolation, stability or owned-copy semantics");
                CryptographicOperations.ZeroMemory(raw); CryptographicOperations.ZeroMemory(expected); CryptographicOperations.ZeroMemory(first); CryptographicOperations.ZeroMemory(second);
                if (mode is "loss" or "replacement")
                {
                    var boundary = new ContactSourcePrivateFiles(Path.Combine(h.Root, "requests"), controlledUnix: !OperatingSystem.IsWindows(), layout: ContactSourcePrivateFiles.Layout.NotesReturnJournal);
                    var requests = new NotesOriginalRequestIntents(boundary, backend.ReadExisting);
                    requests.Seal(h.Choice.CreatePending()!);
                    var physical = Directory.GetFiles(Path.Combine(h.Root, "requests"), "p-*.json").Single(); var before = File.ReadAllBytes(physical);
                    if (mode == "loss") File.Delete(paths.TelefonStorageKey); else Seed(43);
                    Hold(() => requests.LoadPhysical(Path.GetFullPath(h.Host.DataPath), "chosen-private-id"));
                    TestAssert.That(File.ReadAllBytes(physical).AsSpan().SequenceEqual(before) && (mode != "loss" || !File.Exists(paths.TelefonStorageKey)),
                        "Existing-key loss/replacement reconstructed a key or released physical history");
                }
                else TestAssert.That(File.ReadAllText(paths.TelefonStorageKey) == original, "Read-only adapter rewrote native storage key");
            }
            TestAssert.That(returnedSecrets.All(value => value.All(item => item == 0)) && protector.Secrets.All(value => value.All(item => item == 0)) &&
                !File.Exists(paths.TelefonDatabase), "Key backend retained owned plaintext or instantiated phone database");
        }
        if (!OperatingSystem.IsWindows())
            TestAssert.Throws<PlatformNotSupportedException>(() => new NotesOriginalExistingJournalKey(new WindowsPaths(root)), "Existing-key adapter enabled Unix production fallback");
        else TestAssert.Throws<ArgumentException>(() => new NotesOriginalExistingJournalKey(new WindowsPaths(root), controlledUnprotect: value => value), "Production key backend admitted arbitrary unprotect callback");
        TestAssert.Throws<ArgumentException>(() => new NotesOriginalExistingJournalKey(new WindowsPaths("relative-native-profile"), controlledUnix: true), "Existing-key backend guessed an implicit current-directory profile");
        Console.WriteLine($"Notes existing independent journal key: {modes.Length} synthetic read-only/DPAPI-or-controlled cases passed (no key/store/database creation).");
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateHardLinkW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateStorageHardLink(string path, string existing, IntPtr security);
}
