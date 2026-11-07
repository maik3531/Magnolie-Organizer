package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.os.Looper
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [NativeIncomingMediaInspectionTest.FixtureLinux::class])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class NativeGalleryIncomingRuntimeTest {
    @Before fun mountedVolume() { GalleryIncomingRowsTest().mountedPrimaryVolume() }
    private class Harness(joined: Boolean = true, localConsent: Boolean = joined) : AutoCloseable {
        val helper = NativeGalleryIncomingTransferTest()
        val link = NativeGalleryIncomingTransferTest.Link()
        val f = GalleryReceiveConsentTest.Fixture(link.channel)
        val raw = helper.png()
        val manifest = helper.manifest(f.pc.deviceId, raw)
        val token = helper.intent()
        val file = File(f.root, "runtime-native.png")
        val provider = GalleryIncomingRowsTest.Provider(f.app, payload = file).apply { allowPublish = true }
        val identity = NativeFileControlIdentity("phone_fixture_0001", "a".repeat(64))
        private val pcPeer = NativeFileControlPeer(identity.deviceId, identity.identitySha256, Any(), true, true, true, true, true, "f".repeat(64))
        private var pcLocal = NativeLocalFileGrant(DeviceFileGrantState(3, "d".repeat(64), true, true), Any(), true)
        private val pc = NativeFileControlSession(f.pc, { pcPeer }, { pcLocal })
        val runtime: NativeGalleryFileRuntime
        var respond = true
        val requested = CountDownLatch(1)
        var held: JsonObject? = null
        var run: NativeGalleryIncomingRun? = null
        init {
            if (joined && localConsent) helper.grant(f)
            ShadowContentResolver.registerProviderInternal("media", provider)
            runtime = if (joined) NativeGalleryFileRuntime.withIncomingMedia(f.app, f.indexRoot, identity, f.protection, link.channel,
                { f.peer }, { true }, { true }, { token }, { token }, { true })
            else NativeGalleryFileRuntime.withSharedMediaIntent(f.app, f.indexRoot, identity, f.protection, link.channel,
                { f.peer }, { true }, { true }, { token })
            link.onMessage = { message ->
                when (message.string("kind")) {
                    DeviceFileControl.KIND -> pc.observeRemote(DeviceFileControlEnvelope.validate(message), pcPeer)
                    DeviceFileChunkEnvelope.REQUEST -> if (respond) answer(message) else { held = message; requested.countDown() }
                }
            }
            handshake()
        }
        fun handshake() {
            sendPc(); runtime.sendControls()
            if (pc.needsPacket()) sendPc()
            runtime.sendControls()
        }
        fun positive(kind: GalleryMediaType = GalleryMediaType.IMAGES): NativeGalleryReceiveConsent {
            val configurer = f.io { runtime.beginReceiveConfiguration() }
            val result = java.util.concurrent.atomic.AtomicReference<Result<NativeGalleryReceiveConsent>?>()
            NativeGalleryReceiveConsent.request(f.activity, "Native own PC", kind, configurer, f.book()) { result.set(it) }
            org.robolectric.shadows.ShadowAlertDialog.getLatestAlertDialog().getButton(android.content.DialogInterface.BUTTON_POSITIVE).performClick()
            Shadows.shadowOf(Looper.getMainLooper()).idle()
            return result.get()!!.getOrThrow()
        }
        fun sendPc() {
            val packet = pc.packet()
            runtime.observeControls(link.receive(DeviceFileControlEnvelope.create(packet)))
            pc.markSent(packet)
        }
        fun withdrawPcSend() {
            pcLocal = NativeLocalFileGrant(DeviceFileGrantState(4, "c".repeat(64), false, true), pcLocal.owner, true)
            sendPc()
        }
        fun answer(message: JsonObject) {
            val request = DeviceFileChunkEnvelope.parseRequest(message); val offset = request.chunkIndex * 65536
            val response = DeviceFileChunkEnvelope.response(request, raw.copyOfRange(offset, minOf(raw.size, offset + 65536)))
            assertTrue(runtime.observeIncomingChunk(link.channel, link.receive(response)))
        }
        fun start(): NativeGalleryIncomingRun = runtime.beginIncoming(DeviceFileOfferEnvelope.create(manifest), GalleryMediaType.IMAGES,
            mapOf("1".repeat(32) to "image/png"), f.book()).also { run = it }
        override fun close() {
            runtime.revokeControl()
            run?.let { check(it.awaitIoEnded(10000)) }
            runtime.close(); pc.close(); f.close(); link.close()
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
    }

    @Test fun actualRuntimeReceivesOnOwnedWorkerWhileChunkDispatcherAndControlsRemainIndependent() {
        Harness().use { h ->
            h.respond = false; val run = h.start()
            assertTrue(h.requested.await(5, TimeUnit.SECONDS))
            assertEquals("gallery_incoming_worker_busy", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.discoverSelectable()
            }.message)
            assertThrows(PhotoFolderScopeError::class.java) { h.start() }
            h.runtime.sendControls() // This lane must not be held behind the waiting receiver.
            h.respond = true; h.answer(h.held!!)
            assertTrue(run.awaitIoEnded(10000)); assertEquals("saved_output", run.phase)
            assertNotNull(run.actualSavedOutput()); assertNull(run.nativeFailure())
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.publishes)
            assertEquals(DeviceFileSavedEnvelope.KIND, h.link.frames.last().string("kind"))
        }
    }

    @Test fun actualControlWithdrawalCancelsPendingReceiverWithoutWaitingForChunkExpiry() {
        Harness().use { h ->
            h.respond = false; val run = h.start()
            assertTrue(h.requested.await(5, TimeUnit.SECONDS)); h.withdrawPcSend()
            assertTrue(run.awaitIoEnded(5000)); assertEquals("canceled_held", run.phase)
            assertNull(run.actualSavedOutput()); assertEquals(0, h.provider.publishes)
            assertTrue(h.link.frames.none { it.string("kind") == DeviceFileSavedEnvelope.KIND })
        }
    }

    @Test fun nativeCloseRetainsIoOwnershipAndDefersIndexCleanupUntilBlockedProviderActuallyReturns() {
        Harness().use { h ->
            val entered = CountDownLatch(1); val release = CountDownLatch(1)
            h.provider.beforeQuery = { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
            val run = h.start(); val closed = java.util.concurrent.atomic.AtomicInteger()
            try {
                assertTrue(entered.await(5, TimeUnit.SECONDS))
                assertFalse(h.runtime.closeWhenQuiescent { closed.incrementAndGet(); h.runtime.close() })
                assertFalse(run.ioEnded); assertEquals(0, closed.get())
                NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }).use { source ->
                    assertThrows(PhotoFolderScopeError::class.java) { source.startLocalInspection { } }
                }
            } finally { release.countDown() }
            assertTrue(run.awaitIoEnded(10000)); Shadows.shadowOf(Looper.getMainLooper()).idle()
            assertEquals(1, closed.get()); assertNull(run.actualSavedOutput())
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.savedPolicy() }
            assertEquals(0, h.provider.publishes)
        }
    }

    @Test fun sourceOnlyRuntimeFactoryNeverGainsIncomingHandlersFromMatchedTwoWayIntent() {
        Harness(joined = false).use { h ->
            val before = h.f.index.galleryPolicy()
            assertEquals("gallery_incoming_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) { h.start() }.message)
            assertEquals(before, h.f.index.galleryPolicy()); assertNull(before.policy)
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun incomingVideoCannotFallBackToImageHandlersWithoutNativeVideoPeerCapability() {
        Harness().use { h ->
            assertEquals("gallery_video_wire_handlers_unavailable", assertThrows(PhotoFolderScopeError::class.java) {
                h.runtime.beginIncoming(DeviceFileOfferEnvelope.create(h.manifest), GalleryMediaType.VIDEO,
                    mapOf("1".repeat(32) to "video/mp4"), h.f.book())
            }.message)
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun sharedProcessLaneSurvivesCancelUntilRealIncomingPreparationEndsAndThenAdmitsSource() {
        val entered = CountDownLatch(1); val release = CountDownLatch(1)
        NativeGalleryIncomingWorker().use { incoming ->
            NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }).use { source ->
                val run = incoming.start { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)); throw java.io.IOException("explicit native preparation end") }
                try {
                    assertTrue(entered.await(5, TimeUnit.SECONDS)); incoming.close()
                    assertFalse(incoming.isQuiescent); assertFalse(run.ioEnded)
                    assertThrows(PhotoFolderScopeError::class.java) { source.startLocalInspection { } }
                } finally { release.countDown() }
                assertTrue(run.awaitIoEnded(10000)); assertTrue(incoming.isQuiescent)
                assertEquals("canceled_held", run.phase)
                val sourceEnded = CountDownLatch(1)
                NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }, { sourceEnded.countDown() }).use { next ->
                    next.startLocalInspection { }; assertTrue(sourceEnded.await(5, TimeUnit.SECONDS)); assertTrue(next.isQuiescent)
                }
            }
        }
    }

    @Test fun actualForegroundPositiveConsentCommitsThroughRuntimeAndStillNeedsFreshDataControlEcho() {
        Harness(localConsent = false).use { h ->
            val before = h.runtime.savedPolicy(); assertNull(before.policy)
            val selected = h.positive()
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.grantReceiving(before, selected) }
            assertNull(h.runtime.savedPolicy().policy)
            val saved = h.f.io { h.runtime.grantReceiving(before, selected) }
            assertTrue(saved.policy!!.receiving!!.photos); assertFalse(saved.policy.receiving.videos)
            assertFalse(saved.policy.enabled); assertFalse(saved.policy.videos!!.enabled)
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED, h.f.app.checkSelfPermission(android.Manifest.permission.READ_MEDIA_IMAGES))
            assertThrows(PhotoFolderScopeError::class.java) { selected.requireCurrent() }
            val held = h.start(); assertTrue(held.awaitIoEnded(5000)); assertNull(held.actualSavedOutput())
            assertEquals(0, h.provider.inserts) // Local positive choice alone is not fresh data agreement.
            h.handshake()
            val run = h.start(); assertTrue(run.awaitIoEnded(10000)); assertNotNull(run.actualSavedOutput())
            assertArrayEquals(h.raw, h.file.readBytes()); assertEquals(1, h.provider.publishes)
        }
    }

    @Test fun canceledOrForeignReceiveConfigurationNeverPersistsRightsOrFinishesANewerTicket() {
        Harness(localConsent = false).use { h ->
            val before = h.f.rows(); val old = h.f.io { h.runtime.beginReceiveConfiguration() }
            val result = java.util.concurrent.atomic.AtomicReference<Result<NativeGalleryReceiveConsent>?>()
            NativeGalleryReceiveConsent.request(h.f.activity, "Native own PC", GalleryMediaType.IMAGES, old, h.f.book()) { result.set(it) }
            org.robolectric.shadows.ShadowAlertDialog.getLatestAlertDialog().getButton(android.content.DialogInterface.BUTTON_NEGATIVE).performClick()
            Shadows.shadowOf(Looper.getMainLooper()).idle(); assertTrue(result.get()!!.isFailure)
            h.runtime.finishReceiveConfiguration(old)
            val current = h.f.io { h.runtime.beginReceiveConfiguration() }
            assertThrows(PhotoFolderScopeError::class.java) { h.runtime.finishReceiveConfiguration(old) }
            h.runtime.finishReceiveConfiguration(current)
            assertEquals(before, h.f.rows()); assertNull(h.runtime.savedPolicy().policy)
        }
    }

    @Test fun positiveReceiveConsentCannotCommitAcrossAnotherOwnedMediaIoAndFreshExplicitRetryWorks() {
        Harness(localConsent = false).use { h ->
            val before = h.runtime.savedPolicy(); val selected = h.positive()
            val entered = CountDownLatch(1); val release = CountDownLatch(1); val ended = CountDownLatch(1)
            NativeGallerySourceWorker({ _, _ -> error("Unexpected source selection") }, { ended.countDown() }).use { source ->
                source.startLocalInspection { entered.countDown(); check(release.await(8, TimeUnit.SECONDS)) }
                try {
                    assertTrue(entered.await(5, TimeUnit.SECONDS))
                    assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.grantReceiving(before, selected) } }
                    assertEquals(before, h.runtime.savedPolicy()); assertThrows(PhotoFolderScopeError::class.java) { selected.requireCurrent() }
                } finally { release.countDown() }
                assertTrue(ended.await(5000, TimeUnit.MILLISECONDS))
            }
            val fresh = h.positive()
            assertTrue(h.f.io { h.runtime.grantReceiving(before, fresh) }.policy!!.receiving!!.photos)
        }
    }

    @Test fun nativeLocalReceiveDecreaseWorksWithoutAnOnlinePcAndPreservesSourceEpochAndStoredHistory() {
        Harness().use { h ->
            val before = h.runtime.savedPolicy(); val epoch = before.policy!!.epoch
            h.f.peer = h.f.peer.copy(ready = false)
            val off = h.f.io { h.runtime.revokeReceiving(before, GalleryMediaType.IMAGES, h.f.book()) }
            assertFalse(off.policy!!.receiving!!.photos); assertEquals(epoch, off.policy.epoch)
            assertEquals(before.policy.enabled, off.policy.enabled); assertTrue(off.policy.fileGrantRevision > before.policy.fileGrantRevision)
            val rows = h.f.rows()
            assertEquals(off, h.f.io { h.runtime.revokeReceiving(off, GalleryMediaType.IMAGES, h.f.book()) }); assertEquals(rows, h.f.rows())
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.beginReceiveConfiguration() } }
            assertEquals(0, h.provider.inserts)
        }
    }

    @Test fun exhaustedReceiveRevisionHoldsTheRuntimeWithoutPretendingPositiveStoredConsentWasOff() {
        Harness().use { h ->
            val p = h.runtime.savedPolicy().policy!!
            val exhausted = h.f.seedPolicy(GalleryPhotoPolicy(p.receiverId, p.receiverIdentitySha256, p.epoch, p.enabled, p.kinds,
                DeviceFileControl.MAX_REVISION, 5, p.pairingEpoch, p.videos, DeviceFileControl.MAX_REVISION,
                p.receiving!!.copy(revision = DeviceFileControl.MAX_REVISION)))
            h.handshake(); val selected = h.positive(GalleryMediaType.VIDEO); val rows = h.f.rows()
            assertThrows(PhotoFolderScopeError::class.java) { h.f.io { h.runtime.grantReceiving(exhausted, selected) } }
            assertEquals(rows, h.f.rows()); assertTrue(h.runtime.savedPolicy().policy!!.receiving!!.photos)
            assertThrows(PhotoFolderScopeError::class.java) { h.start() }
            assertEquals(0, h.provider.inserts)
        }
    }
}
