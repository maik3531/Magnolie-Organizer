package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket

class PhoneScreenControlTest {
    private val probe = JsonObject(mapOf("version" to JsonPrimitive(26), "op" to JsonPrimitive("probe"),
        "request_id" to JsonPrimitive("4b6aef60-a7bf-4a17-8a6b-56928034dd5d"), "nonce" to JsonPrimitive("a".repeat(64))))
    private val session = JsonPrimitive("c".repeat(32))
    private val offer = JsonObject(probe + mapOf("op" to JsonPrimitive("offer"), "session" to session, "secret" to JsonPrimitive("f".repeat(64)),
        "port" to JsonPrimitive(55443), "width" to JsonPrimitive(720), "height" to JsonPrimitive(1600), "density" to JsonPrimitive(160)))
    private fun control(op: String) = JsonObject(probe + mapOf("op" to JsonPrimitive(op), "session" to session))

    @Test fun schemaRequiresExactDirectionAndDimensionsAndNeverAcceptsAddress() {
        PhoneScreenControl.validateBody(offer, PhoneScreenControl.REPORT)
        assertThrows(IllegalArgumentException::class.java) { PhoneScreenControl.validateBody(offer, PhoneScreenControl.REQUEST) }
        for ((key, value) in listOf("host" to JsonPrimitive("example.invalid"), "width" to JsonPrimitive(true),
            "port" to JsonPrimitive("55443"), "density" to JsonPrimitive(1001), "version" to JsonPrimitive(26.0),
            "height" to JsonPrimitive(1921), "muted" to JsonPrimitive(false))) {
            assertThrows(IllegalArgumentException::class.java) { PhoneScreenControl.validateBody(JsonObject(offer + (key to value)), PhoneScreenControl.REPORT) }
        }
        val message = TelefonNachrichten.message(PhoneScreenControl.REPORT, offer, 60_000, now = 10_000)
        assertEquals(offer, PhoneScreenControl.validateMessage(message, 10_000))
        val tooLong = TelefonNachrichten.message(PhoneScreenControl.REPORT, offer, 60_001, now = 10_000)
        assertThrows(IllegalArgumentException::class.java) { PhoneScreenControl.validateMessage(tooLong, 10_000) }
    }

    @Test fun originalPreparedWriteAndSendDoNotPermitReplayOrRetarget() {
        val parent = Any()
        var now = 0L
        val owner = PhoneScreenNotesControl(parent, probe, {}, { now })
        assertFalse(owner.acceptOffer(Any(), offer))
        assertTrue(owner.acceptOffer(parent, offer))
        assertFalse(owner.acceptOffer(parent, offer))
        assertFalse(owner.receive(parent, control("send")))
        owner.prepared({}) { packet, guard ->
            guard()
            assertEquals(control("prepared"), packet)
            assertFalse(owner.hasOriginalSend())
        }
        assertFalse(owner.receive(Any(), control("send")))
        assertTrue(owner.receive(parent, control("send")))
        assertFalse(owner.receive(parent, control("send")))
        now = 60_000
        assertTrue(owner.hasOriginalSend())
        assertTrue(owner.receive(parent, control("stop")))
        assertThrows(IllegalStateException::class.java) { owner.hasOriginalSend() }
    }

    @Test fun captureLossDuringReadyWriteClosesOriginalOwner() {
        val parent = Any()
        var capture = true
        val owner = PhoneScreenNotesControl(parent, probe, {}, { 0 })
        assertTrue(owner.acceptOffer(parent, offer))
        assertThrows(IllegalStateException::class.java) {
            owner.prepared({ check(capture) }) { _, guard -> capture = false; guard() }
        }
        capture = true
        assertThrows(IllegalStateException::class.java) { owner.receive(parent, control("send")) }
    }

    @Test fun originalBoundedWriterUsesTheExactPipeAndEncryptsProbe() {
        ServerSocket(0, 2, InetAddress.getByName("127.0.0.1")).use { listener ->
            TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { pipe ->
                listener.accept().use { desktop ->
                    desktop.soTimeout = 2_000
                    val key = ByteArray(32) { 1 }
                    val prefix = ByteArray(4) { 4 }
                    TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16) { 3 }, key, prefix,
                        ByteArray(32) { 2 }, ByteArray(4) { 5 }).use { parent ->
                        var live = true
                        val native = PhoneScreenNotesChannel(parent, pipe, requireCurrent = { check(live) })
                        live = false
                        assertThrows(IllegalStateException::class.java) { native.write(probe) }
                        live = true
                        native.write(probe)
                        val frame = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
                        val header = JsonObject(frame - "ciphertext")
                        assertEquals(JsonPrimitive(0), header["seq"])
                        val bytes = TelefonKrypto.entschluesseln(key, TelefonKrypto.nonce(prefix, 0),
                            java.util.Base64.getDecoder().decode(frame.string("ciphertext")), TelefonKanonisch.bytes(header))
                        val payload = TelefonKanonisch.json.parseToJsonElement(bytes.decodeToString()).jsonObject
                        assertEquals(probe, PhoneScreenControl.validateMessage(payload))
                    }
                }
            }
        }
    }
}
