package io.gitlab.maik3531.magnolienotes.telefon

import android.app.Service
import android.os.SystemClock
import androidx.annotation.RequiresApi
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.channels.SocketChannel
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Native platform lifetime, not a serialized readiness/permission flag. */
internal interface PhoneWebcamCaptureDevice : AutoCloseable {
    fun start()
    fun isCompletelyStopped(): Boolean
}

/** Joins the genuine permission/foreground capture, private preparation, actual
 * bilateral data guard and original dedicated socket. No service is started by
 * construction, no target is chosen from a URL, and no fallback/reconnect exists.
 * The caller must pin expectedPeer to the REAL authenticated parent connection,
 * and must not use ordinary preferences as the dataAgreement guard.
 */
@RequiresApi(30)
internal class PhoneWebcamForegroundRun(private val permit: PhoneWebcamCapturePermit, secret: ByteArray,
    private val expectedPeer: InetAddress, private val originalControl: () -> Unit,
    private val dataAgreement: () -> Unit, private val prepared: () -> Unit,
    private val ended: (Throwable?) -> Unit,
    private val captureFactory: (Service, PhoneWebcamCapturePermit, (Boolean, Long, ByteArray) -> Unit, (Throwable?) -> Unit) -> PhoneWebcamCaptureDevice =
        { service, permission, sample, stopped -> PhoneWebcamAndroidCapture(service, permission, sample, stopped) }) : AutoCloseable {
    val session get() = permit.session
    val muted get() = permit.muted
    private val gate = Any()
    private val secret = secret.copyOf()
    private val started = AtomicBoolean(false)
    private val stopping = AtomicBoolean(false)
    private val completing = AtomicBoolean(false)
    private val preparedOnce = AtomicBoolean(false)
    private val failure = AtomicReference<Throwable?>()
    @Volatile private var initializing = false
    @Volatile private var capture: PhoneWebcamCaptureDevice? = null
    @Volatile private var lane: PhoneWebcamMediaLane? = null
    @Volatile private var writer: PhoneWebcamChannelWriter? = null
    val terminalFailure: Throwable? get() = failure.get()
    val isStopping get() = stopping.get()
    init { require(secret.size == 32) { "webcam_channel_context_invalid" } }

    internal fun requireVisibleStart() {
        check(!started.get() && !stopping.get()) { "webcam_foreground_run_already_used" }
        originalControl(); permit.requireVisibleStart()
    }
    fun isCapturePrepared() = !stopping.get() && lane?.isPrepared() == true
    internal fun abort(error: Throwable) { stop(error) }

    fun start(actualService: Service) {
        check(started.compareAndSet(false, true) && !stopping.get()) { "webcam_foreground_run_already_used" }
        initializing = true
        try {
            originalControl()
            val media = PhoneWebcamMediaLane(session, secret, muted,
                { originalControl(); check(!stopping.get()); permit.requireActive(actualService) },
                { originalControl(); dataAgreement(); check(writer != null && !stopping.get()) },
                SystemClock::elapsedRealtimeNanos,
                { bytes, current -> checkNotNull(writer) { "webcam_original_media_channel_required" }.write(bytes, current) },
                { interruptOriginalIo() }, { error -> stop(error) })
            lane = media
            secret.fill(0)
            capture = captureFactory(actualService, permit, { video, time, bytes ->
                media.offer(video, time, bytes)
                if (media.isPrepared() && preparedOnce.compareAndSet(false, true)) prepared()
            }, { error -> stop(error) })
            originalControl()
            check(!stopping.get()) { "webcam_foreground_run_retired" }
            checkNotNull(capture).start()
        } catch (error: Throwable) { stop(error); throw error }
        finally { initializing = false; if (stopping.get()) completeStop() }
    }

    /** Ownership transfers for this exact originally admitted channel only. */
    fun startSending(channel: SocketChannel) {
        var owned: PhoneWebcamChannelWriter? = null
        try {
            originalControl(); dataAgreement()
            check(started.get() && !stopping.get() && preparedOnce.get()) { "webcam_capture_not_prepared" }
            val remote = channel.remoteAddress as? InetSocketAddress
            check(channel.isConnected && remote?.address == expectedPeer) { "webcam_original_peer_address_required" }
            owned = PhoneWebcamChannelWriter(channel)
            synchronized(gate) {
                check(writer == null && !stopping.get()) { "webcam_original_media_channel_already_used" }
                writer = owned
            }
            checkNotNull(lane).activate()
        } catch (error: Throwable) {
            runCatching { owned?.close() ?: channel.close() }
            stop(error)
            throw error
        }
    }

    override fun close() { stop(null) }
    private fun stop(error: Throwable?) {
        if (error != null && !stopping.get()) failure.compareAndSet(null, error)
        stopping.set(true)
        permit.close(); secret.fill(0)
        lane?.close()
        interruptOriginalIo()
        completeStop()
    }
    private fun interruptOriginalIo() {
        // Nonblocking signals only; never wait for an IO/capture worker under
        // the caller's original control or Activity-result scope.
        runCatching { writer?.close() }.exceptionOrNull()?.let { failure.compareAndSet(null, it) }
        runCatching { capture?.close() }.exceptionOrNull()?.let { failure.compareAndSet(null, it) }
    }
    fun isCompletelyStopped(): Boolean = stopping.get() && !initializing &&
        (capture?.isCompletelyStopped() ?: true) && (lane?.awaitStopped(0) ?: true)

    private fun completeStop() {
        if (!completing.compareAndSet(false, true)) return
        Thread({
            val deadline = System.nanoTime() + 10_000_000_000L
            while (!isCompletelyStopped() && System.nanoTime() < deadline) Thread.sleep(25)
            if (!isCompletelyStopped()) failure.compareAndSet(null, IllegalStateException("webcam_native_shutdown_pending"))
            // This callback is NOT permission to free a global capture slot.
            // The service/controller must still inspect isCompletelyStopped().
            try { ended(failure.get()) }
            catch (observer: Exception) { failure.compareAndSet(null, observer) }
        }, "Magnolie webcam original shutdown").start()
    }
}
