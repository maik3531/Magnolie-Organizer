package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Application
import android.graphics.BitmapFactory
import android.graphics.Color
import android.view.Surface
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadow.api.Shadow
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class PhoneScreenJpegOutputTest {
    private class Input : PhoneScreenJpegOutput.Capture {
        override val surface: Surface = Shadow.newInstanceOf(Surface::class.java)
        val frames = LinkedBlockingQueue<ByteBuffer>()
        val calls = AtomicInteger()
        val closing = CountDownLatch(1)
        val release = CountDownLatch(1)
        var closeError: Exception? = null
        override fun withLatestFrame(read: (ByteBuffer, Int, Int) -> Unit) {
            calls.incrementAndGet()
            frames.poll()?.let { read(it, 4, 68) }
        }
        override fun close() {
            closing.countDown()
            check(release.await(4, TimeUnit.SECONDS))
            closeError?.let { throw it }
        }
    }

    private fun waitUntil(condition: () -> Boolean) {
        val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(4)
        while (!condition() && System.nanoTime() < until) Thread.sleep(10)
        assertTrue(condition())
    }

    @Test fun stripsRowPaddingWithoutReadingPastTheLastRow() {
        val source = ByteBuffer.wrap(byteArrayOf(99, 1, 2, 3, 4, 5, 6, 7, 8, 90, 91, 92, 93, 9, 10, 11, 12, 13, 14, 15, 16))
        source.position(1)
        val dest = IntArray(4)
        PhoneScreenJpegOutput.copyRgbaAsArgb(source, 4, 12, 2, 2, dest)
        assertEquals(1, source.position())
        assertArrayEquals(intArrayOf(0x04010203, 0x08050607, 0x0c090a0b, 0x100d0e0f), dest)
        source.limit(source.limit() - 1)
        assertThrows(IllegalArgumentException::class.java) { PhoneScreenJpegOutput.copyRgbaAsArgb(source, 4, 12, 2, 2, dest) }
        assertThrows(IllegalArgumentException::class.java) { PhoneScreenJpegOutput.copyRgbaAsArgb(source, 3, 12, 2, 2, dest) }
    }

    @Test fun rejectsOversizeJpegWithoutExposingTruncatedBytes() {
        val output = PhoneScreenJpegOutput.BoundedJpeg()
        val data = ByteArray(PhoneScreenJpegOutput.MAX_FRAME_BYTES) { 3 }
        output.write(data)
        assertEquals(data.size, output.size)
        output.write(7)
        assertTrue(output.overflow)
        assertThrows(IllegalStateException::class.java) { output.copy() }
        output.clear()
        output.write(9)
        assertArrayEquals(byteArrayOf(9), output.copy())
    }

    @Test fun controlledRgbaThroughActualJpegCodecAndDrainWaitsForRelease() {
        val input = Input()
        val accepted = LinkedBlockingQueue<PhoneScreenJpegOutput.Frame>()
        val output = PhoneScreenJpegOutput(16, 16, input, {}) { accepted.offer(it) }
        val rows = ByteBuffer.allocate(15 * 68 + 64)
        for (y in 0 until 16) for (x in 0 until 16) {
            rows.position(y * 68 + x * 4)
            rows.put(248.toByte()).put(12).put(35).put(255.toByte())
        }
        rows.rewind()
        input.frames.add(rows)
        output.start()
        try {
            val frame = checkNotNull(accepted.poll(4, TimeUnit.SECONDS)) { "no encoding output: ${output.failure}" }
            assertEquals(16, frame.width)
            assertEquals(16, frame.height)
            val decoded = checkNotNull(BitmapFactory.decodeByteArray(frame.jpeg, 0, frame.jpeg.size))
            try {
                val pixel = decoded.getPixel(8, 8)
                assertTrue("decoded RGB: ${Color.red(pixel)}, ${Color.green(pixel)}, ${Color.blue(pixel)}",
                    Color.red(pixel) >= 235 && Color.green(pixel) < 30 && Color.blue(pixel) < 55)
            } finally { decoded.recycle(); frame.jpeg.fill(0) }
            output.requestStop()
            assertTrue(input.closing.await(4, TimeUnit.SECONDS))
            assertFalse(output.isDrained())
        } finally { output.requestStop(); input.release.countDown() }
        waitUntil { output.isDrained() }
        assertNull(output.failure)
    }

    @Test fun guardDenialStopsProductionAndUnconfirmedCloseNeverReportsDrain() {
        val input = Input()
        val lost = IllegalStateException("original lost")
        val cue = IllegalStateException("controlled reader close failure")
        input.closeError = cue
        val output = PhoneScreenJpegOutput(16, 16, input, { throw lost }) { fail("no frame after guard failure"); false }
        output.start()
        try {
            waitUntil { output.failure === lost }
            assertEquals(0, input.calls.get())
            assertEquals(1L, input.closing.count) // Service still owns the display until stop.
            assertFalse(output.isDrained())
        } finally { output.requestStop(); input.release.countDown() }
        waitUntil { output.failure is PhoneScreenOutputCleanupException }
        assertSame(cue, output.failure?.cause)
        assertFalse(output.isDrained())
    }
}
