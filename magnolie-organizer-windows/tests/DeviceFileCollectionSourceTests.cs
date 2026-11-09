using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileCollectionSourceTests
{
    private const string Book = "{\"syncEpoch\":\"collection-source-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    private static async Task<DeviceFileReceiveJobTests.Fixture> Fixture()
    {
        var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sourceSend: false, sharedMedia: true);
        try
        {
            void Set(string field, JsonNode value) => f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, field,
                value, f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, field));
            Set("enabled", JsonValue.Create(true)!); Set("direction", JsonValue.Create("pc_to_phone")!);
            Set("collection_mode", JsonValue.Create("entire_collection")!); Set("photos_only", JsonValue.Create(false)!);
            await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            await DeviceFileMappedSourceTests.AllowSending(f, pcReceive: false, phoneRead: false);
            TestAssert.That(f.Current() is null && f.Owner.Binding(new string('f', 64), true) is not null,
                "Independent PC source fixture still depends on PC RECEIVE or phone READ.");
            return f;
        }
        catch { f.Dispose(); throw; }
    }

    private static NativeMediaCollectionRoot Select(DeviceFileReceiveJobTests.Fixture f, byte[] bytes)
    {
        var path = Path.Combine(f.Native.Paths.Root, "selected-pc-source"); Directory.CreateDirectory(path);
        File.WriteAllBytes(Path.Combine(path, "new-pc.png"), bytes);
        using var root = DeviceFileNativeDirectory.OpenExisting(path);
        return f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
    }

    private static DeviceFileNativeDirectory.CollectionMember Member(NativeMediaCollectionRoot selection)
    {
        using var root = selection.OpenNative(); return root.InventoryCollection(() => { }, CancellationToken.None).Members.Single();
    }

    private static JsonObject Record(DeviceFileReceiveJobTests.Fixture f, string job)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; read.Parameters.AddWithValue("$job", job);
        var clear = f.Native.Store.Open("native_media_source_job", f.Native.Peer.Id + "/" + job, (byte[])read.ExecuteScalar()!);
        try { return JsonNode.Parse(clear)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(clear); }
    }

    private static async Task SendToEnd(DeviceFileReceiveJobTests.Fixture f, TelefonStore.NativePreparedMediaSource cache, byte[] expected, string? expectedPrevious = null)
    {
        DeviceFileConnectionRunsTests.Clear(f); using var stop = new CancellationTokenSource();
        var send = f.Native.Connection.SendNativeMappedMediaSourceToSourceEndAsync(cache, stop.Token);
        try
        {
            var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
            var media = MediaOfferEnvelope.Validate(offer, cache.Manifest.SenderId, cache.Manifest.ReceiverId, Now());
            TestAssert.That(media.Originals.Count == 0 && media.MimeTypes[cache.Manifest.Files[0].Id]!.GetValue<string>() == "image/png",
                "Independent PC source invented a phone reference or lost actual byte-derived MIME.");
            var origin = media.PcOrigins[cache.Manifest.Files[0].Id]!.AsObject();
            TestAssert.That(offer["body"]!["format"]!.GetValue<int>() == 2 && media.PcOrigins.Count == 1 &&
                origin["origin_sha256"]!.GetValue<string>() == DeviceFileControl.Digest("magnolie-pc-media-origin-v1\0", Record(f, cache.JobId)["local_origin"]!) &&
                origin["previous_publication_sha256"]?.GetValue<string>() == expectedPrevious,
                "Actual wire did not bind opaque PC origin and exact previously completed publication without leaking native identity/path.");
            var acceptance = DeviceFileSourceSendTests.Accept(f, cache, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
            var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Now()); var chunks = (expected.Length + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes;
            for (var index = 0; index < chunks; index++)
            {
                var request = DeviceFileSourceSendTests.Chunk(cache, acceptance, offer, index); await f.Native.Connection.HandlePlainAsync(request);
                var response = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileChunkEnvelope.ResultKind, index);
                var bytes = DeviceFileChunkEnvelope.ParseResponse(response, request, cache.Manifest, accepted, Now());
                try { TestAssert.That(bytes.SequenceEqual(expected.Skip(index * DeviceFileManifest.ChunkBytes).Take(DeviceFileManifest.ChunkBytes)), "Actual encrypted output lost independent original PC bytes."); }
                finally { CryptographicOperations.ZeroMemory(bytes); }
            }
            await f.Native.Connection.HandlePlainAsync(DeviceFileSourceSendTests.Saved(cache, acceptance, offer));
            TestAssert.That(!send.IsCompleted && DeviceFileSourceSendTests.Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "peer_saved",
                "Peer Saved alone became own source-END.");
            TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded, "Peer Saved manufactured independent source END.");
            var file = cache.Manifest.Files.Single();
            var context = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(),
                ["manifest_sha256"] = cache.Manifest.Fingerprint, ["transfer_id"] = cache.Manifest.TransferId, ["source_id"] = cache.Manifest.SourceId,
                ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["media_type"] = "images", ["mime_type"] = "image/png",
                ["publication_sha256"] = new string('b', 64), ["row_sha256"] = new string('d', 64),
                ["permission_epoch"] = acceptance["body"]!["permission_epoch"]!.DeepClone(), ["readback_nonce"] = new string('e', 64) };
            var binding = f.Owner.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), true)!;
            var readback = DeviceFileSourceSendTests.Message(DevicePublishedReadbackEnvelope.Kind, DevicePublishedReadbackEnvelope.EncodeBody(context, binding), offer);
            await f.Native.Connection.HandlePlainAsync(readback); await send; cache.RequireIoEnded();
            TestAssert.That(DeviceFileSourceSendTests.Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "source_ended" &&
                DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]!.GetValue<string>() != DeviceFileSources.RequestKind),
                "Independent source did not reach actual native END or requested phone source READ/discovery.");
        }
        finally { stop.Cancel(); try { await send; } catch { } }
    }

    internal static async Task WindowsActualSourceAsync()
    {
        using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); var original = Member(selection);
        TelefonStore.NativeCollectionMediaSource Open() => f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using (var source = Open())
        using (var cache = source.Freeze())
        {
            var record = Record(f, cache.JobId);
            TestAssert.That(record["format"]!.GetValue<int>() == 3 && record["originals"]!.AsObject().Count == 0 &&
                record["local_origin"]!["root_id"]!.GetValue<string>() == selection.Id && !record["provenance"]!.AsObject().ContainsKey("mapping_job") &&
                !f.Native.Store.HasNativeMediaSourceReference(f.Native.Peer.Id, new JsonObject { ["not"] = "a phone reference" }),
                "Protected PC-origin cache invented/claimed a phone mapping or used the legacy cache schema.");
            await SendToEnd(f, cache, data);
        }
        var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        using (var unchanged = Open()) TestAssert.Throws<InvalidDataException>(() => unchanged.FreezeCompletedSuccessor(), "Already-completed unchanged PC payload was resent.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == before, "Unchanged source appended or discarded history.");
        data = DeviceFileSourceSendTests.PaddedPng(1, 256); File.WriteAllBytes(Path.Combine(selection.NativePath, "new-pc.png"), data);
        var changed = Member(selection);
        TestAssert.That(changed.Identity == original.Identity && changed.CreationFileTime == original.CreationFileTime, "Version fixture accidentally replaced its source generation.");
        // Older internal local caches could have ended with v1 (no stable wire
        // association). Preserve them, but never infer a receiver association.
        using (var db = f.Native.Store.OpenDatabase())
        {
            db.Open(); using var query = db.CreateCommand(); query.CommandText = "SELECT value FROM native_media_source_exchanges WHERE job_id=$job";
            query.Parameters.AddWithValue("$job", before.JobId); var originalExchange = (byte[])query.ExecuteScalar()!;
            var old = DeviceFileSourceSendTests.Exchange(f, before.JobId); old["offer"]!["body"]!["format"] = 1; old["offer"]!["body"]!.AsObject().Remove("pc_origins");
            var bytes = TelefonCrypto.Canonical(old); byte[] cipher;
            try { cipher = f.Native.Store.Seal("native_media_source_exchange", f.Native.Peer.Id + "/" + before.JobId, bytes); }
            finally { CryptographicOperations.ZeroMemory(bytes); }
            using var update = db.CreateCommand(); update.CommandText = "UPDATE native_media_source_exchanges SET value=$value WHERE job_id=$job";
            update.Parameters.AddWithValue("$job", before.JobId); var value = update.Parameters.Add("$value", Microsoft.Data.Sqlite.SqliteType.Blob); value.Value = cipher; update.ExecuteNonQuery();
            try
            {
                using var unbound = Open(); TestAssert.Throws<InvalidDataException>(() => unbound.FreezeCompletedSuccessor(), "Old v1 local predecessor acquired an inferred stable phone publication association.");
                TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == before, "Unbound predecessor HOLD changed local source history.");
            }
            finally { value.Value = originalExchange; update.ExecuteNonQuery(); }
        }
        using (var source = Open())
        using (var cache = source.FreezeCompletedSuccessor())
        {
            var record = Record(f, cache.JobId);
            TestAssert.That(record["format"]!.GetValue<int>() == 4 && record["previous"]!["job_id"]!.GetValue<string>() == before.JobId,
                "Changed independent PC payload lost its latest completed source lineage.");
            await SendToEnd(f, cache, data, new string('b', 64));
        }
        var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        File.SetCreationTimeUtc(Path.Combine(selection.NativePath, "new-pc.png"), DateTime.FromFileTimeUtc((long)original.CreationFileTime).AddSeconds(-5));
        using (var changedGeneration = Open())
            TestAssert.Throws<InvalidDataException>(() => changedGeneration.FreezeCompletedSuccessor(), "Known native file ID with a different creation witness silently inherited/replaced source history.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
            File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data),
            "Independent source versions altered incoming history, original bytes or existing source records.");
    }

    internal static async Task WindowsOwnerGuardsAsync()
    {
        foreach (var fault in new[] { "consent", "book", "intent" })
        {
            using var f = await Fixture(); var data = DeviceFileSourceSendTests.PaddedPng(length: 256); var selection = Select(f, data);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
            using var source = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
            using var cache = source.Freeze(); var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
            var frames = f.Native.Stream.ToArray();
            if (fault == "consent")
            {
                var before = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                var off = f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, before.Version, false, false);
                f.Native.Store.ChangeNativeMediaSendConsent(f.Native.Peer.Id, off.Version, true, false);
            }
            if (fault == "book")
            {
                var changed = JsonNode.Parse(Book)!.AsObject(); changed["notizen"] = new JsonArray(new JsonObject { ["id"] = "new", ["titel"] = "Changed" });
                using var message = System.Text.Json.JsonDocument.Parse(new JsonObject { ["id"] = 1, ["text"] = changed.ToJsonString() }.ToJsonString());
                await host.SaveAsync(message.RootElement);
                TestAssert.That(host.Responses.Last().Value["ok"]!.GetValue<bool>(), "Actual changed-book fixture save was not accepted.");
            }
            if (fault == "intent")
            {
                var version = f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode");
                f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("phone_inventory")!, version);
                await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            }
            TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Independent PC cache ignored original owner withdrawal: " + fault);
            TestAssert.Throws<InvalidDataException>(() => source.ReadExact(0, 1), "Independent PC source retained rights after withdrawal: " + fault);
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == history &&
                f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 0 &&
                File.ReadAllBytes(Path.Combine(selection.NativePath, "new-pc.png")).SequenceEqual(data) &&
                (fault == "intent" || f.Native.Stream.ToArray().SequenceEqual(frames)) &&
                DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).All(frame => frame["kind"]?.GetValue<string>() is not (MediaOfferEnvelope.Kind or DeviceFileChunkEnvelope.ResultKind or DeviceFileSources.RequestKind)),
                "Owner rejection changed original bytes/cache/history or sent unauthorized data: " + fault);
        }
    }

    internal static async Task WindowsMixedHistoryAndSchemaAsync()
    {
        var data = DeviceFileSourceSendTests.PaddedPng(length: 256);
        using var f = await DeviceFileSourceCacheTests.Fixture(data);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "book"), Book);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved); JsonObject reference;
        using (var mapped = DeviceFileSourceCacheTests.Open(f, book))
        using (var cache = mapped.Freeze())
        {
            reference = mapped.OriginalReference;
            TestAssert.That(Record(f, cache.JobId)["format"]!.GetValue<int>() == 1, "Existing mapped preparation was rewritten to a local-origin schema.");
        }
        var field = f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode");
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("entire_collection")!, field);
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        var selection = Select(f, data);
        using var local = f.Native.Connection.OpenNativeCollectionMediaSource("images", selection.Id, selection.Version, Member(selection), new string('f', 64), book);
        using var prepared = local.Freeze(); var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
        TestAssert.That(before.Length == 2 && f.Native.Store.HasNativeMediaSourceReference(f.Native.Peer.Id, reference),
            "Mixed local/mapped histories lost old records or misclassified an independent PC origin as a phone reference.");
        using (var root = DeviceFileNativeDirectory.OpenExisting(f.Root))
        {
            var mappedRoot = f.Native.Store.AddNativeMediaCollectionRoot(f.Native.Peer.Id, "images", root, () => { });
            var mappedMember = root.InventoryCollection(() => { }, CancellationToken.None).Members.Single(item => item.Name == "first.jpg");
            TestAssert.Throws<InvalidDataException>(() => f.Native.Connection.OpenNativeCollectionMediaSource("images", mappedRoot.Id, mappedRoot.Version,
                mappedMember, new string('f', 64), book), "An existing native phone mapping was relabelled as an independent PC origin.");
        }
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var query = db.CreateCommand();
        query.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; query.Parameters.AddWithValue("$job", prepared.JobId);
        var originalCipher = (byte[])query.ExecuteScalar()!; var original = Record(f, prepared.JobId);
        void Replace(JsonObject body)
        {
            var bytes = TelefonCrypto.Canonical(body); byte[] cipher;
            try { cipher = f.Native.Store.Seal("native_media_source_job", f.Native.Peer.Id + "/" + prepared.JobId, bytes); }
            finally { CryptographicOperations.ZeroMemory(bytes); }
            using var update = db.CreateCommand(); update.CommandText = "UPDATE native_media_source_jobs SET value=$value WHERE job_id=$job";
            update.Parameters.AddWithValue("$value", cipher); update.Parameters.AddWithValue("$job", prepared.JobId); update.ExecuteNonQuery();
        }
        foreach (var mutate in new Action<JsonObject>[] {
            body => body["format"] = 1,
            body => body["local_origin"]!.AsObject().Remove("file_creation_filetime"),
            body => body["local_origin"]!["file_creation_filetime"] = "0000000000000000",
            body => body["local_origin"]!["root_id"] = new string('f', 32),
            body => body["local_origin"]!["root_identity"] = new JsonObject(),
            body => body["local_origin"]!["file_identity"] = "not a native identity",
            body => body["originals"] = new JsonObject { ["fake"] = reference.DeepClone() } })
        {
            var changed = original.DeepClone().AsObject(); mutate(changed); Replace(changed);
            TestAssert.Throws<InvalidDataException>(() => f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id), "Malformed authenticated local-origin source record was adopted or relaxed into the legacy schema.");
        }
        using (var restore = db.CreateCommand())
        {
            restore.CommandText = "UPDATE native_media_source_jobs SET value=$value WHERE job_id=$job";
            restore.Parameters.AddWithValue("$value", originalCipher); restore.Parameters.AddWithValue("$job", prepared.JobId); restore.ExecuteNonQuery();
        }
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(before) &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Count == 1, "Schema rejection discarded/restored source or receive history.");
    }
}
