using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileConnectionTransportTests
{
    internal static IReadOnlyList<JsonObject> OpenFrames(byte[] wire)
    {
        var result = new List<JsonObject>();
        for (var offset = 0; offset < wire.Length;)
        {
            var length = BinaryPrimitives.ReadInt32BigEndian(wire.AsSpan(offset, 4)); offset += 4;
            var envelope = JsonNode.Parse(wire.AsSpan(offset, length))!.AsObject(); offset += length;
            var header = envelope.DeepClone().AsObject(); header.Remove("ciphertext");
            var sequence = TelefonProtocolContract.Integer(header["seq"]);
            var nonce = new byte[12]; BinaryPrimitives.WriteInt64BigEndian(nonce.AsSpan(4), sequence);
            var cipher = Convert.FromBase64String(envelope["ciphertext"]!.GetValue<string>());
            var plain = new byte[cipher.Length - 16];
            using (var aes = new AesGcm(new byte[32], 16)) aes.Decrypt(nonce, cipher.AsSpan(0, plain.Length), cipher.AsSpan(plain.Length), plain, TelefonCrypto.Canonical(header));
            TestAssert.That(header["dir"]!.GetValue<string>() == "desktop_to_phone", "Wrong secure file output direction.");
            result.Add(JsonNode.Parse(plain)!.AsObject());
        }
        return result;
    }

    private static void Identity(DeviceFileConnectionMetadataTests.Fixture fixture)
    {
        var identity = fixture.Store.LoadOrCreateIdentity();
        CryptographicOperations.ZeroMemory(identity.PrivateKey);
    }

    internal static async Task HandshakeAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        var localOwner = new object();
        var local = new NativeLocalFileGrant(new(7, new string('b', 64), false, true), localOwner, true);
        TestAssert.Throws<InvalidDataException>(() => fixture.Connection.OpenNativeFileControls(() => local), "Warmup metadata opened a native route.");
        await fixture.SeedAsync();
        // Existing shared/time warmup may initialize its ordinary identity.
        // Remove only this fixture's public record, preserving its original key.
        var savedIdentity = fixture.Paths.TelefonIdentity + ".fixture";
        File.Move(fixture.Paths.TelefonIdentity, savedIdentity);
        var originalKey = File.ReadAllBytes(fixture.Paths.TelefonIdentityKey);
        TestAssert.Throws<InvalidDataException>(() => fixture.Connection.OpenNativeFileControls(() => local), "Absent protected identity was silently created.");
        TestAssert.That(!File.Exists(fixture.Paths.TelefonIdentity) && File.ReadAllBytes(fixture.Paths.TelefonIdentityKey).SequenceEqual(originalKey), "Native route wrote identity files.");
        File.Move(savedIdentity, fixture.Paths.TelefonIdentity);
        Identity(fixture);
        var identityBytes = File.ReadAllBytes(fixture.Paths.TelefonIdentity);
        var keyBytes = File.ReadAllBytes(fixture.Paths.TelefonIdentityKey);
        var identity = fixture.Store.ReadFileIdentity();
        var owner = fixture.Connection.OpenNativeFileControls(() => local);
        TestAssert.Throws<InvalidDataException>(() => fixture.Connection.OpenNativeFileControls(() => local), "Native owners overlapped on one channel.");
        var phoneIdentity = new NativeFileControlIdentity(fixture.Peer.Id, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
        var remoteLocal = new NativeLocalFileGrant(new(3, new string('a', 64), true, false), new object(), true);
        var remotePeer = new NativeFileControlPeer(identity.DeviceId, identity.IdentitySha256, new object(), true, true, true, true, true, fixture.Peer.FilePairingEpoch);
        using var phone = new NativeFileControlSession(phoneIdentity, () => remotePeer, () => remoteLocal);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        TestAssert.That(await fixture.Connection.SendNativeFileControlsAsync(), "Initial controls were not sent.");
        var first = OpenFrames(fixture.Stream.ToArray()).Single();
        phone.ObserveRemote(DeviceFileControlEnvelope.Validate(first, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), remotePeer);
        var phonePacket = phone.Packet(); phone.MarkSent(phonePacket);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        var incoming = DeviceFileControlEnvelope.Create(phonePacket, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        await fixture.Connection.HandlePlainAsync(incoming);
        var echoed = OpenFrames(fixture.Stream.ToArray()).Single();
        TestAssert.That(echoed["kind"]!.GetValue<string>() == DeviceFileControl.Kind, "File controls entered legacy ACK/personal transport.");
        phone.ObserveRemote(DeviceFileControlEnvelope.Validate(echoed, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), remotePeer);
        var destination = new string('c', 64);
        TestAssert.That(owner.Binding(destination) is not null && phone.Binding(destination, senderIsLocal: true) is not null,
            "Actual encrypted control handshake did not produce matching native data scope.");
        TestAssert.That(owner.Binding(destination) == phone.Binding(destination, senderIsLocal: true), "Peers disagreed on current file scope.");
        TestAssert.That(!await fixture.Connection.SendNativeFileControlsAsync(), "Unchanged controls sent unsolicited repeats.");
        TestAssert.That(!fixture.Store.HasIncomingReceipt(fixture.Peer.Id, incoming["message_id"]!.GetValue<string>()), "File controls created a generic inbox receipt.");
        TestAssert.That(File.ReadAllBytes(fixture.Paths.TelefonIdentity).SequenceEqual(identityBytes) && File.ReadAllBytes(fixture.Paths.TelefonIdentityKey).SequenceEqual(keyBytes), "Read-only identity scope rewrote keys/name.");
        fixture.Connection.Dispose();
        TestAssert.That(owner.Binding(destination) is null, "Disconnected file owner retained data authority.");
    }

    internal static async Task FailureAsync()
    {
        foreach (var failure in new[] { "write", "metadata", "local", "peer", "identity" })
        {
            using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
            await fixture.SeedAsync(); Identity(fixture);
            var nativeOwner = new object();
            var local = new NativeLocalFileGrant(new(7, new string('b', 64), false, true), nativeOwner, true);
            var owner = fixture.Connection.OpenNativeFileControls(() => local);
            fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
            fixture.Stream.Fail = failure == "write";
            fixture.Stream.BeforeWrite = () => {
                if (failure == "metadata") fixture.Store.UpdatePeerProtocol(fixture.Peer.Id, 2, TelefonProtocolContract.DesktopCapabilities()["items"]!.AsObject(), 0, null);
                if (failure == "local") local = new(new(8, new string('c', 64), false, false), nativeOwner, true);
                if (failure == "peer") fixture.Store.SavePeers([fixture.Store.LoadPeers().Single() with { FilePairingEpoch = new string('f', 64) }]);
                if (failure == "identity") File.WriteAllText(fixture.Paths.TelefonIdentity, "{}");
            };
            var failed = false;
            try { await fixture.Connection.SendNativeFileControlsAsync(); }
            catch (Exception error) when (error is IOException or InvalidDataException or InvalidOperationException or CryptographicException) { failed = true; }
            TestAssert.That(failed, "Uncertain control output was counted as sent: " + failure);
            TestAssert.That(owner.RemoteControlWitness() is null, "Failed control owner retained remote witness: " + failure);
            fixture.Stream.BeforeWrite = null; fixture.Stream.Fail = false;
            TestAssert.Throws<InvalidDataException>(() => fixture.Connection.OpenNativeFileControls(() => local), "A failed route silently reopened: " + failure);
        }
    }

    internal static async Task ReservedAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        await fixture.SeedAsync(); Identity(fixture);
        var local = new NativeLocalFileGrant(new(7, new string('b', 64)), new object(), false);
        var owner = fixture.Connection.OpenNativeFileControls(() => local);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        TestAssert.That(await fixture.Connection.SendNativeFileControlsAsync(), "OFF control route did not send its native policy.");
        var message = OpenFrames(fixture.Stream.ToArray()).Single();
        TestAssert.That(message["body"]!["receive_files"]!.GetValue<bool>() == false && owner.Binding(new string('c', 64)) is null,
            "Absent data handlers advertised receive permission.");
        foreach (var kind in new[] { "file_transfer.offer", "file_transfer.sources.media", "file_transfer.unknown" })
        {
            var incoming = message.DeepClone().AsObject(); incoming["kind"] = kind; incoming["message_id"] = Guid.NewGuid().ToString("D");
            var failed = false;
            try { await fixture.Connection.HandlePlainAsync(incoming); }
            catch (InvalidDataException) { failed = true; }
            TestAssert.That(failed && !fixture.Store.HasIncomingReceipt(fixture.Peer.Id, incoming["message_id"]!.GetValue<string>()),
                "Unsupported reserved data entered personal inbox: " + kind);
        }
    }

    internal static async Task LostIdentityAsync()
    {
        using var fixture = new DeviceFileConnectionMetadataTests.Fixture();
        await fixture.SeedAsync(); Identity(fixture);
        var local = new NativeLocalFileGrant(new(7, new string('b', 64)), new object(), false);
        var owner = fixture.Connection.OpenNativeFileControls(() => local);
        var original = File.ReadAllBytes(fixture.Paths.TelefonIdentity);
        File.WriteAllText(fixture.Paths.TelefonIdentity, "{}");
        TestAssert.Throws<InvalidDataException>(() => { _ = owner.NeedsPacket; }, "Unreadable protected identity did not fail the native scope.");
        TestAssert.That(!owner.NeedsPacket && owner.Binding(new string('c', 64)) is null, "Disposed native scope reread its failed protected identity.");
        File.WriteAllBytes(fixture.Paths.TelefonIdentity, original);
        TestAssert.That(!owner.NeedsPacket && owner.Binding(new string('c', 64)) is null, "Restored identity revived a failed native owner.");
        TestAssert.Throws<InvalidDataException>(() => fixture.Connection.OpenNativeFileControls(() => local), "Identity read failure permitted a replacement owner on the old channel.");
    }

    internal static Task EnvelopeAsync()
    {
        var packet = new DeviceFileControlPacket(new(1, new string('a', 64)), new string('b', 64), 1, null);
        const long now = 1000000;
        var valid = DeviceFileControlEnvelope.Create(packet, now);
        TestAssert.That(DeviceFileControlEnvelope.Validate(valid, now).Same(packet), "Native file envelope changed its control body.");
        foreach (var mutate in new Action<JsonObject>[] {
            value => value["extra"] = true, value => value["v"] = true, value => value["kind"] = "file_transfer.offer",
            value => value["message_id"] = "not-a-uuid", value => value["created_ms"] = -1,
            value => value["expires_ms"] = now, value => value["expires_ms"] = now + 60001,
            value => { value["created_ms"] = now + 300001; value["expires_ms"] = now + 360001; },
            value => value["body"]!["send_files"] = 1, value => value["body"]!["grant_epoch"] = new string('a', 9000)
        })
        {
            var changed = valid.DeepClone().AsObject(); mutate(changed);
            TestAssert.Throws<InvalidDataException>(() => DeviceFileControlEnvelope.Validate(changed, now), "Invalid file control envelope accepted.");
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileControlEnvelope.Validate(valid, now + 60000), "Expired controls received legacy grace.");
        return Task.CompletedTask;
    }

    internal static async Task<NativeFileControlSession> OpenOffSourceAsync(DeviceFileConnectionMetadataTests.Fixture fixture, bool videos = true)
    {
        await fixture.SeedAsync(); Identity(fixture);
        if (!videos) await fixture.Connection.HandlePlainAsync(fixture.Message("capabilities.update", 2, video: false));
        var identity = fixture.Store.ReadFileIdentity();
        var local = new NativeLocalFileGrant(new(7, new string('b', 64), false, true), new object(), true);
        var owner = fixture.Connection.OpenNativeFileControls(() => local);
        var phoneIdentity = new NativeFileControlIdentity(fixture.Peer.Id, Convert.ToHexString(SHA256.HashData(fixture.Peer.PublicKey)).ToLowerInvariant());
        var phoneLocal = new NativeLocalFileGrant(new(3, new string('a', 64)), new object(), true);
        var phonePeer = new NativeFileControlPeer(identity.DeviceId, identity.IdentitySha256, new object(), true, true, true, true, true, fixture.Peer.FilePairingEpoch);
        using var phone = new NativeFileControlSession(phoneIdentity, () => phonePeer, () => phoneLocal);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        await fixture.Connection.SendNativeFileControlsAsync();
        phone.ObserveRemote(DeviceFileControlEnvelope.Validate(OpenFrames(fixture.Stream.ToArray()).Single(), DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()), phonePeer);
        var packet = phone.Packet(); phone.MarkSent(packet);
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        await fixture.Connection.HandlePlainAsync(DeviceFileControlEnvelope.Create(packet, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()));
        TestAssert.That(owner.Binding(new string('c', 64)) is null, "Source SEND-OFF acquired a data binding.");
        fixture.Stream.SetLength(0); fixture.Stream.Position = 0;
        return owner;
    }
}
