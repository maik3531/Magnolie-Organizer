package io.gitlab.maik3531.magnolienotes.telefon

import java.io.EOFException
import java.io.IOException
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.channels.SocketChannel
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.LockSupport
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Send-only data lane. Caller must supply the original peer-bound socket,
 * fresh context and live SEND guard; this class never starts capture. */
internal class PhoneScreenViewLane(
    private val socket: SocketChannel,
    session: ByteArray,
    secret: ByteArray,
    private val width: Int,
    private val height: Int,
    private val requireOriginal: () -> Unit,
) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val context: ByteArray
    private val key: SecretKeySpec
    private val prefix: ByteArray
    private var ordinal = 0L

    init {
        try {
            require(session.size == 16 && secret.size == 32 && width in 2..1920 && height in 2..1920 && width * height <= 1920 * 1080)
            context = DOMAIN + session + ByteBuffer.allocate(4).putShort(width.toShort()).putShort(height.toShort()).array()
            val root = hmac(session, secret)
            try {
                val first = hmac(root, context + byteArrayOf(1))
                try {
                    key = SecretKeySpec(first, "AES")
                    val second = hmac(root, first + context + byteArrayOf(2))
                    try { prefix = second.copyOf(4) } finally { second.fill(0) }
                } finally { first.fill(0) }
            } finally { root.fill(0) }
            requireOriginal()
            check(socket.isConnected)
            socket.configureBlocking(false)
        } catch (failure: Exception) {
            retire(failure)
            throw failure
        }
    }

    /** Takes ownership of a unique frame from the original pending slot. */
    @Synchronized fun send(frame: PhoneScreenJpegOutput.Frame) {
        try {
            val end = System.nanoTime() + 2_000_000_000L
            current(end)
            val jpeg = frame.jpeg
            require(ordinal < Long.MAX_VALUE && frame.width == width && frame.height == height &&
                jpeg.size in 1..PhoneScreenJpegOutput.MAX_FRAME_BYTES)
            val header = ByteBuffer.allocate(12).putInt(jpeg.size + 16).putLong(ordinal).array()
            val nonce = ByteBuffer.allocate(12).put(prefix).putLong(ordinal).array()
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce))
            cipher.updateAAD(context)
            cipher.updateAAD(header)
            val encrypted = cipher.doFinal(jpeg)
            write(ByteBuffer.wrap(header), end)
            write(ByteBuffer.wrap(encrypted), end)
            current(end)
            ordinal++
        } catch (failure: Exception) {
            retire(failure)
            throw failure
        } finally { frame.jpeg.fill(0) }
    }

    private fun current(end: Long) {
        if (closed.get()) throw IOException("screen_lane_closed")
        if (Thread.currentThread().isInterrupted) throw IOException("screen_lane_interrupted")
        requireOriginal()
        if (System.nanoTime() - end >= 0) throw SocketTimeoutException("screen_lane_record_timeout")
    }

    private fun write(data: ByteBuffer, end: Long) {
        while (data.hasRemaining()) {
            current(end)
            when (socket.write(data)) {
                -1 -> throw EOFException("screen_lane_disconnected")
                0 -> LockSupport.parkNanos(5_000_000L)
            }
        }
    }

    private fun retire(failure: Exception) {
        try { close() } catch (cleanup: Exception) { if (cleanup !== failure) failure.addSuppressed(cleanup) }
    }

    override fun close() { if (closed.compareAndSet(false, true)) socket.close() }

    companion object {
        private val DOMAIN = "magnolie-phone-screen-view/1\u0000phone_to_desktop\u0000".toByteArray(Charsets.US_ASCII)
        private fun hmac(key: ByteArray, data: ByteArray) = Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(key, "HmacSHA256")); doFinal(data)
        }
    }
}
