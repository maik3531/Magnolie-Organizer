package io.gitlab.maik3531.magnolienotes.telefon

import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.media.ImageReader
import android.os.SystemClock
import android.view.Surface
import java.io.OutputStream
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Standalone JPEGs: a slow consumer can drop a complete frame without
 * losing codec state. Only the original native transport may accept frames.
 * Its offer must be nonblocking (at most one pending frame) and independently
 * recheck current SEND authority before accepting or writing to the wire.
 * Nothing here opens sockets, writes files or enables a capability. */
internal class PhoneScreenJpegOutput(
    private val width: Int,
    private val height: Int,
    private val capture: Capture,
    private val requireOriginal: () -> Unit,
    private val offer: (Frame) -> Boolean,
) : PhoneScreenOutput {
    internal class Frame(val width: Int, val height: Int, val timestampNanos: Long, val jpeg: ByteArray)
    internal interface Capture : AutoCloseable {
        val surface: Surface
        fun withLatestFrame(read: (ByteBuffer, Int, Int) -> Unit)
    }

    override val surface: Surface = capture.surface
    private val stopSignal = CountDownLatch(1)
    private val stopped get() = stopSignal.count == 0L
    @Volatile private var released = false
    @Volatile override var failure: Exception? = null
        private set
    private val worker = Thread(::encode, "magnolie-screen-jpeg")

    fun start() = worker.start()

    override fun requestStop() = stopSignal.countDown()
    override fun isDrained() = released && !worker.isAlive

    private fun encode() {
        var bitmap: Bitmap? = null
        var packed: IntArray? = null
        var jpeg: BoundedJpeg? = null
        try {
            val pixels = IntArray(width * height).also { packed = it }
            val target = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).also { bitmap = it }
            val destination = BoundedJpeg().also { jpeg = it }
            while (!stopped) {
                requireOriginal()
                val started = SystemClock.elapsedRealtime()
                capture.withLatestFrame { buffer, pixelStride, rowStride ->
                    if (!stopped) {
                        copyRgbaAsArgb(buffer, pixelStride, rowStride, width, height, pixels)
                        encodeFrame(pixels, target, destination)
                    }
                }
                val pause = FRAME_INTERVAL_MS - (SystemClock.elapsedRealtime() - started)
                if (pause > 0) stopSignal.await(pause, TimeUnit.MILLISECONDS)
            }
        } catch (error: Exception) {
            if (!stopped) failure = error
        } catch (error: OutOfMemoryError) {
            failure = IllegalStateException("screen_output_buffers_unavailable", error)
        } finally {
            var teardown: Exception? = null
            fun clean(action: () -> Unit) {
                try { action() }
                catch (error: Exception) {
                    val first = teardown
                    if (first == null) teardown = error else if (first !== error) first.addSuppressed(error)
                }
            }
            clean { bitmap?.eraseColor(0); bitmap?.recycle() }
            clean { packed?.fill(0) }
            clean { jpeg?.clear() }
            // On failure, wait for the service to detach the virtual display
            // before closing its Surface. Stop carries no work to the UI thread.
            while (!stopped) {
                try { stopSignal.await() }
                catch (error: InterruptedException) { if (failure == null) failure = error }
            }
            clean { capture.close() }
            val error = teardown
            if (error == null) released = true
            else failure = PhoneScreenOutputCleanupException(error).also { problem -> failure?.let(problem::addSuppressed) }
        }
    }

    private fun encodeFrame(pixels: IntArray, bitmap: Bitmap, destination: BoundedJpeg) {
        bitmap.setPixels(pixels, 0, width, 0, 0, width, height)
        destination.clear()
        try {
            val encoded = bitmap.compress(Bitmap.CompressFormat.JPEG, 72, destination)
            if (destination.overflow) return // Drop an oversized still, never a partial JPEG.
            check(encoded && destination.size > 0) { "screen_jpeg_encoding_failed" }
            if (stopped) return
            requireOriginal()
            val frame = Frame(width, height, SystemClock.elapsedRealtimeNanos(), destination.copy())
            var accepted = false
            try { if (!stopped) accepted = offer(frame) }
            finally { if (!accepted) frame.jpeg.fill(0) }
        } finally { destination.clear() }
    }

    companion object {
        internal const val MAX_FRAME_BYTES = 1_048_576
        private const val FRAME_INTERVAL_MS = 83L
        internal fun open(width: Int, height: Int, requireOriginal: () -> Unit, offer: (Frame) -> Boolean): PhoneScreenJpegOutput {
            require(width in 2..1920 && height in 2..1920 && width * height <= 1920 * 1080)
            requireOriginal()
            val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
            try {
                val capture = object : Capture {
                    override val surface get() = reader.surface
                    override fun withLatestFrame(read: (ByteBuffer, Int, Int) -> Unit) {
                        reader.acquireLatestImage()?.use { image ->
                            check(image.format == PixelFormat.RGBA_8888 && image.width == width && image.height == height)
                            val plane = image.planes.single()
                            read(plane.buffer, plane.pixelStride, plane.rowStride)
                        }
                    }
                    override fun close() = reader.close()
                }
                val output = PhoneScreenJpegOutput(width, height, capture, requireOriginal, offer)
                output.start()
                return output
            } catch (error: Exception) {
                try { reader.close() }
                catch (cleanup: Exception) { throw PhoneScreenOutputCleanupException(cleanup).also { it.addSuppressed(error) } }
                throw error
            }
        }

        internal fun copyRgbaAsArgb(src: ByteBuffer, pixelStride: Int, rowStride: Int, width: Int, height: Int, dst: IntArray) {
            require(width in 1..1920 && height in 1..1920)
            val rowBytes = width * 4
            val start = src.position()
            require(pixelStride == 4 && rowStride >= rowBytes && dst.size >= width * height)
            require(rowStride.toLong() * (height - 1) + rowBytes <= src.remaining()) { "screen_image_plane_truncated" }
            // Read the Android plane's declared RGBA bytes, not the host's
            // Bitmap storage order (which need not match RGBA).
            val row = src.duplicate().order(java.nio.ByteOrder.BIG_ENDIAN)
            var index = 0
            repeat(height) { y ->
                row.position(start + y * rowStride)
                repeat(width) { dst[index++] = Integer.rotateRight(row.int, 8) }
            }
        }
    }

    internal class BoundedJpeg : OutputStream() {
        private val payload = ByteArray(MAX_FRAME_BYTES)
        var size = 0
            private set
        var overflow = false
            private set

        override fun write(value: Int) {
            if (reserve(1)) payload[size++] = value.toByte()
        }
        override fun write(bytes: ByteArray, offset: Int, length: Int) {
            require(offset >= 0 && length >= 0 && offset <= bytes.size - length)
            if (reserve(length)) { bytes.copyInto(payload, size, offset, offset + length); size += length }
        }
        private fun reserve(length: Int): Boolean {
            if (overflow || length > payload.size - size) { overflow = true; return false }
            return true
        }
        fun copy(): ByteArray { check(!overflow); return payload.copyOf(size) }
        fun clear() { payload.fill(0, 0, size); size = 0; overflow = false }
    }
}
