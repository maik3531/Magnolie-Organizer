using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileReconcileTests
{
    private static readonly byte[][] Data = ["original first"u8.ToArray(), "original second"u8.ToArray()];
    private static async Task<JsonObject> Request(DeviceFileReceiveJobTests.Fixture f, int number, string operation)
    {
        var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSources.RequestKind, number);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == operation, "Unexpected reconciliation source operation: " + operation);
        return request;
    }
    internal static async Task Finish(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run, int number)
    {
        var cancel = await Request(f, number, "cancel_run");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(cancel, run.Lease.RunId, "canceled_held", run.Result.BatchEnd));
        var end = await Request(f, number + 1, "end_run");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(end, run.Lease.RunId, "canceled_held"));
    }
    internal static async Task Establish(DeviceFileReceiveJobTests.Fixture f)
    {
        var manifest = f.Manifest(("first.jpg", Data[0]), ("second.jpg", Data[1]));
        var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest); var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        for (var index = 0; index < 2; index++)
        {
            var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, Data[index]));
        }
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind); await Finish(f, run, 0); var result = await operation;
        TestAssert.That(result.Plan.Members.All(member => member.Action == "copy_phone_new") && result.ReceivedJobId is not null && !result.NeedsReview,
            "First native reconciliation did not receive new files with actual local proofs.");
        DeviceFileConnectionRunsTests.Clear(f); var ended = f.Native.Connection.EndNativeMediaAlbumAsync(run); var album = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(album, run.Lease.RunId, "canceled_held")); await ended;
    }

    internal static async Task WindowsRepeatKeepsLocalEditsAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Establish(f);
        var edited = "actual local edit, not a new source"u8.ToArray();
        using (var file = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write)) { file.SetLength(0); file.Write(edited); }
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var manifest = f.Manifest(("first.jpg", Data[0]), ("second.jpg", Data[1])); var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest);
        var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run); await Finish(f, run, 0); var outcome = await operation;
        var frames = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray());
        TestAssert.That(outcome.Plan.Members.Select(member => member.Action).SequenceEqual(new[] { "keep_local_edit", "unchanged" }) &&
            outcome.ReceivedJobId is null && !outcome.NeedsReview && frames.All(frame => frame["kind"]!.GetValue<string>() == DeviceFileSources.RequestKind) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == history &&
            File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(edited) && File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(Data[1]),
            "Repeated native reconciliation downloaded old content, lost a local edit or fabricated another baseline/job.");
    }

    internal static async Task WindowsChangedSourceIsHeldAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Establish(f);
        var manifest = f.Manifest(("first.jpg", "phone changed"u8.ToArray()), ("second.jpg", Data[1]));
        var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest); var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        await Finish(f, run, 0); var result = await operation;
        TestAssert.That(result.NeedsReview && result.Plan.Members[0].Action == "unsupported_desktop_replace" && result.ReceivedJobId is null &&
            File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(Data[0]) && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L),
            "Changed source content overwrote the original without the still-required recoverable replacement adapter.");
    }

    internal static async Task WindowsMixedPreviewSelectsOnlyNewAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await Establish(f);
        var added = "new third native photo"u8.ToArray();
        var preview = f.Manifest(("first.jpg", Data[0]), ("third.jpg", added));
        // Actual source media identities, not filename equality, own comparison.
        var run = await DeviceFileConnectionRunsTests.OfferReady(f, preview, secondPhotoId: new string('d', 64));
        var offerTask = f.Native.Connection.OfferNativeMediaRunAsync(run); var request = DeviceFileConnectionRunsTests.Request(f);
        var offer = DeviceFileOfferEnvelope.Create(preview, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(offer);
        var offered = DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "snapshot_ready", false); offered["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); offered["body"]!["manifest_sha256"] = preview.Fingerprint;
        await f.Native.Connection.HandlePlainAsync(offered); await offerTask; DeviceFileConnectionRunsTests.Clear(f);
        var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run);
        request = await Request(f, 0, "select_run"); var selected = DeviceFileSources.ParseRequest(request, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(selected.ManifestSha256 == preview.Fingerprint && selected.SelectedFileIds!.SequenceEqual(new[] { preview.Files[1].Id }), "Mixed native batch did not select exactly its new source file.");
        var id = Guid.NewGuid().ToString("D"); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "snapshot_ready", false));
        request = await Request(f, 1, "media_page");
        var subset = new DeviceFileManifest(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), preview.SenderId, preview.ReceiverId, new[] { preview.Files[1] }, added.Length);
        var page = DeviceFileConnectionRunsTests.Media(request, id); var value = page["body"]!["page"]!;
        value["manifest_sha256"] = subset.Fingerprint; value["total_files"] = 1; value["entries"]![0]!["file_id"] = preview.Files[1].Id; value["entries"]![0]!["photo_id"] = new string('d', 64);
        await f.Native.Connection.HandlePlainAsync(page);
        request = await Request(f, 2, "offer_run"); offer = DeviceFileOfferEnvelope.Create(subset, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(offer);
        offered = DeviceFileConnectionRunsTests.Reply(request, id, "snapshot_ready", false); offered["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); offered["body"]!["manifest_sha256"] = subset.Fingerprint;
        await f.Native.Connection.HandlePlainAsync(offered);
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        var chunk = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind);
        TestAssert.That(chunk["body"]!["file_id"]!.GetValue<string>() == preview.Files[1].Id, "Unchanged preview file was downloaded after selection.");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(chunk, added));
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
        var current = f.Native.Connection.CurrentNativeMediaSourceRun!; await Finish(f, current, 3); var outcome = await operation;
        TestAssert.That(outcome.Run.Lease.RunId == id && outcome.ReceivedJobId is not null && !outcome.NeedsReview &&
            outcome.Plan.Members.Select(member => member.Action).SequenceEqual(new[] { "unchanged", "copy_phone_new" }) &&
            File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(Data[0]) && File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(Data[1]) &&
            File.ReadAllBytes(Path.Combine(f.Root, "third.jpg")).SequenceEqual(added) && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (2, 0, 0L),
            "Subset reconciliation lost old files/history or failed the new original receipt/END path.");
    }

    internal static async Task WindowsSelectionRejectsChangedSubsetAsync()
    {
        foreach (var mutation in new[] { "owner", "media", "manifest" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
            var manifest = f.Manifest(("first.jpg", Data[0]), ("second.jpg", Data[1]));
            var preview = await DeviceFileConnectionReceiveTests.Ready(f, manifest);
            var selection = f.Native.Connection.SelectNativeMediaRunAsync(preview, new[] { manifest.Files[0].Id });
            var request = await Request(f, 0, "select_run");
            var id = mutation == "owner" ? preview.Lease.RunId : Guid.NewGuid().ToString("D");
            var dispatch = f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, id, "snapshot_ready", false));
            if (mutation == "owner")
            {
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(dispatch, "Dispatcher accepted a reused selected owner.");
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(selection, "Selection reused the retired preview owner.");
            }
            else
            {
                await dispatch;
                var run = await selection; DeviceFileConnectionRunsTests.Clear(f);
                var subsetFile = mutation == "manifest" ? manifest.Files[0] with { Path = "changed.jpg" } : manifest.Files[0];
                var subset = new DeviceFileManifest(Guid.NewGuid().ToString("N"), Guid.NewGuid().ToString("N"), manifest.SenderId, manifest.ReceiverId, new[] { subsetFile }, subsetFile.Size);
                var read = f.Native.Connection.ReadNativeMediaPageAsync(run); request = await Request(f, 0, "media_page");
                var page = DeviceFileConnectionRunsTests.Media(request, id); var value = page["body"]!["page"]!;
                value["manifest_sha256"] = subset.Fingerprint; value["total_files"] = 1;
                if (mutation == "media") value["entries"]![0]!["photo_id"] = new string('f', 64);
                dispatch = f.Native.Connection.HandlePlainAsync(page);
                if (mutation == "media")
                {
                    await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(dispatch, "Dispatcher accepted changed selected media.");
                    await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(read, "Selection accepted a different native media identity.");
                }
                else
                {
                    await dispatch;
                    await read; DeviceFileConnectionRunsTests.Clear(f);
                    var offerTask = f.Native.Connection.OfferNativeMediaRunAsync(run); request = await Request(f, 0, "offer_run");
                    var offer = DeviceFileOfferEnvelope.Create(subset, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
                    await f.Native.Connection.HandlePlainAsync(offer);
                    var reply = DeviceFileConnectionRunsTests.Reply(request, id, "snapshot_ready", false);
                    reply["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); reply["body"]!["manifest_sha256"] = subset.Fingerprint;
                    await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(reply), "Dispatcher accepted changed selected metadata.");
                    await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(offerTask, "Selection accepted changed selected file metadata.");
                }
            }
            TestAssert.That(f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (0, 0, 0L) && !Directory.EnumerateFileSystemEntries(f.Root).Any(),
                "Invalid subset minted a native receive job or touched destination files: " + mutation);
        }
    }
}
