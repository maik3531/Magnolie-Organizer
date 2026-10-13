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
            using var coordinator = new TelefonCoordinator(paths, (_, _) => Task.CompletedTask, dataStore: store, localOnly: true);
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
            TestAssert.That(store.LoadPeers().Count == 1, "Renewal created a second phone binding.");
            TestAssert.That(!store.TryFinishPending(peer.Id, new byte[32], new byte[32], 1, out _, out _), "Old proof completed renewed pairing.");
            TestAssert.That(store.TryFinishPending(peer.Id, transcript, phoneProof, 1, out var confirmed, out _)
                && confirmed.State == "paired" && confirmed.PublicKey.SequenceEqual(peer.PublicKey), "New phone finish proof was not accepted.");
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }
}
