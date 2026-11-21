package io.gitlab.maik3531.magnolienotes.telefon

import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class NativeMediaSupportAttemptTest {
    private val at = 1_800_000_000_000L
    private val sid = ByteArray(16) { 3 }
    private val phoneKey = ByteArray(32) { 1 }
    private val desktopKey = ByteArray(32) { 2 }
    private val phonePrefix = ByteArray(4) { 4 }
    private val desktopPrefix = ByteArray(4) { 5 }

    private fun header(sequence: Long, direction: String) = JsonObject(mapOf(
        "p" to JsonPrimitive(TelefonParameter.PROTOKOLL), "sid" to JsonPrimitive(TelefonKrypto.b64(sid)),
        "seq" to JsonPrimitive(sequence), "dir" to JsonPrimitive(direction)))

    private fun exchange(block: (TelefonTcpRoehre, TelefonSecureChannel, Socket) -> Unit) {
        ServerSocket(0, 2, InetAddress.getByName("127.0.0.1")).use { listener ->
            TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { pipe ->
                listener.accept().use { desktop ->
                    desktop.soTimeout = 2_000
                    TelefonSecureChannel(pipe.input, pipe.output, sid.copyOf(), phoneKey.copyOf(), phonePrefix.copyOf(),
                        desktopKey.copyOf(), desktopPrefix.copyOf()).use { channel -> block(pipe, channel, desktop) }
                }
            }
        }
    }

    private fun send(desktop: Socket, sequence: Long, frame: JsonObject) {
        val header = header(sequence, "desktop_to_phone")
        val bytes = TelefonKrypto.verschluesseln(desktopKey, TelefonKrypto.nonce(desktopPrefix, sequence),
            TelefonKanonisch.bytes(frame), TelefonKanonisch.bytes(header))
        TelefonRahmen.schreiben(desktop.getOutputStream(), JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(bytes)))),
            TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
    }

    private fun receive(desktop: Socket, sequence: Long): JsonObject {
        val frame = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
        val header = header(sequence, "phone_to_desktop")
        assertEquals(header, JsonObject(frame - "ciphertext"))
        val ciphertext = java.util.Base64.getDecoder().decode(frame.string("ciphertext"))
        val bytes = TelefonKrypto.entschluesseln(phoneKey, TelefonKrypto.nonce(phonePrefix, sequence),
            ciphertext, TelefonKanonisch.bytes(header))
        return TelefonKanonisch.json.parseToJsonElement(bytes.decodeToString()).jsonObject
    }

    @Test fun supportRequiresTwoAcknowledgedOffersAndDoesNotReappearAfterWithdrawal() = exchange { pipe, channel, desktop ->
        var live = true
        NativeMediaSupportAttempt(channel, pipe, { live }, { at }, { 100L }).use { attempt ->
            assertFalse(attempt.supports(channel))
            assertTrue(attempt.send())
            val own = receive(desktop, 0)
            assertTrue(NativeMediaSupportAttempt.valid(own, at))
            send(desktop, 0, NativeMediaSupportAttempt.ack(own))
            assertTrue(attempt.receive(channel, channel.receive()))
            assertFalse(attempt.supports(channel))
            val remote = NativeMediaSupportAttempt.offer(at)
            send(desktop, 1, remote)
            assertTrue(attempt.receive(channel, channel.receive()))
            assertEquals(NativeMediaSupportAttempt.ack(remote), receive(desktop, 1))
            assertTrue(attempt.supports(channel))
            live = false
            assertFalse(attempt.supports(channel))
            live = true
            assertFalse(attempt.supports(channel))
            assertFalse(attempt.send())
        }
        val heartbeat = JsonObject(mapOf("type" to JsonPrimitive("ping")))
        channel.send(heartbeat)
        assertEquals(heartbeat, receive(desktop, 2))
    }

    @Test fun expiredOrDifferentFeatureDoesNotEstablishSupport() = exchange { pipe, channel, desktop ->
        var tick = 100L
        NativeMediaSupportAttempt(channel, pipe, { true }, { at }, { tick }).use { attempt ->
            val wrong = JsonObject(NativeMediaSupportAttempt.offer(at) + ("body" to JsonObject(mapOf(
                "format" to JsonPrimitive(1), "feature" to JsonPrimitive("pc_image_batch")))))
            send(desktop, 0, wrong)
            assertFalse(attempt.receive(channel, channel.receive()))
            assertTrue(attempt.send())
            val own = receive(desktop, 0)
            tick += NativeMediaSupportAttempt.TTL
            send(desktop, 1, NativeMediaSupportAttempt.ack(own))
            assertFalse(attempt.receive(channel, channel.receive()))
            assertFalse(attempt.supports(channel))
        }
    }
}
