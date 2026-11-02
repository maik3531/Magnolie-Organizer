package io.gitlab.maik3531.magnolienotes.telefon

import android.content.Context
import android.app.Application
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.security.Provider
import java.security.Security
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class NativeFilePairingBootstrapTest {
    private val provider = object : Provider("FilePairingBootstrapFixture", 1.0, "Synthetic keys only") {
        init { put("KeyStore.AndroidKeyStore", InvitationTestKeyStore::class.java.name) }
    }
    private lateinit var storage: TelefonAblage
    private fun instance() = TelefonAblage::class.java.getDeclaredField("instance").also { it.isAccessible = true }
    @Before fun setup() {
        Security.insertProviderAt(provider, 1)
        instance().set(null, null)
        val app = ApplicationProvider.getApplicationContext<Context>()
        storage = TelefonAblage.get(app)
        storage.identity("Synthetic file pairing phone").second.fill(0)
        storage.savePeer(TelefonPeer("receiver_fixture_01", "Fixture desktop", TelefonKrypto.b64(ByteArray(32) { 7 }),
            own_device = true, remote_own_device = true, remote_device_status_available = true,
            remote_device_status_versions = listOf(1, DeviceFileControl.DISCOVERY_VERSION)))
    }
    @After fun cleanup() { instance().set(null, null); Security.removeProvider(provider.name) }

    private fun field(type: Class<*>, name: String) = type.getDeclaredField(name).also { it.isAccessible = true }
    private fun withNativeTransport(action: (TelefonWerk, TelefonSecureChannel, Long) -> Unit) {
        field(TelefonWerk::class.java, "instance").set(null, null)
        val work = TelefonWerk.get(ApplicationProvider.getApplicationContext())
        val bytes = ByteArrayOutputStream()
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = bytes
            override fun close() = Unit
        }
        val channel = TelefonSecureChannel(pipe.input, bytes, ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4))
        try {
            storage.setEnabled(true)
            field(TelefonWerk::class.java, "serviceRunning").setBoolean(work, true)
            (field(TelefonWerk::class.java, "connecting").get(work) as java.util.concurrent.atomic.AtomicBoolean).set(true)
            field(TelefonWerk::class.java, "activeChannel").set(work, channel)
            field(TelefonWerk::class.java, "activeTransport").set(work, TelefonTransportArt.WIFI to pipe)
            action(work, channel, field(TelefonWerk::class.java, "pairingGeneration").getLong(work))
        } finally {
            work.serviceStopped()
            val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
            (field(TelefonQueue::class.java, "helper").get(queue) as TelefonDatenbank).close()
            field(TelefonWerk::class.java, "instance").set(null, null)
            channel.close()
        }
    }

    @Test fun explicitProtectedBootstrapIsIdempotentAndPreservesAllOtherPeerPreferences() {
        val legacy = storage.peers().peer!!
        assertEquals("", legacy.file_pairing_epoch)
        assertEquals(legacy, storage.peers().peer)
        val saved = storage.initializeFilePairingEpoch(legacy) { true }
        assertTrue(DeviceFileControl.hash(saved.file_pairing_epoch))
        assertEquals(legacy, saved.copy(file_pairing_epoch = ""))
        assertEquals(saved, storage.peers().peer)
        assertEquals(saved, storage.initializeFilePairingEpoch(saved) { true })
        assertFalse(saved.personal_notes_sync_granted)
        assertFalse(saved.contacts_read_enabled)
    }

    @Test fun staleOrDeniedActivationCannotOverwriteTheCurrentProtectedPeer() {
        val legacy = storage.peers().peer!!
        assertThrows(PhotoFolderScopeError::class.java) { storage.initializeFilePairingEpoch(legacy) { false } }
        assertEquals(legacy, storage.peers().peer)
        val updated = legacy.copy(display_name = "User preference change")
        storage.savePeer(updated)
        assertThrows(PhotoFolderScopeError::class.java) { storage.initializeFilePairingEpoch(legacy) { true } }
        assertEquals(updated, storage.peers().peer)
    }

    @Test fun reentrantNativeAuthorizationChangeIsDetectedWithoutRestoringAnOldSnapshot() {
        val legacy = storage.peers().peer!!
        val updated = legacy.copy(display_name = "Keep concurrent preference")
        assertThrows(PhotoFolderScopeError::class.java) {
            storage.initializeFilePairingEpoch(legacy) { storage.savePeer(updated); true }
        }
        assertEquals(updated, storage.peers().peer)
        assertEquals("", storage.peers().peer!!.file_pairing_epoch)
    }

    @Test fun lostPostcommitAuthorityKeepsOnlyProtectedRelationshipMetadataNotImplicitFileGrants() {
        val legacy = storage.peers().peer!!
        var calls = 0
        assertThrows(PhotoFolderScopeError::class.java) { storage.initializeFilePairingEpoch(legacy) { ++calls < 3 } }
        val held = storage.peers().peer!!
        assertTrue(DeviceFileControl.hash(held.file_pairing_epoch))
        assertEquals(legacy, held.copy(file_pairing_epoch = ""))
        assertEquals(held, storage.initializeFilePairingEpoch(held) { true })
    }

    @Test fun actualNativeTransportGuardsLegacyBootstrapAndCurrentFilePeerWithoutPersonalModuleGrants() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.peers().peer!!
            assertNull(work.currentNativeFilePeer(legacy.device_id, legacy.static_public, channel, generation, true))
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation + 1) { true }
            }
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, TelefonKrypto.b64(ByteArray(32)), channel, generation) { true }
            }
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { false }
            }
            assertEquals(legacy, storage.peers().peer)
            val saved = work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { true }
            val native = work.currentNativeFilePeer(saved.device_id, saved.static_public, channel, generation, true)!!
            assertSame(channel, native.owner); assertEquals(saved.file_pairing_epoch, native.pairingEpoch)
            assertFalse(saved.personal_notes_sync_granted); assertFalse(saved.contacts_read_enabled)
            field(TelefonWerk::class.java, "activeChannel").set(work, null)
            assertNull(work.currentNativeFilePeer(saved.device_id, saved.static_public, channel, generation, true))
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(saved.device_id, saved.static_public, channel, generation) { true }
            }
            assertEquals(saved, storage.peers().peer)
        }
    }

    @Test fun stoppingNativeHandlersDuringBootstrapIsRecheckedBeforeProtectedPeerWrite() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.peers().peer!!
            var calls = 0
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { ++calls < 3 }
            }
            assertEquals(3, calls)
            assertEquals(legacy, storage.peers().peer)
        }
    }
}
