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
import kotlinx.serialization.json.*

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
    private fun withNativeTransport(output: java.io.OutputStream? = null, action: (TelefonWerk, TelefonSecureChannel, Long) -> Unit) {
        field(TelefonWerk::class.java, "instance").set(null, null)
        val work = TelefonWerk.get(ApplicationProvider.getApplicationContext())
        val bytes = output ?: ByteArrayOutputStream()
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

    @Test fun nativeFileDiscoveryIsReadinessMetadataAndNeverPairingSourceOrOsReadConsent() {
        assertFalse(DeviceFileControl.DISCOVERY_VERSION in TelefonCapabilities.phase1().getValue("device_status").versions)
        assertTrue(DeviceFileControl.DISCOVERY_VERSION in TelefonCapabilities.phase1(fileHandlersReady = true).getValue("device_status").versions)
        withNativeTransport { work, channel, generation ->
            val original = storage.fileAuthorityPeers().peer!!
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, false)
            assertFalse(DeviceFileControl.DISCOVERY_VERSION in work.sharedLocalCapabilities().getValue("device_status").versions)
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            assertTrue(DeviceFileControl.DISCOVERY_VERSION in work.sharedLocalCapabilities().getValue("device_status").versions)
            assertEquals(original, storage.fileAuthorityPeers().peer)
            assertNull(work.currentNativeFilePeer(original.device_id, original.static_public, channel, generation, true))
            assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
        }
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

    @Test fun freshOwnPcWithdrawalMustCloseFileAuthorityDespiteLegacyPersonalNormalization() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.fileAuthorityPeers().peer!!
            val peer = work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { true }
            assertNotNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            val message = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                put("format", 1); put("own_device", false)
            }, 60_000)
            work.receiveMessage(peer, message, channel, generation)
            val queue = field(TelefonWerk::class.java, "queue").get(work) as TelefonQueue
            assertTrue(queue.receivedMatches(peer.device_id, message))
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            assertThrows(PhotoFolderScopeError::class.java) {
                work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            }
        }
    }

    @Test fun oldPositiveOwnReceiptCannotUndoNewerWithdrawalOrChangePhoneMetadata() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.fileAuthorityPeers().peer!!
            val peer = work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { true }
            fun decision(own: Boolean) = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                put("format", 1); put("own_device", own)
            }, 60_000)
            val positive = decision(true)
            work.receiveMessage(peer, positive, channel, generation)
            work.receiveMessage(peer, positive, channel, generation) // Current exact duplicate is harmless.
            assertNotNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            val withdrawal = decision(false)
            work.receiveMessage(peer, withdrawal, channel, generation)
            work.receiveMessage(peer, positive, channel, generation) // Valid but superseded receipt.
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            val altered = JsonObject(withdrawal + ("body" to buildJsonObject { put("format", 1); put("own_device", true) }))
            work.receiveMessage(peer, altered, channel, generation)
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            assertEquals(peer, storage.fileAuthorityPeers().peer)
            work.receiveMessage(peer, decision(true), channel, generation) // New, actually acknowledged decision.
            assertNotNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            assertEquals(peer, storage.fileAuthorityPeers().peer)
        }
    }

    @Test fun failedOwnAckCannotRestoreConsentAndWithdrawalDoesNotWaitForOutputRecovery() {
        val bytes = object : java.io.OutputStream() {
            var fail = false
            val saved = ByteArrayOutputStream()
            override fun write(value: Int) { if (fail) throw java.io.IOException("Fixture secure ACK failed"); saved.write(value) }
        }
        withNativeTransport(bytes) { work, channel, generation ->
            val legacy = storage.fileAuthorityPeers().peer!!
            val peer = work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { true }
            fun decision(own: Boolean) = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                put("format", 1); put("own_device", own)
            }, 60_000)
            bytes.fail = true
            assertThrows(java.io.IOException::class.java) { work.receiveMessage(peer, decision(false), channel, generation) }
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            assertThrows(java.io.IOException::class.java) { work.receiveMessage(peer, decision(true), channel, generation) }
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            bytes.fail = false
            work.receiveMessage(peer, decision(true), channel, generation)
            assertNotNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            assertEquals(peer, storage.fileAuthorityPeers().peer)
        }
    }

    @Test fun expiredOrReplacedChannelOwnDecisionsCannotRestoreRevokedFileAuthority() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.fileAuthorityPeers().peer!!
            val peer = work.prepareNativeFileRelationshipForExplicitActivation(legacy.device_id, legacy.static_public, channel, generation) { true }
            val withdrawal = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                put("format", 1); put("own_device", false)
            }, 60_000)
            work.receiveMessage(peer, withdrawal, channel, generation)
            val expired = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                put("format", 1); put("own_device", true)
            }, 60_000, System.currentTimeMillis() - 120_000)
            work.receiveMessage(peer, expired, channel, generation)
            assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
            val replacement = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), ByteArrayOutputStream(),
                ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4))
            try {
                field(TelefonWerk::class.java, "activeChannel").set(work, replacement)
                val positive = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                    put("format", 1); put("own_device", true)
                }, 60_000)
                work.receiveMessage(peer, positive, channel, generation)
                assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
                field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                assertNull(work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true))
                assertEquals(peer, storage.fileAuthorityPeers().peer)
            } finally {
                field(TelefonWerk::class.java, "activeChannel").set(work, channel)
                replacement.close()
            }
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

    @Test fun nativeFileIdentityLookupUsesOnlyTheExactAuthenticatedChannelCacheWithoutCreatingIdentity() {
        withNativeTransport { work, channel, generation ->
            val peer = storage.fileAuthorityPeers().peer!!
            val identity = field(TelefonAblage::class.java, "identityFile").get(storage) as java.io.File
            val held = java.io.File(identity.parentFile, identity.name + ".file-test-held")
            java.nio.file.Files.move(identity.toPath(), held.toPath())
            try {
                assertNull(work.currentNativeFileIdentity(peer.device_id, peer.static_public, channel, generation))
                assertFalse(identity.exists())
                @Suppress("UNCHECKED_CAST")
                val cache = field(TelefonWerk::class.java, "fileChannelIdentities").get(work) as MutableMap<TelefonSecureChannel, NativeFileControlIdentity>
                val captured = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
                cache[channel] = captured
                assertSame(captured, work.currentNativeFileIdentity(peer.device_id, peer.static_public, channel, generation))
                assertNull(work.currentNativeFileIdentity(peer.device_id, peer.static_public, channel, generation + 1))
                field(TelefonWerk::class.java, "activeChannel").set(work, null)
                assertNull(work.currentNativeFileIdentity(peer.device_id, peer.static_public, channel, generation))
                assertFalse(identity.exists())
            } finally { java.nio.file.Files.move(held.toPath(), identity.toPath()) }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun captureFileIdentity(work: TelefonWerk, channel: TelefonSecureChannel) {
        val cache = field(TelefonWerk::class.java, "fileChannelIdentities").get(work) as MutableMap<TelefonSecureChannel, NativeFileControlIdentity>
        cache[channel] = NativeFileControlIdentity("sender_fixture_01", "d".repeat(64))
    }

    private fun activationControl(receive: Boolean = true) = DeviceFileControlEnvelope.create(
        DeviceFileControlPacket(DeviceFileGrantState(1, "c".repeat(64), false, receive), "e".repeat(64), 1, null))

    @Test fun actualFirstReceiverControlBootstrapsOnlyClosedGalleryRuntimeWithoutNotesOrReadGrants() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            val legacy = storage.fileAuthorityPeers().peer!!
            val message = activationControl()
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, false)
            assertThrows(PhotoFolderScopeError::class.java) { work.receiveMessage(legacy, message, channel, generation) }
            assertEquals(legacy, storage.fileAuthorityPeers().peer) // Incomplete native handlers cannot activate.
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            work.receiveMessage(legacy, message, channel, generation)
            val connection = field(TelefonWerk::class.java, "galleryFileConnection").get(work) as NativeGalleryFileConnection
            try {
                val saved = storage.fileAuthorityPeers().peer!!
                assertTrue(DeviceFileControl.hash(saved.file_pairing_epoch))
                assertEquals(legacy, saved.copy(file_pairing_epoch = ""))
                assertNull(connection.runtime.savedPolicy().policy)
                assertNull(connection.runtime.currentRequest())
                assertFalse(saved.personal_notes_sync_granted)
                val bytes = field(TelefonSecureChannel::class.java, "output").get(channel) as ByteArrayOutputStream
                val frame = TelefonRahmen.lesen(ByteArrayInputStream(bytes.toByteArray()))
                val header = JsonObject(frame - "ciphertext")
                val clear = TelefonKrypto.entschluesseln(ByteArray(32), TelefonKrypto.nonce(ByteArray(4), header.long("seq")),
                    java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                val packet = DeviceFileControlEnvelope.validate(Json.parseToJsonElement(clear.decodeToString()).jsonObject)
                assertFalse(packet.grants.sendFiles); assertFalse(packet.grants.receiveFiles)
                val withdrawal = TelefonNachrichten.message("personal_sync.settings", buildJsonObject {
                    put("format", 1); put("own_device", false)
                }, 60_000)
                work.receiveMessage(saved, withdrawal, channel, generation)
                assertNull(work.currentNativeFilePeer(saved.device_id, saved.static_public, channel, generation, true))
                assertThrows(PhotoFolderScopeError::class.java) { connection.runtime.sendControls() }
                assertThrows(PhotoFolderScopeError::class.java) { work.receiveMessage(saved, message, channel, generation) }
                assertEquals(saved, storage.fileAuthorityPeers().peer)
            } finally { connection.close() }
        }
    }

    @Test fun firstFileMessageCannotBootstrapFromStatusMalformedControlNoReceiveConsentOrMissingNativeIdentity() {
        withNativeTransport { work, channel, generation ->
            val legacy = storage.fileAuthorityPeers().peer!!
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val status = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", "status")
            }, 60_000)
            for (message in listOf(status, activationControl(false),
                JsonObject(activationControl() + ("body" to buildJsonObject { put("format", 1) })), activationControl())) {
                assertThrows(PhotoFolderScopeError::class.java) { work.receiveMessage(legacy, message, channel, generation) }
                assertEquals(legacy, storage.fileAuthorityPeers().peer)
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            }
            val bytes = field(TelefonSecureChannel::class.java, "output").get(channel) as ByteArrayOutputStream
            assertEquals(0, bytes.size())
        }
    }

    private fun awaitUiFactory(worker: Thread) {
        val deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(2)
        while (worker.state != Thread.State.TIMED_WAITING && worker.isAlive && System.nanoTime() < deadline) Thread.sleep(1)
        assertEquals(Thread.State.TIMED_WAITING, worker.state)
    }

    @Test @org.robolectric.annotation.LooperMode(org.robolectric.annotation.LooperMode.Mode.PAUSED)
    fun canceledQueuedActivationCannotInitializeLegacyMetadataOrOpenLateRuntime() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val legacy = storage.fileAuthorityPeers().peer!!
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val worker = Thread {
                try { work.receiveMessage(legacy, activationControl(), channel, generation) }
                catch (error: Throwable) { failure.set(error) }
            }
            try {
                worker.start(); awaitUiFactory(worker); worker.interrupt(); worker.join(5000)
                assertFalse(worker.isAlive); assertNotNull(failure.get())
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertEquals(legacy, storage.fileAuthorityPeers().peer)
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            } finally { worker.interrupt(); worker.join(5000) }
        }
    }

    @Test @org.robolectric.annotation.LooperMode(org.robolectric.annotation.LooperMode.Mode.PAUSED)
    fun queuedActivationRechecksExactNativeChannelBeforeAnyProtectedBootstrap() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val legacy = storage.fileAuthorityPeers().peer!!
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val worker = Thread {
                try { work.receiveMessage(legacy, activationControl(), channel, generation) }
                catch (error: Throwable) { failure.set(error) }
            }
            try {
                worker.start(); awaitUiFactory(worker)
                field(TelefonWerk::class.java, "activeChannel").set(work, null)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                worker.join(5000); assertFalse(worker.isAlive)
                assertTrue(failure.get() is PhotoFolderScopeError)
                assertEquals(legacy, storage.fileAuthorityPeers().peer)
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            } finally { worker.interrupt(); worker.join(5000) }
        }
    }

    @Test @org.robolectric.annotation.LooperMode(org.robolectric.annotation.LooperMode.Mode.PAUSED)
    fun actualSocketLaneWaitsForUiFactoryThenWritesOnlyEncryptedClosedControlsOffUiAndOutsideWerkMonitor() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val legacy = storage.fileAuthorityPeers().peer!!
            val uiThread = Thread.currentThread()
            val bytes = field(TelefonSecureChannel::class.java, "output").get(channel) as ByteArrayOutputStream
            val writes = java.util.concurrent.atomic.AtomicInteger()
            val checked = object : java.io.OutputStream() {
                override fun write(value: Int) {
                    assertNotSame(uiThread, Thread.currentThread())
                    assertFalse(Thread.holdsLock(work))
                    writes.incrementAndGet(); bytes.write(value)
                }
            }
            field(TelefonSecureChannel::class.java, "output").set(channel, checked)
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val worker = Thread {
                try { work.receiveMessage(legacy, activationControl(), channel, generation) }
                catch (error: Throwable) { failure.set(error) }
            }
            try {
                worker.start(); awaitUiFactory(worker)
                assertEquals(0, writes.get())
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                worker.join(5000); assertFalse(worker.isAlive); assertNull(failure.get())
                assertTrue(writes.get() > 0)
                val connection = field(TelefonWerk::class.java, "galleryFileConnection").get(work) as NativeGalleryFileConnection
                assertNull(connection.runtime.savedPolicy().policy); assertNull(connection.runtime.currentRequest())
                connection.close()
            } finally { worker.interrupt(); worker.join(5000) }
        }
    }

    @Test @org.robolectric.annotation.LooperMode(org.robolectric.annotation.LooperMode.Mode.PAUSED)
    fun queuedActivationRechecksHandlerReadinessBeforeAnyProtectedBootstrap() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val legacy = storage.fileAuthorityPeers().peer!!
            val failure = java.util.concurrent.atomic.AtomicReference<Throwable?>()
            val worker = Thread {
                try { work.receiveMessage(legacy, activationControl(), channel, generation) }
                catch (error: Throwable) { failure.set(error) }
            }
            try {
                worker.start(); awaitUiFactory(worker)
                field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, false)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                worker.join(5000); assertFalse(worker.isAlive)
                assertTrue(failure.get() is PhotoFolderScopeError)
                assertEquals(legacy, storage.fileAuthorityPeers().peer)
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            } finally { worker.interrupt(); worker.join(5000) }
        }
    }

    @Test fun nativeFactoryUsesCapturedIdentityExistingKeyAndRetainsOwnershipUntilActualUiClose() {
        withNativeTransport { work, channel, generation ->
            var peer = storage.fileAuthorityPeers().peer!!
            assertThrows(PhotoFolderScopeError::class.java) {
                work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }
            }
            captureFileIdentity(work, channel)
            peer = work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            val identityFile = field(TelefonAblage::class.java, "identityFile").get(storage) as java.io.File
            val held = java.io.File(identityFile.parentFile, identityFile.name + ".factory-test-held")
            java.nio.file.Files.move(identityFile.toPath(), held.toPath())
            var opened: NativeGalleryFileConnection? = null
            try {
                val connection = work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }
                opened = connection
                assertNull(connection.runtime.savedPolicy().policy)
                assertNull(connection.runtime.currentRequest())
                assertFalse(identityFile.exists())
                assertTrue(connection.runtime.sendControls()) // Actual encrypted frame write, still initial OFF.
                assertThrows(PhotoFolderScopeError::class.java) {
                    work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }
                }
                val unrelated = TelefonSecureChannel(ByteArrayInputStream(byteArrayOf()), ByteArrayOutputStream(),
                    ByteArray(16), ByteArray(32), ByteArray(4), ByteArray(32), ByteArray(4))
                try { work.nativeGalleryFileTransportEnded(unrelated) } finally { unrelated.close() }
                assertFalse(connection.isEnded)
                field(TelefonWerk::class.java, "activeChannel").set(work, null)
                val ended = java.util.concurrent.CountDownLatch(1)
                val failed = java.util.concurrent.atomic.AtomicReference<Throwable?>()
                val worker = Thread {
                    try { work.nativeGalleryFileTransportEnded(channel) } catch (error: Throwable) { failed.set(error) }
                    finally { ended.countDown() }
                }
                worker.start(); assertTrue(ended.await(5, java.util.concurrent.TimeUnit.SECONDS)); worker.join(5000)
                assertNull(failed.get()); assertTrue(connection.isEnded)
                assertThrows(PhotoFolderScopeError::class.java) { connection.runtime }
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                assertFalse(identityFile.exists())
            } finally {
                opened?.close()
                java.nio.file.Files.move(held.toPath(), identityFile.toPath())
            }
        }
    }

    @Test fun nativeFactoryRejectsDisabledHandlersAndCanReopenPreservedMetadataOnlyAfterClose() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            val peer = storage.fileAuthorityPeers().peer!!
            work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            assertThrows(PhotoFolderScopeError::class.java) {
                work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { false }
            }
            assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }.use { first ->
                assertNull(first.runtime.savedPolicy().policy)
            }
            work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }.use { reopened ->
                assertNull(reopened.runtime.savedPolicy().policy)
                assertNull(reopened.runtime.currentRequest())
            }
        }
    }

    @Test fun actualFactoryKeepsVideoOffByDefaultAndCannotUpgradeAnImageOnlyPeerFromLocalReadiness() {
        withNativeTransport { work, channel, generation ->
            // Exercise a genuinely incomplete native installation explicitly;
            // the shipped source handlers are now compiled and available.
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, false)
            field(TelefonWerk::class.java, "nativeGalleryVideoHandlersReady").setBoolean(work, false)
            assertFalse(work.sharedLocalCapabilities().getValue("device_status").versions.contains(DeviceFileControl.VIDEO_DISCOVERY_VERSION))
            assertFalse(field(TelefonWerk::class.java, "nativeGalleryVideoHandlersReady").getBoolean(work))
            captureFileIdentity(work, channel)
            val peer = storage.fileAuthorityPeers().peer!!
            work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }.use { connection ->
                val before = connection.runtime.savedPolicy()
                val command = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                    put("format", 1); put("operation", "configure_videos"); put("expected_version", before.version); put("enabled", true)
                }, 60_000, System.currentTimeMillis())
                var writes = 0
                assertEquals("gallery_video_wire_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) {
                    connection.runtime.receiveSourceCommand(command, { writes++ })
                }.code)
                field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
                field(TelefonWerk::class.java, "nativeGalleryVideoHandlersReady").setBoolean(work, true)
                assertTrue(work.sharedLocalCapabilities().getValue("device_status").versions.contains(DeviceFileControl.VIDEO_DISCOVERY_VERSION))
                assertEquals("gallery_video_wire_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) {
                    connection.runtime.receiveSourceCommand(command, { writes++ })
                }.code)
                assertEquals(0, writes); assertEquals(before, connection.runtime.savedPolicy())
                assertNull(connection.runtime.currentRequest(GalleryMediaType.VIDEO))
            }
        }
    }

    @Test fun shippedNativeSourceHandlersAdvertiseAvailabilityWithoutEnablingPhotoOrVideoPolicy() {
        withNativeTransport { work, channel, generation ->
            val versions = work.sharedLocalCapabilities().getValue("device_status").versions
            assertTrue(versions.contains(DeviceFileControl.DISCOVERY_VERSION))
            assertTrue(versions.contains(DeviceFileControl.VIDEO_DISCOVERY_VERSION))
            captureFileIdentity(work, channel)
            val peer = storage.fileAuthorityPeers().peer!!
            work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }.use { connection ->
                assertNull(connection.runtime.savedPolicy().policy)
                assertNull(connection.runtime.currentRequest())
                assertNull(connection.runtime.currentRequest(GalleryMediaType.VIDEO))
            }
        }
    }

    @Test fun actualMessageDispatcherKeepsFileStatusAndConfigurationOutOfPersonalStagingAndOsRead() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            var peer = storage.fileAuthorityPeers().peer!!
            peer = work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            val native = work.currentNativeFilePeer(peer.device_id, peer.static_public, channel, generation, true)!!
            val desktopPeer = NativeFileControlPeer("sender_fixture_01", "d".repeat(64), Any(), true, true, true, true, true, native.pairingEpoch)
            val desktopState = NativeLocalFileGrant(DeviceFileGrantState(1, "b".repeat(64), false, true), Any(), true)
            var desktop = NativeFileControlSession(NativeFileControlIdentity(peer.device_id, native.identitySha256), { desktopPeer }, { desktopState })
            val bytes = field(TelefonSecureChannel::class.java, "output").get(channel) as ByteArrayOutputStream
            fun sent(): List<JsonObject> {
                val input = ByteArrayInputStream(bytes.toByteArray()); bytes.reset()
                val result = mutableListOf<JsonObject>()
                while (input.available() > 0) {
                    val frame = TelefonRahmen.lesen(input)
                    val header = JsonObject(frame - "ciphertext")
                    val encrypted = java.util.Base64.getDecoder().decode(frame.string("ciphertext"))
                    val clear = TelefonKrypto.entschluesseln(ByteArray(32), TelefonKrypto.nonce(ByteArray(4), header.long("seq")),
                        encrypted, TelefonKanonisch.bytes(header))
                    result += Json.parseToJsonElement(clear.decodeToString()).jsonObject
                }
                return result
            }
            fun command(operation: String, version: String? = null) = TelefonNachrichten.message(DeviceFileSourceCommand.REQUEST, buildJsonObject {
                put("format", 1); put("operation", operation)
                if (version != null) {
                    put("expected_version", version)
                    if (operation == "configure") { put("enabled", true); put("kinds", JsonArray(listOf(JsonPrimitive("camera")))) }
                }
            }, 60_000)
            val initial = command("status")
            assertThrows(PhotoFolderScopeError::class.java) { work.receiveMessage(peer, initial, channel, generation) }
            assertEquals(0, bytes.size()) // No fallback to ordinary personal staging/ACK.
            field(TelefonWerk::class.java, "nativeGalleryHandlersReady").setBoolean(work, true)
            val activation = desktop.packet(); desktop.markSent(activation)
            work.receiveMessage(peer, DeviceFileControlEnvelope.create(activation), channel, generation)
            sent().forEach { desktop.observeRemote(DeviceFileControlEnvelope.validate(it), desktopPeer) }
            (field(TelefonWerk::class.java, "galleryFileConnection").get(work) as NativeGalleryFileConnection).use { connection ->
                assertNull(connection.runtime.savedPolicy().policy)
                fun metadata() {
                    val packet = desktop.packet(); desktop.markSent(packet)
                    work.receiveMessage(peer, DeviceFileControlEnvelope.create(packet), channel, generation)
                    sent().forEach { desktop.observeRemote(DeviceFileControlEnvelope.validate(it), desktopPeer) }
                }
                metadata(); metadata()
                work.receiveMessage(peer, command("status"), channel, generation)
                val status = sent().single()
                assertEquals(DeviceFileSourceCommand.RESULT, status.string("kind"))
                assertEquals(JsonPrimitive(false), status["body"]!!.jsonObject["enabled"])
                assertNull(connection.runtime.savedPolicy().policy)
                val version = status["body"]!!.jsonObject.string("version")
                val configure = command("configure", version)
                work.receiveMessage(peer, configure, channel, generation)
                val reply = sent()
                assertEquals(2, reply.size) // Metadata result followed by changed control grant.
                assertEquals(JsonPrimitive(true), reply.first()["body"]!!.jsonObject["associated"])
                assertEquals(JsonPrimitive(true), reply.first()["body"]!!.jsonObject["enabled"])
                desktop.observeRemote(DeviceFileControlEnvelope.validate(reply.last()), desktopPeer)
                assertNull(connection.runtime.currentRequest()) // No data authority until the new grant is echoed.
                metadata()
                assertNotNull(connection.runtime.currentRequest())
                val saved = connection.runtime.savedPolicy()
                assertThrows(PhotoFolderScopeError::class.java) { work.receiveMessage(peer, configure, channel, generation) }
                assertEquals(saved, connection.runtime.savedPolicy())
                assertEquals(0, bytes.size())
                assertFalse(storage.fileAuthorityPeers().peer!!.personal_notes_sync_granted)
                assertEquals("gallery_workflow_permission_host_missing", assertThrows(PhotoFolderScopeError::class.java) {
                    connection.runtime.requestReadPermission() }.code)
                val read = command("request_read", saved.version)
                work.receiveMessage(peer, read, channel, generation)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                awaitPermissionIo(connection)
                val permission = sent().single()
                assertEquals(DeviceFileSourceCommand.PERMISSION_RESULT, permission.string("kind"))
                assertEquals("notification_posted", permission["body"]!!.jsonObject.string("state"))
                val app = ApplicationProvider.getApplicationContext<Application>()
                assertNull(org.robolectric.Shadows.shadowOf(app).nextStartedActivity)
                val manager = app.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                val originalIntent = org.robolectric.Shadows.shadowOf(manager).allNotifications.single().contentIntent
                work.receiveMessage(peer, read, channel, generation)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                awaitPermissionIo(connection)
                assertEquals("notification_posted", sent().single()["body"]!!.jsonObject.string("state"))
                assertSame(originalIntent, org.robolectric.Shadows.shadowOf(manager).allNotifications.single().contentIntent)
                assertEquals(saved, connection.runtime.savedPolicy())
                val oldAction = GalleryPhotoPermissionIntent.token(org.robolectric.Shadows.shadowOf(originalIntent).savedIntent)!!
                connection.close(); desktop.close()
                assertFalse(NativeGalleryForeground.acceptsPermissionAction(oldAction))
                desktop = NativeFileControlSession(NativeFileControlIdentity(peer.device_id, native.identitySha256), { desktopPeer }, { desktopState })
                work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }.use { reopened ->
                    metadata(); metadata() // Fresh dedicated control epochs, same protected pairing/policy.
                    work.receiveMessage(peer, read, channel, generation)
                    org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                    awaitPermissionIo(reopened)
                    assertEquals("notification_posted", sent().single()["body"]!!.jsonObject.string("state"))
                    assertSame(originalIntent, org.robolectric.Shadows.shadowOf(manager).allNotifications.single().contentIntent)
                    assertFalse(NativeGalleryForeground.acceptsPermissionAction(oldAction))
                    val routes = field(NativeGalleryForeground::class.java, "routes").get(null) as Map<*, *>
                    assertEquals(GalleryMediaType.entries.toSet(), routes.keys)
                    routes.values.forEach { route -> assertNull(field(route!!.javaClass, "binding").get(route)) } // No media UI attempt/owner was created.
                    assertEquals(saved, reopened.runtime.savedPolicy())
                    val outputField = field(TelefonSecureChannel::class.java, "output")
                    val originalOutput = outputField.get(channel) as java.io.OutputStream
                    val writeEntered = java.util.concurrent.CountDownLatch(1); val releaseWrite = java.util.concurrent.CountDownLatch(1)
                    val uiReturned = java.util.concurrent.CountDownLatch(1); val uiBlocked = java.util.concurrent.atomic.AtomicBoolean(false)
                    val delayed = object : java.io.OutputStream() {
                        override fun write(value: Int) {
                            writeEntered.countDown(); check(releaseWrite.await(5, java.util.concurrent.TimeUnit.SECONDS)); originalOutput.write(value)
                        }
                        override fun flush() { originalOutput.flush() }
                    }
                    outputField.set(channel, delayed)
                    val guard = Thread {
                        try {
                            check(writeEntered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                            uiBlocked.set(!uiReturned.await(500, java.util.concurrent.TimeUnit.MILLISECONDS))
                        } finally { releaseWrite.countDown() }
                    }
                    try {
                        guard.start()
                        work.receiveMessage(peer, command("request_read", saved.version), channel, generation)
                        org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle(); uiReturned.countDown()
                        @Suppress("UNCHECKED_CAST")
                        val completion = field(NativeGalleryFileConnection::class.java, "permissionIoEnd").get(reopened) as
                            java.util.concurrent.atomic.AtomicReference<java.util.concurrent.CountDownLatch>
                        assertTrue(completion.get().await(5, java.util.concurrent.TimeUnit.SECONDS)); guard.join(5000)
                        assertFalse("Permission UI waited for native response frame output", uiBlocked.get())
                        assertEquals(DeviceFileSourceCommand.PERMISSION_RESULT, sent().single().string("kind"))
                    } finally {
                        uiReturned.countDown(); releaseWrite.countDown(); guard.join(5000)
                        outputField.set(channel, originalOutput)
                    }
                }
            }
            desktop.close()
        }
    }

    private fun awaitPermissionIo(connection: NativeGalleryFileConnection) {
        @Suppress("UNCHECKED_CAST")
        val completion = field(NativeGalleryFileConnection::class.java, "permissionIoEnd").get(connection) as
            java.util.concurrent.atomic.AtomicReference<java.util.concurrent.CountDownLatch>
        assertTrue(completion.get().await(5, java.util.concurrent.TimeUnit.SECONDS))
    }

    @Test fun permissionBackgroundIoRetainsTheNativeOwnerUntilActualEndAfterUiClose() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            val peer = storage.fileAuthorityPeers().peer!!
            work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            val connection = work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }
            val entered = java.util.concurrent.CountDownLatch(1)
            val release = java.util.concurrent.CountDownLatch(1)
            val calls = java.util.concurrent.atomic.AtomicInteger()
            try {
                connection.enqueuePermissionCommand({ calls.incrementAndGet() }, {
                    assertNotSame(android.os.Looper.getMainLooper(), android.os.Looper.myLooper())
                    entered.countDown(); check(release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                })
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS))
                assertEquals(1, calls.get())
                assertThrows(PhotoFolderScopeError::class.java) { connection.enqueuePermissionCommand { calls.incrementAndGet() } }
                connection.close()
                assertSame(connection, field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                assertThrows(PhotoFolderScopeError::class.java) { connection.runtime }
                release.countDown(); awaitPermissionIo(connection)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
                assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
                assertEquals(1, calls.get())
            } finally {
                release.countDown(); awaitPermissionIo(connection)
                org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle(); connection.close()
            }
        }
    }

    @Test fun queuedNativePermissionWorkIsBoundedAndCannotRunAfterItsConnectionCloses() {
        withNativeTransport { work, channel, generation ->
            captureFileIdentity(work, channel)
            val peer = storage.fileAuthorityPeers().peer!!
            work.prepareNativeFileRelationshipForExplicitActivation(peer.device_id, peer.static_public, channel, generation) { true }
            val connection = work.openNativeGalleryFileConnection(peer.device_id, peer.static_public, channel, generation) { true }
            var calls = 0
            connection.enqueuePermissionCommand { calls++ }
            assertThrows(PhotoFolderScopeError::class.java) { connection.enqueuePermissionCommand { calls++ } }
            connection.close()
            org.robolectric.Shadows.shadowOf(android.os.Looper.getMainLooper()).idle()
            assertEquals(0, calls)
            assertNull(field(TelefonWerk::class.java, "galleryFileConnection").get(work))
            assertThrows(PhotoFolderScopeError::class.java) { connection.enqueuePermissionCommand { calls++ } }
        }
    }
}
