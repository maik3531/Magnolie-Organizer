package io.gitlab.maik3531.magnolienotes.telefon

import android.Manifest
import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.Looper
import androidx.activity.ComponentActivity
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Real ActivityResult/lifecycle/permission and Service adapters in Robolectric;
 * no physical permission, foreground capture, camera or microphone acceptance.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamPermissionHostTest {
    class CaptureService : Service() {
        var cameraLookups = 0
        override fun onBind(intent: Intent?): IBinder? = null
        override fun getSystemService(name: String): Any? {
            if (name == CAMERA_SERVICE) cameraLookups++
            return super.getSystemService(name)
        }
    }
    internal class Fixture : AutoCloseable {
        val controller = Robolectric.buildActivity(ComponentActivity::class.java).create()
        val activity = controller.get()
        var competing = false
        var live = true
        var now = 100L
        val host = PhoneWebcamPermissionHost(activity) { competing }
        val results = mutableListOf<Result<PhoneWebcamCapturePermit>>()
        private val app = Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application)
        init {
            app.denyPermissions(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
            controller.start().resume()
        }
        fun request(muted: Boolean = false) = PhoneWebcamCaptureRequest("a".repeat(32), muted, false,
            { check(live) { "original paired desktop context changed" } }, { now })
        fun grant(microphone: Boolean = true) {
            app.grantPermissions(Manifest.permission.CAMERA)
            if (microphone) app.grantPermissions(Manifest.permission.RECORD_AUDIO)
        }
        @Suppress("DEPRECATION") fun result(granted: Boolean = true) {
            val request = checkNotNull(Shadows.shadowOf(activity).lastRequestedPermission)
            activity.onRequestPermissionsResult(request.requestCode, request.requestedPermissions,
                IntArray(request.requestedPermissions.size) { if (granted) PackageManager.PERMISSION_GRANTED else PackageManager.PERMISSION_DENIED })
            Shadows.shadowOf(Looper.getMainLooper()).idle()
        }
        fun permit(): PhoneWebcamCapturePermit {
            host.request(request()) { results += it }; grant(); result()
            return results.single().getOrThrow()
        }
        override fun close() {
            results.forEach { it.getOrNull()?.close() }
            host.close(); controller.pause().stop().destroy()
        }
    }

    @Test fun constructionNeverPromptsOrCapturesAndGenuineOriginalResultCreatesOnlyPendingPermit() {
        Fixture().use { f ->
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            val original = f.request()
            f.host.request(original) { f.results += it }
            assertTrue(f.host.requestPending)
            assertEquals(setOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO),
                Shadows.shadowOf(f.activity).lastRequestedPermission!!.requestedPermissions.toSet())
            f.grant(); f.result()
            assertFalse(f.host.requestPending)
            val permit = f.results.single().getOrThrow()
            assertEquals("a".repeat(32), permit.session)
            assertFalse(permit.muted)
            assertThrows(IllegalStateException::class.java) { f.host.request(original) {} }
        }
    }

    @Test fun permissionCallbackBooleansNeverReplaceActualAndroidGrants() {
        Fixture().use { f ->
            f.host.request(f.request()) { f.results += it }; f.result(granted = true)
            assertTrue(f.results.single().isFailure)
        }
    }

    @Test fun missingMicrophoneNeverFallsBackToSilentVideoButExplicitMuteRequestsOnlyCamera() {
        Fixture().use { f ->
            f.host.request(f.request()) { f.results += it }; f.grant(microphone = false); f.result()
            assertTrue(f.results.single().isFailure)
        }
        Fixture().use { f ->
            f.host.request(f.request(muted = true)) { f.results += it }
            assertArrayEquals(arrayOf(Manifest.permission.CAMERA), Shadows.shadowOf(f.activity).lastRequestedPermission!!.requestedPermissions)
            f.grant(microphone = false); f.result()
            assertTrue(f.results.single().getOrThrow().muted)
        }
    }

    @Test fun deniedOsResultNeverUsesAnAlreadyGrantedPermissionAsConsentOverride() {
        Fixture().use { f ->
            f.host.request(f.request()) { f.results += it }; f.grant(); f.result(granted = false)
            assertTrue(f.results.single().isFailure)
        }
    }

    @Test fun oldCallbackCannotAdoptChangedPeerOrExpiredOriginalRequest() {
        for (change in listOf("peer", "deadline")) Fixture().use { f ->
            f.host.request(f.request()) { f.results += it }; f.grant()
            if (change == "peer") f.live = false else f.now += 60_000
            f.result(); assertTrue(f.results.single().isFailure)
        }
    }

    @Test fun actualStopKeepsOldOsSlotOccupiedUntilOriginalCallbackReturns() {
        Fixture().use { f ->
            val old = f.request(); f.host.request(old) { f.results += it }
            f.controller.pause().stop()
            assertTrue(f.host.requestPending)
            assertEquals(1, f.results.size); assertTrue(f.results.single().isFailure)
            f.controller.start().resume()
            assertThrows(IllegalStateException::class.java) { f.host.request(f.request()) {} }
            f.grant(); f.result()
            assertFalse(f.host.requestPending); assertEquals(1, f.results.size)
            assertThrows(IllegalStateException::class.java) { old.requireOriginal() }
        }
    }

    @Test fun backgroundOrCompetingPermissionFlowDoesNotLaunchNewPrompt() {
        Fixture().use { f ->
            f.competing = true
            assertThrows(IllegalStateException::class.java) { f.host.request(f.request()) {} }
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            f.competing = false; f.controller.pause()
            assertThrows(IllegalStateException::class.java) { f.host.request(f.request()) {} }
            assertNull(Shadows.shadowOf(f.activity).lastRequestedPermission)
            f.controller.resume()
        }
    }

    @Test fun nativeCaptureEngineRefusesMissingForegroundServiceBeforeLookingUpAnyCamera() {
        Fixture().use { f ->
            val permit = f.permit()
            val service = Robolectric.buildService(CaptureService::class.java).create()
            val ended = mutableListOf<Throwable?>()
            val capture = PhoneWebcamAndroidCapture(service.get(), permit, { _, _, _ -> fail("Unexpected hardware sample") }, { ended += it })
            try {
                assertThrows(IllegalStateException::class.java) { capture.start() }
                assertEquals(0, service.get().cameraLookups)
                assertTrue(capture.isCompletelyStopped()); assertEquals(1, ended.size)
                assertNotNull(ended.single())
            } finally { capture.close(); service.destroy() }
        }
    }

    @Test fun originalNativeForegroundTypeAndActualPermissionsStayLiveAndFailureIsSticky() {
        Fixture().use { f ->
            val permit = f.permit()
            val controller = Robolectric.buildService(CaptureService::class.java).create()
            val service = controller.get()
            try {
                val manager = service.getSystemService(NotificationManager::class.java)
                manager.createNotificationChannel(NotificationChannel("webcam-test", "Synthetic webcam test", NotificationManager.IMPORTANCE_LOW))
                service.startForeground(918, Notification.Builder(service, "webcam-test").setSmallIcon(android.R.drawable.ic_menu_camera).build(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
                permit.enterForeground(service); permit.requireActive(service)
                f.controller.pause() // A genuinely admitted foreground service may continue after Activity pause.
                permit.requireActive(service)
                Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).denyPermissions(Manifest.permission.RECORD_AUDIO)
                assertThrows(IllegalStateException::class.java) { permit.requireActive(service) }
                f.grant()
                assertThrows(IllegalStateException::class.java) { permit.requireActive(service) }
                f.controller.resume()
            } finally { service.stopForeground(Service.STOP_FOREGROUND_REMOVE); controller.destroy() }
        }
    }

    @Test fun optionalAdapterFailureDuringOsResultIsContainedAndOriginalRequestIsRetired() {
        Fixture().use { f ->
            val request = f.request()
            f.host.request(request) { throw IllegalStateException("synthetic capture adapter startup failure") }
            f.grant(); f.result()
            assertEquals("synthetic capture adapter startup failure", request.terminalFailure?.message)
            assertFalse(f.host.requestPending)
            assertThrows(IllegalStateException::class.java) { request.requireOriginal() }
        }
    }

    @Test fun competingFlowAppearingBeforeTheOriginalCallbackCannotGrantCapture() {
        Fixture().use { f ->
            f.host.request(f.request()) { f.results += it }
            f.competing = true; f.grant(); f.result()
            assertTrue(f.results.single().isFailure)
        }
    }

    @Test fun foregroundAdmittedEngineWithNoCameraDrainsItsOriginalCleanupWorkerWithoutSamples() {
        Fixture().use { f ->
            val permit = f.permit()
            val controller = Robolectric.buildService(CaptureService::class.java).create()
            val service = controller.get()
            val done = CountDownLatch(1)
            var outcome: Throwable? = null
            try {
                service.getSystemService(NotificationManager::class.java).createNotificationChannel(
                    NotificationChannel("webcam-empty-camera", "Synthetic camera test", NotificationManager.IMPORTANCE_LOW))
                service.startForeground(919, Notification.Builder(service, "webcam-empty-camera").setSmallIcon(android.R.drawable.ic_menu_camera).build(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
                val capture = PhoneWebcamAndroidCapture(service, permit, { _, _, _ -> fail("Unexpected native sample") }, { outcome = it; done.countDown() })
                val error = assertThrows(IllegalStateException::class.java) { capture.start() }
                assertEquals("webcam_requested_camera_unavailable", error.message)
                assertTrue(done.await(3, TimeUnit.SECONDS))
                assertTrue(capture.isCompletelyStopped())
                assertNotNull(outcome)
                assertTrue(service.cameraLookups > 0)
                capture.close()
            } finally { service.stopForeground(Service.STOP_FOREGROUND_REMOVE); controller.destroy() }
        }
    }

    @Test fun captureEndObserverFailureCannotEscapeIntoTheActivityOrReviveAnEngine() {
        Fixture().use { f ->
            val permit = f.permit()
            val controller = Robolectric.buildService(CaptureService::class.java).create()
            try {
                val capture = PhoneWebcamAndroidCapture(controller.get(), permit, { _, _, _ -> fail("Unexpected capture") },
                    { throw IllegalStateException("synthetic optional observer failure") })
                val original = assertThrows(IllegalStateException::class.java) { capture.start() }
                assertEquals("webcam_actual_foreground_capture_required", original.message)
                assertSame(original, capture.terminalFailure)
                assertEquals("synthetic optional observer failure", original.suppressed.single().message)
                assertTrue(capture.isCompletelyStopped())
                assertThrows(IllegalStateException::class.java) { capture.start() }
            } finally { controller.destroy() }
        }
    }
}
