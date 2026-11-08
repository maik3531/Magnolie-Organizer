using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSendConsentTests
{
    internal static async Task NativeDialogContextAsync()
    {
        foreach (var scenario in new[] { "cancel", "accept", "book", "connection", "stale" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sharedMedia: true);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-dialog-book"),
                "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}");
            using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
            coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online.Add(f.Native.Peer.Id, f.Native.Connection);
            var before = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
            var receiving = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
            var calls = 0;
            bool Confirm()
            {
                calls++;
                TestAssert.That(f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id) == before, "Permission was persisted before the native answer.");
                if (scenario == "book") typeof(PersonalActorNativeSaveHost).GetProperty("currentPlainTextAvailable",
                    System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.SetValue(host, false);
                if (scenario == "connection") online.Remove(f.Native.Peer.Id);
                if (scenario == "stale") f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, before.Version, false, false);
                return scenario != "cancel";
            }
            if (scenario is "book" or "connection" or "stale")
                TestAssert.Throws<InvalidDataException>(() => coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, before.Version, true, false, Confirm),
                    "A stale native dialog authorized SEND: " + scenario);
            else
            {
                var result = coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, before.Version, true, false, Confirm);
                var after = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                TestAssert.That(scenario == "cancel" ? result["canceled"]?.GetValue<bool>() == true && after == before : after is { Photos: true, Videos: false, Explicit: true },
                    "Native dialog result did not control the exact independent send choice.");
                if (scenario == "accept")
                {
                    _ = coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, after.Version, false, false,
                        () => throw new Exception("Revocation must not require positive confirmation."));
                }
            }
            TestAssert.That(calls == 1 && f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id) == receiving,
                "Dialog replayed or modified independent receiving consent.");
            if (scenario is "book" or "connection")
                TestAssert.That(f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id) == before, "Stale native context changed SEND consent.");
        }
    }

    private static void Protect(DeviceFileConnectionMetadataTests.Fixture f)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
    }

    internal static Task DefaultsAndPersistenceAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Protect(f);
        var initial = f.Store.ReadNativeMediaSendConsent(f.Peer.Id);
        TestAssert.That(!initial.Photos && !initial.Videos && !initial.Explicit && DeviceFileControl.Hash(initial.Version), "Default SEND was not closed.");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT count(*) FROM sqlite_master WHERE name='native_media_send_consent'";
            TestAssert.That(Convert.ToInt32(read.ExecuteScalar()) == 0, "Passive SEND read created its consent table.");
        }
        var receiving = f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id);
        receiving = f.Store.ChangeNativeMediaReceiveConsent(f.Peer.Id, receiving.Version, true);
        var identity = f.Store.LoadOrCreateIdentity();
        try
        {
            var remote = MediaSyncSettings.Create(f.Peer.Id);
            remote = MediaSyncSettings.Change(remote, f.Peer.Id, identity.Id, "enabled", JsonValue.Create(true)!);
            remote = MediaSyncSettings.Change(remote, f.Peer.Id, identity.Id, "direction", JsonValue.Create("two_way")!);
            f.Store.MergeNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey, remote);
        }
        finally { CryptographicOperations.ZeroMemory(identity.PrivateKey); }
        TestAssert.That(f.Store.ReadNativeMediaSendConsent(f.Peer.Id) == initial, "Receive consent or peer direction granted SEND.");
        var denied = f.Store.ChangeNativeMediaSendConsent(f.Peer.Id, initial.Version, false, false);
        TestAssert.That(denied.Explicit && denied.Version != initial.Version, "Explicit refusal remained an absent default.");
        var photos = f.Store.ChangeNativeMediaSendConsent(f.Peer.Id, denied.Version, true, false);
        TestAssert.That(photos.Photos && !photos.Videos && photos.Version != denied.Version, "Photo SEND enabled video or reused a refusal version.");
        TestAssert.That(f.Store.ChangeNativeMediaSendConsent(f.Peer.Id, photos.Version, true, false) == photos, "Unchanged consent unnecessarily rotated its version.");
        var reopened = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(reopened.ReadNativeMediaSendConsent(f.Peer.Id) == photos, "SEND consent was lost after reopen.");
        TestAssert.Throws<InvalidDataException>(() => reopened.ChangeNativeMediaSendConsent(f.Peer.Id, initial.Version, false, true), "Stale UI replaced a later SEND choice.");
        var off = reopened.ChangeNativeMediaSendConsent(f.Peer.Id, photos.Version, false, false);
        var on = reopened.ChangeNativeMediaSendConsent(f.Peer.Id, off.Version, true, false);
        TestAssert.That(on.Version != photos.Version && f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id) == receiving &&
            f.Store.ReadNativeMediaPreferences(f.Peer.Id).Version is null, "Off/on reused an old consent owner or changed receive/native selection.");
        using (var db = f.Store.OpenDatabase())
        { db.Open(); using var clear = db.CreateCommand(); clear.CommandText = "DELETE FROM meta"; clear.ExecuteNonQuery(); }
        TestAssert.That(reopened.ReadNativeMediaSendConsent(f.Peer.Id) == on, "Notes cleanup deleted SEND consent.");
        f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
        TestAssert.Throws<InvalidDataException>(() => reopened.ReadNativeMediaSendConsent(f.Peer.Id), "A new pairing inherited old SEND consent.");
        return Task.CompletedTask;
    }

    internal static Task CorruptionStaysHeldAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Protect(f);
        var initial = f.Store.ReadNativeMediaSendConsent(f.Peer.Id);
        _ = f.Store.ChangeNativeMediaSendConsent(f.Peer.Id, initial.Version, false, true);
        using var db = f.Store.OpenDatabase(); db.Open(); using var command = db.CreateCommand();
        command.CommandText = "SELECT value FROM native_media_send_consent WHERE peer_id=$peer";
        command.Parameters.AddWithValue("$peer", f.Peer.Id); var cipher = (byte[])command.ExecuteScalar()!;
        cipher[0] ^= 1;
        command.CommandText = "UPDATE native_media_send_consent SET value=$value WHERE peer_id=$peer";
        command.Parameters.AddWithValue("$value", cipher); command.ExecuteNonQuery();
        TestAssert.Throws<CryptographicException>(() => f.Store.ReadNativeMediaSendConsent(f.Peer.Id), "Tampered SEND consent became a default or grant.");
        command.CommandText = "SELECT value FROM native_media_send_consent WHERE peer_id=$peer";
        TestAssert.That(((byte[])command.ExecuteScalar()!).SequenceEqual(cipher), "Failed read silently repaired/discarded damaged consent.");
        return Task.CompletedTask;
    }
}
