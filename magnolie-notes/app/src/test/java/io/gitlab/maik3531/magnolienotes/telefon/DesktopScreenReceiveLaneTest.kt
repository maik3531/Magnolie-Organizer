package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.security.MessageDigest
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Test

class DesktopScreenReceiveLaneTest {
    private val session = ByteArray(16) { it.toByte() }
    private val secret = ByteArray(32) { (it + 32).toByte() }
    private val context = "magnolie-desktop-screen-send/1\u0000desktop_to_phone\u0000".toByteArray() +
        session + byteArrayOf(2, 0, 57, 0, 33)
    private val challenge = ByteArray(16) { (it + 80).toByte() }
    private val heartbeat = "000000100000000000000000bfb6de89f9e5ca0e92e7696a2a090be9".chunked(2)
        .map { it.toInt(16).toByte() }.toByteArray()

    private fun pair(action: (SocketChannel, SocketChannel) -> Unit) {
        ServerSocketChannel.open().use { server ->
            server.bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0))
            SocketChannel.open(server.localAddress).use { phone ->
                server.accept().use { desktop ->
                    desktop.socket().soTimeout = 1500
                    action(phone, desktop)
                }
            }
        }
    }

    private fun lane(phone: SocketChannel) = DesktopScreenReceiveLane(phone, session, secret, 2, 57, 33,
        System.nanoTime() + TimeUnit.SECONDS.toNanos(4)) { }

    private fun prove(lane: DesktopScreenReceiveLane, desktop: SocketChannel, role: Int = 1): ByteArray {
        val worker = Executors.newSingleThreadExecutor()
        val task = worker.submit(Callable { lane.prove() })
        try {
            val input = desktop.socket().getInputStream()
            val phone = ByteArray(16)
            java.io.DataInputStream(input).readFully(phone)
            val transcript = context + phone + challenge
            fun signature(role: Int) = Mac.getInstance("HmacSHA256").run {
                init(SecretKeySpec(secret, "HmacSHA256"))
                doFinal("magnolie-desktop-screen-proof/1\u0000".toByteArray() + byteArrayOf(role.toByte()) + transcript)
            }
            desktop.socket().getOutputStream().write(challenge + signature(role))
            if (role == 1) {
                val reply = ByteArray(32)
                java.io.DataInputStream(input).readFully(reply)
                assertArrayEquals(signature(2), reply)
            }
            val digest = task.get(2, TimeUnit.SECONDS)
            assertArrayEquals(MessageDigest.getInstance("SHA-256").digest(transcript), digest)
            return digest
        } finally {
            worker.shutdownNow()
            assertTrue(worker.awaitTermination(2, TimeUnit.SECONDS))
        }
    }

    @Test fun authenticatesHeartbeatAndDeniesReplay() = pair { phone, desktop ->
        lane(phone).use { lane ->
            lane.activate(prove(lane, desktop))
            desktop.socket().getOutputStream().write(heartbeat)
            assertArrayEquals(ByteArray(0), lane.receive())
            desktop.socket().getOutputStream().write(heartbeat)
            assertThrows(IllegalStateException::class.java) { lane.receive() }
            assertFalse(phone.isOpen)
        }
    }

    @Test fun proofAndPreparedDoNotAuthorizeReading() = pair { phone, desktop ->
        lane(phone).use { lane ->
            prove(lane, desktop)
            desktop.socket().getOutputStream().write(heartbeat)
            assertThrows(IllegalStateException::class.java) { lane.receive() }
            assertFalse(phone.isOpen)
        }
    }

    @Test fun rejectsOtherReceiptAndReflectedRole() {
        pair { phone, desktop ->
            lane(phone).use { lane ->
                val wrong = prove(lane, desktop).apply { this[0] = (this[0].toInt() xor 1).toByte() }
                assertThrows(IllegalStateException::class.java) { lane.activate(wrong) }
                assertFalse(phone.isOpen)
            }
        }
        pair { phone, desktop ->
            lane(phone).use { lane ->
                val error = assertThrows(ExecutionException::class.java) { prove(lane, desktop, 2) }
                assertTrue(error.cause is IllegalStateException)
                assertFalse(phone.isOpen)
            }
        }
    }

    @Test fun rejectsOversizeAndDamagedTag() {
        for (record in listOf(ByteBuffer.allocate(12).putInt(1_048_593).putLong(0).array(),
            heartbeat.clone().apply { this[lastIndex] = (last().toInt() xor 1).toByte() })) {
            pair { phone, desktop ->
                lane(phone).use { lane ->
                    lane.activate(prove(lane, desktop))
                    desktop.socket().getOutputStream().write(record)
                    assertThrows(Exception::class.java) { lane.receive() }
                    assertFalse(phone.isOpen)
                }
            }
        }
    }

    @Test fun closeInterruptsIncompleteRecordAndDoesNotRenewExpiredSetup() {
        pair { phone, desktop ->
            lane(phone).use { lane ->
                lane.activate(prove(lane, desktop))
                desktop.socket().getOutputStream().write(heartbeat.copyOf(12))
                val worker = Executors.newSingleThreadExecutor()
                val entered = CountDownLatch(1)
                val result = worker.submit(Callable { entered.countDown(); lane.receive() })
                try {
                    assertTrue(entered.await(1, TimeUnit.SECONDS))
                    lane.close()
                    val error = assertThrows(ExecutionException::class.java) { result.get(1, TimeUnit.SECONDS) }
                    assertTrue(error.cause is IOException)
                } finally { worker.shutdownNow() }
            }
        }
        pair { phone, _ ->
            assertThrows(SocketTimeoutException::class.java) {
                DesktopScreenReceiveLane(phone, session, secret, 2, 57, 33, System.nanoTime() - 1) { }
            }
            assertFalse(phone.isOpen)
        }
    }
}
