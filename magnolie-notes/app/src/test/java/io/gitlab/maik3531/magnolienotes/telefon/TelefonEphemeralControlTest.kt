package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicBoolean

class TelefonEphemeralControlTest {
    private class Pipe(val blocking: Boolean = false) : TelefonRoehre {
        val bytes = ByteArrayOutputStream()
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val closed = AtomicBoolean(false)
        override val input = ByteArrayInputStream(ByteArray(0))
        override val output: OutputStream = object : OutputStream() {
            override fun write(value: Int) {
                if (blocking) {
                    entered.countDown(); check(release.await(3, TimeUnit.SECONDS))
                    if (closed.get()) throw IOException("original owned pipe closed")
                }
                bytes.write(value)
            }
        }
        override fun close() { closed.set(true); release.countDown() }
    }
    private fun channel(pipe: TelefonRoehre) = TelefonSecureChannel(pipe.input, pipe.output,
        ByteArray(16) { 3 }, ByteArray(32) { 1 }, ByteArray(4) { 4 }, ByteArray(32) { 2 }, ByteArray(4) { 5 })
    private val message get() = buildJsonObject { put("type", "ping"); put("sent_ms", 123) }
    private fun clear(frame: JsonObject, sequence: Long): JsonObject {
        assertEquals(JsonPrimitive(sequence), frame["seq"])
        val header = JsonObject(frame - "ciphertext")
        val cipher = java.util.Base64.getDecoder().decode(frame.string("ciphertext"))
        val bytes = TelefonKrypto.entschluesseln(ByteArray(32) { 1 }, TelefonKrypto.nonce(ByteArray(4) { 4 }, sequence),
            cipher, TelefonKanonisch.bytes(header))
        return TelefonKanonisch.json.parseToJsonElement(bytes.decodeToString()).jsonObject
    }

    @Test fun ephemeralAndOrdinaryFramesShareOriginalSequenceAndLeaveHealthyPipeOpen() {
        val pipe = Pipe(); val channel = channel(pipe)
        try {
            channel.sendEphemeral(message, pipe, {})
            channel.send(message)
            val input = ByteArrayInputStream(pipe.bytes.toByteArray())
            assertEquals(message, clear(TelefonRahmen.lesen(input), 0))
            assertEquals(message, clear(TelefonRahmen.lesen(input), 1))
            assertEquals(0, input.available()); assertFalse(pipe.closed.get())
        } finally { channel.close(); pipe.close() }
    }

    @Test fun blockedOriginalWriterHasBoundedAdmissionWithoutClosingTheParent() {
        val pipe = Pipe(blocking = true); val channel = channel(pipe)
        val worker = Thread { channel.send(message) }
        try {
            worker.start(); assertTrue(pipe.entered.await(2, TimeUnit.SECONDS))
            assertThrows(TimeoutException::class.java) { channel.sendEphemeral(message, pipe, {}, 30) }
            assertFalse(pipe.closed.get())
        } finally { pipe.release.countDown(); worker.join(3_000); channel.close(); pipe.close() }
        assertFalse(worker.isAlive)
        assertEquals(message, clear(TelefonRahmen.lesen(ByteArrayInputStream(pipe.bytes.toByteArray())), 0))
    }

    @Test fun originalOwnerIsRecheckedAfterWriterWaitBeforeAnyExtraFrameIsPublished() {
        val pipe = Pipe(blocking = true); val channel = channel(pipe)
        val original = Thread { channel.send(message) }
        val allowed = AtomicBoolean(true)
        val waiting = CountDownLatch(1)
        val failed = CountDownLatch(1)
        val ephemeral = Thread {
            try { channel.sendEphemeral(message, pipe, { waiting.countDown(); check(allowed.get()) }) }
            catch (_: IllegalStateException) { failed.countDown() }
        }
        try {
            original.start(); assertTrue(pipe.entered.await(2, TimeUnit.SECONDS))
            ephemeral.start(); assertTrue(waiting.await(1, TimeUnit.SECONDS))
            allowed.set(false); pipe.release.countDown()
            assertTrue(failed.await(2, TimeUnit.SECONDS)); assertFalse(pipe.closed.get())
        } finally {
            pipe.release.countDown(); original.join(3_000); ephemeral.join(3_000); channel.close(); pipe.close()
        }
        assertFalse(original.isAlive); assertFalse(ephemeral.isAlive)
        val input = ByteArrayInputStream(pipe.bytes.toByteArray())
        assertEquals(message, clear(TelefonRahmen.lesen(input), 0)); assertEquals(0, input.available())
    }

    @Test fun rejectionAfterEncryptionDoesNotConsumeASequenceOrCloseThePipe() {
        val pipe = Pipe(); val channel = channel(pipe)
        var checks = 0
        try {
            assertThrows(IllegalStateException::class.java) {
                channel.sendEphemeral(message, pipe, { checks++; check(checks != 3) })
            }
            assertEquals(0, pipe.bytes.size()); assertFalse(pipe.closed.get())
            channel.send(message)
            assertEquals(message, clear(TelefonRahmen.lesen(ByteArrayInputStream(pipe.bytes.toByteArray())), 0))
        } finally { channel.close(); pipe.close() }
    }

    @Test fun actualWriteDeadlineClosesOnlyTheOriginalBlockedPipeAndReleasesItsWriter() {
        val pipe = Pipe(blocking = true); val foreign = Pipe(); val channel = channel(pipe)
        try {
            assertThrows(IOException::class.java) { channel.sendEphemeral(message, pipe, {}, 150) }
            assertTrue(pipe.closed.get()); assertFalse(foreign.closed.get())
            // The timeout has released serialization; close cannot wait for an orphan writer.
            channel.close()
        } finally { pipe.close(); foreign.close(); channel.close() }
    }

    @Test fun foreignPipeAndOversizeControlsCannotReplaceOriginalTransportOwnership() {
        val pipe = Pipe(); val foreign = Pipe(); val channel = channel(pipe)
        try {
            assertThrows(IllegalStateException::class.java) { channel.sendEphemeral(message, foreign, {}) }
            assertThrows(IllegalArgumentException::class.java) {
                channel.sendEphemeral(buildJsonObject { put("padding", "x".repeat(4096)) }, pipe, {})
            }
            assertEquals(0, pipe.bytes.size()); assertFalse(pipe.closed.get()); assertFalse(foreign.closed.get())
        } finally { channel.close(); pipe.close(); foreign.close() }
    }

    @Test fun realTcpPipeExposesActualPinnedAddressesAndSupportsOriginalEncryptedControlWrite() {
        ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1")).use { listener ->
            TelefonTcpRoehre("127.0.0.1", port = listener.localPort).use { pipe ->
                listener.accept().use { desktop ->
                    desktop.soTimeout = 2_000
                    assertEquals(desktop.localAddress, pipe.remoteAddress)
                    assertEquals(desktop.inetAddress, pipe.localAddress)
                    assertFalse(pipe.isClosed)
                    channel(pipe).use { channel ->
                        channel.sendEphemeral(message, pipe, {})
                        assertEquals(message, clear(TelefonRahmen.lesen(desktop.getInputStream()), 0))
                    }
                }
            }
        }
    }
}
