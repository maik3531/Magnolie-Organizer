using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSharedProjectionTests
{
    private static void Identity(DeviceFileConnectionMetadataTests.Fixture f)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var identity = f.Store.LoadOrCreateIdentity(); CryptographicOperations.ZeroMemory(identity.PrivateKey);
        File.WriteAllText(f.Paths.TelefonStorageKey, Convert.ToBase64String(ProtectedData.Protect(
            Enumerable.Repeat((byte)29, 32).ToArray(), Encoding.UTF8.GetBytes("magnolie-phone-storage-v1"), DataProtectionScope.CurrentUser)));
    }
    private static JsonObject Change(DeviceFileConnectionMetadataTests.Fixture f, string field, bool value) =>
        f.Store.ChangeNativeMediaSharedSetting(f.Peer.Id, f.Peer.PublicKey, field, JsonValue.Create(value)!,
            f.Store.NativeMediaSharedFieldVersion(f.Peer.Id, f.Peer.PublicKey, field));
    private static byte[] Blob(DeviceFileConnectionMetadataTests.Fixture f)
    {
        using var db = f.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_preferences WHERE peer_id=$peer";
        read.Parameters.AddWithValue("$peer", f.Peer.Id); return (byte[])read.ExecuteScalar()!;
    }

    internal static Task RightsAndMasterAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var body = Change(f, "enabled", true);
        var denied = f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, body, () => { });
        TestAssert.That(denied.Version is null && !denied.PhotosEnabled && !denied.VideosEnabled && !denied.AutomaticWifi &&
            f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id) is { Granted: false, Explicit: true }, "Remote media intent projected positive local rights/policy.");
        var receive = f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id);
        f.Store.ChangeNativeMediaReceiveConsent(f.Peer.Id, receive.Version, true);
        var projected = f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, body, () => { });
        var bytes = Blob(f);
        TestAssert.That(projected is { PhotosEnabled: true, VideosEnabled: false, AutomaticWifi: false, SkipDeletions: false, GrantsReceiveAuthority: false } &&
            f.Store.ReadNativeMediaDestination(f.Peer.Id, "images") is null && f.Store.NativeMediaReceiveHistory(f.Peer.Id).Count == 0,
            "Matched manual intent was not projected precisely or created IO/destination authority.");
        TestAssert.That(f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, body, () => { }) == projected &&
            bytes.SequenceEqual(Blob(f)), "An unchanged shared snapshot renewed native policy or ciphertext.");
        body = Change(f, "enabled", false);
        var off = f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, body, () => { });
        TestAssert.That(!off.PhotosEnabled && !off.VideosEnabled && !off.AutomaticWifi && f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id).Granted &&
            MediaSyncSettings.Effective(body)["photos_enabled"]!.GetValue<bool>(), "Master OFF erased local rights or the remembered photo choice.");
        return Task.CompletedTask;
    }

    internal static Task AtomicFenceAsync()
    {
        using var f = new DeviceFileConnectionMetadataTests.Fixture(); Identity(f);
        var receive = f.Store.ReadNativeMediaReceiveConsent(f.Peer.Id);
        f.Store.ChangeNativeMediaReceiveConsent(f.Peer.Id, receive.Version, true);
        var initial = Change(f, "enabled", true);
        var previous = f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, initial, () => { });
        var bytes = Blob(f); var next = Change(f, "videos_enabled", true);
        TestAssert.Throws<InvalidDataException>(() => f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, initial, () => { }),
            "Stale source snapshot overwrote a newer peer intent.");
        var checks = 0;
        TestAssert.Throws<InvalidDataException>(() => f.Store.ProjectNativeMediaSharedPreferences(f.Peer.Id, f.Peer.PublicKey, next, () => {
            if (++checks == 4) throw DeviceFileControl.Error("synthetic_saved_book_revoked_after_write");
        }), "A book/intent revocation during native policy write was ignored.");
        TestAssert.That(checks == 4 && f.Store.ReadNativeMediaPreferences(f.Peer.Id) == previous && bytes.SequenceEqual(Blob(f)) &&
            JsonNode.DeepEquals(next, f.Store.ReadNativeMediaSharedSettings(f.Peer.Id, f.Peer.PublicKey)),
            "Projection HOLD changed native policy/ciphertext or discarded the actual newer shared choice.");
        return Task.CompletedTask;
    }
}
