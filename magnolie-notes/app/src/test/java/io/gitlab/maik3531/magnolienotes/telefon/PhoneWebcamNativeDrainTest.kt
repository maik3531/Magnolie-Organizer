package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.os.HandlerThread
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Models a timed-out join by retaining a genuinely live original thread after
 * the cleanup signal. No capture API/device is started by these drain probes. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamNativeDrainTest {
    private fun checkOriginalThread(field: String) {
        PhoneWebcamPermissionHostTest.Fixture().use { ui ->
            val controller = Robolectric.buildService(PhoneWebcamPermissionHostTest.CaptureService::class.java).create()
            val entered = CountDownLatch(1)
            val release = CountDownLatch(1)
            val awaitOriginal = { entered.countDown(); check(release.await(5, TimeUnit.SECONDS)) }
            val worker = if (field == "imageThread") object : HandlerThread("Magnolie controlled image drain") {
                override fun run() = awaitOriginal.invoke()
            } else Thread(awaitOriginal, "Magnolie controlled audio drain")
            val capture = PhoneWebcamAndroidCapture(controller.get(), ui.permit(),
                { _, _, _ -> fail("No device capture allowed in drain test") }, {})
            try {
                PhoneWebcamAndroidCapture::class.java.getDeclaredField(field).apply { isAccessible = true }.set(capture, worker)
                worker.start(); assertTrue(entered.await(2, TimeUnit.SECONDS))
                capture.close() // Cleanup is signalled, but the original thread is still alive.
                assertTrue(worker.isAlive)
                assertFalse("$field still owns a live capture worker", capture.isCompletelyStopped())
                release.countDown(); worker.join(2_000)
                assertFalse(worker.isAlive)
                assertTrue(capture.isCompletelyStopped())
            } finally {
                release.countDown(); worker.join(2_000); capture.close(); controller.destroy()
            }
        }
    }

    @Test fun cleanupSignalCannotRetireAnOriginalAudioThreadUntilItReallyExits() = checkOriginalThread("audioThread")
    @Test fun cleanupSignalCannotRetireAnOriginalImageThreadUntilItReallyExits() = checkOriginalThread("imageThread")
}
