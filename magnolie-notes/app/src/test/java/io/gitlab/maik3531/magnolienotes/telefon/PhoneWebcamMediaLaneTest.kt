package io.gitlab.maik3531.magnolienotes.telefon

import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.channels.ServerSocketChannel
import java.nio.channels.SocketChannel
import java.security.MessageDigest
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.*
import org.junit.Test

class PhoneWebcamMediaLaneTest {
    private val secret get() = ByteArray(32) { it.toByte() }
    private val audio get() = ByteArray(1920) { if (it % 2 == 0) 0x12 else 0x34 }
    private fun hash(data: ByteArray) = MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }
    private class Fixture(val muted: Boolean = false) : AutoCloseable {
        @Volatile var now = 1_066_667_000L
        @Volatile var capture = true
        @Volatile var agreement = false
        val packets = CopyOnWriteArrayList<ByteArray>()
        val interrupted = AtomicInteger()
        val two = CountDownLatch(2)
        val blocked = CountDownLatch(1)
        val release = CountDownLatch(1)
        var blockFirst = false
        val lane = PhoneWebcamMediaLane("a".repeat(32), ByteArray(32) { it.toByte() }, muted,
            { check(capture) { "original actual capture revoked" } }, { check(agreement) { "actual bilateral SEND missing" } }, { now },
            { bytes, current ->
                if (blockFirst && packets.isEmpty()) { blocked.countDown(); check(release.await(2, TimeUnit.SECONDS)) }
                current(); packets += bytes; two.countDown()
            }, { interrupted.incrementAndGet(); release.countDown() }, {})
        fun prepare() {
            lane.offer(true, 1_066_667_000, ByteArray(460800))
            if (!muted) lane.offer(false, 1_000_000_000, ByteArray(1920) { if (it % 2 == 0) 0x12 else 0x34 })
        }
        override fun close() { lane.close(); assertTrue(lane.awaitStopped(3_000)) }
    }

    @Test fun pendingPrivateCaptureSendsNothingUntilActualAgreementAndMatchesIndependentWireVectors() {
        Fixture().use { f ->
            f.prepare(); assertTrue(f.lane.isPrepared()); assertTrue(f.packets.isEmpty())
            f.agreement = true; f.lane.activate()
            assertTrue(f.two.await(2, TimeUnit.SECONDS))
            assertEquals("ac07c1baeaea58c00f70d794813f653e1409f865dc7363ecba9703612d0707e0", hash(f.packets[0]))
            assertEquals("8b253d9e1bf3129a3b7e3a1caa5aac9316cf9dc8a7348a71aca8e9c3f8ccaee3", hash(f.packets[1]))
        }
    }

    @Test fun capturePermissionAloneDoesNotSendOrReviveAfterAnAgreementDenial() {
        Fixture().use { f ->
            f.prepare()
            assertThrows(IllegalStateException::class.java) { f.lane.activate() }
            f.agreement = true
            assertThrows(IllegalStateException::class.java) { f.lane.activate() }
            assertTrue(f.packets.isEmpty()); assertEquals(1, f.interrupted.get())
        }
    }

    @Test fun revokedOriginalCaptureDuringReadinessStaysRetiredAfterPermissionReturns() {
        Fixture().use { f ->
            f.prepare(); f.capture = false
            assertThrows(IllegalStateException::class.java) { f.lane.isPrepared() }
            f.capture = true; f.agreement = true
            assertThrows(IllegalStateException::class.java) { f.lane.activate() }
            assertTrue(f.packets.isEmpty()); assertEquals(1, f.interrupted.get())
        }
    }

    @Test fun audioBackpressureStopsBothPathsInsteadOfSilentlyDroppingSamples() {
        Fixture().use { f ->
            f.prepare(); f.agreement = true; f.blockFirst = true; f.lane.activate()
            assertTrue(f.blocked.await(1, TimeUnit.SECONDS))
            for (index in 1..10) {
                f.now = 1_066_667_000L + index * 20_000_000L
                f.lane.offer(false, f.now, audio)
            }
            f.now += 20_000_000
            val error = assertThrows(IllegalStateException::class.java) { f.lane.offer(false, f.now, audio) }
            assertEquals("webcam_audio_backpressure", error.message)
            assertTrue(f.lane.awaitStopped(2_000))
            assertEquals(1, f.interrupted.get()); assertTrue(f.packets.isEmpty())
        }
    }

    @Test fun replacementOfWholeUnsentVideoFramesDoesNotAllocateMissingWireSequences() {
        Fixture().use { f ->
            f.prepare(); f.agreement = true; f.blockFirst = true; f.lane.activate()
            assertTrue(f.blocked.await(1, TimeUnit.SECONDS))
            f.now = 1_200_000_000
            f.lane.offer(true, 1_133_333_000, ByteArray(460800) { 4 })
            f.lane.offer(true, 1_200_000_000, ByteArray(460800) { 7 })
            f.release.countDown()
            assertTrue(f.two.await(2, TimeUnit.SECONDS))
            PhoneWebcamMediaCodec("a".repeat(32), secret) {}.use { reference ->
                assertArrayEquals(reference.encode(false, 0, 0, audio), f.packets[0])
                assertArrayEquals(reference.encode(true, 0, 200_000, ByteArray(460800) { 7 }), f.packets[1])
            }
        }
    }

    @Test fun defaultAudioRequirementAndExplicitMuteHaveDifferentActualReadiness() {
        Fixture().use { f ->
            f.lane.offer(true, f.now, ByteArray(460800))
            assertFalse(f.lane.isPrepared()); assertTrue(f.packets.isEmpty())
        }
        Fixture(muted = true).use { f ->
            f.prepare(); assertTrue(f.lane.isPrepared())
            assertThrows(IllegalStateException::class.java) { f.lane.offer(false, f.now, audio) }
        }
    }

    @Test fun delayedHeldFramesAreNotFreshReceiverReadinessAndCannotResetOriginalTime() {
        Fixture().use { f ->
            f.prepare(); f.now += 300_000_000
            assertFalse(f.lane.isPrepared())
            assertTrue(f.packets.isEmpty())
        }
    }

    @Test fun alreadyConnectedDedicatedSocketWritesBinaryPacketWithLiveGuardAndClosesOnRevocation() {
        ServerSocketChannel.open().use { listener ->
            listener.bind(InetSocketAddress("127.0.0.1", 0))
            SocketChannel.open(listener.localAddress).use { outgoing ->
                listener.accept().use { incoming ->
                    PhoneWebcamChannelWriter(outgoing).use { writer ->
                        val packet = PhoneWebcamMediaCodec("a".repeat(32), secret) {}.use { it.encode(false, 0, 0, audio) }
                        var calls = 0
                        writer.write(packet) { calls++ }
                        val result = ByteBuffer.allocate(packet.size)
                        while (result.hasRemaining()) assertTrue(incoming.read(result) > 0)
                        assertArrayEquals(packet, result.array()); assertTrue(calls >= 2)
                        assertThrows(IllegalStateException::class.java) { writer.write(packet) { error("original channel agreement revoked") } }
                        assertFalse(outgoing.isOpen)
                    }
                }
            }
        }
    }

    @Test fun activeSenderRechecksActualAgreementWithoutWaitingForAnotherCapturePacket() {
        Fixture().use { f ->
            f.prepare(); f.agreement = true; f.lane.activate()
            assertTrue(f.two.await(2, TimeUnit.SECONDS))
            f.agreement = false
            assertTrue(f.lane.awaitStopped(2_000))
            assertEquals("actual bilateral SEND missing", f.lane.terminalFailure?.message)
            f.agreement = true
            assertThrows(IllegalStateException::class.java) { f.lane.activate() }
            assertEquals(2, f.packets.size); assertEquals(1, f.interrupted.get())
        }
    }

    @Test fun unavailableDedicatedChannelIsNotReplacedByAnotherSocketOrRoute() {
        val channel = SocketChannel.open()
        assertThrows(IllegalStateException::class.java) { PhoneWebcamChannelWriter(channel) }
        assertFalse(channel.isOpen)
    }
}
