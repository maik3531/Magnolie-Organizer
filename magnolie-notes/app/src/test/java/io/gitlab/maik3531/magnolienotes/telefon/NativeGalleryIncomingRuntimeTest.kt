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
    private class Harness(joined: Boolean = true) : AutoCloseable {
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
            if (joined) helper.grant(f)
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
            sendPc(); runtime.sendControls()
            if (pc.needsPacket()) sendPc()
            runtime.sendControls()
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
}
