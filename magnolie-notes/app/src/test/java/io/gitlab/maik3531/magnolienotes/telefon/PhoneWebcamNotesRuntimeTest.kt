package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.app.Service
import android.os.Looper
import android.os.SystemClock
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.DataInputStream
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicBoolean

/** Actual encrypted parent + permission/FGS adapters + actual media TCP socket;
 * generated capture buffers, not a physical Android capture acceptance. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneWebcamNotesRuntimeTest {
    private class Fixture(val generated: Boolean = true, register: Boolean = true) : AutoCloseable {
        val ui = PhoneWebcamPermissionHostTest.Fixture()
        val listener = ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))
        val pipe = TelefonTcpRoehre("127.0.0.1", port = listener.localPort)
        val desktop = listener.accept().also { it.soTimeout = 3_000 }
        val parent = TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16) { 3 }, ByteArray(32) { 1 },
            ByteArray(4) { 4 }, ByteArray(32) { 2 }, ByteArray(4) { 5 })
        val live = AtomicBoolean(true)
        var desktopSequence = 0L
        var phoneSequence = 0L
        var capturedClosed = false
        var sourceStarts = 0
        var service: org.robolectric.android.controller.ServiceController<PhoneWebcamCaptureService>? = null
        val runtime: PhoneWebcamNotesRuntime
        init {
            if (register) PhoneWebcamForeground.register(ui.host)
            val native = { check(live.get()) { "original native parent lost" } }
            val sender: (JsonObject, () -> Unit) -> Unit = { value, current -> parent.sendEphemeral(value, pipe, current) }
            runtime = if (!generated) PhoneWebcamNotesRuntime(ui.activity, parent, pipe, native, sender)
            else PhoneWebcamNotesRuntime(ui.activity, parent, pipe, native, sender) { actual, permission, sample, stopped ->
                object : PhoneWebcamCaptureDevice {
                    override fun start() {
                        sourceStarts++; permission.enterForeground(actual)
                        val time = SystemClock.elapsedRealtimeNanos()
                        sample(true, time, ByteArray(460800) { 75 }); sample(false, time, ByteArray(1920) { 42 })
                    }
                    override fun close() { if (!capturedClosed) { capturedClosed = true; stopped(null) } }
                    override fun isCompletelyStopped() = capturedClosed
                }
            }
            runtime.start()
        }
        fun fromPhone(): JsonObject {
            val value = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            val header = JsonObject(value - "ciphertext")
            assertEquals(JsonPrimitive(phoneSequence), header["seq"])
            assertEquals(JsonPrimitive("phone_to_desktop"), header["dir"])
            val cipher = java.util.Base64.getDecoder().decode(value.string("ciphertext"))
            val bytes = TelefonKrypto.entschluesseln(ByteArray(32) { 1 }, TelefonKrypto.nonce(ByteArray(4) { 4 }, phoneSequence++),
                cipher, TelefonKanonisch.bytes(header))
            return TelefonKanonisch.json.parseToJsonElement(bytes.decodeToString()).jsonObject
        }
        fun deliver(body: JsonObject): Boolean {
            val payload = TelefonNachrichten.message(PhoneWebcamControl.REPORT, body, 60_000)
            val header = buildJsonObject {
                put("p", TelefonParameter.PROTOKOLL); put("sid", TelefonKrypto.b64(ByteArray(16) { 3 }))
                put("seq", desktopSequence); put("dir", "desktop_to_phone")
            }
            val cipher = TelefonKrypto.verschluesseln(ByteArray(32) { 2 }, TelefonKrypto.nonce(ByteArray(4) { 5 }, desktopSequence++),
                TelefonKanonisch.bytes(payload), TelefonKanonisch.bytes(header))
            TelefonRahmen.schreiben(desktop.getOutputStream(), JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(cipher)))))
            return runtime.receive(parent.receive())
        }
        fun offer(probe: JsonObject, port: Int) = JsonObject(probe + mapOf("op" to JsonPrimitive("offer"),
            "session" to JsonPrimitive("a".repeat(32)), "secret" to JsonPrimitive("b".repeat(64)), "port" to JsonPrimitive(port),
            "muted" to JsonPrimitive(false), "front" to JsonPrimitive(false)))
        fun idleUntil(predicate: () -> Boolean) {
            val deadline = System.nanoTime() + 3_000_000_000L
            while (!predicate() && System.nanoTime() < deadline) {
                Shadows.shadowOf(Looper.getMainLooper()).idle(); Thread.sleep(5)
            }
            assertTrue(predicate())
        }
        fun grantAndStartService() {
            idleUntil { ui.host.requestPending }
            ui.grant(); ui.result()
            val intent = checkNotNull(Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).nextStartedService)
            org.robolectric.shadows.ShadowSystemClock.advanceBy(java.time.Duration.ofMillis(100))
            service = Robolectric.buildService(PhoneWebcamCaptureService::class.java).create().also {
                it.get().onStartCommand(intent, 0, 1)
            }
        }
        override fun close() {
            runtime.close()
            idleUntil { runtime.isCompletelyStopped() }
            service?.destroy()
            PhoneWebcamForeground.unregister(ui.host)
            ui.close(); parent.close(); pipe.close(); desktop.close(); listener.close()
        }
    }

    private fun packet(socket: java.net.Socket): ByteArray {
        socket.soTimeout = 2_000
        val input = DataInputStream(socket.getInputStream())
        val header = ByteArray(12); input.readFully(header)
        val length = java.nio.ByteBuffer.wrap(header).int
        check(length in 34..460834)
        val body = ByteArray(length); input.readFully(body)
        return header + body
    }

    @Test fun encryptedOfferUsesActualOsPermitAndServiceThenPinnedSocketAndMatchingSend() {
        Fixture().use { f -> ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1")).use { media ->
            media.soTimeout = 3_000
            val probe = (f.fromPhone()["body"] as JsonObject)
            assertEquals(JsonPrimitive("probe"), probe["op"]); assertEquals(0, f.sourceStarts)
            assertTrue(f.deliver(f.offer(probe, media.localPort)))
            f.grantAndStartService()
            media.accept().use { incoming ->
                val prepared = f.fromPhone()["body"] as JsonObject
                assertEquals(JsonPrimitive("prepared"), prepared["op"])
                assertEquals(1, f.sourceStarts)
                assertTrue(f.deliver(JsonObject(prepared + ("op" to JsonPrimitive("send")))))
                PhoneWebcamMediaCodec("a".repeat(32), ByteArray(32) { 0xbb.toByte() }) {}.use { expected ->
                    assertArrayEquals(expected.encode(false, 0, 0, ByteArray(1920) { 42 }), packet(incoming))
                    assertArrayEquals(expected.encode(true, 0, 0, ByteArray(460800) { 75 }), packet(incoming))
                }
                val foreign = JsonObject(prepared + mapOf("op" to JsonPrimitive("stop"), "nonce" to JsonPrimitive("c".repeat(64))))
                assertFalse(f.deliver(foreign)); assertFalse(f.capturedClosed)
                assertTrue(f.deliver(JsonObject(prepared + ("op" to JsonPrimitive("stop")))))
                f.idleUntil { f.runtime.isCompletelyStopped() }
                assertTrue(f.capturedClosed)
                assertFalse(f.pipe.isClosed) // Capture stop did not replace/close the encrypted parent.
            }
        } }
    }

    @Test fun deniedRealPermissionResultEmitsOnlyMatchingErrorAndNeverStartsService() {
        Fixture().use { f ->
            val probe = f.fromPhone()["body"] as JsonObject
            assertTrue(f.deliver(f.offer(probe, 24401)))
            f.idleUntil { f.ui.host.requestPending }
            f.ui.result(granted = false)
            val failure = f.fromPhone()["body"] as JsonObject
            assertEquals(JsonPrimitive("error"), failure["op"]); assertEquals(JsonPrimitive("permission_denied"), failure["reason"])
            f.idleUntil { f.runtime.isCompletelyStopped() }
            assertEquals(0, f.sourceStarts)
            assertNull(Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).nextStartedService)
            assertFalse(f.pipe.isClosed)
        }
    }

    @Test fun missingVisibleHostNeverLaunchesUiAndReportsForegroundRequired() {
        Fixture(register = false).use { f ->
            val probe = f.fromPhone()["body"] as JsonObject
            assertTrue(f.deliver(f.offer(probe, 24401)))
            f.idleUntil { f.runtime.terminalFailure != null }
            val failure = f.fromPhone()["body"] as JsonObject
            assertEquals(JsonPrimitive("foreground_required"), failure["reason"])
            f.idleUntil { f.runtime.isCompletelyStopped() }
            assertEquals(0, f.sourceStarts)
            assertNull(Shadows.shadowOf(f.ui.activity).lastRequestedPermission)
        }
    }

    @Test fun defaultNativeCameraFactoryFailsClosedInsteadOfClaimingGeneratedCapture() {
        Fixture(generated = false).use { f ->
            val probe = f.fromPhone()["body"] as JsonObject
            assertTrue(f.deliver(f.offer(probe, 24401)))
            f.grantAndStartService()
            val failure = f.fromPhone()["body"] as JsonObject
            assertEquals(JsonPrimitive("error"), failure["op"]); assertEquals(JsonPrimitive("capture_failed"), failure["reason"])
            f.idleUntil { f.runtime.isCompletelyStopped() }
            assertEquals(0, f.sourceStarts)
            assertFalse(f.pipe.isClosed)
        }
    }

    @Test fun parentRevocationWhileOsDialogIsPendingCannotStartServiceAfterLateGrant() {
        Fixture().use { f ->
            val probe = f.fromPhone()["body"] as JsonObject
            assertTrue(f.deliver(f.offer(probe, 24401)))
            f.idleUntil { f.ui.host.requestPending }
            f.live.set(false)
            f.runtime.close()
            f.ui.grant(); f.ui.result()
            f.idleUntil { f.runtime.isCompletelyStopped() }
            assertEquals(0, f.sourceStarts)
            assertNull(Shadows.shadowOf(RuntimeEnvironment.getApplication() as Application).nextStartedService)
            assertFalse(f.pipe.isClosed)
        }
    }
}
