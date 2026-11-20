package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.KeyguardManager
import android.app.Notification
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.view.Surface
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.shadow.api.Shadow
import java.time.Duration

/** Projection/VirtualDisplay test doubles, real cleanup paths; no system capture. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [PhoneScreenProjectionTest.ProjectionApi::class,
    PhoneScreenProjectionTest.DisplayApi::class, PhoneScreenProjectionTest.SurfaceApi::class])
class PhoneScreenProjectionTest {
    class CaptureService : Service() { override fun onBind(intent: Intent?): IBinder? = null }

    @Implements(MediaProjection::class)
    class ProjectionApi {
        var created = 0
        var stopped = 0
        var unregistered = 0
        var flags: Int? = null
        var failCreate = false
        var target: Surface? = null
        val display: VirtualDisplay = Shadow.newInstanceOf(VirtualDisplay::class.java)

        @Implementation fun createVirtualDisplay(name: String, width: Int, height: Int, density: Int, flags: Int,
                target: Surface, callback: VirtualDisplay.Callback, handler: Handler): VirtualDisplay {
            created++
            this.flags = flags
            this.target = target
            if (failCreate) throw SecurityException("controlled OS display denial")
            return display
        }
        @Implementation fun stop() { stopped++ }
        @Implementation fun unregisterCallback(callback: MediaProjection.Callback) { unregistered++ }
    }

    @Implements(VirtualDisplay::class)
    class DisplayApi {
        var released = 0
        var failRelease = false
        @Implementation fun release() { released++; if (failRelease) error("controlled native display release failure") }
    }

    @Implements(Surface::class)
    class SurfaceApi {
        var releases = 0
        @Implementation fun isValid() = true
        @Implementation fun release() { releases++ }
    }

    private class Fixture(val promoted: Boolean = true) : AutoCloseable {
        val service = Robolectric.buildService(CaptureService::class.java).create().get()
        val projection: MediaProjection = Shadow.newInstanceOf(MediaProjection::class.java)
        val surface: Surface = Shadow.newInstanceOf(Surface::class.java)
        val api: ProjectionApi = Shadow.extract(projection)
        val display: DisplayApi = Shadow.extract(api.display)
        val output: SurfaceApi = Shadow.extract(surface)
        val ends = mutableListOf<Exception?>()
        var live = true
        var consentClosed = 0
        var opened = 0
        var callback: MediaProjection.Callback? = null
        val request = PhoneScreenViewRequest({ check(live) }, { 0L })
        val permit = object : PhoneScreenViewConsent {
            override fun requireVisibleStart(original: PhoneScreenViewRequest) { assertSame(request, original) }
            override fun open(original: PhoneScreenViewRequest, service: Service, callback: MediaProjection.Callback): MediaProjection {
                assertSame(request, original)
                assertSame(this@Fixture.service, service)
                opened++
                this@Fixture.callback = callback
                return projection
            }
            override fun close() { consentClosed++ }
        }
        val run = PhoneScreenProjection(service, request, permit) { ends += it }
        init {
            Shadows.shadowOf(service.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(false)
            Shadows.shadowOf(service.getSystemService(PowerManager::class.java)).setIsInteractive(true)
            if (promoted) service.startForeground(1, Notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        }
        fun start() = run.start(surface, 720, 1280, 160)
        fun tick() = Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(250))
        override fun close() = run.close()
    }

    @Test fun startsOneNonSecureMirrorOnTheOriginalSurfaceAndReleasesExactlyOnce() {
        Fixture().use { f ->
            assertEquals(0, f.opened)
            f.start()
            assertSame(f.surface, f.api.target)
            assertEquals(DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, f.api.flags)
            assertThrows(IllegalStateException::class.java) { f.start() }
            f.callback!!.onStop()
            f.callback!!.onStop()
            f.run.close()
            assertEquals(listOf<Exception?>(null), f.ends)
            assertEquals(1, f.api.created)
            assertEquals(1, f.display.released)
            assertEquals(1, f.api.unregistered)
            assertEquals(1, f.api.stopped)
            assertEquals(1, f.consentClosed)
            assertEquals(0, f.output.releases) // encoder Surface belongs to original service
        }
    }

    @Test fun peerLossKeyguardAndScreenOffEndTheExactCapture() {
        for (event in listOf("peer", "keyguard", "screen-off")) Fixture().use { f ->
            f.start()
            when (event) {
                "peer" -> f.live = false
                "keyguard" -> Shadows.shadowOf(f.service.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(true)
                "screen-off" -> f.service.sendBroadcast(Intent(Intent.ACTION_SCREEN_OFF))
            }
            f.tick()
            assertEquals(event, 1, f.ends.size)
            assertEquals(event, 1, f.display.released)
            assertEquals(event, 1, f.api.stopped)
            assertThrows(IllegalStateException::class.java) { f.start() }
        }
    }

    @Test fun deniedNativeSetupHasNoRetryAndCleanupFailureCannotSkipProjectionStop() {
        Fixture(promoted = false).use { f ->
            assertThrows(IllegalStateException::class.java) { f.start() }
            assertEquals(0, f.opened)
            assertEquals(1, f.consentClosed)
        }
        Fixture().use { f ->
            f.api.failCreate = true
            assertSame(assertThrows(SecurityException::class.java) { f.start() }, f.ends.single())
            assertEquals(0, f.display.released)
            assertEquals(1, f.api.stopped)
            assertThrows(IllegalStateException::class.java) { f.start() }
        }
        Fixture().use { f ->
            f.start()
            f.display.failRelease = true
            f.run.close()
            assertEquals("controlled native display release failure", f.ends.single()?.message)
            assertEquals(1, f.api.stopped)
            assertEquals(1, f.consentClosed)
        }
    }
}
