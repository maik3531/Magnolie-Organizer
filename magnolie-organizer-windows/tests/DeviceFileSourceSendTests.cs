using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileSourceSendTests
{
    private const string Book = "{\"syncEpoch\":\"source-send-test\",\"einstellungen\":{\"papierkorb\":{\"an\":true,\"tage\":30}}}";
    private static readonly byte[] MediaBytes = PaddedPng();
    private static byte[] PaddedPng(int salt = 0)
    {
        var png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC");
        // Valid private ancillary chunk before IEND: real PNG, still two chunks.
        var result = new byte[70013]; var offset = png.Length - 12; png.AsSpan(0, offset).CopyTo(result);
        var size = result.Length - png.Length - 12;
        System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(result.AsSpan(offset), size);
        "npAD"u8.CopyTo(result.AsSpan(offset + 4));
        for (var index = 0; index < size; index++) result[offset + 8 + index] = (byte)((index + salt) % 251);
        uint crc = 0xffffffff;
        foreach (var value in result.AsSpan(offset + 4, size + 4))
        {
            crc ^= value;
            for (var bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0);
        }
        System.Buffers.Binary.BinaryPrimitives.WriteUInt32BigEndian(result.AsSpan(offset + 8 + size), crc ^ 0xffffffff);
        png.AsSpan(png.Length - 12).CopyTo(result.AsSpan(result.Length - 12)); return result;
    }
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
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
        var before = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single(); DeviceFileConnectionRunsTests.Clear(f);
        using var cancellation = new CancellationTokenSource(); var send = f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, cancellation.Token);
        try
        {
            var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
            var media = MediaOfferEnvelope.Validate(offer, cache.Manifest.SenderId, cache.Manifest.ReceiverId, Now());
            TestAssert.That(media.Manifest.Fingerprint == cache.Manifest.Fingerprint && media.Offer["message_id"]!.GetValue<string>() == offer["message_id"]!.GetValue<string>() &&
                media.MimeTypes[cache.Manifest.Files[0].Id]!.GetValue<string>() == "image/png" && JsonNode.DeepEquals(media.Originals, cache.Originals),
                "Actual sender lost byte-derived MIME, original phone reference or ordinary-offer correlation.");
            TestAssert.That(Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "offer_sent", "Offer output was not durably confirmed.");
            var acceptance = Accept(f, cache, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
            var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Now());
            var expected = MediaBytes; var occurrence = 0;
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

    internal static async Task WindowsUnknownMimeBeforeOutputAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture();
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "unknown-send-book"), Book);
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
        DeviceFileConnectionRunsTests.Clear(f); var before = f.Native.Stream.ToArray();
        var sourceHistory = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        var incoming = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.SendNativeMappedMediaSourceAsync(cache),
            "A .jpg filename with unknown actual content reached media output.");
        TestAssert.That(f.Native.Stream.ToArray().SequenceEqual(before) && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == sourceHistory &&
            f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == incoming && cache.ReadChunk(0).Length == DeviceFileManifest.ChunkBytes,
            "Unknown content emitted an offer, retired its original cache or rewrote received history.");
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_media_source_exchanges'";
        if (read.ExecuteScalar() is not null)
        {
            read.CommandText = "SELECT count(*) FROM native_media_source_exchanges";
            TestAssert.That(Convert.ToInt32(read.ExecuteScalar()) == 0, "Rejected MIME fabricated a send attempt journal.");
        }
    }

    internal static async Task WindowsCorrelatedReadbackAsync(string scenario)
    {
        var successor = scenario.StartsWith("successor-", StringComparison.Ordinal);
        var endSource = successor || scenario.StartsWith("end-", StringComparison.Ordinal);
        foreach (var fault in new[] { successor ? (scenario == "successor-incomplete" ? "cancel" : "none") : endSource ? scenario[4..] : scenario })
        {
            using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "readback-book"), Book);
            using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
            using var cache = source.Freeze(); using var stop = new CancellationTokenSource();
            TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded, "A prepared cache fabricated native source END.");
            DeviceFileConnectionRunsTests.Clear(f);
            var before = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
            var send = endSource ? f.Native.Connection.SendNativeMappedMediaSourceToSourceEndAsync(cache, stop.Token) :
                f.Native.Connection.SendNativeMappedMediaSourceWithReadbackAsync(cache, stop.Token);
            try
            {
                var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
                var acceptance = Accept(f, cache, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
                for (var chunk = 0; chunk < 2; chunk++)
                    await f.Native.Connection.HandlePlainAsync(Chunk(cache, acceptance, offer, chunk));
                var file = cache.Manifest.Files.Single();
                var context = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(),
                    ["manifest_sha256"] = cache.Manifest.Fingerprint, ["transfer_id"] = cache.Manifest.TransferId,
                    ["source_id"] = cache.Manifest.SourceId, ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256,
                    ["media_type"] = "images", ["mime_type"] = fault == "mime" ? "image/jpeg" : "image/png",
                    ["publication_sha256"] = new string(fault == "publication" ? 'c' : 'b', 64), ["row_sha256"] = new string('d', 64),
                    ["permission_epoch"] = acceptance["body"]!["permission_epoch"]!.DeepClone(), ["readback_nonce"] = new string('e', 64) };
                var binding = f.Owner.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), true)!;
                var readback = Message(DevicePublishedReadbackEnvelope.Kind, DevicePublishedReadbackEnvelope.EncodeBody(context, binding), offer);
                if (fault != "early")
                {
                    await f.Native.Connection.HandlePlainAsync(Saved(cache, acceptance, offer));
                    TestAssert.That(!send.IsCompleted && Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == "peer_saved",
                        "Peer Saved alone completed a readback-aware sender.");
                    TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded, "Peer Saved manufactured native source END.");
                }
                if (fault == "cancel") { stop.Cancel(); await Failed(send); }
                else if (fault != "none")
                {
                    await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(f.Native.Connection.HandlePlainAsync(readback),
                        "Readback bypassed native send/Saved/publication/MIME correlation: " + fault);
                    await Failed(send);
                }
                else
                {
                    await f.Native.Connection.HandlePlainAsync(readback); var result = await send;
                    TestAssert.That(!result.Readback.IsSavedReceipt && !result.Readback.GrantsWriteAuthority && !result.Readback.AllowsChunkOutput &&
                        Exchange(f, cache.JobId)["phase"]!.GetValue<string>() == (endSource ? "source_ended" : "peer_readback"),
                        "Correlated peer readback became native completion authority.");
                    if (endSource)
                    {
                        cache.RequireIoEnded();
                        TestAssert.Throws<Exception>(source.Require, "Native Source-END left original source handle usable.");
                        TestAssert.Throws<InvalidDataException>(() => cache.ReadChunk(0), "Native Source-END reopened cached chunk output.");
                        var terminal = Exchange(f, cache.JobId);
                        TestAssert.That(terminal["source_end"]!["readback_sha256"]!.GetValue<string>() == result.Readback.Body["readback_sha256"]!.GetValue<string>(),
                            "Native source end lost its exact correlated readback.");
                    }
                }
                if (!endSource || fault != "none") TestAssert.Throws<InvalidDataException>(cache.RequireIoEnded,
                    "Readback metadata or a failed send manufactured local native source END.");
                TestAssert.That(f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == before &&
                    f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single().Phase == "ready",
                    "Readback or its failure retired source cache/changed receive history.");
                if (scenario == "successor-chain") await VerifySuccessorChainAsync(f, host, cache);
                else if (scenario == "successor-during-copy") await VerifySuccessorMutationAsync(f, host, cache);
                else if (successor) VerifySuccessor(f, host, cache, scenario);
            }
            finally { stop.Cancel(); try { await send; } catch { } }
        }
    }

    private static void VerifySuccessor(DeviceFileReceiveJobTests.Fixture f, PersonalActorNativeSaveHost host,
        TelefonStore.NativePreparedMediaSource previous, string scenario)
    {
        var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        var exchange = Exchange(f, previous.JobId).ToJsonString();
        byte[] OriginalChunk()
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT value FROM native_media_source_chunks WHERE job_id=$job AND number=0";
            read.Parameters.AddWithValue("$job", previous.JobId); return (byte[])read.ExecuteScalar()!;
        }
        var cipher = OriginalChunk();
        if (scenario == "successor-corrupt")
        {
            var corrupt = cipher.ToArray(); corrupt[0] ^= 1;
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var write = db.CreateCommand();
            write.CommandText = "UPDATE native_media_source_chunks SET value=$value WHERE job_id=$job AND number=0";
            write.Parameters.AddWithValue("$value", corrupt); write.Parameters.AddWithValue("$job", previous.JobId); write.ExecuteNonQuery();
        }
        if (scenario != "successor-new")
        {
            using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
            TestAssert.Throws<InvalidDataException>(() => source.FreezeCompletedSuccessor(),
                "Unchanged, incomplete or corrupted predecessor admitted a new source version: " + scenario);
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == history &&
                Exchange(f, previous.JobId).ToJsonString() == exchange, "Rejected successor mutated predecessor history.");
            return;
        }
        var changed = PaddedPng(1);
        using (var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write))
        { edit.SetLength(0); edit.Write(changed); }
        using (var ordinary = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)))
            TestAssert.Throws<InvalidDataException>(() => ordinary.Freeze(), "Ordinary preparation bypassed its original duplicate guard.");
        using var next = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        using var cache = next.FreezeCompletedSuccessor();
        var retained = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id);
        TestAssert.That(retained.Count == 2 && retained.Single(item => item.JobId == previous.JobId) == history &&
            cache.ReadChunk(0).Concat(cache.ReadChunk(1)).SequenceEqual(changed) && OriginalChunk().SequenceEqual(cipher) &&
            Exchange(f, previous.JobId).ToJsonString() == exchange && cache.JobId != previous.JobId,
            "Successor failed to keep original protected cache/history or did not freeze fresh current bytes.");
    }

    private static JsonObject SourceRecord(DeviceFileReceiveJobTests.Fixture f, string jobId)
    {
        using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
        read.CommandText = "SELECT value FROM native_media_source_jobs WHERE job_id=$job"; read.Parameters.AddWithValue("$job", jobId);
        var open = typeof(TelefonStore).GetMethod("Open", BindingFlags.Instance | BindingFlags.NonPublic, null,
            [typeof(string), typeof(string), typeof(byte[])], null)!;
        var clear = (byte[])open.Invoke(f.Native.Store, ["native_media_source_job", f.Native.Peer.Id + "/" + jobId, (byte[])read.ExecuteScalar()!])!;
        try { return JsonNode.Parse(clear)!.AsObject(); } finally { CryptographicOperations.ZeroMemory(clear); }
    }

    internal static async Task WindowsSuccessorBeforeOfferAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "unattempted-book"), Book);
        using var originalSource = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        using var original = originalSource.Freeze();
        var before = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single();
        DeviceFileConnectionRunsTests.Clear(f);
        using var replacement = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        TestAssert.Throws<InvalidDataException>(() => replacement.FreezeCompletedSuccessor(), "A prepared but never sent cache admitted successor preparation.");
        TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single() == before && f.Native.Stream.Length == 0 && original.ReadChunk(0).Length > 0,
            "Rejected successor altered the original unattempted source or emitted output.");
    }

    internal static Task WindowsNativeUiOutgoingPassAsync() => NativeUiOutgoingPassAsync("end");
    internal static Task WindowsNativeUiSendWithdrawalAsync() => NativeUiOutgoingPassAsync("withdraw");
    internal static Task WindowsNativeUiSendCloseAsync() => NativeUiOutgoingPassAsync("close");
    private static async Task NativeUiOutgoingPassAsync(string scenario)
    {
        var initial = new NativeBookOwnerScope(); initial.SetReady(true); initial.RecordSaved("native-send-bootstrap", true, new string('a', 64));
        PersonalActorNativeSaveHost? host = null;
        NativeBookSaveState? Saved() => host is null ? initial.SaveState("native-send-bootstrap", true) : host.Saved();
        using var f = await DeviceFileReceiveJobTests.Fixture.CreateAsync(sharedMedia: true, uiSavedBook: Saved);
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "enabled", JsonValue.Create(true)!,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "enabled"));
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        await DeviceFileReconcileTests.Establish(f);
        var originalSession = f.Owner;
        host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "native-send-ui-book"), Book);
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection);
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "direction", JsonValue.Create("pc_to_phone")!,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "direction"));
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        var receiving = f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id);
        coordinator.ChangeNativeMediaUiReceiveConsent(f.Native.Peer.Id, receiving.Version, false);
        var consent = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id); var answers = 0;
        coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, consent.Version, true, false, () => { answers++; return true; });
        using (var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write))
        { edit.SetLength(0); edit.Write(MediaBytes); }
        DeviceFileConnectionRunsTests.Clear(f);
        var intent = f.Native.Store.ReadNativeMediaSharedSettings(f.Native.Peer.Id, f.Native.Peer.PublicKey)!;
        using var stop = new CancellationTokenSource();
        var pass = coordinator.RunNativeMediaManualOnceAsync(f.Native.Peer.Id, intent, stop.Token);
        try
        {
            var control = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind);
            var packet = DeviceFileControlEnvelope.Validate(control, Now());
            TestAssert.That(packet.Grants.SendFiles && !packet.Grants.ReceiveFiles && ReferenceEquals(f.Owner, originalSession) && answers == 1 &&
                f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0 &&
                !DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Any(frame => frame["kind"]!.GetValue<string>() == MediaOfferEnvelope.Kind),
                "Native SEND substituted the control owner, inherited RECEIVE, skipped the dialog or offered data before bilateral ACK.");
            if (scenario is "withdraw" or "close")
            {
                if (scenario == "withdraw")
                {
                    var currentConsent = f.Native.Store.ReadNativeMediaSendConsent(f.Native.Peer.Id);
                    coordinator.ConfirmNativeMediaUiSendConsent(f.Native.Peer.Id, currentConsent.Version, false, false,
                        () => throw new Exception("Withdrawal must not require native positive confirmation."));
                    TestAssert.That(f.Owner.Binding(new string('0', 64), senderIsLocal: true) is null, "SEND-only UI owner ignored withdrawal.");
                    TestAssert.That(await f.Native.Connection.SendNativeFileControlsAsync(), "Withdrawal did not emit its actual control update.");
                    var withdrawn = DeviceFileControlEnvelope.Validate(await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind, 1), Now());
                    TestAssert.That(!withdrawn.Grants.SendFiles && !withdrawn.Grants.ReceiveFiles && withdrawn.Grants.Revision > packet.Grants.Revision &&
                        withdrawn.SessionEpoch == packet.SessionEpoch, "Withdrawal substituted the session or changed bits without a newer revision.");
                }
                else f.Native.Connection.Dispose();
                try { await pass.WaitAsync(TimeSpan.FromSeconds(5)); throw new Exception("Native outgoing preparation survived withdrawal/close."); }
                catch (Exception error) when (error is OperationCanceledException or InvalidDataException) { }
                TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0 && File.ReadAllBytes(Path.Combine(f.Root, "first.jpg")).SequenceEqual(MediaBytes),
                    "Aborted native SEND preparation reserved a cache or changed source bytes.");
                return;
            }
            f.Phone.ObserveRemote(packet, f.RemotePeer);
            f.RemoteLocal = new(new(f.RemoteLocal.Grants.Revision + 1, new string('6', 64), sendFiles: false, receiveFiles: true), f.RemoteLocal.Owner, true);
            var response = f.Phone.Packet(); f.Phone.MarkSent(response);
            await f.Native.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(response, Now()));
            var echo = await DeviceFileConnectionReceiveTests.Outbound(f, DeviceFileControl.Kind, 1);
            f.Phone.ObserveRemote(DeviceFileControlEnvelope.Validate(echo, Now()), f.RemotePeer);
            var manifest = await DriveMappedExportAsync(f);
            TestAssert.That(await pass == "content_pass" && Exchange(f, manifest.SourceId)["phase"]!.GetValue<string>() == "source_ended" &&
                !f.Native.Store.ReadNativeMediaReceiveConsent(f.Native.Peer.Id).Granted && ReferenceEquals(f.Owner, originalSession),
                "The actual normal native-UI source path failed without RECEIVE or replaced the established control session.");
            TestAssert.That(!DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Any(frame => frame["kind"]!.GetValue<string>() == DeviceFileSources.RequestKind),
                "Native PC-only SEND discovered/read/imported phone sources.");
        }
        finally { stop.Cancel(); try { await pass; } catch { } }
    }

    internal static Task WindowsMappedOutgoingPassAsync() => MappedOutgoingPassAsync(automatic: false);
    internal static Task WindowsMappedAutomaticOutgoingPassAsync() => MappedOutgoingPassAsync(automatic: true);
    private static async Task MappedOutgoingPassAsync(bool automatic)
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "mapped-pass-book"), Book);
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "direction", JsonValue.Create("pc_to_phone")!,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "direction"));
        if (automatic) f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "auto_mode", JsonValue.Create("wifi")!,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "auto_mode"));
        await DeviceFileSharedTransportTests.MatchAsync(f.Native);
        using var coordinator = new TelefonCoordinator(f.Native.Paths, (_, _) => Task.CompletedTask, dataStore: f.Native.Store, localOnly: true);
        coordinator.NativeProducerBook = host.Snapshot; coordinator.NativeSavedBook = host.Saved;
        var online = (Dictionary<string, TelefonConnection>)typeof(TelefonCoordinator).GetField("online", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
        online.Add(f.Native.Peer.Id, f.Native.Connection);
        var intent = f.Native.Store.ReadNativeMediaSharedSettings(f.Native.Peer.Id, f.Native.Peer.PublicKey)!;
        var before = f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single();
        using var stop = new CancellationTokenSource(); Task<string>? pass = null;
        async Task<string> Run()
        {
            if (!automatic) return await coordinator.RunNativeMediaManualOnceAsync(f.Native.Peer.Id, intent, stop.Token);
            await coordinator.RunNativeMediaAutomaticOnceAsync(f.Native.Peer.Id, stop.Token);
            var states = (System.Collections.IDictionary)typeof(TelefonCoordinator).GetField("nativeAutomaticMedia", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(coordinator)!;
            var state = states[f.Native.Peer.Id]!;
            return (string)state.GetType().GetField("Phase", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(state)!;
        }
        try
        {
            for (var version = 0; version < (automatic ? 1 : 2); version++)
            {
                if (version != 0)
                {
                    using var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write);
                    edit.SetLength(0); edit.Write(PaddedPng(version));
                }
                DeviceFileConnectionRunsTests.Clear(f); pass = Run();
                var manifest = await DriveMappedExportAsync(f);
                TestAssert.That(await pass == "content_pass" && Exchange(f, manifest.SourceId)["phase"]!.GetValue<string>() == "source_ended" &&
                    f.Native.Store.NativeMediaReceiveHistory(f.Native.Peer.Id).Single() == before,
                    "The actual mapped pass did not finish source END or rewrote its receive baseline.");
                TestAssert.That(!DeviceFileConnectionTransportTests.OpenFrames(f.Native.Stream.ToArray()).Any(frame => frame["kind"]?.GetValue<string>() == DeviceFileSources.RequestKind),
                    "PC-only direction started phone discovery/READ/import.");
                var history = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).ToArray();
                DeviceFileConnectionRunsTests.Clear(f); pass = Run();
                TestAssert.That(await pass == "content_pass" && f.Native.Stream.Length == 0 &&
                    f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).SequenceEqual(history),
                    "Unchanged latest source was retransmitted, adopted or prepared twice.");
            }
            TestAssert.That(f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == (automatic ? 1 : 2), "The normal mapped pass discarded previous content versions.");
        }
        finally { stop.Cancel(); if (pass is not null) try { await pass; } catch { } }
    }

    private static async Task<DeviceFileManifest> DriveMappedExportAsync(DeviceFileReceiveJobTests.Fixture f)
    {
        var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
        var identity = f.Native.Store.LoadOrCreateIdentity(); DeviceFileManifest manifest;
        try { manifest = MediaOfferEnvelope.Validate(offer, identity.Id, f.Native.Peer.Id, Now()).Manifest; }
        finally { CryptographicOperations.ZeroMemory(identity.PrivateKey); }
        return await DriveMappedManifestAsync(f, offer, manifest);
    }

    private static async Task<DeviceFileManifest> DriveMappedManifestAsync(DeviceFileReceiveJobTests.Fixture f, JsonObject offer, DeviceFileManifest manifest)
    {
        var file = manifest.Files.Single(); var binding = f.Owner.Binding(new string('f', 64), true)!;
        var acceptedBody = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(), ["transfer_id"] = manifest.TransferId,
            ["manifest_sha256"] = manifest.Fingerprint, ["permission_epoch"] = binding.PermissionEpoch, ["destination_token"] = binding.DestinationToken,
            ["acceptance_sha256"] = new string('a', 64) };
        await f.Native.Connection.HandlePlainAsync(Message(DeviceFileAcceptanceEnvelope.Kind, acceptedBody, offer));
        var chunk = acceptedBody.DeepClone().AsObject(); chunk.Remove("offer_id"); chunk["file_id"] = file.Id;
        for (var index = 0; index < (file.Size + DeviceFileManifest.ChunkBytes - 1) / DeviceFileManifest.ChunkBytes; index++)
        { var request = chunk.DeepClone().AsObject(); request["chunk_index"] = index; await f.Native.Connection.HandlePlainAsync(Message(DeviceFileChunkEnvelope.RequestKind, request, offer)); }
        var saved = acceptedBody.DeepClone().AsObject(); saved.Remove("offer_id");
        saved["receipts"] = new JsonArray(new JsonObject { ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["receipt_sha256"] = new string('b', 64) });
        await f.Native.Connection.HandlePlainAsync(Message(DeviceFileSavedEnvelope.Kind, saved, offer));
        var context = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(), ["manifest_sha256"] = manifest.Fingerprint,
            ["transfer_id"] = manifest.TransferId, ["source_id"] = manifest.SourceId, ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256,
            ["media_type"] = "images", ["mime_type"] = "image/png", ["publication_sha256"] = new string('b', 64), ["row_sha256"] = new string('d', 64),
            ["permission_epoch"] = binding.PermissionEpoch, ["readback_nonce"] = new string('e', 64) };
        var readbackBinding = f.Owner.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), true)!;
        await f.Native.Connection.HandlePlainAsync(Message(DevicePublishedReadbackEnvelope.Kind, DevicePublishedReadbackEnvelope.EncodeBody(context, readbackBinding), offer));
        return manifest;
    }

    internal static async Task WindowsMappedOutgoingRejectsScopeAndUnknownBytesAsync()
    {
        foreach (var importOnly in new[] { false, true })
        {
            using var f = await DeviceFileSourceCacheTests.Fixture(importOnly ? MediaBytes : null);
            var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "mapped-rejection-book"), Book);
            if (importOnly)
            {
                f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode", JsonValue.Create("import_only")!,
                    f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "collection_mode"));
                await DeviceFileSharedTransportTests.MatchAsync(f.Native);
            }
            DeviceFileConnectionRunsTests.Clear(f);
            var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
            await DeviceFileConnectionSourcesTests.FailsAsync<InvalidDataException>(
                f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, book.Require, CancellationToken.None),
                "Import-only or unknown actual bytes entered mapped source output.");
            TestAssert.That(f.Native.Stream.Length == 0 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
                "Rejected mapped pass emitted PC data or reserved an unusable source cache.");
        }
    }

    internal static async Task WindowsMappedPhotoFilterBeforePreparationAsync()
    {
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes);
        var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "mapped-photo-filter-book"), Book);
        f.Native.Store.ChangeNativeMediaSharedSetting(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only", JsonValue.Create(true)!,
            f.Native.Store.NativeMediaSharedFieldVersion(f.Native.Peer.Id, f.Native.Peer.PublicKey, "photos_only"));
        await DeviceFileSharedTransportTests.MatchAsync(f.Native); DeviceFileConnectionRunsTests.Clear(f);
        var book = NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved);
        var pass = await f.Native.Connection.SynchronizeNativeMappedMediaChangesAsync("images", book, book.Require, CancellationToken.None);
        TestAssert.That(pass.Sent == 0 && f.Native.Stream.Length == 0 && f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 0,
            "Photos-only used filename/MIME instead of actual camera metadata or reserved a filtered cache.");
    }

    private static async Task VerifySuccessorMutationAsync(DeviceFileReceiveJobTests.Fixture f, PersonalActorNativeSaveHost host,
        TelefonStore.NativePreparedMediaSource original)
    {
        using (var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write))
        { edit.SetLength(0); edit.Write(PaddedPng(1)); }
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim(); var watch = false; var blocked = 0;
        NativeBookSaveState? Saved()
        {
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var read = db.CreateCommand();
            read.CommandText = "SELECT count(*) FROM native_media_source_chunks WHERE job_id<>$job";
            read.Parameters.AddWithValue("$job", original.JobId);
            if (Volatile.Read(ref watch) && Convert.ToInt32(read.ExecuteScalar()) == 1 && Interlocked.CompareExchange(ref blocked, 1, 0) == 0)
            { entered.Set(); if (!release.Wait(TimeSpan.FromSeconds(10))) throw new TimeoutException("successor mutation fixture deadline"); }
            return host.Saved();
        }
        using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, Saved));
        Volatile.Write(ref watch, true);
        var copying = Task.Run(() => TestAssert.Throws<InvalidDataException>(() => source.FreezeCompletedSuccessor(), "Changed predecessor completed a successor cache."));
        try
        {
            TestAssert.That(entered.Wait(TimeSpan.FromSeconds(10)), "Successor did not reach the first committed native chunk.");
            using var db = f.Native.Store.OpenDatabase(); db.Open(); using var change = db.CreateCommand();
            change.CommandText = "SELECT value FROM native_media_source_chunks WHERE job_id=$job AND number=0";
            change.Parameters.AddWithValue("$job", original.JobId); var cipher = (byte[])change.ExecuteScalar()!; cipher[0] ^= 1;
            change.CommandText = "UPDATE native_media_source_chunks SET value=$value WHERE job_id=$job AND number=0";
            change.Parameters.AddWithValue("$value", cipher); change.ExecuteNonQuery();
        }
        finally { Volatile.Write(ref watch, false); release.Set(); await copying; }
        var records = f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id);
        TestAssert.That(records.Count == 2 && records.Single(item => item.JobId != original.JobId).Phase == "planned" &&
            records.Single(item => item.JobId == original.JobId).Phase == "ready",
            "Mutation was concealed, partial successor erased or predecessor metadata replaced.");
    }

    private static async Task VerifySuccessorChainAsync(DeviceFileReceiveJobTests.Fixture f, PersonalActorNativeSaveHost host,
        TelefonStore.NativePreparedMediaSource original)
    {
        void Edit(byte[] bytes)
        {
            using var edit = new FileStream(Path.Combine(f.Root, "first.jpg"), FileMode.Open, FileAccess.Write);
            edit.SetLength(0); edit.Write(bytes);
        }
        Edit(PaddedPng(1));
        using var secondSource = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        using var second = secondSource.FreezeCompletedSuccessor(); var secondVersion = second.Version;
        var link = SourceRecord(f, second.JobId)["previous"]!.AsObject();
        TestAssert.That(link["job_id"]!.GetValue<string>() == original.JobId &&
            link["job_version"]!.GetValue<string>() == f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Single(item => item.JobId == original.JobId).Version,
            "Successor did not bind the exact original protected predecessor.");
        DeviceFileConnectionRunsTests.Clear(f);
        using var stop = new CancellationTokenSource();
        var sending = f.Native.Connection.SendNativeMappedMediaSourceToSourceEndAsync(second, stop.Token);
        try
        {
            var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind);
            var acceptance = Accept(f, second, offer); await f.Native.Connection.HandlePlainAsync(acceptance);
            for (var index = 0; index < 2; index++) await f.Native.Connection.HandlePlainAsync(Chunk(second, acceptance, offer, index));
            await f.Native.Connection.HandlePlainAsync(Saved(second, acceptance, offer));
            var file = second.Manifest.Files.Single();
            var context = new JsonObject { ["format"] = 1, ["offer_id"] = offer["message_id"]!.DeepClone(),
                ["manifest_sha256"] = second.Manifest.Fingerprint, ["transfer_id"] = second.Manifest.TransferId,
                ["source_id"] = second.Manifest.SourceId, ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256,
                ["media_type"] = "images", ["mime_type"] = "image/png", ["publication_sha256"] = new string('b', 64),
                ["row_sha256"] = new string('d', 64), ["permission_epoch"] = acceptance["body"]!["permission_epoch"]!.DeepClone(), ["readback_nonce"] = new string('e', 64) };
            var binding = f.Owner.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), true)!;
            await f.Native.Connection.HandlePlainAsync(Message(DevicePublishedReadbackEnvelope.Kind, DevicePublishedReadbackEnvelope.EncodeBody(context, binding), offer));
            await sending; second.RequireIoEnded();
        }
        finally { stop.Cancel(); try { await sending; } catch { } }
        // Returning to older bytes is a NEW change relative to the latest end,
        // not a reason to silently reuse the first historical cache.
        Edit(MediaBytes);
        using var thirdSource = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved));
        using var third = thirdSource.FreezeCompletedSuccessor();
        var thirdLink = SourceRecord(f, third.JobId)["previous"]!.AsObject();
        TestAssert.That(third.Manifest.Files.Single().Sha256 == original.Manifest.Files.Single().Sha256 &&
            third.Manifest.Files.Single().Sha256 != second.Manifest.Files.Single().Sha256 &&
            thirdLink["job_id"]!.GetValue<string>() == second.JobId && thirdLink["job_version"]!.GetValue<string>() == secondVersion &&
            f.Native.Store.NativeMediaSourceHistory(f.Native.Peer.Id).Count == 3 && Exchange(f, original.JobId)["phase"]!.GetValue<string>() == "source_ended",
            "Rollback bytes were suppressed by older history, forked lineage or discarded a previous version.");
    }

    internal static async Task WindowsRejectsEarlySavedAndLostAttemptAsync()
    {
        foreach (var missing in new[] { false, true })
        {
            using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
            using var source = DeviceFileSourceCacheTests.Open(f, NativeMediaBookPermit.Capture(host.Snapshot()!, host.Saved)); using var cache = source.Freeze();
            DeviceFileConnectionRunsTests.Clear(f); using var stop = new CancellationTokenSource(); var send = f.Native.Connection.SendNativeMappedMediaSourceAsync(cache, stop.Token);
            try
            {
                var offer = await DeviceFileConnectionReceiveTests.Outbound(f, MediaOfferEnvelope.Kind); var acceptance = Accept(f, cache, offer);
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
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
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
        using var f = await DeviceFileSourceCacheTests.Fixture(MediaBytes); var host = new PersonalActorNativeSaveHost(Path.Combine(f.Native.Paths.Root, "send-book"), Book);
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
