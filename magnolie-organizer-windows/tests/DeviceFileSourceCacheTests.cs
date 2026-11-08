using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSourceCacheTests
{
    private const string Book = "{\"syncEpoch\":\"source-cache-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static readonly byte[] Bytes = Enumerable.Range(0, 70013).Select(index => (byte)(index % 251)).ToArray();
    private static async Task<DeviceFileReceiveJobTests.Fixture> Fixture()
    {
        var f = await DeviceFileMappedSourceTests.Established();
        try
        {
            await DeviceFileMappedSourceTests.AllowSending(f);
            using var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write);
            edit.SetLength(0); edit.Write(Bytes); return f;
        }
        catch { f.Dispose(); throw; }
    }
    private static TelefonStore.NativeMappedMediaSource Open(DeviceFileReceiveJobTests.Fixture f, NativeMediaBookPermit book)
    {
        var mapping = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        return f.Native.Connection.OpenNativeMappedMediaSource("images", mapping.JobId, mapping.Version, 1.ToString("x32"), new string('f', 64), book);
    }
    private static int ChunkCount(DeviceFileReceiveJobTests.Fixture f)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_source_chunks'";
        if (read.ExecuteScalar() is null) return 0;
        read.CommandText = "SELECT count(*) FROM native_media_source_chunks"; return Convert.ToInt32(read.ExecuteScalar());
    }
    private static byte[] Cipher(DeviceFileReceiveJobTests.Fixture f, string jobId, int number)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_source_chunks WHERE job_id=$job AND number=$number";
        read.Parameters.AddWithValue("$job", jobId); read.Parameters.AddWithValue("$number", number); return (byte[])read.ExecuteScalar()!;
    }
    private static void ReplaceCipher(DeviceFileReceiveJobTests.Fixture f, string jobId, byte[] cipher)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
        write.CommandText = "UPDATE native_media_source_chunks SET value=$value WHERE job_id=$job AND number=0";
        write.Parameters.AddWithValue("$job", jobId); write.Parameters.AddWithValue("$value", cipher); write.ExecuteNonQuery();
    }

    internal static async Task WindowsActualFreezeAsync()
    {
        using var f = await Fixture(); var before = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "cache-book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        using var source = Open(f, book); var output = f.Native.Stream.ToArray();
        using var cache = source.Freeze();
        TestAssert.That(ReferenceEquals(cache, source.Freeze()) && cache.Manifest.Files[0].Sha256 == Convert.ToHexString(SHA256.HashData(Bytes)).ToLowerInvariant() &&
            cache.ReadChunk(0).Concat(cache.ReadChunk(1)).SequenceEqual(Bytes), "Actual source freeze/readback did not preserve current multi-chunk PC bytes.");
        var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        TestAssert.That(history.JobId == cache.JobId && history.Version == cache.Version && history.Phase == "ready" && ChunkCount(f) == 2 &&
            JsonNode.DeepEquals(cache.Originals, source.PreparedOriginalReferences()), "Durable ready cache lost its original source/ref/cipher identity.");
        var cipher = Cipher(f, cache.JobId, 0);
        TestAssert.That(cipher.Length == DeviceFileManifest.ChunkBytes + 28 && !cipher.AsSpan(0, DeviceFileManifest.ChunkBytes).SequenceEqual(Bytes.AsSpan(0, DeviceFileManifest.ChunkBytes)), "Cache was not sealed with the existing native key.");
        using (var duplicate = Open(f, book)) TestAssert.Throws<InvalidDataException>(() => duplicate.Freeze(), "A second source adopted/replaced the original durable preparation.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == history &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == before && f.Native.Stream.ToArray().SequenceEqual(output) &&
            Cipher(f, cache.JobId, 0).SequenceEqual(cipher), "Cache preparation rewrote original history, emitted wire data or repaired an existing record.");
    }

    internal static async Task WindowsCorruptionAndMissingHeadAsync()
    {
        foreach (var missing in new[] { false, true })
        {
            using var f = await Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "cache-book"), Book);
            using var source = Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
            var original = Cipher(f, cache.JobId, 0);
            if (missing)
            {
                using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
                write.CommandText = "DELETE FROM native_media_source_jobs WHERE job_id=$job"; write.Parameters.AddWithValue("$job", cache.JobId); write.ExecuteNonQuery();
            }
            else { var damaged = original.ToArray(); damaged[0] ^= 1; ReplaceCipher(f, cache.JobId, damaged); }
            TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Missing/corrupt cache state returned plaintext.");
            if (!missing) ReplaceCipher(f, cache.JobId, original);
            TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Retired cache became readable after historical ciphertext was restored.");
            TestAssert.Throws<InvalidDataException>(() => source.Freeze(), "Cache lookup fabricated a new live owner after corruption.");
            using (var fresh = Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)))
                TestAssert.Throws<InvalidDataException>(() => fresh.Freeze(), "A fresh source silently replaced a missing original preparation while its encrypted chunks survived.");
            TestAssert.That(ChunkCount(f) == 2 && File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(Bytes), "Cache failure destroyed retained chunks or original PC bytes.");
        }
    }

    internal static async Task WindowsSaveDuringCopyAsync()
    {
        using var f = await Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "cache-book"), Book);
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim(); var watch = false; var blocked = 0;
        NativeBookSaveState? Saved()
        {
            if (Volatile.Read(ref watch) && ChunkCount(f) == 1 && Interlocked.CompareExchange(ref blocked, 1, 0) == 0)
            { entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(10))) throw new TimeoutException("cache copy fixture deadline"); }
            return host.Saved();
        }
        using var source = Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, Saved)); Volatile.Write(ref watch, true);
        var copy = Task.Run(() => TestAssert.Throws<InvalidDataException>(() => source.Freeze(), "Changed original book completed a cache copy."));
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(10)), "Cache did not reach its first actual committed chunk.");
            using var save = JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = Book }.ToJsonString()); await host.SaveAsync(save.RootElement);
        }
        finally { release.Set(); await copy; }
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "planned" && ChunkCount(f) == 1,
            "Interrupted copy was marked ready or discarded instead of retaining the partial original preparation.");
        using var fresh = Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        TestAssert.Throws<InvalidDataException>(() => fresh.Freeze(), "A fresh book silently adopted/replaced the retained partial cache.");
        TestAssert.That(ChunkCount(f) == 1, "Failed cache restart repaired or removed a historical partial chunk.");
    }

    internal static async Task WindowsCancellationDrainsReadAsync()
    {
        using var f = await Fixture(); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "cache-book"), Book);
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim(); var watch = false;
        NativeBookSaveState? Saved()
        {
            if (Volatile.Read(ref watch)) { entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(10))) throw new TimeoutException("cache read fixture deadline"); }
            return host.Saved();
        }
        using var source = Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, Saved)); using var cache = source.Freeze();
        Volatile.Write(ref watch, true);
        var read = Task.Run(() => TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Canceled cache read returned plaintext."));
        Task? close = null;
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(10)), "Cache read did not enter the original native owner guard.");
            close = Task.Run(cache.Dispose); await Task.Delay(50);
            TestAssert.That(!read.IsCompleted && !close.IsCompleted, "Cache cancellation released undrained IO ownership.");
        }
        finally { Volatile.Write(ref watch, false); release.Set(); await read; if (close is not null) await close; }
        TestAssert.That(ChunkCount(f) == 2 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "ready", "Cancellation discarded the durable ready version.");
    }
}
