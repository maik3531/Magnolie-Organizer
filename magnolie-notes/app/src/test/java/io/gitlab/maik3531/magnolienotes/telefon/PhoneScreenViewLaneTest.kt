package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel

class PhoneScreenViewLaneTest {
    private fun connected(test: (SocketChannel, SocketChannel) -> Unit) {
        ServerSocketChannel.open().use { listener ->
            listener.bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0))
            SocketChannel.open(listener.localAddress).use { producer ->
                listener.accept().use { receiver ->
                    receiver.socket().soTimeout = 2_000
                    test(producer, receiver)
                }
            }
        }
    }

    private fun lane(socket: SocketChannel, guard: () -> Unit = {}) =
        PhoneScreenViewLane(socket, ByteArray(16) { it.toByte() }, ByteArray(32) { it.toByte() }, 17, 16, guard)

    private fun frame(payload: String) = PhoneScreenJpegOutput.Frame(17, 16, 0, payload.toByteArray())

    @Test fun actualSocketEmitsTheSameTwoWireRecordsAsLinuxAndClearsOwnedPictures() = connected { producer, receiver ->
        val first = frame("first")
        val second = frame("second")
        lane(producer).use { sender ->
            sender.send(first)
            sender.send(second)
        }
        val seen = receiver.socket().getInputStream().readBytes().joinToString("") { "%02x".format(it.toInt() and 255) }
        assertEquals("000000150000000000000000ff4cf254a965f55e05d2cde81cd0c87f07d170c8a0" +
            "0000001600000000000000012cf1d07d1ce098974a3ae945893a44699c661252d503", seen)
        assertTrue(first.jpeg.all { it == 0.toByte() } && second.jpeg.all { it == 0.toByte() })
    }

    @Test fun revokedOriginalAfterHeaderCannotSendBodyOrReuseTheChannel() = connected { producer, receiver ->
        var checks = 0
        val sender = lane(producer) { if (++checks >= 4) throw SecurityException("original revoked") }
        val original = frame("first")
        assertThrows(SecurityException::class.java) { sender.send(original) }
        val received = receiver.socket().getInputStream().readBytes()
        assertEquals(12, received.size)
        assertTrue(original.jpeg.all { it == 0.toByte() })
        assertFalse(producer.isOpen)
    }

    @Test fun wrongShapeIsTerminalBeforeWritingAndAlsoClearsFrame() = connected { producer, receiver ->
        val sender = lane(producer)
        val wrong = PhoneScreenJpegOutput.Frame(16, 16, 0, byteArrayOf(42))
        assertThrows(IllegalArgumentException::class.java) { sender.send(wrong) }
        assertEquals(-1, receiver.socket().getInputStream().read())
        assertArrayEquals(byteArrayOf(0), wrong.jpeg)
    }

    @Test fun socketProofMatchesLinuxChallengeAndDoesNotSendFrames() = connected { producer, receiver ->
        receiver.socket().getOutputStream().write(ByteArray(16) { (it + 16).toByte() })
        PhoneScreenViewLane.answerSocketProof(producer, ByteArray(16) { it.toByte() }, ByteArray(32) { it.toByte() },
            17, 16) {}
        producer.close()
        val seen = receiver.socket().getInputStream().readBytes().joinToString("") { "%02x".format(it.toInt() and 255) }
        assertEquals("8151fa3e157e140cde257828478f01b806cce5a5093a329c62e704f8b9ffbc8d", seen)
    }

    @Test fun originalConsentLostAfterChallengeDoesNotProduceProof() = connected { producer, receiver ->
        receiver.socket().getOutputStream().write(ByteArray(16) { (it + 16).toByte() })
        var checks = 0
        assertThrows(SecurityException::class.java) {
            PhoneScreenViewLane.answerSocketProof(producer, ByteArray(16) { it.toByte() }, ByteArray(32) { it.toByte() },
                17, 16) { if (++checks >= 3) throw SecurityException("consent withdrawn") }
        }
        assertEquals(-1, receiver.socket().getInputStream().read())
        assertFalse(producer.isOpen)
    }
}
