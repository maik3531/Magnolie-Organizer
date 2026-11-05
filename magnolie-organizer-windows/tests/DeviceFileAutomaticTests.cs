using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileAutomaticTests
{
    internal static Task WindowsEmptyAlbumAsync() => RunAsync(false);
    internal static Task WindowsStopPreparingAsync() => RunAsync(true);
    internal static Task WindowsVideoEmptyAlbumAsync() => RunAsync(false, true);
    internal static Task WindowsReceiveSavedAsync() => RunAsync(false, transfer: true);

    internal static async Task WindowsServiceLifetimeAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        Task Invoke(string method) => (Task)typeof(TelefonCoordinator).GetMethod(method, flags)!.Invoke(coordinator, null)!;
        var workers = (System.Collections.Concurrent.ConcurrentDictionary<Task, byte>)typeof(TelefonCoordinator).GetField("workers", flags)!.GetValue(coordinator)!;
        DeviceFileConnectionRunsTests.Clear(f);
        await Invoke("StartAsync").WaitAsync(TimeSpan.FromSeconds(5));
        try
        {
            TestAssert.That(coordinator.IsRunning && workers.Count >= 2, "Native service did not track its automatic loop alongside its accept worker.");
            TestAssert.That(f.Native.Stream.Length == 0, "Starting native service with manual default emitted media work.");
        }
        finally { await Invoke("StopAsync").WaitAsync(TimeSpan.FromSeconds(5)); }
        TestAssert.That(!coordinator.IsRunning && workers.IsEmpty, "Native service shutdown left an automatic worker or listener task running.");
    }

    private static async Task RunAsync(bool stop, bool video = false, bool transfer = false)
    {
        var book = new NativeBookOwnerScope(); book.SetReady(true); book.RecordSaved("auto-book", true, new string('a', 64));
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(uiSavedBook: () => book.SaveState("auto-book", true));
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection);
        DeviceFileConnectionRunsTests.Clear(f);
        await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
        TestAssert.That(f.Native.Stream.Length == 0, "Manual default emitted automatic file/control work.");
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, !video, video, true);
        if (video)
        {
            var path = Path.Combine(f.Native.Paths.Root, "automatic-video"); Directory.CreateDirectory(path);
            using var root = DeviceFileNativeDirectory.OpenExistingForReceive(path);
            f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, root);
        }
        using (var bluetooth = f.Native.NewConnection(f.Native.Stream, "bluetooth"))
        {
            online[f.Native.Peer.Id] = bluetooth;
            await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
            TestAssert.That(f.Native.Stream.Length == 0, "Bluetooth admitted automatic WLAN media work.");
        }
        using (var unacknowledged = f.Native.NewConnection(f.Native.Stream))
        {
            online[f.Native.Peer.Id] = unacknowledged;
            await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
            TestAssert.That(f.Native.Stream.Length == 0, "Claimed capabilities without actual native receipts admitted automatic work.");
        }
        online[f.Native.Peer.Id] = f.Native.Connection;
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None),
            "Automatic worker admitted a book without actual durable save proof.");
        TestAssert.That(f.Native.Stream.Length == 0, "Failed saved-book admission emitted automatic READ/configuration.");
        const string text = "{\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":0}}}";
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "automatic-book"), text);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var automatic = coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
        var outgoing = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind);
        TestAssert.That(!automatic.IsCompleted && !DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Any(message =>
            message["kind"]?.GetValue<string>() == DeviceFileSources.RequestKind), "Automatic worker substituted stored intent for current bilateral ACK.");
        f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(outgoing, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), f.RemotePeer);
        var ack = f.Phone.Packet(); f.Phone.MarkSent(ack);
        await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(ack, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        async Task<JsonObject> Source(int number, string operation)
        {
            var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, number);
            TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == operation, "Unexpected automatic source operation: " + operation);
            return request;
        }
        var request = await Source(0, "status");
        await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(coordinator.DiscoverNativeMediaUiAsync(f.Native.Peer.Id, "images", CancellationToken.None),
            "Manual discovery overlapped an automatic worker.");
        var status = DeviceFileConnectionCommandsTests.Configuration(request, video); status["body"]!["operation"] = "status";
        await f.Native.Connection.HandlePlainAsync(status);
        request = await Source(1, video ? "configure_videos" : "configure");
        TestAssert.That(DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Count(frame => frame["kind"]?.GetValue<string>() == DeviceFileSources.RequestKind) == 2,
            "Automatic video/image READ was issued before correlated positive native configuration.");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Configuration(request, video));
        request = await Source(2, "discover"); var catalog = DeviceFileConnectionCommandsTests.Catalog(request, video);
        var album = catalog["body"]!["page"]!["albums"]![0]!; album["visible_images"] = transfer ? 2 : stop ? 1 : 0;
        await f.Native.Connection.HandlePlainAsync(catalog);
        request = await Source(3, "batch_run");
        TestAssert.That(request["body"]!["album_id"]!.GetValue<string>() == album["album_id"]!.GetValue<string>() &&
            !request["body"]!["desktop_choice"]!.GetValue<bool>(), "Automatic worker reused a stale album ID or invented explicit album consent.");
        var run = Guid.NewGuid().ToString("D");
        JsonObject RunReply(JsonObject source, string phase, bool? end = null)
        {
            var reply = DeviceFileConnectionRunsTests.Reply(source, run, phase, end);
            if (video) reply["body"]!["media_type"] = "video";
            return reply;
        }
        await f.Native.Connection.HandlePlainAsync(RunReply(request, stop ? "preparing" : transfer ? "snapshot_ready" : "empty_ready", stop ? null : true));
        var offset = 4;
        var epoch = new string('e', 64);
        byte[][] data = ["automatic first file"u8.ToArray(), "automatic second file"u8.ToArray()];
        if (transfer)
        {
            var manifest = f.Manifest(("first.jpg", data[0]), ("second.jpg", data[1]));
            for (var after = 0; after < 2; after++)
            {
                request = await Source(offset++, "media_page");
                var page = DeviceFileConnectionRunsTests.Media(request, run, after, after == 0, epoch);
                page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
                await f.Native.Connection.HandlePlainAsync(page);
            }
            request = await Source(offset++, "offer_run");
            var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            offer["expires_ms"] = request["expires_ms"]!.DeepClone();
            await f.Native.Connection.HandlePlainAsync(offer);
            var offered = RunReply(request, "snapshot_ready", true);
            offered["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); offered["body"]!["manifest_sha256"] = manifest.Fingerprint;
            await f.Native.Connection.HandlePlainAsync(offered);
            _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
            for (var index = 0; index < 2; index++)
            {
                var chunk = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
                await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(chunk, data[index]));
            }
            _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
            TestAssert.That(f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 1, manifest.TotalBytes), "Automatic publication retired budget before actual source END.");
        }
        if (stop)
        {
            _ = await Source(offset++, "run_status");
            TestAssert.That(coordinator.StopNativeMediaAutomatic(f.Native.Peer.Id), "Stop did not target the actual automatic lifetime.");
        }
        request = await Source(offset++, "cancel_run"); await f.Native.Connection.HandlePlainAsync(RunReply(request, "canceled_held", stop ? null : true));
        request = await Source(offset++, "end_run"); await f.Native.Connection.HandlePlainAsync(RunReply(request, "canceled_held"));
        request = await Source(offset, "end_album"); await f.Native.Connection.HandlePlainAsync(RunReply(request, "canceled_held"));
        if (stop) await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(automatic, "Stopped automatic work returned completion.");
        else await automatic;
        var ui = coordinator.NativeMediaUiStatus(f.Native.Peer.Id);
        TestAssert.That(ui["automatic_phase"]!.GetValue<string>() == (stop ? "paused" : "content_pass") && !ui["automatic_busy"]!.GetValue<bool>() &&
            !ui["deletions_ready"]!.GetValue<bool>() && f.Native.Connection.CurrentNativeMediaSourceRun is null &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (transfer ? 1 : 0, 0, 0L) &&
            (transfer || !Directory.EnumerateFileSystemEntries(f.Root).Any()),
            "Automatic cleanup fabricated Saved/deletion/output or retained active source ownership.");
        if (transfer)
        {
            var root = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Synthetic camera").Folder);
            TestAssert.That(File.ReadAllBytes(Path.Combine(root, "first.jpg")).SequenceEqual(data[0]) &&
                File.ReadAllBytes(Path.Combine(root, "second.jpg")).SequenceEqual(data[1]) &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 1, "Automatic native receive lost published content or immutable history.");
        }
        if (stop)
        {
            var frames = f.Native.Stream.Length;
            await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, CancellationToken.None);
            TestAssert.That(f.Native.Stream.Length == frames, "Stopped automatic operation silently restarted on its next tick.");
        }
        var choice = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        coordinator.SetNativeMediaUiAutomaticMode(f.Native.Peer.Id, choice.Version, false);
        var manual = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        TestAssert.That(!manual.AutomaticWifi && manual.PhotosEnabled == !video && manual.VideosEnabled == video &&
            manual.DeleteFromPhone == choice.DeleteFromPhone && manual.DeleteFromDesktop == choice.DeleteFromDesktop,
            "Mode change overwrote media or directional deletion choices.");
    }
}
