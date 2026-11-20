package io.gitlab.maik3531.magnolienotes.telefon

import java.io.EOFException
import java.io.IOException
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.channels.SocketChannel
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.LockSupport
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Unadvertised draft receiver. The trusted caller owns the visible viewer,
 * original authenticated WLAN connection and matching SEND control receipt.
 * This lane never opens a connection, decodes or grants display permission. */
internal class DesktopScreenReceiveLane(
    private val socket: SocketChannel,
    session: ByteArray,
    secret: ByteArray,
    mode: Int,
    private val width: Int,
    private val height: Int,
    private val setupDeadlineNanos: Long,
    private val requireOriginal: () -> Unit,
) : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val context: ByteArray
    private val proofKey = ByteArray(32)
    private val key: SecretKeySpec
    private val prefix: ByteArray
    private var proof: ByteArray? = null
    private var receiving = false
    private var ordinal = 0L

    init {
        try {
            require(session.size == 16 && secret.size == 32 && mode in 1..2 &&
                width in 16..1920 && height in 16..1920 && width * height <= 1920 * 1080)
            context = DOMAIN + session + ByteBuffer.allocate(5).put(mode.toByte())
                .putShort(width.toShort()).putShort(height.toShort()).array()
            current(setupDeadlineNanos)
            check(socket.isConnected)
            socket.configureBlocking(false)
            val root = hmac(session, secret)
            try {
                val first = hmac(root, context + byteArrayOf(1))
                try {
                    key = SecretKeySpec(first, "AES")
                    val second = hmac(root, first + context + byteArrayOf(2))
                    try { prefix = second.copyOf(4) } finally { second.fill(0) }
                } finally { first.fill(0) }
            } finally { root.fill(0) }
            secret.copyInto(proofKey)
        } catch (failure: Exception) {
            retire(failure)
            throw failure
        }
    }

    /** One proof on this socket; returns only the digest to bind PREPARED. */
    @Synchronized fun prove(): ByteArray = guarded {
        check(proof == null)
        val now = System.nanoTime()
        val end = now + minOf(setupDeadlineNanos - now, IO_NS)
        current(end)
        val phone = ByteArray(16).also(SecureRandom()::nextBytes)
        transfer(ByteBuffer.wrap(phone), end, socket::write)
        val answer = read(48, end)
        val transcript = context + phone + answer.copyOf(16)
        try {
            check(MessageDigest.isEqual(answer.copyOfRange(16, 48), hmac(proofKey, PROOF + byteArrayOf(1) + transcript))) {
                "desktop_screen_desktop_proof_invalid"
            }
            val reply = hmac(proofKey, PROOF + byteArrayOf(2) + transcript)
            try { transfer(ByteBuffer.wrap(reply), end, socket::write) } finally { reply.fill(0) }
            current(end)
            val receipt = MessageDigest.getInstance("SHA-256").digest(transcript)
            proof = receipt
            receipt.copyOf()
        } finally { proofKey.fill(0) }
    }

    /** Call only after authenticated SEND for this exact prepared attempt. */
    @Synchronized fun activate(preparedTranscript: ByteArray) = guarded {
        current(setupDeadlineNanos)
        val original = checkNotNull(proof)
        check(!receiving && MessageDigest.isEqual(original, preparedTranscript)) { "desktop_screen_original_send_required" }
        receiving = true
    }

    /** Returns a bounded baseline JPEG candidate, or empty for a heartbeat.
     * The visible viewer must still verify the native decoder's result. */
    @Synchronized fun receive(): ByteArray = guarded {
        check(receiving) { "desktop_screen_original_send_required" }
        val end = System.nanoTime() + IO_NS
        current(end)
        val header = read(12, end)
        val fields = ByteBuffer.wrap(header)
        val size = fields.int
        check(fields.long == ordinal && ordinal < Long.MAX_VALUE && size in 16..MAX_JPEG_PLUS_TAG) {
            "desktop_screen_record_header_invalid"
        }
        val encrypted = read(size, end)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val nonce = ByteBuffer.allocate(12).put(prefix).putLong(ordinal).array()
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, nonce))
        cipher.updateAAD(context)
        cipher.updateAAD(header)
        val plaintext = cipher.doFinal(encrypted)
        try {
            current(end)
            if (plaintext.isNotEmpty()) requireDesktopScreenJpeg(plaintext, width, height)
            current(end)
        } catch (failure: Exception) { plaintext.fill(0); throw failure }
        ordinal++
        plaintext
    }

    private fun current(end: Long) {
        if (closed.get() || Thread.currentThread().isInterrupted) throw IOException("desktop_screen_receive_retired")
        requireOriginal()
        if (closed.get()) throw IOException("desktop_screen_receive_retired")
        if (System.nanoTime() - end >= 0) throw SocketTimeoutException("desktop_screen_receive_timeout")
    }

    private fun transfer(buffer: ByteBuffer, end: Long, operation: (ByteBuffer) -> Int) {
        while (buffer.hasRemaining()) {
            current(end)
            when (operation(buffer)) {
                -1 -> throw EOFException("desktop_screen_receive_eof")
                0 -> LockSupport.parkNanos(5_000_000L)
            }
        }
        current(end)
    }

    private fun read(size: Int, end: Long): ByteArray = ByteArray(size).also { transfer(ByteBuffer.wrap(it), end, socket::read) }

    private inline fun <T> guarded(action: () -> T): T = try { action() } catch (failure: Exception) {
        retire(failure)
        throw failure
    }

    private fun retire(failure: Exception) {
        try { close() } catch (cleanup: Exception) { if (cleanup !== failure) failure.addSuppressed(cleanup) }
    }

    override fun close() {
        // Closing the original socket may interrupt an active worker. The
        // caller must join that worker, not equate close with receiver drain.
        if (closed.compareAndSet(false, true)) {
            // Serial proof may observe a cleared key only during retirement;
            // all publication paths recheck the closed flag after I/O.
            proofKey.fill(0)
            socket.close()
        }
    }

    companion object {
        private const val IO_NS = 2_000_000_000L
        private const val MAX_JPEG_PLUS_TAG = 1_048_576 + 16
        private val DOMAIN = "magnolie-desktop-screen-send/1\u0000desktop_to_phone\u0000".toByteArray(Charsets.US_ASCII)
        private val PROOF = "magnolie-desktop-screen-proof/1\u0000".toByteArray(Charsets.US_ASCII)

        private fun hmac(key: ByteArray, body: ByteArray) = Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(key, "HmacSHA256"))
            doFinal(body)
        }
    }
}

