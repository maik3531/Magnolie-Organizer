package io.gitlab.maik3531.magnolienotes.telefon

import java.io.EOFException
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.nio.channels.SocketChannel
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.LockSupport
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Open no arbitrary address: the only remote and local interface are those of
 * the authenticated original WLAN parent. The caller still owns consent and proof. */
internal fun openPhoneScreenWlanSocket(pipe: TelefonTcpRoehre, port: Int, requireOriginal: () -> Unit): SocketChannel {
    require(port in 1024..65535)
    fun current() {
        requireOriginal()
        pipe.pruefen()
        if (Thread.currentThread().isInterrupted) throw IOException("screen_socket_connect_interrupted")
    }
    current()
    val local = pipe.localAddress
    val remote = pipe.remoteAddress
    val data = SocketChannel.open()
    try {
        data.configureBlocking(false)
        data.bind(InetSocketAddress(local, 0))
        current()
        val deadline = System.nanoTime() + 2_000_000_000L
        if (!data.connect(InetSocketAddress(remote, port))) {
            while (true) {
                current()
                if (System.nanoTime() - deadline >= 0) throw SocketTimeoutException("screen_socket_connect_timeout")
                if (data.finishConnect()) break
                LockSupport.parkNanos(5_000_000L)
            }
        }
        current()
        check((data.remoteAddress as InetSocketAddress).address == remote && (data.localAddress as InetSocketAddress).address == local)
        return data
    } catch (failure: Exception) {
        try { data.close() } catch (cleanup: Exception) { if (cleanup !== failure) failure.addSuppressed(cleanup) }
        throw failure
    }
}

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
            context = context(session, secret, width, height)
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
    @Synchronized fun send(frame: PhoneScreenJpegOutput.Frame) = writeRecord(frame)

    /** An authenticated liveness record, never a frame or a new SEND decision. */
    @Synchronized fun heartbeat() = writeRecord(null)

    private fun writeRecord(frame: PhoneScreenJpegOutput.Frame?) {
        try {
            val end = System.nanoTime() + 2_000_000_000L
            current(end)
            val jpeg = frame?.jpeg ?: EMPTY
            require(ordinal < Long.MAX_VALUE && (frame == null || frame.width == width && frame.height == height &&
                jpeg.size in 1..PhoneScreenJpegOutput.MAX_FRAME_BYTES))
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
        } finally { frame?.jpeg?.fill(0) }
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
        private val EMPTY = ByteArray(0)
        private val PROOF_DOMAIN = "magnolie-phone-screen-proof/1\u0000".toByteArray(Charsets.US_ASCII)

        private fun context(session: ByteArray, secret: ByteArray, width: Int, height: Int): ByteArray {
            require(session.size == 16 && secret.size == 32 && width in 2..1920 && height in 2..1920 && width * height <= 1920 * 1080)
            return DOMAIN + session + ByteBuffer.allocate(4).putShort(width.toShort()).putShort(height.toShort()).array()
        }

        /** This only proves the original secret on this socket; it cannot authorize SEND. */
        fun answerSocketProof(socket: SocketChannel, session: ByteArray, secret: ByteArray, width: Int, height: Int,
            requireOriginal: () -> Unit) {
            try {
                val context = context(session, secret, width, height)
                val end = System.nanoTime() + 2_000_000_000L
                fun current() {
                    requireOriginal()
                    if (Thread.currentThread().isInterrupted) throw IOException("screen_socket_proof_interrupted")
                    if (System.nanoTime() - end >= 0) throw SocketTimeoutException("screen_socket_proof_timeout")
                }
                current()
                check(socket.isConnected)
                socket.configureBlocking(false)
                fun transfer(buffer: ByteBuffer, operation: (ByteBuffer) -> Int) {
                    while (buffer.hasRemaining()) {
                        current()
                        when (operation(buffer)) {
                            -1 -> throw EOFException("screen_socket_proof_disconnected")
                            0 -> LockSupport.parkNanos(5_000_000L)
                        }
                    }
                }
                val challenge = ByteBuffer.allocate(16)
                transfer(challenge, socket::read)
                val proof = hmac(secret, PROOF_DOMAIN + context + challenge.array())
                try { transfer(ByteBuffer.wrap(proof), socket::write); current() }
                finally { proof.fill(0) }
            } catch (failure: Exception) {
                try { socket.close() } catch (cleanup: Exception) { if (cleanup !== failure) failure.addSuppressed(cleanup) }
                throw failure
            }
        }

        private fun hmac(key: ByteArray, data: ByteArray) = Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(key, "HmacSHA256")); doFinal(data)
        }
    }
}
