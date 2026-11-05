using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileReplacementTests
{
    private static readonly byte[][] Original = ["original first"u8.ToArray(), "original second"u8.ToArray()];

    private static async Task Send(DeviceFileReceiveJobTests.Fixture f, byte[][] data)
    {
        for (var index = 0; index < data.Length; index++)
        {
            var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, data[index]));
        }
    }

    internal static async Task WindowsReplacementChainAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var originalJob = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var before = Original;
        for (var generation = 1; generation <= 2; generation++)
        {
            var next = new[] { System.Text.Encoding.UTF8.GetBytes("phone first generation " + generation), System.Text.Encoding.UTF8.GetBytes("phone second generation " + generation) };
            var manifest = f.Manifest(("first.jpg", next[0]), ("second.jpg", next[1]));
            var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest);
            var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run, replacementConsent: new(() => true));
            _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
            TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(before[0]) &&
                f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Count == (generation - 1) * 2, "Replacement moved originals before the new data was received.");
            await Send(f, next);
            _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
            var heldArchive = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).First(entry => entry.State == "trashed" &&
                entry.JobId == run.Replacements!.Records[0]!["job_id"]!.GetValue<string>());
            TestAssert.Throws<IOException>(() => { using var edit = File.OpenWrite(Path.Combine(f.Root, ".magnolie-trash-" + heldArchive.Operation)); },
                "Recovery copy was writable while publication/Saved/END was still owned.");
            TestAssert.Throws<IOException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, heldArchive, () => true),
                "A competing restore consumed the recovery copy while new publication was owned.");
            await DeviceFileReconcileTests.Finish(f, run, 0); var result = await operation;
            var trash = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id);
            TestAssert.That(result.Plan.Members.All(member => member.Action == "replace_managed_desktop") && !result.NeedsReview && result.ReceivedJobId is not null &&
                File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(next[0]) && trash.Count == generation * 2 && trash.All(entry => entry.State == "trashed") &&
                trash.Any(entry => File.ReadAllBytes(Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation)).SequenceEqual(before[0])) &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Contains(originalJob), "Native replacement lost original bytes or original Saved/END lineage.");
            DeviceFileConnectionRunsTests.Clear(f); var end = f.Native.Connection.EndNativeMediaAlbumAsync(run); var request = DeviceFileConnectionRunsTests.Request(f);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held")); await end;
            var repeated = await DeviceFileConnectionReceiveTests.Ready(f, f.Manifest(("first.jpg", next[0]), ("second.jpg", next[1])));
            var plan = f.Native.Connection.PlanNativeMediaRun(repeated);
            TestAssert.That(plan.Members.All(member => member.Action == "unchanged" && member.BaselineJob == result.ReceivedJobId), "Repeat did not select the latest protected replacement baseline.");
            var skip = f.Native.Connection.ReconcileNativeMediaBatchAsync(repeated); await DeviceFileReconcileTests.Finish(f, repeated, 0); await skip;
            DeviceFileConnectionRunsTests.Clear(f); end = f.Native.Connection.EndNativeMediaAlbumAsync(repeated); request = DeviceFileConnectionRunsTests.Request(f);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, repeated.Lease.RunId, "canceled_held")); await end;
            before = next;
        }
        TestAssert.That(f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (3, 0, 0L), "Replacement widened or failed to retire actual receive budget.");
    }

    internal static async Task WindowsReplacementWithdrawalAndEditAsync()
    {
        foreach (var mutation in new[] { "permit", "edit" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
            var next = new[] { "new first"u8.ToArray(), "new second"u8.ToArray() }; var allowed = true;
            var run = await DeviceFileConnectionReceiveTests.Ready(f, f.Manifest(("first.jpg", next[0]), ("second.jpg", next[1])));
            var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run, replacementConsent: new(() => allowed));
            _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
            if (mutation == "permit") allowed = false;
            else { using var edit = File.OpenWrite(Path.Combine(f.Root, "first.jpg")); edit.WriteByte(42); }
            var expected = File.ReadAllBytes(Path.Combine(f.Root, "first.jpg"));
            await Send(f, next);
            await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(operation, "Native replacement ignored current consent/local edits: " + mutation);
            TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(expected) &&
                File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(Original[1]) && f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Count == 0 &&
                DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]!.GetValue<string>() != DeviceFileSavedEnvelope.Kind),
                "Failed replacement changed originals or manufactured Saved: " + mutation);
        }
    }

    internal static async Task WindowsReplacementOccupiedPublicationAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var next = new[] { "new first"u8.ToArray(), "new second"u8.ToArray() }; var path = Path.Combine(f.Root, "first.jpg");
        var run = await DeviceFileConnectionReceiveTests.Ready(f, f.Manifest(("first.jpg", next[0]), ("second.jpg", next[1])));
        var operation = f.Native.Connection.ReconcileNativeMediaBatchAsync(run, replacementConsent: new(() =>
        {
            if (!File.Exists(path) && Directory.EnumerateFiles(f.Root, ".magnolie-trash-*").Any()) File.WriteAllText(path, "concurrent new user file");
            return true;
        }));
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind); await Send(f, next);
        await DeviceFileConnectionSourcesTests.FailsAsync<IOException>(operation, "Replacement publication overwrote a newly occupied target.");
        var trash = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single();
        TestAssert.That(File.ReadAllText(path) == "concurrent new user file" &&
            File.ReadAllBytes(Path.Combine(f.Root, ".magnolie-trash-" + trash.Operation)).SequenceEqual(Original[0]) &&
            File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(Original[1]) &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id).ActiveJobs == 1 &&
            DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]!.GetValue<string>() != DeviceFileSavedEnvelope.Kind),
            "Uncertain replacement lost old/new user bytes, retired budget or fabricated Saved.");
    }

    internal static async Task WindowsReplacementAdmissionGuardsAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var manifest = f.Manifest(("first.jpg", "changed first"u8.ToArray()), ("second.jpg", "changed second"u8.ToArray()));
        var run = await DeviceFileConnectionReceiveTests.Ready(f, manifest); var allowed = true;
        var consent = new NativeMediaReplacementConsent(() => allowed);
        var plan = f.Native.Connection.PlanNativeMediaRun(run, consent);
        var replacement = f.Native.Store.CreateNativeMediaReplacements(manifest, run.Pages, plan, consent);
        using var job = f.Native.Store.BeginNativeMediaReceiveJob(f.Native.Peer.Id, "images", manifest, f.Current,
            new(run.Pages[0].SourceEpoch, null), replacement);
        TestAssert.Throws<InvalidDataException>(() => job.PrepareNativeAcceptance(Guid.NewGuid().ToString("D")), "Replacement accepted before binding actual native media identity.");
        job.BindNativeMediaContext(run.CatalogId, run.AlbumId, run.Pages); _ = job.PrepareNativeAcceptance(Guid.NewGuid().ToString("D"));
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.BeginNativeMediaReceiveJob(f.Native.Peer.Id, "images",
            f.Manifest(("first.jpg", "changed first"u8.ToArray()), ("second.jpg", "changed second"u8.ToArray())), f.Current, new(run.Pages[0].SourceEpoch, null), replacement),
            "A second replacement reservation inherited another active target slot.");
        allowed = false; TestAssert.Throws<InvalidDataException>(consent.Require, "Replacement consent ignored withdrawal.");
        allowed = true; TestAssert.Throws<InvalidDataException>(consent.Require, "A historical replacement consent revived after withdrawal.");
        TestAssert.That(f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Count == 0 &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (2, 1, manifest.TotalBytes) &&
            File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(Original[0]), "Admission guards changed original bytes/history or admitted another reservation.");
    }
}
