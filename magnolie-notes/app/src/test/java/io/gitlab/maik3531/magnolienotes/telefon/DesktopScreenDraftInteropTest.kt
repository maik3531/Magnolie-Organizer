package io.gitlab.maik3531.magnolienotes.telefon

import java.io.ByteArrayInputStream
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.imageio.ImageIO
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class DesktopScreenDraftInteropTest {
    @Test fun realEncryptedControlAndJpegWithLinuxDraftCounterpart() {
        // Opt-in: ordinary Android builds must not need a host Python install.
        assumeTrue(System.getenv("MAGNOLIE_DESKTOP_SCREEN_INTEROP") == "1")
        val script = File("../magnolie-organizer/pruefungen/desktop_screen_draft_interop_peer.py").canonicalFile
        assertTrue(script.isFile)
        val server = ProcessBuilder("/usr/bin/python3", "-B", script.path)
            .redirectError(ProcessBuilder.Redirect.INHERIT).start()
        val readPort = Executors.newSingleThreadExecutor()
        try {
            val port = readPort.submit<Int> { checkNotNull(server.inputStream.bufferedReader().readLine()).toInt() }
                .get(4, TimeUnit.SECONDS)
            TelefonTcpRoehre("127.0.0.1", port = port).use { pipe ->
                pipe.setReadTimeout(4_000)
                TelefonSecureChannel(pipe.input, pipe.output, ByteArray(16), ByteArray(32) { 1 }, ByteArray(4) { 4 },
                    ByteArray(32) { 2 }, ByteArray(4) { 5 }).use { parent ->
                    val wire = DesktopScreenDraftPhoneChannel(parent, pipe) { }
                    DesktopScreenDraftPhoneRequest(wire, 2, 10_000).use { original ->
                        original.writeRequest()
                        assertTrue(original.receive(parent, parent.receive()))
                        val offer = checkNotNull(original.takeOffer())
                        fun hex(key: String) = (offer[key] as JsonPrimitive).content.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
                        val mediaPort = (offer["port"] as JsonPrimitive).content.toInt()
                        openPhoneScreenWlanSocket(pipe, mediaPort, original::requireCurrent).use { data ->
                            DesktopScreenReceiveLane(data, hex("session"), hex("secret"), 2, 57, 33,
                                original.setupDeadlineNanos, original::requireCurrent).use { lane ->
                                val proof = lane.prove()
                                original.writePrepared(proof) { }
                                assertTrue(original.receive(parent, parent.receive()))
                                lane.activate(checkNotNull(original.takeSend()))
                                assertTrue(lane.receive().isEmpty())
                                val rgb = ImageIO.read(ByteArrayInputStream(lane.receive()))
                                assertEquals(57 to 33, rgb.width to rgb.height)
                                val pixel = rgb.getRGB(28, 16)
                                assertTrue(kotlin.math.abs((pixel shr 8 and 255) - 110) <= 4)
                                assertTrue(kotlin.math.abs((pixel and 255) - 228) <= 4)
                                val stop = JsonObject(offer.filterKeys { it in setOf("draft", "request", "mode", "setup_until_ms", "session") } +
                                    ("op" to JsonPrimitive("stop")))
                                original.close()
                                wire.write(stop) { }
                            }
                        }
                    }
                    parent.send(JsonObject(mapOf("type" to JsonPrimitive("ping"))))
                    assertEquals(JsonPrimitive("pong"), parent.receive()["type"])
                }
            }
            assertTrue(server.waitFor(3, TimeUnit.SECONDS))
            assertEquals(0, server.exitValue())
        } finally {
            if (server.isAlive) server.destroyForcibly().waitFor(2, TimeUnit.SECONDS)
            readPort.shutdownNow()
        }
    }
}
