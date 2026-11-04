using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionRunsTests
{
    private static readonly string Version = new('d', 64);
    private static readonly string Catalog = Guid.NewGuid().ToString("D"), Album = Guid.NewGuid().ToString("D");
    internal static JsonObject Request(DeviceFileReceiveJobTests.Fixture f)
    {
        var request = DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Single();
        _ = DeviceFileSources.ParseRequest(request, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); return request;
    }
    internal static void Clear(DeviceFileReceiveJobTests.Fixture f) { f.Native.Stream.SetLength(0); f.Native.Stream.Position = 0; }
    internal static JsonObject Reply(JsonObject request, string runId, string state, bool? batchEnd = null)
    {
        var operation = request["body"]!["operation"]!.GetValue<string>();
        var ending = operation is "end_run" or "end_album" or "end_resume";
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var body = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = operation,
            ["version"] = Version, ["run_id"] = runId, ["state"] = state,
            ["source_io_ended"] = state is "snapshot_ready" or "empty_ready" or "canceled_held" or "failed_held" };
        if (ending) body["run_ended"] = true;
        else if (!operation.Contains("resume", StringComparison.Ordinal)) body["batch_end"] = batchEnd;
        if (operation is "offer_run" or "offer_resume") { body["offer_id"] = Guid.NewGuid().ToString("D"); body["manifest_sha256"] = new string('a', 64); }
        if (request["body"]!["media_type"] is JsonNode mediaType) body["media_type"] = mediaType.DeepClone();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"),
            ["kind"] = DeviceFileSources.RunResultKind, ["created_ms"] = now, ["expires_ms"] = now + 60000, ["body"] = body };
    }
    private static Task Fails(Task task) => DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(task, "Unsafe source lifecycle was admitted.");
    private static async Task Quiesce(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run)
    {
        Clear(f); var cancel = f.Native.Connection.CancelNativeMediaRunAsync(run); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held", run.Result.BatchEnd)); await cancel; Clear(f);
    }
    internal static JsonObject Media(JsonObject request, string runId, int after = 0, bool more = false, string? epoch = null)
    {
        var reply = Reply(request, runId, "snapshot_ready", false); reply["kind"] = DeviceFileSources.MediaKind;
        reply["body"] = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = request["body"]!["operation"]!.DeepClone(), ["version"] = Version,
            ["run_id"] = runId, ["page"] = new JsonObject { ["format"] = 1, ["manifest_sha256"] = new string('a', 64), ["source_epoch"] = epoch ?? new string('e', 64),
                ["media_type"] = "images", ["insertion_witness"] = true, ["after"] = after, ["next_cursor"] = more ? after + 1 : null,
                ["total_files"] = 2, ["entries"] = new JsonArray(new JsonObject { ["file_id"] = (after + 1).ToString("x32"), ["photo_id"] = new string(after == 0 ? 'b' : 'c', 64), ["media_kind"] = "image" }) } };
        if (request["body"]!["media_type"] is JsonNode mediaType)
        {
            reply["body"]!["media_type"] = mediaType.DeepClone(); reply["body"]!["page"]!["media_type"] = mediaType.DeepClone();
            reply["body"]!["page"]!["entries"]![0]!["media_kind"] = "video";
        }
        return reply;
    }
    private static async Task<TelefonConnection.NativeMediaSourceRun> Start(DeviceFileReceiveJobTests.Fixture f, string state, bool? batchEnd, string mediaType = "images")
    {
        Clear(f); var pending = f.Native.Connection.StartNativeMediaBatchAsync(Version, Catalog, Album, true, mediaType);
        var request = Request(f); var id = Guid.NewGuid().ToString("D");
        await f.Native.Connection.HandlePlainAsync(Reply(request, id, state, batchEnd)); var run = await pending;
        TestAssert.That(run.Result.RunId == id && !run.GrantsReadAuthority && !run.Result.RunEnded, "Starting reply fabricated END or lost original identity.");
        return run;
    }
    internal static Task CodecAsync()
    {
        const long now = 100000; var id = Guid.NewGuid().ToString("D");
        foreach (var media in new[] { "images", "video" })
        {
            foreach (var operation in new[] { "batch_run", "next_batch", "run_status", "cancel_run", "end_run", "end_album", "resume_status", "cancel_resume", "offer_resume", "end_resume", "resume_media_page" })
            {
                var starting = operation == "batch_run";
                var message = DeviceFileSources.CreateRequest(operation, now, Version, catalogId: starting ? Catalog : null,
                    albumId: starting ? Album : null, desktopChoice: starting ? true : null, runId: starting ? null : id,
                    after: operation == "resume_media_page" ? 0 : null, mediaType: media);
                var parsed = DeviceFileSources.ParseRequest(message, now);
                TestAssert.That(parsed.Operation == operation && parsed.MediaType == media, "Lifecycle request lost operation/media.");
            }
        }
        var request = DeviceFileSources.CreateRequest("batch_run", now, Version, catalogId: Catalog, albumId: Album, desktopChoice: true);
        var reply = Reply(request, id, "empty_ready", true); // Replace wallclock envelope for pure test.
        reply["created_ms"] = now; reply["expires_ms"] = now + 60000;
        DeviceFileRunResult Parse(JsonObject value) => DeviceFileSources.ParseRunResult(value, request["message_id"]!.GetValue<string>(), "batch_run", Version, now);
        TestAssert.That(Parse(reply).BatchEnd is true && !Parse(reply).RunEnded, "Empty snapshot became actual END.");
        foreach (var (key, value) in new (string, JsonNode?)[] { ("batch_end", null), ("batch_end", JsonValue.Create(false)),
            ("batch_end", JsonValue.Create(1)), ("source_io_ended", JsonValue.Create(false)), ("run_ended", JsonValue.Create(true)), ("run_id", JsonValue.Create("not-a-run")) })
        {
            var wrong = reply.DeepClone().AsObject(); wrong["body"]![key] = value;
            TestAssert.Throws<InvalidDataException>(() => Parse(wrong), "Malformed batch/END metadata accepted.");
        }
        var endRequest = DeviceFileSources.CreateRequest("end_run", now, Version, runId: id);
        var endReply = Reply(endRequest, id, "canceled_held"); endReply["created_ms"] = now; endReply["expires_ms"] = now + 60000;
        DeviceFileRunResult End(JsonObject value) => DeviceFileSources.ParseRunResult(value, endRequest["message_id"]!.GetValue<string>(), "end_run", Version, now, id);
        TestAssert.That(End(endReply).RunEnded && End(endReply).SourceIoEnded, "Explicit source END was lost.");
        foreach (var key in new[] { "run_ended", "source_io_ended" })
        {
            var wrong = endReply.DeepClone().AsObject(); wrong["body"]![key] = false;
            TestAssert.Throws<InvalidDataException>(() => End(wrong), "Unconfirmed source END accepted.");
        }
        return Task.CompletedTask;
    }

    internal static async Task WindowsBatchEndAndAdvanceAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var run = await Start(f, "snapshot_ready", false);
        Clear(f); await Fails(f.Native.Connection.StartNativeMediaBatchAsync(Version, Catalog, Album, true));
        TestAssert.That(f.Native.Stream.Length == 0, "An owned run was replaced by a normal new batch.");
        var offering = f.Native.Connection.OfferNativeMediaRunAsync(run); var offerRequest = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(offerRequest, run.Lease.RunId, "snapshot_ready", false));
        TestAssert.That((await offering).OfferId is not null, "Correlated original offer not retained.");
        await Quiesce(f, run); var ending = f.Native.Connection.EndNativeMediaRunAsync(run); var endRequest = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(endRequest, run.Lease.RunId, "canceled_held")); await ending;
        TestAssert.That(run.Result.RunEnded && run.Result.BatchEnd is false, "END discarded the album cursor.");
        Clear(f); var advancing = f.Native.Connection.NextNativeMediaBatchAsync(run); var nextRequest = Request(f);
        var nextId = Guid.NewGuid().ToString("D"); await f.Native.Connection.HandlePlainAsync(Reply(nextRequest, nextId, "empty_ready", true));
        var next = await advancing;
        TestAssert.That(next.Lease.RunId == nextId && next.CatalogId == Catalog && next.AlbumId == Album && next.DesktopChoice, "Advancement lost original album provenance.");
        Clear(f); await Fails(f.Native.Connection.CancelNativeMediaRunAsync(run));
        TestAssert.That(f.Native.Stream.Length == 0, "Old run lease survived cursor advancement.");
        await Quiesce(f, next); var nextEnd = f.Native.Connection.EndNativeMediaRunAsync(next); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, nextId, "canceled_held")); await nextEnd;
        Clear(f); await Fails(f.Native.Connection.NextNativeMediaBatchAsync(next));
        var albumEnd = f.Native.Connection.EndNativeMediaAlbumAsync(next); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, nextId, "canceled_held")); await albumEnd;
        Clear(f); await Fails(f.Native.Connection.EndNativeMediaAlbumAsync(next));
        TestAssert.That(f.Native.Stream.Length == 0, "Released album ownership could be reused.");
    }

    internal static async Task WindowsCleanupAfterWithdrawalAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var run = await Start(f, "preparing", null);
        Clear(f); await Fails(f.Native.Connection.EndNativeMediaRunAsync(run));
        var preferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id);
        f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, preferences.Version, false, false, false);
        f.Local = new(new(8, new string('e', 64), false, false), f.Local.Owner, false);
        TestAssert.That(f.Current() is null, "Withdrawn receive data remained ready.");
        await Fails(f.Native.Connection.OfferNativeMediaRunAsync(run));
        TestAssert.That(f.Native.Stream.Length == 0, "Cleanup ownership authorized new media offer/END before quiescence.");
        var cancel = f.Native.Connection.CancelNativeMediaRunAsync(run); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "cancel_pending", null)); await cancel;
        Clear(f); var status = f.Native.Connection.ReadNativeMediaRunAsync(run); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held", null)); await status;
        Clear(f); var end = f.Native.Connection.EndNativeMediaRunAsync(run); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held")); await end;
        Clear(f); var album = f.Native.Connection.EndNativeMediaAlbumAsync(run); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held")); await album;
        TestAssert.That(f.Current() is null && !run.GrantsReadAuthority, "Source cleanup revived receive consent.");
    }

    internal static async Task WindowsRejectReusedNextAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var run = await Start(f, "snapshot_ready", false);
        await Quiesce(f, run); var end = f.Native.Connection.EndNativeMediaRunAsync(run); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held")); await end;
        Clear(f); var next = f.Native.Connection.NextNativeMediaBatchAsync(run); request = Request(f);
        await Fails(f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "snapshot_ready", false))); await Fails(next);
    }

    internal static async Task WindowsMediaPagesAndAlbumScopeAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var run = await Start(f, "snapshot_ready", false);
        Clear(f); var page = f.Native.Connection.ReadNativeMediaPageAsync(run); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Media(request, run.Lease.RunId, more: true)); await page;
        Clear(f); await Fails(f.Native.Connection.OfferNativeMediaRunAsync(run));
        TestAssert.That(f.Native.Stream.Length == 0, "Incomplete media metadata allowed offer.");
        page = f.Native.Connection.ReadNativeMediaPageAsync(run); request = Request(f);
        TestAssert.That(request["body"]!["after"]!.GetValue<int>() == 1, "Media cursor was guessed/restarted.");
        await f.Native.Connection.HandlePlainAsync(Media(request, run.Lease.RunId, after: 1)); await page;
        Clear(f); await Fails(f.Native.Connection.ReadNativeMediaPageAsync(run));
        var offer = f.Native.Connection.OfferNativeMediaRunAsync(run); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "snapshot_ready", false)); await offer;
        await Quiesce(f, run); var end = f.Native.Connection.EndNativeMediaRunAsync(run); request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Reply(request, run.Lease.RunId, "canceled_held")); await end;
        Clear(f); var next = f.Native.Connection.NextNativeMediaBatchAsync(run); request = Request(f); var nextId = Guid.NewGuid().ToString("D");
        await f.Native.Connection.HandlePlainAsync(Reply(request, nextId, "snapshot_ready", false)); var nextRun = await next;
        Clear(f); page = f.Native.Connection.ReadNativeMediaPageAsync(nextRun); request = Request(f);
        await Fails(f.Native.Connection.HandlePlainAsync(Media(request, nextId, more: true, epoch: new string('f', 64)))); await Fails(page);
    }

    internal static async Task WindowsUnconfirmedEndAndRollbackAsync()
    {
        foreach (var badEnd in new[] { true, false })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var run = await Start(f, "snapshot_ready", false);
            if (badEnd) await Quiesce(f, run);
            Clear(f);
            var pending = badEnd ? f.Native.Connection.EndNativeMediaRunAsync(run) : f.Native.Connection.ReadNativeMediaRunAsync(run);
            var request = Request(f); var reply = Reply(request, run.Lease.RunId, badEnd ? "canceled_held" : "preparing", badEnd ? null : false);
            if (badEnd) reply["body"]!["run_ended"] = false;
            await Fails(f.Native.Connection.HandlePlainAsync(reply)); await Fails(pending);
            TestAssert.That(!run.Result.RunEnded && ReferenceEquals(f.Native.Connection.CurrentNativeMediaSourceRun, run), "Rejected END/rollback discarded original run ownership.");
        }
    }

    internal static JsonObject Resume(JsonObject request, DeviceFileManifest manifest, string phoneJobId)
    {
        var reply = Reply(request, Guid.NewGuid().ToString("D"), "snapshot_ready"); reply["kind"] = DeviceFileSources.ResumeKind;
        reply["expires_ms"] = request["expires_ms"]!.DeepClone();
        reply["body"] = new JsonObject { ["format"] = 1, ["request_id"] = request["message_id"]!.DeepClone(), ["operation"] = "resume_lookup", ["version"] = Version,
            ["history"] = new JsonObject { ["job_id"] = phoneJobId, ["job_version"] = new string('f', 64), ["phase"] = "sealed", ["source_id"] = manifest.SourceId,
                ["transfer_id"] = manifest.TransferId, ["manifest_sha256"] = manifest.Fingerprint, ["remote_saved_history"] = false, ["attempt_phase"] = null } };
        return reply;
    }

    internal static async Task WindowsOriginalSourceResumeHistoryAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var bytes = "held original bytes"u8.ToArray(); var manifest = f.Manifest(("resume.jpg", bytes));
        var job = f.Begin(manifest); job.ReceiveChunk(manifest.Files[0].Id, 0, bytes); var jobId = job.JobId; var version = job.Version; job.Dispose();
        var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, jobId, version);
        TestAssert.That(!selected.GrantsResumeAuthority, "Historical selection granted file access.");
        Clear(f); var pending = f.Native.Connection.LookupNativeMediaResumeAsync(selected, Version); var request = Request(f);
        TestAssert.That(request["body"]!["source_id"]!.GetValue<string>() == manifest.SourceId && request["body"]!["transfer_id"]!.GetValue<string>() == manifest.TransferId,
            "Resume lookup inferred another original manifest.");
        var phoneJobId = Guid.NewGuid().ToString("N");
        await f.Native.Connection.HandlePlainAsync(Resume(request, manifest, phoneJobId)); var lookup = await pending;
        TestAssert.That(lookup.History.JobId == phoneJobId && phoneJobId != jobId && !lookup.History.GrantsResumeAuthority &&
            lookup.Selection.JobId == jobId && lookup.Selection.Version != selected.Version, "Phone job ownership was guessed from desktop job or failed to persist.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RequireNativeMediaResumeSelection(selected), "Old local history version survived durable source ownership update.");
        f.Native.Store.RequireNativeMediaResumeSelection(lookup.Selection);
        var history = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        TestAssert.That(history.JobId == jobId && history.Phase == "receiving" &&
            File.ReadAllBytes(Path.Combine(f.Root, ".magnolie-receive-" + jobId, manifest.Files[0].Id + ".part")).SequenceEqual(bytes), "Resume metadata replaced original bytes/phase/job.");
        Clear(f); var changed = f.Native.Connection.LookupNativeMediaResumeAsync(lookup.Selection, Version); request = Request(f);
        await Fails(f.Native.Connection.HandlePlainAsync(Resume(request, manifest, Guid.NewGuid().ToString("N")))); await Fails(changed);
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Version == lookup.Selection.Version, "A different source original silently replaced protected resume provenance.");
    }

    internal static async Task WindowsResumeCorrelationAndExpiryAsync()
    {
        foreach (var change in new[] { "manifest", "request", "expiry", "attempt", "media" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var manifest = f.Manifest(("resume.jpg", "hello"u8.ToArray()));
            var job = f.Begin(manifest); var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, job.JobId, job.Version); job.Dispose();
            Clear(f); var pending = f.Native.Connection.LookupNativeMediaResumeAsync(selected, Version); var request = Request(f);
            var reply = Resume(request, manifest, Guid.NewGuid().ToString("N")); var body = reply["body"]!.AsObject();
            if (change == "manifest") body["history"]!["manifest_sha256"] = new string('b', 64);
            if (change == "request") body["request_id"] = Guid.NewGuid().ToString("D");
            if (change == "expiry") reply["expires_ms"] = request["expires_ms"]!.GetValue<long>() + 1;
            if (change == "attempt") body["history"]!["attempt_phase"] = "accepted";
            if (change == "media") body["media_type"] = "video";
            await Fails(f.Native.Connection.HandlePlainAsync(reply)); await Fails(pending);
            TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Version == selected.Version, "Invalid source history changed original local job: " + change);
        }
    }

    internal static async Task WindowsResumeStaleLocalOwnerAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var manifest = f.Manifest(("resume.jpg", "hello"u8.ToArray()));
        var job = f.Begin(manifest); var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, job.JobId, job.Version); job.Dispose();
        Clear(f); var pending = f.Native.Connection.LookupNativeMediaResumeAsync(selected, Version); var request = Request(f);
        var reply = Resume(request, manifest, Guid.NewGuid().ToString("N"));
        var remote = DeviceFileSources.ParseResumeHistory(reply, request["message_id"]!.GetValue<string>(), Version, manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        var newer = f.Native.Store.RecordNativeSourceResumeHistory(selected, remote, () => { });
        await Fails(f.Native.Connection.HandlePlainAsync(reply)); await Fails(pending);
        TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Version == newer.Version,
            "A delayed source history reply overwrote a newer original local history owner.");
    }

    private static async Task<TelefonStore.NativeMediaResumeSelection> Original(DeviceFileReceiveJobTests.Fixture f, string jobId, string version, DeviceFileManifest manifest)
    {
        var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, jobId, version);
        Clear(f); var pending = f.Native.Connection.LookupNativeMediaResumeAsync(selected, Version); var request = Request(f);
        await f.Native.Connection.HandlePlainAsync(Resume(request, manifest, Guid.NewGuid().ToString("N")));
        return (await pending).Selection;
    }

    internal static async Task WindowsActualCheckpointRecoveryAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var bytes = Enumerable.Range(0, 70000).Select(index => (byte)(index % 251)).ToArray(); var manifest = f.Manifest(("recovered.jpg", bytes));
        var original = f.Begin(manifest); var id = original.JobId;
        original.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]); var version = original.Version; original.Dispose();
        var selected = await Original(f, id, version, manifest);
        using var recovered = f.Native.Store.RecoverNativeMediaReceiveJob(selected, f.Current);
        TestAssert.That(recovered.JobId == id && recovered.Version == selected.Version, "Recovery fabricated a new job or progress version.");
        recovered.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]); // Exact old duplicate from rebuilt original ledger.
        TestAssert.That(recovered.Version == selected.Version, "Exact duplicate checkpoint rewrote original history.");
        recovered.ReceiveChunk(manifest.Files[0].Id, 1, bytes[DeviceFileManifest.ChunkBytes..]); recovered.PublishAll(); recovered.Dispose();
        TestAssert.That(File.ReadAllBytes(Path.Combine(f.Root, "recovered.jpg")).SequenceEqual(bytes) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().JobId == id, "Recovered original bytes/job did not publish correctly.");
        TestAssert.Throws<InvalidDataException>(() => f.Native.Store.RecoverNativeMediaReceiveJob(selected, f.Current), "Stale original checkpoint owner reopened published bytes.");
    }

    internal static async Task WindowsCheckpointMutationHoldAsync()
    {
        foreach (var change in new[] { "prefix", "tail", "replacement", "unknown", "missing" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
            var bytes = new byte[70000]; var manifest = f.Manifest(("held-recovery.jpg", bytes));
            var job = f.Begin(manifest); job.ReceiveChunk(manifest.Files[0].Id, 0, bytes[..DeviceFileManifest.ChunkBytes]);
            var id = job.JobId; var version = job.Version; job.Dispose();
            var selected = await Original(f, id, version, manifest);
            var stage = Path.Combine(f.Root, ".magnolie-receive-" + id); var payload = Path.Combine(stage, manifest.Files[0].Id + ".part");
            if (change == "prefix") { using var edit = File.OpenWrite(payload); edit.WriteByte(1); }
            if (change == "tail") { using var edit = new FileStream(payload, FileMode.Append); edit.WriteByte(1); }
            if (change == "replacement") { File.Move(payload, payload + ".original"); File.WriteAllBytes(payload, bytes[..DeviceFileManifest.ChunkBytes]); File.Move(payload + ".original", Path.Combine(f.Root, "held-original-part")); }
            if (change == "unknown") File.WriteAllText(Path.Combine(stage, "unknown"), "keep unrelated original evidence");
            if (change == "missing") File.Move(payload, Path.Combine(f.Root, "held-original-part"));
            var before = Directory.EnumerateFiles(f.Root, "*", SearchOption.AllDirectories).ToDictionary(path => path, File.ReadAllBytes);
            try { using var unexpected = f.Native.Store.RecoverNativeMediaReceiveJob(selected, f.Current); throw new InvalidOperationException("Mutated original checkpoint was recovered: " + change); }
            catch (InvalidDataException) { }
            TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Version == selected.Version &&
                before.All(item => File.ReadAllBytes(item.Key).SequenceEqual(item.Value)) && Directory.EnumerateFiles(f.Root, "*", SearchOption.AllDirectories).Count() == before.Count,
                "Recovery HOLD changed/recreated/truncated original files/history: " + change);
        }
    }

    internal static async Task WindowsRecoveredSourceResumeAndCleanupAsync()
    {
        await RecoveredSourceResumeAsync(false);
        await RecoveredSourceResumeAsync(true);
    }

    private static async Task RecoveredSourceResumeAsync(bool invalidMember)
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var bytes = "original cache"u8.ToArray(); var manifest = f.Manifest(("resume-source.jpg", bytes));
        var original = f.Begin(manifest); original.ReceiveChunk(manifest.Files[0].Id, 0, bytes);
        var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, original.JobId, original.Version); original.Dispose();
        Clear(f); var lookupTask = f.Native.Connection.LookupNativeMediaResumeAsync(selected, Version); var request = Request(f);
        var phoneJobId = Guid.NewGuid().ToString("N"); await f.Native.Connection.HandlePlainAsync(Resume(request, manifest, phoneJobId)); var lookup = await lookupTask;
        using var recovered = f.Native.Store.RecoverNativeMediaReceiveJob(lookup.Selection, f.Current);
        Clear(f); var start = f.Native.Connection.StartNativeMediaResumeAsync(lookup, recovered, Catalog, Album, true); request = Request(f);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "resume_run" && request["body"]!["original_job_id"]!.GetValue<string>() == phoneJobId &&
            request["body"]!["original_job_version"]!.GetValue<string>() == lookup.History.JobVersion && phoneJobId != recovered.JobId,
            "Resumed source command substituted desktop/new job identity.");
        var runId = Guid.NewGuid().ToString("D"); await f.Native.Connection.HandlePlainAsync(Reply(request, runId, "snapshot_ready")); var run = await start;
        Clear(f); await Fails(f.Native.Connection.OfferNativeMediaRunAsync(run));
        var pages = f.Native.Connection.ReadNativeMediaPageAsync(run); request = Request(f);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "resume_media_page", "Resumed source metadata used ordinary-run scope.");
        var page = Media(request, runId); page["body"]!["page"]!["total_files"] = 1; page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
        if (invalidMember)
        {
            page["body"]!["page"]!["entries"]![0]!["file_id"] = new string('2', 32);
            await Fails(f.Native.Connection.HandlePlainAsync(page)); await Fails(pages);
            return;
        }
        await f.Native.Connection.HandlePlainAsync(page); await pages;
        Clear(f); var offer = f.Native.Connection.OfferNativeMediaRunAsync(run); request = Request(f);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "offer_resume", "Original source resume fell back to ordinary offer.");
        var offered = Reply(request, runId, "snapshot_ready"); offered["body"]!["manifest_sha256"] = manifest.Fingerprint;
        await f.Native.Connection.HandlePlainAsync(offered); await offer;
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, false, false, false);
        f.Local = new(new(8, new string('e', 64), false, false), f.Local.Owner, false);
        Clear(f); var cancel = f.Native.Connection.CancelNativeMediaRunAsync(run); request = Request(f);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "cancel_resume", "Resume cleanup lost original operation.");
        await f.Native.Connection.HandlePlainAsync(Reply(request, runId, "canceled_held")); await cancel;
        Clear(f); var end = f.Native.Connection.EndNativeMediaRunAsync(run); request = Request(f);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "end_resume", "Resume END used ordinary cleanup.");
        await f.Native.Connection.HandlePlainAsync(Reply(request, runId, "canceled_held")); await end;
        TestAssert.That(run.Result.RunEnded && f.Native.Connection.CurrentNativeMediaSourceRun is null &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().Phase == "receiving", "Metadata resume END retired/erased local bytes or left a stale source owner.");
    }

    internal static async Task<TelefonConnection.NativeMediaSourceRun> OfferReady(DeviceFileReceiveJobTests.Fixture f, DeviceFileManifest manifest, string mediaType = "images")
    {
        var run = await Start(f, "snapshot_ready", false, mediaType);
        foreach (var after in new[] { 0, 1 })
        {
            Clear(f); var pageTask = f.Native.Connection.ReadNativeMediaPageAsync(run); var request = Request(f);
            var page = Media(request, run.Lease.RunId, after, after == 0); page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
            await f.Native.Connection.HandlePlainAsync(page); await pageTask;
        }
        Clear(f); return run;
    }

    internal static async Task WindowsOfferBeforeCommandResultAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var manifest = f.Manifest(("first.jpg", "hello"u8.ToArray()), ("second.jpg", "world"u8.ToArray()));
        var run = await OfferReady(f, manifest); var pending = f.Native.Connection.OfferNativeMediaRunAsync(run); var request = Request(f);
        var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(offer);
        TestAssert.That(!pending.IsCompleted && run.OfferedManifest is null && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
            !Directory.EnumerateFileSystemEntries(f.Root).Any(), "Early source offer created a grant/job/file or completed before correlated result.");
        var result = Reply(request, run.Lease.RunId, "snapshot_ready", false); result["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); result["body"]!["manifest_sha256"] = manifest.Fingerprint;
        await f.Native.Connection.HandlePlainAsync(result); await pending;
        TestAssert.That(run.OfferedManifest?.Fingerprint == manifest.Fingerprint && run.OfferedMessageId == offer["message_id"]!.GetValue<string>() &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 && DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Count == 1,
            "Correlated buffered offer was lost or emitted an implicit receive acceptance.");
    }

    internal static async Task WindowsEarlyOfferCorrelationHoldAsync()
    {
        foreach (var change in new[] { "result_id", "duplicate", "expired", "unsolicited" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var manifest = f.Manifest(("first.jpg", "hello"u8.ToArray()), ("second.jpg", "world"u8.ToArray()));
            var run = await OfferReady(f, manifest);
            var pending = change == "unsolicited" ? null : f.Native.Connection.OfferNativeMediaRunAsync(run);
            var request = pending is null ? null : Request(f);
            var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            if (request is not null) offer["expires_ms"] = request["expires_ms"]!.DeepClone();
            if (change == "expired") { offer["created_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 2000; offer["expires_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - 1000; }
            if (change is "expired" or "unsolicited") await Fails(f.Native.Connection.HandlePlainAsync(offer));
            else
            {
                await f.Native.Connection.HandlePlainAsync(offer);
                if (change == "duplicate") await Fails(f.Native.Connection.HandlePlainAsync(offer));
                else
                {
                    var result = Reply(request!, run.Lease.RunId, "snapshot_ready", false); result["body"]!["manifest_sha256"] = manifest.Fingerprint;
                    await Fails(f.Native.Connection.HandlePlainAsync(result));
                }
            }
            if (pending is not null) await Fails(pending);
            TestAssert.That(run.OfferedManifest is null && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 && !Directory.EnumerateFileSystemEntries(f.Root).Any(),
                "Invalid early source offer acquired bytes/history/acceptance: " + change);
        }
    }
}
