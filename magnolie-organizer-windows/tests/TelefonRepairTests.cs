using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class TelefonRepairTests
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "magnolie-phone-repair-" + Guid.NewGuid().ToString("N"));
        try
        {
            var paths = new WindowsPaths(root);
            var store = new TelefonStore(paths, testStorageKey: Enumerable.Repeat((byte)7, 32).ToArray());
            store.LoadOrCreateIdentity(); store.Enabled = true;
            var peer = new TelefonPeer("11111111-1111-4111-8111-111111111111", "Fixture", Enumerable.Repeat((byte)1, 32).ToArray());
            store.SavePeers([peer]);
            var defaults = store.PersonalSettings(peer.Id);
            TestAssert.That(defaults.OwnDevice && defaults.AutoWifi && defaults.RemoteOwnDevice, "Confirmed pairing did not provide device authorization.");
            store.SetPersonalSettings(peer.Id, remoteOwnDevice: true);
            var received = store.PersonalSettings(peer.Id);
            TestAssert.That(received.OwnDevice && received.AutoWifi && received.RemoteOwnDevice,
                "Receiving remote settings silently revoked the confirmed phone's default local authorization.");
            store.SetPersonalSettings(peer.Id, ownDevice: false, autoWifi: false);
            TestAssert.That(store.PersonalSettings(peer.Id).OwnDevice && !store.PersonalSettings(peer.Id).AutoWifi,
                "Legacy ownership flags must not revoke pairing, and manual automatic-sync disable must survive.");
            TestAssert.That(!store.PersonalSettings("22222222-2222-4222-8222-222222222222").OwnDevice,
                "An unknown device obtained pairing-derived authorization.");
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store, localOnly: true);
            TestAssert.That(coordinator.PersonalSettings(peer.Id).OwnDevice && !coordinator.PersonalSettings(peer.Id).AutoWifi,
                "The GUI source must expose pairing-derived ownership and retain manual automation choice.");
            TestAssert.That(!coordinator.InitialSkipDeletions, "An unconfigured connection must not start with skip-deletions selected.");
            store.SetLocalGrant("personal_deletions_sync", false);
            TestAssert.That(coordinator.InitialSkipDeletions, "An explicit skip-deletions choice was lost.");
            store.SetLocalGrant("personal_deletions_sync", true);
            TestAssert.That(!coordinator.InitialSkipDeletions, "An explicit deletion-sync choice was lost.");
            await coordinator.ResumeAsync();
            var token = (byte[]?)typeof(TelefonCoordinator).GetField("pairingToken", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator);
            TestAssert.That(token?.Length == 16 && store.LoadPeers().Single().Id == peer.Id,
                "Known offline phone suppressed automatic Desktop search or changed existing trust.");
            // Confirmed renewal uses the existing pending-proof transaction, so
            // an old completion proof cannot finish the replacement pairing.
            var transcript = Enumerable.Repeat((byte)2, 32).ToArray();
            var phoneProof = Enumerable.Repeat((byte)3, 32).ToArray();
            var desktopProof = Enumerable.Repeat((byte)4, 32).ToArray();
            store.SavePending(peer, transcript, phoneProof, desktopProof, long.MaxValue);
            TestAssert.That(!store.PersonalSettings(peer.Id).OwnDevice, "Pending renewal reused the old pairing authority.");
            TestAssert.That(store.LoadPeers().Count == 1, "Renewal created a second phone binding.");
            TestAssert.That(!store.TryFinishPending(peer.Id, new byte[32], new byte[32], 1, out _, out _), "Old proof completed renewed pairing.");
            TestAssert.That(store.TryFinishPending(peer.Id, transcript, phoneProof, 1, out var confirmed, out _)
                && confirmed.State == "paired" && confirmed.PublicKey.SequenceEqual(peer.PublicKey), "New phone finish proof was not accepted.");
            await coordinator.RemoveAsync(peer.Id);
            var flags = BindingFlags.Instance | BindingFlags.NonPublic;
            byte[]? AdvertisedToken() => (byte[]?)typeof(TelefonCoordinator).GetMethod("CurrentPairingToken", flags)!.Invoke(coordinator, null);
            var cancelled = coordinator.OpenSetupPairing(peer.Id, System.Net.IPAddress.Parse("192.168.1.2"));
            coordinator.EndSetupPairing(cancelled["token"]!.GetValue<string>());
            TestAssert.That(AdvertisedToken() is { Length: 16 } fresh && Convert.ToBase64String(fresh) != cancelled["token"]!.GetValue<string>() && store.LoadPeers().Count == 0,
                "Cancelled setup disabled desktop discovery instead of retiring only its bound token.");
            var offer = coordinator.OpenSetupPairing(peer.Id, System.Net.IPAddress.Parse("192.168.1.2"));
            store.SavePending(peer, transcript, phoneProof, desktopProof, long.MaxValue);
            using var output = new MemoryStream();
            var retry = (Task)typeof(TelefonCoordinator).GetMethod("RetryPairFinishAsync", flags)!.Invoke(coordinator,
                [output, new JsonObject { ["p"] = TelefonCrypto.Protocol, ["type"] = "pair_finish", ["side"] = "phone",
                    ["transcript"] = Convert.ToBase64String(transcript), ["proof"] = Convert.ToBase64String(phoneProof) }, CancellationToken.None])!;
            await retry;
            var afterFinish = AdvertisedToken();
            coordinator.EndSetupPairing(offer["token"]!.GetValue<string>());
            TestAssert.That(afterFinish is { Length: 16 } && AdvertisedToken()!.SequenceEqual(afterFinish) &&
                store.LoadPeers().Single().PublicKey.SequenceEqual(peer.PublicKey) && store.PersonalSettings(peer.Id).OwnDevice,
                "A late setup-dialog close disabled rediscovery after a completed phone finish or changed confirmed trust.");
        }
        finally { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
