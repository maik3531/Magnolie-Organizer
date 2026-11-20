package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.KeyguardManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.os.Looper
import android.os.PowerManager
import android.view.Surface
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.shadow.api.Shadow
import java.time.Duration

/** Actual service/Intent/notification wiring with controlled projection/encoder adapters. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, shadows = [PhoneScreenProjectionTest.ProjectionApi::class,
    PhoneScreenProjectionTest.DisplayApi::class, PhoneScreenProjectionTest.SurfaceApi::class])
class PhoneScreenCaptureServiceTest {
    private class Handoff : AutoCloseable {
        val context = RuntimeEnvironment.getApplication() as Application
        val projection: MediaProjection = Shadow.newInstanceOf(MediaProjection::class.java)
        val api: PhoneScreenProjectionTest.ProjectionApi = Shadow.extract(projection)
        var live = true
        val request = PhoneScreenViewRequest(originalCurrent = { check(live) })
        var consentClosed = 0
        var opens = 0
        var targetStarts = 0
        var targetStops = 0
        var joined = false
        lateinit var handle: PhoneScreenCaptureHandle
            private set
        private val output = object : PhoneScreenOutput {
            override val surface: Surface = Shadow.newInstanceOf(Surface::class.java)
            override fun requestStop() { targetStops++ }
            override fun isDrained() = joined
        }
        private val consent = object : PhoneScreenViewConsent {
            override fun requireVisibleStart(original: PhoneScreenViewRequest) {
                assertSame(request, original)
                check(live)
            }
            override fun open(original: PhoneScreenViewRequest, service: Service, callback: MediaProjection.Callback): MediaProjection {
                requireVisibleStart(original)
                assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION, service.foregroundServiceType)
                opens++
                return projection
            }
            override fun close() { consentClosed++ }
        }

        init {
            Shadows.shadowOf(context.getSystemService(KeyguardManager::class.java)).setIsDeviceLocked(false)
            Shadows.shadowOf(context.getSystemService(PowerManager::class.java)).setIsInteractive(true)
        }

        fun enqueue(): Intent {
            handle = PhoneScreenServiceStarts.start(context, request, consent, 720, 1280, 160) { targetStarts++; output }
            return checkNotNull(Shadows.shadowOf(context).nextStartedService)
        }

        override fun close() { if (::handle.isInitialized) handle.close() }
    }

    private fun tick(millis: Long = 250) = Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(millis))

    @Test fun invalidOrRecreatedServiceNeverStartsProjection() {
        val controller = Robolectric.buildService(PhoneScreenCaptureService::class.java).create()
        val actual = controller.get()
        val shadow = Shadows.shadowOf(actual)
        try {
            for (intent in listOf(null, PhoneScreenCaptureService.startIntent(actual, "unbound"))) {
                assertEquals(Service.START_NOT_STICKY, actual.onStartCommand(intent, 0, 1))
                assertTrue(shadow.isStoppedBySelf)
                assertEquals(0, shadow.lastForegroundNotificationId)
            }
            assertNull(actual.onBind(Intent()))
        } finally { controller.destroy() }
    }

    @Test fun stopActionAndDrainBelongToOriginalServiceAndCannotStopReplacement() {
        val first = Handoff()
        val replacement = Handoff()
        val original = Robolectric.buildService(PhoneScreenCaptureService::class.java).create()
        val actual = original.get()
        val shadow = Shadows.shadowOf(actual)
        val launch = first.enqueue()
        assertThrows(IllegalStateException::class.java) { first.handle.requireActive() }
        assertEquals(Service.START_NOT_STICKY, actual.onStartCommand(launch, 0, 1))
        first.handle.requireActive()
        assertEquals(1, first.opens)
        assertEquals(1, first.api.created)
        assertEquals(1, first.targetStarts)
        val stopAction = shadow.lastForegroundNotification.actions.single().actionIntent
        val stop = Shadows.shadowOf(stopAction).savedIntent
        // Replay never consumes the permit twice or creates a second output.
        actual.onStartCommand(launch, 0, 2)
        assertEquals(1, first.opens)
        assertThrows(IllegalStateException::class.java) { replacement.enqueue() }
        actual.onStartCommand(stop, 0, 3)
        tick()
        assertEquals(1, first.targetStops)
        assertEquals(1, first.api.stopped)
        assertFalse(shadow.isStoppedBySelf)
        assertThrows(IllegalStateException::class.java) { first.handle.requireActive() }
        assertFalse(first.handle.isDrained())
        assertThrows(IllegalStateException::class.java) { replacement.enqueue() }

        // Even forced Android destruction does not make an undrained worker reusable.
        original.destroy()
        assertThrows(IllegalStateException::class.java) { replacement.enqueue() }
        first.joined = true
        assertTrue(first.handle.isDrained())
        val nextLaunch = replacement.enqueue()
        val next = Robolectric.buildService(PhoneScreenCaptureService::class.java).create()
        try {
            next.get().onStartCommand(nextLaunch, 0, 4)
            next.get().onStartCommand(stop, 0, 5)
            first.close()
            assertEquals(1, replacement.opens)
            assertEquals(0, replacement.targetStops)
            replacement.handle.requireActive()
            assertThrows(IllegalStateException::class.java) { first.handle.requireActive() }
            replacement.close()
            replacement.joined = true
            tick()
            assertEquals(1, replacement.targetStops)
            assertTrue(Shadows.shadowOf(next.get()).isStoppedBySelf)
        } finally { replacement.joined = true; next.destroy() }
    }

    @Test fun cancelledExpiredAndRevokedHandoffsNeverOpenEncoderOrConsent() {
        for (event in listOf("cancel", "expire", "revoke")) Handoff().use { start ->
            val launch = start.enqueue()
            when (event) {
                "cancel" -> start.close()
                "expire" -> tick(8_001)
                "revoke" -> start.live = false
            }
            val controller = Robolectric.buildService(PhoneScreenCaptureService::class.java).create()
            try {
                assertEquals(Service.START_NOT_STICKY, controller.get().onStartCommand(launch, 0, 1))
                assertTrue(event, Shadows.shadowOf(controller.get()).isStoppedBySelf)
                assertEquals(event, 0, start.opens)
                assertEquals(event, 0, start.targetStarts)
                assertEquals(event, 1, start.consentClosed)
            } finally { controller.destroy() }
        }
    }
}
