package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class DeviceFileControlTest {
    private class Side(val identity: NativeFileControlIdentity, other: NativeFileControlIdentity, grants: DeviceFileGrantState) {
        var peer = NativeFileControlPeer(other.deviceId, other.identitySha256, Any(), true, true, true, true, true)
        var local = NativeLocalFileGrant(grants, Any(), true)
        var session = newSession()
        fun newSession() = NativeFileControlSession(identity, { peer }, { local })
    }
    private fun pair(): Pair<Side, Side> {
        val sender = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
        val receiver = NativeFileControlIdentity("receiver_fixture_01", "e".repeat(64))
        return Side(sender, receiver, DeviceFileGrantState(3, "a".repeat(64), true, false)) to
            Side(receiver, sender, DeviceFileGrantState(7, "b".repeat(64), false, true))
    }
    private fun send(first: Side, second: Side): DeviceFileControlPacket {
        val packet = first.session.packet()
        first.session.markSent(packet) // Native guarded send completion boundary.
        second.session.observeRemote(DeviceFileControlPacket.parse(packet.wire()), second.peer)
        return packet
    }
    private fun handshake(first: Side, second: Side) {
        send(first, second); send(second, first)
        if (first.session.needsPacket()) send(first, second)
        if (second.session.needsPacket()) send(second, first)
    }
    private fun vector() = Json.parseToJsonElement(File("../contracts/file-transfer-control-v1-vectors.json").readText()).jsonObject

    @Test fun sharedCanonicalChallengeAndPermissionEpochMatchDesktop() {
        val vector = vector(); val packet = DeviceFileControlPacket.parse(vector["packet"]!!.jsonObject)
        val bytes = TelefonKanonisch.bytes(packet.wire())
        assertEquals(vector["canonical_bytes"]!!.jsonPrimitive.content.toInt(), bytes.size)
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }
        assertEquals(vector["canonical_sha256"]!!.jsonPrimitive.content, digest)
        assertEquals(vector["challenge_sha256"]!!.jsonPrimitive.content, packet.challenge)
        val (first, second) = pair(); handshake(first, second)
        val native = first.session.binding("c".repeat(64), true)!!
        assertEquals(second.session.binding("c".repeat(64)), native)
        assertEquals(vector["permission_epoch"]!!.jsonPrimitive.content, native.permissionEpoch)
        assertFalse(first.session.needsPacket()); assertFalse(second.session.needsPacket())
    }

    @Test fun freshEchoAndExactNativeSendTicketAreRequiredBeforePhotoReceiverExists() {
        val (first, second) = pair()
        assertNull(first.session.photoReceiver())
        send(first, second); send(second, first)
        assertNull(first.session.photoReceiver())
        val echo = first.session.packet()
        assertThrows(PhotoFolderScopeError::class.java) { first.session.markSent(echo.copy()) }
        assertNull(first.session.photoReceiver())
        first.session.markSent(echo)
        second.session.observeRemote(DeviceFileControlPacket.parse(echo.wire()), second.peer)
        val receiver = first.session.photoReceiver()!!
        assertTrue(receiver.allowed); assertSame(first.session, receiver.owner)
        assertEquals(second.identity.deviceId, receiver.peerId)
        assertNull(second.session.photoReceiver()) // Reverse direction remains off.
    }

    @Test fun reconnectRequiresFreshEchoButDoesNotRekeyPersistentAcceptedConsent() {
        val (first, second) = pair(); handshake(first, second)
        val before = first.session.binding("c".repeat(64), true)
        val oldPacket = first.session.packet(); val old = first.session
        first.peer = first.peer.copy(owner = Any()); second.peer = second.peer.copy(owner = Any())
        assertNull(old.photoReceiver())
        first.session = first.newSession(); second.session = second.newSession()
        second.session.observeRemote(DeviceFileControlPacket.parse(oldPacket.wire()), second.peer)
        assertNull(second.session.binding("c".repeat(64)))
        handshake(first, second)
        assertEquals(before, first.session.binding("c".repeat(64), true))
        assertEquals(before, second.session.binding("c".repeat(64)))
    }

    @Test fun currentNativePeerFlagsAndOwnerAreNotReplacedByWireClaims() {
        for (change in listOf("ready", "paired", "own", "remoteOwn", "supported", "owner", "key")) {
            val (first, second) = pair(); handshake(first, second)
            assertNotNull(first.session.photoReceiver())
            val original = first.peer
            first.peer = when (change) {
                "ready" -> original.copy(ready = false); "paired" -> original.copy(paired = false)
                "own" -> original.copy(ownDevice = false); "remoteOwn" -> original.copy(remoteOwnDevice = false)
                "supported" -> original.copy(controlSupported = false); "owner" -> original.copy(owner = Any())
                else -> original.copy(identitySha256 = "f".repeat(64))
            }
            assertNull(first.session.photoReceiver())
            if (change in setOf("owner", "key")) { first.peer = original; assertNull(first.session.photoReceiver()) }
        }
    }

    @Test fun grantRevocationAndEquivocationCannotKeepAnOldAllowedSourceReceiver() {
        val (first, second) = pair(); handshake(first, second)
        val before = first.session.photoReceiver()!!
        first.local = NativeLocalFileGrant(DeviceFileGrantState(4, "c".repeat(64), false, false), first.local.owner, true)
        assertNull(first.session.photoReceiver())
        send(first, second); assertNull(second.session.binding("c".repeat(64)))
        first.local = NativeLocalFileGrant(DeviceFileGrantState(5, "d".repeat(64), true, false), first.local.owner, true)
        send(first, second); send(second, first)
        assertNotEquals(before.permissionEpoch, first.session.photoReceiver()!!.permissionEpoch)
        first.local = NativeLocalFileGrant(DeviceFileGrantState(5, "d".repeat(64), false, false), first.local.owner, true)
        assertNull(first.session.photoReceiver()) // Same persistent revision, changed grant: fail closed.
    }

    @Test fun futureManifestCapabilityDoesNotRekeyV1ButUnsupportedV1PausesIt() {
        val (first, second) = pair(); handshake(first, second)
        val before = first.session.photoReceiver()!!.permissionEpoch
        first.local = NativeLocalFileGrant(DeviceFileGrantState(3, "a".repeat(64), true, false, listOf(1, 2)), first.local.owner, true)
        assertNull(first.session.photoReceiver())
        send(first, second); send(second, first)
        assertEquals(before, first.session.photoReceiver()!!.permissionEpoch)
        first.local = NativeLocalFileGrant(DeviceFileGrantState(3, "a".repeat(64), true, false, listOf(2)), first.local.owner, true)
        send(first, second); assertNull(first.session.photoReceiver()); assertNull(second.session.binding("c".repeat(64)))
    }

    @Test fun strictWireShapesAndDefensiveVersionsRejectBooleanCounterAliases() {
        val original = vector()["packet"]!!.jsonObject
        for ((key, value) in listOf("format" to JsonPrimitive(true), "grant_revision" to JsonPrimitive(true),
            "grant_revision" to JsonPrimitive("3"), "sequence" to JsonPrimitive(DeviceFileControl.MAX_REVISION + 1),
            "send_files" to JsonPrimitive(1), "echo" to JsonPrimitive("peer-name"),
            "manifest_versions" to JsonArray(listOf(JsonPrimitive(2), JsonPrimitive(1))),
            "personal_notes_sync" to JsonPrimitive(true))) {
            assertThrows(PhotoFolderScopeError::class.java) { DeviceFileControlPacket.parse(JsonObject(original + (key to value))) }
        }
        val mutable = mutableListOf(1)
        val state = DeviceFileGrantState(1, "a".repeat(64), versions = mutable)
        mutable.add(2); assertEquals(listOf(1), state.manifestVersions)
        assertThrows(UnsupportedOperationException::class.java) { (state.manifestVersions as MutableList<Int>).add(2) }
    }

    @Test fun copiedPacketAndSameRevisionDifferentGrantFailWithoutChangingNativeLocalPolicy() {
        val (first, second) = pair(); val packet = send(first, second)
        assertFalse(second.session.observeRemote(DeviceFileControlPacket.parse(packet.wire()), second.peer))
        val changed = packet.copy(grants = DeviceFileGrantState(3, "a".repeat(64), false, false))
        assertThrows(PhotoFolderScopeError::class.java) { second.session.observeRemote(changed, second.peer) }
        assertFalse(second.local.grants.sendFiles); assertTrue(second.local.grants.receiveFiles)
        assertNull(second.session.binding("c".repeat(64)))
        first.session.close(); assertNull(first.session.photoReceiver()); assertFalse(first.session.needsPacket())
    }
}
