using System.Reflection;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileDestinationChoiceTests
{
    internal static Task WindowsChoicesAsync() => Choices(["same", "initial", "cancel", "other-root", "legacy"]);
    internal static Task WindowsContextAsync() => Choices(["book", "connection", "intent", "preferences", "send", "receive", "control", "metadata", "stale"]);
    internal static Task WindowsLifetimeAsync() => Choices(["worker", "deadline"]);

    internal static async Task WindowsStoreRollbackAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false);
        var path = Path.Combine(f.Native.Paths.Root, "rollback-destination"); Directory.CreateDirectory(path);
        using var owner = DeviceFileNativeDirectory.OpenExistingForReceive(path);
        var calls = 0;
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, owner, () => {
            if (++calls == 3) throw DeviceFileControl.Error("test_original_context_retired");
        }), "Late original-context failure committed an initial target.");
        TestAssert.That(calls == 3 && f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "video") is null &&
            f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination && !Directory.EnumerateFileSystemEntries(path).Any(),
            "Precommit original-context rejection did not roll back metadata.");
    }

    private static async Task Choices(string[] scenarios)
    {
        foreach (var scenario in scenarios)
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false, sharedMedia: scenario != "legacy");
            if (scenario != "legacy")
            {
                f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("import_only")!,
                    f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode"));
                await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            }
            var receive = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
            receive = f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, receive.Version, true);
            var send = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
            var preferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "destination-choice-book"),
                "{\"syncEpoch\":\"destination-choice\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}");
            using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
            coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
            var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            online.Add(f.Native.Peer.Id, f.Native.Connection);
            var kind = scenario == "initial" ? "video" : "images";
            var original = f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, kind);
            var status = coordinator.NativeMediaUiStatus(f.Native.Peer.Id);
            var version = status["destination_choices"]![kind]!.GetValue<string>();
            TestAssert.That(version.Length == 64 && version != original?.Version && !send.Photos && !send.Videos,
                "Destination context required sending or reused an immutable root version.");
            var path = Path.Combine(f.Native.Paths.Root, "new-destination"); Directory.CreateDirectory(path);
            DeviceFileConnectionRunsTests.Clear(f);
            DeviceFileNativeDirectory? held = null; var calls = 0;
            DeviceFileNativeDirectory? Picker(Action current)
            {
                calls++; current();
                TestAssert.Throws<InvalidDataException>(() => coordinator.ChooseNativeMediaDestination(f.Native.Peer.Id, kind, version,
                    _ => throw new Exception("Nested destination picker opened.")), "Destination slot was not exclusive.");
                TestAssert.Throws<InvalidDataException>(() => coordinator.ChooseNativeMediaCollectionFolder(f.Native.Peer.Id, "images", version,
                    _ => throw new Exception("Competing source picker opened.")), "Source picker overlapped destination.");
                TestAssert.Throws<InvalidDataException>(() => coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, send.Version, true, false,
                    () => throw new Exception("Competing SEND dialog opened.")), "SEND dialog overlapped destination.");
                if (scenario == "cancel") return null;
                if (scenario == "book") typeof(PersonalActorNativeSaveHost).GetProperty("currentPlainTextAvailable", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(host, false);
                if (scenario == "connection") online.Remove(f.Native.Peer.Id);
                if (scenario == "intent") f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only", JsonValue.Create(false)!,
                    f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only"));
                if (scenario == "preferences") f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, preferences.Version,
                    preferences.PhotosEnabled, preferences.VideosEnabled, !preferences.AutomaticWifi);
                if (scenario == "send") f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, send.Version, true, false);
                if (scenario == "receive") f.Native.Store.ChangeNativeMediaReceiveConsent(f.Native.Peer.Id, receive.Version, false);
                if (scenario == "control")
                {
                    var packet = f.Phone.Packet(); f.Phone.MarkSent(packet);
                    f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(packet, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds())).GetAwaiter().GetResult();
                }
                if (scenario == "metadata") f.Native.Connection.HandlePlainAsync(f.Native.Message("personal_sync.settings")).GetAwaiter().GetResult();
                if (scenario == "worker")
                {
                    var worker = typeof(TelefonCoordinator).GetField("nativeMediaWorker", BindingFlags.Instance | BindingFlags.NonPublic)!;
                    worker.SetValue(coordinator, 1);
                    TestAssert.Throws<InvalidDataException>(current, "Worker conflict did not retire the dialog.");
                    worker.SetValue(coordinator, 0);
                    TestAssert.Throws<InvalidDataException>(current, "Restored worker slot revived the retired dialog.");
                }
                if (scenario == "deadline") Thread.Sleep(TimeSpan.FromSeconds(61));
                return held = scenario is "initial" or "other-root" ? DeviceFileNativeDirectory.OpenExistingForReceive(path) : f.Destination.OpenNative();
            }
            if (scenario is "same" or "initial" or "cancel" or "legacy")
            {
                var reply = coordinator.ChooseNativeMediaDestination(f.Native.Peer.Id, kind, version, Picker);
                TestAssert.That((reply["canceled"]?.GetValue<bool>() == true) == (scenario == "cancel"), "Cancellation was not retained.");
            }
            else TestAssert.Throws<InvalidDataException>(() => coordinator.ChooseNativeMediaDestination(f.Native.Peer.Id, kind,
                scenario == "stale" ? new string('a', 64) : version, Picker), "Changed context or unimplemented root switch was accepted: " + scenario);
            TestAssert.That(calls == (scenario == "stale" ? 0 : 1), "Stale choice reached native picker.");
            if (held is not null) TestAssert.Throws<ObjectDisposedException>(() => held.CurrentIdentity(), "Native owner survived reply or failed selection.");
            var after = f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, kind);
            TestAssert.That(scenario == "initial" ? after is not null && !after.GrantsReceiveAuthority && after.NativePath == held!.NativePath : after == original,
                "Dialog changed original destination or granted receiving.");
            TestAssert.That(!Directory.EnumerateFileSystemEntries(path).Any() && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
                f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0, "Metadata choice created transfer data/history.");
            if (scenario is not ("control" or "metadata")) TestAssert.That(f.Native.Stream.Length == 0, "Destination metadata sent control/data packets.");
        }
    }
}