/** Check dimensions before any Android bitmap allocation. This is a header
 * check, not a substitute for full native JPEG decoding. */
internal fun requireDesktopScreenJpeg(data: ByteArray, width: Int, height: Int) {
    fun byte(index: Int) = data[index].toInt() and 0xff
    fun u16(index: Int) = (byte(index) shl 8) or byte(index + 1)
    val end = data.size - 2
    require(data.size in 14..1_048_576 && u16(0) == 0xffd8 && u16(end) == 0xffd9)
    var at = 2
    var baseline = false
    while (at + 4 <= end && byte(at) == 0xff) {
        val marker = byte(at + 1)
        val length = u16(at + 2)
        val next = at + 2 + length
        require(length >= 2 && next <= end)
        when (marker) {
            0xc0 -> {
                require(!baseline && length == 17 && byte(at + 4) == 8 && byte(at + 9) == 3)
                require(u16(at + 5) == height && u16(at + 7) == width)
                baseline = true
            }
            0xda -> {
                require(baseline && length == 12 && byte(at + 4) == 3 && next < end)
                return
            }
            0xc4, 0xdb, 0xdd, 0xfe, in 0xe0..0xef -> Unit
            else -> break
        }
        at = next
    }
    throw IllegalArgumentException("desktop_screen_jpeg_header_invalid")
}
