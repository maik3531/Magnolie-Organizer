using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSourceSendTests
{
    private const string Book = "{\"syncEpoch\":\"source-send-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private static JsonObject Message(string kind, JsonObject body, JsonObject offer) => new()
    {
        ["type"] = "message", ["v"] = 1, ["message_id"] = Guid.NewGuid().ToString("D"), ["kind"] = kind,
        ["created_ms"] = Now(), ["expires_ms"] = offer["expires_ms"]!.DeepClone(), ["body"] = body
    };
    private static JsonObject Accept(DeviceFileReceiveJobTests.Fixture f, TelefonStore.NativePreparedMediaSource cache, JsonObject offer) => Message(DeviceFileAcceptanceEnvelope.Kind,
        new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(), ["transfer_id"] = cache.Manifest.TransferId,
            ["manifest_sha256"] = cache.Manifest.Fingerprint, ["permission_epoch"] = f.Owner.Binding(new string('f', 64), true)!.PermissionEpoch,
            ["destination_token"] = new string('f', 64), ["acceptance_sha256"] = new string('a', 64) }, offer);
    private static JsonObject Chunk(TelefonStore.NativePreparedMediaSource cache, JsonObject acceptance, JsonObject offer, int index)
    {
        var body = acceptance["body"]!.DeepClone().AsObject(); body.Remove("offer_id"); body["file_id"] = cache.Manifest.Files[0].Id; body["chunk_index"] = index;
        return Message(DeviceFileChunkEnvelope.RequestKind, body, offer);
    }
    private static JsonObject Saved(TelefonStore.NativePreparedMediaSource cache, JsonObject acceptance, JsonObject offer)
    {
        var body = acceptance["body"]!.DeepClone().AsObject(); body.Remove("offer_id");
        var file = cache.Manifest.Files[0];
        body["receipts"] = new JsonArray(new JsonObject { ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["receipt_sha256"] = new string('b', 64) });
        return Message(DeviceFileSavedEnvelope.Kind, body, offer);
    }
    private static JsonObject Exchange(DeviceFileReceiveJobTests.Fixture f, string jobId)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_source_exchanges WHERE job_id=$job"; read.Parameters.AddWithValue("$job", jobId);
        var cipher = (byte[])read.ExecuteScalar()!;
        var open = typeof(TelefonStore).GetMethod("Open", BindingFlags.Instance | BindingFlags.NonPublic, null,
            [typeof(string), typeof(string), typeof(byte[])], null)!;
        var plain = (byte[])open.Invoke(f.Native.Store, ["native_media_source_exchange", f.Native.Peer.Id + "/" + jobId, cipher])!;
        try { return JsonNode.Parse(plain)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(plain); }
    }
    private static async Task Failed(Task task)
    {
        TestAssert.That(ReferenceEquals(await Task.WhenAny(task, Task.Delay(15000)), task), "Failed native sender did not actually drain.");
        await DeviceFileConnectionSourcesTests.FailsAsync<Exception>(task, "Rejected native sender reported success.");
    }

    internal static async Task WindowsActualSecureSendAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
        var before = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); DeviceFileConnectionRunsTests.Clear(f);
        using var cancellation = new CancellationTokenSource(); var send = f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, cancellation.Token);
        try
        {
            var offer = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileOfferEnvelope.Kind);
            TestAssert.That(Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "offer_sent", "Offer output was not durably confirmed.");
            var acceptance = Accept(f, cache, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
            var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Now());
            var expected = Enumerable.Range(0, 70013).Select(index => (byte)(index % 251)).ToArray(); var occurrence = 0;
            foreach (var index in new[] { 1, 0 })
            {
                var request = Chunk(cache, acceptance, offer, index); await f.Native.Connection.HandlePlainAsync(request);
                var response = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.ResultKind, occurrence++);
                var bytes = DeviceFileChunkEnvelope.ParseResponse(response, request, cache.Manifest, accepted, Now());
                TestAssert.That(bytes.SequenceEqual(expected.Skip(index * DeviceFileManifest.ChunkBytes).Take(DeviceFileManifest.ChunkBytes)), "Actual encrypted source output did not match cached current PC bytes.");
                CryptographicOperations.ZeroMemory(bytes);
            }
            await f.Native.Connection.HandlePlainAsync(Saved(cache, acceptance, offer));
            TestAssert.That((await send).Members.Single().Sha256 == cache.Manifest.Files[0].Sha256 &&
                Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "peer_saved" &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == before && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "ready",
                "Remote Saved was not correlated or incorrectly became local Saved/END/cache retirement.");
            await Failed(f.Native.Connection.SendNativeMappedMediaSourceAsync(cache));
        }
        finally { cancellation.Cancel(); try { await send; } catch { } }
    }

    internal static async Task WindowsRejectsEarlySavedAndLostAttemptAsync()
    {
        foreach (var missing in new[] { false, true })
        {
            using var f = await DeviceFileSourceCacheTests.Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
            using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
            DeviceFileConnectionRunsTests.Clear(f); using var stop = new CancellationTokenSource(); var send = f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, stop.Token);
            try
            {
                var offer = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileOfferEnvelope.Kind); var acceptance = Accept(f, cache, offer);
                await f.Native.Connection.HandlePlainAsync(acceptance); var output = f.Native.Stream.ToArray();
                if (missing)
                {
                    using var db = f.Native.Store.OpenDatabase(); db.Open(); using var remove = db.CreateCommand();
                    remove.CommandText = "DELETE FROM native_media_source_exchanges WHERE job_id=$job"; remove.Parameters.AddWithValue("$job", cache.JobId); remove.ExecuteNonQuery();
                }
                await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(
                    missing ? Chunk(cache, acceptance, offer, 0) : Saved(cache, acceptance, offer)), "Missing attempt or unsent chunks produced successful output.");
                await Failed(send);
                TestAssert.That(f.Native.Stream.ToArray().SequenceEqual(output), "Rejected input sent data before its native output prerequisites.");
                await Failed(f.Native.Connection.SendNativeMappedMediaSourceAsync(cache));
                TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "ready", "Uncertain wire attempt erased the original cache.");
            }
            finally { stop.Cancel(); try { await send; } catch { } }
        }
    }

    internal static async Task WindowsOfferDrainAndCancellationAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
        DeviceFileConnectionRunsTests.Clear(f); using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var cancellation = new CancellationTokenSource(); var writes = 0;
        f.Native.Stream.BeforeWrite = () => { if (Interlocked.Increment(ref writes) == 2) { entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(10))) throw new TimeoutException("native source output fixture deadline"); } };
        var send = Task.Run(() => f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, cancellation.Token));
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(10)), "Offer never entered actual encrypted payload output.");
            TestAssert.That(Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "offer_planned", "Unfinished secure output became offer_sent.");
            cancellation.Cancel(); await Task.Delay(50);
            TestAssert.That(!send.IsCompleted, "Canceled sender released ownership before actual output drained.");
        }
        finally { f.Native.Stream.BeforeWrite = null; release.Set(); await Failed(send); }
        TestAssert.That(Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "offer_planned" && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "ready",
            "Interrupted output fabricated successful offer output or deleted its cache.");
    }

    internal static async Task WindowsEarlyAcceptanceWaitsForOutputAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
        DeviceFileConnectionRunsTests.Clear(f); using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var cancellation = new CancellationTokenSource(); var writes = 0; Task? incoming = null;
        f.Native.Stream.BeforeWrite = () => { if (Interlocked.Increment(ref writes) == 2) { entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(10))) throw new TimeoutException("native early-response fixture deadline"); } };
        var send = Task.Run(() => f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, cancellation.Token));
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(10)), "Offer did not enter actual output.");
            var run = (TelefonConnection.NativeMediaSendRun)typeof(TelefonConnection).GetField("nativeMediaSend", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(f.Native.Connection)!;
            incoming = f.Native.Connection.HandlePlainAsync(Accept(f, cache, run.Offer)); await Task.Delay(50);
            var planned = Exchange(f, cache.JobId);
            TestAssert.That(!incoming.IsCompleted && planned["phase"]!.GetValue<string>() == "offer_planned" && planned["acceptance"] is null,
                "An early peer acceptance converted unfinished encrypted output into successful offer/acceptance.");
            f.Native.Stream.BeforeWrite = null; release.Set(); await incoming;
            TestAssert.That(Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "accepted", "Actual output drain did not release the exact waiting acceptance.");
        }
        finally
        {
            f.Native.Stream.BeforeWrite = null; release.Set(); cancellation.Cancel();
            if (incoming is not null) try { await incoming; } catch { }
            await Failed(send);
        }
    }
}
