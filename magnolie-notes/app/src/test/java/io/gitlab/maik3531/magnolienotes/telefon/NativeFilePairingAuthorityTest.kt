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

    @Test fun nativePeerBuilderNeedsFileDiscoveryAndHandlersNotNotesOrContactsConsent() {
        val epoch = NativeFilePairingAuthority.epochForConfirmedTranscript(TelefonKrypto.b64(ByteArray(32) { 3 }))
        val saved = peer(epoch).copy(remote_device_status_available = true,
            remote_device_status_versions = listOf(1, DeviceFileControl.DISCOVERY_VERSION), contacts_read_enabled = false,
            personal_notes_sync_granted = false, personal_tasks_sync_granted = false, device_status_granted = false)
        val owner = Any()
        val native = NativeFilePairingAuthority.controlPeer(saved, owner, true, true)!!
        assertSame(owner, native.owner); assertTrue(native.allowed); assertEquals(epoch, native.pairingEpoch)
        assertEquals(saved.device_id, native.peerId)
        assertEquals(java.security.MessageDigest.getInstance("SHA-256").digest(TelefonKrypto.b64(saved.static_public, 32))
            .joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }, native.identitySha256)
        assertNull(NativeFilePairingAuthority.controlPeer(saved, owner, false, true))
        assertNull(NativeFilePairingAuthority.controlPeer(saved, owner, true, false))
        assertNull(NativeFilePairingAuthority.controlPeer(saved.copy(remote_device_status_versions = listOf(1, 20)), owner, true, true))
        assertNull(NativeFilePairingAuthority.controlPeer(saved.copy(remote_device_status_available = false), owner, true, true))
        assertNull(NativeFilePairingAuthority.controlPeer(saved.copy(file_pairing_epoch = ""), owner, true, true))
    }

    @Test fun authenticatedLocalIdentityProjectionDoesNotNeedAStoreOrPrivateKeyAndRejectsOtherRoles() {
        val value = TelefonIdentitaet(device_id = "sender_fixture_01", display_name = "Fixture phone",
            static_public = TelefonKrypto.b64(ByteArray(32) { 7 }), wrapped_private = "No private key is read here")
        val projected = NativeFilePairingAuthority.fromAuthenticatedIdentity(value)
        assertEquals(value.device_id, projected.deviceId)
        assertEquals(java.security.MessageDigest.getInstance("SHA-256").digest(ByteArray(32) { 7 })
            .joinToString("") { "%02x".format(java.util.Locale.ROOT, it.toInt() and 255) }, projected.identitySha256)
        assertThrows(IllegalArgumentException::class.java) { NativeFilePairingAuthority.fromAuthenticatedIdentity(value.copy(role = "desktop")) }
        assertThrows(IllegalArgumentException::class.java) { NativeFilePairingAuthority.fromAuthenticatedIdentity(value.copy(storage_version = 2)) }
        assertThrows(TelefonProtokollFehler::class.java) {
            NativeFilePairingAuthority.fromAuthenticatedIdentity(value.copy(static_public = TelefonKrypto.b64(ByteArray(31))))
        }
    }

    @Test fun videoMarkerDoesNotReplaceBaseFilesOrCreateNativeTransportAuthority() {
        val saved = peer("1".repeat(64)).copy(remote_device_status_available = true,
            remote_device_status_versions = listOf(1, DeviceFileControl.DISCOVERY_VERSION, DeviceFileControl.VIDEO_DISCOVERY_VERSION))
        val owner = Any()
        val video = NativeFilePairingAuthority.controlPeer(saved, owner, true, true)!!
        assertTrue(video.videoSupported)
        val photos = NativeFilePairingAuthority.controlPeer(saved.copy(remote_device_status_versions = listOf(1, DeviceFileControl.DISCOVERY_VERSION)), owner, true, true)!!
        assertFalse(photos.videoSupported); assertEquals(video.pairingEpoch, photos.pairingEpoch); assertSame(video.owner, photos.owner)
        assertNull(NativeFilePairingAuthority.controlPeer(saved.copy(remote_device_status_versions = listOf(1, DeviceFileControl.VIDEO_DISCOVERY_VERSION)), owner, true, true))
        assertNull(NativeFilePairingAuthority.controlPeer(saved, owner, false, true))
        assertNull(NativeFilePairingAuthority.controlPeer(saved, owner, true, false))
    }
}
