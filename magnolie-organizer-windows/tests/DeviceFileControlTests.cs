using System.Security.Cryptography;
using System.Text.Json.Nodes;
using MagnolieOrganizer.Windows;

namespace MagnolieOrganizer.Windows.Tests;

internal static class DeviceFileControlTests
{
    private sealed class Side
    {
        internal NativeFileControlIdentity Identity { get; }
        internal NativeFileControlPeer Peer;
        internal NativeLocalFileGrant Local;
        internal NativeFileControlSession Session;
        internal Side(NativeFileControlIdentity identity, NativeFileControlIdentity other, DeviceFileGrantState grants)
        {
            Identity = identity; Peer = new(other.DeviceId, other.IdentitySha256, new object(), true, true, true, true, true);
            Local = new(grants, new object(), true); Session = NewSession();
        }
        internal NativeFileControlSession NewSession() => new(Identity, () => Peer, () => Local);
    }
    private static (Side First, Side Second) Pair()
    {
        var sender = new NativeFileControlIdentity("sender_fixture_01", new string('d', 64));
        var receiver = new NativeFileControlIdentity("receiver_fixture_01", new string('e', 64));
        return (new(sender, receiver, new(3, new string('a', 64), true, false)), new(receiver, sender, new(7, new string('b', 64), false, true)));
    }
    private static DeviceFileControlPacket Send(Side sender, Side receiver)
    {
        var packet = sender.Session.Packet(); sender.Session.MarkSent(packet);
        receiver.Session.ObserveRemote(DeviceFileControlPacket.Parse(packet.Wire()), receiver.Peer);
        return packet;
    }
    private static void Handshake(Side first, Side second)
    {
        Send(first, second); Send(second, first);
        if (first.Session.NeedsPacket) Send(first, second);
        if (second.Session.NeedsPacket) Send(second, first);
    }
    internal static Task RunAsync()
    {
        var (epochFirst, epochSecond) = Pair();
        {
            var (metadata, other) = Pair();
            metadata.Local = new(new(4, new string('a', 64), false, false), metadata.Local.Owner, true);
            other.Local = new(new(8, new string('b', 64), false, false), other.Local.Owner, true);
            Handshake(metadata, other);
            var position = metadata.Session.RemoteControlWitness();
            TestAssert.That(position is not null && metadata.Session.NativeMetadataPositionUnchanged(position) &&
                metadata.Session.Binding(new string('f', 64), true) is null, "Native metadata position required or manufactured data grants.");
            // Comparing is local-only and must neither invoke Scope/store
            // callbacks nor generate/renew a control packet.
            var session = metadata.Session; var needs = session.NeedsPacket;
            metadata.Peer = metadata.Peer with { Ready = false };
            TestAssert.That(session.NativeMetadataPositionUnchanged(position) && session.NativeMetadataPositionUnchanged(position),
                "Deny-only position comparison unexpectedly invoked native callbacks; it must not be used as standalone readiness.");
            metadata.Peer = metadata.Peer with { Ready = true };
            TestAssert.That(session.NeedsPacket == needs, "Metadata comparison mutated transport output state.");
            Send(other, metadata);
            TestAssert.That(!session.NativeMetadataPositionUnchanged(position), "A later control position revived an original dialog snapshot.");
            var fresh = session.RemoteControlWitness(); session.Dispose();
            TestAssert.That(!session.NativeMetadataPositionUnchanged(fresh), "Disposed control context still matched a metadata dialog.");
            other.Session.Dispose();
        }
        epochFirst.Peer = epochFirst.Peer with { PairingEpoch = new string('c', 64) };
        epochFirst.Session.Dispose(); epochFirst.Session = epochFirst.NewSession();
        Handshake(epochFirst, epochSecond);
        TestAssert.That(epochFirst.Session.Binding(new string('f', 64), true) is not null, "Native paired file scope missing after exact handshake.");
        var epochPacket = epochSecond.Session.Packet(); epochSecond.Session.MarkSent(epochPacket);
        TestAssert.Throws<InvalidDataException>(() => epochFirst.Session.ObserveRemote(epochPacket,
            epochFirst.Peer with { PairingEpoch = new string('d', 64) }), "Foreign native pairing scope accepted.");
        epochFirst.Peer = epochFirst.Peer with { PairingEpoch = new string('d', 64) };
        TestAssert.That(epochFirst.Session.Binding(new string('f', 64), true) is null, "Native re-pair preserved old file authority.");
        epochFirst.Peer = epochFirst.Peer with { PairingEpoch = new string('c', 64) };
        TestAssert.That(epochFirst.Session.Binding(new string('f', 64), true) is null, "Old native pairing was revived.");
        epochFirst.Session.Dispose(); epochSecond.Session.Dispose();
        // Actual peer codecs, without constructing TelefonStore/keys/personal DB.
        var writePeer = typeof(TelefonStore).GetMethod("WritePeer", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
        var readPeer = typeof(TelefonStore).GetMethod("ReadPeer", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
        JsonObject Write(TelefonPeer value) => (JsonObject)writePeer.Invoke(null, [value])!;
        TelefonPeer Read(JsonObject value) => (TelefonPeer)readPeer.Invoke(null, [value])!;
        var legacyPeer = new TelefonPeer("receiver_fixture_01", "Fixture", Enumerable.Repeat((byte)7, 32).ToArray());
        var legacyWire = Write(legacyPeer);
        TestAssert.That(!legacyWire.ContainsKey("file_pairing_epoch") && DeviceFileControl.CurrentPairingEpoch(Read(legacyWire), true, true) is null,
            "Legacy peer read created native file relationship authority.");
        var firstEpoch = DeviceFileControl.PairingEpoch(Enumerable.Repeat((byte)1, 32).ToArray());
        var secondEpoch = DeviceFileControl.PairingEpoch(Enumerable.Repeat((byte)2, 32).ToArray());
        var pairedPeer = legacyPeer with { FilePairingEpoch = firstEpoch };
        TestAssert.That(firstEpoch != secondEpoch && DeviceFileControl.CurrentPairingEpoch(Read(Write(pairedPeer)) with { LastSeenMs = 1000 }, true, true) == firstEpoch &&
            DeviceFileControl.CurrentPairingEpoch(pairedPeer with { FilePairingEpoch = secondEpoch }, true, true) == secondEpoch,
            "Native reconnect lost its epoch or re-pair reused the old relationship.");
        TestAssert.That(DeviceFileControl.CurrentPairingEpoch(pairedPeer with { State = "pair_commit_pending" }, true, true) is null &&
            DeviceFileControl.CurrentPairingEpoch(pairedPeer, false, true) is null && DeviceFileControl.CurrentPairingEpoch(pairedPeer, true, false) is null,
            "Pending or revoked relationship exposed native file authority.");
        foreach (var invalid in new JsonNode?[] { null, JsonValue.Create(true), JsonValue.Create(""), JsonValue.Create(new string('A', 64)) })
        {
            var corrupt = Write(pairedPeer); corrupt["file_pairing_epoch"] = invalid;
            try { Read(corrupt); throw new InvalidOperationException("Corrupt file relationship was accepted."); }
            catch (System.Reflection.TargetInvocationException error) when (error.InnerException is InvalidDataException) { }
        }
        TestAssert.Throws<InvalidDataException>(() => DeviceFileControl.PairingEpoch(new byte[31]), "Invalid native transcript length was accepted.");
        const string relative = "contracts/file-transfer-control-v1-vectors.json";
        var vector = JsonNode.Parse(File.ReadAllText(Path.Combine(TestSource.Root(relative), relative)))!.AsObject();
        var packet = DeviceFileControlPacket.Parse(vector["packet"]!.AsObject());
        var bytes = TelefonCrypto.Canonical(packet.Wire());
        TestAssert.That(bytes.Length == vector["canonical_bytes"]!.GetValue<int>() &&
            Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() == vector["canonical_sha256"]!.GetValue<string>() &&
            packet.Challenge == vector["challenge_sha256"]!.GetValue<string>(), "Shared file-control canonical challenge differs.");
        var (first, second) = Pair();
        TestAssert.That(first.Session.Binding(new string('c', 64), true) is null, "Unconfirmed file consent became active.");
        Send(first, second); Send(second, first);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) is null, "Missing native echo send became active consent.");
        var echo = first.Session.Packet();
        TestAssert.Throws<InvalidDataException>(() => first.Session.MarkSent(DeviceFileControlPacket.Parse(echo.Wire())), "Copied wire packet released native send ownership.");
        first.Session.MarkSent(echo); second.Session.ObserveRemote(DeviceFileControlPacket.Parse(echo.Wire()), second.Peer);
        var binding = first.Session.Binding(new string('c', 64), true)!;
        TestAssert.That(binding == second.Session.Binding(new string('c', 64)) && binding.PermissionEpoch == vector["permission_epoch"]!.GetValue<string>() &&
            first.Session.Binding(new string('c', 64)) is null && !first.Session.NeedsPacket && !second.Session.NeedsPacket,
            "File direction, persistent permission epoch or bounded echo differs.");
        first.Local = new(first.Local.Grants, first.Local.Owner, true, policyReady: false);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) is null && !first.Session.NeedsPacket, "Pending native policy retained data I/O authority.");
        TestAssert.Throws<InvalidDataException>(() => first.Session.Packet(), "Pending policy generated ordinary file controls.");
        first.Local = new(first.Local.Grants, first.Local.Owner, true, policyReady: true);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) == binding, "Temporary native policy fence rekeyed unchanged confirmed grants.");

        var old = first.Session; var oldPacket = old.Packet();
        first.Peer = first.Peer with { Owner = new object() }; second.Peer = second.Peer with { Owner = new object() };
        TestAssert.That(old.Binding(new string('c', 64), true) is null, "Old native channel ownership survived replacement.");
        first.Session = first.NewSession(); second.Session = second.NewSession();
        second.Session.ObserveRemote(DeviceFileControlPacket.Parse(oldPacket.Wire()), second.Peer);
        TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Old echo authorized a fresh channel.");
        Handshake(first, second);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) == binding && second.Session.Binding(new string('c', 64)) == binding,
            "Fresh file handshake rekeyed unchanged persistent accepted consent.");

        second.Local = new(new(8, new string('c', 64), false, false), second.Local.Owner, true);
        TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Native local revocation retained file consent.");
        Send(second, first);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) is null, "Remote file revocation retained sender consent.");
        second.Local = new(new(9, new string('d', 64), false, true), second.Local.Owner, true);
        Send(second, first); Send(first, second);
        TestAssert.That(second.Session.Binding(new string('c', 64))?.PermissionEpoch != binding.PermissionEpoch, "Changed persistent grant epoch reused old file binding.");

        (first, second) = Pair(); Handshake(first, second); binding = first.Session.Binding(new string('c', 64), true)!;
        first.Local = new(new(3, new string('a', 64), true, false, [1, 2]), first.Local.Owner, true);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) is null, "New capability metadata bypassed fresh echo.");
        Send(first, second); Send(second, first);
        TestAssert.That(first.Session.Binding(new string('c', 64), true) == binding && second.Session.Binding(new string('c', 64)) == binding,
            "Future compatible manifest version reset accepted v1 permission epoch.");
        first.Local = new(new(3, new string('a', 64), true, false, [2]), first.Local.Owner, true);
        Send(first, second);
        TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Unsupported manifest v1 was treated as native support.");

        foreach (var field in new[] { "ready", "paired", "own", "remoteOwn", "supported", "owner", "key", "localOwner" })
        {
            (first, second) = Pair(); Handshake(first, second); var original = second.Peer; var originalLocal = second.Local;
            second.Peer = field switch
            {
                "ready" => original with { Ready = false }, "paired" => original with { Paired = false },
                "own" => original with { OwnDevice = false }, "remoteOwn" => original with { RemoteOwnDevice = false },
                "supported" => original with { ControlSupported = false }, "owner" => original with { Owner = new object() },
                "key" => original with { IdentitySha256 = new string('f', 64) }, _ => original
            };
            if (field == "localOwner") second.Local = new(second.Local.Grants, new object(), true);
            TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Native peer/local scope was inferred from wire metadata.");
            if (field is "owner" or "key" or "localOwner")
            {
                second.Peer = original; second.Local = originalLocal;
                TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Changed original native owner was silently adopted again.");
            }
        }
        (first, second) = Pair(); var sent = Send(first, second);
        TestAssert.That(!second.Session.ObserveRemote(DeviceFileControlPacket.Parse(sent.Wire()), second.Peer), "Identical control duplicate was not idempotent.");
        var equivocation = new DeviceFileControlPacket(new(3, new string('a', 64), false, false), sent.SessionEpoch, sent.Sequence, sent.Echo);
        TestAssert.Throws<InvalidDataException>(() => second.Session.ObserveRemote(equivocation, second.Peer), "Same control sequence/revision adopted different consent.");
        TestAssert.That(second.Session.Binding(new string('c', 64)) is null, "Equivocated file controls remained active.");

        foreach (var field in new[] { "format", "revision", "flag", "versions", "echo", "extra" })
        {
            var invalid = packet.Wire();
            switch (field)
            {
                case "format": invalid["format"] = true; break;
                case "revision": invalid["sequence"] = DeviceFileControl.MaximumRevision + 1; break;
                case "flag": invalid["send_files"] = 1; break;
                case "versions": invalid["manifest_versions"] = new JsonArray(2, 1); break;
                case "echo": invalid["echo"] = "peer-name"; break;
                default: invalid["personal_notes_sync"] = true; break;
            }
            TestAssert.Throws<InvalidDataException>(() => DeviceFileControlPacket.Parse(invalid), "Invalid file-control wire shape became consent.");
        }
        var mutable = new[] { 1 }; var frozen = new DeviceFileGrantState(1, new string('a', 64), versions: mutable); mutable[0] = 2;
        TestAssert.That(frozen.ManifestVersions.SequenceEqual([1]), "Native manifest capability list retained a mutable caller alias.");
        first.Session.Dispose(); TestAssert.That(first.Session.Binding(new string('c', 64), true) is null && !first.Session.NeedsPacket, "Closed file session retained ownership.");
        return Task.CompletedTask;
    }
}
