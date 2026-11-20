package io.gitlab.maik3531.magnolienotes.telefon

import java.io.IOException
import java.net.SocketTimeoutException
import java.nio.channels.SocketChannel
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.LockSupport

/** One approved viewer and one original data socket. Not a product dispatcher.
 * Native callers bind openOriginal to the authenticated WLAN endpoints, and
 * invoke acceptSend only for an authenticated control receipt from that parent.
 */
internal class DesktopScreenReceiveRun(
    private val parent: Any,
    session: ByteArray,
    secret: ByteArray,
    private val mode: Int,
    private val width: Int,
    private val height: Int,
    private val deadline: Long,
    private val requireViewerAndParent: () -> Unit,
    private val openOriginal: (() -> Unit) -> SocketChannel,
    private val writePrepared: (ByteArray, () -> Unit) -> Unit,
    private val present: (ByteArray) -> Unit,
    private val closeViewer: () -> Unit,
) : AutoCloseable {
    private val stopped = AtomicBoolean(false)
    private val gate = Any()
    private val session = session.copyOf()
    private val secret = secret.copyOf()
    private var socket: SocketChannel? = null
    private var armed: ByteArray? = null
    private var sendAccepted = false
    private var started = false
    private var cleanupConfirmed = true
    @Volatile private var transportActive = false
    @Volatile var failure: Exception? = null
        private set
    private val worker = Thread(::run, "magnolie-desktop-screen-receive").apply { isDaemon = true }

    init { require(session.size == 16 && secret.size == 32) }

    /** Constructing the draft run is inert. Start only after the native click. */
    fun start() {
        current()
        synchronized(gate) {
            check(!stopped.get() && !started) { "desktop_screen_receive_run_already_used" }
            worker.start()
            started = true
        }
    }

    fun acceptSend(actualParent: Any, transcript: ByteArray): Boolean {
        if (actualParent !== parent || transcript.size != 32 || stopped.get()) return false
        synchronized(gate) { if (armed == null || sendAccepted) return false }
        try { current() } catch (_: Exception) { close(); return false }
        synchronized(gate) {
            val original = armed ?: return false
            if (stopped.get() || sendAccepted || !MessageDigest.isEqual(original, transcript) ||
                System.nanoTime() - deadline >= 0) return false
            sendAccepted = true
        }
        LockSupport.unpark(worker)
        return true
    }

    private fun current() {
        if (stopped.get()) throw IOException("desktop_screen_receive_run_retired")
        requireViewerAndParent()
        if (stopped.get()) throw IOException("desktop_screen_receive_run_retired")
        if (!transportActive && System.nanoTime() - deadline >= 0) throw SocketTimeoutException("desktop_screen_receive_run_expired")
    }

    private fun run() {
        try {
            openOriginal(::current).use { data ->
                synchronized(gate) {
                    if (stopped.get()) throw IOException("desktop_screen_receive_run_retired")
                    socket = data
                }
                current()
                DesktopScreenReceiveLane(data, session, secret, mode, width, height, deadline, ::current).use { lane ->
                    secret.fill(0)
                    val proof = lane.prove()
                    // The original protected writer calls this guard at the
                    // write edge. An early SEND cannot skip the writer return.
                    writePrepared(proof.copyOf()) {
                        current()
                        synchronized(gate) {
                            if (stopped.get()) throw IOException("desktop_screen_receive_run_retired")
                            if (armed == null) armed = proof
                        }
                    }
                    current()
                    check(synchronized(gate) { armed === proof }) { "desktop_screen_prepared_not_written" }
                    while (true) {
                        current()
                        if (synchronized(gate) { sendAccepted }) break
                        LockSupport.parkNanos(5_000_000L)
                    }
                    lane.activate(proof)
                    current()
                    transportActive = true
                    while (true) {
                        current()
                        val bytes = lane.receive()
                        try {
                            current()
                            if (bytes.isNotEmpty()) present(bytes)
                        } finally { bytes.fill(0) }
                    }
                }
            }
        } catch (error: Exception) {
            if (!stopped.get()) failure = error
        } finally {
            secret.fill(0)
            close()
        }
    }

    override fun close() {
        if (!stopped.compareAndSet(false, true)) return
        val original = synchronized(gate) {
            armed = null
            if (!started) secret.fill(0)
            socket.also { socket = null }
        }
        try { original?.close() } catch (_: IOException) {
            synchronized(gate) { cleanupConfirmed = false }
        }
        LockSupport.unpark(worker)
        try { closeViewer() } catch (_: Exception) {
            synchronized(gate) { cleanupConfirmed = false }
        } finally { synchronized(gate) { stopFinished = true } }
    }

    private var stopFinished = false

    /** Receiver worker and its connection, not proof of native UI removal. */
    val drained: Boolean
        get() = synchronized(gate) { stopFinished && cleanupConfirmed && !worker.isAlive }
}
