package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Notification
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Looper
import android.os.SystemClock
import io.gitlab.maik3531.magnolienotes.R
import java.net.InetAddress
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.android.controller.ServiceController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamCaptureServiceTest {
    private class Fixture : AutoCloseable {
        val ui = PhoneWebcamPermissionHostTest.Fixture()
        var current = true
        var factories = 0
        var closes = 0
        val runs = mutableListOf<PhoneWebcamForegroundRun>()
        val services = mutableListOf<ServiceController<PhoneWebcamCaptureService>>()
        init { ShadowSystemClock.advanceBy(Duration.ofMillis(100)) }
        fun run(second: Boolean = false, native: Boolean = false): PhoneWebcamForegroundRun {
            var permit: PhoneWebcamCapturePermit? = null
            if (!second) permit = ui.permit()
            else {
                ui.host.request(PhoneWebcamCaptureRequest("b".repeat(32), false, false, { check(current) })) { permit = it.getOrThrow() }
                Shadows.shadowOf(Looper.getMainLooper()).idle()
            }
            val key = ByteArray(32) { it.toByte() }
            val control = { check(current) { "original control changed" } }
            val value = if (native) PhoneWebcamForegroundRun(checkNotNull(permit), key, InetAddress.getByName("127.0.0.1"),
                control, { error("No receiver agreement in service fixture") }, {}, {})
            else PhoneWebcamForegroundRun(checkNotNull(permit), key, InetAddress.getByName("127.0.0.1"),
                control, { error("No receiver agreement in service fixture") }, {}, {}) { service, grant, sample, end ->
                factories++
                object : PhoneWebcamCaptureDevice {
                    var closed = false
                    override fun start() {
                        grant.enterForeground(service)
                        val time = SystemClock.elapsedRealtimeNanos()
                        sample(true, time, ByteArray(460800)); sample(false, time, ByteArray(1920))
                    }
                    override fun close() { if (!closed) { closed = true; closes++; end(null) } }
                    override fun isCompletelyStopped() = closed
                }
            }
            runs += value
            return value
        }
        fun submit(run: PhoneWebcamForegroundRun): Intent {
            PhoneWebcamServiceStarts.start(ui.activity, run)
            return checkNotNull(Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).nextStartedService)
        }
        fun service(): ServiceController<PhoneWebcamCaptureService> = Robolectric.buildService(PhoneWebcamCaptureService::class.java)
            .create().also { services += it }
        fun shown(): Notification? = ui.activity.getSystemService(NotificationManager::class.java)
            .activeNotifications.firstOrNull { it.id == 24401 }?.notification
        override fun close() {
            runs.forEach { it.close() }
            // Own test sources close synchronously; allow the actual lane/stop workers to retire.
            val deadline = System.nanoTime() + 3_000_000_000L
            while (runs.any { !it.isCompletelyStopped() } && System.nanoTime() < deadline) Thread.sleep(5)
            assertTrue(runs.all { it.isCompletelyStopped() })
            services.forEach { it.destroy() }
            Shadows.shadowOf(Looper.getMainLooper()).idle()
            ui.close()
        }
    }

    @Test fun missingOrRestoredServiceIntentDoesNotCreateForegroundCaptureOrRestart() {
        val controller = Robolectric.buildService(PhoneWebcamCaptureService::class.java).create()
        try {
            val service = controller.get()
            assertEquals(Service.START_NOT_STICKY, service.onStartCommand(null, 0, 1))
            assertNull(Shadows.shadowOf(service).lastForegroundNotification)
            val unknown = Intent(service, PhoneWebcamCaptureService::class.java).setAction(PhoneWebcamCaptureService.START)
                .putExtra(PhoneWebcamCaptureService.TOKEN, "f".repeat(64))
            assertEquals(Service.START_NOT_STICKY, service.onStartCommand(unknown, 0, 2))
            assertNull(Shadows.shadowOf(service).lastForegroundNotification)
        } finally { controller.destroy() }
    }

    @Test fun originalOneUseHandoffStartsRealForegroundTypesAndOnlyThenShowsActualCaptureState() {
        Fixture().use { f ->
            val run = f.run(); val intent = f.submit(run); val service = f.service().get()
            assertEquals(Service.START_NOT_STICKY, service.onStartCommand(intent, 0, 1))
            assertEquals(ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE, service.foregroundServiceType)
            assertEquals(f.ui.activity.getString(R.string.webcam_startet), f.shown()!!.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
            Shadows.shadowOf(Looper.getMainLooper()).idle()
            assertEquals(f.ui.activity.getString(R.string.webcam_aktiv), f.shown()!!.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
            assertTrue(f.shown()!!.actions.single().actionIntent.isImmutable)
            service.onStartCommand(intent, 0, 2)
            assertEquals(1, f.factories)
        }
    }

    @Test fun secondCaptureOwnerIsRejectedWithoutStoppingOriginalAndNativeStopTokenIsExact() {
        Fixture().use { f ->
            val first = f.run(); val intent = f.submit(first); val service = f.service().get()
            service.onStartCommand(intent, 0, 1)
            val second = f.run(second = true)
            val error = assertThrows(IllegalStateException::class.java) { f.submit(second) }
            assertEquals("webcam_native_capture_owner_busy", error.message)
            assertFalse(first.isStopping); assertEquals(1, f.factories); assertEquals(0, f.closes)
            service.onStartCommand(Intent(service, PhoneWebcamCaptureService::class.java).setAction(PhoneWebcamCaptureService.STOP)
                .putExtra(PhoneWebcamCaptureService.TOKEN, "f".repeat(64)), 0, 2)
            assertFalse(first.isStopping)
            service.onStartCommand(Intent(service, PhoneWebcamCaptureService::class.java).setAction(PhoneWebcamCaptureService.STOP)
                .putExtra(PhoneWebcamCaptureService.TOKEN, intent.getStringExtra(PhoneWebcamCaptureService.TOKEN)), 0, 3)
            assertTrue(first.isStopping); assertEquals(1, f.closes)
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(200))
            assertTrue(Shadows.shadowOf(service).isForegroundStopped)
        }
    }

    @Test fun staleOriginalContextBeforeServiceClaimNeverCreatesCaptureOrAStuckStartSlot() {
        Fixture().use { f ->
            val run = f.run(); val intent = f.submit(run); f.current = false
            val service = f.service().get()
            service.onStartCommand(intent, 0, 1)
            assertTrue(run.isCompletelyStopped()); assertEquals(0, f.factories)
            assertNull(Shadows.shadowOf(service).lastForegroundNotification)
        }
    }

    @Test fun defaultNativeCaptureFailureStopsForegroundRatherThanPublishingSyntheticReadiness() {
        Fixture().use { f ->
            val run = f.run(native = true); val intent = f.submit(run); val service = f.service().get()
            service.onStartCommand(intent, 0, 1)
            val deadline = System.nanoTime() + 3_000_000_000L
            while (!run.isCompletelyStopped() && System.nanoTime() < deadline) Thread.sleep(5)
            Shadows.shadowOf(Looper.getMainLooper()).idleFor(Duration.ofMillis(200))
            assertEquals("webcam_requested_camera_unavailable", run.terminalFailure?.message)
            assertTrue(Shadows.shadowOf(service).isForegroundStopped)
            assertNull(f.shown())
        }
    }
}
