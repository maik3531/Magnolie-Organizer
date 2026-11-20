package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Activity
import android.app.Application
import android.content.Intent
import android.os.Looper
import androidx.activity.ComponentActivity
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.util.Base64

/** Actual encrypted parent + ActivityResult dialog handoff, no system capture. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PhoneScreenNotesRunTest {
    private class Fixture : AutoCloseable {
        val activityController = Robolectric.buildActivity(ComponentActivity::class.java).setup()
        val activity = activityController.get()
        val host = PhoneScreenConsentHost(activity) { false }
        val listener = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        val pipe = TelefonTcpRoehre("127.0.0.1", port = listener.localPort)
        val desktop = listener.accept().also { it.soTimeout = 2_000 }
        val sid = ByteArray(16) { 3 }
        val send = ByteArray(32) { 1 }
        val recv = ByteArray(32) { 2 }
        val sendPrefix = ByteArray(4) { 4 }
        val recvPrefix = ByteArray(4) { 5 }
        val parent = TelefonSecureChannel(pipe.input, pipe.output, sid, send, sendPrefix, recv, recvPrefix)
        var live = true
        val run = PhoneScreenNotesRun(activity, parent, pipe, { check(live) }, { host })
        var sequence = 0L

        fun probe() = readControl(0)

        fun readControl(sequence: Long): JsonObject {
            val packet = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
            val header = JsonObject(packet - "ciphertext")
            assertEquals(JsonPrimitive(sequence), header["seq"])
            val clear = TelefonKrypto.entschluesseln(send, TelefonKrypto.nonce(sendPrefix, sequence),
                Base64.getDecoder().decode(packet.string("ciphertext")), TelefonKanonisch.bytes(header))
            return PhoneScreenControl.validateMessage(TelefonKanonisch.json.parseToJsonElement(clear.decodeToString()).jsonObject)
        }

        fun offer(probe: JsonObject) = JsonObject(probe + mapOf("op" to JsonPrimitive("offer"), "session" to JsonPrimitive("a".repeat(32)),
            "secret" to JsonPrimitive("b".repeat(64)), "port" to JsonPrimitive(55555), "width" to JsonPrimitive(720),
            "height" to JsonPrimitive(1600), "density" to JsonPrimitive(160)))

        fun deliver(body: JsonObject): Boolean {
            val message = TelefonNachrichten.message(PhoneScreenControl.REPORT, body, 60_000)
            val header = JsonObject(mapOf("p" to JsonPrimitive(TelefonParameter.PROTOKOLL), "sid" to JsonPrimitive(TelefonKrypto.b64(sid)),
                "seq" to JsonPrimitive(sequence), "dir" to JsonPrimitive("desktop_to_phone")))
            val cipher = TelefonKrypto.verschluesseln(recv, TelefonKrypto.nonce(recvPrefix, sequence++),
                TelefonKanonisch.bytes(message), TelefonKanonisch.bytes(header))
            TelefonRahmen.schreiben(desktop.getOutputStream(), JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(cipher)))))
            return run.receive(parent, parent.receive())
        }

        fun idle() = Shadows.shadowOf(Looper.getMainLooper()).idle()

        fun drained() {
            val deadline = System.nanoTime() + 2_000_000_000L
            while (!run.isDrained() && System.nanoTime() - deadline < 0) { idle(); Thread.sleep(10) }
            assertTrue(run.isDrained())
        }

        override fun close() {
            run.close()
            drained()
            host.close()
            activityController.pause().stop().destroy()
            parent.close(); pipe.close(); desktop.close(); listener.close()
        }
    }

    @Test fun originalEncryptedOfferPromptsOnceAndActualDenialRetiresWithoutService() {
        Fixture().use { f ->
            val shadow = Shadows.shadowOf(f.activity)
            f.run.start()
            val probe = f.probe()
            assertEquals("probe", probe.string("op"))
            assertNull(shadow.nextStartedActivityForResult)
            val offer = f.offer(probe)
            assertTrue(f.deliver(offer))
            assertFalse(f.deliver(offer))
            f.idle()
            val launched = checkNotNull(shadow.nextStartedActivityForResult)
            assertNotNull(launched.intent.component)
            f.activity.activityResultRegistry.dispatchResult(launched.requestCode, Activity.RESULT_CANCELED, null)
            f.drained()
            assertNotNull(f.run.failure)
            val error = f.readControl(1)
            assertEquals("error", error.string("op"))
            assertEquals("permission_denied", error.string("reason"))
            assertEquals(offer["session"], error["session"])
            assertNull(shadow.nextStartedService)
            assertFalse(f.pipe.isClosed)
        }
    }

    @Test fun peerStopWhileConsentPendingCannotStartServiceFromLateResult() {
        Fixture().use { f ->
            f.run.start()
            val probe = f.probe()
            val offer = f.offer(probe)
            assertTrue(f.deliver(offer))
            f.idle()
            val launched = checkNotNull(Shadows.shadowOf(f.activity).nextStartedActivityForResult)
            val stop = JsonObject(probe + mapOf("op" to JsonPrimitive("stop"), "session" to offer.getValue("session")))
            assertTrue(f.deliver(stop))
            f.drained()
            f.activity.activityResultRegistry.dispatchResult(launched.requestCode, Activity.RESULT_OK, Intent())
            f.idle()
            assertNull(Shadows.shadowOf(f.activity).nextStartedService)
            assertFalse(f.pipe.isClosed)
            assertTrue(f.run.isDrained())
            f.desktop.soTimeout = 100
            assertThrows(SocketTimeoutException::class.java) { f.desktop.getInputStream().read() }
        }
    }
}
