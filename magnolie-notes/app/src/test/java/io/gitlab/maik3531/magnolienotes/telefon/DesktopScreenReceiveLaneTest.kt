package io.gitlab.maik3531.magnolienotes.telefon

import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
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
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import javax.imageio.ImageIO
import org.junit.Assert.*
import org.junit.Test

class DesktopScreenReceiveLaneTest {
    private val session = ByteArray(16) { it.toByte() }
    private val secret = ByteArray(32) { (it + 32).toByte() }
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

    private fun respond(desktop: SocketChannel, role: Int = 1) = DesktopScreenDraftPeer.respond(desktop, role)

    private fun prove(lane: DesktopScreenReceiveLane, desktop: SocketChannel, role: Int = 1): ByteArray {
        val worker = Executors.newSingleThreadExecutor()
        val task = worker.submit(Callable { lane.prove() })
        try {
            val expected = respond(desktop, role)
            val digest = task.get(2, TimeUnit.SECONDS)
            assertArrayEquals(expected, digest)
            return digest
        } finally {
            worker.shutdownNow()
            assertTrue(worker.awaitTermination(2, TimeUnit.SECONDS))
        }
    }

    @Test fun ownerCannotPresentBeforePreparedReturnsOrAcceptForeignSend() {
        pair { phone, desktop -> exerciseOwner(phone, desktop, stopBeforeReturn = false) }
    }

    @Test fun ownerClosesDataSocketButWaitsForWriterToDrain() {
        pair { phone, desktop -> exerciseOwner(phone, desktop, stopBeforeReturn = true) }
    }

    private fun exerciseOwner(phone: SocketChannel, desktop: SocketChannel, stopBeforeReturn: Boolean) {
        val parent = Any()
        val entering = CountDownLatch(1)
        val release = CountDownLatch(1)
        val presented = CountDownLatch(1)
        val stopped = CountDownLatch(1)
        val jpeg = ByteArrayOutputStream().also {
            assertTrue(ImageIO.write(BufferedImage(57, 33, BufferedImage.TYPE_INT_RGB), "jpeg", it))
        }.toByteArray()
        val frames = java.util.concurrent.LinkedBlockingQueue<ByteArray>()
        val opened = java.util.concurrent.atomic.AtomicBoolean(false)
        val run = DesktopScreenReceiveRun(parent, session, secret, 2, 57, 33,
            System.nanoTime() + TimeUnit.SECONDS.toNanos(4), {},
            { guard -> guard(); opened.set(true); phone },
            { _, guard -> guard(); entering.countDown(); check(release.await(2, TimeUnit.SECONDS)) },
            { data -> frames.add(data.copyOf()); presented.countDown() }, stopped::countDown)
        try {
            assertFalse(opened.get())
            assertFalse(run.acceptSend(parent, ByteArray(32)))
            run.start()
            val transcript = respond(desktop)
            assertTrue(entering.await(1, TimeUnit.SECONDS))
            assertFalse(run.acceptSend(Any(), transcript))
            assertFalse(run.acceptSend(parent, ByteArray(32)))
            assertTrue(run.acceptSend(parent, transcript))
            assertFalse(run.acceptSend(parent, transcript))
            desktop.socket().getOutputStream().write(record(jpeg, 0))
            assertFalse(presented.await(60, TimeUnit.MILLISECONDS))
            if (stopBeforeReturn) {
                run.close()
                assertFalse(phone.isOpen)
                assertFalse(run.drained)
                assertFalse(run.acceptSend(parent, transcript))
            }
            release.countDown()
            if (!stopBeforeReturn) {
                assertTrue(presented.await(1, TimeUnit.SECONDS))
                assertArrayEquals(jpeg, frames.remove())
                run.close()
            }
            assertTrue(stopped.await(1, TimeUnit.SECONDS))
        } finally {
            release.countDown()
            run.close()
        }
        val end = System.nanoTime() + TimeUnit.SECONDS.toNanos(1)
        while (!run.drained && System.nanoTime() - end < 0) Thread.sleep(5)
        assertTrue(run.drained)
        assertTrue(frames.isEmpty())
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

    @Test fun authenticatesAndChecksExactBaselineShapeBeforeHandoff() {
        val jpeg = ByteArrayOutputStream().also {
            assertTrue(ImageIO.write(BufferedImage(57, 33, BufferedImage.TYPE_INT_RGB), "jpeg", it))
        }.toByteArray()
        pair { phone, desktop ->
            lane(phone).use { lane ->
                lane.activate(prove(lane, desktop))
                desktop.socket().getOutputStream().write(record(jpeg, 0))
                assertArrayEquals(jpeg, lane.receive())
                val wrong = ByteArrayOutputStream().also {
                    assertTrue(ImageIO.write(BufferedImage(58, 33, BufferedImage.TYPE_INT_RGB), "jpeg", it))
                }.toByteArray()
                desktop.socket().getOutputStream().write(record(wrong, 1))
                assertThrows(IllegalArgumentException::class.java) { lane.receive() }
                assertFalse(phone.isOpen)
            }
        }
        val sof = (2 until jpeg.lastIndex).first { jpeg[it] == 0xff.toByte() && jpeg[it + 1] == 0xc0.toByte() }
        assertThrows(IllegalArgumentException::class.java) {
            requireDesktopScreenJpeg(jpeg.clone().apply { this[sof + 1] = 0xc2.toByte() }, 57, 33)
        }
        assertThrows(IllegalArgumentException::class.java) { requireDesktopScreenJpeg(jpeg.copyOf(jpeg.size - 1), 57, 33) }
    }

    private fun record(data: ByteArray, ordinal: Long) = DesktopScreenDraftPeer.record(data, ordinal)

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

/** Independent synthetic peer using the known draft record vector. */
internal object DesktopScreenDraftPeer {
    fun session() = ByteArray(16) { it.toByte() }
    fun secret() = ByteArray(32) { (it + 32).toByte() }
    private val context = "magnolie-desktop-screen-send/1\u0000desktop_to_phone\u0000".toByteArray() +
        session() + byteArrayOf(2, 0, 57, 0, 33)
    private val challenge = ByteArray(16) { (it + 80).toByte() }

    fun respond(desktop: SocketChannel, role: Int = 1): ByteArray {
        val input = java.io.DataInputStream(desktop.socket().getInputStream())
        val phone = ByteArray(16).also(input::readFully)
        val transcript = context + phone + challenge
        fun signature(role: Int) = Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(secret(), "HmacSHA256"))
            doFinal("magnolie-desktop-screen-proof/1\u0000".toByteArray() + byteArrayOf(role.toByte()) + transcript)
        }
        desktop.socket().getOutputStream().write(challenge + signature(role))
        if (role == 1) assertArrayEquals(signature(2), ByteArray(32).also(input::readFully))
        return MessageDigest.getInstance("SHA-256").digest(transcript)
    }

    fun record(data: ByteArray, ordinal: Long): ByteArray {
        val material = "f2076c96174d23d200b45ec33273d4fe035e12da30dae7bd3f986b1f79a2976ee2fc6010"
            .chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val header = ByteBuffer.allocate(12).putInt(data.size + 16).putLong(ordinal).array()
        val nonce = ByteBuffer.allocate(12).put(material.copyOfRange(32, 36)).putLong(ordinal).array()
        return Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, SecretKeySpec(material.copyOf(32), "AES"), GCMParameterSpec(128, nonce))
            updateAAD(context)
            updateAAD(header)
            header + doFinal(data)
        }
    }
}
