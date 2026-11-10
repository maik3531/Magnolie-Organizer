package io.gitlab.maik3531.magnolienotes.telefon

import java.nio.ByteBuffer
import java.nio.channels.SelectionKey
import java.nio.channels.Selector
import java.nio.channels.SocketChannel
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Bounded capture → encrypted binary output. Capture and bilateral SEND are
 * deliberately separate guards: foreground/OS capture consent is not wire SEND.
 * Pending before the real receiver-ready agreement retains only the newest
 * private sample per track; it sends nothing. Active audio never silently drops.
 * Native callers must bind both guards to their original actual session owners.
 */
internal class PhoneWebcamMediaLane(private val session: String, secret: ByteArray, private val muted: Boolean,
    private val captureCurrent: () -> Unit, private val sendCurrent: () -> Unit,
    private val bootTimeNanos: () -> Long,
    private val packet: (bytes: ByteArray, current: () -> Unit) -> Unit,
    private val interruptIo: () -> Unit, private val ended: (Throwable?) -> Unit) : AutoCloseable {
    private data class Sample(val video: Boolean, val time: Long, val bytes: ByteArray)
    private val gate = Object()
    private val secret = secret.copyOf()
    private var video: Sample? = null
    private val audio = ArrayDeque<Sample>()
    private var epoch = 0L
    private var videoSequence = 0L
    private var audioSequence = 0L
    private var previousVideo = -1L
    private var previousAudio = -1L
    @Volatile private var active = false
    @Volatile private var closed = false
    @Volatile private var failure: Throwable? = null
    private var worker: Thread? = null
    private val done = CountDownLatch(1)
    val terminalFailure: Throwable? get() = failure
    init { require(Regex("[0-9a-f]{32}").matches(session) && secret.size == 32) { "webcam_channel_context_invalid" } }

    /** Ownership of the new capture buffer transfers to this bounded lane. */
    fun offer(video: Boolean, time: Long, bytes: ByteArray) {
        try {
            captureCurrent()
            check(!closed) { "webcam_media_lane_retired" }
            require(bytes.size == if (video) PhoneWebcamMediaCodec.VIDEO_BYTES else PhoneWebcamMediaCodec.AUDIO_BYTES) { "webcam_packet_invalid" }
            check(video || !muted) { "webcam_muted_audio_rejected" }
            fresh(time)
            synchronized(gate) {
                check(!closed) { "webcam_media_lane_retired" }
                check(time > if (video) previousVideo else previousAudio) { "webcam_capture_timestamp_stale" }
                if (video) {
                    previousVideo = time
                    this.video = Sample(true, time, bytes) // Only whole unsent video frames may be replaced.
                } else {
                    previousAudio = time
                    if (!active) audio.clear() // Private startup warmup, before any streaming epoch.
                    check(audio.size < 10) { "webcam_audio_backpressure" }
                    audio.addLast(Sample(false, time, bytes))
                }
                gate.notifyAll()
            }
        } catch (error: Throwable) { retire(error); throw error }
    }

    fun isPrepared(): Boolean {
        try {
            captureCurrent()
            synchronized(gate) {
                if (closed || video == null || !muted && audio.isEmpty()) return false
                val image = video!!
                val sound = audio.peekLast()
                val now = bootTimeNanos()
                return now >= image.time && now - image.time <= MAX_AGE &&
                    (muted || sound != null && now >= sound.time && now - sound.time <= MAX_AGE &&
                        kotlin.math.abs(sound.time - image.time) <= MAX_AGE)
            }
        } catch (error: Throwable) { retire(error); throw error }
    }

    /** Call only for the original authenticated receiver-ready data agreement,
     * NOT merely an enabled preference or Android permission result. */
    fun activate() {
        try {
            captureCurrent(); sendCurrent()
            check(isPrepared()) { "webcam_capture_not_prepared" }
            synchronized(gate) {
                check(!closed && !active) { "webcam_media_start_already_used" }
                epoch = minOf(video!!.time, if (muted) video!!.time else checkNotNull(audio.peekLast()).time)
                active = true
                worker = Thread(::send, "Magnolie webcam binary sender").also { it.start() }
            }
        } catch (error: Throwable) { retire(error); throw error }
    }

    private fun fresh(time: Long) {
        val now = bootTimeNanos()
        check(time > 0 && now >= time && now - time <= MAX_AGE) { "webcam_capture_sample_expired" }
    }
    private fun requireSend() {
        check(!closed) { "webcam_media_lane_retired" }
        captureCurrent(); sendCurrent.invoke()
        check(!closed) { "webcam_media_lane_retired" }
    }
    private fun send() {
        var codec: PhoneWebcamMediaCodec? = null
        try {
            val material = synchronized(gate) { check(!closed); secret.copyOf() }
            try { codec = PhoneWebcamMediaCodec(session, material, ::requireSend) }
            finally { material.fill(0) }
            while (!closed) {
                requireSend()
                val next = synchronized(gate) {
                    val image = video
                    val sound = audio.peekFirst()
                    when {
                        closed -> null
                        sound != null && (image == null || sound.time <= image.time) -> audio.removeFirst()
                        image != null -> image.also { video = null }
                        else -> { gate.wait(100); null }
                    }
                } ?: continue
                fresh(next.time)
                val sequence = if (next.video) videoSequence++ else audioSequence++
                val pts = (next.time - epoch) / 1_000
                check(pts >= 0) { "webcam_capture_clock_changed" }
                packet(codec.encode(next.video, sequence, pts, next.bytes), ::requireSend)
                requireSend()
            }
        } catch (error: Throwable) { if (!closed) retire(error) }
        finally { codec?.close(); synchronized(gate) { secret.fill(0) }; notifyEnded() }
    }

    override fun close() { retire(null) }
    private fun retire(error: Throwable?) {
        val notify = synchronized(gate) {
            if (closed) return
            closed = true; failure = error
            video = null; audio.clear(); secret.fill(0); gate.notifyAll()
            worker == null
        }
        try { interruptIo() }
        catch (cleanup: Exception) { if (failure == null) failure = cleanup else if (failure !== cleanup) failure!!.addSuppressed(cleanup) }
        if (notify) notifyEnded()
    }
    private fun notifyEnded() {
        try { ended(failure) }
        catch (observer: Exception) { if (failure == null) failure = observer else if (failure !== observer) failure!!.addSuppressed(observer) }
        finally { done.countDown() }
    }
    fun awaitStopped(timeoutMs: Long): Boolean {
        require(timeoutMs in 0..10_000)
        val deadline = System.nanoTime() + timeoutMs * 1_000_000
        if (!done.await(timeoutMs, TimeUnit.MILLISECONDS)) return false
        val thread = synchronized(gate) { worker }
        if (thread != null && thread !== Thread.currentThread()) {
            val remaining = deadline - System.nanoTime()
            if (remaining > 0) thread.join(maxOf(1, remaining / 1_000_000))
            return !thread.isAlive
        }
        return thread == null
    }
    companion object { private const val MAX_AGE = 250_000_000L }
}

