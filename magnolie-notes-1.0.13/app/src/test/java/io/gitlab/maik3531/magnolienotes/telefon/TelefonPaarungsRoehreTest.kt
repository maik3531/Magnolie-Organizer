package io.gitlab.maik3531.magnolienotes.telefon

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class TelefonPaarungsRoehreTest {
    @Test fun `real TCP preserves telephone framing through pairing pipe`() {
        ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { listener ->
            val result = CompletableFuture<Unit>()
            val frame = buildJsonObject {
                put("p", JsonPrimitive(TelefonParameter.PROTOKOLL))
                put("type", JsonPrimitive("pair_abort"))
                put("reason", JsonPrimitive("code_mismatch"))
            }
            thread(isDaemon = true) {
                try {
                    listener.accept().use { socket ->
                        socket.soTimeout = 2000
                        assertEquals(frame, TelefonRahmen.lesen(socket.getInputStream()))
                        TelefonRahmen.schreiben(socket.getOutputStream(), frame)
                    }
                    result.complete(Unit)
                } catch (error: Throwable) { result.completeExceptionally(error) }
            }
            TelefonPaarungsRoehre(TelefonTcpRoehre(requireNotNull(listener.inetAddress.hostAddress),
                port = listener.localPort)).use { pipe ->
                TelefonRahmen.schreiben(pipe.output, frame)
                assertEquals(frame, TelefonRahmen.lesen(pipe.input))
            }
            result.get(3, TimeUnit.SECONDS)
        }
    }

    @Test fun `deadline interrupts blocked real TCP read`() {
        ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { listener ->
            val client = TelefonTcpRoehre(requireNotNull(listener.inetAddress.hostAddress), port = listener.localPort)
            listener.accept().use { server ->
                TelefonPaarungsRoehre(client, 100).use { pipe ->
                    assertThrows(IOException::class.java) { pipe.input.read() }
                    server.soTimeout = 2000
                    assertEquals(-1, server.getInputStream().read())
                }
            }
        }
    }

    @Test fun `RFCOMM shaped streams close exactly once on deadline and cancel`() {
        val closed = CountDownLatch(1)
        val closes = AtomicInteger()
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = ByteArrayOutputStream()
            override fun close() { closes.incrementAndGet(); closed.countDown() }
        }
        val pairing = TelefonPaarungsRoehre(pipe, 10)
        assertTrue(closed.await(2, TimeUnit.SECONDS))
        pairing.close()
        pairing.close()
        assertEquals(1, closes.get())
    }

    @Test fun `immediate expiry cannot access uninitialized scheduled future`() {
        val closed = CountDownLatch(1)
        val pipe = object : TelefonRoehre {
            override val input = ByteArrayInputStream(byteArrayOf())
            override val output = ByteArrayOutputStream()
            override fun close() { closed.countDown() }
        }
        TelefonPaarungsRoehre(pipe, 0).use {
            assertTrue(closed.await(2, TimeUnit.SECONDS))
        }
    }
}
