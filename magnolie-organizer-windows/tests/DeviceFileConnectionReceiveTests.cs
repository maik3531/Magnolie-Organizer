using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionReceiveTests
{
    internal static async Task<TelefonConnection.NativeMediaSourceRun> Ready(DeviceFileReceiveJobTests.Fixture f, DeviceFileManifest manifest, TelefonConnection.NativeMediaSourceRun? existing = null, string mediaType = "images")
    {
        var run = existing ?? await DeviceFileConnectionRunsTests.OfferReady(f, manifest, mediaType);
        var pending = f.Native.Connection.OfferNativeMediaRunAsync(run); var request = DeviceFileConnectionRunsTests.Request(f);
        var offer = DeviceFileOfferEnvelope.Create(manifest, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()); offer["expires_ms"] = request["expires_ms"]!.DeepClone();
        await f.Native.Connection.HandlePlainAsync(offer);
        var result = DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "snapshot_ready", false);
        result["body"]!["offer_id"] = offer["message_id"]!.DeepClone(); result["body"]!["manifest_sha256"] = manifest.Fingerprint;
        await f.Native.Connection.HandlePlainAsync(result); await pending;
        DeviceFileConnectionRunsTests.Clear(f); return run;
    }
    internal static async Task<JsonObject> Outbound(DeviceFileReceiveJobTests.Fixture f, string kind, int occurrence = 0)
    {
        var deadline = Environment.TickCount64 + 10000;
        while (Environment.TickCount64 < deadline)
        {
            var bytes = f.Native.Stream.ToArray(); var end = 0;
            while (bytes.Length - end >= 4)
            {
                var length = System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(end, 4));
                if (length < 0) throw new InvalidDataException("Negative native frame length.");
                if (length > bytes.Length - end - 4) break; // Test stream may currently hold only the next length prefix.
                end += 4 + length;
            }
            var frames = DeviceFileConnectionTransportTests.OpenFrames(bytes[..end]);
            var matching = frames.Where(frame => frame["kind"]!.GetValue<string>() == kind).ToArray();
            if (matching.Length > occurrence) return matching[occurrence];
            await Task.Delay(5);
        }
        throw new TimeoutException("Missing actual native frame: " + kind);
    }
    internal static JsonObject Chunk(JsonObject request, byte[] bytes)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); var body = request["body"]!.DeepClone().AsObject();
        body["request_id"] = request["message_id"]!.DeepClone(); body["data_base64"] = Convert.ToBase64String(bytes);
        body["data_sha256"] = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        return new() { ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = DeviceFileChunkEnvelope.ResultKind,
            ["created_ms"] = now, ["expires_ms"] = request["expires_ms"]!.DeepClone(), ["body"] = body };
    }
    private static JsonObject Head(DeviceFileReceiveJobTests.Fixture f)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT job_id,value FROM native_media_receive_jobs WHERE peer_id=$peer"; read.Parameters.AddWithValue("$peer", f.Native.Peer.Id);
        using var rows = read.ExecuteReader(); TestAssert.That(rows.Read(), "No actual protected native job."); var id = rows.GetString(0);
        var plain = f.Native.Store.Open("native_media_receive_job", f.Native.Peer.Id + "/" + id, (byte[])rows[1]);
        try { return JsonNode.Parse(plain)!["record"]!.DeepClone().AsObject(); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }
    private static async Task Feed(DeviceFileReceiveJobTests.Fixture f, DeviceFileManifest manifest, byte[][] data)
    {
        var number = 0;
        foreach (var (file, content) in manifest.Files.Zip(data))
            for (var index = 0; (long)index * DeviceFileManifest.ChunkBytes < file.Size; index++)
            {
                var request = await Outbound(f, DeviceFileChunkEnvelope.RequestKind, number++);
                var parsed = DeviceFileChunkEnvelope.ParseRequest(request, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                TestAssert.That(parsed.FileId == file.Id && parsed.ChunkIndex == index, "Wire worker skipped/reordered original missing chunk.");
                var offset = index * DeviceFileManifest.ChunkBytes; var bytes = content[offset..Math.Min(content.Length, offset + DeviceFileManifest.ChunkBytes)];
                await f.Native.Connection.HandlePlainAsync(Chunk(request, bytes));
            }
    }

    private static async Task<JsonObject> StoppedEndRequest(DeviceFileReceiveJobTests.Fixture f, TelefonConnection.NativeMediaSourceRun run)
    {
        var cancel = await Outbound(f, DeviceFileSources.RequestKind, 0);
        TestAssert.That(cancel["body"]!["operation"]!.GetValue<string>() == (run.Resume is null ? "cancel_run" : "cancel_resume"),
            "Saved path skipped Android's required acknowledged source stop before END.");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(cancel, run.Lease.RunId, "canceled_held", run.Result.BatchEnd));
        TestAssert.That(!Head(f).ContainsKey("source_end"), "Source stop alone was treated as END/cache retirement.");
        var end = await Outbound(f, DeviceFileSources.RequestKind, 1);
        TestAssert.That(end["body"]!["operation"]!.GetValue<string>() == (run.Resume is null ? "end_run" : "end_resume"), "Stopped source path used the wrong END operation.");
        return end;
    }

    internal static async Task WindowsActualReceiveSavedEndAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var data = new[] { Enumerable.Range(0, 70000).Select(index => (byte)(index % 251)).ToArray(), "second actual native file"u8.ToArray() };
        var manifest = f.Manifest(("wire-first.jpg", data[0]), ("wire-second.jpg", data[1])); var run = await Ready(f, manifest);
        var legacy = 0; f.Native.DuringReceive = () => legacy++;
        var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run);
        var acceptance = await Outbound(f, DeviceFileAcceptanceEnvelope.Kind); var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(accepted.ManifestSha256 == manifest.Fingerprint && Head(f).ContainsKey("acceptance") && !Head(f).ContainsKey("saved"),
            "Wire acceptance preceded original durable native admission or fabricated Saved.");
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.EndNativeMediaRunAsync(run), "Source END raced active incoming bytes.");
        await Feed(f, manifest, data);
        var saved = await Outbound(f, DeviceFileSavedEnvelope.Kind);
        var wire = DeviceFileSavedEnvelope.Parse(saved, manifest, accepted, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(wire.Members.Count == 2 && Head(f).ContainsKey("saved") && !Head(f).ContainsKey("source_end"),
            "Saved was not backed by local proof or publication incorrectly retired the original source.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 1, manifest.TotalBytes), "Publication/Saved alone freed native reservation budget.");
        var endRequest = await StoppedEndRequest(f, run);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(endRequest, run.Lease.RunId, "canceled_held"));
        var id = await receiving;
        TestAssert.That(Head(f).ContainsKey("source_end") && f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single().JobId == id &&
            File.ReadAllBytes(Path.Combine(f.Root, "wire-first.jpg")).SequenceEqual(data[0]) && File.ReadAllBytes(Path.Combine(f.Root, "wire-second.jpg")).SequenceEqual(data[1]) && legacy == 0,
            "Actual encrypted chunks/local publication/Saved/END did not retain original bytes/history outside generic inbox.");
        TestAssert.That(f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L), "Actual original Saved END failed to retire only the active budget while retaining history.");
        DeviceFileConnectionRunsTests.Clear(f); var albumEnd = f.Native.Connection.EndNativeMediaAlbumAsync(run); var albumRequest = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(albumRequest, run.Lease.RunId, "canceled_held")); await albumEnd;
    }

    internal static async Task WindowsBadChunkAndPartialHistoryAsync()
    {
        foreach (var change in new[] { "request", "hash", "expiry", "binding" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var data = new[] { "first"u8.ToArray(), "second"u8.ToArray() };
            var manifest = f.Manifest(("first.jpg", data[0]), ("second.jpg", data[1])); var run = await Ready(f, manifest);
            var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run); _ = await Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
            var request = await Outbound(f, DeviceFileChunkEnvelope.RequestKind); var response = Chunk(request, data[0]);
            if (change == "request") response["body"]!["request_id"] = Guid.NewGuid().ToString("D");
            if (change == "hash") response["body"]!["data_sha256"] = new string('a', 64);
            if (change == "expiry") response["expires_ms"] = request["expires_ms"]!.GetValue<long>() + 1;
            if (change == "binding") response["body"]!["destination_token"] = new string('a', 64);
            await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(response), "Invalid actual wire chunk accepted.");
            await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(receiving, "Invalid actual chunk left receive owner running.");
            TestAssert.That(!Head(f).ContainsKey("saved") && !Head(f).ContainsKey("source_end") && !File.Exists(Path.Combine(f.Root, "first.jpg")) &&
                Directory.EnumerateDirectories(f.Root, ".magnolie-receive-*").Count() == 1,
                "Bad chunk fabricated Saved/END or discarded original held stage: " + change);
        }
    }

    internal static async Task WindowsEndAfterReceiveWithdrawalAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var data = new[] { "first"u8.ToArray(), "second"u8.ToArray() };
        var manifest = f.Manifest(("first.jpg", data[0]), ("second.jpg", data[1])); var run = await Ready(f, manifest);
        var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run); _ = await Outbound(f, DeviceFileAcceptanceEnvelope.Kind); await Feed(f, manifest, data);
        _ = await Outbound(f, DeviceFileSavedEnvelope.Kind); var request = await StoppedEndRequest(f, run);
        var before = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, before.Version, false, false, false);
        f.Local = new(new(8, new string('e', 64), false, false), f.Local.Owner, false);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held")); await receiving;
        TestAssert.That(Head(f).ContainsKey("source_end") && f.Current() is null, "Exact Saved END required/revived receive permission.");
    }

    internal static Task WindowsWireStopDrainAndOriginalResumeAsync() => RunStoppedWireResumeAsync(false);
    internal static Task WindowsAlbumWireStopDrainAndOriginalResumeAsync() => RunStoppedWireResumeAsync(true);

    private static async Task RunStoppedWireResumeAsync(bool albumLayout)
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var data = new[] { Enumerable.Range(0, 70000).Select(index => (byte)(index % 251)).ToArray(), "second"u8.ToArray() };
        var manifest = f.Manifest(("resumed-first.jpg", data[0]), ("resumed-second.jpg", data[1]));
        var run = albumLayout ? await DeviceFileAlbumTests.Preview(f, manifest, new string('e', 64), "Kamera") : await Ready(f, manifest);
        var publishedRoot = albumLayout ? Path.Combine(f.Root, new NativeMediaAlbumContext(new string('e', 64), "Kamera").Folder) : f.Root;
        var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run); var firstAcceptance = DeviceFileAcceptanceEnvelope.Parse(await Outbound(f, DeviceFileAcceptanceEnvelope.Kind), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        var first = await Outbound(f, DeviceFileChunkEnvelope.RequestKind);
        await f.Native.Connection.HandlePlainAsync(Chunk(first, data[0][..DeviceFileManifest.ChunkBytes]));
        var late = await Outbound(f, DeviceFileChunkEnvelope.RequestKind, 1);
        var stop = f.Native.Connection.StopNativeMediaReceiveAsync(run);
        await DeviceFileConnectionSourcesTests.FailsAsync<OperationCanceledException>(receiving, "Native stop did not cancel and drain the actual chunk owner.");
        // An in-flight reply is drained only against that exact retired request,
        // without writes/receipts or destroying metadata-only cleanup authority.
        await f.Native.Connection.HandlePlainAsync(Chunk(late, data[0][DeviceFileManifest.ChunkBytes..]));
        var cancel = await Outbound(f, DeviceFileSources.RequestKind, 0);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(cancel, run.Lease.RunId, "canceled_held", false));
        var end = await Outbound(f, DeviceFileSources.RequestKind, 1);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(end, run.Lease.RunId, "canceled_held"));
        var album = await Outbound(f, DeviceFileSources.RequestKind, 2);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(album, run.Lease.RunId, "canceled_held"));
        TestAssert.That(await stop && !Head(f).ContainsKey("saved") && !Head(f).ContainsKey("source_end") &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 1, manifest.TotalBytes), "Aborted source cleanup falsely retired original bytes/budget.");
        var original = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var selected = f.Native.Store.SelectNativeMediaResume(f.Native.Peer.Id, original.JobId, original.Version);
        DeviceFileConnectionRunsTests.Clear(f); var lookupTask = f.Native.Connection.LookupNativeMediaResumeAsync(selected, new string('d', 64));
        var request = DeviceFileConnectionRunsTests.Request(f); await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Resume(request, manifest, Guid.NewGuid().ToString("N"))); var lookup = await lookupTask;
        using var recovered = f.Native.Store.RecoverNativeMediaReceiveJob(lookup.Selection, f.Current);
        DeviceFileConnectionRunsTests.Clear(f); var start = f.Native.Connection.StartNativeMediaResumeAsync(lookup, recovered, run.CatalogId, run.AlbumId, run.DesktopChoice);
        request = DeviceFileConnectionRunsTests.Request(f); var newRunId = Guid.NewGuid().ToString("D");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, newRunId, "snapshot_ready")); var resumed = await start;
        foreach (var after in new[] { 0, 1 })
        {
            DeviceFileConnectionRunsTests.Clear(f); var pages = f.Native.Connection.ReadNativeMediaPageAsync(resumed); request = DeviceFileConnectionRunsTests.Request(f);
            var page = DeviceFileConnectionRunsTests.Media(request, newRunId, after, after == 0); page["body"]!["page"]!["manifest_sha256"] = manifest.Fingerprint;
            await f.Native.Connection.HandlePlainAsync(page); await pages;
        }
        DeviceFileConnectionRunsTests.Clear(f); await Ready(f, manifest, resumed);
        var renewed = f.Native.Connection.ReceiveNativeMediaRunAsync(resumed);
        var accepted = DeviceFileAcceptanceEnvelope.Parse(await Outbound(f, DeviceFileAcceptanceEnvelope.Kind), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        TestAssert.That(accepted.AcceptanceSha256 == firstAcceptance.AcceptanceSha256 && recovered.JobId == original.JobId, "Resume changed original native acceptance/job instead of renewing only wire offer ownership.");
        var next = await Outbound(f, DeviceFileChunkEnvelope.RequestKind, 0);
        TestAssert.That(next["body"]!["chunk_index"]!.GetValue<int>() == 1, "Resumed wire worker redownloaded the verified original prefix.");
        await f.Native.Connection.HandlePlainAsync(Chunk(next, data[0][DeviceFileManifest.ChunkBytes..]));
        next = await Outbound(f, DeviceFileChunkEnvelope.RequestKind, 1); await f.Native.Connection.HandlePlainAsync(Chunk(next, data[1]));
        _ = await Outbound(f, DeviceFileSavedEnvelope.Kind); request = await StoppedEndRequest(f, resumed);
        TestAssert.That(request["body"]!["operation"]!.GetValue<string>() == "end_resume", "Resumed actual data path used ordinary source END.");
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, newRunId, "canceled_held"));
        TestAssert.That(await renewed == original.JobId && File.ReadAllBytes(Path.Combine(publishedRoot, "resumed-first.jpg")).SequenceEqual(data[0]) &&
            f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L), "Original wire resume/Saved/END failed to preserve bytes and retire only original budget.");
    }

    internal static async Task WindowsUncertainSavedOrEndKeepsBudgetAsync()
    {
        foreach (var failure in new[] { "saved_output", "end_reply" })
        {
            using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(); var data = new[] { "first"u8.ToArray(), "second"u8.ToArray() };
            var manifest = f.Manifest(("first.jpg", data[0]), ("second.jpg", data[1])); var run = await Ready(f, manifest);
            var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run); _ = await Outbound(f, DeviceFileAcceptanceEnvelope.Kind);
            if (failure == "saved_output") f.Native.Stream.BeforeWrite = () => { if (Head(f).ContainsKey("saved")) f.Native.Stream.Fail = true; };
            await Feed(f, manifest, data);
            if (failure == "saved_output") await DeviceFileConnectionSourcesTests.FailsAsync<IOException>(receiving, "Failed actual Saved write was treated as confirmed.");
            else
            {
                _ = await Outbound(f, DeviceFileSavedEnvelope.Kind); var request = await StoppedEndRequest(f, run);
                var reply = DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held"); reply["body"]!["run_ended"] = false;
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(reply), "Unconfirmed source END accepted after Saved.");
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(receiving, "Unconfirmed END completed original receive.");
            }
            f.Native.Stream.BeforeWrite = null; f.Native.Stream.Fail = false;
            TestAssert.That(Head(f).ContainsKey("saved") && !Head(f).ContainsKey("source_end") && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 1, manifest.TotalBytes) &&
                File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(data[0]) && File.ReadAllBytes(Path.Combine(f.Root, "second.jpg")).SequenceEqual(data[1]),
                "Uncertain Saved/END discarded published bytes or released original budget: " + failure);
        }
    }

    internal static async Task WindowsSeparateVideoWireReceiveAsync()
    {
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync();
        var videoPath = Path.Combine(f.Native.Paths.Root, "native-videos"); Directory.CreateDirectory(videoPath);
        using (var root = DeviceFileNativeDirectory.OpenExistingForReceive(videoPath)) f.Native.Store.SetNativeMediaDestination(f.Native.Peer.Id, "video", null, root);
        var preferences = f.Native.Store.ReadNativeMediaPreferences(f.Native.Peer.Id); f.Native.Store.SetNativeMediaPreferences(f.Native.Peer.Id, preferences.Version, true, true, false);
        DeviceFileConnectionRunsTests.Clear(f); var configuring = f.Native.Connection.ConfigureNativeMediaSourceAsync(new string('c', 64), "video", true);
        var request = DeviceFileConnectionRunsTests.Request(f);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionCommandsTests.Configuration(request, true)); await configuring;
        var data = new[] { "bounded video bytes one"u8.ToArray(), "bounded video bytes two"u8.ToArray() };
        var manifest = f.Manifest(("first.mp4", data[0]), ("second.mp4", data[1])); var run = await Ready(f, manifest, mediaType: "video");
        var receiving = f.Native.Connection.ReceiveNativeMediaRunAsync(run); _ = await Outbound(f, DeviceFileAcceptanceEnvelope.Kind); await Feed(f, manifest, data);
        _ = await Outbound(f, DeviceFileSavedEnvelope.Kind); request = await StoppedEndRequest(f, run);
        await f.Native.Connection.HandlePlainAsync(DeviceFileConnectionRunsTests.Reply(request, run.Lease.RunId, "canceled_held")); await receiving;
        TestAssert.That(File.ReadAllBytes(Path.Combine(videoPath, "first.mp4")).SequenceEqual(data[0]) && !Directory.EnumerateFileSystemEntries(f.Root).Any() &&
            Head(f)["media"]!["media_type"]!.GetValue<string>() == "video" && f.Native.Store.NativeMediaReceiveBudget(f.Native.Peer.Id) == (1, 0, 0L),
            "Video wire receive fell back to photo destination/scope or failed its exact Saved END.");
    }
}
