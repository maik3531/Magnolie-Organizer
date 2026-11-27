using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileOriginalImagesTests
{
    internal static async Task VerifyManualAsync(PhoneCameraParentTests.Fixture fixture, TelefonCoordinator coordinator,
        Func<Task<JsonObject>> read, Func<JsonObject, Task> send)
    {
        var peer = fixture.Peer.Id;
        var offered = coordinator.NativeMediaUiStatus(peer);
        var sendVersion = offered["send_consent"]?["version"]?.GetValue<string>();
        TestAssert.That(sendVersion is not null && offered["send_choice_kinds"] is JsonArray kinds &&
            kinds.Count == 1 && kinds[0]?.GetValue<string>() == "images" && offered["shared_start_version"] is null,
            "Original discovery did not expose only the separate photo SEND choice.");
        var allowed = coordinator.ConfirmNativeMediaUiSendConsent(peer, sendVersion!, true, false, () => true);
        var sourceVersion = allowed["collection_sources_version"]?.GetValue<string>();
        TestAssert.That(sourceVersion is not null && allowed["shared_start_version"] is null &&
            fixture.Store.NativeMediaCollectionRoots(peer).Count == 0 && !fixture.HasUnexpectedFrame,
            "Confirming SEND chose a root or started work.");
        var root = Path.Combine(fixture.Paths.Root, "explicit-photo-source");
        Directory.CreateDirectory(root);
        var originals = new Dictionary<string, byte[]> {
            ["first.png"] = DeviceFileSourceSendTests.PaddedPng(length: 128),
            ["second.png"] = DeviceFileSourceSendTests.PaddedPng(length: 256) };
        foreach (var (name, bytes) in originals) File.WriteAllBytes(Path.Combine(root, name), bytes);
        var selected = coordinator.ChooseNativeMediaCollectionFolder(peer, "images", sourceVersion!,
            current => { current(); return DeviceFileNativeDirectory.OpenExisting(root); });
        TestAssert.That(selected["private_pc_image_manual_start"]?.GetValue<bool>() == true &&
            selected["shared_start_version"] is not null && !fixture.HasUnexpectedFrame && !Directory.Exists(Path.Combine(root, "Backup")),
            "Native folder selection should prepare only the manual action.");
        var request = new JsonObject { ["cmd"] = "telefon_medien", ["device_id"] = peer,
            ["requestId"] = Guid.NewGuid().ToString("D"), ["action"] = "sync_shared", ["version"] = new string('0', 64) };
        TestAssert.Throws<InvalidDataException>(() => coordinator.RunNativeMediaUiSharedAsync(
            NativeMediaUiRequest.Parse(request), CancellationToken.None), "A stale version started the native sender.");
        request["version"] = selected["shared_start_version"]!.DeepClone();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(230));
        var pass = coordinator.RunNativeMediaUiSharedAsync(NativeMediaUiRequest.Parse(request), deadline.Token);
        try
        {
            async Task<JsonObject> ReadApplication(string expectedKind)
            {
                while (true)
                {
                    var next = read();
                    if (await Task.WhenAny(next, pass).WaitAsync(deadline.Token) == pass)
                        throw new InvalidDataException($"The native action ended before {expectedKind}: {await pass}.");
                    var frame = await next;
                    if (JsonNode.DeepEquals(frame["type"], JsonValue.Create("ping")))
                    {
                        frame["type"] = "pong";
                        await send(frame);
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
            using var controls = new NativeFileControlSession(phone, () => desktop, () => phoneGrant);
            var first = DeviceFileControlEnvelope.Validate(await ReadApplication(DeviceFileControl.Kind), Now());
            TestAssert.That(first.Grants.SendFiles && !first.Grants.ReceiveFiles && !pass.IsCompleted,
                "Manual photo export did not wait for independent phone RECEIVE.");
            controls.ObserveRemote(first, desktop);
            var echoed = controls.Packet(); controls.MarkSent(echoed);
            await send(DeviceFileControlEnvelope.Create(echoed, Now()));
            controls.ObserveRemote(DeviceFileControlEnvelope.Validate(await ReadApplication(DeviceFileControl.Kind), Now()), desktop);
            Console.WriteLine("Original WLAN SEND/RECEIVE echoed.");

            var binding = controls.Binding(new string('f', 64), senderIsLocal: false)!;
            var offerFrame = await ReadApplication(MediaOfferEnvelope.Kind);
            Console.WriteLine("Original WLAN photo offer received.");
            var offer = MediaOfferEnvelope.Validate(offerFrame, binding.SenderId, binding.ReceiverId, Now(), allowPcBatch: true);
            TestAssert.That(offer.PcBatch && offer.Manifest.Files.Count == originals.Count && offer.Originals.Count == 0,
                "The original reader did not send the one complete Format 3 offer.");
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
                            "An original PNG changed through the actual encrypted connection.");
                    }
                    finally { CryptographicOperations.ZeroMemory(received); }
                }
                var publication = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(file.Id))).ToLowerInvariant();
                var row = DeviceFileControl.Digest("magnolie-test-published-row-v1\0", JsonValue.Create(file.Id)!);
                receipts.Add(new JsonObject { ["file_id"] = file.Id, ["size"] = file.Size, ["sha256"] = file.Sha256, ["receipt_sha256"] = publication });
                members[file.Id] = new JsonObject { ["size"] = file.Size, ["sha256"] = file.Sha256,
                    ["mime_type"] = "image/png", ["publication_sha256"] = publication, ["row_sha256"] = row };
            }
            var saved = accept.DeepClone().AsObject(); saved.Remove("offer_id"); saved["receipts"] = receipts;
            await send(DeviceFileSourceSendTests.Message(DeviceFileSavedEnvelope.Kind, saved, acceptance));
            TestAssert.That(!pass.IsCompleted, "Saved alone stopped the native operation.");
            var context = new JsonObject { ["format"] = 2, ["offer_id"] = offerFrame["message_id"]!.DeepClone(),
                ["manifest_sha256"] = offer.Manifest.Fingerprint, ["transfer_id"] = offer.Manifest.TransferId,
                ["source_id"] = offer.Manifest.SourceId, ["media_type"] = "images", ["members"] = members,
                ["permission_epoch"] = binding.PermissionEpoch, ["readback_nonce"] = new string('b', 64) };
            var readback = controls.Binding(DevicePublishedBatchReadbackEnvelope.DestinationToken(context), senderIsLocal: false)!;
            await send(DeviceFileSourceSendTests.Message(DevicePublishedBatchReadbackEnvelope.Kind,
                DevicePublishedBatchReadbackEnvelope.EncodeBody(context, readback), acceptance));
            Console.WriteLine("Original WLAN complete readback sent.");
            TestAssert.That(await pass.WaitAsync(deadline.Token) == "content_pass" &&
                !fixture.Store.ReadNativeMediaReceiveConsent(peer).Granted &&
                originals.All(pair => File.ReadAllBytes(Path.Combine(root, pair.Key)).SequenceEqual(pair.Value)),
                "The completed photo batch changed an original or acquired PC RECEIVE.");
        }
        finally
        {
            deadline.Cancel();
            try { await pass.WaitAsync(TimeSpan.FromSeconds(10)); } catch { }
        }
    }

    private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
}
