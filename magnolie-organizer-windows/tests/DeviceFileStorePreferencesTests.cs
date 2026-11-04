using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Data.Sqlite;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileStorePreferencesTests
{
    private static void Identity(DeviceFileConnectionMetadataTests.Fixture fixture)
    {
        var identity = fixture.Store.LoadOrCreateIdentity();
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
    }
    private static long TableCount(TelefonStore store)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT count(*) FROM sqlite_master WHERE name='native_media_preferences'";
        return (long)command.ExecuteScalar()!;
    }
    private static byte[] Blob(TelefonStore store, string peer)
    {
        using var db = store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT value FROM native_media_preferences WHERE peer_id=$peer";
        command.Parameters.AddWithValue("$peer", peer); return (byte[])command.ExecuteScalar()!;
    }

    internal static Task DefaultsAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var before = File.ReadAllBytes(fixture.Paths.TelefonIdentity);
        TestAssert.That(TableCount(fixture.Store) == 0, "Constructor created a media preference table.");
        var initial = fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id);
        TestAssert.That(initial is { Revision: 0, Version: null, PhotosEnabled: false, VideosEnabled: false, AutomaticWifi: false,
            DeleteFromPhone: false, DeleteFromDesktop: false, GrantsReceiveAuthority: false }, "Missing preferences did not stay manual/OFF.");
        TestAssert.That(fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, false, false, false) == initial &&
            TableCount(fixture.Store) == 0, "Read/no-op bootstrapped persisted policy.");
        TestAssert.That(File.ReadAllBytes(fixture.Paths.TelefonIdentity).SequenceEqual(before), "Preference read refreshed protected identity.");
        return Task.CompletedTask;
    }

    internal static Task PersistenceAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var first = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, false, false);
        var cipher = Blob(fixture.Store, fixture.Peer.Id);
        TestAssert.That(first is { Revision: 1, PhotosEnabled: true, VideosEnabled: false, AutomaticWifi: false } &&
            DeviceFileControl.Hash(first.Version), "Explicit photo choice changed video/manual defaults.");
        var secondStore = new TelefonStore(fixture.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(secondStore.ReadNativeMediaPreferences(fixture.Peer.Id) == first, "Protected intent did not survive a new store owner.");
        TestAssert.Throws<InvalidDataException>(() => secondStore.SetNativeMediaPreferences(fixture.Peer.Id, null, false, true, true), "Stale window overwrote a native choice.");
        var next = secondStore.SetNativeMediaPreferences(fixture.Peer.Id, first.Version, true, true, false);
        TestAssert.That(next.Revision == 2 && next.Version != first.Version && next.PhotosEnabled && next.VideosEnabled &&
            !next.GrantsReceiveAuthority && !next.DeleteFromDesktop && !next.DeleteFromPhone, "Persisted video intent armed receive/deletion.");
        var unchanged = Blob(fixture.Store, fixture.Peer.Id);
        TestAssert.That(fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, next.Version, true, true, false) == next &&
            Blob(fixture.Store, fixture.Peer.Id).SequenceEqual(unchanged), "No-op rotated consent/version or rewrote ciphertext.");
        TestAssert.That(!Encoding.UTF8.GetString(cipher).Contains("photos_enabled", StringComparison.Ordinal) &&
            !Encoding.UTF8.GetString(cipher).Contains(first.Version!, StringComparison.Ordinal), "Saved preference body is plaintext.");
        using var db = fixture.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "DELETE FROM meta"; command.ExecuteNonQuery();
        TestAssert.That(fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id) == next, "Generic Notes metadata cleanup reset native intent.");
        return Task.CompletedTask;
    }

    internal static Task BindingAsync()
    {
        foreach (var change in new[] { "key", "pairing", "local", "unpaired" })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
            var saved = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, true, false);
            var blob = Blob(fixture.Store, fixture.Peer.Id);
            if (change == "key") fixture.Store.SavePeers([fixture.Peer with { PublicKey = Enumerable.Repeat((byte)91, 32).ToArray() }]);
            if (change == "pairing") fixture.Store.SavePeers([fixture.Peer with { FilePairingEpoch = new string('f', 64) }]);
            if (change == "unpaired") fixture.Store.SavePeers([]);
            if (change == "local")
            {
                // This fixture owns both records; production never replaces them.
                File.Delete(fixture.Paths.TelefonIdentity); File.Delete(fixture.Paths.TelefonIdentityKey); Identity(fixture);
            }
            TestAssert.Throws<InvalidDataException>(() => fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id), "Changed binding silently reset/reused intent: " + change);
            TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, saved.Version, false, false, false), "Changed binding overwrote historical intent: " + change);
            TestAssert.That(Blob(fixture.Store, fixture.Peer.Id).SequenceEqual(blob), "Binding HOLD mutated saved intent: " + change);
        }
        return Task.CompletedTask;
    }

    internal static Task CorruptionAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var saved = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, false, false);
        var original = Blob(fixture.Store, fixture.Peer.Id); var damaged = original.ToArray(); damaged[^1] ^= 1;
        using var db = fixture.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
        write.CommandText = "UPDATE native_media_preferences SET value=$value WHERE peer_id=$peer";
        write.Parameters.AddWithValue("$value", damaged); write.Parameters.AddWithValue("$peer", fixture.Peer.Id); write.ExecuteNonQuery();
        TestAssert.Throws<CryptographicException>(() => fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id), "Tampered intent became defaults.");
        TestAssert.Throws<CryptographicException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, saved.Version, false, false, false), "Tampered intent was replaced by a new choice.");
        TestAssert.That(Blob(fixture.Store, fixture.Peer.Id).SequenceEqual(damaged), "Corruption handling repaired/discarded historical bytes.");
        return Task.CompletedTask;
    }

    internal static Task SchemaAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var saved = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, false, false);
        var original = JsonNode.Parse(fixture.Store.Open("native_media_preferences", fixture.Peer.Id, Blob(fixture.Store, fixture.Peer.Id)))!.AsObject();
        using var db = fixture.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
        write.CommandText = "UPDATE native_media_preferences SET value=$value WHERE peer_id=$peer";
        write.Parameters.AddWithValue("$peer", fixture.Peer.Id);
        var bytes = write.Parameters.Add("$value", SqliteType.Blob);
        foreach (var mutate in new Action<JsonObject>[] {
            value => value["revision"] = 0, value => value["revision"] = true,
            value => value["revision"] = DeviceFileControl.MaximumRevision + 1,
            value => value["version"] = "bad", value => value["format"] = 2,
            value => value["videos_enabled"] = 1, value => value["automatic_wifi"] = "true",
            value => value["direction"] = "bidirectional", value => value["delete_phone"] = 1,
            value => value["delete_desktop"] = "true", value => value["path"] = "untrusted",
            value => value.Remove("photos_enabled") })
        {
            var changed = original.DeepClone().AsObject(); mutate(changed);
            bytes.Value = fixture.Store.Seal("native_media_preferences", fixture.Peer.Id, TelefonCrypto.Canonical(changed)); write.ExecuteNonQuery();
            TestAssert.Throws<InvalidDataException>(() => fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id), "Authenticated malformed preferences accepted.");
            TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, saved.Version, false, false, false), "Malformed preferences silently overwritten.");
        }
        original["revision"] = DeviceFileControl.MaximumRevision;
        bytes.Value = fixture.Store.Seal("native_media_preferences", fixture.Peer.Id, TelefonCrypto.Canonical(original)); write.ExecuteNonQuery();
        var exhausted = Blob(fixture.Store, fixture.Peer.Id);
        TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, saved.Version, false, false, false), "Exhausted policy revision reset/wrapped.");
        TestAssert.That(Blob(fixture.Store, fixture.Peer.Id).SequenceEqual(exhausted), "Revision exhaustion changed saved intent.");
        return Task.CompletedTask;
    }

    internal static Task RestoreAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var saved = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, true, false);
        var before = Blob(fixture.Store, fixture.Peer.Id);
        var token = Guid.NewGuid().ToString("D"); fixture.Store.BeginRestore(token);
        TestAssert.Throws<InvalidDataException>(() => fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id), "Restore fence allowed preference readback.");
        TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, saved.Version, false, false, false), "Restore fence allowed new intent.");
        fixture.Store.AbortRestore(token);
        TestAssert.That(fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id) == saved &&
            Blob(fixture.Store, fixture.Peer.Id).SequenceEqual(before), "Actual restore abort discarded native preference history.");
        return Task.CompletedTask;
    }

    internal static Task DeletionChoicesAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var photos = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, false, false);
        var desktopTrash = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, photos.Version, true, false, false,
            deleteFromDesktop: true);
        TestAssert.That(desktopTrash is { DeleteFromDesktop: true, DeleteFromPhone: false, GrantsReceiveAuthority: false },
            "Explicit phone-to-desktop deletion choice enabled the opposite direction or a runtime grant.");
        var both = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, desktopTrash.Version, true, true, false,
            deleteFromPhone: true);
        TestAssert.That(both.DeleteFromPhone && both.DeleteFromDesktop && both.Version != desktopTrash.Version,
            "Both deletion directions were not independently selectable.");
        TestAssert.That(both.ComparisonPolicy is { Direction: "phone_to_desktop", PhoneDeletionsToDesktop: true, DesktopDeletionsToPhone: true },
            "Deletion choices did not reach the pure comparison policy independently of content direction.");
        var reloaded = fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id);
        TestAssert.That(reloaded == both, "Protected deletion intent did not survive readback.");
        var unrelated = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, both.Version, false, true, false);
        TestAssert.That(unrelated.DeleteFromPhone && unrelated.DeleteFromDesktop, "Photo/video choice silently reset deletion consent.");
        TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, desktopTrash.Version,
            true, true, false, false, false), "Stale deletion choice overwrote current consent.");
        var off = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, unrelated.Version, false, true, false, false, false);
        TestAssert.That(!off.DeleteFromPhone && !off.DeleteFromDesktop && !off.GrantsReceiveAuthority,
            "Explicit OFF did not persist independently of positive media intent.");
        return Task.CompletedTask;
    }

    internal static Task NotesStyleDeletionModeAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var initial = fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id);
        TestAssert.That(initial.SkipDeletions == true, "Initial media policy did not skip deletion safely.");
        var selected = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, null, true, true, false);
        var include = fixture.Store.SetNativeMediaSyncMode(fixture.Peer.Id, selected.Version, true, skipDeletions: false);
        TestAssert.That(include is { PhotosEnabled: true, VideosEnabled: true, AutomaticWifi: true, SkipDeletions: false,
            DeleteFromPhone: true, DeleteFromDesktop: true, GrantsReceiveAuthority: false },
            "Notes-style unchecked skip choice did not select both trash directions while preserving media choices.");
        TestAssert.That(fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id) == include, "Shared deletion mode did not persist.");
        var skip = fixture.Store.SetNativeMediaSyncMode(fixture.Peer.Id, include.Version, false, skipDeletions: true);
        TestAssert.That(skip is { SkipDeletions: true, DeleteFromPhone: false, DeleteFromDesktop: false, AutomaticWifi: false,
            PhotosEnabled: true, VideosEnabled: true }, "Checked skip choice failed to suppress both deletion directions.");
        TestAssert.Throws<InvalidDataException>(() => fixture.Store.SetNativeMediaSyncMode(fixture.Peer.Id, include.Version, true, false),
            "Stale shared checkbox revived deletion consent.");
        var mixed = fixture.Store.SetNativeMediaPreferences(fixture.Peer.Id, skip.Version, true, true, false, deleteFromPhone: true);
        TestAssert.That(mixed.SkipDeletions is null, "Mixed historical policy was misrepresented as one clear checkbox choice.");
        var resolved = fixture.Store.SetNativeMediaSyncMode(fixture.Peer.Id, mixed.Version, false, true);
        TestAssert.That(resolved.SkipDeletions == true && !resolved.DeleteFromPhone && !resolved.DeleteFromDesktop,
            "Explicit common choice did not resolve a mixed historical policy.");
        return Task.CompletedTask;
    }

    internal static async Task ConcurrentAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture(); Identity(fixture);
        var other = new TelefonStore(fixture.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        using var ready = new Barrier(2);
        Task<bool> Save(TelefonStore store, bool video) => Task.Run(() => {
            ready.SignalAndWait(TimeSpan.FromSeconds(10));
            try { store.SetNativeMediaPreferences(fixture.Peer.Id, null, !video, video, false); return true; }
            catch (InvalidDataException) { return false; }
        });
        var results = await Task.WhenAll(Save(fixture.Store, false), Save(other, true));
        var saved = fixture.Store.ReadNativeMediaPreferences(fixture.Peer.Id);
        TestAssert.That(results.Count(value => value) == 1 && saved.Revision == 1 && saved.PhotosEnabled != saved.VideosEnabled,
            "Independent native store owners lost a concurrent explicit choice.");
    }
}
