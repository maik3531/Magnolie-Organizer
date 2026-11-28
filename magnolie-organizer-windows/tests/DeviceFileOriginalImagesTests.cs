using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileOriginalImagesTests
{
    internal static async Task VerifyManualAsync(PhoneCameraParentTests.Fixture fixture, TelefonCoordinator coordinator,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send, bool video = false)
    {
        var peer = fixture.Peer.Id;
        var kind = video ? "video" : "images";
        var offered = coordinator.NativeMediaUiStatus(peer);
        var sendVersion = offered["send_consent"]?["version"]?.GetValue<string>();
        TestAssert.That(sendVersion is not null && offered["send_choice_kinds"] is JsonArray kinds &&
            kinds.Count == 1 && kinds[0]?.GetValue<string>() == kind && offered["shared_start_version"] is null,
            "Original discovery did not expose only the selected media SEND choice.");
        var allowed = coordinator.ConfirmNativeMediaUiSendConsent(peer, sendVersion!, !video, video, () => true);
        var sourceVersion = allowed["collection_sources_version"]?.GetValue<string>();
        TestAssert.That(sourceVersion is not null && allowed["shared_start_version"] is null &&
            fixture.Store.NativeMediaCollectionRoots(peer).Count == 0 && !fixture.HasUnexpectedFrame,
            "Confirming SEND chose a root or started work.");
        var root = Path.Combine(fixture.Paths.Root, "explicit-" + kind + "-source");
        Directory.CreateDirectory(root);
        var originals = video ? new Dictionary<string, byte[]> { ["original.mp4"] = OriginalMp4() }
            : new Dictionary<string, byte[]> {
            ["first.png"] = DeviceFileSourceSendTests.PaddedPng(length: 128),
            ["second.png"] = DeviceFileSourceSendTests.PaddedPng(length: 256) };
        foreach (var (name, bytes) in originals) File.WriteAllBytes(Path.Combine(root, name), bytes);
        var selected = coordinator.ChooseNativeMediaCollectionFolder(peer, kind, sourceVersion!,
            current => { current(); return DeviceFileNativeDirectory.OpenExisting(root); });
        TestAssert.That(selected[video ? "private_pc_video_manual_start" : "private_pc_image_manual_start"]?.GetValue<bool>() == true &&
            selected["shared_start_version"] is not null && !fixture.HasUnexpectedFrame && !Directory.Exists(Path.Combine(root, "Backup")),
            "Native folder selection should prepare only the manual action.");
        var request = new JsonObject { ["cmd"] = "telefon_medien", ["device_id"] = peer,
            ["requestId"] = Guid.NewGuid().ToString("D"), ["action"] = "sync_shared", ["version"] = new string('0', 64) };
        TestAssert.Throws<InvalidDataException>(() => coordinator.RunNativeMediaUiSharedAsync(
            NativeMediaUiRequest.Parse(request), CancellationToken.None), "A stale version started the native sender.");
        request["version"] = selected["shared_start_version"]!.DeepClone();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(230));
        var pass = coordinator.RunNativeMediaUiSharedAsync(NativeMediaUiRequest.Parse(request), deadline.Token);
        await VerifyTransferAsync(fixture, read, send, video, originals, root, pass, deadline);
    }

    internal static async Task VerifyTransferAsync(PhoneCameraParentTests.Fixture fixture,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send, bool video,
        Dictionary<string, byte[]> originals, string root, Task pass, CancellationTokenSource deadline,
        NativeFileControlSession? agreedControls = null)
    {
        var peer = fixture.Peer.Id;
        var kind = video ? "video" : "images";
        var mime = video ? "video/mp4" : "image/png";
        try
        {
            async Task<JsonObject> ReadApplication(string expectedKind)
            {
                while (true)
                {
                    var next = read();
                    if (await Task.WhenAny(next, pass).WaitAsync(deadline.Token) == pass)
                    {
                        await pass;
                        throw new InvalidDataException($"The native action ended before {expectedKind}.");
                    }
                    var frame = await next;
                    if (JsonNode.DeepEquals(frame["type"], JsonValue.Create("ping")))
                    {
                        frame["type"] = "pong";
                        await send(frame);
                        Console.WriteLine("Original WLAN heartbeat answered during transfer preparation or exchange.");
                        continue;
                    }
                    TestAssert.That(frame["kind"]?.GetValue<string>() == expectedKind,
                        $"Expected {expectedKind}; received {frame["type"]} / {frame["kind"]}.");
                    return frame;
                }
            }
            var local = fixture.Store.ReadFileIdentity();
            var phone = new NativeFileControlIdentity(peer, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
            var desktop = new NativeFileControlPeer(local.DeviceId, local.IdentitySha256, new object(),
                true, true, true, true, true, fixture.Peer.FilePairingEpoch);
            var phoneGrant = new NativeLocalFileGrant(new(1, new string('a', 64), false, true), new object(), true);
            using var ownedControls = agreedControls is null ? new NativeFileControlSession(phone, () => desktop, () => phoneGrant) : null;
            var controls = agreedControls ?? ownedControls!;
            if (agreedControls is null)
            {
                var first = DeviceFileControlEnvelope.Validate(await ReadApplication(DeviceFileControl.Kind), Now());
                TestAssert.That(first.Grants.SendFiles && !first.Grants.ReceiveFiles && !pass.IsCompleted,
                    "Manual export did not wait for independent phone RECEIVE.");
                controls.ObserveRemote(first, desktop);
                var echoed = controls.Packet(); controls.MarkSent(echoed);
                await send(DeviceFileControlEnvelope.Create(echoed, Now()));
                controls.ObserveRemote(DeviceFileControlEnvelope.Validate(await ReadApplication(DeviceFileControl.Kind), Now()), desktop);
            }
            Console.WriteLine("Original WLAN SEND/RECEIVE echoed.");

            var binding = controls.Binding(new string('f', 64), senderIsLocal: false)!;
            var offerFrame = await ReadApplication(MediaOfferEnvelope.Kind);
            Console.WriteLine($"Original WLAN {kind} offer received.");
            var offer = MediaOfferEnvelope.Validate(offerFrame, binding.SenderId, binding.ReceiverId, Now(), allowPcBatch: !video);
            TestAssert.That(offer.PcBatch == !video && offer.Manifest.Files.Count == originals.Count && offer.Originals.Count == 0 &&
                offer.MediaType == kind && offerFrame["body"]?["format"]?.GetValue<int>() == (video ? 2 : 3) &&
                offer.PcOrigins.Count == originals.Count && offer.PcOrigins.All(pair =>
                    pair.Value?["previous_publication_sha256"] is null),
                "The original reader sent an unexpected offer shape or predecessor.");
            var accept = new JsonObject { ["format"] = 1, ["offer_id"] = offerFrame["message_id"]!.DeepClone(),
                ["transfer_id"] = offer.Manifest.TransferId, ["manifest_sha256"] = offer.Manifest.Fingerprint,
                ["permission_epoch"] = binding.PermissionEpoch, ["destination_token"] = binding.DestinationToken,
                ["acceptance_sha256"] = new string('a', 64) };
            var acceptance = DeviceFileSourceSendTests.Message(DeviceFileAcceptanceEnvelope.Kind, accept, offerFrame);
            await send(acceptance);
            var accepted = DeviceFileAcceptanceEnvelope.Parse(acceptance, Now());
            var receipts = new JsonArray();
            var members = new JsonObject();
            foreach (var file in offer.Manifest.Files)
            {
                var bytes = originals[file.Path];
                for (var index = 0; index * DeviceFileManifest.ChunkBytes < bytes.Length; index++)
                {
                    var chunk = accept.DeepClone().AsObject();
                    chunk.Remove("offer_id");
                    chunk["file_id"] = file.Id;
                    chunk["chunk_index"] = index;
                    var message = DeviceFileSourceSendTests.Message(DeviceFileChunkEnvelope.RequestKind, chunk, acceptance);
                    await send(message);
                    var received = DeviceFileChunkEnvelope.ParseResponse(
                        await ReadApplication(DeviceFileChunkEnvelope.ResultKind), message, offer.Manifest, accepted, Now());
                    try
                    {
                        TestAssert.That(received.SequenceEqual(bytes.Skip(index * DeviceFileManifest.ChunkBytes).Take(received.Length)),
                            "Original bytes changed through the actual encrypted connection.");
                    }
                    finally { CryptographicOperations.ZeroMemory(received); }
                }
                var publication = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(file.Id))).ToLowerInvariant();
                var row = DeviceFileControl.Digest("magnolie-test-published-row-v1\0", JsonValue.Create(file.Id)!);
                receipts.Add(new JsonObject { ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["receipt_sha256"] = publication });
                members[file.Id] = new JsonObject { ["size"] = file.Size, ["sha256"] = file.Sha256,
                    ["mime_type"] = mime, ["publication_sha256"] = publication, ["row_sha256"] = row };
            }
            var saved = accept.DeepClone().AsObject(); saved.Remove("offer_id"); saved["receipts"] = receipts;
            await send(DeviceFileSourceSendTests.Message(DeviceFileSavedEnvelope.Kind, saved, acceptance));
            TestAssert.That(!pass.IsCompleted, "Saved alone stopped the native operation.");
            var context = new JsonObject { ["format"] = video ? 1 : 2, ["offer_id"] = offerFrame["message_id"]!.DeepClone(),
                ["manifest_sha256"] = offer.Manifest.Fingerprint, ["transfer_id"] = offer.Manifest.TransferId,
                ["source_id"] = offer.Manifest.SourceId, ["media_type"] = kind,
                ["permission_epoch"] = binding.PermissionEpoch, ["readback_nonce"] = new string('b', 64) };
            if (video)
            {
                var member = members.Single();
                context["file_id"] = member.Key;
                foreach (var field in member.Value!.AsObject()) context[field.Key] = field.Value!.DeepClone();
                var readback = controls.Binding(DevicePublishedReadbackEnvelope.DestinationToken(context), senderIsLocal: false)!;
                await send(DeviceFileSourceSendTests.Message(DevicePublishedReadbackEnvelope.Kind,
                    DevicePublishedReadbackEnvelope.EncodeBody(context, readback), acceptance));
            }
            else
            {
                context["members"] = members;
                var readback = controls.Binding(DevicePublishedBatchReadbackEnvelope.DestinationToken(context), senderIsLocal: false)!;
                await send(DeviceFileSourceSendTests.Message(DevicePublishedBatchReadbackEnvelope.Kind,
                    DevicePublishedBatchReadbackEnvelope.EncodeBody(context, readback), acceptance));
            }
            Console.WriteLine("Original WLAN complete readback sent.");
            await pass.WaitAsync(deadline.Token);
            TestAssert.That((pass is not Task<string> result || result.Result == "content_pass") &&
                !fixture.Store.ReadNativeMediaReceiveConsent(peer).Granted &&
                originals.All(pair => File.ReadAllBytes(Path.Combine(root, pair.Key)).SequenceEqual(pair.Value)),
                "The completed export changed an original or acquired PC RECEIVE.");
            var exchange = DeviceFileSourceSendTests.Exchange(fixture.Store, peer, offer.Manifest.SourceId);
            var proof = video ? exchange["peer_readback"] : exchange["peer_readback"]?["body"];
            TestAssert.That(exchange["phase"]?.GetValue<string>() == "source_ended" && proof?["readback_sha256"] is not null &&
                JsonNode.DeepEquals(exchange["source_end"]?["readback_sha256"], proof["readback_sha256"]),
                $"The original {kind} transfer did not reach durable local END for its own readback.");
        }
        finally
        {
            deadline.Cancel();
            try { await pass.WaitAsync(TimeSpan.FromSeconds(10)); } catch { }
        }
    }

    // One synthetic 16×16 AVC frame, the same original used by the Notes fixture.
    internal static byte[] OriginalMp4() => Convert.FromBase64String("""
        AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMVbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAA
        AAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAj90cmFr
        AAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAA
        AABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAG3bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAA
        AABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1oZAAAAAEA
        AAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAA
        AAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2MC4zMS4xMDIgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAA
        NGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAAg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAA
        AADQAAAA0AAAABhzdHRzAAAAAAAAAAEAAAABAABAAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAAAaAAAA
        AQAAABRzdGNvAAAAAAAAAAEAAANFAAAAYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAt
        aWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2MC4xNi4xMDAAAAAIZnJlZQAAACJtZGF0AAAAFmWIhAAV//7sz34FNyA8i/WU
        CHS1b4E=
        """);

    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
}
