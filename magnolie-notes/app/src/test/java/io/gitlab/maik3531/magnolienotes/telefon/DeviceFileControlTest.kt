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

    private fun incomingPair(ready: () -> Boolean = { true }, clock: () -> Long = { DeviceFileControl.monotonicMs() },
        pairingEpoch: String? = "f".repeat(64)): Pair<Side, Side> {
        val (pc, phone) = pair()
        pc.peer = pc.peer.copy(pairingEpoch = pairingEpoch); phone.peer = phone.peer.copy(pairingEpoch = pairingEpoch)
        phone.local = NativeLocalFileGrant(DeviceFileGrantState(7, "b".repeat(64), false, false), phone.local.owner, true)
        pc.session.close(); phone.session.close(); pc.session = pc.newSession()
        phone.session = NativeFileControlSession(phone.identity, { phone.peer }, { phone.local }, clock, ready)
        return pc to phone
    }

    @Test fun incomingBootstrapNeedsActualReceiveHandlersAndNativePairingNotOnlyPcSendConsent() {
        for ((ready, pairing) in listOf(false to "f".repeat(64), true to null)) {
            val (pc, phone) = incomingPair({ ready }, pairingEpoch = pairing); handshake(pc, phone)
            assertThrows(PhotoFolderScopeError::class.java) { phone.session.receiveConfigurationTicket() }
            assertFalse(phone.local.grants.receiveFiles); assertNull(phone.session.binding("c".repeat(64)))
            pc.session.close(); phone.session.close()
        }
        val (pc, phone) = incomingPair()
        phone.session.close(); phone.session = NativeFileControlSession(phone.identity, { phone.peer }, { phone.local })
        handshake(pc, phone)
        assertThrows(PhotoFolderScopeError::class.java) { phone.session.receiveConfigurationTicket() } // Production default remains closed.
        pc.session.close(); phone.session.close()
    }

    @Test fun incomingBootstrapNeedsFreshEchoAndPcSendNotPcReceiveOnly() {
        val (pc, phone) = incomingPair()
        assertThrows(PhotoFolderScopeError::class.java) { phone.session.receiveConfigurationTicket() }
        send(pc, phone); send(phone, pc)
        assertThrows(PhotoFolderScopeError::class.java) { phone.session.receiveConfigurationTicket() }
        handshake(pc, phone)
        val ticket = phone.session.receiveConfigurationTicket()
        assertNotNull(phone.session.receiveConfigurationAuthority(ticket))
        phone.session.finishConfiguration(ticket)
        pc.local = NativeLocalFileGrant(DeviceFileGrantState(4, "d".repeat(64), false, true), pc.local.owner, true)
        handshake(pc, phone)
        assertThrows(PhotoFolderScopeError::class.java) { phone.session.receiveConfigurationTicket() }
        assertNotNull(phone.session.configurationAuthority(phone.session.configurationTicket()))
        assertFalse(phone.local.grants.receiveFiles); assertNull(phone.session.binding("c".repeat(64)))
        pc.session.close(); phone.session.close()
    }

    @Test fun sourceAndIncomingConfigurationTicketsAreNotInterchangeableAndNeverGrantData() {
        val (pc, phone) = incomingPair(); handshake(pc, phone)
        val before = phone.local.grants
        val incoming = phone.session.receiveConfigurationTicket()
        val authority = phone.session.receiveConfigurationAuthority(incoming)!!
        assertSame(incoming, authority.owner); assertEquals(pc.identity.deviceId, authority.peerId)
        assertEquals("f".repeat(64), authority.pairingEpoch)
        assertNull(phone.session.configurationAuthority(incoming)); assertNull(phone.session.photoReceiver())
        assertNull(phone.session.binding("c".repeat(64))); assertSame(before, phone.local.grants)
        assertThrows(PhotoFolderScopeError::class.java) { phone.session.configurationTicket() }
        phone.session.finishConfiguration(incoming)
        assertNull(phone.session.receiveConfigurationAuthority(incoming))
        pc.local = NativeLocalFileGrant(DeviceFileGrantState(4, "d".repeat(64), true, true), pc.local.owner, true)
        handshake(pc, phone)
        val source = phone.session.configurationTicket()
        assertNotNull(phone.session.configurationAuthority(source)); assertNull(phone.session.receiveConfigurationAuthority(source))
        phone.session.finishConfiguration(source); pc.session.close(); phone.session.close()
    }

    @Test fun incomingConfigurerAllowsOnlyLocalConsentTransactionAndDataStillNeedsFreshActualAck() {
        val (pc, phone) = incomingPair(); handshake(pc, phone)
        val ticket = phone.session.receiveConfigurationTicket(); val before = phone.session.receiveConfigurationAuthority(ticket)!!
        phone.local = NativeLocalFileGrant(DeviceFileGrantState(8, "c".repeat(64), false, true), phone.local.owner, true, policyReady = false)
        assertSame(before.owner, phone.session.receiveConfigurationAuthority(ticket)!!.owner)
        assertNull(phone.session.binding("e".repeat(64))); assertFalse(phone.session.needsPacket())
        phone.local = NativeLocalFileGrant(phone.local.grants, phone.local.owner, true)
        assertNull(phone.session.binding("e".repeat(64)))
        handshake(pc, phone)
        assertNotNull(phone.session.binding("e".repeat(64)))
        assertEquals(pc.session.binding("e".repeat(64), true), phone.session.binding("e".repeat(64)))
        phone.session.finishConfiguration(ticket); pc.session.close(); phone.session.close()
    }

    @Test fun incomingHandlerWithdrawalOrLookupFailureIsStickyAndOldTicketCannotRevive() {
        for (throws in listOf(false, true)) {
            var enabled = true
            val (pc, phone) = incomingPair({ if (!enabled && throws) error("native receive handlers failed") else enabled })
            handshake(pc, phone); val ticket = phone.session.receiveConfigurationTicket()
            enabled = false
            if (throws) assertThrows(IllegalStateException::class.java) { phone.session.receiveConfigurationAuthority(ticket) }
            else assertNull(phone.session.receiveConfigurationAuthority(ticket))
            enabled = true; assertNull(phone.session.receiveConfigurationAuthority(ticket))
            phone.session.finishConfiguration(ticket)
            val fresh = phone.session.receiveConfigurationTicket(); assertNotNull(phone.session.receiveConfigurationAuthority(fresh))
            phone.session.close(); assertNull(phone.session.receiveConfigurationAuthority(fresh)); phone.session.finishConfiguration(fresh)
            pc.session.close()
        }
    }

    @Test fun incomingTicketExpiresAndObservedClockRollbackRetiresItPermanently() {
        for (rollback in listOf(false, true)) {
            var now = 100L
            val (pc, phone) = incomingPair(clock = { now }); handshake(pc, phone)
            val ticket = phone.session.receiveConfigurationTicket()
            now = 200; assertNotNull(phone.session.receiveConfigurationAuthority(ticket))
            now = if (rollback) 150 else 100 + DeviceFileControl.MAX_TTL_MS
            assertNull(phone.session.receiveConfigurationAuthority(ticket))
            now = 200; assertNull(phone.session.receiveConfigurationAuthority(ticket))
            phone.session.finishConfiguration(ticket); pc.session.close(); phone.session.close()
        }
    }

    @Test fun incomingTicketCannotSurvivePcGrantTurnoverOrNativeOwnDeviceWithdrawal() {
        val (pc, phone) = incomingPair(); handshake(pc, phone)
        val ticket = phone.session.receiveConfigurationTicket()
        pc.local = NativeLocalFileGrant(DeviceFileGrantState(4, "d".repeat(64), false, false), pc.local.owner, true)
        send(pc, phone); assertNull(phone.session.receiveConfigurationAuthority(ticket))
        pc.local = NativeLocalFileGrant(DeviceFileGrantState(5, "e".repeat(64), true, false), pc.local.owner, true)
        handshake(pc, phone); assertNull(phone.session.receiveConfigurationAuthority(ticket)); phone.session.finishConfiguration(ticket)
        val fresh = phone.session.receiveConfigurationTicket(); val original = phone.peer
        phone.peer = original.copy(ownDevice = false); assertNull(phone.session.receiveConfigurationAuthority(fresh))
        phone.peer = original; assertNull(phone.session.receiveConfigurationAuthority(fresh))
        phone.session.finishConfiguration(fresh); pc.session.close(); phone.session.close()
    }

    @Test fun revocationDoesNotWaitForNativeLookupAndExactTicketCleanupStillCannotRestoreAuthority() {
        val (first, second) = pair()
        val entered = java.util.concurrent.CountDownLatch(1); val release = java.util.concurrent.CountDownLatch(1)
        val closeReturned = java.util.concurrent.CountDownLatch(1); val ended = java.util.concurrent.CountDownLatch(1)
        val blocking = java.util.concurrent.atomic.AtomicBoolean(false); val blocked = java.util.concurrent.atomic.AtomicBoolean(false)
        val reads = java.util.concurrent.atomic.AtomicInteger(); val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
        val observed = java.util.concurrent.atomic.AtomicReference<NativePhotoReceiver?>()
        val session = NativeFileControlSession(first.identity, { first.peer }, {
            reads.incrementAndGet()
            if (blocking.get()) { entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS)) }
            first.local
        })
        first.session = session; handshake(first, second)
        val ticket = session.configurationTicket()
        blocking.set(true)
        val reader = Thread {
            try { observed.set(session.photoReceiver()) } catch (error: Throwable) { failure.set(error) }
            finally { ended.countDown() }
        }
        var guard: Thread? = null
        try {
            reader.start(); assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
            guard = Thread {
                try { blocked.set(!closeReturned.await(500, java.util.concurrent.TimeUnit.MILLISECONDS)) }
                finally { release.countDown() }
            }.also { it.start() }
            session.close(); closeReturned.countDown()
            assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); reader.join(5000); guard.join(5000)
            assertFalse("Revocation waited behind the native permission lookup", blocked.get())
            assertNull(failure.get()); assertNull(observed.get())
            val before = reads.get()
            assertNull(session.photoReceiver()); assertNull(session.configurationAuthority(ticket)); assertFalse(session.needsPacket())
            assertThrows(PhotoFolderScopeError::class.java) { session.packet() }
            session.finishConfiguration(ticket)
            assertThrows(PhotoFolderScopeError::class.java) { session.finishConfiguration(ticket) }
            assertEquals(before, reads.get()) // Closed authority never reopens metadata/key readers.
        } finally {
            release.countDown(); closeReturned.countDown()
            assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); reader.join(5000); guard?.join(5000); session.close()
        }
    }

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

    @Test fun pendingNativePolicyPausesDataAndPacketsWithoutChangingConfirmedConsent() {
        val (first, second) = pair(); handshake(first, second)
        val before = first.session.photoReceiver()!!
        first.local = NativeLocalFileGrant(first.local.grants, first.local.owner, true, policyReady = false)
        assertNull(first.session.photoReceiver()); assertFalse(first.session.needsPacket())
        assertThrows(PhotoFolderScopeError::class.java) { first.session.packet() }
        first.local = NativeLocalFileGrant(first.local.grants, first.local.owner, true, policyReady = true)
        assertEquals(before.permissionEpoch, first.session.photoReceiver()!!.permissionEpoch)
    }

    @Test fun freshMetadataTicketCanBootstrapSourcePolicyWithoutInventingFileSendOrOsRead() {
        val (first, second) = pair()
        first.local = NativeLocalFileGrant(DeviceFileGrantState(3, "a".repeat(64), false, false), first.local.owner, true)
        first.session.close(); first.session = first.newSession() // Capture OFF as the initial native policy, not an illegal same-revision mutation.
        handshake(first, second)
        assertNull(first.session.photoReceiver())
        val ticket = first.session.configurationTicket()
        assertThrows(PhotoFolderScopeError::class.java) { first.session.configurationTicket() }
        val authority = first.session.configurationAuthority(ticket)!!
        assertTrue(authority.allowed); assertSame(ticket, authority.owner)
        assertNull(first.session.photoReceiver())
        first.local = NativeLocalFileGrant(first.local.grants, first.local.owner, true, policyReady = false)
        assertNotNull(first.session.configurationAuthority(ticket)); assertNull(first.session.photoReceiver())
        first.local = NativeLocalFileGrant(DeviceFileGrantState(4, "c".repeat(64), true, false), first.local.owner, true)
        assertNotNull(first.session.configurationAuthority(ticket)); assertNull(first.session.photoReceiver())
        first.session.finishConfiguration(ticket)
        assertNull(first.session.configurationAuthority(ticket))
        assertThrows(PhotoFolderScopeError::class.java) { first.session.finishConfiguration(ticket) }
        send(first, second); send(second, first)
        assertTrue(first.session.photoReceiver()!!.allowed)
    }

    @Test fun configurationTicketsAreNativeOneShotBoundAndExpiryCannotBeRewound() {
        val (first, second) = pair(); var now = 100L
        first.session = NativeFileControlSession(first.identity, { first.peer }, { first.local }, { now })
        handshake(first, second)
        val ticket = first.session.configurationTicket()
        assertNull(first.session.configurationAuthority(NativeFileConfigurationTicket()))
        assertNotNull(first.session.configurationAuthority(ticket))
        now += DeviceFileControl.MAX_TTL_MS
        assertNull(first.session.configurationAuthority(ticket))
        now = 100L
        assertNull(first.session.configurationAuthority(ticket))
        first.session.finishConfiguration(ticket)
        val fresh = first.session.configurationTicket()
        second.local = NativeLocalFileGrant(DeviceFileGrantState(8, "d".repeat(64), false, false), second.local.owner, true)
        send(second, first)
        assertNull(first.session.configurationAuthority(fresh))
        first.session.finishConfiguration(fresh)
    }
}
