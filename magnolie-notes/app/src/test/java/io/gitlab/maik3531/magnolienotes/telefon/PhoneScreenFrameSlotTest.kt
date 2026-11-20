package io.gitlab.maik3531.magnolienotes.telefon

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class PhoneScreenFrameSlotTest {
    private fun jpeg(time: Long, width: Int = 17, height: Int = 16, size: Int = 256) =
        PhoneScreenJpegOutput.Frame(width, height, time, ByteArray(size) { 7 })

    @Test fun newestFrameWinsAndDisplacedBytesAreCleared() {
        PhoneScreenFrameSlot(17, 16).use { slot ->
            assertNull(slot.take())
            val first = jpeg(0)
            val next = jpeg(1)
            assertTrue(slot.offer(first))
            assertTrue(slot.offer(next))
            assertTrue(first.jpeg.all { it == 0.toByte() })
            assertSame(next, slot.take())
            assertNull(slot.take())
            val equal = jpeg(1)
            assertFalse(slot.offer(equal))
            assertTrue(equal.jpeg.all { it == 7.toByte() })
        }
    }

    @Test fun rejectedFramesStayWithProducerAndTerminalCloseDoesNotClearTakenBytes() {
        val slot = PhoneScreenFrameSlot(17, 16)
        for (invalid in listOf(jpeg(-1), jpeg(1, 16), jpeg(1, height = 17), jpeg(1, size = 0),
            jpeg(1, size = PhoneScreenJpegOutput.MAX_FRAME_BYTES + 1))) assertFalse(slot.offer(invalid))
        val original = jpeg(1)
        assertTrue(slot.offer(original))
        assertFalse(slot.offer(PhoneScreenJpegOutput.Frame(17, 16, 2, original.jpeg)))
        assertSame(original, slot.take())
        val pending = jpeg(2)
        assertTrue(slot.offer(pending))
        slot.close(); slot.close()
        assertTrue(pending.jpeg.all { it == 0.toByte() })
        assertTrue(original.jpeg.all { it == 7.toByte() })
        assertFalse(slot.offer(jpeg(3)))
        assertNull(slot.take())
    }

    @Test fun closeRacingWithProducerAndConsumerNeverReturnsPartialOrAlreadyClearedFrame() {
        val slot = PhoneScreenFrameSlot(17, 16)
        val frames = Array(500) { jpeg(it.toLong()) }
        val entered = CountDownLatch(1)
        val produced = CountDownLatch(1)
        val finished = CountDownLatch(2)
        val invalid = AtomicInteger()
        val accepted = BooleanArray(frames.size)
        thread(name = "screen-test-producer") {
            try {
                entered.await()
                for ((index, frame) in frames.withIndex()) {
                    accepted[index] = slot.offer(frame)
                    if (index == 0) produced.countDown()
                }
            } finally { finished.countDown() }
        }
        thread(name = "screen-test-consumer") {
            try {
                entered.await()
                repeat(frames.size) {
                    slot.take()?.let {
                        if (it.jpeg.any { b -> b != 7.toByte() }) invalid.incrementAndGet()
                        it.jpeg.fill(0)
                    }
                }
            } finally { finished.countDown() }
        }
        entered.countDown()
        try { assertTrue(produced.await(4, TimeUnit.SECONDS)) }
        finally { slot.close() }
        assertTrue(finished.await(4, TimeUnit.SECONDS))
        assertEquals(0, invalid.get())
        assertNull(slot.take())
        for ((index, frame) in frames.withIndex()) assertTrue(frame.jpeg.all { it == (if (accepted[index]) 0 else 7).toByte() })
    }
}
