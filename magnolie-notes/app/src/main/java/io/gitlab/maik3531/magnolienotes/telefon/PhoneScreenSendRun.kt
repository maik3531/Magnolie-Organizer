package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import java.net.SocketTimeoutException
import java.nio.channels.SocketChannel
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** One original proof/SEND/socket/slot lifetime. The native control owner supplies
 * an already connected owned socket and a capture guard for the genuine original
 * active projection (including lock and disconnect). `hasOriginalSend` must check
 * the exact live authenticated control decision, not a persisted/renderer flag.
 * Neither this worker nor its constructor can make that decision or start capture. */
internal class PhoneScreenSendRun(
    private val socket: SocketChannel,
    session: ByteArray,
    secret: ByteArray,
    private val width: Int,
    private val height: Int,
    private val pending: PhoneScreenFrameSlot,
    private val requireCapture: () -> Unit,
    private val hasOriginalSend: () -> Boolean,
) : AutoCloseable {
    private val session = session.copyOf()
    private val secret = secret.copyOf()
    private val stop = CountDownLatch(1)
    private val gate = Any()
    private var started = false
    private val worker = Thread(::send, "magnolie-phone-screen-send")
    @Volatile var failure: Exception? = null
        private set
    @Volatile var cleanupError: Exception? = null
        private set

    fun start() = synchronized(gate) {
        check(!started && !stopped()) { "screen_sender_already_used" }
        started = true
        try { worker.start() }
        catch (error: Exception) { started = false; close(); throw error }
    }

    private fun stopped() = stop.count == 0L

    private fun current() {
        if (stopped()) throw IOException("screen_sender_stopped")
        pending.requireOpen()
        requireCapture()
        if (stopped()) throw IOException("screen_sender_stopped")
    }

    private fun sendCurrent() {
        current()
        if (!hasOriginalSend()) throw SecurityException("screen_original_send_withdrawn")
    }

    private fun send() {
        try {
            check(pending.matchesSize(width, height)) { "screen_original_frame_slot_shape" }
            PhoneScreenViewLane.answerSocketProof(socket, session, secret, width, height, ::current)
            val untilSend = System.nanoTime() + 5_000_000_000L
            while (true) {
                current()
                if (hasOriginalSend()) break
                if (System.nanoTime() - untilSend >= 0) throw SocketTimeoutException("screen_original_send_timeout")
                stop.await(20, TimeUnit.MILLISECONDS)
            }
            PhoneScreenViewLane(socket, session, secret, width, height, ::sendCurrent).use { lane ->
                secret.fill(0)
                while (true) {
                    sendCurrent()
                    val frame = pending.take()
                    if (frame != null) lane.send(frame)
                    else stop.await(20, TimeUnit.MILLISECONDS)
                }
            }
        } catch (error: Exception) {
            if (!stopped()) failure = error
        } finally {
            secret.fill(0)
            close()
        }
    }

    override fun close() = synchronized(gate) {
        if (stopped()) return@synchronized
        stop.countDown()
        pending.close()
        if (!started) secret.fill(0)
        try { socket.close() } catch (error: IOException) { cleanupError = error }
    }

    fun isDrained() = synchronized(gate) { stopped() && !worker.isAlive && cleanupError == null }
}
