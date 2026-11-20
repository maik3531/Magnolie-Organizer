package io.gitlab.maik3531.magnolienotes.telefon

import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Base64
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class DesktopScreenDraftPhoneChannelTest {
    private val sid = ByteArray(16) { 3 }
    private val sendKey = ByteArray(32) { 1 }
    private val sendPrefix = ByteArray(4) { 4 }
    private val receiveKey = ByteArray(32) { 2 }
    private val receivePrefix = ByteArray(4) { 5 }
    private val vectors = TelefonKanonisch.json.parseToJsonElement(
        File("../contracts/desktop-screen-control-draft-v1-vectors.json").readText()).jsonObject

    private fun channel(pipe: TelefonTcpRoehre) = TelefonSecureChannel(pipe.input, pipe.output, sid.copyOf(),
        sendKey.copyOf(), sendPrefix.copyOf(), receiveKey.copyOf(), receivePrefix.copyOf())

    private fun frame(body: JsonObject) = JsonObject(mapOf("type" to JsonPrimitive(DesktopScreenDraftPhoneChannel.TYPE), "body" to body))

    private fun desktopWrites(desktop: Socket, sequence: Long, body: JsonObject) {
        val header = JsonObject(mapOf("p" to JsonPrimitive(TelefonParameter.PROTOKOLL), "sid" to JsonPrimitive(TelefonKrypto.b64(sid)),
            "seq" to JsonPrimitive(sequence), "dir" to JsonPrimitive("desktop_to_phone")))
        val encrypted = TelefonKrypto.verschluesseln(receiveKey, TelefonKrypto.nonce(receivePrefix, sequence),
            TelefonKanonisch.bytes(frame(body)), TelefonKanonisch.bytes(header))
        TelefonRahmen.schreiben(desktop.getOutputStream(), JsonObject(header + ("ciphertext" to JsonPrimitive(TelefonKrypto.b64(encrypted)))),
            TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
    }

    private fun requestFrom(desktop: Socket, sequence: Long = 0): JsonObject {
        val encrypted = TelefonRahmen.lesen(desktop.getInputStream(), TelefonParameter.VERSCHLUESSELT_RAHMEN_MAX)
        val header = JsonObject(encrypted - "ciphertext")
        assertEquals(JsonPrimitive(sequence), header["seq"])
        assertEquals(JsonPrimitive("phone_to_desktop"), header["dir"])
        val bytes = TelefonKrypto.entschluesseln(sendKey, TelefonKrypto.nonce(sendPrefix, sequence),
            Base64.getDecoder().decode(encrypted.string("ciphertext")), TelefonKanonisch.bytes(header))
        val privateFrame = TelefonKanonisch.json.parseToJsonElement(bytes.decodeToString()).jsonObject
        assertEquals(JsonPrimitive(DesktopScreenDraftPhoneChannel.TYPE), privateFrame["type"])
        return privateFrame.getValue("body").jsonObject
    }

    @Test fun encryptedRequestAndSingleMatchingOfferBelongToOriginalWlan() {
        ServerSocket(0, 2, InetAddress.getByName("127.0.0.1")).use { listener ->
            TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { pipe ->
                listener.accept().use { desktop ->
                    desktop.soTimeout = 2_000
                    channel(pipe).use { parent ->
                        val original = DesktopScreenDraftPhoneChannel(parent, pipe) { }
                        val request = DesktopScreenDraftPhoneRequest(original, 2, 20_000)
                        request.use {
                            val template = JsonObject(vectors.getValue("request").jsonObject + vectors.getValue("offer_fields").jsonObject +
                                ("op" to JsonPrimitive("offer")))
                            assertFalse(request.receive(parent, frame(template)))
                            assertNull(request.takeOffer())
                            request.writeRequest()
                            val sent = requestFrom(desktop)
                            assertEquals(JsonPrimitive(2), sent["mode"])
                            DesktopScreenDraftControl.validate(sent, DesktopScreenDraftControl.Role.PHONE)
                            assertThrows(IllegalStateException::class.java) { request.writeRequest() }
                            val offer = JsonObject(sent + vectors.getValue("offer_fields").jsonObject + ("op" to JsonPrimitive("offer")))
                            channel(pipe).use { other -> assertFalse(request.receive(other, frame(offer))) }
                            desktopWrites(desktop, 0, JsonObject(offer + ("mode" to JsonPrimitive(1))))
                            assertFalse(request.receive(parent, parent.receive()))
                            assertNull(request.takeOffer())
                            desktopWrites(desktop, 1, offer)
                            assertTrue(request.receive(parent, parent.receive()))
                            assertEquals(offer, request.takeOffer())
                            desktopWrites(desktop, 2, offer)
                            assertFalse(request.receive(parent, parent.receive()))
                            assertNull(request.takeOffer())
                            val transcript = vectors.getValue("transcript") as JsonPrimitive
                            val receipt = transcript.content.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
                            val activeMessage = JsonObject(sent + mapOf("op" to JsonPrimitive("send"),
                                "session" to offer.getValue("session"), "transcript" to transcript))
                            desktopWrites(desktop, 3, activeMessage)
                            assertFalse(request.receive(parent, parent.receive()))
                            assertNull(request.takeSend())
                            request.writePrepared(receipt) { }
                            val prepared = requestFrom(desktop, 1)
                            assertEquals(JsonObject(activeMessage + ("op" to JsonPrimitive("prepared"))), prepared)
                            desktopWrites(desktop, 4, JsonObject(activeMessage + ("transcript" to JsonPrimitive("00".repeat(32)))))
                            assertFalse(request.receive(parent, parent.receive()))
                            assertNull(request.takeSend())
                            desktopWrites(desktop, 5, activeMessage)
                            assertTrue(request.receive(parent, parent.receive()))
                            assertArrayEquals(receipt, request.takeSend())
                            assertNull(request.takeSend())
                            desktopWrites(desktop, 6, activeMessage)
                            assertFalse(request.receive(parent, parent.receive()))
                            val stop = JsonObject(activeMessage - "transcript" + ("op" to JsonPrimitive("stop")))
                            desktopWrites(desktop, 7, stop)
                            assertTrue(request.receive(parent, parent.receive()))
                            assertThrows(IllegalStateException::class.java) { request.requireCurrent() }
                        }
                    }
                }
            }
        }
    }

    @Test fun wrongPipeAndRetiredDeadlineCannotConsumeWriterSequence() {
        ServerSocket(0, 2, InetAddress.getByName("127.0.0.1")).use { listener ->
            TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { pipe ->
                listener.accept().use { desktop ->
                    desktop.soTimeout = 2_000
                    channel(pipe).use { parent ->
                        TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { other ->
                            listener.accept().use {
                                val wrong = DesktopScreenDraftPhoneChannel(parent, other) {}
                                assertThrows(IllegalStateException::class.java) {
                                    wrong.write(vectors.getValue("request").jsonObject) { error("unexpected write") }
                                }
                            }
                        }
                        val original = DesktopScreenDraftPhoneChannel(parent, pipe) {}
                        var clock = 4L
                        DesktopScreenDraftPhoneRequest(original, 1, 10, { clock }).use { request ->
                            clock = request.setupDeadlineNanos
                            assertThrows(IllegalStateException::class.java) { request.writeRequest() }
                            clock = 4L
                            assertThrows(IllegalStateException::class.java) { request.writeRequest() }
                        }
                        DesktopScreenDraftPhoneRequest(original, 1, 20_000).use { request -> request.writeRequest() }
                        assertEquals(JsonPrimitive(1), requestFrom(desktop)["mode"])
                    }
                }
            }
        }
    }
}
