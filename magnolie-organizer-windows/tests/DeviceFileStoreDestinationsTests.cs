using System.Security.Cryptography;
using System.Text;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileStoreDestinationsTests
{
    private static DeviceFileConnectionMetadataTests.Fixture Fixture()
    {
        var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var identity = fixture.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        return fixture;
    }
    private static long Tables(TelefonStore store)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT count(*) FROM sqlite_master WHERE name='native_media_destinations'";
        return (long)command.ExecuteScalar()!;
    }
    private static byte[] Blob(TelefonStore store, string peer, string kind)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT value FROM native_media_destinations WHERE peer_id=$peer AND media_type=$kind";
        command.Parameters.AddWithValue("$peer", peer); command.Parameters.AddWithValue("$kind", kind);
        return (byte[])command.ExecuteScalar()!;
    }
    internal static Task DefaultsAsync()
    {
        using var f = Fixture(); var before = File.ReadAllBytes(f.Paths.TelefonIdentity);
        TestAssert.That(f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") is null &&
            f.Store.ReadNativeMediaDestination(f.Peer.Id, "video") is null && Tables(f.Store) == 0, "Read created a destination/default root.");
        TestAssert.That(File.ReadAllBytes(f.Paths.TelefonIdentity).SequenceEqual(before), "Destination read refreshed local identity.");
        TestAssert.Throws<InvalidDataException>(() => f.Store.ReadNativeMediaDestination(f.Peer.Id, "all"), "Unknown media destination kind accepted.");
        return Task.CompletedTask;
    }
    private static DeviceFileNativeDirectory Directory(DeviceFileConnectionMetadataTests.Fixture f, string name)
    {
        var path = Path.Combine(f.Paths.Root, name); System.IO.Directory.CreateDirectory(path);
        return DeviceFileNativeDirectory.OpenExistingForReceive(path);
    }
    internal static Task WindowsPersistenceAsync()
    {
        using var f = Fixture(); using var images = Directory(f, "native-pictures"); using var videos = Directory(f, "native-videos");
        var picture = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images);
        var video = f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, videos);
        TestAssert.That(picture.DestinationToken != video.DestinationToken && !picture.GrantsReceiveAuthority && !video.GrantsReceiveAuthority,
            "Independent destinations shared a token or created receive consent.");
        var cipher = Blob(f.Store, f.Peer.Id, "images");
        var second = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(second.ReadNativeMediaDestination(f.Peer.Id, "images") == picture && second.ReadNativeMediaDestination(f.Peer.Id, "video") == video,
            "New owner lost a protected native destination.");
        TestAssert.That(second.SetNativeMediaDestination(f.Peer.Id, "images", picture.Version, images) == picture && Blob(f.Store, f.Peer.Id, "images").SequenceEqual(cipher),
            "Idempotent destination save rotated token/ciphertext.");
        TestAssert.Throws<InvalidDataException>(() => second.SetNativeMediaDestination(f.Peer.Id, "images", null, images), "Stale destination choice overwrote saved binding.");
        TestAssert.That(!Encoding.UTF8.GetString(cipher).Contains(picture.NativePath, StringComparison.Ordinal) &&
            !Encoding.UTF8.GetString(cipher).Contains(picture.DestinationToken, StringComparison.Ordinal), "Destination was stored as plaintext.");
        var preferences = second.ReadNativeMediaPreferences(f.Peer.Id);
        TestAssert.That(!preferences.PhotosEnabled && !preferences.VideosEnabled, "Selecting a destination enabled photos/videos.");
        using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand(); command.CommandText = "DELETE FROM meta"; command.ExecuteNonQuery();
        TestAssert.That(second.ReadNativeMediaDestination(f.Peer.Id, "images") == picture, "Generic Notes metadata cleanup erased media destination.");
        return Task.CompletedTask;
    }
    internal static Task WindowsOverlapAndReopenAsync()
    {
        using var f = Fixture(); var images = Directory(f, "pictures");
        try
        {
            var saved = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images);
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, images), "Photos/videos accepted the same root.");
            using (var nested = images.CreateChild("nested-videos"))
                TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, nested), "Videos accepted a child of the photo destination.");
            using var parent = DeviceFileNativeDirectory.OpenExistingForReceive(f.Paths.Root);
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "video", null, parent), "Videos accepted a parent of the photo destination.");
            using var other = Directory(f, "other-pictures");
            TestAssert.Throws<InvalidDataException>(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "images", saved.Version, other), "Existing historical destination was silently reassigned.");
            images.Dispose();
            using (var reopened = saved.OpenNative()) TestAssert.That(reopened.CurrentIdentity() == saved.RootIdentity, "Protected native destination could not be reopened exactly.");
            System.IO.Directory.Move(saved.NativePath, saved.NativePath + "-original"); System.IO.Directory.CreateDirectory(saved.NativePath);
            TestAssert.Throws<InvalidDataException>(() => saved.OpenNative(), "A different directory at the old path inherited saved identity/token.");
        }
        finally { images.Dispose(); }
        return Task.CompletedTask;
    }
    internal static Task WindowsBindingAndTamperAsync()
    {
        foreach (var change in new[] { "key", "pairing", "local", "unpaired", "cipher" })
        {
            using var f = Fixture(); using var images = Directory(f, "pictures");
            var saved = f.Store.SetNativeMediaDestination(f.Peer.Id, "images", null, images); var original = Blob(f.Store, f.Peer.Id, "images");
            if (change == "key") f.Store.SavePeers([f.Peer with { PublicKey = Enumerable.Repeat((byte)91, 32).ToArray() }]);
            if (change == "pairing") f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
            if (change == "unpaired") f.Store.SavePeers([]);
            if (change == "local")
            {
                File.Delete(f.Paths.TelefonIdentity); File.Delete(f.Paths.TelefonIdentityKey);
                var local = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(local.PrivateKey);
            }
            var expected = original;
            if (change == "cipher")
            {
                expected = original.ToArray(); expected[^1] ^= 1;
                using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
                command.CommandText = "UPDATE native_media_destinations SET value=$value WHERE peer_id=$peer";
                command.Parameters.AddWithValue("$value", expected); command.Parameters.AddWithValue("$peer", f.Peer.Id); command.ExecuteNonQuery();
            }
            void Held(Action action)
            {
                try { action(); } catch (InvalidDataException) { return; } catch (CryptographicException) { return; }
                throw new InvalidOperationException("Changed/tampered destination was not held: " + change);
            }
            Held(() => f.Store.ReadNativeMediaDestination(f.Peer.Id, "images"));
            Held(() => f.Store.SetNativeMediaDestination(f.Peer.Id, "images", saved.Version, images));
            TestAssert.That(Blob(f.Store, f.Peer.Id, "images").SequenceEqual(expected), "Binding/tamper HOLD overwrote destination evidence: " + change);
        }
        return Task.CompletedTask;
    }
}
