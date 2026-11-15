using System.Security.Cryptography;
using System.Text;

namespace MagnolieOrganizer.Windows;

// Read an ALREADY EXISTING independent phone-storage secret, without constructing
// TelefonStore/creating a key or database. Derive a separate fixed journal domain;
// never use the native choice/consent key or book encryption key as history key.
// No startup registration. Native-owned paths only; no imported profile lookup.
internal sealed class NotesOriginalExistingJournalKey
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("magnolie-phone-storage-v1");
    private static readonly byte[] Domain = Encoding.UTF8.GetBytes("Magnolie/notes-original/journal/from-existing-phone-storage/windows/v1");
    private readonly ContactSourcePrivateFiles files;
    private readonly Func<byte[], byte[]> unprotect;

    internal NotesOriginalExistingJournalKey(WindowsPaths nativePaths, bool controlledUnix = false,
        Func<byte[], byte[]>? controlledUnprotect = null)
    {
        ArgumentNullException.ThrowIfNull(nativePaths);
        if (!Path.IsPathFullyQualified(nativePaths.Telefon)) throw new ArgumentException("notes_existing_key_native_root_required");
        if (!OperatingSystem.IsWindows() && !controlledUnix) throw new PlatformNotSupportedException();
        files = new(Path.GetFullPath(nativePaths.Telefon), controlledUnix: controlledUnix,
            layout: ContactSourcePrivateFiles.Layout.ExistingPhoneStorageKey);
        if (controlledUnprotect is not null && !controlledUnix)
            throw new ArgumentException("notes_key_test_unprotect_requires_controlled_test");
        unprotect = controlledUnprotect ?? NativeUnprotect;
    }
    private static byte[] NativeUnprotect(byte[] encrypted)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        return ProtectedData.Unprotect(encrypted, Entropy, DataProtectionScope.CurrentUser);
    }
    private string? Envelope()
    {
        using var directory = files.Open();
        return directory?.Read("storage.key", 4096);
    }
    internal byte[]? ReadExisting()
    {
        var text = Envelope(); if (text is null) return null; // No key/root/database creation or fallback.
        byte[]? encrypted = null, secret = null;
        try
        {
            encrypted = Convert.FromBase64String(text);
            if (encrypted.Length == 0 || Convert.ToBase64String(encrypted) != text)
                throw new InvalidDataException("notes_existing_key_envelope_invalid");
            secret = unprotect(encrypted); // No source/application callback while a private file session is locked.
            if (secret.Length != 32) throw new CryptographicException("notes_existing_key_length_invalid");
            if (Envelope() != text) throw new InvalidOperationException("notes_existing_key_changed_during_read");
            return MagnolienbaumCrypto.HkdfSha256(secret, null, Domain, 32); // Owned derived copy; consumer must clear it.
        }
        finally
        {
            if (encrypted is not null) CryptographicOperations.ZeroMemory(encrypted);
            if (secret is not null) CryptographicOperations.ZeroMemory(secret);
        }
    }
}
