using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileAlbumTests
{
    private static readonly byte[][] Data = ["first native album file"u8.ToArray(), "second native album file"u8.ToArray()];
    private static async Task<(string CatalogId, string AlbumId)> Catalog(DeviceFileReceiveJobTests.Fixture f, string label)
    {
        var catalogId = Guid.NewGuid().ToString("D"); var albumId = Guid.NewGuid().ToString("D"); var version = new string('d', 64);
        DeviceFileConnectionRunsTests.Clear(f); var discover = f.Native.Connection.DiscoverNativeMediaAlbumsAsync(version); var request = DeviceFileConnectionRunsTests.Request(f);
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        await f.Native.Connection.HandlePlainAsync(new JsonObject { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = DeviceFileSources.CatalogKind, ["created_ms"] = now, ["expires_ms"] = now + 60000,
            ["body"] = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = "discover", ["version"] = version,
                ["page"] = new JsonObject { ["format"] = 1, ["catalog_id"] = catalogId, ["after"] = 0, ["next_cursor"] = null, ["coverage"] = "full_images", ["proves_deletion"] = false,
                    ["albums"] = new JsonArray(new JsonObject { ["album_id"] = albumId, ["kind"] = "camera", ["display_name"] = label, ["visible_images"] = 2, ["needs_choice"] = false }) } } });
        await discover;
        return (catalogId, albumId);
    }
    internal static async Task<TelefonConnection.NativeMediaSourceRun> Preview(DeviceFileReceiveJobTests.Fixture f, DeviceFileManifest manifest, string epoch, string label)
    {
        var (catalogId, albumId) = await Catalog(f, label); var version = new string('d', 64);
        DeviceFileConnectionRunsTests.Clear(f); var start = f.Native.Connection.StartNativeMediaBatchAsync(version, catalogId, albumId, true); var request = DeviceFileConnectionRunsTests.Request(f);
        var id = Guid.NewGuid().ToString("D"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "snapshot_ready", false)); var run = await start;
        TestAssert.That(run.AlbumMetadata?.DisplayName == label, "Native album name did not come from the actual correlated catalog.");
        foreach (var after in new[] { 0, 1 })
        {
            DeviceFileConnectionRunsTests.Clear(f); var read = f.Native.Connection.ReadNativeMediaPageAsync(run); request = DeviceFileConnectionRunsTests.Request(f);
            var page = DeviceFileConnectionRunsTests.Media(request, id, after, after == 0, epoch); page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
            await f.Native.Connection.HandlePlainAsync(page); await read;
        }
        DeviceFileConnectionRunsTests.Clear(f); await DeviceFileConnectionReceiveTests.Ready(f, manifest, run); return run;
    }
    private static async Task End(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run)
    {
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 0);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "cancel_run", "Album flow skipped native source stop.");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held", run.Result.BatchEnd));
        request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, 1);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held"));
    }
    private static async Task Release(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run)
    {
        DeviceFileConnectionRunsTests.Clear(f); var end = f.Native.Connection.EndNativeMediaAlbumAsync(run); var request = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held")); await end;
    }
    internal static async Task Copy(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run, byte[][] data)
    {
        DeviceFileConnectionRunsTests.Clear(f); var receive = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        for (var index = 0; index < 2; index++)
        {
            var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, data[index]));
        }
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind); await End(f, run); var outcome = await receive;
        TestAssert.That(!outcome.NeedsReview && outcome.ReceivedJobId is not null, "Native album copy did not earn original Saved/END.");
        await Release(f, run);
    }

    internal static async Task WindowsStableAlbumNamespaceAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var epoch = new string('e', 64);
        var manifest = f.Manifest(("same.jpg", Data[0]), ("other.jpg", Data[1])); var run = await Preview(f, manifest, epoch, "Kamera"); await Copy(f, run, Data);
        var folder = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder);
        TestAssert.That(File.ReadAllBytes(Path.Combine(folder, "same.jpg")).SequenceEqual(Data[0]) && !File.Exists(Path.Combine(f.Root, "same.jpg")), "Album files fell back to the flat media root.");
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        // New random native catalog/album IDs and a new display label must not
        // rename/adopt/recreate the original native album directory.
        run = await Preview(f, f.Manifest(("same.jpg", Data[0]), ("other.jpg", Data[1])), epoch, "Anderer Anzeigename");
        DeviceFileConnectionRunsTests.Clear(f); var repeat = f.Native.Connection.ReconcileNativeMediaBatchAsync(run); await End(f, run); var result = await repeat;
        TestAssert.That(result.Plan.Members.All(member => member.Action == "unchanged") && result.ReceivedJobId is null &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == history && !Directory.Exists(Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Anderer Anzeigename").Folder)),
            "Ephemeral catalog IDs/labels replaced durable native album ownership.");
        await Release(f, run);
        var secondData = new[] { "another camera same filename"u8.ToArray(), "another camera other filename"u8.ToArray() }; var secondEpoch = new string('f', 64);
        run = await Preview(f, f.Manifest(("same.jpg", secondData[0]), ("other.jpg", secondData[1])), secondEpoch, "Kamera"); await Copy(f, run, secondData);
        var second = Path.Combine(f.Root, new NativeMediaAlbumContext(secondEpoch, "Kamera").Folder);
        TestAssert.That(File.ReadAllBytes(Path.Combine(folder, "same.jpg")).SequenceEqual(Data[0]) && File.ReadAllBytes(Path.Combine(second, "same.jpg")).SequenceEqual(secondData[0]) &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (2, 0, 0L), "Distinct native album namespaces collided or overwrote the same-named original file.");
    }

    internal static async Task WindowsAlbumReplacementHoldAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var epoch = new string('e', 64);
        var run = await Preview(f, f.Manifest(("same.jpg", Data[0]), ("other.jpg", Data[1])), epoch, "Kamera"); await Copy(f, run, Data);
        var folder = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder); Directory.Move(folder, folder + "-kept"); Directory.CreateDirectory(folder);
        run = await Preview(f, f.Manifest(("same.jpg", Data[0]), ("other.jpg", Data[1])), epoch, "Kamera");
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.ReconcileNativeMediaBatchAsync(run), "A replacement album directory inherited old native file ownership.");
        TestAssert.That(!Directory.EnumerateFileSystemEntries(folder).Any() && File.ReadAllBytes(Path.Combine(folder + "-kept", "same.jpg")).SequenceEqual(Data[0]) &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L), "Album replacement HOLD recreated files or erased original bytes/history.");
    }

    internal static async Task WindowsUnownedAlbumFolderHoldAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var epoch = new string('e', 64);
        var folder = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder); Directory.CreateDirectory(folder); File.WriteAllText(Path.Combine(folder, "personal.txt"), "keep user content");
        var run = await Preview(f, f.Manifest(("same.jpg", Data[0]), ("other.jpg", Data[1])), epoch, "Kamera");
        DeviceFileConnectionRunsTests.Clear(f); var receive = f.Native.Connection.ReconcileNativeMediaBatchAsync(run); await End(f, run); var result = await receive;
        TestAssert.That(result.NeedsReview && result.Plan.Members.All(member => member.Action == "pause_unknown_album_root") && result.ReceivedJobId is null &&
            File.ReadAllText(Path.Combine(folder, "personal.txt")) == "keep user content" && Directory.EnumerateFileSystemEntries(folder).Count() == 1 &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (0, 0, 0L), "Unowned existing album folder was silently adopted or given a fabricated receipt.");
    }

    private static async Task<JsonObject> Source(DeviceFileReceiveJobTests.Fixture f, int number, string operation)
    {
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, number);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == operation, "Wrong whole-album source phase: " + operation); return request;
    }

    internal static async Task WindowsWholeAlbumBatchLoopAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var (catalog, album) = await Catalog(f, "Kamera"); var epoch = new string('e', 64);
        var manifest = f.Manifest(("first.jpg", Data[0]), ("second.jpg", Data[1])); DeviceFileConnectionRunsTests.Clear(f);
        var sync = f.Native.Connection.SynchronizeNativeMediaAlbumAsync(new string('d', 64), catalog, album, true);
        var request = await Source(f, 0, "batch_run"); var runId = Guid.NewGuid().ToString("D");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, runId, "snapshot_ready", false));
        for (var after = 0; after < 2; after++)
        {
            request = await Source(f, 1 + after, "media_page"); var page = DeviceFileConnectionRunsTests.Media(request, runId, after, after == 0, epoch);
            page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint; await f.Native.Connection.HandlePlainAsync(page);
        }
        request = await Source(f, 3, "offer_run"); var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(offer); var offered = DeviceFileConnectionRunsTests.Reply(request, runId, "snapshot_ready", false);
        offered["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); offered["body"]!["manifest_sha256"] = manifest.Fingerprint; await f.Native.Connection.HandlePlainAsync(offered);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        for (var index = 0; index < 2; index++)
        {
            request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, Data[index]));
        }
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
        request = await Source(f, 4, "cancel_run"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, runId, "canceled_held", false));
        request = await Source(f, 5, "end_run"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, runId, "canceled_held"));
        request = await Source(f, 6, "next_batch"); TestAssert.That(request["body"]!["run_id"]!.GetValue<string>() == runId, "Whole-album cursor lost the exact ended source owner.");
        var emptyId = Guid.NewGuid().ToString("D"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, emptyId, "empty_ready", true));
        request = await Source(f, 7, "cancel_run"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, emptyId, "canceled_held", true));
        request = await Source(f, 8, "end_run"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, emptyId, "canceled_held"));
        request = await Source(f, 9, "end_album"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, emptyId, "canceled_held"));
        var result = await sync; var root = Path.Combine(f.Root, new NativeMediaAlbumContext(epoch, "Kamera").Folder);
        TestAssert.That(result.ReceivedJobs.Count == 1 && result.Members.Count == 2 && !result.NeedsReview && !result.ProvesDeletion &&
            f.Native.Connection.CurrentNativeMediaSourceRun is null && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L) &&
            File.ReadAllBytes(Path.Combine(root, "first.jpg")).SequenceEqual(Data[0]), "Whole-album operation failed its actual batch continuation/empty END/album release or fabricated deletion proof.");
    }

    internal static async Task WindowsWholeAlbumPreparingCancelAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var (catalog, album) = await Catalog(f, "Kamera"); using var cancel = new CancellationTokenSource();
        DeviceFileConnectionRunsTests.Clear(f); var sync = f.Native.Connection.SynchronizeNativeMediaAlbumAsync(new string('d', 64), catalog, album, true, token: cancel.Token);
        var request = await Source(f, 0, "batch_run"); var id = Guid.NewGuid().ToString("D");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "preparing", null));
        var oldStatus = await Source(f, 1, "run_status"); cancel.Cancel();
        request = await Source(f, 2, "cancel_run");
        var late = DeviceFileConnectionRunsTests.Reply(oldStatus, id, "preparing", null); late["expires_ms"] = oldStatus["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(late); // Retired status cannot mutate state or block exact cleanup.
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "canceled_held", null));
        request = await Source(f, 3, "end_run"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "canceled_held"));
        request = await Source(f, 4, "end_album"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "canceled_held"));
        await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(sync, "Whole-album cancellation lost the original native cancellation result.");
        TestAssert.That(f.Native.Connection.CurrentNativeMediaSourceRun is null && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (0, 0, 0L) &&
            !Directory.EnumerateFileSystemEntries(f.Root).Any(), "Cancelled source preparation left active ownership or fabricated file/receipt/budget state.");
    }
}
