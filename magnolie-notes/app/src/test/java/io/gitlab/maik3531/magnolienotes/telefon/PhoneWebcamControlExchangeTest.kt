package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.pm.ServiceInfo
import android.os.SystemClock
import kotlinx.serialization.json.*
import java.net.InetAddress
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamControlExchangeTest {
    private class Fixture : AutoCloseable {
        val parent = Any()
        var live = true
        var now = 100L
        val exchange = PhoneWebcamControlExchange(parent, { check(live) { "original live parent lost" } }, { now })
        val probe = exchange.probe(parent)
        fun report(op: String = "offer", fields: Map<String, JsonElement> = emptyMap()): JsonObject {
            val body = JsonObject(probe + mapOf("op" to JsonPrimitive(op)) + when (op) {
                "offer" -> mapOf("session" to JsonPrimitive("c".repeat(32)), "secret" to JsonPrimitive("d".repeat(64)),
                    "port" to JsonPrimitive(24401), "muted" to JsonPrimitive(false), "front" to JsonPrimitive(false))
                "unavailable" -> mapOf("reason" to JsonPrimitive("disabled"))
                else -> mapOf("session" to JsonPrimitive("c".repeat(32)))
            } + fields)
            return TelefonNachrichten.message(PhoneWebcamControl.REPORT, body, 60_000)
        }
        override fun close() { exchange.close() }
    }

    @Test fun newProbeIsOneUseAndOfferCreatesOnlyAnOriginalRequestNotAnOsPermit() {
        Fixture().use { f ->
            val request = f.exchange.acceptOffer(f.parent, f.report())!!
            assertEquals("c".repeat(32), request.session); assertFalse(request.muted)
            request.requireOriginal(); assertEquals(24401, f.exchange.port)
            assertThrows(IllegalStateException::class.java) { f.exchange.probe(f.parent) }
            assertThrows(IllegalStateException::class.java) { request.requireOriginal() }
        }
    }

    @Test fun foreignParentOrOldNonceCannotAdoptOrRetireTheCurrentExchange() {
        Fixture().use { f ->
            assertThrows(IllegalStateException::class.java) { f.exchange.acceptOffer(Any(), f.report()) }
            assertThrows(IllegalStateException::class.java) {
                f.exchange.acceptOffer(f.parent, f.report(fields = mapOf("nonce" to JsonPrimitive("0".repeat(64)))))
            }
            f.exchange.acceptOffer(f.parent, f.report())!!.requireOriginal()
        }
    }

    @Test fun originalParentLossAndStartupDeadlineAreStickyNotPreferenceRecovery() {
        for (mode in listOf("parent", "deadline", "rollback")) Fixture().use { f ->
            val original = f.exchange.acceptOffer(f.parent, f.report())!!
            when (mode) { "parent" -> f.live = false; "deadline" -> f.now += 60_000; else -> f.now-- }
            assertThrows(IllegalStateException::class.java) { original.requireOriginal() }
            f.live = true; f.now = 100
            assertThrows(IllegalStateException::class.java) { original.requireOriginal() }
        }
    }

    @Test fun offerAloneCannotAcceptReceiverSendBeforeActualCapturePrepared() {
        Fixture().use { f ->
            val request = f.exchange.acceptOffer(f.parent, f.report())!!
            assertThrows(IllegalStateException::class.java) { f.exchange.acceptSend(f.parent, f.report("send")) }
            assertThrows(IllegalStateException::class.java) { request.requireOriginal() }
        }
    }

    @Test fun unavailableNeverCreatesCaptureAndCannotBeReplacedWithAProviderFallback() {
        Fixture().use { f ->
            assertNull(f.exchange.acceptOffer(f.parent, f.report("unavailable")))
            assertThrows(IllegalStateException::class.java) { f.exchange.acceptOffer(f.parent, f.report()) }
        }
    }

    @Test fun matchingWireMetadataCannotSubstituteAnotherOriginalAndroidPermit() {
        Fixture().use { f -> PhoneWebcamPermissionHostTest.Fixture().use { ui ->
            f.exchange.acceptOffer(f.parent, f.report())
            val foreign = ui.permit()
            assertThrows(IllegalStateException::class.java) {
                f.exchange.createRun(f.parent, foreign, InetAddress.getByName("127.0.0.1"), {}, {})
            }
            foreign.requireVisibleStart() // Rejecting it did not steal/retire another owner's permit.
        } }
    }

    @Test fun onlyOriginalOsPermitAndActualJoinedCapturePreparationPermitMatchingSendAndStop() {
        Fixture().use { f -> PhoneWebcamPermissionHostTest.Fixture().use { ui ->
            val original = f.exchange.acceptOffer(f.parent, f.report())!!
            var permit: PhoneWebcamCapturePermit? = null
            ui.host.request(original) { permit = it.getOrThrow() }; ui.grant(); ui.result()
            val controller = Robolectric.buildService(PhoneWebcamPermissionHostTest.CaptureService::class.java).create()
            val service = controller.get()
            val ended = CountDownLatch(1)
            var prepared: JsonObject? = null
            var closed = false
            val run = f.exchange.createRun(f.parent, checkNotNull(permit), InetAddress.getByName("127.0.0.1"),
                { prepared = it }, { ended.countDown() }) { actual, permission, sample, stopped ->
                object : PhoneWebcamCaptureDevice {
                    override fun start() {
                        permission.enterForeground(actual)
                        val time = maxOf(1, SystemClock.elapsedRealtimeNanos())
                        sample(true, time, ByteArray(460800)); sample(false, time, ByteArray(1920))
                    }
                    override fun close() { if (!closed) { closed = true; stopped(null) } }
                    override fun isCompletelyStopped() = closed
                }
            }
            try {
                service.getSystemService(NotificationManager::class.java).createNotificationChannel(
                    NotificationChannel("exchange-test", "Controlled exchange", NotificationManager.IMPORTANCE_LOW))
                service.startForeground(924, Notification.Builder(service, "exchange-test").setSmallIcon(android.R.drawable.ic_menu_camera).build(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
                org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(100))
                run.start(service)
                assertNotNull(prepared)
                PhoneWebcamControl.validateBody(checkNotNull(prepared), PhoneWebcamControl.REQUEST)
                assertEquals(JsonPrimitive("prepared"), prepared!!["op"])
                f.exchange.acceptSend(f.parent, f.report("send"))
                f.now += 60_000 // Actual admitted SEND does not refresh/restart the original startup request.
                original.requireOriginal()
                f.exchange.acceptStop(f.parent, f.report("stop"))
                assertTrue(ended.await(3, TimeUnit.SECONDS)); assertTrue(run.isCompletelyStopped()); assertTrue(closed)
            } finally { run.close(); service.stopForeground(Service.STOP_FOREGROUND_REMOVE); controller.destroy() }
        } }
    }
}
