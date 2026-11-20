package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.io.DataInputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.util.concurrent.atomic.AtomicBoolean

class PhoneScreenSendRunTest {
    private class Context(val sender: SocketChannel, val receiver: SocketChannel) : AutoCloseable {
        val pending = PhoneScreenFrameSlot(17, 16)
        val approval = AtomicBoolean(false)
        val current = AtomicBoolean(true)
        val run = PhoneScreenSendRun(sender, ByteArray(16) { it.toByte() }, ByteArray(32) { it.toByte() },
            17, 16, pending, { check(current.get()) { "projection withdrawn" } }, approval::get)
        val input = DataInputStream(receiver.socket().getInputStream())
        fun proof() {
            receiver.socket().getOutputStream().write(ByteArray(16) { (16 + it).toByte() })
            val proof = ByteArray(32).also { input.readFully(it) }.joinToString("") { "%02x".format(it.toInt() and 255) }
            assertEquals("8151fa3e157e140cde257828478f01b806cce5a5093a329c62e704f8b9ffbc8d", proof)
        }
        fun enqueue() = PhoneScreenJpegOutput.Frame(17, 16, 0, "first".toByteArray()).also { assertTrue(pending.offer(it)) }
        fun assertDrained() {
            val end = System.nanoTime() + 2_000_000_000L
            while (!run.isDrained() && System.nanoTime() - end < 0) Thread.sleep(10)
            assertTrue(run.isDrained())
        }
        override fun close() { run.close(); assertDrained() }
    }

    private fun connected(test: (Context) -> Unit) = ServerSocketChannel.open().use { listener ->
        listener.bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0))
        SocketChannel.open(listener.localAddress).use { sender ->
            listener.accept().use { receiver ->
                receiver.socket().soTimeout = 2_000
                Context(sender, receiver).use(test)
            }
        }
    }

    @Test fun originalProofAloneNeverTakesOrSendsFrameButOriginalSendDoes() = connected { f ->
        val frame = f.enqueue()
        f.run.start()
        f.proof()
        f.receiver.socket().soTimeout = 100
        assertThrows(SocketTimeoutException::class.java) { f.input.read() }
        assertArrayEquals("first".toByteArray(), frame.jpeg)
        f.receiver.socket().soTimeout = 2_000
        f.approval.set(true)
        val record = ByteArray(33).also { f.input.readFully(it) }.joinToString("") { "%02x".format(it.toInt() and 255) }
        assertEquals("000000150000000000000000ff4cf254a965f55e05d2cde81cd0c87f07d170c8a0", record)
        f.approval.set(false)
        assertEquals(-1, f.input.read())
        f.assertDrained()
        assertArrayEquals(ByteArray(5), frame.jpeg)
        assertTrue(f.run.failure is SecurityException)
        assertThrows(IllegalStateException::class.java) { f.run.start() }
    }

    @Test fun projectionWithdrawalWhileAwaitingSendRetiresOriginalWithoutMedia() = connected { f ->
        val frame = f.enqueue()
        f.run.start()
        f.proof()
        f.current.set(false)
        assertEquals(-1, f.input.read())
        f.assertDrained()
        assertEquals("projection withdrawn", f.run.failure?.message)
        assertArrayEquals(ByteArray(5), frame.jpeg)
        assertNull(f.pending.take())
    }

    @Test fun quietProjectionEmitsOnlyGuardedAuthenticatedHeartbeatsAfterSend() = connected { f ->
        f.run.start()
        f.proof()
        f.approval.set(true)
        val header = ByteArray(12).also { f.input.readFully(it) }
        val data = ByteArray(16).also { f.input.readFully(it) }
        assertEquals(16, java.nio.ByteBuffer.wrap(header).int)
        assertEquals("000000100000000000000000645ed91909ccdd8fc7eec4b153dbaa61",
            (header + data).joinToString("") { "%02x".format(it.toInt() and 255) })
        f.approval.set(false)
        assertEquals(-1, f.input.read())
        f.assertDrained()
    }
}
