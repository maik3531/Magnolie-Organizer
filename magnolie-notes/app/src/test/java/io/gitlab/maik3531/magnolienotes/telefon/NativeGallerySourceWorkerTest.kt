package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class)
class NativeGallerySourceWorkerTest {
    private fun selection(): NativeGalleryAlbumSelection {
        val receiver = NativePhotoReceiver("receiver_fixture_01", "e".repeat(64), Any(), "f".repeat(64), true, true, true, true, true, true, 1)
        val request = NativeGalleryRequest(receiver, "a".repeat(64), setOf(GallerySourceKind.CAMERA))
        val album = GalleryAlbumCandidate(GallerySourceKind.CAMERA, "external", "camera", "Camera", null, 1, false)
        val catalog = NativeGalleryAlbumCatalog(GalleryAlbumCatalog(GalleryReadCoverage.FULL_IMAGES, listOf(album), request), Any(), { true })
        val page = catalog.page()
        val entry = (page.getValue("albums") as kotlinx.serialization.json.JsonArray).single() as JsonObject
        return catalog.select(page.string("catalog_id"), entry.string("album_id"), true)
    }
    private fun job() = PhotoSourceJob("fixture", "a".repeat(64), "b".repeat(64), 5, 4096, "synthetic-root", "sealed", JsonObject(emptyMap()))

    @Test fun constructionIsInertAndCancellationDoesNotReleaseBlockedIoOrStartAnOverlappingRun() {
        val entered = CountDownLatch(1); val release = CountDownLatch(1); val ended = CountDownLatch(1)
        val calls = AtomicInteger()
        lateinit var worker: NativeGallerySourceWorker
        worker = NativeGallerySourceWorker({ _, signal ->
            signal.setOnCancelListener {
                val gate = NativeGallerySourceWorker::class.java.getDeclaredField("gate").also { it.isAccessible = true }.get(worker)
                assertFalse("Native cancellation ran under the worker ownership monitor", Thread.holdsLock(gate))
            }
            calls.incrementAndGet(); entered.countDown()
            check(release.await(5, TimeUnit.SECONDS))
            signal.throwIfCanceled(); job()
        }, { ended.countDown() })
        assertEquals(0, calls.get()); assertTrue(worker.isQuiescent)
        val selected = selection(); val run = worker.start(selected)
        try {
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            worker.cancel(run)
            assertTrue(run.cancelRequested); assertFalse(run.ioEnded)
            assertSame(run, worker.current); assertFalse(worker.isQuiescent)
            assertThrows(PhotoFolderScopeError::class.java) { run.snapshotJob() }
            assertThrows(PhotoFolderScopeError::class.java) { worker.start(selected) }
            worker.close()
            assertFalse(worker.isQuiescent); assertFalse(run.ioEnded)
            release.countDown(); assertTrue(ended.await(5, TimeUnit.SECONDS))
            assertTrue(run.ioEnded); assertTrue(worker.isQuiescent)
            assertEquals("canceled_held", run.phase); assertNull(run.snapshotJob())
            assertThrows(PhotoFolderScopeError::class.java) { worker.start(selected) }
        } finally { release.countDown(); worker.close(); assertTrue(ended.await(5, TimeUnit.SECONDS)); selected.catalog.close() }
    }

    @Test fun actualPreparationEndExposesOnlySnapshotMetadataAndAllowsTheNextExplicitRun() {
        val ends = java.util.concurrent.LinkedBlockingQueue<NativeGallerySourceRun>()
        val prepared = job(); val worker = NativeGallerySourceWorker({ _, _ -> prepared }, { ends.add(it) })
        val selected = selection()
        try {
            val first = worker.start(selected)
            assertSame(first, ends.poll(5, TimeUnit.SECONDS)); assertTrue(first.ioEnded)
            assertSame(prepared, first.snapshotJob()); assertEquals("snapshot_ready", first.phase)
            assertTrue(worker.isQuiescent)
            val second = worker.start(selected)
            assertSame(second, ends.poll(5, TimeUnit.SECONDS))
            assertNotEquals(first.id, second.id)
            assertThrows(PhotoFolderScopeError::class.java) { worker.cancel(first) }
            assertSame(prepared, second.snapshotJob())
        } finally { worker.close(); selected.catalog.close() }
    }

    @Test fun sourceFailureIsHeldAsAnExactNativeFailureNotAutomaticallyRetriedOrRetired() {
        val ended = CountDownLatch(1); val failure = IOException("synthetic preparation failure"); val calls = AtomicInteger()
        val worker = NativeGallerySourceWorker({ _, _ -> calls.incrementAndGet(); throw failure }, { ended.countDown() })
        val selected = selection()
        try {
            val run = worker.start(selected)
            assertTrue(ended.await(5, TimeUnit.SECONDS))
            assertEquals(1, calls.get()); assertTrue(run.ioEnded)
            assertEquals("failed_held", run.phase); assertSame(failure, run.nativeFailure()); assertNull(run.snapshotJob())
            assertTrue(worker.isQuiescent)
        } finally { worker.close(); assertTrue(ended.await(5, TimeUnit.SECONDS)); selected.catalog.close() }
    }

    @Test fun anUnexpectedPreparationErrorCannotBeReportedAsASuccessfulSnapshot() {
        val ended = CountDownLatch(1); val fatal = AssertionError("synthetic native preparation error")
        val worker = NativeGallerySourceWorker({ _, _ -> throw fatal }, { ended.countDown() })
        val selected = selection()
        try {
            val run = worker.start(selected)
            assertTrue(ended.await(5, TimeUnit.SECONDS))
            assertTrue(run.ioEnded); assertEquals("failed_held", run.phase)
            assertSame(fatal, run.nativeFailure()); assertNull(run.snapshotJob()); assertTrue(worker.isQuiescent)
        } finally { worker.close(); assertTrue(ended.await(5, TimeUnit.SECONDS)); selected.catalog.close() }
    }
}