/** One already-connected, originally admitted dedicated channel. No listener,
 * address selection, reconnect, document JSON or default network side effects. */
internal class PhoneWebcamChannelWriter(private val channel: SocketChannel) : AutoCloseable {
    private val selector: Selector
    init {
        var opened: Selector? = null
        try {
            opened = Selector.open()
            check(channel.isConnected) { "webcam_original_connected_channel_required" }
            channel.configureBlocking(false); channel.register(opened, SelectionKey.OP_WRITE)
            selector = opened
        } catch (error: Throwable) { try { channel.close() } finally { opened?.close() }; throw error }
    }
    @Synchronized fun write(bytes: ByteArray, current: () -> Unit) {
        val deadline = System.nanoTime() + 2_000_000_000L
        try {
            require(bytes.size == 46 + PhoneWebcamMediaCodec.AUDIO_BYTES || bytes.size == 46 + PhoneWebcamMediaCodec.VIDEO_BYTES) { "webcam_encoded_packet_invalid" }
            val buffer = ByteBuffer.wrap(bytes)
            while (buffer.hasRemaining()) {
                current()
                check(System.nanoTime() < deadline) { "webcam_media_write_timeout" }
                if (channel.write(buffer) == 0) { selector.select(100); selector.selectedKeys().clear() }
            }
            current()
        } catch (error: Throwable) { close(); throw error }
    }
    override fun close() { try { channel.close() } finally { selector.wakeup(); selector.close() } }
}
