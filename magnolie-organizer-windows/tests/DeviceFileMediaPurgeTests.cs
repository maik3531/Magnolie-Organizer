using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileMediaPurgeTests
{
    private static PersonalActorNativeSaveHost Host(DeviceFileReceiveJobTests.Fixture f, int days = 0, bool enabled = true)
        => new(Path.Combine(f.Native.Paths.Root, "purge-book-" + Guid.NewGuid().ToString("N")),
            "{\"einstellungen\":{\"papierkorb\":{\"an\":" + (enabled ? "true" : "false") + ",\"tage\":" + days + "}}}");
    private static NativeMediaBookPermit Permit(PersonalActorNativeSaveHost host) => NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
    private static NativeMediaTrashEntry Trash(DeviceFileReceiveJobTests.Fixture f)
    {
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        return f.Native.Store.TrashNativeMediaSavedFile(f.Native.Peer.Id, job.JobId, job.Version, new string('0', 31) + "1", () => true);
    }

    internal static async Task WindowsRetentionAndManualNeverAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var job = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); var entry = Trash(f);
        foreach (var days in new[] { 0, 7, 30, 90, 365 })
        {
            var host = Host(f, days); var permit = Permit(host);
            TestAssert.That(!TelefonStore.NativeMediaTrashExpired(entry, permit, entry.ChangedMs - 1) &&
                !TelefonStore.NativeMediaTrashExpired(entry, permit, entry.ChangedMs + Math.Max(0, days * 86400000L - 1)), "Fresh/future trash expired.");
            TestAssert.That(TelefonStore.NativeMediaTrashExpired(entry, permit, entry.ChangedMs + Math.Max(1, days) * 86400000L) == (days != 0), "Canonical retention boundary/never changed.");
        }
        var never = Permit(Host(f));
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, never), "Never retention permitted unconfirmed unlink.");
        var wrong = entry with { FileId = new string('0', 31) + "2" };
        var consent = NativeMediaPermanentConsent.FromConfirmedNativeChoice(never, entry);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, wrong, never, consent), "Native confirmation moved to another file.");
        var result = f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, never, NativeMediaPermanentConsent.FromConfirmedNativeChoice(never, entry));
        TestAssert.That(result.State == "purged" && result.ChangedMs == entry.ChangedMs &&
            !File.Exists(Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation)) && File.ReadAllText(Path.Combine(f.Root, "second.jpg")) == "original second" &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == job && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L),
            "Manual purge lost another file or changed immutable receive/Saved/END history.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RestoreNativeMediaTrash(f.Native.Peer.Id, entry, () => true), "Old trash selection restored after purge.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, never,
            NativeMediaPermanentConsent.FromConfirmedNativeChoice(never, entry)), "Old trash selection replayed purge.");
    }

    internal static async Task WindowsActualExpiryAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f); var entry = Trash(f);
        var permit = Permit(Host(f, 7)); var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation);
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit, retentionNow: entry.ChangedMs + 7 * 86400000L - 1), "Trash expired before its exact retention boundary.");
        TestAssert.That(File.Exists(trash), "Premature expiry touched original trash.");
        var result = f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit, retentionNow: entry.ChangedMs + 7 * 86400000L);
        TestAssert.That(result.State == "purged" && !File.Exists(trash), "Actual NT expiry did not complete its prepared journal.");
    }

    internal static async Task WindowsForeignFileAndPolicyHoldAsync()
    {
        foreach (var reason in new[] { "identity", "content", "missing", "destination", "locked", "disabled" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f); var entry = Trash(f);
            var host = Host(f, 7, reason != "disabled"); var allowed = true;
            var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, () => allowed ? host.Saved() : null);
            var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation); var original = File.ReadAllBytes(trash);
            if (reason == "identity") { File.Move(trash, trash + ".kept"); File.WriteAllBytes(trash, original); }
            if (reason == "content") File.WriteAllText(trash, "modified user data");
            if (reason == "missing") File.Move(trash, trash + ".kept");
            if (reason == "destination")
            {
                var path = Path.Combine(f.Native.Paths.Root, "foreign-purge-root"); Directory.CreateDirectory(path);
                using var root = DeviceFileNativeDirectory.OpenExistingForReceive(path);
                TestAssert.Throws<InvalidDataException>(() => f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "images", f.Destination.Version, root),
                    "Historical purge target was reassociated with a foreign root.");
                TestAssert.That(f.Native.Store.ReadNativeMediaDestination(f.Native.Peer.Id, "images") == f.Destination && File.ReadAllBytes(trash).SequenceEqual(original),
                    "Rejected destination change lost original trash ownership.");
                continue;
            }
            if (reason == "locked") allowed = false;
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit, retentionNow: entry.ChangedMs + 7 * 86400000L),
                "Unsafe automatic purge admitted " + reason);
            TestAssert.That(f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single() == entry &&
                (reason == "missing" ? File.ReadAllBytes(trash + ".kept").SequenceEqual(original) : File.Exists(trash)), "Failed purge touched bytes/journal: " + reason);
        }
    }

    internal static async Task WindowsInterruptedRemovalRecoveryAsync()
    {
        foreach (var boundary in new[] { "prepared", "removed", "foreign_recovery" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f); var entry = Trash(f);
            var host = Host(f); var cut = true; var trash = Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation);
            NativeBookSaveState? Current()
            {
                var withdrawn = boundary == "prepared" ? f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single().State == "purge_prepared" : !File.Exists(trash);
                return cut && withdrawn ? null : host.Saved();
            }
            var permit = NativeMediaBookPermit.Capture(host.Snapshot()!, Current);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit,
                NativeMediaPermanentConsent.FromConfirmedNativeChoice(permit, entry)), "Uncertain native removal fabricated completion.");
            var pending = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single();
            TestAssert.That(pending.State == "purge_prepared" && pending.ChangedMs == entry.ChangedMs && File.Exists(trash) == (boundary == "prepared"), "Uncertain purge lost preparation/retention origin.");
            cut = false; permit = NativeMediaBookPermit.Capture(host.Snapshot()!, Current);
            if (boundary == "foreign_recovery")
            {
                File.WriteAllText(trash, "new user file must remain");
                TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, pending, permit,
                    NativeMediaPermanentConsent.FromConfirmedNativeChoice(permit, pending)), "Recovery deleted a foreign replacement at the old trash name.");
                TestAssert.That(File.ReadAllText(trash) == "new user file must remain", "Foreign recovery lost user bytes.");
            }
            else
            {
                var result = f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, pending, permit, NativeMediaPermanentConsent.FromConfirmedNativeChoice(permit, pending));
                TestAssert.That(result.State == "purged" && result.Operation == entry.Operation && !File.Exists(trash), "Prepared native purge could not recover without a new operation.");
            }
        }
    }

    internal static async Task WindowsNativeUiAndFailedSaveAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f); var entry = Trash(f);
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        TestAssert.Throws<InvalidDataException>(() => coordinator.ReadNativeMediaTrashUi(f.Native.Peer.Id), "Trash UI bypassed the actually saved book.");
        var host = Host(f); coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var item = coordinator.ReadNativeMediaTrashUi(f.Native.Peer.Id).Single();
        TestAssert.That(item.Entry == entry && item.DisplayName == "first.jpg" && item.MediaType == "images" &&
            coordinator.SweepNativeMediaTrashFromSavedBook(f.Native.Peer.Id) == 0, "Trash listing fabricated a path or automatic expiry for Never.");
        var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
        var lane = typeof(TelefonCoordinator).GetField("nativeMediaWorker", flags)!;
        lane.SetValue(coordinator, 1);
        try { TestAssert.Throws<InvalidDataException>(() => coordinator.RestoreNativeMediaTrashUi(f.Native.Peer.Id, entry.Operation, entry.Version), "Restore overlapped another native worker."); }
        finally { lane.SetValue(coordinator, 0); }
        var choice = coordinator.PrepareNativeMediaRemovalChoice(f.Native.Peer.Id, entry.Operation, entry.Version);
        var consent = NativeMediaPermanentConsent.FromConfirmedNativeChoice(choice.Permit, choice.Item.Entry);
        host.FailAfterPrimary = true;
        using (var message = System.Text.Json.JsonDocument.Parse(new System.Text.Json.Nodes.JsonObject { ["id"] = 1,
            ["text"] = "{\"einstellungen\":{\"papierkorb\":{\"an\":false,\"tage\":0}}}" }.ToJsonString()))
            await host.SaveAsync(message.RootElement);
        TestAssert.Throws<InvalidDataException>(() => coordinator.RemoveConfirmedNativeMediaTrash(choice, consent), "Native confirmation survived a failed post-replace book save.");
        TestAssert.That(File.ReadAllText(Path.Combine(f.Root, ".magnolie-trash-" + entry.Operation)) == "original first" &&
            f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).Single() == entry, "Failed native book save lost retained trash or prepared deletion.");
    }

    internal static async Task WindowsReplacementArchiveUntilSavedEndAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); await DeviceFileReconcileTests.Establish(f);
        var originalJob = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        byte[][] data = ["new first protected"u8.ToArray(), "new second protected"u8.ToArray()];
        var run = await DeviceFileConnectionReceiveTests.Ready(f, f.Manifest(("first.jpg", data[0]), ("second.jpg", data[1])));
        var replacing = f.Native.Connection.ReconcileNativeMediaBatchAsync(run, replacementConsent: new(() => true));
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
        for (var index = 0; index < 2; index++)
        {
            var request = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.RequestKind, index);
            await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionReceiveTests.Chunk(request, data[index]));
        }
        _ = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileSavedEnvelope.Kind);
        var entry = f.Native.Store.NativeMediaTrashHistory(f.Native.Peer.Id).First(); var permit = Permit(Host(f));
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit,
            NativeMediaPermanentConsent.FromConfirmedNativeChoice(permit, entry)), "Replacement Saved without actual source END permitted original archive removal.");
        await DeviceFileReconcileTests.Finish(f, run, 0); await replacing;
        var removed = f.Native.Store.PurgeNativeMediaTrash(f.Native.Peer.Id, entry, permit, NativeMediaPermanentConsent.FromConfirmedNativeChoice(permit, entry));
        TestAssert.That(removed.State == "purged" && File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(data[0]) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Contains(originalJob), "Archive removal changed the new publication or original receive history.");
    }
}
