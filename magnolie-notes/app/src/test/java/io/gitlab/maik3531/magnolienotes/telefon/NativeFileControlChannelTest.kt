package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream

class NativeFileControlChannelTest {
    private val now = 1_800_000_000_000L
    private val localId = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
    private val remoteId = NativeFileControlIdentity("receiver_fixture_01", "e".repeat(64))
    private val sid = ByteArray(16) { 2 }
    private val key = ByteArray(32) { 3 }
    private val prefix = ByteArray(4) { 4 }
    private fun channel(output: OutputStream) = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), output,
        sid, key.copyOf(), prefix, ByteArray(32) { 5 }, ByteArray(4) { 6 })
    private fun peer(owner: Any) = NativeFileControlPeer(remoteId.deviceId, remoteId.identitySha256, owner,
        true, true, true, true, true, "1".repeat(64))
    private fun state() = NativeLocalFileGrant(DeviceFileGrantState(3, "a".repeat(64), true, false), Any(), true)
    private fun packet() = DeviceFileControlPacket(DeviceFileGrantState(7, "b".repeat(64), false, true), "2".repeat(64), 1, null)

    @Test fun exactNativeSendCompletionFollowsActualEncryptedFrameWriteAndFreshEcho() {
        val output = ByteArrayOutputStream(); val channel = channel(output); val peer = peer(channel); val state = state()
        NativeFileControlChannel(localId, channel, { peer }, { state }).use { adapter ->
            assertNull(adapter.session.photoReceiver())
            assertTrue(adapter.sendIfNeeded(now))
            val rawFrame = TelefonRahmen.lesen(ByteArrayInputStream(output.toByteArray()))
            val header = JsonObject(rawFrame - "ciphertext")
            val encrypted = java.util.Base64.getDecoder().decode(rawFrame.string("ciphertext"))
            val clear = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, 0), encrypted, TelefonKanonisch.bytes(header))
            val sent = DeviceFileControlEnvelope.validate(Json.parseToJsonElement(clear.decodeToString()).jsonObject, now)
            assertEquals(state.grants, sent.grants)
            assertNull(adapter.session.photoReceiver())
            val reply = packet().copy(echo = sent.challenge)
            assertTrue(adapter.observe(DeviceFileControlEnvelope.create(reply, now), now))
            assertNull(adapter.session.photoReceiver()) // The echo has not actually been sent yet.
            assertTrue(adapter.sendIfNeeded(now))
            assertNotNull(adapter.session.photoReceiver())
            assertFalse(adapter.sendIfNeeded(now))
            assertFalse(adapter.observe(DeviceFileControlEnvelope.create(reply, now), now))
        }
    }

    @Test fun failedNativeFrameWriteNeverCompletesConsentOrClosesSharedTransport() {
        var writes = 0
        val output = object : OutputStream() { override fun write(value: Int) { writes++; throw IOException("native output failed") } }
        val channel = channel(output); val peer = peer(channel); val state = state()
        val adapter = NativeFileControlChannel(localId, channel, { peer }, { state })
        assertThrows(IOException::class.java) { adapter.sendIfNeeded(now) }
        assertTrue(writes > 0); assertNull(adapter.session.photoReceiver())
        assertThrows(PhotoFolderScopeError::class.java) { adapter.sendIfNeeded(now) }
        // Adapter closure does not clear the shared secure-channel keys.
        val field = TelefonSecureChannel::class.java.getDeclaredField("sendKey").also { it.isAccessible = true }
        assertArrayEquals(key, field.get(channel) as ByteArray)
        channel.close()
    }

    @Test fun nativeOwnerReplacementDuringFrameWriteCannotReleaseSendTicket() {
        var native: NativeFileControlPeer? = null
        val output = object : ByteArrayOutputStream() {
            override fun write(bytes: ByteArray, offset: Int, length: Int) {
                super.write(bytes, offset, length)
                native = native!!.copy(owner = Any())
            }
        }
        val channel = channel(output); native = peer(channel); val state = state()
        val adapter = NativeFileControlChannel(localId, channel, { native }, { state })
        assertThrows(PhotoFolderScopeError::class.java) { adapter.sendIfNeeded(now) }
        assertNull(adapter.session.photoReceiver())
    }

    @Test fun envelopeRejectsExpiryOversizeWrongKindAndBooleanHeaderAliases() {
        val valid = DeviceFileControlEnvelope.create(packet(), now)
        assertEquals(packet(), DeviceFileControlEnvelope.validate(valid, now))
        assertThrows(PhotoFolderScopeError::class.java) { DeviceFileControlEnvelope.validate(valid, now + DeviceFileControl.MAX_TTL_MS + 1) }
        for ((name, value) in listOf("kind" to JsonPrimitive("personal_sync.settings"),
            "expires_ms" to JsonPrimitive(now + DeviceFileControl.MAX_TTL_MS + 1),
            "v" to JsonPrimitive(true), "extra" to JsonPrimitive("x".repeat(9000)))) {
            assertThrows(Exception::class.java) { DeviceFileControlEnvelope.validate(JsonObject(valid + (name to value)), now) }
        }
    }
}
