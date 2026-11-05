using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileReceiveConsentTests
{
    internal static Task DefaultsAndPersistenceAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        using var f = new DeviceFileConnectionMetadataTests.Fixture();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
        var initial = f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id);
        TestAssert.That(!initial.Granted && DeviceFileControl.Hash(initial.Version), "New shared intent implicitly granted local receiving.");
        var remote = MediaSyncSettings.Create(f.Peer.Id);
        remote = MediaSyncSettings.Change(remote, f.Peer.Id, identity.Id, "enabled", JsonValue.Create(true)!);
        f.Store.MergeNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey, remote);
        TestAssert.That(f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id) == initial,
            "A remote master-switch edit created or changed local receive permission.");
        var explicitOff = f.Store.ChangeNativeMediaReceiveConsent(f.Peer.Id, initial.Version, false);
        TestAssert.That(explicitOff.Explicit && !explicitOff.Granted && explicitOff.Version != initial.Version,
            "An explicit refusal was left as a future legacy-inheriting default.");
        var local = f.Store.ChangeNativeMediaReceiveConsent(f.Peer.Id, explicitOff.Version, true);
        TestAssert.That(local.Granted && local.Version != initial.Version && f.Store.ReadNativeMediaPreferences(f.Peer.Id).Version is null,
            "Local receiving consent enabled native media choices or was not durable.");
        var reopened = new TelefonStore(f.Paths, Enumerable.Repeat((byte)29, 32).ToArray());
        TestAssert.That(reopened.ReadNativeMediaReceiveConsent(f.Peer.Id) == local, "Receiving consent was lost on reopen.");
        TestAssert.Throws<InvalidDataException>(() => reopened.ChangeNativeMediaReceiveConsent(f.Peer.Id, initial.Version, false),
            "A stale window revoked or replaced another explicit permission choice.");
        using (var db = f.Store.OpenDatabase())
        {
            db.Open(); using var clear = db.CreateCommand(); clear.CommandText = "DELETE FROM meta"; clear.ExecuteNonQuery();
        }
        TestAssert.That(reopened.ReadNativeMediaReceiveConsent(f.Peer.Id) == local, "Notes cleanup removed native receiving consent.");
        f.Store.SavePeers([f.Peer with { FilePairingEpoch = new string('f', 64) }]);
        TestAssert.Throws<InvalidDataException>(() => reopened.ReadNativeMediaReceiveConsent(f.Peer.Id), "New pairing reused an old local permission.");
        return Task.CompletedTask;
    }

    internal static async Task ActualWithdrawalAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var initial = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
        TestAssert.That(initial.Granted, "An existing explicit native receive choice was silently revoked by migration.");
        initial = f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, initial.Version, true);
        TestAssert.That(initial.Explicit, "Confirming inherited rights did not separate them from media selection.");
        var bytes = Enumerable.Range(0, 70000).Select(index => (byte)(index % 251)).ToArray();
        var manifest = f.Manifest(("local-consent.jpg", bytes));
        using var job = f.Begin(manifest);
        job.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var denied = f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, initial.Version, false);
        TestAssert.Throws<InvalidDataException>(() => job.ReceiveChunk(manifest.Files[0].Id, 1, bytes[DeviceFileManifest.ChunkBytes..]),
            "An active native receiver ignored local permission withdrawal.");
        f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, denied.Version, true);
        TestAssert.Throws<InvalidDataException>(() => job.ReceiveChunk(manifest.Files[0].Id, 1, bytes[DeviceFileManifest.ChunkBytes..]),
            "Off/on resurrected a stopped native worker.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == history &&
            !File.Exists(Path.Combine(f.Root, "local-consent.jpg")), "Permission withdrawal discarded history or published incomplete bytes.");
        job.Dispose();
        var nextManifest = f.Manifest(("off-on-between-checks.jpg", bytes));
        using var nextJob = f.Begin(nextManifest);
        var current = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
        var off = f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, current.Version, false);
        f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, off.Version, true);
        TestAssert.Throws<InvalidDataException>(() => nextJob.ReceiveChunk(nextManifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]),
            "A withdrawal and regrant between two worker checks resurrected the older consent owner.");
        var preferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, preferences.Version, false, false, false);
        TestAssert.That(f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id).Granted,
            "Turning media selection off erased an independently confirmed local right.");
    }
}
