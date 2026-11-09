using System.Security.Cryptography;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileCollectionRootsTests
{
    internal static Task WindowsTamperAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        foreach (var change in new[] { "pairing", "cipher", "missing-key" })
        {
            using var f = new DeviceFileConnectionMetadataTests.Fixture();
            var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
            File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
                Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
            var path = Path.Combine(f.Paths.Root, "source"); Directory.CreateDirectory(path);
            using var selected = DeviceFileNativeDirectory.OpenExisting(path);
            var saved = f.Store.AddNativeMediaCollectionRoot(f.Peer.Id, "images", selected, () => { });
            using var db = f.Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
            query.CommandText = "SELECT value FROM native_media_collection_roots WHERE root_id=$root"; query.Parameters.AddWithValue("$root", saved.Id);
            var cipher = (byte[])query.ExecuteScalar()!;
            if (change == "pairing") f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
            if (change == "missing-key") File.Delete(f.Paths.TelefonStorageKey);
            if (change == "cipher")
            {
                cipher[^1] ^= 1;
                using var update = db.CreateCommand(); update.CommandText = "UPDATE native_media_collection_roots SET value=$value WHERE root_id=$root";
                update.Parameters.AddWithValue("$value", cipher); update.Parameters.AddWithValue("$root", saved.Id); update.ExecuteNonQuery();
            }
            void Refuse(Action action)
            {
                try { action(); }
                catch (InvalidDataException) { return; }
                catch (CryptographicException) { return; }
                throw new InvalidOperationException("Invalid source-root ownership was accepted: " + change);
            }
            Refuse(() => f.Store.NativeMediaCollectionRoots(f.Peer.Id));
            Refuse(() => f.Store.AddNativeMediaCollectionRoot(f.Peer.Id, "images", selected, () => { }));
            TestAssert.That(((byte[])query.ExecuteScalar()!).SequenceEqual(cipher), "Root HOLD overwrote source evidence: " + change);
        }
        return Task.CompletedTask;
    }

    internal static Task WindowsPersistenceAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        using var f = new DeviceFileConnectionMetadataTests.Fixture();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        TestAssert.Throws<InvalidDataException>(() => f.Store.NativeMediaCollectionRoots(f.Peer.Id), "Root inspection bootstrapped a missing original storage key.");
        TestAssert.That(!File.Exists(f.Paths.TelefonStorageKey), "Rejected inspection wrote a replacement storage key.");
        // Same explicit injected-key materialization as ReceiveJobTests.Fixture;
        // source inspection itself must never bootstrap a missing product key.
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
        TestAssert.That(f.Store.NativeMediaCollectionRoots(f.Peer.Id).Count == 0, "Missing selected roots became an inferred/default source.");
        var path = Path.Combine(f.Paths.Root, "selected-source"); Directory.CreateDirectory(path);
        var selected = DeviceFileNativeDirectory.OpenExisting(path);
        try
        {
            var beforePreferences = f.Store.ReadNativeMediaPreferences(f.Peer.Id);
            var beforeSend = f.Store.ReadNativeMediaSendConsent(f.Peer.Id);
            var saved = f.Store.AddNativeMediaCollectionRoot(f.Peer.Id, "images", selected, () => { });
            TestAssert.That(saved.Identity == selected.CurrentIdentity() && saved.Id.Length == 32 && saved.Version.Length == 64 &&
                f.Store.AddNativeMediaCollectionRoot(f.Peer.Id, "images", selected, () => { }) == saved,
                "Native source selection was not exact/idempotent or fabricated a phone reference.");
            var second = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
            TestAssert.That(second.NativeMediaCollectionRoots(f.Peer.Id).Single() == saved &&
                second.ReadNativeMediaPreferences(f.Peer.Id) == beforePreferences && second.ReadNativeMediaSendConsent(f.Peer.Id) == beforeSend &&
                second.ReadNativeMediaDestination(f.Peer.Id, "images") is null && second.NativeMediaReceiveHistory(f.Peer.Id).Count == 0,
                "Selected source lost protected persistence or conferred receive/SEND/phone mapping authority.");
            using (var db = f.Store.OpenDatabase())
            {
                db.Open(); using var read = db.CreateCommand(); read.CommandText = "SELECT value FROM native_media_collection_roots";
                var cipher = (byte[])read.ExecuteScalar()!;
                TestAssert.That(!Encoding.UTF8.GetString(cipher).Contains(path), "Private source path was stored as plaintext.");
            }
            var nested = Path.Combine(path, "nested"); Directory.CreateDirectory(nested);
            using (var child = DeviceFileNativeDirectory.OpenExisting(nested))
                TestAssert.Throws<InvalidDataException>(() => second.AddNativeMediaCollectionRoot(f.Peer.Id, "images", child, () => { }),
                    "Overlapping roots duplicated source membership.");
            using (var writer = DeviceFileNativeDirectory.OpenExistingForReceive(path))
                TestAssert.Throws<InvalidDataException>(() => second.AddNativeMediaCollectionRoot(f.Peer.Id, "video", writer, () => { }),
                    "Receive owner substituted for explicit read-only source selection.");
            TestAssert.Throws<InvalidDataException>(() => second.AddNativeMediaCollectionRoot(f.Peer.Id, "video", selected,
                () => throw DeviceFileControl.Error("synthetic_source_picker_revoked")), "Withdrawn native picker persisted a source.");
            TestAssert.That(second.NativeMediaCollectionRoots(f.Peer.Id).Single() == saved, "Failed root choice altered previous source history.");
            var privatePath = Path.Combine(f.Paths.Root, ".magnolie-trash-private"); Directory.CreateDirectory(privatePath);
            using (var privateRoot = DeviceFileNativeDirectory.OpenExisting(privatePath))
                TestAssert.Throws<InvalidDataException>(() => second.AddNativeMediaCollectionRoot(f.Peer.Id, "images", privateRoot, () => { }),
                    "Selecting a private trash root bypassed source inventory exclusions.");
            selected.Dispose();
            using (var reopened = saved.OpenNative()) TestAssert.That(reopened.CurrentCollectionSourceIdentity() == saved.Identity, "Exact source could not reopen read-only.");
            Directory.Move(path, path + "-old"); Directory.CreateDirectory(path);
            TestAssert.Throws<InvalidDataException>(() => saved.OpenNative(), "Replacement root at the old path inherited selected source identity.");
            using (var replacement = DeviceFileNativeDirectory.OpenExisting(path))
                TestAssert.Throws<InvalidDataException>(() => second.AddNativeMediaCollectionRoot(f.Peer.Id, "images", replacement, () => { }),
                    "Replacement selection silently overwrote old source/history.");
            TestAssert.That(second.NativeMediaCollectionRoots(f.Peer.Id).Single() == saved, "Replacement HOLD discarded old source root record.");
        }
        finally { selected.Dispose(); }
        return Task.CompletedTask;
    }
}
