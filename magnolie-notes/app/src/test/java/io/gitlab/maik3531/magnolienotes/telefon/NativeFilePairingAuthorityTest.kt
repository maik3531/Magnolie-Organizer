package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class NativeFilePairingAuthorityTest {
    private val json = Json { encodeDefaults = true; ignoreUnknownKeys = false }
    private fun peer(epoch: String = "") = TelefonPeer("receiver_fixture_01", "Fixture desktop",
        TelefonKrypto.b64(ByteArray(32) { 7 }), own_device = true, remote_own_device = true, file_pairing_epoch = epoch)

    @Test fun legacyPeerDecodeAndOrdinaryCopiesDoNotInventAFileRelationshipEpoch() {
        val legacy = JsonObject(json.encodeToJsonElement(TelefonPeer.serializer(), peer()).jsonObject - "file_pairing_epoch")
        val decoded = json.decodeFromJsonElement(TelefonPeer.serializer(), legacy)
        assertEquals("", decoded.file_pairing_epoch)
        assertNull(NativeFilePairingAuthority.currentEpoch(decoded))
        assertNull(NativeFilePairingAuthority.currentEpoch(decoded.copy(last_contact_ms = 1000, personal_notes_sync_granted = true)))
    }

    @Test fun freshConfirmedPairingDiffersEvenWhenDeviceIdAndPublicKeyAreIdentical() {
        val first = NativeFilePairingAuthority.epochForConfirmedTranscript(TelefonKrypto.b64(ByteArray(32) { 1 }))
        val second = NativeFilePairingAuthority.epochForConfirmedTranscript(TelefonKrypto.b64(ByteArray(32) { 2 }))
        assertNotEquals(first, second)
        val original = peer(first)
        val rePaired = peer(second)
        assertEquals(original.device_id, rePaired.device_id); assertEquals(original.static_public, rePaired.static_public)
        assertNotEquals(NativeFilePairingAuthority.currentEpoch(original), NativeFilePairingAuthority.currentEpoch(rePaired))
        val restored = json.decodeFromString(TelefonPeer.serializer(), json.encodeToString(TelefonPeer.serializer(), original))
        assertEquals(first, NativeFilePairingAuthority.currentEpoch(restored.copy(last_contact_ms = 3000)))
    }

    @Test fun unfinishedOrRevokedNativeRelationshipIsNotFileAuthority() {
        val epoch = NativeFilePairingAuthority.epochForConfirmedTranscript(TelefonKrypto.b64(ByteArray(32) { 3 }))
        val saved = peer(epoch)
        for (value in listOf(saved.copy(state = "paired_unverified"), saved.copy(own_device = false), saved.copy(remote_own_device = false)))
            assertNull(NativeFilePairingAuthority.currentEpoch(value))
        assertNull(NativeFilePairingAuthority.currentEpoch(null))
        assertThrows(IllegalArgumentException::class.java) { peer("device name") }
        assertThrows(TelefonProtokollFehler::class.java) {
            NativeFilePairingAuthority.epochForConfirmedTranscript(TelefonKrypto.b64(ByteArray(31)))
        }
    }
}
