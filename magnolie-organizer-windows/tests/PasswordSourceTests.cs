using System.Security.Cryptography;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class PasswordSourceTests
{
    internal static Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-password-source-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var encryption = new EncryptionService();
        try
        {
            var path = Path.Combine(root, "owned.json");
            const string plain = "{\"owned\":\"🌸é\\n\"}";
            var store = new AtomicStore();
            store.WriteRecoverableJson(path, plain);
            var first = PasswordSource.Read(store, path, encryption);
            TestAssert.That(!first.Encrypted && first.Plain == plain && first.BookRevision == "e8ee8f96c8396a7489b1c6575214023125205dc4ae474c0be57d535df8859f1e",
                "Native password revision differs from the actual JavaScript canonical-string golden.");
            first.Require(first.StateRevision, first.BookRevision);
            void MustReject(Action action)
            {
                var rejected = false;
                try { action(); } catch (InvalidOperationException error) when (error.Message == "mcp_conflict") { rejected = true; }
                TestAssert.That(rejected, "Native password source accepted a stale precondition.");
            }
            MustReject(() => first.Require(new string('0', 64), first.BookRevision));
            MustReject(() => first.Require(first.StateRevision, new string('0', 64)));
            var envelope = encryption.Enable(plain, "owned-source-password");
            store.WriteRecoverableJson(path, envelope);
            var encrypted = PasswordSource.Read(store, path, encryption);
            TestAssert.That(encrypted.Encrypted && encrypted.BookRevision == first.BookRevision && encrypted.StateRevision != first.StateRevision,
                "Enabling encryption lost content identity or retained the plaintext file token.");
            MustReject(() => encrypted.Require(first.StateRevision, first.BookRevision));
            var changed = encryption.ChangePasswordWithSession(envelope, "owned-source-changed-password");
            store.WriteRecoverableJson(path, changed);
            var after = PasswordSource.Read(store, path, encryption);
            TestAssert.That(after.Plain == plain && after.BookRevision == first.BookRevision && after.StateRevision != encrypted.StateRevision,
                "Rewrapping the same book did not invalidate the old encryption-state token.");
            var unknownSession = new EncryptionService();
            var locked = false;
            try { PasswordSource.Read(store, path, unknownSession); } catch (CryptographicException) { locked = true; }
            TestAssert.That(locked, "A locked native reader exposed an authenticated password source.");
            store.WriteRecoverableJson(path, encryption.DisableWithSession(changed));
            var removed = PasswordSource.Read(store, path, encryption);
            TestAssert.That(!removed.Encrypted && removed.Plain == plain && removed.BookRevision == first.BookRevision,
                "Actual plaintext primary readback failed after password removal.");
        }
        finally { encryption.Clear(); Directory.Delete(root, true); }
        return Task.CompletedTask;
    }
}
